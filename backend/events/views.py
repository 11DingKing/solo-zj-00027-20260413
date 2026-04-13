# SPDX-License-Identifier: AGPL-3.0-or-later
"""
API views for event management.
"""

import logging
import os
import re
from typing import Any, Sequence, Type
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.db.utils import IntegrityError, OperationalError
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from icalendar import Calendar
from icalendar import Event as ICalEvent
from rest_framework import status, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import (
    AllowAny,
    IsAuthenticated,
    IsAuthenticatedOrReadOnly,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from authentication.models import UserModel
from core.paginator import CustomPagination
from core.permissions import IsAdminStaffCreatorOrReadOnly
from events.filters import EventFilters
from events.models import (
    Event,
    EventAttendee,
    EventAttendeeStatus,
    EventFaq,
    EventFlag,
    EventResource,
    EventSocialLink,
    EventText,
    Notification,
)
from events.serializers import (
    EventFaqSerializer,
    EventFlagSerializers,
    EventPOSTSerializer,
    EventRegistrationResponseSerializer,
    EventRegistrationSerializer,
    EventResourceSerializer,
    EventSerializer,
    EventSocialLinkSerializer,
    EventTextSerializer,
    NotificationSerializer,
)

logger = logging.getLogger("django")

# MARK: API


class EventAPIView(GenericAPIView[Event]):
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    pagination_class = CustomPagination
    filterset_class = EventFilters
    filter_backends = [DjangoFilterBackend]
    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self) -> QuerySet[Event]:
        queryset = super().get_queryset().order_by("id")

        # E2E: only in development or CI — put activist_0's events last so
        # member permission tests (open first event, assert no add/edit) are deterministic.
        apply_e2e_ordering = (
            os.environ.get("ENVIRONMENT") == "development"
            or os.environ.get("CI") == "true"
        )
        e2e_member = (
            UserModel.objects.filter(username="activist_0").first()
            if apply_e2e_ordering
            else None
        )
        if e2e_member is not None:
            queryset = queryset.annotate(
                _e2e_last=Case(
                    When(created_by=e2e_member, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            ).order_by("_e2e_last", "id")

        if os.environ.get("ENVIRONMENT") != "development":
            return queryset

        dev_sync_match = Q(name__iexact="activist dev sync")
        qs = queryset.annotate(
            _priority=Case(
                When(dev_sync_match, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        if e2e_member is not None:
            return qs.order_by("_e2e_last", "_priority", "id")
        return qs.order_by("_priority", "id")

    def get_permissions(self) -> Sequence[Any]:
        if self.request.method == "POST":
            return [IsAuthenticated()]
        return [IsAuthenticatedOrReadOnly()]

    def get_serializer_class(self) -> Type[EventPOSTSerializer | EventSerializer]:
        if self.request.method == "POST":
            return EventPOSTSerializer

        return EventSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="topics",
                type=OpenApiTypes.STR,
                many=True,
                description="Filter by topic type (e.g. from Topic.model type).",
            ),
        ],
        responses={200: EventSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.serializer_class(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.serializer_class(queryset, many=True)
        return Response(serializer.data)

    @extend_schema(
        request=EventPOSTSerializer,
        responses={
            201: EventPOSTSerializer,
            400: OpenApiResponse(response={"detail": "Failed to create event."}),
        },
    )
    def post(self, request: Request) -> Response:
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        validated_data["created_by"] = request.user

        try:
            event = serializer.save()
            logger.info(f"Event created by user {request.user.id}")

        except ValidationError as e:
            logger.exception(
                f"Validation failed for event creation by user {request.user.id}: {e}"
            )
            return Response(
                {"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = EventSerializer(event)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


# MARK: Detail API


class EventDetailAPIView(APIView):
    queryset = Event.objects.all()
    serializer_class = EventSerializer

    @extend_schema(
        responses={
            200: EventSerializer,
            400: OpenApiResponse(response={"detail": "Event ID is required."}),
            404: OpenApiResponse(response={"detail": "Event Not Found."}),
        }
    )
    def get(self, request: Request, id: None | UUID = None) -> Response:
        if id is None:
            return Response(
                {"detail": "Event ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = self.queryset.get(id=id)
            serializer = self.serializer_class(event)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Event.DoesNotExist as e:
            logger.exception(f"Event with id {id} does not exist for get: {e}")
            return Response(
                {"detail": "Event Not Found."},
                status=status.HTTP_404_NOT_FOUND,
            )

    @extend_schema(
        responses={
            200: EventSerializer,
            400: OpenApiResponse(response={"detail": "Event ID is required."}),
            401: OpenApiResponse(response={"detail": "User not authorized."}),
            404: OpenApiResponse(response={"detail": "Event Not Found."}),
        }
    )
    def put(self, request: Request, id: None | UUID = None) -> Response:
        if id is None:
            return Response(
                {"detail": "Event ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = self.queryset.get(id=id)

        except Event.DoesNotExist as e:
            logger.exception(f"Event with id {id} does not exist for update: {e}")
            return Response(
                {"detail": "Event Not Found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.user != event.created_by:
            return Response(
                {"detail": "User not authorized."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = self.serializer_class(event, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={
            200: OpenApiResponse(response={"message": "Event deleted successfully."}),
            400: OpenApiResponse(response={"detail": "Event ID is required."}),
            401: OpenApiResponse(response={"detail": "User not authorized."}),
            404: OpenApiResponse(response={"detail": "Event Not Found."}),
        }
    )
    def delete(self, request: Request, id: None | UUID = None) -> Response:
        if id is None:
            return Response(
                {"detail": "Event ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = self.queryset.get(id=id)

        except Event.DoesNotExist as e:
            logger.exception(f"Event with id {id} does not exist for delete: {e}")
            return Response(
                {"detail": "Event Not Found."}, status=status.HTTP_404_NOT_FOUND
            )

        if request.user != event.created_by:
            return Response(
                {"detail": "User not authorized."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        event.delete()
        return Response(
            {"message": "Event deleted successfully."},
            status=status.HTTP_204_NO_CONTENT,
        )


# MARK: Flag


class EventFlagAPIView(GenericAPIView[EventFlag]):
    queryset = EventFlag.objects.all()
    serializer_class = EventFlagSerializers
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: EventFlagSerializers(many=True)})
    def get(self, request: Request) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={
            201: EventFlagSerializers,
            400: OpenApiResponse(response={"detail": "Failed to create flag."}),
        }
    )
    def post(self, request: Request) -> Response:
        serializer_class = self.get_serializer_class()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            serializer.save(created_by=request.user)
            logger.info(f"Event flag created by user {request.user.id}")

        except (IntegrityError, OperationalError) as e:
            logger.exception(
                f"Failed to create event flag for user {request.user.id}: {e}"
            )
            return Response(
                {"detail": "Failed to create flag."}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(serializer.data, status=status.HTTP_201_CREATED)


# MARK: Flag Detail


class EventFlagDetailAPIView(GenericAPIView[EventFlag]):
    queryset = EventFlag.objects.all()
    serializer_class = EventFlagSerializers
    permission_classes = [IsAdminStaffCreatorOrReadOnly]

    @extend_schema(
        responses={
            200: EventFlagSerializers,
            404: OpenApiResponse(
                response={"detail": "Failed to retrieve the event flag."}
            ),
        }
    )
    def get(self, request: Request, id: UUID | str) -> Response:
        try:
            flag = EventFlag.objects.get(id=id)

        except EventFlag.DoesNotExist as e:
            logger.exception(f"EventFlag with id {id} does not exist for get: {e}")
            return Response(
                {"detail": "Failed to retrieve the flag."},
                status=status.HTTP_404_NOT_FOUND,
            )

        self.check_object_permissions(request, flag)

        serializer = EventFlagSerializers(flag)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(
        responses={
            204: OpenApiResponse(response={"message": "Flag deleted successfully."}),
            401: OpenApiResponse(
                response={"detail": "You are not authorized to delete this flag."}
            ),
            403: OpenApiResponse(
                response={"detail": "You are not authorized to delete this flag."}
            ),
            404: OpenApiResponse(response={"detail": "Failed to retrieve flag."}),
        }
    )
    def delete(self, request: Request, id: UUID | str) -> Response:
        try:
            flag = EventFlag.objects.get(id=id)

        except EventFlag.DoesNotExist as e:
            logger.exception(f"EventFlag with id {id} does not exist for delete: {e}")
            return Response(
                {"detail": "Flag not found."}, status=status.HTTP_404_NOT_FOUND
            )

        self.check_object_permissions(request, flag)

        flag.delete()
        return Response(
            {"message": "Flag deleted successfully."}, status=status.HTTP_204_NO_CONTENT
        )


# MARK: FAQ


class EventFaqViewSet(viewsets.ModelViewSet[EventFaq]):
    queryset = EventFaq.objects.all()
    serializer_class = EventFaqSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event: Event = serializer.validated_data["event"]

        if request.user != event.created_by and not request.user.is_staff:
            return Response(
                {"detail": "You are not authorized to create FAQs for this event."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer.save()
        logger.info(f"FAQ created for event {event.id} by user {request.user.id}")

        return Response(
            {"message": "FAQ created successfully."}, status=status.HTTP_201_CREATED
        )

    def update(self, request: Request, pk: UUID | str) -> Response:
        try:
            faq = EventFaq.objects.get(id=pk)

        except EventFaq.DoesNotExist as e:
            logger.exception(f"FAQ with id {pk} does not exist for update: {e}")
            return Response(
                {"detail": "FAQ not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if request.user != faq.event.created_by and not request.user.is_staff:
            return Response(
                {"detail": "You are not authorized to update this FAQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"message": "FAQ updated successfully."}, status=status.HTTP_200_OK
        )

    @extend_schema(
        responses={
            204: OpenApiResponse(response={"message": "FAQ deleted successfully."}),
            403: OpenApiResponse(
                response={
                    "detail": "You are not authorized to delete the faqs for this event."
                }
            ),
            404: OpenApiResponse(response={"detail": "FAQ not found."}),
        }
    )
    def destroy(self, request: Request, pk: UUID | str) -> Response:
        try:
            faq = EventFaq.objects.get(id=pk)

        except EventFaq.DoesNotExist as e:
            logger.exception(f"FAQ with id {pk} does not exist for delete: {e}")
            return Response(
                {"detail": "FAQ not found."}, status=status.HTTP_404_NOT_FOUND
            )

        event = faq.event
        if event is not None:
            creator = event.created_by

        else:
            raise ValueError("Org is None.")

        if request.user != creator and not request.user.is_staff:
            return Response(
                {"detail": "You are not authorized to delete this FAQ."},
                status=status.HTTP_403_FORBIDDEN,
            )

        faq.delete()
        logger.info(f"FAQ {pk} deleted for event {event.id} by user {request.user.id}")

        return Response(
            {"message": "FAQ deleted successfully."}, status=status.HTTP_204_NO_CONTENT
        )


# MARK: Resource


class EventResourceViewSet(viewsets.ModelViewSet[EventResource]):
    queryset = EventResource.objects.all()
    serializer_class = EventResourceSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]

    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event: Event = serializer.validated_data["event"]

        if request.user != event.created_by and not request.user.is_staff:
            return Response(
                {
                    "detail": "You are not authorized to create Resources for this event."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer.save(created_by=request.user)
        logger.info(f"Resource created for event {event.id} by user {request.user.id}")

        return Response(
            {"message": "Resource created successfully."},
            status=status.HTTP_201_CREATED,
        )

    def update(self, request: Request, pk: UUID | str) -> Response:
        try:
            faq = EventResource.objects.get(id=pk)

        except EventResource.DoesNotExist as e:
            logger.exception(f"Resource with id {pk} does not exist for update: {e}")
            return Response(
                {"detail": "Resource not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if request.user != faq.event.created_by and not request.user.is_staff:
            return Response(
                {"detail": "You are not authorized to update this Resource."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"message": "Resource updated successfully."}, status=status.HTTP_200_OK
        )


# MARK: Social Link


class EventSocialLinkViewSet(viewsets.ModelViewSet[EventSocialLink]):
    queryset = EventSocialLink.objects.all()
    serializer_class = EventSocialLinkSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    http_method_names = ["post", "put", "delete"]

    @extend_schema(
        responses={
            201: OpenApiResponse(
                response={"message": "Social link created successfully."}
            ),
            403: OpenApiResponse(
                response={
                    "detail": "You are not authorized to create social links for this event."
                }
            ),
        }
    )
    def create(self, request: Request) -> Response:
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event: Event = serializer.validated_data["event"]

        if request.user != event.created_by and not request.user.is_staff:
            return Response(
                {
                    "detail": "You are not authorized to create social links for this event."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer.save()
        logger.info(f"Social link created for event {event.id}")

        return Response(
            {"message": "Social link created successfully."},
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        responses={
            200: OpenApiResponse(
                response={"message": "Social link updated successfully."}
            ),
            400: OpenApiResponse(response={"detail": "Invalid request."}),
            403: OpenApiResponse(
                response={
                    "detail": "You are not authorized to update the social links for this event."
                }
            ),
            404: OpenApiResponse(response={"detail": "Social links not found."}),
        }
    )
    def update(self, request: Request, pk: UUID | str) -> Response:
        try:
            social_link = EventSocialLink.objects.get(id=pk)

        except EventSocialLink.DoesNotExist as e:
            logger.exception(f"Social link with id {pk} does not exist for update: {e}")
            return Response(
                {"detail": "Social link not found."}, status=status.HTTP_404_NOT_FOUND
            )

        event = social_link.event
        if event is not None:
            creator = event.created_by

        else:
            raise ValueError("Event is None.")

        if request.user != creator and not request.user.is_staff:
            return Response(
                {
                    "detail": "You are not authorized to update the social links for this event."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.get_serializer(social_link, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save(event=event)

            return Response(
                {"message": "Social link updated successfully."},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"detail": "Invalid request."}, status=status.HTTP_400_BAD_REQUEST
        )

    @extend_schema(
        responses={
            204: OpenApiResponse(
                response={"message": "Social link deleted successfully."}
            ),
            403: OpenApiResponse(
                response={
                    "detail": "You are not authorized to delete this social links for this event."
                }
            ),
            404: OpenApiResponse(response={"detail": "Social link not found."}),
        }
    )
    def destroy(self, request: Request, pk: UUID | str) -> Response:
        try:
            social_link = EventSocialLink.objects.get(id=pk)

        except EventSocialLink.DoesNotExist as e:
            logger.exception(
                f"Social link with id {pk} does not exist for deletion: {e}"
            )
            return Response(
                {"detail": "Social link not found."}, status=status.HTTP_404_NOT_FOUND
            )

        event = social_link.event
        if event is not None:
            creator = event.created_by

        else:
            raise ValueError("Event is None.")

        if request.user != creator and not request.user.is_staff:
            return Response(
                {"detail": "You are not authorized to delete this social link."},
                status=status.HTTP_403_FORBIDDEN,
            )

        social_link.delete()
        logger.info(
            f"Social link {pk} deleted for event {event.id} by user {request.user.id}"
        )

        return Response(
            {"message": "Social link deleted successfully."},
            status=status.HTTP_204_NO_CONTENT,
        )


# MARK: Text


class EventTextViewSet(GenericAPIView[EventText]):
    queryset = EventText.objects.all()
    serializer_class = EventTextSerializer
    permission_classes = [IsAdminStaffCreatorOrReadOnly]

    @extend_schema(
        responses={
            200: EventTextSerializer,
            403: OpenApiResponse(
                response={
                    "detail": "You are not authorized to update to this event's text."
                }
            ),
            404: OpenApiResponse(response={"detail": "Event text not found."}),
        }
    )
    def put(self, request: Request, id: UUID | str) -> Response:
        try:
            event_text = EventText.objects.get(id=id)

        except EventText.DoesNotExist as e:
            logger.exception(f"Event text not found for update with id {id}: {e}")
            return Response(
                {"detail": "Event text not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if (
            request.user != getattr(event_text.event, "created_by", None)
            and not request.user.is_staff
        ):
            return Response(
                {"detail": "You are not authorized to update to this event's text."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = self.serializer_class(event_text, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(serializer.data, status=status.HTTP_200_OK)


# MARK: Calendar


class EventCalenderAPIView(APIView):
    queryset = Event.objects.all()
    permission_classes = [AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="event_id",
                type=UUID,
                required=True,
            )
        ],
        responses={
            200: OpenApiResponse(
                description="iCalendar (.ics) file for the requested event.",
            ),
            400: OpenApiResponse(
                description="Event ID is required.",
            ),
            404: OpenApiResponse(
                description="Event not found.",
            ),
        },
    )
    def get(self, request: Request) -> HttpResponse | Response:
        event_id = request.query_params.get("event_id")

        if not event_id:
            return Response(
                {"detail": "Event ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = self.queryset.get(id=event_id)

        except Event.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        cal = Calendar()
        cal.add("prodid", "-//Activist//EN")
        cal.add("version", "2.0")
        ical_event = ICalEvent()
        ical_event.add("summary", event.name)
        ical_event.add("description", event.tagline or "")

        # Get the first event time if available.
        if first_time := event.times.first():
            ical_event.add("dtstart", first_time.start_time)
            ical_event.add("dtend", first_time.end_time)

        ical_event.add(
            "location",
            (
                event.online_location_link
                if event.location_type == "online"
                else event.physical_location
            ),
        )
        ical_event.add("uid", event.id)
        cal.add_component(ical_event)

        # Convert to lower camel case.
        event_name = re.sub(r"[\t\n\r\f\v]+", " ", event.name)
        event_file_identifier = (
            "".join(filter(str.isalnum, event_name)).replace(" ", "_").lower()
        )

        response = HttpResponse(cal.to_ical(), content_type="text/calendar")
        response["Content-Disposition"] = (
            f"attachment; filename=activist_event_{event_file_identifier}.ics"
        )

        return response


# MARK: Event Registration


def get_or_create_registered_status() -> EventAttendeeStatus:
    """
    Get or create the 'registered' status.

    Returns
    -------
    EventAttendeeStatus
        The registered status instance.
    """
    status, _ = EventAttendeeStatus.objects.get_or_create(
        status_name=EventAttendeeStatus.STATUS_REGISTERED
    )
    return status


def get_or_create_cancelled_status() -> EventAttendeeStatus:
    """
    Get or create the 'cancelled' status.

    Returns
    -------
    EventAttendeeStatus
        The cancelled status instance.
    """
    status, _ = EventAttendeeStatus.objects.get_or_create(
        status_name=EventAttendeeStatus.STATUS_CANCELLED
    )
    return status


def create_notification(
    user: UserModel,
    notification_type: str,
    title: str,
    message: str,
    event: Event | None = None,
) -> Notification:
    """
    Create a notification for a user.

    Parameters
    ----------
    user : UserModel
        The user to notify.
    notification_type : str
        The type of notification.
    title : str
        The notification title.
    message : str
        The notification message.
    event : Event, optional
        The associated event, if any.

    Returns
    -------
    Notification
        The created notification instance.
    """
    return Notification.objects.create(
        user=user,
        type=notification_type,
        title=title,
        message=message,
        event=event,
    )


def get_remaining_spots(event: Event) -> int | None:
    """
    Calculate remaining spots for an event.

    Parameters
    ----------
    event : Event
        The event to calculate spots for.

    Returns
    -------
    int or None
        Remaining spots, or None if no max_participants set.
    """
    if event.max_participants is None:
        return None

    registered_status = get_or_create_registered_status()
    registered_count = EventAttendee.objects.filter(
        event=event, attendee_status=registered_status
    ).count()

    return max(0, event.max_participants - registered_count)


class EventRegisterAPIView(APIView):
    """
    API view for event registration.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=EventRegistrationSerializer,
        responses={
            200: EventRegistrationResponseSerializer,
            400: OpenApiResponse(response={"detail": "Registration failed."}),
            404: OpenApiResponse(response={"detail": "Event not found."}),
        },
    )
    def post(self, request: Request) -> Response:
        """
        Register the current user for an event.

        Uses database transaction and row locking to prevent overselling.

        Parameters
        ----------
        request : Request
            The DRF request containing event_id.

        Returns
        -------
        Response
            Response with registration result.
        """
        serializer = EventRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_id = serializer.validated_data["event_id"]
        user = request.user

        try:
            with transaction.atomic():
                event = Event.objects.select_for_update().get(id=event_id)

                if event.created_by == user:
                    return Response(
                        {
                            "success": False,
                            "message": "You cannot register for your own event.",
                            "remaining_spots": get_remaining_spots(event),
                            "is_registered": False,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                registered_status = get_or_create_registered_status()

                existing_attendee = EventAttendee.objects.filter(
                    event=event, user=user
                ).first()

                if existing_attendee:
                    if existing_attendee.attendee_status == registered_status:
                        return Response(
                            {
                                "success": False,
                                "message": "You are already registered for this event.",
                                "remaining_spots": get_remaining_spots(event),
                                "is_registered": True,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    else:
                        existing_attendee.attendee_status = registered_status
                        existing_attendee.save()

                        create_notification(
                            user=user,
                            notification_type="event_registration_success",
                            title=f"Registered for {event.name}",
                            message=f"You have successfully registered for the event '{event.name}'.",
                            event=event,
                        )

                        return Response(
                            {
                                "success": True,
                                "message": "Successfully registered for the event.",
                                "remaining_spots": get_remaining_spots(event),
                                "is_registered": True,
                            },
                            status=status.HTTP_200_OK,
                        )

                if event.max_participants is not None:
                    registered_count = EventAttendee.objects.filter(
                        event=event, attendee_status=registered_status
                    ).count()

                    if registered_count >= event.max_participants:
                        return Response(
                            {
                                "success": False,
                                "message": "This event is full.",
                                "remaining_spots": 0,
                                "is_registered": False,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                EventAttendee.objects.create(
                    event=event,
                    user=user,
                    attendee_status=registered_status,
                )

                create_notification(
                    user=user,
                    notification_type="event_registration_success",
                    title=f"Registered for {event.name}",
                    message=f"You have successfully registered for the event '{event.name}'.",
                    event=event,
                )

                remaining = get_remaining_spots(event)

                return Response(
                    {
                        "success": True,
                        "message": "Successfully registered for the event.",
                        "remaining_spots": remaining,
                        "is_registered": True,
                    },
                    status=status.HTTP_200_OK,
                )

        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            logger.exception(f"Event registration failed: {e}")
            return Response(
                {"detail": "Registration failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class EventUnregisterAPIView(APIView):
    """
    API view for cancelling event registration.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        request=EventRegistrationSerializer,
        responses={
            200: EventRegistrationResponseSerializer,
            400: OpenApiResponse(response={"detail": "Cancellation failed."}),
            404: OpenApiResponse(response={"detail": "Event not found."}),
        },
    )
    def post(self, request: Request) -> Response:
        """
        Cancel the current user's registration for an event.

        Parameters
        ----------
        request : Request
            The DRF request containing event_id.

        Returns
        -------
        Response
            Response with cancellation result.
        """
        serializer = EventRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        event_id = serializer.validated_data["event_id"]
        user = request.user

        try:
            event = Event.objects.get(id=event_id)

            registered_status = get_or_create_registered_status()
            cancelled_status = get_or_create_cancelled_status()

            attendee = EventAttendee.objects.filter(
                event=event, user=user, attendee_status=registered_status
            ).first()

            if not attendee:
                return Response(
                    {
                        "success": False,
                        "message": "You are not registered for this event.",
                        "remaining_spots": get_remaining_spots(event),
                        "is_registered": False,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            attendee.attendee_status = cancelled_status
            attendee.save()

            create_notification(
                user=user,
                notification_type="event_registration_cancelled",
                title=f"Cancelled registration for {event.name}",
                message=f"You have cancelled your registration for the event '{event.name}'.",
                event=event,
            )

            remaining = get_remaining_spots(event)

            return Response(
                {
                    "success": True,
                    "message": "Successfully cancelled registration.",
                    "remaining_spots": remaining,
                    "is_registered": False,
                },
                status=status.HTTP_200_OK,
            )

        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        except Exception as e:
            logger.exception(f"Event cancellation failed: {e}")
            return Response(
                {"detail": "Cancellation failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class EventRegistrationStatusAPIView(APIView):
    """
    API view for checking event registration status.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="event_id",
                type=OpenApiTypes.UUID,
                location=OpenApiParameter.QUERY,
                required=True,
                description="The event ID to check registration status for.",
            ),
        ],
        responses={
            200: EventRegistrationResponseSerializer,
            404: OpenApiResponse(response={"detail": "Event not found."}),
        },
    )
    def get(self, request: Request) -> Response:
        """
        Check the current user's registration status for an event.

        Parameters
        ----------
        request : Request
            The DRF request containing event_id as query parameter.

        Returns
        -------
        Response
            Response with registration status and remaining spots.
        """
        event_id = request.query_params.get("event_id")

        if not event_id:
            return Response(
                {"detail": "Event ID is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            event = Event.objects.get(id=event_id)
            user = request.user

            registered_status = get_or_create_registered_status()

            is_registered = EventAttendee.objects.filter(
                event=event, user=user, attendee_status=registered_status
            ).exists()

            remaining = get_remaining_spots(event)

            return Response(
                {
                    "success": True,
                    "message": "Registration status retrieved.",
                    "remaining_spots": remaining,
                    "is_registered": is_registered,
                    "is_creator": event.created_by == user,
                    "max_participants": event.max_participants,
                },
                status=status.HTTP_200_OK,
            )

        except Event.DoesNotExist:
            return Response(
                {"detail": "Event not found."},
                status=status.HTTP_404_NOT_FOUND,
            )


class NotificationListAPIView(GenericAPIView[Notification]):
    """
    API view for listing user notifications.
    """

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = CustomPagination

    def get_queryset(self) -> QuerySet[Notification]:
        return Notification.objects.filter(user=self.request.user).order_by(
            "-creation_date"
        )

    @extend_schema(
        responses={200: NotificationSerializer(many=True)},
    )
    def get(self, request: Request) -> Response:
        """
        List all notifications for the current user.

        Parameters
        ----------
        request : Request
            The DRF request.

        Returns
        -------
        Response
            Paginated list of notifications.
        """
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


class NotificationMarkReadAPIView(APIView):
    """
    API view for marking a notification as read.
    """

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses={
            200: OpenApiResponse(response={"message": "Notification marked as read."}),
            404: OpenApiResponse(response={"detail": "Notification not found."}),
        },
    )
    def post(self, request: Request, id: UUID) -> Response:
        """
        Mark a notification as read.

        Parameters
        ----------
        request : Request
            The DRF request.
        id : UUID
            The notification ID.

        Returns
        -------
        Response
            Response indicating success.
        """
        try:
            notification = Notification.objects.get(id=id, user=request.user)
            notification.is_read = True
            notification.save()

            return Response(
                {"message": "Notification marked as read."},
                status=status.HTTP_200_OK,
            )

        except Notification.DoesNotExist:
            return Response(
                {"detail": "Notification not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

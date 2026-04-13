// SPDX-License-Identifier: AGPL-3.0-or-later
// Events service: plain exported functions (no composables, no state).
// Uses services/http.ts helpers and centralizes error handling + normalization.

import { del, get, post } from "~/services/http";

export interface EventRegistrationStatusResponse {
  success: boolean;
  message: string;
  remainingSpots: number | null;
  isRegistered: boolean;
  isCreator: boolean;
  maxParticipants: number | null;
}

export interface EventRegistrationResponse {
  success: boolean;
  message: string;
  remainingSpots: number | null;
  isRegistered: boolean;
}

// MARK: Map API Response to Type

export function mapEvent(res: EventResponse): EventResponse {
  return {
    id: res.id,
    name: res.name,
    tagline: res.tagline,
    createdBy: res.createdBy,
    iconUrl: res.iconUrl,
    type: res.type,
    onlineLocationLink: res.onlineLocationLink,
    physicalLocation: res.physicalLocation,
    socialLinks: res.socialLinks ?? [],
    resources: res.resources ?? [],
    faqEntries: res.faqEntries ?? [],
    times: res.times ?? [],
    creationDate: res.creationDate,
    orgs: res.orgs,
    texts: res.texts ?? [],
    maxParticipants: res.maxParticipants,
  };
}

// MARK: Get by ID

export async function getEvent(id: string): Promise<EventResponse> {
  try {
    const res = await get<EventResponse>(`/events/events/${id}`, {
      withoutAuth: true,
    });
    return mapEvent(res);
  } catch (e) {
    throw errorHandler(e);
  }
}

// MARK: List All

export async function listEvents(
  filters: EventFilters & Pagination = { page: 1, page_size: 10 }
): Promise<EventsPaginatedResponse> {
  try {
    const query = new URLSearchParams();
    // Handle topics specially: arrays become repeated params (?topics=A&topics=B).
    const { topics, ...rest } = filters;
    if (topics) {
      topics.forEach((t) => {
        if (!t) return;
        query.append("topics", String(t));
      });
    }

    // Add the remaining filters as single query params.
    Object.entries(rest).forEach(([key, value]) => {
      if (value === undefined || value === null) return;
      query.append(key, String(value));
    });
    const res = await get<EventsResponseBody>(
      `/events/events?${query.toString()}`,
      { withoutAuth: true }
    );
    return { data: res.results.map(mapEvent), isLastPage: !res.next };
  } catch (e: unknown) {
    throw errorHandler(e);
  }
}

// MARK: Create

export async function createEvent(
  data: CreateEventInput
): Promise<EventResponse> {
  try {
    const res = await post<EventResponse, typeof data>(`/events/events`, data, {
      headers: { "Content-Type": "application/json" },
    });
    return res;
  } catch (e) {
    throw errorHandler(e);
  }
}

// MARK: Delete

export async function deleteEvent(eventId: string): Promise<void> {
  try {
    await del(`/events/events/${eventId}`);
  } catch (e) {
    throw errorHandler(e);
  }
}

// MARK: Registration

export async function getEventRegistrationStatus(
  eventId: string
): Promise<EventRegistrationStatusResponse> {
  try {
    const res = await get<EventRegistrationStatusResponse>(
      `/events/event_registration_status?event_id=${eventId}`
    );
    return res;
  } catch (e) {
    throw errorHandler(e);
  }
}

export async function registerForEvent(
  eventId: string
): Promise<EventRegistrationResponse> {
  try {
    const res = await post<EventRegistrationResponse, { eventId: string }>(
      `/events/event_register`,
      { eventId },
      { headers: { "Content-Type": "application/json" } }
    );
    return res;
  } catch (e) {
    throw errorHandler(e);
  }
}

export async function unregisterFromEvent(
  eventId: string
): Promise<EventRegistrationResponse> {
  try {
    const res = await post<EventRegistrationResponse, { eventId: string }>(
      `/events/event_unregister`,
      { eventId },
      { headers: { "Content-Type": "application/json" } }
    );
    return res;
  } catch (e) {
    throw errorHandler(e);
  }
}

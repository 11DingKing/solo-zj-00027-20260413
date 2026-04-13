<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
<template>
  <CardGetInvolved>
    <div class="flex items-center gap-5">
      <h3 class="text-left font-display">
        {{ $t("i18n.components._global.participate") }}
      </h3>
      <IconEdit
        v-if="userIsSignedIn"
        @click="openModalTextEvent"
        @keydown.enter="openModalTextEvent"
        :entity="event"
      />
    </div>
    <div class="space-y-3 pt-3">
      <p v-if="event?.texts[0]?.getInvolved">
        {{ event.texts[0]?.getInvolved }}
      </p>
      <p v-else>
        {{ $t("i18n.components.card_get_involved_event.participate_subtext") }}
      </p>

      <div v-if="registrationStatus" class="space-y-3 pt-2">
        <div
          v-if="remainingSpotsDisplay"
          class="flex items-center gap-2 text-sm font-medium"
          :class="{
            'text-warning': isLowSpots,
            'text-error': isFull,
            'text-primary-text': !isLowSpots && !isFull,
          }"
        >
          <span>{{ remainingSpotsDisplay }}</span>
        </div>

        <div v-if="userIsSignedIn" class="flex w-max pt-2">
          <BtnAction
            v-if="registrationStatus.isCreator"
            :disabled="true"
            :label="$t('i18n.components.card_get_involved_event.you_are_creator')"
            class="w-full opacity-60"
            fontSize="sm"
          />

          <BtnAction
            v-else-if="registrationStatus.isRegistered"
            @click="handleUnregister"
            :loading="registrationLoading"
            :label="$t('i18n.components.card_get_involved_event.cancel_registration')"
            class="w-full"
            fontSize="sm"
            variant="secondary"
          />

          <BtnAction
            v-else-if="isFull"
            :disabled="true"
            :label="$t('i18n.components.card_get_involved_event.event_full')"
            class="w-full opacity-60"
            fontSize="sm"
          />

          <BtnAction
            v-else
            @click="handleRegister"
            :loading="registrationLoading"
            :label="$t('i18n.components.card_get_involved_event.register')"
            class="w-full"
            :cta="true"
            fontSize="sm"
          />
        </div>

        <div v-else class="flex w-max pt-2">
          <BtnRouteInternal
            ariaLabel="i18n._global.sign_in_aria_label"
            class="w-full"
            :cta="true"
            fontSize="sm"
            iconSize="1.45em"
            :label="$t('i18n.components.card_get_involved_event.sign_in_to_register')"
            linkTo="/sign-in"
            :rightIcon="IconMap.ARROW_RIGHT"
          />
        </div>
      </div>

      <div v-else class="flex w-max pt-2">
        <BtnRouteInternal
          ariaLabel="i18n._global.offer_to_help_aria_label"
          class="w-full"
          :cta="true"
          fontSize="sm"
          iconSize="1.45em"
          label="i18n._global.offer_to_help"
          linkTo="/"
          :rightIcon="IconMap.ARROW_RIGHT"
        />
      </div>
    </div>
  </CardGetInvolved>
</template>

<script setup lang="ts">
const { openModal: openModalTextEvent } = useModalHandlers("ModalTextEvent");

const { userIsSignedIn } = useUser();

const paramsEventId = useRoute().params.eventId;
const eventId = typeof paramsEventId === "string" ? paramsEventId : "";

const { data: event } = useGetEvent(eventId);

const {
  loading: registrationLoading,
  registrationStatus,
  fetchRegistrationStatus,
  register,
  unregister,
  getRemainingSpotsDisplay,
} = useEventRegistrationMutations();

const { handleError, clearError } = useAppError();
const { toast } = useToaster();

const remainingSpotsDisplay = computed(() => {
  if (!registrationStatus.value) return null;
  return getRemainingSpotsDisplay(
    registrationStatus.value.remainingSpots,
    registrationStatus.value.maxParticipants
  );
});

const isLowSpots = computed(() => {
  if (!registrationStatus.value) return false;
  const spots = registrationStatus.value.remainingSpots;
  return spots !== null && spots > 0 && spots < 10;
});

const isFull = computed(() => {
  if (!registrationStatus.value) return false;
  const spots = registrationStatus.value.remainingSpots;
  return spots !== null && spots <= 0;
});

const handleRegister = async () => {
  clearError();
  const result = await register(eventId);

  if (result.success) {
    toast.success(result.message || "Successfully registered for the event.");
    await fetchRegistrationStatus(eventId);
  } else {
    toast.error(result.message || "Registration failed. Please try again.");
  }
};

const handleUnregister = async () => {
  clearError();
  const result = await unregister(eventId);

  if (result.success) {
    toast.success(result.message || "Successfully cancelled registration.");
    await fetchRegistrationStatus(eventId);
  } else {
    toast.error(result.message || "Cancellation failed. Please try again.");
  }
};

watch(
  () => eventId,
  async (newEventId) => {
    if (newEventId && userIsSignedIn) {
      await fetchRegistrationStatus(newEventId);
    }
  },
  { immediate: true }
);

watch(
  userIsSignedIn,
  async (isSignedIn) => {
    if (isSignedIn && eventId) {
      await fetchRegistrationStatus(eventId);
    }
  }
);
</script>

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
      <p v-if="event?.texts?.[0]?.getInvolved">
        {{ event.texts[0].getInvolved }}
      </p>
      <p v-else>
        {{ $t("i18n.components.card_get_involved_event.participate_subtext") }}
      </p>

      <div v-if="userIsSignedIn && eventId" class="space-y-3 pt-2">
        <div
          v-if="remainingSpotsText"
          class="flex items-center gap-2 text-sm font-medium"
          :class="{
            'text-warning': isLowSpots,
            'text-error': isFull,
            'text-primary-text': !isLowSpots && !isFull,
          }"
        >
          <span>{{ remainingSpotsText }}</span>
        </div>

        <div class="flex w-max pt-2">
          <BtnAction
            v-if="isCreator"
            :disabled="true"
            :label="
              $t('i18n.components.card_get_involved_event.you_are_creator')
            "
            class="w-full opacity-60"
            fontSize="sm"
          />

          <BtnAction
            v-else-if="isRegistered"
            @click="handleUnregister"
            :loading="isLoading"
            :label="
              $t('i18n.components.card_get_involved_event.cancel_registration')
            "
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
            :loading="isLoading"
            :label="$t('i18n.components.card_get_involved_event.register')"
            class="w-full"
            :cta="true"
            fontSize="sm"
          />
        </div>
      </div>

      <div v-else class="flex w-max pt-2">
        <BtnRouteInternal
          v-if="!userIsSignedIn"
          ariaLabel="i18n._global.sign_in_aria_label"
          class="w-full"
          :cta="true"
          fontSize="sm"
          iconSize="1.45em"
          :label="
            $t('i18n.components.card_get_involved_event.sign_in_to_register')
          "
          linkTo="/sign-in"
          :rightIcon="IconMap.ARROW_RIGHT"
        />
        <BtnRouteInternal
          v-else
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
const props = defineProps<{
  event?: CommunityEvent | null;
  disclaimer?: string;
}>();

const { openModal: openModalTextEvent } = useModalHandlers("ModalTextEvent");

const { userIsSignedIn } = useUser();

const isLoading = ref(false);
const registrationStatus = ref<{
  isRegistered: boolean;
  isCreator: boolean;
  remainingSpots: number | null;
  maxParticipants: number | null;
} | null>(null);

const { toast } = useToaster();

const eventId = computed(() => props.event?.id || "");

const isRegistered = computed(() => {
  return registrationStatus.value?.isRegistered || false;
});

const isCreator = computed(() => {
  return registrationStatus.value?.isCreator || false;
});

const remainingSpots = computed(() => {
  return registrationStatus.value?.remainingSpots;
});

const maxParticipants = computed(() => {
  return registrationStatus.value?.maxParticipants;
});

const isFull = computed(() => {
  const spots = remainingSpots.value;
  const max = maxParticipants.value;
  if (max === null || max === undefined) {
    return false;
  }
  return spots !== null && spots !== undefined && spots <= 0;
});

const isLowSpots = computed(() => {
  const spots = remainingSpots.value;
  const max = maxParticipants.value;
  if (max === null || max === undefined) {
    return false;
  }
  return spots !== null && spots !== undefined && spots > 0 && spots < 10;
});

const remainingSpotsText = computed(() => {
  const spots = remainingSpots.value;
  const max = maxParticipants.value;

  if (
    max === null ||
    max === undefined ||
    spots === null ||
    spots === undefined
  ) {
    return null;
  }

  if (spots <= 0) {
    return "Full";
  }

  if (spots < 10) {
    return `Only ${spots} spots left`;
  }

  return `${spots} spots available`;
});

const fetchRegistrationStatus = async () => {
  if (!eventId.value || !userIsSignedIn) {
    return;
  }

  try {
    const status = await getEventRegistrationStatus(eventId.value);
    registrationStatus.value = {
      isRegistered: status.isRegistered,
      isCreator: status.isCreator,
      remainingSpots: status.remainingSpots,
      maxParticipants: status.maxParticipants,
    };
  } catch (e) {
    console.error("Failed to fetch registration status:", e);
  }
};

const handleRegister = async () => {
  if (!eventId.value) return;

  isLoading.value = true;
  try {
    const result = await registerForEvent(eventId.value);

    if (result.success) {
      toast.success(result.message || "Successfully registered for the event.");
      await fetchRegistrationStatus();
    } else {
      toast.error(result.message || "Registration failed. Please try again.");
    }
  } catch (e) {
    toast.error("Registration failed. Please try again.");
  } finally {
    isLoading.value = false;
  }
};

const handleUnregister = async () => {
  if (!eventId.value) return;

  isLoading.value = true;
  try {
    const result = await unregisterFromEvent(eventId.value);

    if (result.success) {
      toast.success(result.message || "Successfully cancelled registration.");
      await fetchRegistrationStatus();
    } else {
      toast.error(result.message || "Cancellation failed. Please try again.");
    }
  } catch (e) {
    toast.error("Cancellation failed. Please try again.");
  } finally {
    isLoading.value = false;
  }
};

watch(
  () => props.event,
  async (newEvent) => {
    if (newEvent?.id && userIsSignedIn) {
      await fetchRegistrationStatus();
    } else {
      registrationStatus.value = null;
    }
  },
  { immediate: true }
);

watch(userIsSignedIn, async (isSignedIn) => {
  if (isSignedIn && eventId.value) {
    await fetchRegistrationStatus();
  } else {
    registrationStatus.value = null;
  }
});
</script>

// SPDX-License-Identifier: AGPL-3.0-or-later

import {
  getEventRegistrationStatus,
  registerForEvent,
  unregisterFromEvent,
  type EventRegistrationStatusResponse,
} from "~/services/event/event";

export const useEventRegistrationMutations = () => {
  const loading = ref(false);
  const { error, handleError, clearError } = useAppError();

  const registrationStatus = ref<EventRegistrationStatusResponse | null>(null);

  const fetchRegistrationStatus = async (
    eventId: string
  ): Promise<EventRegistrationStatusResponse | null> => {
    clearError();
    try {
      const status = await getEventRegistrationStatus(eventId);
      registrationStatus.value = status;
      return status;
    } catch (e) {
      handleError(e);
      return null;
    }
  };

  const register = async (
    eventId: string
  ): Promise<{ success: boolean; message: string; remainingSpots: number | null }> => {
    loading.value = true;
    clearError();
    try {
      const result = await registerForEvent(eventId);
      if (registrationStatus.value) {
        registrationStatus.value.isRegistered = result.isRegistered;
        registrationStatus.value.remainingSpots = result.remainingSpots;
      }
      return {
        success: result.success,
        message: result.message,
        remainingSpots: result.remainingSpots,
      };
    } catch (e) {
      handleError(e);
      return {
        success: false,
        message: "Registration failed. Please try again.",
        remainingSpots: null,
      };
    } finally {
      loading.value = false;
    }
  };

  const unregister = async (
    eventId: string
  ): Promise<{ success: boolean; message: string; remainingSpots: number | null }> => {
    loading.value = true;
    clearError();
    try {
      const result = await unregisterFromEvent(eventId);
      if (registrationStatus.value) {
        registrationStatus.value.isRegistered = result.isRegistered;
        registrationStatus.value.remainingSpots = result.remainingSpots;
      }
      return {
        success: result.success,
        message: result.message,
        remainingSpots: result.remainingSpots,
      };
    } catch (e) {
      handleError(e);
      return {
        success: false,
        message: "Cancellation failed. Please try again.",
        remainingSpots: null,
      };
    } finally {
      loading.value = false;
    }
  };

  const getRemainingSpotsDisplay = (
    remainingSpots: number | null,
    maxParticipants: number | null
  ): string | null => {
    if (maxParticipants === null || remainingSpots === null) {
      return null;
    }

    if (remainingSpots <= 0) {
      return "Full";
    }

    if (remainingSpots < 10) {
      return `Only ${remainingSpots} spots left`;
    }

    return `${remainingSpots} spots available`;
  };

  return {
    loading: readonly(loading),
    error: readonly(error),
    registrationStatus: readonly(registrationStatus),
    fetchRegistrationStatus,
    register,
    unregister,
    getRemainingSpotsDisplay,
  };
};

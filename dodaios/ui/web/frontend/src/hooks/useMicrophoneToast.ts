import { useCallback, useEffect, useRef } from "react";

import { useRestartApp } from "@/hooks/useRestartApp";
import { translate } from "@/i18n";
import { handleMicrophoneToastEvent } from "@/lib/microphoneToast";

/**
 * The microphone toast's entry point for the WebSocket hook: one STABLE
 * function to call with every bus event (it reads only `MicrophoneTrouble` and
 * `MicrophoneRecovered`, see `lib/microphoneToast.ts`).
 *
 * It exists for the same reason as `usePermissionToast`: the toast's "Restart
 * now" button is `useRestartApp`, which is React state, while the socket
 * handler is installed once and lives outside React. The latest `restart` is
 * kept in a ref so the handler never goes stale.
 */
export function useMicrophoneToast(): (eventName: string, payload: unknown) => void {
  const { restart } = useRestartApp();
  const restartRef = useRef(restart);
  useEffect(() => {
    restartRef.current = restart;
  }, [restart]);

  return useCallback(
    (eventName: string, payload: unknown) =>
      handleMicrophoneToastEvent(eventName, payload, {
        restart: () =>
          restartRef.current({ failureMessage: translate("permissions.restart_failed") }),
      }),
    [],
  );
}

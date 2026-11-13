import { postJson, useSignIn } from "@/hooks/useSignIn";

/**
 * Connect a plugin or a CLI: what a Connect button runs, for either kind.
 *
 * A plugin runs its own sign-in (`useSignIn`). A CLI is checked first (already
 * signed in means connected at once), then its login or install opens in a
 * terminal and the hook watches until the CLI reports signed in. Shared by the
 * Connect card in the chat and the notice tile on the rail, so a click in
 * either place does the same thing.
 */

export interface ServiceToConnect {
  kind: "plugin" | "cli";
  /** The plugin id, or the CLI's name. */
  id: string;
  /** The service's readable name, for the sentences a failed sign-in shows. */
  label: string;
}

async function cliConnected(name: string): Promise<{ connected: boolean; installed: boolean }> {
  const data = await postJson(`/api/clis/${encodeURIComponent(name)}/check`);
  return { connected: Boolean(data.connected), installed: Boolean(data.installed) };
}

export function useServiceConnect(service: ServiceToConnect, onConnected: () => void | Promise<void>) {
  const signIn = useSignIn(service.label, onConnected);
  const { setPhase, watch, connectPlugin, start } = signIn;

  const connectCli = async () => {
    const state = await cliConnected(service.id).catch(() => ({ connected: false, installed: true }));
    if (state.connected) {
      await onConnected();
      return;
    }
    await postJson(`/api/clis/${encodeURIComponent(service.id)}/spawn-external`, {
      kind: state.installed ? "login" : "install",
      method: null,
    });
    setPhase({ kind: "waiting" });
    watch(async () => (await cliConnected(service.id)).connected);
  };

  /** Run the connect once; whatever it throws ends as the "try again" line. */
  const connect = () => start(service.kind === "plugin" ? () => connectPlugin(service.id) : connectCli);

  return { ...signIn, connect };
}

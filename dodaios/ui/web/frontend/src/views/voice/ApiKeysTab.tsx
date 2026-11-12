import { useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  sectionHealthForSubject,
  useProviders,
  useSectionHealth,
  type ProviderDescriptor,
  type ProviderTier,
} from "@/hooks/useProviders";
import { useT } from "@/i18n";
import { ProviderRow } from "@/views/voice/keys/ProviderRow";
import { Empty, Group, LoadingGroup, Notice, VoicePage } from "@/views/voice/kit";

/** The two kinds of provider the Voice section uses, in screen order. */
const GROUPS: readonly { tier: ProviderTier; titleKey: string }[] = [
  { tier: "stt", titleKey: "voiceui.keys.speech" },
  { tier: "dictation", titleKey: "voiceui.keys.wording" },
];

/**
 * The order of a group's rows: the provider in use first, then the ones that
 * are set up, then the rest. The order is taken once, when the list first
 * arrives, so a row never moves under the pointer when it is chosen.
 */
function useSettledOrder(providers: ProviderDescriptor[]): ProviderDescriptor[] {
  const order = useRef<string[] | null>(null);
  if (order.current === null && providers.length > 0) {
    const rank = (p: ProviderDescriptor) => (p.active ? 2 : p.configured ? 1 : 0);
    order.current = [...providers].sort((a, b) => rank(b) - rank(a)).map((p) => p.id);
  }
  const position = new Map((order.current ?? []).map((id, index) => [id, index]));
  const at = (p: ProviderDescriptor) => position.get(p.id) ?? Number.MAX_SAFE_INTEGER;
  return [...providers].sort((a, b) => at(a) - at(b));
}

/**
 * The API Keys tab: the providers that turn speech into text, and the ones
 * that clean up wording.
 *
 * One row per provider. These are the same providers and the same stored keys
 * as on the app's main API Keys screen; a key saved here shows there, and the
 * other way round.
 */
export function ApiKeysTab() {
  const t = useT();
  const { providers, loading, error, refetch, setActiveOptimistic } = useProviders();
  const { health } = useSectionHealth();
  // The hook clears its error when it starts to load again, and an empty list
  // without an error would read as "no providers" for the length of the request.
  const [retrying, setRetrying] = useState(false);

  const ordered = useSettledOrder(providers);

  async function retry() {
    setRetrying(true);
    try {
      await refetch();
    } finally {
      setRetrying(false);
    }
  }

  if (providers.length === 0 && (loading || retrying)) {
    return (
      <VoicePage testId="voice-keys">
        <LoadingGroup rows={4} testId="voice-keys-loading" />
        <LoadingGroup rows={3} />
      </VoicePage>
    );
  }

  const failed = Boolean(error);

  return (
    <VoicePage testId="voice-keys">
      {failed && (
        <Notice
          tone="fault"
          testId="voice-keys-error"
          action={
            <Button variant="outline" onClick={() => void retry()} disabled={retrying}>
              {t("voiceui.common.retry")}
            </Button>
          }
        >
          {t("voiceui.keys.load_failed")}
        </Notice>
      )}

      {/* After a failed first load there is nothing to list, and "no
          providers" would be an invented answer. */}
      {!(failed && providers.length === 0) &&
        GROUPS.map(({ tier, titleKey }) => {
          const rows = ordered.filter((p) => p.tier === tier && p.brain_switchable !== false);
          const groupHasActive = rows.some((p) => p.active);
          if (rows.length === 0) {
            return (
              <section key={tier} className="flex flex-col gap-stack" data-testid={`voice-keys-${tier}`}>
                <h2 className="px-1 text-body font-medium text-muted-foreground">{t(titleKey)}</h2>
                <Empty>{t("voiceui.keys.empty")}</Empty>
              </section>
            );
          }
          return (
            <Group key={tier} title={t(titleKey)} testId={`voice-keys-${tier}`}>
              {rows.map((provider) => (
                <ProviderRow
                  key={provider.id}
                  provider={provider}
                  groupHasActive={groupHasActive}
                  health={
                    provider.active ? sectionHealthForSubject(health[tier], provider.id) : undefined
                  }
                  onChanged={() => void refetch()}
                  onActivateOptimistic={setActiveOptimistic}
                />
              ))}
            </Group>
          );
        })}
    </VoicePage>
  );
}

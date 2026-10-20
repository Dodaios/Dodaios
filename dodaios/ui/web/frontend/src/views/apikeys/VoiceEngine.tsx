import { useEffect, useState } from "react";
import { Brain } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  makeProviderCategories,
  ProviderCategory,
  useTierHealth,
} from "@/components/providers/ProviderTierSection";
import { useProviders } from "@/hooks/useProviders";
import { useVoiceMode } from "@/hooks/useVoiceMode";
import { useT } from "@/i18n";
import { Segmented, SettingsGroup, SettingsRow } from "@/views/apikeys/settingsUi";

/** What the Live calls tab shows: GPT-Live's settings or the three pipeline steps. */
export type VoiceEngineView = "live" | "pipeline";

/**
 * The engine choice at the top of the Live calls tab.
 *
 * It writes `[voice].mode` through the same route as the Settings switch.
 * Picking Pipeline always works. Picking GPT-Live works once a live provider
 * is ready; before that the tab only shows GPT-Live's settings, and saving
 * them makes GPT-Live the engine (the backend sets the mode on save).
 */
export function useVoiceEngineView() {
  const voice = useVoiceMode();
  const configured: VoiceEngineView = voice.mode === "pipeline" ? "pipeline" : "live";
  // Only set while GPT-Live is shown but not yet usable.
  const [preview, setPreview] = useState<VoiceEngineView | null>(null);
  useEffect(() => setPreview(null), [configured]);
  const view = preview ?? configured;

  const choose = (next: VoiceEngineView) => {
    if (next === configured) {
      setPreview(null);
      return;
    }
    if (next === "pipeline") {
      setPreview(null);
      voice.setMode("pipeline");
      return;
    }
    if (voice.realtimeAvailable) {
      setPreview(null);
      voice.setMode("realtime");
    } else {
      setPreview("live");
    }
  };

  return {
    view,
    configured,
    choose,
    busy: voice.isLoading || voice.isSaving,
    error: voice.saveError,
  };
}

export function VoiceEngineSwitch({ engine }: { engine: ReturnType<typeof useVoiceEngineView> }) {
  const t = useT();
  const pendingSetup = engine.view === "live" && engine.configured !== "live";
  return (
    <SettingsGroup data-testid="voice-engine" className="mb-6">
      <SettingsRow
        title={t("providers_page.engine_title")}
        description={
          engine.view === "pipeline"
            ? t("providers_page.engine_pipeline_desc")
            : t("providers_page.engine_live_desc")
        }
        status={
          engine.error ? (
            <span role="alert" className="text-destructive">
              {t("providers_page.engine_failed").replace("{0}", engine.error)}
            </span>
          ) : pendingSetup ? (
            t("providers_page.engine_live_setup")
          ) : (
            t("providers_page.engine_next_call")
          )
        }
        control={
          <Segmented<VoiceEngineView>
            testId="voice-engine-switch"
            label={t("providers_page.engine_title")}
            value={engine.view}
            disabled={engine.busy}
            onChange={engine.choose}
            options={[
              { value: "live", label: t("providers_page.engine_live") },
              { value: "pipeline", label: t("providers_page.engine_pipeline") },
            ]}
          />
        }
      />
    </SettingsGroup>
  );
}

/**
 * The pipeline's three steps: voice input, the brain, voice output. Input and
 * output are the same provider lists the rest of the app uses; the brain is
 * the default agent provider, chosen on the Agents tab.
 */
export function PipelinePane({ onOpenAgents }: { onOpenAgents: () => void }) {
  const t = useT();
  const { providers, loading, error, refetch, setActiveOptimistic } = useProviders();
  const health = useTierHealth(providers);
  const categories = makeProviderCategories(t);
  const brain = providers.find((provider) => provider.tier === "brain" && provider.active);

  return (
    <div data-testid="voice-pipeline" className="flex flex-col gap-group">
      <ProviderCategory
        meta={categories.stt}
        tier="stt"
        providers={providers}
        loading={loading}
        error={error}
        onChanged={refetch}
        onActivateOptimistic={setActiveOptimistic}
        health={health.stt}
      />

      <SettingsGroup data-testid="voice-pipeline-brain">
        <SettingsRow
          title={
            <>
              <Brain aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
              {t("providers_page.pipeline_brain_title")}
            </>
          }
          description={
            brain
              ? t("providers_page.pipeline_brain_desc").replace("{0}", brain.label)
              : t("providers_page.pipeline_brain_none")
          }
          control={
            <Button size="sm" variant="outline" onClick={onOpenAgents}>
              {t("providers_page.pipeline_brain_change")}
            </Button>
          }
        />
      </SettingsGroup>

      <ProviderCategory
        meta={categories.tts}
        tier="tts"
        providers={providers}
        loading={loading}
        error={error}
        onChanged={refetch}
        onActivateOptimistic={setActiveOptimistic}
        health={health.tts}
      />
    </div>
  );
}

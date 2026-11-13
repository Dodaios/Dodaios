import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { LanguageSelect } from "@/components/ui/language-select";
import { BrandedSelect, type BrandedSelectOption } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  testDictationPolish,
  useDictation,
  type DictationSettings,
} from "@/hooks/useDictation";
import { useProviders } from "@/hooks/useProviders";
import { fill, useT } from "@/i18n";
import { KeyField } from "@/views/voice/keys/KeyField";
import { modelEntry, modelIsLocal, modelName } from "@/views/voice/language/models";
import { SampleResult, type SampleOutcome } from "@/views/voice/language/SampleResult";
import { Group, LoadingGroup, Notice, Row, VoicePage } from "@/views/voice/kit";

/** The width of a select at the end of a row. */
const SELECT_WIDTH = "w-60 text-title";

/** The last row of a group: one sentence about where the text goes. */
function GroupSentence({ children, testId }: { children: ReactNode; testId: string }) {
  return (
    <p className="px-block py-4 text-body text-foreground" data-testid={testId}>
      {children}
    </p>
  );
}

/**
 * The Language tab: which language is spoken, how the words are written down,
 * and in which language.
 *
 * Every option is a row with a switch or a select, saved the moment it
 * changes. A row that only matters while another is on appears with it. Three
 * options hand the text to a model (clean up wording, the coding prompt, the
 * translation); they share one model, chosen in the last group, and a group
 * says in one sentence when that model is a company's and the text goes there.
 */
export function LanguageTab() {
  const t = useT();
  const {
    settings,
    choices,
    wordingProvider,
    loading,
    saveSettings: persistSettings,
    refetch,
  } = useDictation();
  // For the key row only: which other places read the same key.
  const { providers, refetch: refetchProviders } = useProviders();

  const [saving, setSaving] = useState(false);
  const [saveFailed, setSaveFailed] = useState(false);
  const [testing, setTesting] = useState(false);
  const [sample, setSample] = useState<SampleOutcome>(null);
  // The hook clears its error when it starts to load again; without this the
  // screen would be blank for the length of the request.
  const [retrying, setRetrying] = useState(false);
  const writing = useRef(false);
  const sampleVersion = useRef(0);
  const busy = loading || saving || testing;

  // A sample result describes the settings it ran with. When they change, here
  // or on another screen, the result goes, and one still on its way is dropped.
  useEffect(() => {
    sampleVersion.current += 1;
    setSample(null);
  }, [settings]);

  async function save(patch: Partial<DictationSettings>) {
    if (writing.current) return;
    writing.current = true;
    sampleVersion.current += 1;
    setSample(null);
    setSaving(true);
    try {
      await persistSettings(patch);
      setSaveFailed(false);
    } catch {
      setSaveFailed(true);
    } finally {
      writing.current = false;
      setSaving(false);
    }
  }

  async function runSample() {
    if (busy) return;
    const version = ++sampleVersion.current;
    setTesting(true);
    setSample(null);
    try {
      const result = await testDictationPolish();
      if (version === sampleVersion.current) setSample({ kind: "result", result });
    } catch {
      if (version === sampleVersion.current) setSample({ kind: "failed" });
    } finally {
      setTesting(false);
    }
  }

  async function retry() {
    setRetrying(true);
    try {
      await refetch();
    } finally {
      setRetrying(false);
    }
  }

  if (!settings) {
    return (
      <VoicePage testId="voice-language">
        {loading || retrying ? (
          <>
            <LoadingGroup rows={1} testId="voice-language-loading" />
            <LoadingGroup rows={4} />
            <LoadingGroup rows={1} />
          </>
        ) : (
          <Notice
            tone="fault"
            testId="voice-language-error"
            action={
              <Button variant="outline" onClick={() => void retry()}>
                {t("voiceui.common.retry")}
              </Button>
            }
          >
            {t("voiceui.language.load_failed")}
          </Notice>
        )}
      </VoicePage>
    );
  }

  const spoken = settings.language ?? "auto";
  const polishOn = settings.polish ?? true;
  const precisionOn = settings.polish_precision ?? false;
  const conversationOn = settings.polish_conversation ?? false;
  const promptOn = settings.prompt_mode ?? false;
  const translateOn = settings.translate ?? false;
  const translateTarget = settings.translate_target ?? "en";
  // More exact words keep the wording model at work while clean-up is off, so
  // the two together decide whether wording is on.
  const wordingOn = polishOn || precisionOn;
  // Anything that hands the text to the model.
  const modelInUse = wordingOn || promptOn || translateOn;

  // Which model really answers is the server's answer. The order of the
  // automatic choice depends on the keys on this computer, so it is never
  // worked out a second time here.
  const answering = wordingProvider && wordingProvider.family ? wordingProvider : null;
  const ready = Boolean(answering?.ready);
  const answeringLocal = answering ? modelIsLocal(answering.family, providers, answering) : false;
  const answeringName = answering ? modelName(answering.family, providers, answering.label) : "";
  // The company the text goes to, or nothing when it stays on this computer
  // or no model answers.
  const sentTo = ready && !answeringLocal ? answeringName : null;
  // Nothing answers: the options above are on and do nothing.
  const noModel = modelInUse && wordingProvider !== null && !ready;
  // The key that would fix it.
  const missingKey = noModel && answering?.secret_key ? answering.secret_key : null;
  const keyEntry = answering ? modelEntry(answering.family, providers) : null;

  // The language spoken and the language written are the same one, so the
  // translation has nothing to do.
  const sameLanguage = translateOn && spoken !== "auto" && spoken === translateTarget;

  const storedModel = settings.polish_provider ?? "auto";
  const served = choices?.polish_provider ?? ["auto"];
  // A stored model the served list does not hold is still shown as itself;
  // the select must not name a model the settings do not say.
  const modelIds = served.includes(storedModel) ? served : [...served, storedModel];
  const localName = (id: string) =>
    fill(t("voiceui.language.model_local"), { provider: modelName(id, providers) });
  const modelOptions: BrandedSelectOption[] = modelIds.map((id) => {
    if (id !== "auto") {
      return {
        value: id,
        label: modelIsLocal(id, providers, answering) ? localName(id) : modelName(id, providers),
      };
    }
    // The closed select names the model the automatic choice lands on.
    const lands = ready && answering ? (answeringLocal ? localName(answering.family) : answeringName) : null;
    return {
      value: id,
      label: t("voiceui.language.model_auto"),
      triggerLabel: lands
        ? fill(t("voiceui.language.model_auto_resolved"), { provider: lands })
        : undefined,
    };
  });

  return (
    <VoicePage testId="voice-language">
      {saveFailed && (
        <Notice tone="fault" testId="voice-language-save-failed">
          {t("voiceui.language.save_failed")}
        </Notice>
      )}

      <Group>
        <Row label={t("voiceui.language.spoken")}>
          <LanguageSelect
            value={spoken}
            codes={choices?.language ?? []}
            onChange={(language) => void save({ language })}
            autoLabel={t("voiceui.language.auto")}
            ariaLabel={t("voiceui.language.spoken")}
            disabled={busy}
            className={SELECT_WIDTH}
            testId="voice-language-spoken"
          />
        </Row>
      </Group>

      <Group title={t("voiceui.language.wording")} testId="voice-language-wording">
        <Row label={t("voiceui.language.polish")}>
          <Switch
            checked={polishOn}
            disabled={busy}
            onCheckedChange={(polish) => void save({ polish })}
            aria-label={t("voiceui.language.polish")}
            data-testid="voice-language-polish"
          />
        </Row>
        {/* Not under the switch above: more exact words also apply to a
            translated dictation, which runs while clean-up is off. */}
        <Row label={t("voiceui.language.precision")}>
          <Switch
            checked={precisionOn}
            disabled={busy}
            onCheckedChange={(polish_precision) => void save({ polish_precision })}
            aria-label={t("voiceui.language.precision")}
            data-testid="voice-language-precision"
          />
        </Row>
        {/* The conversation pass extends clean-up and runs only while it is on. */}
        {polishOn && (
          <Row label={t("voiceui.language.conversation")}>
            <Switch
              checked={conversationOn}
              disabled={busy}
              onCheckedChange={(polish_conversation) => void save({ polish_conversation })}
              aria-label={t("voiceui.language.conversation")}
              data-testid="voice-language-conversation"
            />
          </Row>
        )}
        <Row label={t("voiceui.language.prompt_mode")}>
          <Switch
            checked={promptOn}
            disabled={busy}
            onCheckedChange={(prompt_mode) => void save({ prompt_mode })}
            aria-label={t("voiceui.language.prompt_mode")}
            data-testid="voice-language-prompt-mode"
          />
        </Row>
        {(wordingOn || promptOn) && sentTo && (
          <GroupSentence testId="voice-language-sends-text">
            {fill(t("voiceui.language.sends_text"), { provider: sentTo })}
          </GroupSentence>
        )}
      </Group>

      <Group title={t("voiceui.language.translation")} testId="voice-language-translation">
        <Row label={t("voiceui.language.translate")}>
          <Switch
            checked={translateOn}
            disabled={busy}
            onCheckedChange={(translate) => void save({ translate })}
            aria-label={t("voiceui.language.translate")}
            data-testid="voice-language-translate"
          />
        </Row>
        {translateOn && (
          <Row label={t("voiceui.language.translate_target")}>
            {/* The served list has no automatic entry: there is nothing to
                detect in the language that is written. */}
            <LanguageSelect
              value={translateTarget}
              codes={choices?.translate_target ?? []}
              onChange={(translate_target) => void save({ translate_target })}
              autoLabel={t("voiceui.language.auto")}
              ariaLabel={t("voiceui.language.translate_target")}
              disabled={busy}
              className={SELECT_WIDTH}
              testId="voice-language-translate-target"
            />
          </Row>
        )}
        {translateOn && sentTo && (
          <GroupSentence testId="voice-language-translate-sends-text">
            {fill(t("voiceui.language.translate_sends_text"), { provider: sentTo })}
          </GroupSentence>
        )}
      </Group>

      {sameLanguage && (
        <Notice testId="voice-language-same-language">{t("voiceui.language.same_language")}</Notice>
      )}

      {noModel && <Notice testId="voice-language-no-model">{t("voiceui.language.no_model")}</Notice>}

      {modelInUse && (
        <Group title={t("voiceui.language.model")} testId="voice-language-model-group">
          <Row label={t("voiceui.language.provider")}>
            <BrandedSelect
              value={storedModel}
              options={modelOptions}
              // Another model has another default version, so a stored version
              // does not carry over.
              onValueChange={(polish_provider) => void save({ polish_provider, polish_model: "" })}
              ariaLabel={t("voiceui.language.provider")}
              disabled={busy}
              className={SELECT_WIDTH}
              testId="voice-language-model"
            />
          </Row>
          {missingKey && (
            <Row
              label={fill(t("voiceui.language.key"), { provider: answeringName })}
              testId="voice-language-key"
              below={
                <KeyField
                  slot={missingKey}
                  provider={answeringName}
                  stored={Boolean(keyEntry?.secrets_set?.[missingKey])}
                  sharedWith={keyEntry?.secret_shared_with?.[missingKey] ?? []}
                  onChanged={() => {
                    void refetchProviders();
                    void refetch();
                  }}
                  testId="voice-language-key-field"
                />
              }
            />
          )}
          <Row label={t("voiceui.language.sample")} below={sample ? <SampleResult outcome={sample} /> : undefined}>
            <Button
              variant="outline"
              onClick={() => void runSample()}
              disabled={busy}
              data-testid="voice-language-test"
            >
              {t(testing ? "voiceui.language.testing" : "voiceui.language.test")}
            </Button>
          </Row>
        </Group>
      )}
    </VoicePage>
  );
}

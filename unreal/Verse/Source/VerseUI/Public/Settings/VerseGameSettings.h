#pragma once

#include "Audio/VerseAudioTypes.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "GenericPlatform/GenericWindow.h"
#include "Scalability.h"

/**
 * The in-game settings menu (docs/verse/unreal/game-settings.md). One catalogue,
 * dodaios/verse_host/game_settings.py, lists every setting; Unreal reads its copy
 * Data/ui/game_settings.json (a unit test keeps the two equal). The values travel in
 * welcome.settings.game, settings.changed {game} and settings.set {game} (bridge-protocol 3.2,
 * 12, 14), flat by setting id. The app config is their truth; the user settings file only caches.
 */

enum class EVerseGameSettingKind : uint8
{
	Choice,
	Toggle,
	Range,
	Key,
};

/** One catalogue entry. */
struct VERSEUI_API FVerseGameSettingDef
{
	FString Id;
	FString Tab;
	FString Section;
	EVerseGameSettingKind Kind = EVerseGameSettingKind::Toggle;
	TArray<FString> Options;
	double Min = 0.0;
	double Max = 0.0;
	double Step = 1.0;
	/** Display hint: "%", "°", "x" or empty. */
	FString Unit;
	TSharedPtr<FJsonValue> Default;
	/**
	 * Legacy place in welcome.settings ("gore", "view.volume", "return_key"); empty when the
	 * value lives in settings.game. Legacy values stay in FVerseAppSettings' own fields.
	 */
	FString Path;
	bool bRestart = false;
	/** A quality group the preset sets at once. */
	bool bPresetGroup = false;

	/** Value checked and normalised for this entry; false when it does not fit. */
	bool Check(const TSharedPtr<FJsonValue>& Value, TSharedPtr<FJsonValue>& Out) const;
	int32 OptionIndex(const FString& Option) const { return Options.IndexOfByKey(Option); }
};

/** The catalogue as Unreal reads it. */
class VERSEUI_API FVerseGameSettingsCatalogue
{
public:
	/** The shipped catalogue, loaded once from DefaultPath(). */
	static const FVerseGameSettingsCatalogue& Get();
	/** <project>/Data/ui/game_settings.json */
	static FString DefaultPath();

	bool LoadJson(const FString& Json, FString* OutError = nullptr);
	bool LoadFile(const FString& Path, FString* OutError = nullptr);

	const TArray<FVerseGameSettingDef>& GetSettings() const { return Settings; }
	const TArray<FString>& GetTabs() const { return Tabs; }
	const TArray<FString>& GetPresetGroups() const { return PresetGroups; }
	const FVerseGameSettingDef* Find(const FString& Id) const;

private:
	TArray<FVerseGameSettingDef> Settings;
	TMap<FString, int32> Index;
	TArray<FString> Tabs;
	TArray<FString> PresetGroups;
};

/**
 * The values of settings.game: only ids the catalogue keeps there (no legacy path). A missing
 * id reads as its default; unknown ids and values the catalogue refuses are ignored.
 */
struct VERSEUI_API FVerseGameSettings
{
	/** Applies a settings.game object (all of it or a subset). Returns how many values changed. */
	int32 ApplyJson(const TSharedPtr<FJsonObject>& Game);
	/** Every id with its current value. */
	TSharedRef<FJsonObject> ToJson() const;
	/** The ids where Other differs from this, with Other's values. */
	TSharedRef<FJsonObject> Diff(const FVerseGameSettings& Other) const;

	/** Current value (the default when unset); null for an unknown or legacy id. */
	TSharedPtr<FJsonValue> GetValue(const FString& Id) const;
	/** Sets one value after the catalogue check; false when refused. */
	bool Set(const FString& Id, const TSharedPtr<FJsonValue>& Value);

	bool GetBool(const FString& Id) const;
	double GetNumber(const FString& Id) const;
	FString GetString(const FString& Id) const;
	bool SetBool(const FString& Id, bool bValue) { return Set(Id, MakeShared<FJsonValueBoolean>(bValue)); }
	bool SetNumber(const FString& Id, double Value) { return Set(Id, MakeShared<FJsonValueNumber>(Value)); }
	bool SetString(const FString& Id, const FString& Value) { return Set(Id, MakeShared<FJsonValueString>(Value)); }

	/** Quality level index of a quality choice: low 0 .. cinematic 4; -1 for auto or custom. */
	static int32 QualityIndex(const FString& Level);
	static FString QualityName(int32 Index);

	static bool SameValue(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B);

private:
	TMap<FString, TSharedPtr<FJsonValue>> Values;
};

/** What the graphics settings ask of the engine, computed without touching it (tests read it). */
struct VERSEUI_API FVerseGraphicsPlan
{
	EWindowMode::Type WindowMode = EWindowMode::WindowedFullscreen;
	/** Pixels; the desktop resolution for "native". */
	FIntPoint Resolution = FIntPoint::ZeroValue;
	/** 0 = unlimited. */
	float FrameLimit = 0.f;
	bool bVSync = false;
	/** Applied at the next start (restart flag in the catalogue). */
	bool bHdr = false;
	/** GEngine->DisplayGamma: 2.2 at brightness 50, 1.6 .. 2.8 over 0 .. 100. */
	float DisplayGamma = 2.2f;
	/** r.AntiAliasingMethod: 0 off, 1 FXAA, 2 TAA, 4 TSR. */
	int32 AntiAliasingMethod = 4;
	/** r.ScreenPercentage */
	float ScreenPercentage = 100.f;
	/** r.Tonemapper.Sharpen, 0 .. 1. */
	float Sharpen = 0.2f;
	/** Preset auto: the engine's hardware benchmark picks the levels. */
	bool bAutoQuality = true;
	Scalability::FQualityLevels Quality;

	bool bMotionBlur = false;
	bool bDepthOfField = true;
	bool bFilmGrain = false;
	bool bChromaticAberration = false;
	bool bLensFlares = true;
	bool bBloom = true;

	static FVerseGraphicsPlan Build(const FVerseGameSettings& Game, const FIntPoint& Desktop);
};

/** What the audio settings ask of the Verse mix (VerseAudioSubsystem). */
struct VERSEUI_API FVerseAudioPlan
{
	/** Linear user gain per EVerseAudioBus. */
	TArray<float> BusGain;
	bool bMuteUnfocused = true;

	/**
	 * @param Game      settings.game
	 * @param bUiSound  welcome.settings.ui_sound (menu sounds on the UI bus)
	 */
	static FVerseAudioPlan Build(const FVerseGameSettings& Game, bool bUiSound);
};

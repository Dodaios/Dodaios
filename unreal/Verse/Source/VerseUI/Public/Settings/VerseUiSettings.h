#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "InputCoreTypes.h"
#include "UObject/Object.h"

#include "VerseUiSettings.generated.h"

/**
 * App-backed Verse settings (bridge-protocol 3.2 welcome.settings). The app config is their
 * truth: Verse reads them from welcome, applies settings.changed live and writes them with
 * settings.set (bridge-protocol 14), so they survive a Verse restart in the app config.
 */
struct VERSEUI_API FVerseAppSettings
{
	EVerseGoreLevel Gore = EVerseGoreLevel::Full;
	bool bReducedMotion = false;
	FKey ReturnKey = EKeys::F10;
	bool bUiSound = true;
	bool bLevelSound = true;
	FString Uniform = TEXT("standard");
	/** "third" | "first" | "overview" */
	FString ViewMode = TEXT("third");
	float Sensitivity = 1.f;
	bool bInvertY = false;
	/** Deck view FOVs (parity V-09). */
	float FovThird = 70.f;
	float FovFirst = 85.f;
	FString Quality = TEXT("auto");
	float Volume = 0.7f;

	/** Reads welcome.settings, or applies a settings.changed / settings.set subset over this. */
	void ApplyJson(const TSharedPtr<FJsonObject>& Json);
	/** The full welcome.settings object. */
	TSharedRef<FJsonObject> ToJson() const;
	/** The subset of fields where Other differs from this, in settings.set shape. */
	TSharedRef<FJsonObject> Diff(const FVerseAppSettings& Other) const;

	static FString GoreToString(EVerseGoreLevel Level);
	static bool GoreFromString(const FString& Text, EVerseGoreLevel& Out);
};

USTRUCT()
struct VERSEUI_API FVerseKeyBinding
{
	GENERATED_BODY()

	UPROPERTY(Config)
	FName Action;

	UPROPERTY(Config)
	FKey Key;
};

/**
 * Unreal-only settings, in Unreal's user settings file (GameUserSettings.ini), so they survive
 * a restart without the app (WP18.8): duel FOV, key bindings except the return key,
 * scalability, text size, last tier.
 */
UCLASS(Config = GameUserSettings, ConfigDoNotCheckDefaults)
class VERSEUI_API UVerseUiUserSettings : public UObject
{
	GENERATED_BODY()

public:
	static constexpr float DuelFovMin = 80.f;
	static constexpr float DuelFovMax = 110.f;
	/** bot.md 3.1 sizes the bot's view cone from this default. */
	static constexpr float DuelFovDefault = 100.f;

	/** Horizontal FOV in the duel, 80-110. */
	UPROPERTY(Config)
	float DuelFov = DuelFovDefault;

	UPROPERTY(Config)
	TArray<FVerseKeyBinding> KeyBindings;

	/** -1 = auto (the engine's benchmark), 0..4 = low..cinematic. */
	UPROPERTY(Config)
	int32 Scalability = -1;

	/** Accessibility text size, 0.8-1.6. */
	UPROPERTY(Config)
	float TextScale = 1.f;

	/** Last tier chosen at the armoury: normal, hard, elite, adaptive. */
	UPROPERTY(Config)
	FName LastTier = TEXT("hard");

	/** Bumped on each save (tests read it back). */
	UPROPERTY(Config)
	int32 SaveCount = 0;

	void Clamp();
	void SaveToDisk();
	void ReloadFromDisk();
};

/** Commands keys can trigger in the UI layer. Gameplay actions belong to the input owners. */
enum class EVerseUiCommand : uint8
{
	None,
	ReturnToApp,
	EscMenu,
	SkipKillCam,
	VerseBar,
};

/**
 * The bindable actions and their default keys (unreal/Verse/Data/ui/keys.json), and the
 * person's current choice. The return key is app-backed (welcome.settings.return_key); every
 * other binding lives in UVerseUiUserSettings.
 */
class VERSEUI_API FVerseKeyMap
{
public:
	struct FAction
	{
		FName Action;
		FKey DefaultKey;
		/** strings key of the label. */
		FString LabelKey;
		/** The UI handles it itself (return, Esc menu, skip, bar); others are gameplay input. */
		EVerseUiCommand Command = EVerseUiCommand::None;
	};

	static FName ReturnAction() { return TEXT("return_to_app"); }

	/** <project>/Data/ui/keys.json */
	static FString DefaultPath();
	bool LoadJson(const FString& Json, FString* OutError = nullptr);
	bool LoadFile(const FString& Path, FString* OutError = nullptr);

	const TArray<FAction>& GetActions() const { return Actions; }
	const FAction* FindAction(FName Action) const;

	/** Current key (user choice, else default). The return key comes from the app settings. */
	FKey GetKey(FName Action) const;

	/** Takes the person's bindings; unknown actions are dropped. */
	void SetBindings(const TArray<FVerseKeyBinding>& Bindings);
	TArray<FVerseKeyBinding> GetBindings() const;
	void SetReturnKey(const FKey& Key) { ReturnKey = Key; }

	/**
	 * Binds Key to Action. When another action already has Key it gets Action's old key (swap),
	 * so no key is ever bound twice. Returns the action that was swapped, or NAME_None.
	 */
	FName Rebind(FName Action, const FKey& Key);

	/** Keys a binding may never take (Esc is the menu, the system keys stay the system's). */
	static bool IsReserved(const FKey& Key);

	/** What a key press does in the UI layer. */
	EVerseUiCommand Route(const FKey& Key) const;

private:
	TArray<FAction> Actions;
	TMap<FName, FKey> Overrides;
	FKey ReturnKey = EKeys::F10;
};

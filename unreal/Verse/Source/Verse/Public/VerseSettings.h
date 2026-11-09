#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"

#include "VerseSettings.generated.h"

/**
 * Per-viewer Verse settings, saved in the local GameUserSettings.ini and never
 * replicated (contracts/combat-state.md 8).
 */
UCLASS(Config = GameUserSettings, meta = (DisplayName = "Verse"))
class VERSE_API UVerseSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	virtual FName GetCategoryName() const override { return TEXT("Game"); }

	/** Full (default) or Reduced: no blood, finishers cut away (README Gore). */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "Gore")
	EVerseGoreLevel GoreLevel = EVerseGoreLevel::Full;

	// View settings (combat-state.md 8). VerseUI writes them from the Esc menu as it writes
	// GoreLevel (GameUserSettings plus this class default object); the camera (WP01), bot
	// perception (WP07) and audio (WP19) read them.

	/** Duel horizontal field of view in degrees; bot.md 3.1 sizes the bot's view cone from it. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View", meta = (ClampMin = "80", ClampMax = "110"))
	float DuelFovDeg = 100.f;

	/** Look sensitivity multiplier. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View", meta = (ClampMin = "0.05", ClampMax = "5"))
	float LookSensitivity = 1.f;

	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View")
	bool bInvertLookY = false;

	/** Deck field of view in third person, degrees. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View", meta = (ClampMin = "50", ClampMax = "120"))
	float DeckFovThirdDeg = 70.f;

	/** Deck field of view in first person, degrees. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View", meta = (ClampMin = "50", ClampMax = "120"))
	float DeckFovFirstDeg = 85.f;

	/** Master volume, 0..1. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "Audio", meta = (ClampMin = "0", ClampMax = "1"))
	float MasterVolume = 0.7f;

	/** Less camera shake and fewer full-screen effects. */
	UPROPERTY(Config, EditAnywhere, BlueprintReadOnly, Category = "View")
	bool bReducedMotion = false;
};

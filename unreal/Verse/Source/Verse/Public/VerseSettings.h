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
};

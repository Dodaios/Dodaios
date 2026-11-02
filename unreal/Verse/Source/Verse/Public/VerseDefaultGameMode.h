#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"

#include "VerseDefaultGameMode.generated.h"

/**
 * Project default game mode (Config/DefaultEngine.ini GlobalDefaultGameMode). It only
 * names the default classes; rules belong to VerseCombat's swappable ruleset
 * (contracts/combat-state.md 10), wired in during integration.
 */
UCLASS()
class VERSE_API AVerseDefaultGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	AVerseDefaultGameMode();
};

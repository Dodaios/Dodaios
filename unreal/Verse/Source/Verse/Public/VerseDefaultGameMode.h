#pragma once

#include "CoreMinimal.h"
#include "Rules/VerseGameMode.h"

#include "VerseDefaultGameMode.generated.h"

class APawn;

/**
 * Project default game mode (Config/DefaultEngine.ini GlobalDefaultGameMode): VerseCombat's
 * AVerseGameMode (ruleset forwarder, AVersePlayerState, spawn selection; combat-state.md 10)
 * with the primary module's default pawn and controller. It adds the one step the combat module
 * cannot take without knowing the pawn class: every spawned pawn gets the loadout (2.2).
 */
UCLASS()
class VERSE_API AVerseDefaultGameMode : public AVerseGameMode
{
	GENERATED_BODY()

public:
	AVerseDefaultGameMode();

	virtual void SetPlayerDefaults(APawn* PlayerPawn) override;

	/**
	 * Server: hands the loadout to a pawn's inventory and gadget components. Slots the ruleset
	 * config leaves empty fall back to the start loadout of 2.2 from the weapon registry.
	 * Returns the number of slots filled (firearms plus gadgets).
	 */
	int32 GiveLoadout(APawn* Pawn);
};

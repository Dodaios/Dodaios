#pragma once

#include "CoreMinimal.h"

#include "VerseCombatTypes.generated.h"

// Shared combat enums (contracts/combat-state.md 11.1). The order of every entry
// is frozen: replicated values and saved settings depend on it. G0.3 adds the
// remaining types of 11.1 to this file.

UENUM(BlueprintType)
enum class EVerseCombatPhase : uint8
{
	Alive,
	Dead,
	FinisherAttacker,
	FinisherVictim
};

UENUM(BlueprintType)
enum class EVerseGoreLevel : uint8
{
	Full,
	Reduced
};

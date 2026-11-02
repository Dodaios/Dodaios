#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "UObject/Interface.h"

#include "VerseMovementQuery.generated.h"

UINTERFACE(MinimalAPI, meta = (CannotImplementInterfaceInBlueprint))
class UVerseMovementQuery : public UInterface
{
	GENERATED_BODY()
};

/**
 * Read-only movement state other modules see (combat-state.md 2.1; architecture 3.3: nothing
 * else touches the CharacterMovementComponent). VerseMovement implements it on its movement
 * component; Combat, Bot and the animation layer read it. Combat never writes stance.
 */
class VERSECORE_API IVerseMovementQuery
{
	GENERATED_BODY()

public:
	/** Lean is replicated as int8, -127..127 = -1..1; lean > 0 moves toward the pawn's right. */
	static float LeanFromQuantized(int8 Quantized) { return float(Quantized) / 127.f; }
	static int8 QuantizeLean(float Lean) { return int8(FMath::Clamp(FMath::RoundToInt(Lean * 127.f), -127, 127)); }

	virtual EVerseStance GetStance() const = 0;
	virtual bool IsSprinting() const = 0;
	virtual bool IsAirborne() const = 0;
	virtual bool IsMantling() const = 0;
	/** -127..127 */
	virtual int8 GetLeanQuantized() const = 0;
	/** Mantling and sprinting block firing (combat-state.md 2.1). */
	virtual bool BlocksFiring() const { return IsSprinting() || IsMantling(); }
};

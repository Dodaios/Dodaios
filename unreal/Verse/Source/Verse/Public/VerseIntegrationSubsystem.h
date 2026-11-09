#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseIntegrationSubsystem.generated.h"

class APawn;

/**
 * Seams between feature modules that may not include each other (architecture.md 2), wired by
 * the primary module when a game world begins play:
 *
 * - kill cam fracture replay: UVerseUiSubsystem::OnKillCamFracture (VerseUI) redraws through
 *   UVerseDebrisSubsystem::ReplayFracture (VerseDestruction), destruction.md 4.
 * - bolts and sight through pieces: UVerseProjectileManager and UVersePerceptionService (VerseCombat)
 *   trace through UVersePenetrationSubsystem (VerseDestruction), and bolt and breach damage reach
 *   AVerseDestructionManager's piece damage (destruction.md 2, 5). Re-bound every second, so a
 *   destruction manager that arrives later (runtime arena) is picked up.
 * - per pawn (AVerseDefaultCharacter::BeginPlay): lag compensation target, gadget penetration
 *   and piece damage (BindPawn).
 */
UCLASS()
class VERSE_API UVerseIntegrationSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;

	/** Binds the kill cam fracture hook in a world; false when either side is missing there. */
	static bool BindKillCamFracture(UWorld& World);

	/** Binds the bolt, sight and piece damage seams of a world; false when a side is missing. */
	static bool BindCombatSeams(UWorld& World);

	/** Server: registers a pawn's hit bodies for lag compensation and wires its gadgets. */
	static void BindPawn(APawn& Pawn);
	static void UnbindPawn(APawn& Pawn);

private:
	FTimerHandle RebindTimer;
};

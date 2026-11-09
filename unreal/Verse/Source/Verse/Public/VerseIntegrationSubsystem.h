#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseIntegrationSubsystem.generated.h"

/**
 * Seams between feature modules that may not include each other (architecture.md 2), wired by
 * the primary module when a game world begins play:
 *
 * - kill cam fracture replay: UVerseUiSubsystem::OnKillCamFracture (VerseUI) redraws through
 *   UVerseDebrisSubsystem::ReplayFracture (VerseDestruction), destruction.md 4.
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
};

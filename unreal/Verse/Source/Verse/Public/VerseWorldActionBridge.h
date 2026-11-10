#pragma once

#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "WorldActions/VerseWorldActionReporter.h"

#include "VerseWorldActionBridge.generated.h"

/**
 * The seam between the deck world actions (VerseDecks) and the bridge (VerseBridge), which may not
 * include each other (architecture.md 2). The primary module wires them (parity W-01..W-03):
 *
 * - the lifecycle becoming Visible tells the deck subsystem (`daily_visit` on the first one of a launch);
 * - every world action of the deck subsystem is sent as a `progression.action` command.
 */
UCLASS()
class VERSE_API UVerseWorldActionBridge : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;

	/** Sends the held actions when the link is up; called on every action and lifecycle change. */
	void Flush();

	/** Actions waiting for the link. */
	TArray<FVerseWorldAction> Pending;

	// No Deinitialize: the delegates live on the bridge and deck subsystems and die with them; the
	// engine tears subsystems down in no order this class can rely on.
};

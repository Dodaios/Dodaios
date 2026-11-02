#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseDuelReporterSubsystem.generated.h"

/**
 * Binds the process duel reporter (VerseDuel::ProcessReporter) to the hub of each game world,
 * so every FVerseSetSummary raised on UVerseEventHub::OnSetEnded becomes one duel.result.
 * Reads Core types only; never includes VerseCombat (combat-state.md 11.2).
 */
UCLASS()
class UVerseDuelReporterSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

protected:
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
};

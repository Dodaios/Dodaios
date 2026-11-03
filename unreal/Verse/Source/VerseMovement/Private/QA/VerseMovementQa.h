#pragma once

#include "Containers/Ticker.h"
#include "CoreMinimal.h"
#include "Subsystems/EngineSubsystem.h"

#include "VerseMovementQa.generated.h"

class ACameraActor;
class AVerseCharacter;

/**
 * Verse.QA.Movement.* commands (work-packages.md 0.2: each package registers its own) and the
 * command-line drivers the netcode soak and the evidence capture use:
 *   -VerseMovementSoak=<seconds>:<seed>:<report.json>   drive the local pawn, write its corrections, quit
 *   -VerseMovementShoot=<folder>                         capture mantle, slide and lean shots, quit
 */
UCLASS()
class UVerseMovementQa : public UEngineSubsystem
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

private:
	bool Tick(float DeltaSeconds);
	bool StartSoak(float Seconds, uint64 Seed, const FString& Report, bool bQuit);
	bool StartShoot(const FString& Folder);
	void TickShoot(float DeltaSeconds);

	FTSTicker::FDelegateHandle TickHandle;
	TArray<FString> Registered;

	// Pending command-line drivers (they wait for a possessed pawn).
	float PendingSoakSeconds = 0.f;
	uint64 PendingSoakSeed = 0;
	FString PendingSoakReport;
	FString PendingShootFolder;
	float WaitTime = 0.f;

	// Running soak.
	TWeakObjectPtr<AVerseCharacter> SoakPawn;
	FString SoakReport;
	float SoakSeconds = 0.f;
	float SoakElapsed = 0.f;
	bool bSoakRunning = false;
	bool bSoakQuit = false;

	// Running capture.
	TWeakObjectPtr<AVerseCharacter> ShootPawn;
	TWeakObjectPtr<ACameraActor> ShootCamera;
	FString ShootFolder;
	int32 ShootStep = -1;
	float ShootTime = 0.f;
	bool bShotTaken = false;
};

#pragma once

#include "Containers/Ticker.h"
#include "CoreMinimal.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "VerseRng.h"

#include "VerseHarnessSubsystem.generated.h"

class UVerseBalanceGauntletController;
class UVerseCaptureDirector;

/**
 * Entry point of every harness run inside a game process. Reads the command line once the
 * game world is up and starts the matching driver:
 *
 * - -VerseHarness=<scenario.json>: balance bouts (UVerseBalanceGauntletController).
 * - -VerseCapture=<capture.json> -VerseCaptureOut=<dir> [-VersePerf]: screenshots or perf replay.
 * - -VerseNetDuration=<s> [-VerseNetAutopilot=<seed>]: netcode test; the server logs
 *   "[VerseNet] server ready", clients walk with seeded input; both exit after the duration.
 *
 * Without any of these switches it does nothing, so loading the module in the editor is free.
 */
UCLASS()
class VERSEHARNESS_API UVerseHarnessSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	/** True when the command line asks for any harness run. */
	static bool IsHarnessRun();

private:
	bool TickHarness(float DeltaS);
	void StartDrivers(UWorld* World);
	void TickNet(UWorld* World, float DeltaS);
	void Quit(const TCHAR* Why);

	FTSTicker::FDelegateHandle TickHandle;

	UPROPERTY()
	TObjectPtr<UVerseBalanceGauntletController> Balance;

	UPROPERTY()
	TObjectPtr<UVerseCaptureDirector> Capture;

	bool bStarted = false;
	bool bQuitRequested = false;
	double NetDurationS = 0.0;
	double NetStartS = -1.0;
	bool bAutopilot = false;
	FVerseRng AutopilotRng;
	FVector2D AutopilotMove = FVector2D::ZeroVector;
	double NextTurnS = 0.0;
	int64 AutopilotTicks = 0;
	double StartWallS = 0.0;
};

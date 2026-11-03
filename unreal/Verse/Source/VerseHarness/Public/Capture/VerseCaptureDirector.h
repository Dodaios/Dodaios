#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseCaptureDirector.generated.h"

class ACameraActor;
class UWorld;

/** One reference view or keyframe of a verse.capture/1 file (Unreal cm and degrees). */
struct VERSEHARNESS_API FVerseCaptureView
{
	FString Id;
	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	float FovDeg = 90.f;
	/** Keyframe time (flythrough) or shot time (shots), seconds. */
	double T = 0.0;
};

struct VERSEHARNESS_API FVerseCaptureScript
{
	FString Id;
	TArray<FVerseCaptureView> Views;
	int32 SettleFrames = 30;
	double WarmupS = 0.0;
	double FlythroughS = 0.0;
	TArray<FVerseCaptureView> Keys;
	TArray<FVerseCaptureView> Shots;

	static bool Parse(const FString& JsonText, FVerseCaptureScript& Out, FString& OutError);

	/** Camera pose along the flythrough at time T (linear, clamped at both ends). */
	FVerseCaptureView Sample(double T) const;
};

/**
 * Scripted camera for capture.py and perf.py (work-packages.md WP10.7, 10.8): places a camera
 * at each reference view, waits for shader compiles, async loading and streaming plus settle
 * frames, and writes <out>/<view>.png without UI; or flies the perf replay path, starting the
 * CSV profiler after the warm-up (-VersePerf) and stopping it before exit.
 */
UCLASS()
class VERSEHARNESS_API UVerseCaptureDirector : public UObject
{
	GENERATED_BODY()

public:
	bool Start(UWorld* InWorld, const FVerseCaptureScript& InScript, const FString& InOutDir, bool bInPerf,
		FString& OutError);

	/** One frame; false once done and exit was requested. */
	bool Tick(float DeltaS);

private:
	bool EnsureCamera();
	bool SceneIsReady() const;
	void Place(const FVerseCaptureView& View);
	void Shoot(const FString& Id);
	void Finish();

	TWeakObjectPtr<UWorld> World;
	TWeakObjectPtr<ACameraActor> Camera;
	FVerseCaptureScript Script;
	FString OutDir;
	bool bPerf = false;
	int32 ViewIndex = 0;
	int32 SettleLeft = 0;
	int32 PendingFrames = 0;
	FString PendingFile;
	double FlyStartS = -1.0;
	double ElapsedS = 0.0;
	int32 NextShot = 0;
	bool bProfiling = false;
	double StopAtS = -1.0;
	bool bDone = false;
	TArray<FString> Written;
};

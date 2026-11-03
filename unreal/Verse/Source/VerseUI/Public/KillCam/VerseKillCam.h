#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

/**
 * Client ring buffer of the last seconds of the fight (WP18.5): every visible pawn's pose,
 * fire events and fracture events, stamped with server time so they line up with
 * FVerseDeathEvent::ServerTime. Pure C++.
 */
class VERSEUI_API FVerseKillCamBuffer
{
public:
	struct FPoseSample
	{
		double Time = 0.0;
		FVector Location = FVector::ZeroVector;
		FRotator Rotation = FRotator::ZeroRotator;
	};
	struct FFireSample
	{
		double Time = 0.0;
		FVerseFireEvent Event;
	};
	struct FFractureSample
	{
		double Time = 0.0;
		FVerseFractureEvent Event;
	};

	/** Seconds kept (4 s, work-packages WP18.5). */
	double Window = 4.0;

	void Reset();
	void AddPose(int32 PlayerId, double ServerTime, const FVector& Location, const FRotator& Rotation);
	void AddFire(const FVerseFireEvent& Event, double ServerTime);
	void AddFracture(const FVerseFractureEvent& Event, double ServerTime);
	/** Drops everything older than Window before Now. */
	void Trim(double ServerNow);

	/** Interpolated pose at Time; false when the player has no samples around it. */
	bool PoseAt(int32 PlayerId, double Time, FVector& OutLocation, FRotator& OutRotation) const;
	/** Earliest time the player has a sample for, or +inf. */
	double EarliestPose(int32 PlayerId) const;

	const TArray<FFireSample>& GetFires() const { return Fires; }
	const TArray<FFractureSample>& GetFractures() const { return Fractures; }
	int32 NumPoses(int32 PlayerId) const;

private:
	TMap<int32, TArray<FPoseSample>> Poses;
	TArray<FFireSample> Fires;
	TArray<FFractureSample> Fractures;
};

enum class EVerseKillCamState : uint8
{
	Idle,
	Playing,
	Finished,
	Skipped,
};

/** Tuning (unreal/Verse/Data/ui/hud.json "kill_cam"). */
struct VERSEUI_API FVerseKillCamTuning
{
	/** End at least this long before respawn (A18.2 asks 200 ms; 250 leaves a frame of slack). */
	float EndMarginS = 0.25f;
	/** Shortest replay worth starting. */
	float MinLengthS = 0.5f;
	/** Third-person camera behind the killer, cm. */
	float CameraBack = 260.f;
	float CameraUp = 70.f;
	float CameraRight = 45.f;
	/** Finisher kills are cut before the takedown when gore is reduced (README Gore). */
	float FinisherCutS = 2.5f;
};

/**
 * Plays one kill cam: the killer's last seconds in third person while the person waits to
 * respawn (A18.2: starts on the death event's frame, ends before respawn, killer path from the
 * buffer). Replayed fire and fracture events go out through the callbacks so VFX and the
 * destruction client can redraw them.
 */
class VERSEUI_API FVerseKillCamPlayer
{
public:
	FVerseKillCamTuning Tuning;
	TFunction<void(const FVerseFireEvent&)> OnReplayFire;
	TFunction<void(const FVerseFractureEvent&)> OnReplayFracture;

	/**
	 * Starts on a death of the local player. Copies the clip out of the buffer, so recording can
	 * go on. False (and Idle) for a suicide, a world kill, no killer samples, or no time left.
	 */
	bool Begin(const FVerseKillCamBuffer& Buffer, const FVerseDeathEvent& Death, int32 LocalPlayerId,
		double LocalNow, double ServerNow, bool bCutFinisher);

	/** Advances; fires replayed events crossed since the last tick. */
	void Tick(double LocalNow);
	void Skip(double LocalNow);
	void Stop();

	EVerseKillCamState GetState() const { return State; }
	bool IsPlaying() const { return State == EVerseKillCamState::Playing; }
	int32 GetKillerId() const { return KillerId; }

	/** Server time being shown. */
	double GetReplayTime() const { return ReplayTime; }
	double GetClipStart() const { return ClipStart; }
	double GetClipEnd() const { return ClipEnd; }
	/** Local time the replay started and ends (planned). */
	double GetPlayStart() const { return PlayStart; }
	double GetPlannedEnd() const { return PlayStart + (ClipEnd - ClipStart); }
	double GetEndedAt() const { return EndedAt; }

	/** The killer's pose at the replay time. */
	bool GetKillerPose(FVector& OutLocation, FRotator& OutRotation) const;
	/** Third-person camera looking past the killer at the replay time. */
	bool GetCamera(FVector& OutLocation, FRotator& OutRotation) const;

private:
	FVerseKillCamBuffer Clip;
	EVerseKillCamState State = EVerseKillCamState::Idle;
	int32 KillerId = INDEX_NONE;
	double ClipStart = 0.0;
	double ClipEnd = 0.0;
	double PlayStart = 0.0;
	double ReplayTime = 0.0;
	double EndedAt = 0.0;
	int32 NextFire = 0;
	int32 NextFracture = 0;
};

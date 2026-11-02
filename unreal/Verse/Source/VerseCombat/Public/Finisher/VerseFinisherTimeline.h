#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Melee/VerseMeleeRules.h"

#include "VerseFinisherTimeline.generated.h"

/**
 * The finisher timeline of combat-state.md 7.4 as pure code: the frozen phase offsets, the
 * server session (validate happened before; lock, phases, kill, abort, release), the paired
 * pose and warp, the victim snap, the camera rules and the knife presentation. Everything here
 * is deterministic in server time, so the server and every client derive the same phase and
 * pose from FVerseFinisherEvent::SequenceStartServerTime alone.
 */
namespace VerseFinisher
{
	inline constexpr double TakedownAt = 0.25;
	inline constexpr double StruggleAt = 0.9;
	inline constexpr double KillAt = 1.8;
	/** Death is applied when Recover starts. */
	inline constexpr double RecoverAt = 2.1;
	inline constexpr double EndAt = 2.5;
	inline constexpr double TimeTolerance = 1e-4;
	/** A client that learns of the finisher less than this before Takedown snaps the attacker instead of blending. */
	inline constexpr double MinWarpS = 0.05;

	/** Offset of a phase from the sequence start; Aborted has none (-1). */
	VERSECOMBAT_API double PhaseOffset(EVerseFinisherPhase Phase);

	/** Phase at Elapsed seconds after Locked (Locked before 0, Recover from 2.1 on). */
	VERSECOMBAT_API EVerseFinisherPhase PhaseAt(double Elapsed);

	/** The sequence has ended (both pawns released). */
	inline bool IsOver(double Elapsed) { return Elapsed + TimeTolerance >= EndAt; }
}

/** One phase entered by the server session, stamped with the server time it was entered at. */
struct FVerseFinisherStep
{
	EVerseFinisherPhase Phase = EVerseFinisherPhase::Locked;
	double ServerTime = 0.0;
};

/**
 * Server-side finisher sequence. Once Start ran (the press passed 7.2 and both pawns are
 * locked), Advance walks the phases on each server tick. The kill is applied exactly when
 * Recover is entered, unless the attacker died before t = 2.1 s (D5): then the session goes to
 * Aborted at the attacker's death time and the victim is released with its health untouched.
 */
struct VERSECOMBAT_API FVerseFinisherSession
{
	static constexpr double NoDeath = 1.0e30;

	double StartTime = 0.0;
	EVerseFinisherPhase Phase = EVerseFinisherPhase::Locked;
	bool bActive = false;
	bool bKillApplied = false;
	bool bAborted = false;
	bool bReleased = false;

	void Start(double Now);

	/**
	 * Advances to Now. AttackerDeathTime is the server time the attacker died (NoDeath while
	 * alive). Appends every phase entered since the last call, in order. Returns true on the call
	 * that releases both pawns (t = 2.5 s, or the abort).
	 */
	bool Advance(double Now, double AttackerDeathTime, TArray<FVerseFinisherStep>& OutEntered);

	double Elapsed(double Now) const { return Now - StartTime; }
};

/** Pose math of the paired finisher (4.4 warp, 4.6 victim snap). Transforms are actor transforms. */
struct VERSECOMBAT_API FVerseFinisherPose
{
	/**
	 * The paired pose: the victim keeps its location and turns its back to the attacker; the
	 * attacker's Warp_Finisher target is PairedOffsetCm behind the victim, facing the same way,
	 * at the attacker's own height (both stand on their floors, |dz| <= 0.6 m).
	 */
	static void ComputePaired(const FTransform& Attacker, const FTransform& Victim, double PairedOffsetCm,
		FTransform& OutVictim, FTransform& OutWarpTarget);

	/** The victim's paired pose as a client derives it from the event's WarpTarget (Z from the victim). */
	static FTransform VictimFromWarpTarget(const FTransform& WarpTarget, double PairedOffsetCm, double VictimZ);

	/**
	 * Attacker pose during the warp. StartPose was sampled at StartElapsed (0 on the server, the
	 * receive time on a client); the pose reaches Target exactly at Takedown (0.25 s) with a
	 * smoothstep and holds it afterwards. A client that learns of the finisher after Takedown snaps.
	 */
	static FTransform EvaluateWarp(const FTransform& StartPose, double StartElapsed, const FTransform& Target, double Elapsed);

	/** Victim correction on a client: smoothstep from the local pose to the paired pose over SnapS. */
	static FTransform EvaluateSnap(const FTransform& From, const FTransform& To, double SinceLocked, double SnapS);

	/** Horizontal plus vertical position error, cm. */
	static double PositionErrorCm(const FTransform& A, const FTransform& B) { return FVector::Dist(A.GetLocation(), B.GetLocation()); }
};

/** What a viewer of the finisher sees (4.5). */
UENUM(BlueprintType)
enum class EVerseFinisherView : uint8
{
	FirstPerson,
	ThirdPerson,
	/** Gore Reduced: cut away from Takedown to Recover (combat-state.md 8). */
	Black
};

struct VERSECOMBAT_API FVerseFinisherViewState
{
	EVerseFinisherView View = EVerseFinisherView::FirstPerson;
	/** The attacker holds the knife (Weapon_L) from Locked to the end. */
	bool bKnifeInHand = false;
	/** At 2.5 s (or on an abort) the active weapon is back in hand. */
	bool bActiveWeaponEquipped = true;

	bool operator==(const FVerseFinisherViewState& O) const
	{
		return View == O.View && bKnifeInHand == O.bKnifeInHand && bActiveWeaponEquipped == O.bActiveWeaponEquipped;
	}
};

namespace VerseFinisher
{
	/** Camera and hands at Elapsed seconds after Locked for a participant's own view. */
	VERSECOMBAT_API FVerseFinisherViewState EvaluateView(double Elapsed, bool bAborted, EVerseGoreLevel Gore);

	/**
	 * Third-person finisher camera: to the side of the pair at DistanceCm, HeightCm above the
	 * pair's base, looking at the pair's midpoint. Both participants use the same shot.
	 */
	VERSECOMBAT_API FTransform CameraTransform(const FTransform& Attacker, const FTransform& Victim,
		double DistanceCm, double HeightCm);
}

/** Animation state of the first-person knife (4.7). */
UENUM(BlueprintType)
enum class EVerseKnifeAnim : uint8
{
	Hidden,
	Equipping,
	Swinging,
	Recovering,
	Ready
};

/**
 * Predicted knife presentation on the owning client. A press starts the swing at once (the
 * server decides the outcome); the server's answer marks it a whiff, a strike or the start
 * of a finisher. A quick knife from another slot draws the knife during the swing and puts it
 * away afterwards, so the contact frame always lands at StrikeHitDelay.
 */
struct VERSECOMBAT_API FVerseKnifePresentation
{
	double EquipS = 0.12;
	double HitDelayS = 0.15;
	double RecoverS = 0.3;

	double PressTime = -1.0e9;
	bool bKnifeSlotActive = false;
	bool bNeedsEquip = false;
	bool bConfirmed = false;
	EVerseMeleeOutcome Confirmed = EVerseMeleeOutcome::Whiff;

	void Press(double Now, bool bKnifeSlot);
	void Confirm(EVerseMeleeOutcome Outcome);
	EVerseKnifeAnim Evaluate(double Now) const;
	bool IsWhiff() const { return bConfirmed && Confirmed == EVerseMeleeOutcome::Whiff; }
	/** Contact frame of the swing (hit spark or whiff swish). */
	double ContactTime() const { return PressTime + HitDelayS; }
};

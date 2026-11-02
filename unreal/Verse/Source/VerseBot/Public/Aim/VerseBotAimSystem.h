#pragma once

#include "Aim/VerseBotAimController.h"
#include "Aim/VerseBotFireGate.h"
#include "Aim/VerseBotNoSightFire.h"
#include "Aim/VerseBotReaction.h"
#include "Aim/VerseBotRecoilControl.h"
#include "Aim/VerseBotTargetTracker.h"
#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "VerseRng.h"

class UVerseBotTier;
class UVerseWeaponDefinition;

/** What the decision layer (WP08) asks of the aim this tick. */
struct VERSEBOT_API FVerseBotAimIntent
{
	/** Shoot a visible opponent once the reaction time has passed. */
	bool bEngage = true;
	/** Where to look when no target is tracked (pre-aim angle, search sweep), world cm. */
	bool bHasLookTarget = false;
	FVector LookTarget = FVector::ZeroVector;
	/** Fire without sight at LookTarget if FVerseBotNoSightFire authorises it (suppression, prefire, wall shot). */
	bool bWantNoSightFire = false;
	FVerseBotNoSightInput NoSight;
};

/** One tick of aim inputs. */
struct VERSEBOT_API FVerseBotAimInput
{
	/** The bot's own percept frame of this tick (own HUD and sightings). */
	const FVersePerceptFrame* Frame = nullptr;
	double DtS = 1.0 / 60.0;
	/** The active weapon's definition (public data: a practised person knows its pattern). */
	const UVerseWeaponDefinition* Weapon = nullptr;
	/** ADS blend 0..1 of the own weapon (own HUD). */
	double AdsBlend = 0.0;
	bool bSprinting = false;
	bool bSliding = false;
	bool bReloading = false;
	FVerseBotAimIntent Intent;
};

/** What the aim puts on the input frame, plus what it decided (presentation, audit, tests). */
struct VERSEBOT_API FVerseBotAimOutput
{
	FVector2f LookDeltaDeg = FVector2f::ZeroVector;
	/** EVerseInputButton bits (Fire, Ads). */
	uint32 Buttons = 0;
	uint32 Pressed = 0;
	/** Authority of a shot requested this tick; None when no Fire bit is set. */
	EVerseBotFireAuthority Authority = EVerseBotFireAuthority::None;
	EVerseBotFireBlock Block = EVerseBotFireBlock::NoTarget;
	/** Angle between the view after this tick and the aim point, degrees; negative without a point. */
	double AimErrorDeg = -1.0;
	/** A target is sighted but the reaction time has not passed yet. */
	bool bReacting = false;
	/** The target the aim follows, when it follows one. */
	bool bTracking = false;
	FVerseBotAimPoint AimPoint;
};

/**
 * The aim and fire layer of the bot (bot.md 8.1, 8.2, 8.4), run every server tick between the
 * percept frame and the input frame: reaction, tracking with latency and lead, the hand controller
 * with OU wander and turn cap, recoil control, the fire gate and the no-sight fire modes.
 *
 * It reads only the own percept frame and public weapon data (B2) and acts only through look delta
 * and buttons (B1). Given the seed, the tier and the same frames it returns the same outputs (B5).
 */
class VERSEBOT_API FVerseBotAimSystem
{
public:
	/** A sighting gap longer than this starts a new engagement with a new reaction, seconds (brain.ts 12 ticks). */
	static constexpr double ReengageGapS = 0.2;

	/** Fresh state for a life. EffectiveSkill >= 0 in adaptive mode (only the taps rule reads it). */
	void Reset(const UVerseBotTier& Tier, uint64 Seed, float EffectiveSkill = -1.f);

	/** New tier values without resetting the state (adaptive mode at respawn calls Reset instead). */
	void SetTier(const UVerseBotTier& Tier, float EffectiveSkill = -1.f);

	FVerseBotAimOutput Tick(const FVerseBotAimInput& In);

	const FVerseBotAimController& GetController() const { return Aim; }
	const FVerseBotRecoilControl& GetRecoil() const { return Recoil; }
	const FVerseBotTargetTracker& GetTracker() const { return Tracker; }

	/** Pitch and yaw of the direction from Eye to Point, degrees. */
	static FVector2D AnglesTo(const FVector& Eye, const FVector& Point);

	/** Angular distance between two (pitch, yaw) pairs, degrees (yaw scaled by cos pitch). */
	static double AngleBetween(const FVector2D& A, const FVector2D& B);

private:
	struct FViewSample
	{
		double TimeS = 0.0;
		FVector2D View = FVector2D::ZeroVector;
		/** Sum of own look deltas output up to (not including) this tick. */
		FVector2D OwnDeltaSum = FVector2D::ZeroVector;
	};

	FVerseBotReactionParams ReactionParams;
	FVerseRng ReactionRng;
	FVerseBotAimController Aim;
	FVerseBotTargetTracker Tracker;
	FVerseBotRecoilControl Recoil;
	FVerseBotFireGate FireGate;
	FVerseBotNoSightFire NoSight;
	double TrackLatencyS = 0.15;

	TArray<FViewSample> ViewHistory;
	FVector2D OwnDeltaSum = FVector2D::ZeroVector;
	FVector2D LastDelta = FVector2D::ZeroVector;
	FVector2D LastView = FVector2D::ZeroVector;
	bool bHaveLastView = false;

	int32 LastMagazine = -1;
	EVerseLoadoutSlot LastSlot = EVerseLoadoutSlot::Primary;
	double ReactAtS = 0.0;
	double LastSightS = -1.0e9;
	bool bEngaged = false;

	/** View the bot perceives now: view TrackLatency ago plus own deltas since. */
	FVector2D PerceivedView(double NowS, const FVector2D& ViewNow) const;
};

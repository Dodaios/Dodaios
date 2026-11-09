#pragma once

#include "Aim/VerseBotReaction.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "VerseRng.h"

class UVerseBotTier;

/** The reflex fields of a tier (bot.md 8.3, 5.2, 9.1). */
struct VERSEBOT_API FVerseBotReflexParams
{
	double LeanUse = 0.2;
	double CrouchPeekUse = 0.2;
	double ProneUse = 0.05;
	double SlideUse = 0.1;
	double SoundDiscipline = 0.1;
	double KnifeChoice = 0.2;
	double PistolSwitchChance = 0.2;
	FVerseBotReactionParams Reaction;

	static FVerseBotReflexParams FromTier(const UVerseBotTier& Tier);
};

/** A reflex that answers a stimulus, for presentation and tests. */
enum class EVerseBotReflex : uint8
{
	None,
	Finisher,
	Knife,
	PistolSwitch,
	RetreatOnEmpty,
	DuckOnHit,
};

/**
 * One tick of reflex inputs. Own values come from the own HUD (FVerseSelfPercept); the opponent
 * from the current sighting only; the intents from the decision layer (WP08) of this tick.
 */
struct VERSEBOT_API FVerseBotReflexContext
{
	double NowS = 0.0;

	// Own HUD.
	EVerseStance Stance = EVerseStance::Stand;
	EVerseLoadoutSlot ActiveSlot = EVerseLoadoutSlot::Primary;
	int32 Magazine = 0;
	bool bChambered = false;
	/** The finisher ability can activate (ruleset, own HUD cooldowns). */
	bool bFinisherAvailable = true;
	FVector SelfLocation = FVector::ZeroVector;
	float SelfYawDeg = 0.f;
	/** A hurt percept arrived this tick. */
	bool bHitThisTick = false;

	// Opponent, from the sighting of this tick.
	bool bTargetVisible = false;
	FVector TargetLocation = FVector::ZeroVector;
	float TargetFacingYawDeg = 0.f;
	bool bTargetSpawnProtected = false;

	// Intents of the decision layer.
	/** The bot is peeking; PeekId changes with every new peek, PeekSide -1 left, +1 right, 0 none. */
	bool bPeeking = false;
	uint32 PeekId = 0;
	int8 PeekSide = 0;
	/** Hiding behind low (1.0 m) cover. */
	bool bBehindLowCover = false;
	/** Moving across open ground; CrossingId changes with every crossing. */
	bool bCrossingOpenGround = false;
	uint32 CrossingId = 0;
	/** In Hold at long range; HoldId changes with every hold. */
	bool bHoldingLongRange = false;
	uint32 HoldId = 0;
	/** The decision layer wants to move and to sprint. */
	bool bWantsMove = false;
	bool bWantsSprint = false;
	/** Distance to the belief TopCluster, metres; negative when the belief is Lost or dead. */
	double TopClusterDistanceM = -1.0;
	/** Changes with every new approach toward the belief. */
	uint32 ApproachId = 0;
};

/** What the reflex layer puts on the input frame. */
struct VERSEBOT_API FVerseBotReflexOutput
{
	/** EVerseInputButton bits held / pressed this tick. */
	uint32 Buttons = 0;
	uint32 Pressed = 0;
	/** Scale on the decision layer's move vector: 1 run, WalkMoveScale walk. */
	float MoveScale = 1.f;
	/** Magazine empty with a target in sight and no pistol switch: the brain retreats (bot.md 5.2). */
	bool bWantRetreat = false;
	/** The stimulus reflex that fired this tick. */
	EVerseBotReflex Fired = EVerseBotReflex::None;
};

/**
 * The reflex layer (bot.md 8.3 and the reflex rows of 5.2), run every tick outside the StateTree:
 *
 *  - finisher: opponent within 1.5 m in its flank or back arc (combat-state.md 7.1, theta > 60 deg)
 *    and the ability can activate: a melee press, in every state;
 *  - knife: opponent within 2 m in front: a melee press when the magazine is empty or the
 *    KnifeChoice roll passes, else keep shooting;
 *  - pistol switch: magazine empty with a target in sight: secondary slot with
 *    PistolSwitchChance, else retreat;
 *  - duck: hit behind low cover: crouch with CrouchPeekUse until the next peek;
 *  - lean on peeks (LeanUse), slide to cross open ground (SlideUse), prone only in Hold at long
 *    range (ProneUse), walk or crouch-walk when TopCluster is within 15 m (SoundDiscipline).
 *
 * Every reflex that answers a stimulus waits a sampled reaction time (B4); each roll is drawn once
 * per episode (peek, crossing, hold, approach, contact), not per tick. Deterministic (B5).
 */
class VERSEBOT_API FVerseBotReflexes
{
public:
	static constexpr double FinisherRangeCm = 150.0;
	static constexpr double KnifeRangeCm = 200.0;
	/** combat-state.md 7.1: front is theta <= 60 deg. */
	static constexpr double FrontArcDeg = 60.0;
	static constexpr double SoundDisciplineRangeM = 15.0;
	/** Within this, sound discipline crouch-walks (never heard) instead of walking (4 m). */
	static constexpr double CrouchWalkRangeM = 6.0;
	static constexpr float WalkMoveScale = 0.5f;

	void Reset(const FVerseBotReflexParams& InParams, uint64 Seed);
	void SetParams(const FVerseBotReflexParams& InParams) { Params = InParams; }
	const FVerseBotReflexParams& GetParams() const { return Params; }

	FVerseBotReflexOutput Tick(const FVerseBotReflexContext& Ctx);

	/** theta of combat-state.md 7.1: angle between the victim's facing and the direction to the attacker, 0..180. */
	static double ArcAngleDeg(const FVector& VictimLocation, float VictimYawDeg, const FVector& AttackerLocation);

private:
	/** A stimulus reflex waiting for its reaction time. */
	struct FPending
	{
		EVerseBotReflex Reflex = EVerseBotReflex::None;
		double FireAtS = 0.0;
	};

	FVerseBotReflexParams Params;
	FVerseRng Rng;
	FPending Pending;

	// Episode rolls.
	bool bCloseContact = false;
	bool bKnifeRolled = false;
	bool bKnifeChosen = false;
	bool bEmptyHandled = false;
	bool bDucking = false;
	uint32 LeanPeekId = 0;
	bool bLeanRolled = false;
	bool bLeanChosen = false;
	uint32 SlideCrossingId = 0;
	bool bSlideRolled = false;
	bool bSlideChosen = false;
	bool bSlideDone = false;
	uint32 ProneHoldId = 0;
	bool bProneRolled = false;
	bool bProneChosen = false;
	uint32 QuietApproachId = 0;
	bool bQuietRolled = false;
	bool bQuietChosen = false;

	void Schedule(EVerseBotReflex Reflex, double NowS, EVerseBotStimulus Stimulus);
	bool RollOnce(uint32 Id, uint32& RolledId, bool& bRolled, bool& bChosen, double Chance);
};

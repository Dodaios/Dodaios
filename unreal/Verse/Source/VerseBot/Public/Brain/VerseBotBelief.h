#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

class FVerseBotMatchMemory;

/** The derived values the decision layer reads (bot.md 4.3). World cm, seconds. */
struct VERSEBOT_API FVerseBotBeliefSummary
{
	EVerseBeliefState State = EVerseBeliefState::Lost;
	/** TopCluster: the 3 m disc with the highest mass. */
	FVector TopCenter = FVector::ZeroVector;
	EVerseArenaLevel TopLevel = EVerseArenaLevel::Floor;
	/** Mass of TopCluster, 0..1. */
	float Confidence = 0.f;
	/** Seconds since the newest seen or heard support inside TopCluster; large when none. */
	float SupportAgeS = 1.0e6f;
	/** True when TopCluster has no seen or heard support at all (prior or inference only). */
	bool bPriorOnly = true;
	/** Weighted sd of the top 90 % of mass, cm. */
	float SpreadCm = 1.0e5f;
	/** Opponent facing estimate (4.1): last seen yaw and its age. */
	float FacingYawDeg = 0.f;
	float FacingAgeS = 1.0e6f;
	/** A reload was heard or seen and not yet followed by a shot. */
	bool bReloadNoticed = false;
	/** Believed velocity of TopCluster, cm/s (from consecutive supports). */
	FVector Velocity = FVector::ZeroVector;
	/** Seconds since the last sighting. */
	float SinceSightingS = 1.0e6f;
	/** Last sighted pelvis location. */
	FVector LastSeenLocation = FVector::ZeroVector;
	/** Estimated opponent health from own confirmed hits (3.3), 0..1 of max. */
	float OpponentHealthFrac = 1.f;
	/** Estimated rounds the opponent fired since the last noticed reload (3.3). */
	int32 OpponentShotsSinceReload = 0;
};

/**
 * The belief map the brain reads (bot.md 4). WP07 ships the grid implementation in
 * the Belief folders of VerseBot; the brain codes against this read and step surface only. Step is
 * deterministic (B5): same frames in, same summary out.
 */
class VERSEBOT_API IVerseBotBelief
{
public:
	virtual ~IVerseBotBelief() = default;

	/** Drop everything (own death, match end). */
	virtual void Reset() = 0;

	/**
	 * One belief step on one percept frame. Memory may be null (learning off); it biases
	 * predict and the 1 % prior mix (7.2). Spawns are the public spawn points (kill feed prior).
	 */
	virtual void Step(const FVersePerceptFrame& Frame, float DtS, const FVerseBotMatchMemory* Memory, TConstArrayView<FVector> Spawns) = 0;

	/** Record an own action that changed a piece (destruction 6.2 "Own action"). */
	virtual void NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState) = 0;

	virtual FVerseBotBeliefSummary Summary() const = 0;

	/** Mass within RadiusCm of Location (4.5). */
	virtual float MassWithin(const FVector& Location, float RadiusCm) const = 0;

	/** Mass within RadiusCm of Location that has seen or heard support (prior-only mass excluded, 4.5). */
	virtual float SupportedMassWithin(const FVector& Location, float RadiusCm) const = 0;

	/** Top N cells by mass (BeliefCells context: N = 8). */
	virtual void TopCells(int32 N, TArray<FVector>& Out) const = 0;

	/** The believed state of a piece; Intact for one never perceived (DR6). */
	virtual EVersePieceState GetPieceBelief(uint16 PieceIndex) const = 0;
};

/**
 * A small deterministic belief: a mixture of up to eight Gaussian hypotheses fed by the same rules
 * as bot.md 4.2 (sighting replaces, heard multiplies, hurt and bolt add a wedge, kill feed clears
 * and seeds the spawn prior, predict diffuses at 4.5 m/s). The controller uses it until WP07's
 * grid lands; tests use it as the scripted-belief baseline.
 */
class VERSEBOT_API FVerseBotCoarseBelief final : public IVerseBotBelief
{
public:
	static constexpr int32 MaxHypotheses = 8;

	virtual void Reset() override;
	virtual void Step(const FVersePerceptFrame& Frame, float DtS, const FVerseBotMatchMemory* Memory, TConstArrayView<FVector> Spawns) override;
	virtual void NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState) override;
	virtual FVerseBotBeliefSummary Summary() const override { return Cached; }
	virtual float MassWithin(const FVector& Location, float RadiusCm) const override;
	virtual float SupportedMassWithin(const FVector& Location, float RadiusCm) const override;
	virtual void TopCells(int32 N, TArray<FVector>& Out) const override;
	virtual EVersePieceState GetPieceBelief(uint16 PieceIndex) const override;

	/** Own player id, so kill feed entries can be read (set by the brain). */
	void SetSelfId(int32 InSelfId) { SelfId = InSelfId; }

private:
	enum class ESupport : uint8 { Prior, Inferred, Heard, Seen };

	struct FHypothesis
	{
		FVector Center = FVector::ZeroVector;
		float SdCm = 50.f;
		float Weight = 0.f;
		EVerseArenaLevel Level = EVerseArenaLevel::Floor;
		ESupport Support = ESupport::Prior;
		float SupportTimeS = -1.0e6f;
		FVector Velocity = FVector::ZeroVector;
	};

	void Normalise();
	void AddHypothesis(const FHypothesis& H);
	void Refresh(float NowS);
	static float DiscMass(const FHypothesis& H, const FVector& Location, float RadiusCm);

	TArray<FHypothesis, TInlineAllocator<MaxHypotheses>> Hyps;
	TMap<uint16, EVersePieceState> Pieces;
	FVerseBotBeliefSummary Cached;
	bool bDead = false;
	bool bReload = false;
	float NowS = 0.f;
	float LastSeenS = -1.0e6f;
	FVector LastSeen = FVector::ZeroVector;
	float FacingYaw = 0.f;
	float FacingTimeS = -1.0e6f;
	float OpponentHealth = 1.f;
	int32 ShotsSinceReload = 0;
	int32 SelfId = 0;
};

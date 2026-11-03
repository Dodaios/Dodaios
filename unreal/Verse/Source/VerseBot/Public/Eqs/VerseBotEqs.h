#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotBelief.h"
#include "Brain/VerseBotTypes.h"
#include "Brain/VerseBotWorldQueries.h"
#include "CoreMinimal.h"

class FVerseBotMatchMemory;
class UVerseBotTier;

// The EQS queries of bot.md 6.2 as deterministic generator / filter / score passes over belief
// contexts only. The contexts (BeliefTop, BeliefCells, BeliefFacing) resolve to belief values,
// never to an actor (F1); sight tests go through IVerseBotWorldQueries::TestSight against the
// piece belief. Every item score is (1 - w) x base + w x learned with w from 7.3.

/** Everything a query reads. */
struct VERSEBOT_API FVerseBotQueryContext
{
	const FVerseSelfPercept* Self = nullptr;
	const FVerseBotBeliefSummary* Belief = nullptr;
	const IVerseBotBelief* BeliefMap = nullptr;
	IVerseBotWorldQueries* World = nullptr;
	const FVerseBotMatchMemory* Memory = nullptr;
	const UVerseBotTier* Tier = nullptr;
	float NowS = 0.f;
	/** Exploration (7.3): this decision ignores the learned term. */
	bool bIgnoreLearned = false;
	/** Preferred engagement range after the learned shift, cm. */
	float PreferredRangeCm = 1400.f;
	FVerseBotWeaponInfo Weapon;
	/** The bot's last three peek edges (PeekRepeatPenalty). */
	TArray<int32, TInlineAllocator<3>> RecentPeekEdges;
	/** Peek edge ids already spent this decision; not used by the queries themselves. */
	int32 CurrentCoverEdge = INDEX_NONE;
};

enum class EVerseBotCoverMode : uint8
{
	Near,
	Far,
	Flank,
	Bulwark
};

struct VERSEBOT_API FVerseBotCoverResult
{
	bool bFound = false;
	FVerseBotCoverPoint Point;
	float Score = 0.f;
	int32 Candidates = 0;
};

struct VERSEBOT_API FVerseBotPeekResult
{
	bool bFound = false;
	EVerseBotPeekType Type = EVerseBotPeekType::LeanRight;
	/** Where the bot stands while peeking. */
	FVector StandPoint = FVector::ZeroVector;
	/** The peek eye. */
	FVector Eye = FVector::ZeroVector;
	float Score = 0.f;
	/**
	 * Learned (7.2): the person's most used peek edge near TopCluster that this peek sees. Hold
	 * pre-aims it and stays out longer the more the person re-peeks it fast.
	 */
	bool bHasWatch = false;
	FVector WatchPoint = FVector::ZeroVector;
	int32 WatchEdge = INDEX_NONE;
	/** The person's fast re-peek share at the watched edge and the learned weight behind it. */
	float WatchRepeekShare = 0.f;
	float WatchWeight = 0.f;
};

struct VERSEBOT_API FVerseBotWallbangResult
{
	bool bFound = false;
	FVector FireFrom = FVector::ZeroVector;
	FVector AimPoint = FVector::ZeroVector;
	float DamageFrac = 0.f;
	int32 Pieces = 0;
	float Score = 0.f;
};

struct VERSEBOT_API FVerseBotBreachResult
{
	bool bFound = false;
	uint16 PieceIndex = 0;
	FVector PlantPoint = FVector::ZeroVector;
	FVector WaitPoint = FVector::ZeroVector;
	float Score = 0.f;
};

struct VERSEBOT_API FVerseBotFinisherResult
{
	bool bFound = false;
	FVector Approach = FVector::ZeroVector;
	float PathLengthCm = 0.f;
	float ArrivalS = 0.f;
	float Score = 0.f;
};

/**
 * Resumable state of one time-sliced query (bot.md 2: EQS 0.2 ms amortised). A query evaluates
 * candidates until its cost budget for this tick is spent (at least one candidate per slice) and
 * resumes with the next candidate on the next tick. The generator runs on the context snapshot the
 * brain took when the query started, so candidate order is stable across slices.
 */
struct VERSEBOT_API FVerseBotEqsSlice
{
	/** Cost units of the world calls (TestSight 1, TraceBolt 2, FindPath 6). */
	static constexpr int32 SightCost = 1;
	static constexpr int32 BoltCost = 2;
	static constexpr int32 PathCost = 6;

	int32 BudgetUnits = MAX_int32;
	int32 SpentUnits = 0;
	int32 TotalUnits = 0;
	int32 Next = 0;
	int32 SliceStart = 0;
	int32 Tested = 0;
	int32 Slices = 0;
	float BestScore = -1.0e9f;
	/** Generator value cached on the first slice (BreachSpot: the direct path length). */
	float Scratch = 0.f;
	bool bScratchSet = false;
	bool bDone = false;

	void BeginSlice(int32 Units)
	{
		BudgetUnits = Units;
		SpentUnits = 0;
		SliceStart = Next;
		++Slices;
	}
	/** True when this slice should stop before candidate Index (never before the first one). */
	bool OutOfBudget(int32 Index) const { return Index > SliceStart && SpentUnits >= BudgetUnits; }
	void Spend(int32 Units)
	{
		SpentUnits += Units;
		TotalUnits += Units;
	}
};

/** Forwards to the real world queries and charges each call to a slice. */
class VERSEBOT_API FVerseBotMeteredWorld final : public IVerseBotWorldQueries
{
public:
	FVerseBotMeteredWorld(IVerseBotWorldQueries& InInner, FVerseBotEqsSlice& InSlice) : Inner(InInner), Slice(InSlice) {}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) override { Slice.Spend(FVerseBotEqsSlice::SightCost); return Inner.TestSight(Eye, Target); }
	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon) override
	{
		Slice.Spend(FVerseBotEqsSlice::BoltCost);
		return Inner.TraceBolt(Origin, Target, Weapon);
	}
	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) override { Slice.Spend(FVerseBotEqsSlice::PathCost); return Inner.FindPath(From, To, bCrouch); }
	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) override { Inner.GetCoverPoints(Center, RadiusCm, Out); }
	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) override { Inner.GetPieces(Center, RadiusCm, Out); }
	virtual void GetSpawnPoints(TArray<FVector>& Out) override { Inner.GetSpawnPoints(Out); }
	virtual int32 GetZoneId(const FVector& Location) override { return Inner.GetZoneId(Location); }
	virtual FVerseBotWeaponInfo GetOwnWeapon() override { return Inner.GetOwnWeapon(); }
	virtual bool CanActivateFinisher() override { return Inner.CanActivateFinisher(); }

private:
	IVerseBotWorldQueries& Inner;
	FVerseBotEqsSlice& Slice;
};

namespace VerseBotEqs
{
	/** Eye heights of the cover hidden-filter (6.2): standing 1.65 m, crouched 1.1 m. */
	inline constexpr float StandEyeCm = 165.f;
	inline constexpr float CrouchEyeCm = 110.f;
	inline constexpr float CoverRadiusCm = 2500.f;
	inline constexpr float BreachRadiusCm = 3000.f;
	inline constexpr float FinisherRangeCm = 150.f;
	inline constexpr float FinisherArcDeg = 100.f;
	inline constexpr float BelievedViewHalfAngleDeg = 55.f;
	/** Crouch-walk speed used for the stalk arrival time, cm/s. */
	inline constexpr float CrouchSpeedCmS = 200.f;
	/** Breach charge pawn radius (combat-state 2.3), cm. */
	inline constexpr float BreachSelfDamageRadiusCm = 300.f;
	inline constexpr float BreachFuseS = 2.5f;

	// Contexts
	VERSEBOT_API FVector BeliefTop(const FVerseBotQueryContext& Ctx);
	VERSEBOT_API void BeliefCells(const FVerseBotQueryContext& Ctx, TArray<FVector>& Out);
	/** Unit facing of the believed opponent (yaw only). */
	VERSEBOT_API FVector BeliefFacing(const FVerseBotQueryContext& Ctx);

	/** (1 - w) x base + w x learned. */
	VERSEBOT_API float Blend(float Base, float Learned, float W);

	/** EQS_Cover (6.2). */
	VERSEBOT_API FVerseBotCoverResult Cover(const FVerseBotQueryContext& Ctx, EVerseBotCoverMode Mode);

	/** EQS_PeekCorner (6.2) from a cover point. */
	VERSEBOT_API FVerseBotPeekResult PeekCorner(const FVerseBotQueryContext& Ctx, const FVerseBotCoverPoint& From);

	/** EQS_WallbangSpot (6.2): only spots that pass wall-shot authority (4.5). */
	VERSEBOT_API FVerseBotWallbangResult WallbangSpot(const FVerseBotQueryContext& Ctx);

	/** EQS_BreachSpot (6.2). */
	VERSEBOT_API FVerseBotBreachResult BreachSpot(const FVerseBotQueryContext& Ctx);

	/** EQS_FinisherApproach (6.2). */
	VERSEBOT_API FVerseBotFinisherResult FinisherApproach(const FVerseBotQueryContext& Ctx);

	// Time-sliced forms: run one slice; Slice.bDone says when InOut holds the final result.
	VERSEBOT_API void CoverSlice(const FVerseBotQueryContext& Ctx, EVerseBotCoverMode Mode, FVerseBotEqsSlice& Slice, FVerseBotCoverResult& InOut);
	VERSEBOT_API void PeekCornerSlice(const FVerseBotQueryContext& Ctx, const FVerseBotCoverPoint& From, FVerseBotEqsSlice& Slice, FVerseBotPeekResult& InOut);
	VERSEBOT_API void WallbangSpotSlice(const FVerseBotQueryContext& Ctx, FVerseBotEqsSlice& Slice, FVerseBotWallbangResult& InOut);
	VERSEBOT_API void BreachSpotSlice(const FVerseBotQueryContext& Ctx, FVerseBotEqsSlice& Slice, FVerseBotBreachResult& InOut);
	VERSEBOT_API void FinisherApproachSlice(const FVerseBotQueryContext& Ctx, FVerseBotEqsSlice& Slice, FVerseBotFinisherResult& InOut);

	/** Distance in 2D from Point to the segment A-B, cm. */
	VERSEBOT_API float DistToSegment2D(const FVector& Point, const FVector& A, const FVector& B);

	/** True when no BeliefCells item sees Point at either eye height (the cover hidden filter). */
	VERSEBOT_API bool HiddenFromBelief(const FVerseBotQueryContext& Ctx, const FVector& Point, TConstArrayView<FVector> Cells, bool bLowCover);

	/** Angle in degrees between the believed facing and the direction from BeliefTop to Point. */
	VERSEBOT_API float OffFacingDeg(const FVerseBotQueryContext& Ctx, const FVector& Point);
}

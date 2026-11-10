#pragma once

#include "Belief/VerseBeliefMap.h"
#include "Brain/VerseBotBelief.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"

class IVerseBotWorldQueries;

/**
 * The bot's sight for the belief map: IVersePenetrationQuery::TestSight answered by the bot's own
 * world queries (VerseSight channel, believed-intact pieces opaque). No bolt traces: the belief map
 * only clears cells and watches pieces with it.
 */
class VERSEBOT_API FVerseBotBeliefSight final : public IVersePenetrationQuery
{
public:
	explicit FVerseBotBeliefSight(IVerseBotWorldQueries& InQueries) : Queries(&InQueries) {}

	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power, float Damage,
		uint8 RadiusMm, int32 MaxPieces) const override
	{
		return TArray<FVersePenetrationHit>();
	}
	virtual bool TestSight(const FVector& Eye, const FVector& Target) const override;

	/** The queries of this tick (the controller may swap them: harness, replay). */
	void SetQueries(IVerseBotWorldQueries& InQueries) { Queries = &InQueries; }

private:
	IVerseBotWorldQueries* Queries;
};

/**
 * IVerseBotBelief over the WP07 belief grid (bot.md 4): the brain's read surface (summary, mass
 * queries, top cells) answered from FVerseBeliefMap. Clearing tests cells against the bot's own
 * sight, so belief mass leaves what the bot has looked at and gathers where it has not; the
 * search state walks to that mass (bot.md 5.1).
 */
class VERSEBOT_API FVerseBotGridBelief final : public IVerseBotBelief
{
public:
	FVerseBotGridBelief(const FVerseBeliefGridSource& InSource, const FVerseBeliefMapConfig& InConfig, IVerseBotWorldQueries& Queries);

	virtual void Reset() override;
	virtual void Step(const FVersePerceptFrame& Frame, float DtS, const FVerseBotMatchMemory* Memory, TConstArrayView<FVector> Spawns) override;
	virtual void NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState) override;
	virtual FVerseBotBeliefSummary Summary() const override { return Cached; }
	virtual float MassWithin(const FVector& Location, float RadiusCm) const override;
	virtual float SupportedMassWithin(const FVector& Location, float RadiusCm) const override;
	virtual void TopCells(int32 N, TArray<FVector>& Out) const override;
	virtual EVersePieceState GetPieceBelief(uint16 PieceIndex) const override;

	/** Own death (bot.md 5.2): belief cleared to uniform. */
	void OnOwnDeath(float NowS);

	const FVerseBeliefMap& GetMap() const { return Map; }

	/** Height of a standing pelvis above the floor: the grid holds floor points, the brain reads pelvis points. */
	static constexpr float PelvisAboveFloorCm = 90.f;

private:
	float SumWithin(const FVector& Location, float RadiusCm, bool bSupportedOnly) const;
	void Summarise();

	FVerseBeliefGridSource Source;
	FVerseBeliefMapConfig Config;
	FVerseBotBeliefSight Sight;
	FVerseBeliefMap Map;
	FVerseBotBeliefSummary Cached;
	float NowS = 0.f;
	bool bWasDead = false;
};

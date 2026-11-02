#pragma once

#include "Brain/VerseBotTypes.h"
#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseBotMatchMemory.generated.h"

class UVerseBotTier;

/**
 * What the bot learned about the person in this match (bot.md 7). Inputs are percepts only. Plain
 * native data with no reflection, no serialisation and no network path: it cannot be saved, cooked
 * or replicated (B8, L1). Times are match seconds; positions world cm.
 */
class VERSEBOT_API FVerseBotMatchMemory
{
public:
	/** Engagement range bins of 7.1: 0-5, 5-10, 10-20, 20-35, 35+ m. */
	static constexpr int32 NumRangeBins = 5;
	static int32 RangeBin(float RangeCm);
	/** The lower bound of a range bin, cm. */
	static float RangeBinCentreCm(int32 Bin);

	/** Heatmap layers (7.1). */
	enum class ELayer : uint8 { Position, Shooting };

	/** Tier fields the bounds of 7.3 read. */
	void Configure(const UVerseBotTier& Tier);
	void SetEnabled(bool bInEnabled) { bEnabled = bInEnabled; }
	bool IsEnabled() const { return bEnabled; }

	/** Match end (7.3 Reset): everything learned is dropped. */
	void Reset();
	bool IsEmpty() const;

	// Updates (7.1)
	void RecordSighting(const FVector& Location, float NowS, bool bFirstContact);
	void RecordHeard(const FVector& Location, float NowS);
	void RecordShotFrom(const FVector& Location, float NowS, bool bSeen);
	void RecordPeek(int32 EdgeId, EVerseBotPeekType Type, float NowS);
	void RecordEngagementEnd(float RangeCm, bool bPersonWon);
	void RecordZone(int32 ZoneId, float NowS);
	void RecordHabit(FName Habit);

	// Reads (7.2, 7.3)
	/** Decayed heat of a 1 m column cell at Location. */
	float Heat(ELayer Layer, const FVector& Location, float NowS) const;
	/** Heat summed over a disc, normalised by the layer total (0..1). */
	float HeatShare(ELayer Layer, const FVector& Location, float RadiusCm, float NowS) const;
	/** Decayed sample count behind a disc (n of 7.3). */
	float SamplesNear(ELayer Layer, const FVector& Location, float RadiusCm, float NowS) const;
	/** w = LearnWeightMax x n / (n + LearnSamplesHalf); 0 when learning is off; never above 0.35. */
	float Weight(float Samples) const;
	/** Probability of a move From -> To among moves out of From (0 when unseen). */
	float ZoneTransitionProb(int32 FromZone, int32 ToZone) const;
	/** The zone most often entered from FromZone, INDEX_NONE when none. */
	int32 MostLikelyNextZone(int32 FromZone) const;
	/** The person's most used zone-to-zone route (from, to), or (INDEX_NONE, INDEX_NONE). */
	TPair<int32, int32> MostUsedRoute() const;
	/** Share of the person's appearances at an edge (0..1) and its sample count. */
	float PeekShare(int32 EdgeId, float& OutSamples) const;
	/** Share of the person's fast re-peeks (< 3 s) at an edge. */
	float RepeekShare(int32 EdgeId) const;
	/** The person's top N peek edges. */
	void TopPeekEdges(int32 N, TArray<int32>& Out) const;
	/** Preferred range shift in bins (-1, 0, 1) toward the bin where the person wins least (7.2). */
	int32 RangeBinShift(float PreferredRangeCm) const;
	int32 HabitCount(FName Habit) const;
	float HalfLifeS() const { return HabitHalfLifeS; }

private:
	struct FCell
	{
		float Value = 0.f;
		float TimeS = 0.f;
	};
	struct FPeekHabit
	{
		float Appearances = 0.f;
		float FastRepeeks = 0.f;
		float JumpPeeks = 0.f;
		float LeanPeeks = 0.f;
		float LastS = -1.0e6f;
	};
	struct FRangeBin
	{
		int32 Engagements = 0;
		int32 PersonWins = 0;
	};

	static FIntVector CellOf(const FVector& Location);
	float Decay(float DtS) const;
	void AddHeat(ELayer Layer, const FVector& Location, float Amount, float NowS);
	float Decayed(const FCell& Cell, float NowS) const;

	TMap<FIntVector, FCell> Layers[2];
	FCell LayerTotal[2];
	TMap<int32, FPeekHabit> Peeks;
	float PeekTotal = 0.f;
	FRangeBin Ranges[NumRangeBins];
	TMap<int64, float> Routes;
	TMap<int32, float> RouteOut;
	int32 LastZone = INDEX_NONE;
	TMap<FName, int32> Habits;

	bool bEnabled = true;
	float LearnWeightMax = 0.1f;
	float LearnSamplesHalf = 12.f;
	float HabitHalfLifeS = 180.f;
};

/**
 * One per bot per match (bot.md 7). Owns the native memory; the object itself carries no
 * reflected state, so nothing of it reaches disk or the bridge. Reset on match end.
 */
UCLASS(Transient)
class VERSEBOT_API UVerseBotMatchMemory : public UObject
{
	GENERATED_BODY()

public:
	FVerseBotMatchMemory& Get() { return Memory; }
	const FVerseBotMatchMemory& Get() const { return Memory; }
	void ResetMatch() { Memory.Reset(); }

private:
	FVerseBotMatchMemory Memory;
};

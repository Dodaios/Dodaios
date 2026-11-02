#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Templates/Function.h"

// The Unreal service record's data (WP21.7): the commander's level, XP and rank, the duel totals,
// and the promotion notices still to show. Fed from the bridge's progression topic
// (bridge-protocol.md 9, 10, 14): `progression.snapshot` and `progression.awarded` in,
// `progression.told {seq}` out once a promotion was on screen, so it is never shown twice.
// The rulebook numbers (level curve, rank ladder) are the server's (dodaios/progression/rules.py);
// tests/unit/progression/test_duel_parity.py holds this copy to them.

/** One step of the fleet's rank ladder. */
struct FVerseRankRow
{
	FName Id;
	int32 Level = 1;
	FName Tier;
};

/** Duel totals as `duel_stats` carries them. */
struct FVerseDuelTotals
{
	int32 Matches = 0;
	int32 Wins = 0;
	int32 Losses = 0;
	int32 Unfinished = 0;
	int32 Kills = 0;
	int32 Deaths = 0;
	int32 Headshots = 0;
	int32 Finishers = 0;
	int32 BestStreak = 0;
	/** Tier -> (wins, losses). */
	TMap<FString, FIntPoint> ByTier;

	/** Kills per death; the kills themselves with no deaths yet. */
	float KillDeathRatio() const { return Deaths > 0 ? float(Kills) / float(Deaths) : float(Kills); }
};

/** The commander's standing. */
struct FVerseCommanderRecord
{
	int32 Level = 1;
	int64 TotalXp = 0;
	int64 IntoLevel = 0;
	int64 ForNext = 0;
	FString Title;
};

/** A level-up of the commander the person has not seen yet. */
struct FVersePromotion
{
	int64 Seq = 0;
	int32 Level = 1;
	int32 PreviousLevel = 1;
	FName RankId;
	FName PreviousRankId;
	TArray<FString> Unlocked;

	/** True when the level-up also reached a new rank (not only a level). */
	bool IsNewRank() const { return RankId != PreviousRankId; }
};

class VERSEUI_API FVerseServiceRecordModel
{
public:
	static constexpr int32 MaxLevel = 50;

	/** XP from Level to the next (0 at the cap); rules.py xp_to_next. */
	static int64 XpToNext(int32 Level);
	/** Total XP at which Level starts; rules.py total_xp_for_level. */
	static int64 TotalXpForLevel(int32 Level);
	static int32 LevelForXp(int64 TotalXp);

	/** The rank ladder, lowest first; rules.py RANKS. */
	static const TArray<FVerseRankRow>& Ladder();
	static const FVerseRankRow& RankFor(int32 Level);
	/** The next rank above Level, or nullptr at the top. */
	static const FVerseRankRow* NextRank(int32 Level);

	/** `progression.snapshot` data. False when it is not one (nothing changes). */
	bool ApplySnapshot(const FJsonObject& Data);
	/** `progression.awarded` data. True when it queued a promotion notice. */
	bool ApplyAwarded(const FJsonObject& Data);
	/** The `duel_stats` object of a snapshot or of a duel.result reply. */
	void ApplyDuelStats(const FJsonObject& Stats);

	const FVerseCommanderRecord& Commander() const { return Record; }
	const FVerseDuelTotals& Duels() const { return DuelTotals; }
	bool HasSnapshot() const { return bHasSnapshot; }
	int64 LatestSeq() const { return Latest; }
	int64 ToldSeq() const { return Told; }

	/** The oldest promotion not yet shown, or nullptr. */
	const FVersePromotion* PendingPromotion() const;
	int32 NumPendingPromotions() const { return Promotions.Num(); }

	/**
	 * The pending promotion has been on screen: drop it and report `progression.told` with its
	 * seq through SendTold, once per seq.
	 */
	void MarkPromotionShown();

	/** Sends `progression.told {seq}` (the bridge client; a test's recorder). */
	TFunction<void(int64 Seq)> SendTold;

	/** Fired after every change, for the views. */
	FSimpleMulticastDelegate OnChanged;

private:
	void SetCommander(int32 Level, int64 TotalXp, const FString& Title);
	void DropToldPromotions();

	FVerseCommanderRecord Record;
	FVerseDuelTotals DuelTotals;
	TArray<FVersePromotion> Promotions;
	int64 Latest = 0;
	int64 Told = 0;
	bool bHasSnapshot = false;
};

#pragma once

#include "CoreMinimal.h"
class FJsonObject;
#include "Templates/Function.h"

// The Unreal service record's data (WP21.7): the commander's level, XP and rank, the duel totals,
// and the promotion notices still to show. Fed from the bridge's progression topic
// (bridge-protocol.md 9, 10, 14): `progression.snapshot` and `progression.awarded` in,
// `progression.told {seq}` out once a promotion was on screen, so it is never shown twice.
// The rulebook numbers (level curve, rank ladder) are the server's (dodaios/progression/rules.py);
// tests/unit/progression/test_duel_parity.py holds this copy to them.

/** The service record's five pages, in tab order (parity R-04). */
enum class EVerseRecordTab : uint8
{
	Record,
	Ladder,
	Rewards,
	Earn,
	Crew,
};

/** One step of the fleet's rank ladder. */
struct FVerseRankRow
{
	FName Id;
	int32 Level = 1;
	FName Tier;
	/** The plate's lit tiles, "top|bottom", three digits each (ranks.ts RANKS, style bible 7.2). */
	FString Plate;
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

/** Who a rule pays, an award went to, a row belongs to. */
enum class EVerseSubjectKind : uint8
{
	Person,
	Agent,
	Pet,
};

/** One reward of the rulebook: a uniform of a tier or a ribbon, with the level that opens it per kind (-1 = never). */
struct FVerseRewardRow
{
	/** "uniform_line", "ribbon_good_conduct" */
	FName RewardId;
	/** "uniform" or "ribbon" */
	FName Slot;
	int32 PersonLevel = -1;
	int32 AgentLevel = -1;
	int32 PetLevel = -1;

	/** The part after the slot: "line", "good_conduct". */
	FName Key() const;
	int32 LevelFor(EVerseSubjectKind Kind) const;
};

/** One XP rule the running server pays. */
struct FVerseXpRule
{
	FName Source;
	EVerseSubjectKind Kind = EVerseSubjectKind::Person;
	int32 Xp = 0;
	/** The ship reports it (a world action) and not the server. */
	bool bWorld = false;
	/** 0 = none */
	int32 CooldownSeconds = 0;
	/** 0 = none */
	int32 DailyCap = 0;
};

/** One line of the award log. */
struct FVerseAwardRow
{
	int64 Seq = 0;
	FString SubjectId;
	EVerseSubjectKind Kind = EVerseSubjectKind::Person;
	FName Source;
	int32 Xp = 0;
	int32 LevelBefore = 1;
	int32 LevelAfter = 1;
	int64 TimestampMs = 0;
};

/** The standing of an officer or of the companion. */
struct FVerseSubjectRow
{
	FString SubjectId;
	EVerseSubjectKind Kind = EVerseSubjectKind::Agent;
	int32 Level = 1;
	int64 TotalXp = 0;
};

/** A level-up the person sees as a quiet line in the corner (parity R-11). */
struct FVerseQuietLine
{
	int64 Seq = 0;
	FString SubjectId;
	EVerseSubjectKind Kind = EVerseSubjectKind::Agent;
	int32 Level = 1;
	FName RankId;
	/** The level-up also reached a new rank. */
	bool bPromoted = false;
};

/** A level-up of the commander or the companion the person has not seen yet. */
struct FVersePromotion
{
	int64 Seq = 0;
	/** The commander or the companion drone. */
	EVerseSubjectKind Kind = EVerseSubjectKind::Person;
	int32 Level = 1;
	int32 PreviousLevel = 1;
	FName RankId;
	FName PreviousRankId;
	TArray<FString> Unlocked;

	/** True when the level-up also reached a new rank (not only a level). */
	bool IsNewRank() const { return RankId != PreviousRankId; }
	/** Only a new rank earns the full notice; any other level-up is a quiet line (parity R-10, R-11). */
	bool IsFullNotice() const { return IsNewRank(); }
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

	// The rulebook and the ledger of the running server (snapshot `rewards`, `rules`, `recent`).
	/** The server rewards, or the built-in table when it sent none (an older server). */
	const TArray<FVerseRewardRow>& Rewards() const;
	static const TArray<FVerseRewardRow>& DefaultRewards();
	const TArray<FVerseXpRule>& Rules() const { return XpRules; }
	/** The newest awards of the commander, newest first, at most Limit. */
	TArray<FVerseAwardRow> CommanderLog(int32 Limit = 8) const;
	/** Officers and the companion. */
	const TArray<FVerseSubjectRow>& Subjects() const { return Others; }
	/** The companion drone: level 1 with 0 XP before the server told. */
	FVerseSubjectRow Companion() const;
	const FString& GetPetId() const { return PetId; }

	/** Uniforms issued to the commander at Level, lowest tier first; the work uniform always. */
	TArray<FName> IssuedUniforms(int32 Level) const;
	/** "auto" or a tier id (deck, line, command, flag). */
	FName GetUniformChoice() const { return UniformChoice; }
	/** The uniform worn now: the choice if it is issued, else the highest issued. */
	FName EffectiveUniform() const;
	/** Picks a uniform ("auto" for the highest issued). False when it is not issued. */
	bool ChooseUniform(FName Choice);
	/** Called at once with the uniform now worn; the commander material follows it. */
	TFunction<void(FName Uniform)> OnUniformWorn;
	/** Where the choice lives between runs; the subsystem installs the config file. */
	TFunction<void(FName Choice)> SaveUniformChoice;
	void RestoreUniformChoice(FName Choice);

	/** The ship bell on promotions (parity R-12 reads it; the setting lives in the app config). */
	bool IsBellOn() const { return bBell; }
	void SetBellOn(bool bOn)
	{
		bBell = bOn;
		if (SaveBell)
		{
			SaveBell(bOn);
		}
		OnChanged.Broadcast();
	}
	TFunction<void(bool)> SaveBell;

	/** The names the crew page lists, by agent id, and the name of the companion. */
	void SetCrewNames(const TMap<FString, FString>& Names, const FString& CompanionName);
	const TMap<FString, FString>& GetCrewNames() const { return CrewNames; }
	const FString& GetCompanionName() const { return CompanionLabel; }

	/** Level-ups the person sees as a quiet line (officers; the drone without a new rank). */
	const TArray<FVerseQuietLine>& QuietLines() const { return Quiet; }
	/** Takes the oldest quiet line; false when there is none. */
	bool PopQuietLine(FVerseQuietLine& Out);

	/** Sends `progression.told {seq}` (the bridge client; a test's recorder). */
	TFunction<void(int64 Seq)> SendTold;

	/** Fired after every change, for the views. */
	FSimpleMulticastDelegate OnChanged;

private:
	void SetCommander(int32 Level, int64 TotalXp, const FString& Title);
	void DropToldPromotions();

	void ParseRulebook(const FJsonObject& Data);
	void ApplySubject(const FString& SubjectId, EVerseSubjectKind Kind, int32 Level, int64 TotalXp);

	TArray<FVerseRewardRow> ServerRewards;
	TArray<FVerseXpRule> XpRules;
	TArray<FVerseAwardRow> Ledger;
	TArray<FVerseSubjectRow> Others;
	TArray<FVerseQuietLine> Quiet;
	TMap<FString, FString> CrewNames;
	FString CompanionLabel;
	FString PetId;
	FName UniformChoice = TEXT("auto");
	FName LastWorn;
	bool bBell = true;

	FVerseCommanderRecord Record;
	FVerseDuelTotals DuelTotals;
	TArray<FVersePromotion> Promotions;
	int64 Latest = 0;
	int64 Told = 0;
	bool bHasSnapshot = false;
};

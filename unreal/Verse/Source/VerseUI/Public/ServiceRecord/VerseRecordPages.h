#pragma once

#include "CoreMinimal.h"
#include "ServiceRecord/VerseServiceRecordModel.h"

class FVerseUiStrings;

/**
 * What the five pages of the service record say (parity R-04 to R-09), as plain values built
 * from the model and the strings catalogue: the widgets only lay them out, and the tests read
 * them. Ranks come from the level, never from a rank id the server sent (R-02).
 */
struct VERSEUI_API FVerseRecordPages
{
	struct FTab
	{
		EVerseRecordTab Tab = EVerseRecordTab::Record;
		/** record, ladder, rewards, earn, crew */
		FName Id;
		/** verse.ranks.record.tabs.<id> */
		FString LabelKey;
	};
	/** The five tabs in order: Record, Ladder, Quartermaster, How to earn, Crew. */
	static const TArray<FTab>& Tabs();

	// ---- Record
	struct FLogRow
	{
		FText Source;
		FText When;
		FText Xp;
	};
	struct FRecordPage
	{
		FName RankId;
		FText Rank;
		FText Tier;
		FText Level;
		FText TotalXp;
		FText ThisLevel;
		/** XP missing for the next rank, or empty at the top. */
		FText NextRankXp;
		/** The next rank by name, or the top-of-ladder line. */
		FText NextRank;
		float Fraction = 0.f;
		bool bHasDuels = false;
		FText Sets;
		FText WonLost;
		FText KillDeath;
		FText Headshots;
		FText Finishers;
		FText BestStreak;
		FText Unfinished;
		TArray<FText> Ribbons;
		FText NoRibbons;
		TArray<FLogRow> Log;
		FText NoLog;
		bool bBellOn = true;
	};
	static FRecordPage Record(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

	// ---- Ladder
	enum class EStepState : uint8
	{
		Held,
		Current,
		Ahead,
	};
	struct FStep
	{
		FName RankId;
		FText Name;
		EStepState State = EStepState::Held;
		/** "Held" or "Current", empty for the ranks ahead. */
		FText StateText;
		/** "Level 14", or "1 280 XP" still missing for a rank ahead. */
		FText Right;
		int32 Level = 1;
	};
	struct FTierBlock
	{
		FName Tier;
		FText Name;
		FText FromLevel;
		TArray<FStep> Steps;
	};
	static TArray<FTierBlock> Ladder(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

	// ---- Quartermaster
	struct FUniformOption
	{
		/** "auto" or a tier id. */
		FName Id;
		FName SwatchTier;
		FText Name;
		FText Note;
		bool bOpen = false;
		bool bChosen = false;
		/** "Wearing", "Issued" or empty. */
		FText StateText;
	};
	struct FRibbonRow
	{
		FName Id;
		FText Name;
		FText Note;
		FText ForYou;
		FText ForCrew;
		bool bOpen = false;
	};
	struct FQuartermasterPage
	{
		TArray<FUniformOption> Uniforms;
		TArray<FRibbonRow> Ribbons;
	};
	static FQuartermasterPage Quartermaster(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

	// ---- How to earn
	struct FRuleRow
	{
		FName Source;
		FText Text;
		FText Limits;
		FText Xp;
	};
	struct FEarnGroup
	{
		EVerseSubjectKind Kind = EVerseSubjectKind::Person;
		FText Title;
		TArray<FRuleRow> Rules;
	};
	struct FEarnPage
	{
		FText Hint;
		TArray<FEarnGroup> Groups;
	};
	static FEarnPage Earn(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

	// ---- Crew
	struct FCrewRow
	{
		FString SubjectId;
		FText Name;
		FName RankId;
		FText Rank;
		int32 Level = 1;
		int64 Xp = 0;
		bool bCompanion = false;
	};
	struct FCrewPage
	{
		/** Officers highest first, then the companion last. */
		TArray<FCrewRow> Rows;
		FText Empty;
		bool bNoOfficers = true;
	};
	static FCrewPage Crew(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings);

	// ---- Shared words
	static FText Figure(int64 Value);
	/** "{key}" arguments as culture-invariant text. */
	static FText Fill(const FVerseUiStrings& Strings, const FString& Key, const TMap<FString, FString>& Values);
	static FText RankName(const FVerseUiStrings& Strings, FName RankId);
	static FText TierName(const FVerseUiStrings& Strings, FName Tier);
	/** "45 s", "10 min" */
	static FString CooldownText(int32 Seconds);
};

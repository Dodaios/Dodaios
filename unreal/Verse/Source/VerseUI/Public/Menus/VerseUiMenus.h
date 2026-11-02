#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"

/** One loadout line of the armoury (combat-state 2.2). */
struct VERSEUI_API FVerseArmouryItem
{
	EVerseLoadoutSlot Slot = EVerseLoadoutSlot::Primary;
	/** Item id; strings keys verse.item.<id>.name and verse.item.<id>.role. */
	FName ItemId;
	/** "firearm" | "melee" | "gadget" */
	FString Kind;
};

/**
 * Armoury (WP18.6): the loadout both duellists get, the bot tier, start duel. Data from
 * unreal/Verse/Data/ui/armoury.json; the loadout follows UVerseRuleset::GetLoadout once WP11
 * offers a choice.
 */
class VERSEUI_API FVerseArmouryModel
{
public:
	static FString DefaultPath();
	bool LoadJson(const FString& Json, FString* OutError = nullptr);
	bool LoadFile(const FString& Path, FString* OutError = nullptr);

	const TArray<FVerseArmouryItem>& GetLoadout() const { return Loadout; }
	/** normal, hard, elite, adaptive */
	const TArray<FName>& GetTiers() const { return Tiers; }
	FName GetSelectedTier() const { return SelectedTier; }
	bool SelectTier(FName Tier);
	void CycleTier(int32 Direction);

private:
	TArray<FVerseArmouryItem> Loadout;
	TArray<FName> Tiers;
	FName SelectedTier = TEXT("hard");
};

enum class EVerseBarEntryKind : uint8
{
	QuickStartDuel,
	Deck,
	ReturnToApp,
};

struct VERSEUI_API FVerseBarEntry
{
	EVerseBarEntryKind Kind = EVerseBarEntryKind::Deck;
	/** Deck id for Deck entries. */
	FName Id;
	FString LabelKey;
	bool bActive = false;
	bool bEnabled = true;
};

/** Verse bar (WP18.7, parity D-03): quick-start duel, the decks of welcome.decks, return to app. */
struct VERSEUI_API FVerseBarModel
{
	static TArray<FVerseBarEntry> Build(const TArray<FName>& Decks, FName CurrentDeck, bool bDuelRunning);
};

struct VERSEUI_API FVerseEndScreenRow
{
	FString LabelKey;
	FText Person;
	FText Opponent;
};

/** End-of-set screen (WP18.9) from FVerseSetSummary and, for the adaptive tier, the bot's s. */
struct VERSEUI_API FVerseEndScreen
{
	EVerseSetOutcome Outcome = EVerseSetOutcome::Unfinished;
	FString TitleKey;
	int32 SetIndex = 0;
	int32 PersonKills = 0;
	int32 OpponentKills = 0;
	FName Tier;
	bool bShowSkill = false;
	/** Adaptive s in [0, 1] (bot.md 9.2). */
	float Skill = -1.f;
	TArray<FVerseEndScreenRow> Rows;

	/** Numbers are formatted in Lang (the Verse UI language), never the machine's culture. */
	static FVerseEndScreen Build(const FVerseSetSummary& Summary, float BotEffectiveSkill, const FString& Lang = TEXT("en"));
};

/** The screens the UI layer can show over the game. */
enum class EVerseUiScreen : uint8
{
	None,
	EscMenu,
	Settings,
	Armoury,
	EndOfSet,
};

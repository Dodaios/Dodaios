#pragma once

#include "CoreMinimal.h"

class FVerseUiStrings;

/** Gives a widget the strings of the moment (the language can change while it is on screen). */
using FVerseStringsGetter = TFunction<const FVerseUiStrings&()>;

/** The capital ship's decks, top to bottom (ids are a contract with the cook and the app). */
struct VERSEUI_API FVerseDeckIds
{
	static const TArray<FName>& All();
	static bool IsDeck(FName Deck);
	/** One-based number on the lift and the title (parity B-02); 0 for an unknown deck. */
	static int32 Number(FName Deck);
	/** Two digits, "04". */
	static FString NumberText(FName Deck);
};

/** Who is on the deck, by duty. */
struct VERSEUI_API FVerseCrewCounts
{
	int32 Aboard = 0;
	int32 Working = 0;
	/** Officers waiting for the person; an error counts as waiting. */
	int32 Waiting = 0;
};

/** One officer on the deck. State: idle, working, waiting, error. */
struct VERSEUI_API FVerseDeckCrewRow
{
	FName State;
};

/** The deck title, top left (parity B-02, H-01). */
struct VERSEUI_API FVerseDeckTitle
{
	FName Deck;
	/** "04" */
	FString Number;
	/** "Deck 4" (verse.deck.label with n). */
	FText Label;
	FText Name;
	FText About;
	FVerseCrewCounts Counts;
	FText AboardText;
	FText WorkingText;
	FText WaitingText;
	/** The waiting figure shows only when somebody waits. */
	bool bShowWaiting = false;

	static FVerseCrewCounts CountCrew(const TArray<FVerseDeckCrewRow>& Rows);
	static FVerseDeckTitle Build(const FVerseUiStrings& Strings, FName Deck, const FVerseCrewCounts& Counts);
};

enum class EVerseDeckView : uint8
{
	Overview,
	Third,
	First,
};

enum class EVerseTool : uint8
{
	ViewOverview,
	ViewThird,
	ViewFirst,
	Lift,
	Hoverboard,
	Commander,
	Duel,
	Settings,
	Help,
};

struct VERSEUI_API FVerseToolEntry
{
	EVerseTool Tool = EVerseTool::Help;
	/** Strings key of the label. */
	FString LabelKey;
	/** The key that does the same thing ("1", "B"), empty when there is none. */
	FString KeyHint;
	bool bEnabled = true;
	bool bPressed = false;
};

/** What decides which tools the rail offers. */
struct VERSEUI_API FVerseToolRailContext
{
	EVerseDeckView View = EVerseDeckView::Third;
	/** Needs the deck's eye-level scene. */
	bool bFirstAvailable = true;
	/** The compact panel inside the app: no duel, no settings. */
	bool bCompactPanel = false;
	/** The deck has an eye-level view on this stage: settings are offered only then. */
	bool bEyeLevelPossible = true;
	bool bHoverboardAvailable = true;
	bool bHoverboardOut = false;
};

/** The tool rail, top right (parity H-03). */
struct VERSEUI_API FVerseToolRail
{
	static TArray<FVerseToolEntry> Build(const FVerseToolRailContext& Context);
	/** Which view a tool picks, if it is a view tool. */
	static bool ViewOfTool(EVerseTool Tool, EVerseDeckView& OutView);
	/** The next view when V cycles. */
	static EVerseDeckView CycleView(EVerseDeckView View, bool bFirstAvailable);
};

/** The help line and the click-to-look hint (parity H-08). */
struct VERSEUI_API FVerseDeckHelp
{
	/** Eye level and overview differ; the duel line is appended to both. */
	static FText Build(const FVerseUiStrings& Strings, bool bEyeLevel, bool bDuelLine = true);
	/** Key of the help body for the view. */
	static FString BodyKey(bool bEyeLevel);
	/** The hint shows at eye level while the mouse is not yet taken and no dialog is open. */
	static bool ShowClickToLook(bool bEyeLevel, bool bMouseTaken, bool bDialogOpen);
};

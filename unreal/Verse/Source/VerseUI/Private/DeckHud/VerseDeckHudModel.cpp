#include "DeckHud/VerseDeckHudModel.h"

#include "Core/VerseUiStrings.h"

const TArray<FName>& FVerseDeckIds::All()
{
	static const TArray<FName> Decks = {FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")), FName(TEXT("hangar"))};
	return Decks;
}

bool FVerseDeckIds::IsDeck(FName Deck)
{
	return All().Contains(Deck);
}

int32 FVerseDeckIds::Number(FName Deck)
{
	return All().IndexOfByKey(Deck) + 1;
}

FString FVerseDeckIds::NumberText(FName Deck)
{
	return FString::Printf(TEXT("%02d"), Number(Deck));
}

FVerseCrewCounts FVerseDeckTitle::CountCrew(const TArray<FVerseDeckCrewRow>& Rows)
{
	FVerseCrewCounts Counts;
	Counts.Aboard = Rows.Num();
	for (const FVerseDeckCrewRow& Row : Rows)
	{
		if (Row.State == FName(TEXT("working")))
		{
			++Counts.Working;
		}
		else if (Row.State == FName(TEXT("waiting")) || Row.State == FName(TEXT("error")))
		{
			++Counts.Waiting;
		}
	}
	return Counts;
}

FVerseDeckTitle FVerseDeckTitle::Build(const FVerseUiStrings& Strings, FName Deck, const FVerseCrewCounts& Counts)
{
	FVerseDeckTitle Title;
	Title.Deck = Deck;
	Title.Number = FVerseDeckIds::NumberText(Deck);
	Title.Counts = Counts;
	FFormatNamedArguments LabelArgs;
	LabelArgs.Add(TEXT("n"), Strings.Number(FVerseDeckIds::Number(Deck)));
	Title.Label = Strings.Format(TEXT("verse.deck.label"), LabelArgs);
	Title.Name = Strings.Get(FString::Printf(TEXT("verse.deck.%s"), *Deck.ToString()));
	Title.About = Strings.Get(FString::Printf(TEXT("verse.deck.%s_about"), *Deck.ToString()));
	auto Counted = [&Strings](const TCHAR* Key, int32 Value)
	{
		FFormatNamedArguments Args;
		Args.Add(TEXT("count"), Strings.Number(Value));
		return Strings.Format(Key, Args);
	};
	Title.AboardText = Counted(TEXT("verse.crew.aboard"), Counts.Aboard);
	Title.WorkingText = Counted(TEXT("verse.crew.working"), Counts.Working);
	Title.WaitingText = Counted(TEXT("verse.crew.waiting"), Counts.Waiting);
	Title.bShowWaiting = Counts.Waiting > 0;
	return Title;
}

TArray<FVerseToolEntry> FVerseToolRail::Build(const FVerseToolRailContext& Context)
{
	TArray<FVerseToolEntry> Out;
	auto Add = [&Out](EVerseTool Tool, const TCHAR* Label, const TCHAR* Key, bool bEnabled = true, bool bPressed = false)
	{
		FVerseToolEntry Entry;
		Entry.Tool = Tool;
		Entry.LabelKey = Label;
		Entry.KeyHint = Key;
		Entry.bEnabled = bEnabled;
		Entry.bPressed = bPressed;
		Out.Add(Entry);
	};
	Add(EVerseTool::ViewOverview, TEXT("verse.tools.overview"), TEXT("1"), true, Context.View == EVerseDeckView::Overview);
	Add(EVerseTool::ViewThird, TEXT("verse.tools.follow"), TEXT("2"), true, Context.View == EVerseDeckView::Third);
	Add(EVerseTool::ViewFirst, TEXT("verse.tools.first"), TEXT("3"), Context.bFirstAvailable, Context.View == EVerseDeckView::First);
	Add(EVerseTool::Lift, TEXT("verse.tools.lift"), TEXT(""));
	if (Context.bHoverboardAvailable)
	{
		Add(EVerseTool::Hoverboard, TEXT("verse.tools.board"), TEXT("B"), true, Context.bHoverboardOut);
	}
	Add(EVerseTool::Commander, TEXT("verse.tools.commander"), TEXT(""));
	if (!Context.bCompactPanel)
	{
		Add(EVerseTool::Duel, TEXT("verse.tools.duel"), TEXT(""));
	}
	if (Context.bEyeLevelPossible && !Context.bCompactPanel)
	{
		Add(EVerseTool::Settings, TEXT("verse.tools.settings"), TEXT(""));
	}
	Add(EVerseTool::Help, TEXT("verse.tools.help"), TEXT(""));
	return Out;
}

bool FVerseToolRail::ViewOfTool(EVerseTool Tool, EVerseDeckView& OutView)
{
	switch (Tool)
	{
	case EVerseTool::ViewOverview: OutView = EVerseDeckView::Overview; return true;
	case EVerseTool::ViewThird: OutView = EVerseDeckView::Third; return true;
	case EVerseTool::ViewFirst: OutView = EVerseDeckView::First; return true;
	default: return false;
	}
}

EVerseDeckView FVerseToolRail::CycleView(EVerseDeckView View, bool bFirstAvailable)
{
	switch (View)
	{
	case EVerseDeckView::Overview: return EVerseDeckView::Third;
	case EVerseDeckView::Third: return bFirstAvailable ? EVerseDeckView::First : EVerseDeckView::Overview;
	default: return EVerseDeckView::Overview;
	}
}

FString FVerseDeckHelp::BodyKey(bool bEyeLevel)
{
	return bEyeLevel ? TEXT("verse.stage.help_eye") : TEXT("verse.stage.help");
}

FText FVerseDeckHelp::Build(const FVerseUiStrings& Strings, bool bEyeLevel, bool bDuelLine)
{
	const FString Body = Strings.Get(BodyKey(bEyeLevel)).ToString();
	if (!bDuelLine)
	{
		return Strings.Get(BodyKey(bEyeLevel));
	}
	return FText::AsCultureInvariant(Body + TEXT(" ") + Strings.Get(TEXT("verse.stage.help_duel")).ToString());
}

bool FVerseDeckHelp::ShowClickToLook(bool bEyeLevel, bool bMouseTaken, bool bDialogOpen)
{
	return bEyeLevel && !bMouseTaken && !bDialogOpen;
}

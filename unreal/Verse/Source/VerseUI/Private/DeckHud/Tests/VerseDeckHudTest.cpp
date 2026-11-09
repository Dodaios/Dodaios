#include "Core/VerseUiStrings.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/Paths.h"
#include "DeckHud/SVerseDialogFrame.h"
#include "DeckHud/VerseDeckHudModel.h"
#include "DeckHud/VerseDeckHudSubsystem.h"
#include "DeckHud/VerseDialogStack.h"
#include "Events/VerseEventHub.h"
#include "Framework/Application/SlateApplication.h"
#include "InputCoreTypes.h"
#include "Lift/SVerseLift.h"
#include "Lift/VerseLiftModel.h"
#include "Loading/SVerseLoadingScreen.h"
#include "Loading/VerseLoadingModel.h"
#include "Misc/AutomationTest.h"
#include "Notices/VerseNoticeLine.h"
#include "ServiceRecord/SVerseRankCard.h"
#include "ServiceRecord/VerseRankPlate.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Parity.<Section>.<Id>: the deck HUD, the lift, the loading screen, the notices and the
// dialogs of stream S6 (parity.md rows A-07, B-02, L-01, L-02, L-05, L-06, H-01, H-02, H-03,
// H-07, H-08, H-12, H-13, R-01, R-03). The models carry the behaviour and take a pinned clock;
// the widgets are built where Slate is up.

#define VERSE_S6_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseS6Test
{
	FVerseUiStrings LoadStrings(const FString& Lang)
	{
		FVerseUiStrings Strings;
		Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		Strings.SetLanguage(Lang);
		return Strings;
	}

	/** A test world with the UI and the deck HUD subsystems on a pinned clock. */
	struct FDeckWorld : FVerseUiTestWorld
	{
		UVerseDeckHudSubsystem* Hud = nullptr;
		double HudNow = 500.0;

		FDeckWorld()
		{
			Hud = World ? World->GetSubsystem<UVerseDeckHudSubsystem>() : nullptr;
			if (Hud)
			{
				Hud->Clock = [this] { return HudNow; };
			}
		}
	};
}

using namespace VerseS6Test;

// A-07: the loading widget shows until the deck's first frame, then fades out in under 600 ms.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityA07Test, "Verse.Parity.A.07", VERSE_S6_FLAGS)
bool FVerseParityA07Test::RunTest(const FString&)
{
	FVerseLoadingModel Model;
	TestEqual(TEXT("hidden before the app opens"), Model.GetPhase(), FVerseLoadingModel::EPhase::Hidden);
	Model.Begin(100.0, 7);
	TestTrue(TEXT("tip is one of the three"), Model.GetTip() >= 1 && Model.GetTip() <= FVerseLoadingModel::NumTips);
	float Last = -1.f;
	for (double T = 100.0; T <= 112.0; T += 0.25)
	{
		Model.Tick(T);
		TestEqual(TEXT("still showing with no first frame"), Model.GetPhase(), FVerseLoadingModel::EPhase::Showing);
		TestEqual(TEXT("fully opaque"), Model.Opacity(T), 1.f);
		const float P = Model.Progress(T);
		TestTrue(TEXT("the bar only moves forward"), P >= Last);
		TestTrue(TEXT("the bar waits for the real ready"), P < 0.93f);
		Last = P;
	}
	Model.NotifyFirstDeckFrame(112.0);
	TestEqual(TEXT("the first frame starts the fade"), Model.GetPhase(), FVerseLoadingModel::EPhase::Leaving);
	TestEqual(TEXT("the bar is full"), Model.Progress(112.0), 1.f);
	Model.Tick(112.26);
	TestTrue(TEXT("half way, half transparent"), Model.Opacity(112.26) > 0.f && Model.Opacity(112.26) < 1.f);
	Model.Tick(112.6);
	TestEqual(TEXT("gone"), Model.GetPhase(), FVerseLoadingModel::EPhase::Gone);
	TestTrue(TEXT("fade under 600 ms"), Model.GetGoneAt() - Model.GetFadeStartedAt() < 0.6);
	TestTrue(TEXT("fade starts at the first frame"), FMath::IsNearlyEqual(Model.GetFadeStartedAt(), 112.0));

	// A deck that loads in a blink does not flash the screen.
	FVerseLoadingModel Quick;
	Quick.Begin(200.0, 1);
	Quick.NotifyFirstDeckFrame(200.1);
	Quick.Tick(200.5);
	TestEqual(TEXT("held for the minimum"), Quick.GetPhase(), FVerseLoadingModel::EPhase::Showing);
	Quick.Tick(200.0 + FVerseLoadingModel::MinShowSeconds);
	TestEqual(TEXT("then fades"), Quick.GetPhase(), FVerseLoadingModel::EPhase::Leaving);

	// Words and art of the widget exist in every language.
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		const FVerseUiStrings Strings = LoadStrings(Lang);
		TestFalse(TEXT("title"), Strings.GetIn(TEXT("verse.loading.title"), Lang).IsEmpty());
		for (int32 Tip = 1; Tip <= FVerseLoadingModel::NumTips; ++Tip)
		{
			TestFalse(TEXT("tip"), Strings.GetIn(FString::Printf(TEXT("verse.loading.tip_%d"), Tip), Lang).IsEmpty());
		}
	}
	TestTrue(TEXT("key art file ships"), FPaths::FileExists(SVerseLoadingScreen::KeyArtPath()));
	FDeckWorld W;
	if (W.Hud && FSlateApplication::IsInitialized())
	{
		W.Hud->GetLoading().Begin(W.HudNow, 0);
		const TSharedRef<SVerseLoadingScreen> Widget = SNew(SVerseLoadingScreen, W.Hud);
		TestTrue(TEXT("the loading widget builds"), Widget->GetVisibility().IsVisible());
	}
	return true;
}

// B-02: the deck number is one-based on the title.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityB02Test, "Verse.Parity.B.02", VERSE_S6_FLAGS)
bool FVerseParityB02Test::RunTest(const FString&)
{
	TestEqual(TEXT("bridge is 01"), FVerseDeckIds::NumberText(TEXT("bridge")), FString(TEXT("01")));
	TestEqual(TEXT("hangar is 04"), FVerseDeckIds::NumberText(TEXT("hangar")), FString(TEXT("04")));
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		const FVerseUiStrings Strings = LoadStrings(Lang);
		const FVerseDeckTitle Title = FVerseDeckTitle::Build(Strings, TEXT("hangar"), FVerseCrewCounts());
		TestEqual(TEXT("title number"), Title.Number, FString(TEXT("04")));
		TestTrue(FString::Printf(TEXT("%s label carries deck number 4"), *Lang), Title.Label.ToString().Contains(TEXT("4")));
		TestFalse(TEXT("deck name"), Title.Name.ToString().IsEmpty());
		TestFalse(TEXT("deck line"), Title.About.ToString().IsEmpty());
	}
	const FVerseDeckTitle En = FVerseDeckTitle::Build(LoadStrings(TEXT("en")), TEXT("hangar"), FVerseCrewCounts());
	TestEqual(TEXT("label"), En.Label.ToString(), FString(TEXT("Deck 4")));
	TestEqual(TEXT("name"), En.Name.ToString(), FString(TEXT("Hangar")));
	return true;
}

// L-01: the lift lists the decks top to bottom with the current one marked and focused.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityL01Test, "Verse.Parity.L.01", VERSE_S6_FLAGS)
bool FVerseParityL01Test::RunTest(const FString&)
{
	FVerseLiftModel Lift;
	Lift.SetCurrentDeck(TEXT("engineering"));
	Lift.OpenPanel(EVerseLiftSource::ToolRail);
	const TArray<FVerseLiftRow> Rows = Lift.Rows();
	if (!TestEqual(TEXT("four rows"), Rows.Num(), 4))
	{
		return false;
	}
	const TCHAR* Order[] = {TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar")};
	for (int32 I = 0; I < 4; ++I)
	{
		TestEqual(TEXT("DECK_IDS order"), Rows[I].Deck.ToString(), FString(Order[I]));
		TestEqual(TEXT("one-based number"), Rows[I].Number, FString::Printf(TEXT("%02d"), I + 1));
		TestEqual(TEXT("only the current row is marked"), Rows[I].bCurrent, I == 2);
		TestEqual(TEXT("and focused"), Rows[I].bFocused, I == 2);
	}
	Lift.MoveFocus(1);
	TestEqual(TEXT("focus moves"), Lift.GetFocusedDeck().ToString(), FString(TEXT("hangar")));
	Lift.MoveFocus(1);
	TestEqual(TEXT("and stops at the end"), Lift.GetFocusedDeck().ToString(), FString(TEXT("hangar")));
	Lift.ClosePanel();
	Lift.OpenPanel(EVerseLiftSource::Station);
	TestEqual(TEXT("reopening starts on the current deck again"), Lift.GetFocusedDeck().ToString(), FString(TEXT("engineering")));

	// The widget lists the same rows.
	FDeckWorld W;
	if (W.Hud && FSlateApplication::IsInitialized())
	{
		W.Hud->GetLift().SetCurrentDeck(TEXT("ops"));
		const TSharedRef<SVerseLiftPanel> Panel = SNew(SVerseLiftPanel, W.Hud);
		const TArray<TSharedRef<SWidget>> Buttons = StaticCastSharedRef<SVerseDialogFrame>(Panel->GetChildren()->GetChildAt(0))->CollectFocusables();
		TestEqual(TEXT("a button per deck and a close button"), Buttons.Num(), 5);
	}
	return true;
}

// L-02: choosing a deck shuts the doors, rides, opens them on the new deck.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityL02Test, "Verse.Parity.L.02", VERSE_S6_FLAGS)
bool FVerseParityL02Test::RunTest(const FString&)
{
	FVerseLiftModel Lift;
	Lift.SetCurrentDeck(TEXT("hangar"));
	TArray<FName> Travelled;
	Lift.TravelTo = [&Travelled](FName Deck) { Travelled.Add(Deck); };
	Lift.OpenPanel(EVerseLiftSource::ToolRail);
	double T = 10.0;
	TestTrue(TEXT("another deck starts a ride"), Lift.Choose(TEXT("bridge"), T));
	TestFalse(TEXT("the panel closes"), Lift.IsPanelOpen());
	TestEqual(TEXT("doors are closing"), Lift.GetDoors(), EVerseDoorState::Closing);
	TestEqual(TEXT("deck unchanged while the doors close"), Travelled.Num(), 0);
	// Frames at 60 Hz. The new deck's first frame comes 500 ms after the doors shut.
	bool bReadySent = false;
	for (; T < 14.0 && Lift.IsRiding(); T += 1.0 / 60.0)
	{
		Lift.Tick(T);
		if (Travelled.Num() > 0 && !bReadySent && T >= Lift.GetClosedAt() + 0.5)
		{
			bReadySent = true;
			Lift.NotifyDeckReady(TEXT("bridge"), T);
		}
	}
	TestEqual(TEXT("travelled once to the chosen deck"), Travelled.Num(), 1);
	TestEqual(TEXT("to bridge"), Travelled.Num() > 0 ? Travelled[0].ToString() : FString(), FString(TEXT("bridge")));
	TestFalse(TEXT("ride is over"), Lift.IsRiding());
	TestEqual(TEXT("current deck changed"), Lift.GetCurrentDeck().ToString(), FString(TEXT("bridge")));
	TestTrue(TEXT("doors stayed shut at least 400 ms"), Lift.GetOpenStartedAt() - Lift.GetClosedAt() >= 0.4 - KINDA_SMALL_NUMBER);
	TestTrue(TEXT("doors open within 150 ms of the first frame"), Lift.GetOpenStartedAt() - Lift.GetReadyAt() <= 0.15 + KINDA_SMALL_NUMBER);
	TestTrue(TEXT("and not before it"), Lift.GetOpenStartedAt() >= Lift.GetReadyAt());

	// A deck that is ready early still waits out the minimum: the doors stay shut 400 ms, then open.
	FVerseLiftModel Early;
	Early.SetCurrentDeck(TEXT("hangar"));
	Early.TravelTo = [](FName) {};
	Early.Choose(TEXT("ops"), 30.0);
	Early.Tick(30.4);
	Early.NotifyDeckReady(TEXT("ops"), 30.45);
	TestEqual(TEXT("still shut"), Early.GetDoors(), EVerseDoorState::Closed);
	for (double E = 30.5; E < 31.5; E += 0.01)
	{
		Early.Tick(E);
	}
	TestTrue(TEXT("opened exactly when 400 ms were up"), FMath::IsNearlyEqual(Early.GetOpenStartedAt() - Early.GetClosedAt(), FVerseLiftModel::MinClosedSeconds, 0.001));
	TestEqual(TEXT("deck changed"), Early.GetCurrentDeck().ToString(), FString(TEXT("ops")));

	// A slow deck keeps the doors shut, then they open right after its first frame.
	FVerseLiftModel Slow;
	Slow.SetCurrentDeck(TEXT("hangar"));
	Slow.TravelTo = [](FName) {};
	Slow.Choose(TEXT("ops"), 50.0);
	Slow.Tick(50.4);
	Slow.Tick(53.0);
	TestEqual(TEXT("shut while the deck loads"), Slow.GetDoors(), EVerseDoorState::Closed);
	TestEqual(TEXT("doors fully shut"), Slow.DoorFraction(53.0), 1.f);
	Slow.NotifyDeckReady(TEXT("ops"), 53.0);
	TestEqual(TEXT("opening"), Slow.GetDoors(), EVerseDoorState::Opening);
	TestTrue(TEXT("within 150 ms"), Slow.GetOpenStartedAt() - 53.0 <= 0.15);

	// A deck that never arrives does not trap the person in the lift.
	FVerseLiftModel Stuck;
	Stuck.SetCurrentDeck(TEXT("hangar"));
	Stuck.TravelTo = [](FName) {};
	Stuck.Choose(TEXT("ops"), 0.0);
	for (double S = 0.0; S < FVerseLiftModel::RideTimeoutSeconds + 2.0; S += 0.1)
	{
		Stuck.Tick(S);
	}
	TestFalse(TEXT("doors open again"), Stuck.IsRiding());
	TestEqual(TEXT("on the old deck"), Stuck.GetCurrentDeck().ToString(), FString(TEXT("hangar")));
	return true;
}

// L-05: the same deck closes the panel and rides nowhere.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityL05Test, "Verse.Parity.L.05", VERSE_S6_FLAGS)
bool FVerseParityL05Test::RunTest(const FString&)
{
	FVerseLiftModel Lift;
	Lift.SetCurrentDeck(TEXT("ops"));
	int32 Rides = 0;
	Lift.TravelTo = [&Rides](FName) { ++Rides; };
	Lift.OpenPanel(EVerseLiftSource::TitleSwitch);
	TestFalse(TEXT("no ride"), Lift.Choose(TEXT("ops"), 1.0));
	TestFalse(TEXT("panel closed"), Lift.IsPanelOpen());
	TestEqual(TEXT("doors stay open"), Lift.GetDoors(), EVerseDoorState::Open);
	for (double T = 1.0; T < 4.0; T += 0.1)
	{
		Lift.Tick(T);
	}
	TestEqual(TEXT("nothing travelled"), Rides, 0);
	TestFalse(TEXT("an unknown deck is not a ride"), Lift.Choose(TEXT("galley"), 5.0));
	return true;
}

// L-06: the lift station, the deck title switch and the tool rail each open the lift UI.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityL06Test, "Verse.Parity.L.06", VERSE_S6_FLAGS)
bool FVerseParityL06Test::RunTest(const FString&)
{
	FDeckWorld W;
	if (!TestNotNull(TEXT("deck HUD subsystem"), W.Hud))
	{
		return false;
	}
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	FVerseStationUsedEvent Armoury;
	Armoury.Kind = TEXT("armoury");
	Armoury.UserId = W.Source->GetLocalPlayerId();
	Hub->OnStationUsed.Broadcast(Armoury);
	TestFalse(TEXT("another station does not open the lift"), W.Hud->GetLift().IsPanelOpen());

	FVerseStationUsedEvent Station;
	Station.Kind = TEXT("lift");
	Station.UserId = W.Source->GetLocalPlayerId();
	Hub->OnStationUsed.Broadcast(Station);
	TestTrue(TEXT("the lift station opens it"), W.Hud->GetLift().IsPanelOpen());
	TestEqual(TEXT("from the station"), W.Hud->GetLift().GetLastSource(), EVerseLiftSource::Station);
	W.Hud->CloseLift();
	TestFalse(TEXT("closed"), W.Hud->GetLift().IsPanelOpen());

	W.Hud->OpenLift(EVerseLiftSource::TitleSwitch);
	TestTrue(TEXT("the title switch opens it"), W.Hud->GetLift().IsPanelOpen());
	TestEqual(TEXT("from the title"), W.Hud->GetLift().GetLastSource(), EVerseLiftSource::TitleSwitch);
	W.Hud->CloseLift();

	W.Hud->ActivateTool(EVerseTool::Lift);
	TestTrue(TEXT("the tool rail opens it"), W.Hud->GetLift().IsPanelOpen());
	TestEqual(TEXT("from the rail"), W.Hud->GetLift().GetLastSource(), EVerseLiftSource::ToolRail);
	TestTrue(TEXT("an open lift is a modal dialog"), W.Hud->GetDialogs().IsOpen(TEXT("lift")));

	// Choosing a deck from the open panel rides through the model and the UI game port.
	W.Hud->SetDeck(TEXT("hangar"));
	TestTrue(TEXT("a ride starts"), W.Hud->ChooseDeck(TEXT("bridge")));
	TestFalse(TEXT("the panel closed"), W.Hud->GetDialogs().IsOpen(TEXT("lift")));
	W.HudNow += 1.0;
	W.Hud->Tick(0.016f);
	TestEqual(TEXT("the game port was asked for the deck"), W.Game->CurrentDeck.ToString(), FString(TEXT("bridge")));
	W.HudNow += 2.0;
	W.Hud->Tick(0.016f);
	W.HudNow += 1.0;
	W.Hud->Tick(0.016f);
	TestFalse(TEXT("the ride is over"), W.Hud->GetLift().IsRiding());
	TestEqual(TEXT("the title shows the new deck"), W.Hud->GetTitle().Number, FString(TEXT("01")));
	return true;
}

// H-01: the title counts who is aboard, working and waiting; an error counts as waiting.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH01Test, "Verse.Parity.H.01", VERSE_S6_FLAGS)
bool FVerseParityH01Test::RunTest(const FString&)
{
	const TArray<FVerseDeckCrewRow> Rows = {{TEXT("working")}, {TEXT("working")}, {TEXT("error")}, {TEXT("idle")}};
	const FVerseCrewCounts Counts = FVerseDeckTitle::CountCrew(Rows);
	TestEqual(TEXT("aboard"), Counts.Aboard, 4);
	TestEqual(TEXT("working"), Counts.Working, 2);
	TestEqual(TEXT("waiting (an error counts)"), Counts.Waiting, 1);
	const TArray<FVerseDeckCrewRow> WaitingToo = {{TEXT("waiting")}, {TEXT("error")}, {TEXT("working")}};
	TestEqual(TEXT("waiting and error add up"), FVerseDeckTitle::CountCrew(WaitingToo).Waiting, 2);

	const FVerseDeckTitle Title = FVerseDeckTitle::Build(LoadStrings(TEXT("en")), TEXT("hangar"), Counts);
	TestEqual(TEXT("aboard text"), Title.AboardText.ToString(), FString(TEXT("4 aboard")));
	TestEqual(TEXT("working text"), Title.WorkingText.ToString(), FString(TEXT("2 on duty")));
	TestEqual(TEXT("waiting text"), Title.WaitingText.ToString(), FString(TEXT("1 need you")));
	TestTrue(TEXT("the waiting figure shows"), Title.bShowWaiting);
	TestFalse(TEXT("and hides when nobody waits"), FVerseDeckTitle::Build(LoadStrings(TEXT("en")), TEXT("hangar"), FVerseCrewCounts()).bShowWaiting);

	FDeckWorld W;
	if (W.Hud)
	{
		W.Hud->SetCrew(Rows);
		TestEqual(TEXT("the subsystem title carries the crew"), W.Hud->GetTitle().Counts.Working, 2);
	}
	return true;
}

// H-02: the rank card shows the commander's rank and a click opens the record on "Record".
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH02Test, "Verse.Parity.H.02", VERSE_S6_FLAGS)
bool FVerseParityH02Test::RunTest(const FString&)
{
	const TSharedRef<FVerseServiceRecordModel> Model = MakeShared<FVerseServiceRecordModel>();
	const TSharedPtr<FJsonObject> Person = MakeShared<FJsonObject>();
	Person->SetStringField(TEXT("subject_id"), TEXT("person"));
	Person->SetStringField(TEXT("kind"), TEXT("person"));
	Person->SetNumberField(TEXT("level"), 14);
	Person->SetNumberField(TEXT("total_xp"), 5230);
	Person->SetNumberField(TEXT("into_level"), 130);
	Person->SetNumberField(TEXT("for_next"), 600);
	FJsonObject Snapshot;
	Snapshot.SetArrayField(TEXT("subjects"), {MakeShared<FJsonValueObject>(Person)});
	Model->ApplySnapshot(Snapshot);

	const FVerseUiStrings Strings = LoadStrings(TEXT("en"));
	const SVerseRankCard::FFacts Facts = SVerseRankCard::Describe(*Model, Strings);
	TestEqual(TEXT("rank id"), Facts.RankId.ToString(), FString(TEXT("lieutenant")));
	TestEqual(TEXT("rank"), Facts.Rank.ToString(), FString(TEXT("Lieutenant")));
	TestEqual(TEXT("level"), Facts.Level.ToString(), FString(TEXT("Level 14")));
	TestTrue(TEXT("what is missing for the next rank"), Facts.ToGo.ToString().Contains(TEXT("Senior Lieutenant")));
	TestTrue(TEXT("bar fraction"), FMath::IsNearlyEqual(Facts.Fraction, 130.f / 600.f, 0.001f));

	if (FSlateApplication::IsInitialized())
	{
		int32 Opened = 0;
		const TSharedRef<SVerseRankCard> Card = SNew(SVerseRankCard, Model.ToSharedPtr(), [&Strings]() -> const FVerseUiStrings& { return Strings; })
			.bCompact(true)
			.OnOpen_Lambda([&Opened] { ++Opened; });
		Card->Activate();
		TestEqual(TEXT("a click opens the record"), Opened, 1);
	}
	TestEqual(TEXT("the card opens the first page"), int32(EVerseRecordTab::Record), 0);
	return true;
}

// H-03: the tool rail has the view switch, lift, hoverboard, commander, duel, settings and help.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH03Test, "Verse.Parity.H.03", VERSE_S6_FLAGS)
bool FVerseParityH03Test::RunTest(const FString&)
{
	auto Has = [](const TArray<FVerseToolEntry>& Tools, EVerseTool Tool) { return Tools.ContainsByPredicate([Tool](const FVerseToolEntry& E) { return E.Tool == Tool; }); };
	auto Find = [](const TArray<FVerseToolEntry>& Tools, EVerseTool Tool) -> const FVerseToolEntry* { return Tools.FindByPredicate([Tool](const FVerseToolEntry& E) { return E.Tool == Tool; }); };

	FVerseToolRailContext Full;
	const TArray<FVerseToolEntry> Tools = FVerseToolRail::Build(Full);
	for (const EVerseTool Tool : {EVerseTool::ViewOverview, EVerseTool::ViewThird, EVerseTool::ViewFirst, EVerseTool::Lift, EVerseTool::Hoverboard, EVerseTool::Commander, EVerseTool::Duel, EVerseTool::Settings, EVerseTool::Help})
	{
		TestTrue(TEXT("the full rail has the tool"), Has(Tools, Tool));
	}
	TestEqual(TEXT("view keys 1 2 3"), Find(Tools, EVerseTool::ViewOverview)->KeyHint + Find(Tools, EVerseTool::ViewThird)->KeyHint + Find(Tools, EVerseTool::ViewFirst)->KeyHint, FString(TEXT("123")));
	TestEqual(TEXT("hoverboard key"), Find(Tools, EVerseTool::Hoverboard)->KeyHint, FString(TEXT("B")));
	TestTrue(TEXT("the view on screen is pressed"), Find(Tools, EVerseTool::ViewThird)->bPressed && !Find(Tools, EVerseTool::ViewOverview)->bPressed);

	FVerseToolRailContext Panel;
	Panel.bCompactPanel = true;
	const TArray<FVerseToolEntry> PanelTools = FVerseToolRail::Build(Panel);
	TestFalse(TEXT("no duel in the panel"), Has(PanelTools, EVerseTool::Duel));
	TestFalse(TEXT("no settings in the panel"), Has(PanelTools, EVerseTool::Settings));
	TestTrue(TEXT("but the lift stays"), Has(PanelTools, EVerseTool::Lift));

	FVerseToolRailContext NoEye;
	NoEye.bEyeLevelPossible = false;
	NoEye.bFirstAvailable = false;
	const TArray<FVerseToolEntry> NoEyeTools = FVerseToolRail::Build(NoEye);
	TestFalse(TEXT("settings only where eye level is possible"), Has(NoEyeTools, EVerseTool::Settings));
	TestFalse(TEXT("first person is off where it cannot run"), Find(NoEyeTools, EVerseTool::ViewFirst)->bEnabled);

	// Labels and tips exist in every language.
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		const FVerseUiStrings Strings = LoadStrings(Lang);
		for (const FVerseToolEntry& Entry : Tools)
		{
			TestFalse(TEXT("tool label"), Strings.GetIn(Entry.LabelKey, Lang).IsEmpty());
		}
	}
	// V cycles the views; first person is skipped where it is off.
	TestEqual(TEXT("V from overview"), FVerseToolRail::CycleView(EVerseDeckView::Overview, true), EVerseDeckView::Third);
	TestEqual(TEXT("V from third"), FVerseToolRail::CycleView(EVerseDeckView::Third, true), EVerseDeckView::First);
	TestEqual(TEXT("V from third without first"), FVerseToolRail::CycleView(EVerseDeckView::Third, false), EVerseDeckView::Overview);

	// Using a view tool switches the view and says so in one notice line.
	FDeckWorld W;
	if (W.Hud)
	{
		W.Hud->ActivateTool(EVerseTool::ViewOverview);
		TestEqual(TEXT("overview"), W.Hud->GetView(), EVerseDeckView::Overview);
		TestFalse(TEXT("a notice says so"), W.Hud->GetNoticeText().IsEmpty());
	}
	return true;
}

// H-07: a notice lives 4.2 s, help text 15 s, one line at a time.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH07Test, "Verse.Parity.H.07", VERSE_S6_FLAGS)
bool FVerseParityH07Test::RunTest(const FString&)
{
	FVerseNoticeLine Line;
	Line.PostNotice(FText::AsCultureInvariant(TEXT("first")), 10.0);
	TestTrue(TEXT("notice lifetime 4.2 s +- 0.1"), FMath::Abs(Line.GetLifetime() - 4.2) <= 0.1);
	TestTrue(TEXT("visible at 4.1 s"), Line.IsVisible(14.1));
	TestFalse(TEXT("gone at 4.3 s"), Line.IsVisible(14.3));
	TestTrue(TEXT("empty once expired"), Line.GetText(14.3).IsEmpty());

	Line.PostNotice(FText::AsCultureInvariant(TEXT("first")), 20.0);
	Line.PostNotice(FText::AsCultureInvariant(TEXT("second")), 21.0);
	TestEqual(TEXT("one line: the newer replaces the older"), Line.GetText(21.5).ToString(), FString(TEXT("second")));
	TestTrue(TEXT("and runs its own time"), Line.IsVisible(25.1) && !Line.IsVisible(25.3));

	Line.PostHelp(FText::AsCultureInvariant(TEXT("help")), 30.0);
	TestTrue(TEXT("help lifetime 15 s +- 0.1"), FMath::Abs(Line.GetLifetime() - 15.0) <= 0.1);
	TestTrue(TEXT("visible at 14.9 s"), Line.IsVisible(44.9));
	TestFalse(TEXT("gone at 15.1 s"), Line.IsVisible(45.1));
	TestEqual(TEXT("kind"), Line.GetKind(), FVerseNoticeLine::EKind::Help);

	Line.PostNotice(FText::GetEmpty(), 50.0);
	TestFalse(TEXT("an empty notice posts nothing"), Line.IsVisible(50.1));

	// Through the subsystem, on its clock.
	FDeckWorld W;
	if (W.Hud)
	{
		W.Hud->PostNoticeKey(TEXT("verse.notice.view_overview"));
		TestFalse(TEXT("shown"), W.Hud->GetNoticeText().IsEmpty());
		W.HudNow += 4.3;
		TestTrue(TEXT("gone after 4.3 s"), W.Hud->GetNoticeText().IsEmpty());
		W.Hud->ShowHelp();
		W.HudNow += 14.0;
		TestFalse(TEXT("help still up after 14 s"), W.Hud->GetNoticeText().IsEmpty());
		W.HudNow += 1.2;
		TestTrue(TEXT("help gone after 15.2 s"), W.Hud->GetNoticeText().IsEmpty());
	}
	return true;
}

// H-08: the help differs at eye level and in overview, and ends with the duel line.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH08Test, "Verse.Parity.H.08", VERSE_S6_FLAGS)
bool FVerseParityH08Test::RunTest(const FString&)
{
	TestEqual(TEXT("eye level key"), FVerseDeckHelp::BodyKey(true), FString(TEXT("verse.stage.help_eye")));
	TestEqual(TEXT("overview key"), FVerseDeckHelp::BodyKey(false), FString(TEXT("verse.stage.help")));
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		const FVerseUiStrings Strings = LoadStrings(Lang);
		const FString Eye = FVerseDeckHelp::Build(Strings, true).ToString();
		const FString Overview = FVerseDeckHelp::Build(Strings, false).ToString();
		const FString Duel = Strings.Get(TEXT("verse.stage.help_duel")).ToString();
		TestNotEqual(TEXT("eye level and overview differ"), Eye, Overview);
		TestTrue(TEXT("eye help starts with its body"), Eye.StartsWith(Strings.Get(TEXT("verse.stage.help_eye")).ToString()));
		TestTrue(TEXT("overview help starts with its body"), Overview.StartsWith(Strings.Get(TEXT("verse.stage.help")).ToString()));
		TestTrue(TEXT("both end with the duel line"), Eye.EndsWith(Duel) && Overview.EndsWith(Duel));
		TestFalse(TEXT("the duel line can be left out"), FVerseDeckHelp::Build(Strings, true, false).ToString().EndsWith(Duel));
	}
	TestTrue(TEXT("click to look at eye level"), FVerseDeckHelp::ShowClickToLook(true, false, false));
	TestFalse(TEXT("not in overview"), FVerseDeckHelp::ShowClickToLook(false, false, false));
	TestFalse(TEXT("not once the mouse is taken"), FVerseDeckHelp::ShowClickToLook(true, true, false));
	TestFalse(TEXT("not under a dialog"), FVerseDeckHelp::ShowClickToLook(true, false, true));

	FDeckWorld W;
	if (W.Hud)
	{
		W.Hud->SetView(EVerseDeckView::Third);
		W.Hud->ShowHelp();
		const FString Eye = W.Hud->GetNoticeText().ToString();
		W.Hud->SetView(EVerseDeckView::Overview);
		W.Hud->ShowHelp();
		TestNotEqual(TEXT("the on-screen help follows the view"), Eye, W.Hud->GetNoticeText().ToString());
		W.Hud->SetView(EVerseDeckView::Third);
		TestTrue(TEXT("hint shows at eye level"), W.Hud->ShowsClickToLook());
		W.Hud->SetMouseTaken(true);
		TestFalse(TEXT("and goes once the mouse is taken"), W.Hud->ShowsClickToLook());
	}
	return true;
}

// H-12: dialogs are modal, focus is trapped, Escape or the scrim closes, focus returns to the opener.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH12Test, "Verse.Parity.H.12", VERSE_S6_FLAGS)
bool FVerseParityH12Test::RunTest(const FString&)
{
	FVerseDialogStack Stack;
	Stack.SetBaseFocus(TEXT("rail_lift"));
	TestFalse(TEXT("nothing modal at first"), Stack.IsModal());
	TestFalse(TEXT("keys pass when no dialog is open"), Stack.HandleNavigate(EVerseDialogNav::Next));

	Stack.Open(TEXT("lift"), NAME_None, {TEXT("a"), TEXT("b"), TEXT("c")}, TEXT("b"));
	TestTrue(TEXT("modal"), Stack.IsModal());
	TestEqual(TEXT("initial focus inside"), Stack.GetFocused().ToString(), FString(TEXT("b")));
	TestTrue(TEXT("Tab is used by the dialog"), Stack.HandleNavigate(EVerseDialogNav::Next));
	TestEqual(TEXT("next"), Stack.GetFocused().ToString(), FString(TEXT("c")));
	Stack.HandleNavigate(EVerseDialogNav::Next);
	TestEqual(TEXT("wraps forward: focus never leaves"), Stack.GetFocused().ToString(), FString(TEXT("a")));
	Stack.HandleNavigate(EVerseDialogNav::Previous);
	TestEqual(TEXT("wraps backward"), Stack.GetFocused().ToString(), FString(TEXT("c")));
	TestTrue(TEXT("a widget behind the dialog is blocked"), Stack.IsBlocked(TEXT("rail_lift")));
	TestFalse(TEXT("one inside is not"), Stack.IsBlocked(TEXT("a")));

	// A dialog from a dialog returns to the widget focused there.
	Stack.Open(TEXT("confirm"), NAME_None, {TEXT("yes"), TEXT("no")});
	TestEqual(TEXT("the top dialog holds the focus"), Stack.GetFocused().ToString(), FString(TEXT("yes")));
	FName Returned;
	TestTrue(TEXT("Escape closes the top dialog only"), Stack.HandleEscape(&Returned));
	TestEqual(TEXT("focus returns into the dialog below"), Returned.ToString(), FString(TEXT("c")));
	TestTrue(TEXT("the lower dialog is still modal"), Stack.IsOpen(TEXT("lift")) && Stack.IsModal());

	// The scrim closes too, and the focus goes back to what opened the lift.
	TestTrue(TEXT("scrim click closes"), Stack.HandleScrimClick(&Returned));
	TestEqual(TEXT("focus returns to the opener"), Returned.ToString(), FString(TEXT("rail_lift")));
	TestEqual(TEXT("and sits there"), Stack.GetFocused().ToString(), FString(TEXT("rail_lift")));
	TestFalse(TEXT("no longer modal"), Stack.IsModal());
	TestFalse(TEXT("Escape with nothing open passes"), Stack.HandleEscape());

	// The Slate frame maps the same keys: Tab, arrows and the gamepad.
	EVerseDialogNav Nav;
	TestTrue(TEXT("Tab"), SVerseDialogFrame::NavigationOfKey(EKeys::Tab, false, Nav) && Nav == EVerseDialogNav::Next);
	TestTrue(TEXT("Shift+Tab"), SVerseDialogFrame::NavigationOfKey(EKeys::Tab, true, Nav) && Nav == EVerseDialogNav::Previous);
	TestTrue(TEXT("gamepad down"), SVerseDialogFrame::NavigationOfKey(EKeys::Gamepad_DPad_Down, false, Nav) && Nav == EVerseDialogNav::Down);
	TestTrue(TEXT("gamepad up"), SVerseDialogFrame::NavigationOfKey(EKeys::Gamepad_DPad_Up, false, Nav) && Nav == EVerseDialogNav::Up);
	TestTrue(TEXT("left stick right"), SVerseDialogFrame::NavigationOfKey(EKeys::Gamepad_LeftStick_Right, false, Nav) && Nav == EVerseDialogNav::Right);
	TestFalse(TEXT("a letter is not navigation"), SVerseDialogFrame::NavigationOfKey(EKeys::A, false, Nav));
	TestEqual(TEXT("ring wraps"), FVerseDialogStack::StepIndex(2, 3, EVerseDialogNav::Down), 0);
	TestEqual(TEXT("ring wraps back"), FVerseDialogStack::StepIndex(0, 3, EVerseDialogNav::Up), 2);

	// The frame itself traps: its buttons are the only focusables it offers.
	if (FSlateApplication::IsInitialized())
	{
		int32 Closed = 0;
		const TSharedRef<SVerseDialogFrame> Frame = SNew(SVerseDialogFrame)
			.bTakeFocus(false)
			.OnClose_Lambda([&Closed] { ++Closed; })
			[
				SNew(SVerticalBox)
				+ SVerticalBox::Slot()[SNew(SButton)]
				+ SVerticalBox::Slot()[SNew(SButton)]
			];
		TestEqual(TEXT("two focusables inside the frame"), Frame->CollectFocusables().Num(), 2);
	}
	return true;
}

// H-13: opening a dialog or a menu shows the cursor and stops mouse look.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH13Test, "Verse.Parity.H.13", VERSE_S6_FLAGS)
bool FVerseParityH13Test::RunTest(const FString&)
{
	FVerseDialogStack Stack;
	TestFalse(TEXT("cursor hidden while playing"), Stack.ShouldShowCursor());
	TestFalse(TEXT("look runs while playing"), Stack.BlocksLookInput());
	Stack.Open(TEXT("record"), NAME_None, {TEXT("tab")});
	TestTrue(TEXT("a dialog shows the cursor"), Stack.ShouldShowCursor());
	TestTrue(TEXT("and stops look"), Stack.BlocksLookInput());
	Stack.Close(TEXT("record"));
	TestFalse(TEXT("closing gives look back"), Stack.BlocksLookInput());

	FDeckWorld W;
	if (!TestNotNull(TEXT("subsystems"), W.Hud))
	{
		return false;
	}
	TestFalse(TEXT("look free at first"), W.Hud->ReleasesMouseLook());
	for (const EVerseUiScreen Screen : {EVerseUiScreen::EscMenu, EVerseUiScreen::Settings, EVerseUiScreen::Armoury, EVerseUiScreen::EndOfSet, EVerseUiScreen::SessionSummary})
	{
		W.Ui->ShowScreen(Screen);
		W.Hud->SyncDialogs();
		TestTrue(TEXT("every menu releases mouse look"), W.Hud->ReleasesMouseLook());
		TestTrue(TEXT("and shows the cursor"), W.Hud->ShowsCursor());
		TestTrue(TEXT("as a modal dialog"), W.Hud->GetDialogs().IsOpen(TEXT("menu")));
	}
	W.Ui->ShowScreen(EVerseUiScreen::None);
	W.Hud->SyncDialogs();
	TestFalse(TEXT("closing the menu gives look back"), W.Hud->ReleasesMouseLook());
	TestFalse(TEXT("and hides the cursor"), W.Hud->ShowsCursor());

	W.Hud->OpenLift(EVerseLiftSource::ToolRail);
	TestTrue(TEXT("the lift releases look too"), W.Hud->ReleasesMouseLook());
	W.Hud->CloseLift();
	TestFalse(TEXT("closing it gives look back"), W.Hud->ReleasesMouseLook());
	return true;
}

// R-01 (the part the deck HUD draws): 15 ranks in 4 tiers with a plate each.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR01Test, "Verse.Parity.R.01", VERSE_S6_FLAGS)
bool FVerseParityR01Test::RunTest(const FString&)
{
	const TArray<FVerseRankRow>& Ladder = FVerseServiceRecordModel::Ladder();
	TestEqual(TEXT("15 ranks"), Ladder.Num(), 15);
	TSet<FName> Tiers;
	int32 LastLevel = 0;
	for (const FVerseRankRow& Row : Ladder)
	{
		Tiers.Add(Row.Tier);
		TestTrue(TEXT("levels rise"), Row.Level > LastLevel);
		LastLevel = Row.Level;
		TestEqual(TEXT("plate pattern is two rows of three"), Row.Plate.Len(), 7);
	}
	TestEqual(TEXT("4 tiers"), Tiers.Num(), 4);
	TestEqual(TEXT("first rank at level 1"), Ladder[0].Level, 1);
	TestEqual(TEXT("last rank at the cap"), Ladder.Last().Level, FVerseServiceRecordModel::MaxLevel);
	// Equality with rules.py RANKS and the web plates is held by tests/unit/progression/test_duel_parity.py.
	return true;
}

// R-03: six hexagon tiles, a unique, symmetric pattern per rank.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityR03Test, "Verse.Parity.R.03", VERSE_S6_FLAGS)
bool FVerseParityR03Test::RunTest(const FString&)
{
	TSet<FString> Patterns;
	for (const FVerseRankRow& Row : FVerseServiceRecordModel::Ladder())
	{
		const FVerseRankPlate Plate = FVerseRankPlate::For(Row.Id);
		TestTrue(FString::Printf(TEXT("%s is symmetric"), *Row.Id.ToString()), Plate.IsSymmetric());
		TestEqual(TEXT("pattern round-trips"), Plate.Pattern(), Row.Plate);
		TestTrue(TEXT("at least one tile lit"), Plate.NumLit() > 0);
		TestEqual(TEXT("tier"), Plate.Tier, Row.Tier);
		Patterns.Add(Plate.Pattern());
	}
	TestEqual(TEXT("all 15 patterns are distinct"), Patterns.Num(), 15);
	TestEqual(TEXT("the fleet admiral wears the full plate"), FVerseRankPlate::For(TEXT("fleet_admiral")).NumLit(), 6);
	TestEqual(TEXT("an unknown rank is the recruit's plate"), FVerseRankPlate::For(TEXT("pirate")).Pattern(), FVerseRankPlate::For(TEXT("recruit")).Pattern());
	TestEqual(TEXT("the plate follows the level"), FVerseRankPlate::ForLevel(14).Pattern(), FString(TEXT("101|000")));
	TSet<uint32> Colours;
	for (const TCHAR* Tier : {TEXT("deck"), TEXT("line"), TEXT("command"), TEXT("flag")})
	{
		Colours.Add(FVerseRankPlate::TierColour(Tier).ToFColor(true).ToPackedARGB());
	}
	TestEqual(TEXT("one tile colour per tier"), Colours.Num(), 4);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

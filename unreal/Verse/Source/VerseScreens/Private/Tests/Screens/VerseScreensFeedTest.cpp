#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Cells/VerseCells.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "Misc/App.h"
#include "Policies/PrettyJsonPrintPolicy.h"
#include "Screens/VerseChatTailScreenComponent.h"
#include "Screens/VerseScreenSurface.h"
#include "Screens/VerseScreensSubsystem.h"
#include "Screens/VerseTerminalMonitorComponent.h"
#include "Serialization/JsonWriter.h"
#include "Stations/VerseStationSubsystem.h"
#include "Tests/Screens/Fakes/FakeVerseCommandLink.h"

#define VERSE_SCREENS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseScreensFeedTest
{
	/** A bare game world with the screens and station subsystems and a fake link. */
	struct FWorldRig
	{
		UWorld* World = nullptr;
		UVerseScreensSubsystem* Screens = nullptr;
		UVerseStationSubsystem* Stations = nullptr;
		TSharedPtr<FFakeVerseCommandLink> Link;

		FWorldRig()
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseScreensTestWorld"));
			Screens = World ? World->GetSubsystem<UVerseScreensSubsystem>() : nullptr;
			Stations = World ? World->GetSubsystem<UVerseStationSubsystem>() : nullptr;
			Link = MakeShared<FFakeVerseCommandLink>();
			if (Stations)
			{
				Stations->SetLink(Link);
			}
		}
		~FWorldRig()
		{
			if (World)
			{
				World->DestroyWorld(false);
			}
		}
		bool Ok() const { return World && Screens && Stations; }

		UVerseTerminalMonitorComponent* AddMonitor(const FString& PaneId, const FVector& At)
		{
			AActor* Desk = World->SpawnActor<AActor>();
			UVerseTerminalMonitorComponent* M = NewObject<UVerseTerminalMonitorComponent>(Desk);
			Desk->SetRootComponent(M);
			M->RegisterComponent();
			M->SetWorldLocation(At);
			if (!PaneId.IsEmpty())
			{
				M->PaneIds.Add(PaneId);
			}
			Screens->RegisterMonitor(M);
			return M;
		}

		/** Answers the last screens.watch with every requested pane bound to ref 1..n. */
		void BindAll()
		{
			const FFakeVerseCommandLink::FSent* Watch = Link->Last(TEXT("screens.watch"));
			if (!Watch)
			{
				return;
			}
			TArray<TSharedPtr<FJsonValue>> Bound;
			int32 Ref = 1;
			for (const TSharedPtr<FJsonValue>& P : Watch->Data->GetArrayField(TEXT("panes")))
			{
				TSharedRef<FJsonObject> B = MakeShared<FJsonObject>();
				B->SetStringField(TEXT("pane_id"), P->AsObject()->GetStringField(TEXT("pane_id")));
				B->SetNumberField(TEXT("ref"), Ref++);
				Bound.Add(MakeShared<FJsonValueObject>(B));
			}
			TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
			Result->SetArrayField(TEXT("bound"), Bound);
			Result->SetArrayField(TEXT("dropped"), TArray<TSharedPtr<FJsonValue>>());
			Result->SetArrayField(TEXT("missing"), TArray<TSharedPtr<FJsonValue>>());
			Link->Answer(Watch->Id, *FFakeVerseCommandLink::Ok(Result));
		}
	};

	FVerseCellRun MakeRun(uint16 Col, const FString& Text, uint32 Fg = 0, uint16 Attrs = 0)
	{
		FVerseCellRun R;
		R.Col = Col;
		R.Text = Text;
		R.Fg = Fg;
		R.Attrs = Attrs;
		VerseCells::BuildClusters(R);
		R.Cells = uint16(R.ClusterEnds.Num());
		return R;
	}

	TArray<uint8> Encode(const FVerseCellFrame& F)
	{
		TArray<uint8> Out;
		FString Error;
		VerseCells::EncodeBinary(F, Out, Error);
		return Out;
	}

	/** One busy agent row: four styled runs across all 240 columns. */
	FVerseCellRow BusyRow(int32 Row, int32 Tick)
	{
		FVerseCellRow R;
		R.Row = uint16(Row);
		const FString Base = FString::Printf(TEXT("[%06d] building module %02d: compiling sources and linking objects "), Tick, Row);
		FString Text;
		while (Text.Len() < 240)
		{
			Text += Base;
		}
		R.Runs.Add(MakeRun(0, Text.Mid(0, 60), (VerseCells::ModePalette << 24) | 2, VerseCells::Bold));
		R.Runs.Add(MakeRun(60, Text.Mid(60, 60), 0));
		R.Runs.Add(MakeRun(120, Text.Mid(120, 60), (VerseCells::ModeRgb << 24) | 0xd2943e));
		R.Runs.Add(MakeRun(180, Text.Mid(180, 60), (VerseCells::ModePalette << 24) | 8, VerseCells::Dim));
		return R;
	}

	void WriteProof(const FString& SubTask, const FString& File, const TSharedRef<FJsonObject>& Json)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TPrettyJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Json, Writer);
		const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP16"), SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		FFileHelper::SaveStringToFile(Out, *FPaths::Combine(Dir, File));
	}
}

using namespace VerseScreensFeedTest;

// WP16.3: nearest first, at most 8, far desks at 2 Hz, out of view distance not watched.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensWatchPlan, "Verse.Screens.Watch.Plan", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensWatchPlan::RunTest(const FString&)
{
	TArray<FVerseWatchCandidate> C;
	for (int32 I = 0; I < 12; ++I)
	{
		C.Add({FString::Printf(TEXT("ws_91:T%d"), I + 1), FVector(200.0 + 200.0 * I, 0.0, 0.0)});
	}
	C.Add({TEXT("ws_91:T1"), FVector(5000.0, 0.0, 0.0)}); // a second desk of T1, farther
	C.Add({TEXT("ws_91:T99"), FVector(9000.0, 0.0, 0.0)}); // beyond view distance
	C.Add({TEXT("ws_91:T50"), FVector(-300.0, 0.0, 0.0)}); // near but behind the view
	const FVerseWatchSettings S;
	const TArray<FVerseWatchEntry> Plan = UVerseScreensSubsystem::PlanWatch(C, FVector::ZeroVector, FVector::ForwardVector, S);
	TestEqual(TEXT("at most 8 panes"), Plan.Num(), 8);
	TestEqual(TEXT("nearest first"), Plan[0].PaneId, FString(TEXT("ws_91:T1")));
	TestEqual(TEXT("the near desk in front at 10 Hz"), Plan[0].Hz, 10);
	const FVerseWatchEntry* Behind = Plan.FindByPredicate([](const FVerseWatchEntry& E) { return E.PaneId == TEXT("ws_91:T50"); });
	TestTrue(TEXT("a near desk behind the view is watched at 2 Hz"), Behind && Behind->Hz == 2);
	TestTrue(TEXT("a far desk (10 m) at 2 Hz"), Plan.Last().Hz == 2);
	TestFalse(TEXT("beyond view distance is not watched"), Plan.ContainsByPredicate([](const FVerseWatchEntry& E) { return E.PaneId == TEXT("ws_91:T99"); }));
	int32 T1 = 0;
	for (const FVerseWatchEntry& E : Plan)
	{
		T1 += E.PaneId == TEXT("ws_91:T1") ? 1 : 0;
	}
	TestEqual(TEXT("each pane once"), T1, 1);
	FVerseWatchSettings Few = S;
	Few.MaxPanes = 3;
	Few.MaxHz = 5;
	const TArray<FVerseWatchEntry> Small = UVerseScreensSubsystem::PlanWatch(C, FVector::ZeroVector, FVector::ForwardVector, Few);
	TestEqual(TEXT("welcome limits cap the count"), Small.Num(), 3);
	TestEqual(TEXT("welcome limits cap the rate"), Small[0].Hz, 5);
	return true;
}

// WP16.1/16.3: the watch goes out, refs bind, binary frames route by ref, a gap asks for a resync.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensFeedRouting, "Verse.Screens.Feed.Routing", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensFeedRouting::RunTest(const FString&)
{
	FWorldRig Rig;
	if (!TestTrue(TEXT("world with subsystems"), Rig.Ok()))
	{
		return false;
	}
	UVerseTerminalMonitorComponent* Near = Rig.AddMonitor(TEXT("ws_91:T1"), FVector(300, 0, 0));
	UVerseTerminalMonitorComponent* Far = Rig.AddMonitor(TEXT("ws_91:T2"), FVector(1500, 0, 0));
	UVerseTerminalMonitorComponent* Empty = Rig.AddMonitor(FString(), FVector(200, 0, 0));
	Rig.Screens->SetViewOverride(FVector::ZeroVector, FVector::ForwardVector);
	Rig.Screens->UpdateWatch();
	const FFakeVerseCommandLink::FSent* Watch = Rig.Link->Last(TEXT("screens.watch"));
	if (!TestNotNull(TEXT("screens.watch sent"), Watch))
	{
		return false;
	}
	// Same shape as the contract's golden request (messages/screens.watch.json).
	const TSharedPtr<FJsonValue> Golden = VerseBridgeGolden::Load(TEXT("messages/screens.watch.json"));
	TestTrue(TEXT("watch data equals the golden screens.watch"),
		FJsonValue::CompareEqual(FJsonValueObject(Watch->Data), FJsonValueObject(Golden->AsArray()[0]->AsObject()->GetObjectField(TEXT("data")))));
	Rig.Screens->UpdateWatch();
	TestEqual(TEXT("an unchanged plan is not sent again"), Rig.Link->Count(TEXT("screens.watch")), 1);

	// Answer with the golden reply (refs 1 and 2).
	const TSharedPtr<FJsonValue> Reply = VerseBridgeGolden::Load(TEXT("replies/screens.watch.json"));
	const FJsonObject& ReplyData = *Reply->AsArray()[0]->AsObject()->GetObjectField(TEXT("reply"))->GetObjectField(TEXT("data"));
	Rig.Link->Answer(Watch->Id, ReplyData);
	TestEqual(TEXT("ref 1 is T1"), Rig.Screens->PaneForRef(1), FString(TEXT("ws_91:T1")));
	TestEqual(TEXT("near monitor at 10 Hz"), Near->WatchHz, 10);
	TestEqual(TEXT("far monitor at 2 Hz"), Far->WatchHz, 2);
	TestEqual(TEXT("a desk without a pane shows standby"), Empty->Page(), EVerseMonitorPage::Standby);

	// The golden binary snapshot of ref 1, then the golden delta (base 88 != 82: a gap).
	const TArray<TSharedPtr<FJsonValue>> Vectors = VerseBridgeGolden::Load(TEXT("cells/vectors.json"))->AsObject()->GetArrayField(TEXT("valid"));
	auto VectorBytes = [&Vectors](const TCHAR* Name)
	{
		for (const TSharedPtr<FJsonValue>& V : Vectors)
		{
			if (V->AsObject()->GetStringField(TEXT("name")) == Name)
			{
				return VerseBridgeGolden::Hex(V->AsObject()->GetStringField(TEXT("bin_hex")));
			}
		}
		return TArray<uint8>();
	};
	Rig.Screens->HandleBridgeBinary(VectorBytes(TEXT("snapshot_basic")));
	TestEqual(TEXT("snapshot shown live"), Near->Page(), EVerseMonitorPage::Live);
	TestEqual(TEXT("row 0 holds the prompt"), Near->Grid().RowText(0), FString(TEXT("$ pytest -q")));
	Rig.Screens->HandleBridgeBinary(VectorBytes(TEXT("contract_delta")));
	const FFakeVerseCommandLink::FSent* Resync = Rig.Link->Last(TEXT("resync"));
	TestTrue(TEXT("a gap sends resync {topic: screens, pane_id}"), Resync && Resync->Data->GetStringField(TEXT("topic")) == TEXT("screens")
		&& Resync->Data->GetStringField(TEXT("pane_id")) == TEXT("ws_91:T1"));
	Rig.Screens->HandleBridgeBinary(VectorBytes(TEXT("contract_delta")));
	TestEqual(TEXT("one resync in flight per pane, not a loop"), Rig.Link->Count(TEXT("resync")), 1);

	// A matching delta applies; an unknown ref and a malformed frame are counted, not applied.
	FVerseCellFrame Delta;
	Delta.Kind = EVerseCellsKind::Delta;
	Delta.Ref = 1;
	Delta.Seq = 90;
	Delta.Base = 82;
	Delta.Cols = 132;
	Delta.Rows = 40;
	Delta.CursorRow = 2;
	Delta.CursorCol = 0;
	FVerseCellRow& Row = Delta.RowsChanged.AddDefaulted_GetRef();
	Row.Row = 2;
	Row.Runs.Add(MakeRun(0, TEXT("3 passed")));
	Rig.Screens->HandleBridgeBinary(Encode(Delta));
	TestEqual(TEXT("in-order delta applied"), Near->Grid().RowText(2), FString(TEXT("3 passed")));
	Delta.Ref = 7;
	Rig.Screens->HandleBridgeBinary(Encode(Delta));
	TestEqual(TEXT("unknown ref counted"), Rig.Screens->Stats().UnknownRefs, 1);
	Rig.Screens->HandleBridgeBinary(VerseBridgeGolden::Hex(TEXT("5658")));
	TestEqual(TEXT("malformed frame rejected"), Rig.Screens->Stats().Rejected, 1);

	// JSON frames (cells.json/1) for T2 and screens.gone.
	// Keep the loaded document alive: a range-for over a temporary's member array dangles.
	const TSharedPtr<FJsonValue> Frames = VerseBridgeGolden::Load(TEXT("messages/screens.frame.json"));
	if (!TestTrue(TEXT("screens.frame golden loads"), Frames.IsValid()))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Env : Frames->AsArray())
	{
		Rig.Screens->HandleBridgeFrame(*Env->AsObject());
	}
	TestEqual(TEXT("JSON snapshot of T2 shown"), Far->Page(), EVerseMonitorPage::Live);
	Rig.Screens->HandleBridgeFrame(*VerseBridgeGolden::Load(TEXT("messages/screens.gone.json"))->AsArray()[0]->AsObject());
	TestEqual(TEXT("screens.gone shows vacant"), Far->Page(), EVerseMonitorPage::Vacant);

	// Redraw budget: dirty monitors repaint, a far one at most at its 2 Hz rate.
	Rig.Screens->RedrawDirty(100.0);
	TestFalse(TEXT("near monitor clean after a repaint"), Near->NeedsRedraw(100.01));
	Rig.Screens->HandleLinkReset();
	TestEqual(TEXT("reset voids refs"), Rig.Screens->PaneForRef(1), FString());
	Rig.Screens->UpdateWatch();
	TestEqual(TEXT("reset re-sends the watch"), Rig.Link->Count(TEXT("screens.watch")), 2);

	// A pane the server dropped (over its limit) shows standby, not its last picture as if live.
	const FFakeVerseCommandLink::FSent* Rewatch = Rig.Link->Last(TEXT("screens.watch"));
	if (TestNotNull(TEXT("second watch"), Rewatch))
	{
		TSharedRef<FJsonObject> BoundFar = MakeShared<FJsonObject>();
		BoundFar->SetStringField(TEXT("pane_id"), TEXT("ws_91:T2"));
		BoundFar->SetNumberField(TEXT("ref"), 3);
		TSharedPtr<FJsonObject> Partial = MakeShared<FJsonObject>();
		Partial->SetArrayField(TEXT("bound"), {MakeShared<FJsonValueObject>(BoundFar)});
		Partial->SetArrayField(TEXT("dropped"), {MakeShared<FJsonValueString>(TEXT("ws_91:T1"))});
		Partial->SetArrayField(TEXT("missing"), TArray<TSharedPtr<FJsonValue>>());
		TestEqual(TEXT("before: the near monitor shows its last picture"), Near->Page(), EVerseMonitorPage::Live);
		Rig.Link->Answer(Rewatch->Id, *FFakeVerseCommandLink::Ok(Partial));
		TestEqual(TEXT("dropped pane: monitor on standby"), Near->Page(), EVerseMonitorPage::Standby);
		TestEqual(TEXT("dropped pane: not watched"), Near->WatchHz, 0);
		TestEqual(TEXT("bound pane keeps its rate"), Far->WatchHz, 2);
	}
	return true;
}

// WP16.4: chat tails watched (nearest owners, at most 6), applied by agent, empty owner says so.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensChatTails, "Verse.Screens.ChatTail.Feed", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensChatTails::RunTest(const FString&)
{
	FWorldRig Rig;
	if (!TestTrue(TEXT("world with subsystems"), Rig.Ok()))
	{
		return false;
	}
	TArray<UVerseChatTailScreenComponent*> Consoles;
	const TCHAR* Agents[] = {TEXT("ag_7f1"), TEXT("ag_02c"), TEXT("ag_3"), TEXT("ag_4"), TEXT("ag_5"), TEXT("ag_6"), TEXT("ag_7"), TEXT("")};
	for (int32 I = 0; I < 8; ++I)
	{
		AActor* Desk = Rig.World->SpawnActor<AActor>();
		UVerseChatTailScreenComponent* C = NewObject<UVerseChatTailScreenComponent>(Desk);
		Desk->SetRootComponent(C);
		C->RegisterComponent();
		C->SetWorldLocation(FVector(100.0 * (I + 1), 0, 0));
		C->AgentId = Agents[I];
		Rig.Screens->RegisterChatScreen(C);
		Consoles.Add(C);
	}
	Rig.Screens->SetViewOverride(FVector::ZeroVector, FVector::ForwardVector);
	Rig.Screens->UpdateWatch();
	const FFakeVerseCommandLink::FSent* Watch = Rig.Link->Last(TEXT("chat_tails.watch"));
	if (!TestNotNull(TEXT("chat_tails.watch sent"), Watch))
	{
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>& Watched = Watch->Data->GetArrayField(TEXT("agents"));
	TestEqual(TEXT("at most 6 agents"), Watched.Num(), 6);
	TestEqual(TEXT("nearest owner first"), Watched[0]->AsString(), FString(TEXT("ag_7f1")));
	const TSharedPtr<FJsonValue> Tails = VerseBridgeGolden::Load(TEXT("messages/chat_tails.update.json"));
	if (!TestTrue(TEXT("chat_tails.update golden loads"), Tails.IsValid()))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Env : Tails->AsArray())
	{
		Rig.Screens->HandleBridgeFrame(*Env->AsObject());
	}
	TestEqual(TEXT("ag_7f1 has its 3 lines"), Consoles[0]->Lines().Num(), 3);
	TestEqual(TEXT("ag_02c took the later update"), Consoles[1]->Version(), FString(TEXT("evt_01K2")));
	TestNotEqual(TEXT("error lines stand out from agent lines"), Consoles[1]->KindColour(TEXT("error")), Consoles[1]->KindColour(TEXT("agent")));
	FVerseTerminalDrawList List;
	TestEqual(TEXT("console draws its lines"), Consoles[0]->Redraw(List), 3);
	if (TestTrue(TEXT("console has text"), List.Texts.Num() > 0))
	{
		TestEqual(TEXT("newest line at the bottom"), FString(List.Texts.Last().Text), FString(TEXT("The retry waits 30 s; I changed it to back off.")));
	}
	Consoles[7]->Redraw(List);
	if (TestTrue(TEXT("vacant console has text"), List.Texts.Num() > 0))
	{
		TestEqual(TEXT("a console without an owner shows the vacant page"), FString(List.Texts[0].Text), FString(TEXT("VACANT")));
	}
	Rig.Link->Strings.Add(TEXT("verse.screen.vacant"), TEXT("FREI"));
	Consoles[7]->Redraw(List);
	if (TestTrue(TEXT("localized vacant console has text"), List.Texts.Num() > 0))
	{
		TestEqual(TEXT("the vacant text is localized"), FString(List.Texts[0].Text), FString(TEXT("FREI")));
	}
	FJsonObject Same;
	Same.SetStringField(TEXT("agent_id"), TEXT("ag_02c"));
	Same.SetStringField(TEXT("version"), TEXT("evt_01K2"));
	TestFalse(TEXT("an unchanged version is not applied again"), Consoles[1]->ApplyUpdate(Same));
	return true;
}

// WP16.5 / A16.4 (fake host): use key -> ide.focus_terminal -> the app takes the foreground.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensTakeover, "Verse.Screens.Takeover.FocusTerminal", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensTakeover::RunTest(const FString&)
{
	FWorldRig Rig;
	if (!TestTrue(TEXT("world with subsystems"), Rig.Ok()))
	{
		return false;
	}
	UVerseTerminalMonitorComponent* Desk = Rig.AddMonitor(TEXT("ws_91:T1"), FVector(100, 0, 0));
	UVerseTerminalMonitorComponent* Pair = Rig.AddMonitor(TEXT("ws_91:T2"), FVector(-100, 0, 0));
	Pair->PaneIds.Add(TEXT("ws_91:T3"));
	UVerseTerminalMonitorComponent* Master = Rig.AddMonitor(TEXT("ws_91:T4"), FVector(0, 100, 0));
	Master->bMasterStation = true;
	const int32 DeskHandle = Rig.Screens->AddTakeoverTarget(Desk);
	const int32 PairHandle = Rig.Screens->AddTakeoverTarget(Pair);
	const int32 MasterHandle = Rig.Screens->AddTakeoverTarget(Master);
	Desk->SetPaneTitle(TEXT("Fix the login retry"));

	// Parity S-15/S-16: only a desk with exactly one pane offers takeover, labelled by the pane title.
	Rig.Stations->SetViewerOverride(FVector(150, 0, 0), FVector(-1, 0, 0));
	Rig.Stations->RefreshPrompt();
	TestEqual(TEXT("prompt targets the single-pane desk"), Rig.Stations->Prompt().Handle, DeskHandle);
	TestEqual(TEXT("prompt label is the pane title"), Rig.Stations->Prompt().Label, FString(TEXT("Fix the login retry")));
	TestEqual(TEXT("prompt action"), Rig.Stations->Prompt().Action, FString(TEXT("Take over the terminal")));
	TestFalse(TEXT("a desk with two panes offers no takeover"), Rig.Stations->UseTarget(PairHandle, 1));
	TestFalse(TEXT("the master station offers no takeover"), Rig.Stations->UseTarget(MasterHandle, 1));

	const double Pressed = FPlatformTime::Seconds();
	TestTrue(TEXT("use key works the desk"), Rig.Stations->UseFocused(1));
	const FFakeVerseCommandLink::FSent* Focus = Rig.Link->Last(TEXT("ide.focus_terminal"));
	if (!TestNotNull(TEXT("ide.focus_terminal sent"), Focus))
	{
		return false;
	}
	const TSharedPtr<FJsonValue> Golden = VerseBridgeGolden::Load(TEXT("messages/ide.focus_terminal.json"));
	TestTrue(TEXT("command equals the golden ide.focus_terminal"),
		FJsonValue::CompareEqual(FJsonValueObject(Focus->Data), FJsonValueObject(Golden->AsArray()[0]->AsObject()->GetObjectField(TEXT("data")))));
	TestFalse(TEXT("a second press while in flight sends nothing"), Rig.Screens->RequestTakeover(Desk));
	TestEqual(TEXT("app not raised before the reply"), Rig.Link->Returns.Num(), 0);
	const TSharedPtr<FJsonValue> Replies = VerseBridgeGolden::Load(TEXT("replies/ide.focus_terminal.json"));
	Rig.Link->Answer(Focus->Id, *Replies->AsArray()[0]->AsObject()->GetObjectField(TEXT("reply"))->GetObjectField(TEXT("data")));
	const double Raised = FPlatformTime::Seconds();
	TestTrue(TEXT("ok reply hands the foreground to the app (focus.return_to_app station)"), Rig.Link->Returns.Num() == 1 && Rig.Link->Returns[0] == TEXT("station"));
	const double KeyToApp = (Raised - Pressed) * 1000.0;
	TestTrue(TEXT("key press to app hand-off within 500 ms (fake host)"), KeyToApp <= 500.0 && Rig.Screens->LastTakeoverMs() >= 0.0);

	// A16.5: a rate_limited reply is shown once and not retried.
	FString Notice;
	Rig.Stations->OnNotice.AddLambda([&Notice](const FString& Text) { Notice = Text; });
	Rig.Screens->RequestTakeover(Desk);
	Rig.Link->AnswerLast(*Replies->AsArray()[1]->AsObject()->GetObjectField(TEXT("reply"))->GetObjectField(TEXT("data")));
	TestEqual(TEXT("rate_limited shown"), Notice, FString(TEXT("Too many requests. Wait a moment, then try again.")));
	TestEqual(TEXT("rate_limited not retried"), Rig.Link->Count(TEXT("ide.focus_terminal")), 2);
	TestEqual(TEXT("app not raised on an error"), Rig.Link->Returns.Num(), 1);

	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	Proof->SetStringField(TEXT("test"), TEXT("Verse.Screens.Takeover.FocusTerminal"));
	Proof->SetStringField(TEXT("host"), TEXT("fake link (WP17 host not landed)"));
	Proof->SetNumberField(TEXT("key_to_app_handoff_ms"), KeyToApp);
	Proof->SetNumberField(TEXT("budget_ms"), 500);
	WriteProof(TEXT("16.5"), TEXT("takeover.json"), Proof);
	return true;
}

namespace VerseScreensFeedTest
{
	struct FLoadResult
	{
		double MsPerFrame = 0.0;
		double KBps = 0.0;
		FVerseScreensStats Stats;
		int32 Painted = 0;
	};

	/**
	 * A16.2 body: 8 panes at 240 x 60, a delta per pane at 10 Hz for 3 s at 60 fps, DirtyRows
	 * changed rows per delta. Rendered, every monitor has a render target and RedrawDirty runs the
	 * whole paint path (draw list, canvas text and tiles, render target update) on the game thread.
	 */
	bool RunEightPanes(FAutomationTestBase& Test, bool bRendered, int32 DirtyRows, FLoadResult& Out)
	{
		FWorldRig Rig;
		if (!Test.TestTrue(TEXT("world with subsystems"), Rig.Ok()))
		{
			return false;
		}
		TArray<UVerseTerminalMonitorComponent*> Desks;
		for (int32 I = 0; I < 8; ++I)
		{
			// Two near desks, six far ones: the busy_panes scenario of G0.11.
			UVerseTerminalMonitorComponent* M = Rig.AddMonitor(FString::Printf(TEXT("ws_91:T%d"), I + 1),
				FVector(I < 2 ? 300.0 + 100.0 * I : 1200.0 + 150.0 * I, 0, 0));
			if (bRendered)
			{
				// BeginPlay makes the monitor's render target.
				M->GetOwner()->DispatchBeginPlay();
				if (!Test.TestTrue(TEXT("monitor has a render target"), M->Surface() && M->Surface()->CanPaint()))
				{
					return false;
				}
			}
			Desks.Add(M);
		}
		Rig.Screens->SetViewOverride(FVector::ZeroVector, FVector::ForwardVector);
		Rig.Screens->UpdateWatch();
		Rig.BindAll();
		TArray<uint32> Seq;
		Seq.Init(0, 8);
		uint32 Counter = 1000;
		for (int32 P = 0; P < 8; ++P)
		{
			FVerseCellFrame Snap;
			Snap.Kind = EVerseCellsKind::Snapshot;
			Snap.Ref = uint16(P + 1);
			Snap.Seq = ++Counter;
			Snap.Cols = 240;
			Snap.Rows = 60;
			Snap.CursorRow = 59;
			Snap.CursorCol = 0;
			for (int32 R = 0; R < 60; ++R)
			{
				Snap.RowsChanged.Add(BusyRow(R, 0));
			}
			Rig.Screens->HandleBridgeBinary(Encode(Snap));
			Seq[P] = Snap.Seq;
		}
		// Pre-encode the deltas so only the receiving side is measured.
		constexpr int32 Seconds = 3;
		constexpr int32 Fps = 60;
		TArray<TArray<uint8>> Deltas;
		TArray<int32> DueFrame;
		for (int32 Tick = 0; Tick < Seconds * 10; ++Tick)
		{
			for (int32 P = 0; P < 8; ++P)
			{
				FVerseCellFrame D;
				D.Kind = EVerseCellsKind::Delta;
				D.Ref = uint16(P + 1);
				D.Base = Seq[P];
				D.Seq = ++Counter;
				Seq[P] = D.Seq;
				D.Cols = 240;
				D.Rows = 60;
				D.CursorRow = 59;
				D.CursorCol = int16(Tick % 200);
				for (int32 R = 0; R < DirtyRows; ++R)
				{
					D.RowsChanged.Add(BusyRow(60 - DirtyRows + R, Tick + 1));
				}
				Deltas.Add(Encode(D));
				DueFrame.Add(Tick * Fps / 10 + P % 6);
			}
		}
		Rig.Screens->RedrawDirty(0.0);
		Rig.Screens->ResetStats();
		TArray<int32> PaintsBefore;
		for (UVerseTerminalMonitorComponent* M : Desks)
		{
			PaintsBefore.Add(M->Surface() ? M->Surface()->PaintCount() : 0);
		}
		int32 Next = 0;
		for (int32 Frame = 0; Frame < Seconds * Fps; ++Frame)
		{
			while (Next < Deltas.Num() && DueFrame[Next] <= Frame)
			{
				Rig.Screens->HandleBridgeBinary(Deltas[Next++]);
			}
			Rig.Screens->RedrawDirty(double(Frame) / Fps);
		}
		Out.Stats = Rig.Screens->Stats();
		Out.MsPerFrame = Out.Stats.WorkSeconds * 1000.0 / double(Seconds * Fps);
		Out.KBps = double(Out.Stats.BytesIn) / 1024.0 / double(Seconds);
		for (int32 I = 0; I < Desks.Num(); ++I)
		{
			Out.Painted += (Desks[I]->Surface() ? Desks[I]->Surface()->PaintCount() : 0) - PaintsBefore[I];
		}
		Test.TestEqual(TEXT("every delta applied in order"), Out.Stats.FramesApplied, Deltas.Num());
		Test.TestEqual(TEXT("no resync"), Out.Stats.Resyncs, 0);
		Test.TestTrue(TEXT("far monitors repaint at most at 2 Hz"), Desks[7]->WatchHz == 2);
		if (bRendered)
		{
			Test.TestEqual(TEXT("every redraw painted its render target"), Out.Painted, Out.Stats.Redraws);
		}
		return true;
	}

	TSharedRef<FJsonObject> LoadProof(const TCHAR* TestName, bool bRendered, int32 DirtyRows, const FLoadResult& R)
	{
		TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
		Proof->SetStringField(TEXT("test"), TestName);
		Proof->SetStringField(TEXT("rhi"), bRendered ? FString(TEXT("rendered: draw list, canvas submit and render target update"))
													  : FString(TEXT("nullrhi: decode, apply and draw-list build only (no paint)")));
		Proof->SetNumberField(TEXT("panes"), 8);
		Proof->SetNumberField(TEXT("cols"), 240);
		Proof->SetNumberField(TEXT("rows"), 60);
		Proof->SetNumberField(TEXT("hz"), 10);
		Proof->SetNumberField(TEXT("dirty_rows_per_delta"), DirtyRows);
		Proof->SetNumberField(TEXT("game_thread_ms_per_frame"), R.MsPerFrame);
		Proof->SetNumberField(TEXT("budget_ms"), 0.3);
		Proof->SetNumberField(TEXT("kb_per_s"), R.KBps);
		Proof->SetNumberField(TEXT("budget_kb_per_s"), 200);
		Proof->SetNumberField(TEXT("frames"), R.Stats.FramesIn);
		Proof->SetNumberField(TEXT("redraws"), R.Stats.Redraws);
		Proof->SetNumberField(TEXT("rows_drawn"), R.Stats.RowsDrawn);
		Proof->SetNumberField(TEXT("render_target_paints"), R.Painted);
		return Proof;
	}
}

// Decode, apply and draw-list path of A16.2 without a GPU (CI lane). Not the A16.2 evidence: that is
// Verse.Visual.Screens.Load, which includes painting.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensLoad, "Verse.Screens.Load.EightPanes", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensLoad::RunTest(const FString&)
{
	FLoadResult R;
	if (!RunEightPanes(*this, false, 6, R))
	{
		return false;
	}
	AddInfo(FString::Printf(TEXT("headless, 6 dirty rows: %.4f ms/frame (no paint), %.1f KB/s, %d redraws"), R.MsPerFrame, R.KBps, R.Stats.Redraws));
	TestTrue(TEXT("decode and draw lists well inside the frame budget"), R.MsPerFrame <= 0.3);
	TestTrue(TEXT("at most 200 KB/s"), R.KBps <= 200.0);
	WriteProof(TEXT("16.2"), TEXT("load_headless.json"), LoadProof(TEXT("Verse.Screens.Load.EightPanes"), false, 6, R));
	return true;
}

// A16.2 (rendered): 8 panes at 60 x 240 at 10 Hz, painted into their render targets on the GPU:
// game thread at most 0.3 ms per frame and at most 200 KB/s. Also measured and reported beside it:
// every row of every pane changing on every delta (a full scroll).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualScreensLoad, "Verse.Visual.Screens.Load", VERSE_SCREENS_TEST_FLAGS)
bool FVerseVisualScreensLoad::RunTest(const FString&)
{
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no renderer (-nullrhi): the rendered load check runs in the visual lane"));
		return true;
	}
	FLoadResult Busy;
	FLoadResult Scroll;
	if (!RunEightPanes(*this, true, 6, Busy) || !RunEightPanes(*this, true, 60, Scroll))
	{
		return false;
	}
	AddInfo(FString::Printf(TEXT("rendered, 6 dirty rows: %.4f ms/frame, %.1f KB/s, %d paints"), Busy.MsPerFrame, Busy.KBps, Busy.Painted));
	AddInfo(FString::Printf(TEXT("rendered, full scroll (60 rows): %.4f ms/frame, %.1f KB/s, %d paints"), Scroll.MsPerFrame, Scroll.KBps, Scroll.Painted));
	TestTrue(TEXT("busy panes: game thread at most 0.3 ms per frame, painting included"), Busy.MsPerFrame <= 0.3);
	TestTrue(TEXT("busy panes: at most 200 KB/s"), Busy.KBps <= 200.0);
	TSharedRef<FJsonObject> Proof = LoadProof(TEXT("Verse.Visual.Screens.Load"), true, 6, Busy);
	Proof->SetObjectField(TEXT("full_scroll"), LoadProof(TEXT("Verse.Visual.Screens.Load"), true, 60, Scroll));
	WriteProof(TEXT("16.2"), TEXT("load.json"), Proof);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

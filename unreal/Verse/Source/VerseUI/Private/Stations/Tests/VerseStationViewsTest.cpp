#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Stations/Tests/Fakes/FakeVerseStationLink.h"
#include "Stations/VerseStationController.h"
#include "Stations/VerseStationSubsystem.h"
#include "Stations/VerseStationUISubsystem.h"

#define VERSE_STATION_VIEWS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseStationViewsTest
{
	/** The data of golden example Index of messages/<Type>.json. */
	TSharedPtr<FJsonObject> GoldenData(const FString& Type, int32 Index = 0)
	{
		const TSharedPtr<FJsonValue> Root = VerseStationGolden::Load(FString::Printf(TEXT("messages/%s.json"), *Type));
		if (!Root.IsValid() || !Root->AsArray().IsValidIndex(Index))
		{
			return nullptr;
		}
		return Root->AsArray()[Index]->AsObject()->GetObjectField(TEXT("data"));
	}

	/** The reply data of golden pair Index of replies/<Type>.json. */
	TSharedPtr<FJsonObject> GoldenReply(const FString& Type, int32 Index)
	{
		const TSharedPtr<FJsonValue> Root = VerseStationGolden::Load(FString::Printf(TEXT("replies/%s.json"), *Type));
		if (!Root.IsValid() || !Root->AsArray().IsValidIndex(Index))
		{
			return nullptr;
		}
		return Root->AsArray()[Index]->AsObject()->GetObjectField(TEXT("reply"))->GetObjectField(TEXT("data"));
	}

	bool SameJson(const TSharedRef<FJsonObject>& A, const TSharedPtr<FJsonObject>& B)
	{
		return B.IsValid() && FJsonValue::CompareEqual(FJsonValueObject(A), FJsonValueObject(B));
	}

	/** A controller wired to a fake link, recording notices and service record tabs. */
	struct FRig
	{
		TSharedRef<FFakeVerseStationLink> Link = MakeShared<FFakeVerseStationLink>();
		FVerseStationController Ctl;
		TArray<FString> Notices;
		TArray<FName> RecordTabs;

		FRig()
		{
			TSharedRef<FFakeVerseStationLink> L = Link;
			Ctl.GetLink = [L]() -> IVerseCommandLink* { return &L.Get(); };
			Ctl.Notice = [this](const FString& T) { Notices.Add(T); };
			Ctl.Localize = [L](const FString& K, const FString& F) { return L->Localize(K, F); };
			Ctl.ErrorText = [](const FString& Code) { return FString::Printf(TEXT("error:%s"), *Code); };
			Ctl.OpenServiceRecord = [this](FName Tab) { RecordTabs.Add(Tab); };
		}
	};
}

using namespace VerseStationViewsTest;

// A16.5: every station command the views send equals its golden message.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUIStationGoldenCommands, "Verse.UI.Stations.GoldenCommands", VERSE_STATION_VIEWS_TEST_FLAGS)
bool FVerseUIStationGoldenCommands::RunTest(const FString&)
{
	using namespace VerseStationCommands;
	struct FCase
	{
		FCommand Command;
		int32 Golden;
	};
	const FCase Cases[] = {
		{AgentsOpenList(), 0},
		{GroupOpen(TEXT("grp_a")), 0},
		{SimulatorOpen(TEXT("asteroid-run")), 0},
		{IdeOpen(), 0},
		{LauncherOptions(), 0},
		{LauncherStart(TEXT("ws_91"), TEXT("claude"), 2, TEXT("Write the bridge relay tests.")), 0},
		{LauncherCancel(), 0},
		{AgentCreate(), 1},
	};
	for (const FCase& C : Cases)
	{
		TestTrue(FString::Printf(TEXT("%s equals its golden message"), *C.Command.Type), SameJson(C.Command.Data, GoldenData(C.Command.Type, C.Golden)));
	}
	return true;
}

// WP16.7: what every station kind does, and that error replies are shown once and never retried.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUIStationController, "Verse.UI.Stations.Controller", VERSE_STATION_VIEWS_TEST_FLAGS)
bool FVerseUIStationController::RunTest(const FString&)
{
	FRig R;
	// Ledger (parity S-02): agents.open_list, the app takes the foreground on ok.
	R.Ctl.HandleStationUsed(TEXT("agents_list"), TEXT("bridge_command"), TEXT("bridge"));
	TestEqual(TEXT("agents.open_list sent"), R.Link->Count(TEXT("agents.open_list")), 1);
	R.Ctl.HandleStationUsed(TEXT("agents_list"), TEXT("bridge_command"), TEXT("bridge"));
	TestEqual(TEXT("a second press while waiting sends nothing"), R.Link->Count(TEXT("agents.open_list")), 1);
	R.Link->AnswerLast(*FFakeVerseStationLink::Ok());
	TestTrue(TEXT("ok returns to the app"), R.Link->Returns.Num() == 1 && R.Link->Returns[0] == TEXT("station"));

	// Team (parity S-03): none -> notice; the team in session, else the first.
	R.Ctl.HandleStationUsed(TEXT("team"), TEXT("briefing"), FString());
	TestTrue(TEXT("no team: localized notice"), R.Notices.Num() == 1 && R.Notices[0].StartsWith(TEXT("No team meets")));
	TSharedRef<FJsonObject> Env = MakeShared<FJsonObject>();
	Env->SetStringField(TEXT("type"), TEXT("groups.snapshot"));
	TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Groups;
	for (const TCHAR* Id : {TEXT("grp_a"), TEXT("grp_b")})
	{
		TSharedRef<FJsonObject> G = MakeShared<FJsonObject>();
		G->SetStringField(TEXT("group_id"), Id);
		G->SetStringField(TEXT("name"), Id);
		Groups.Add(MakeShared<FJsonValueObject>(G));
	}
	Data->SetArrayField(TEXT("groups"), Groups);
	Env->SetObjectField(TEXT("data"), Data);
	R.Ctl.HandleBridgeFrame(*Env);
	R.Ctl.HandleStationUsed(TEXT("team"), TEXT("briefing"), FString());
	TestEqual(TEXT("first team opened"), R.Link->Last(TEXT("group.open"))->Data->GetStringField(TEXT("group_id")), FString(TEXT("grp_a")));
	R.Link->AnswerLast(*FFakeVerseStationLink::Ok());
	const TSharedPtr<FJsonValue> Meetings = VerseStationGolden::Load(TEXT("messages/meetings.update.json"));
	TSharedRef<FJsonObject> Meet = MakeShared<FJsonObject>();
	Meet->SetStringField(TEXT("type"), TEXT("meetings.update"));
	TSharedRef<FJsonObject> MeetData = MakeShared<FJsonObject>();
	MeetData->SetStringField(TEXT("group_id"), TEXT("grp_b"));
	MeetData->SetBoolField(TEXT("running"), true);
	Meet->SetObjectField(TEXT("data"), MeetData);
	R.Ctl.HandleBridgeFrame(*Meet);
	R.Ctl.HandleStationUsed(TEXT("team"), TEXT("briefing"), FString());
	TestEqual(TEXT("the team in session wins"), R.Link->Last(TEXT("group.open"))->Data->GetStringField(TEXT("group_id")), FString(TEXT("grp_b")));
	R.Link->AnswerLast(*GoldenReply(TEXT("group.open"), 1));
	TestEqual(TEXT("not_found shown as a notice"), R.Notices.Last(), FString(TEXT("error:not_found")));
	TestTrue(TEXT("the golden meetings fixture loads"), Meetings.IsValid());

	// Service record (parity S-04, S-05).
	R.Ctl.HandleStationUsed(TEXT("service_record"), TEXT("records"), TEXT("records_hall"));
	R.Ctl.HandleStationUsed(TEXT("service_record"), TEXT("desk"), TEXT("ready_room"));
	R.Ctl.HandleStationUsed(TEXT("quartermaster"), TEXT("qm"), TEXT("stores"));
	TestTrue(TEXT("ladder, record, rewards"), R.RecordTabs.Num() == 3 && R.RecordTabs[0] == TEXT("ladder") && R.RecordTabs[1] == TEXT("record")
		&& R.RecordTabs[2] == TEXT("rewards"));

	// Simulator (parity S-07).
	R.Ctl.HandleStationUsed(TEXT("games"), TEXT("sim"), FString());
	TestEqual(TEXT("simulator panel"), R.Ctl.Panel(), EVerseStationPanel::Simulator);
	TestFalse(TEXT("an unknown programme is not sent"), R.Ctl.OpenProgramme(TEXT("reactor-defense")));
	TestTrue(TEXT("asteroid run"), R.Ctl.OpenProgramme(TEXT("asteroid-run")));
	R.Link->AnswerLast(*FFakeVerseStationLink::Ok());
	TestEqual(TEXT("panel closes when the app opens it"), R.Ctl.Panel(), EVerseStationPanel::None);

	// Launcher (parity X-03 to X-06).
	R.Ctl.HandleStationUsed(TEXT("coding_launcher"), TEXT("master"), FString());
	TestEqual(TEXT("launcher panel"), R.Ctl.Panel(), EVerseStationPanel::Launcher);
	TestEqual(TEXT("launcher.options asked"), R.Link->Count(TEXT("launcher.options")), 1);
	R.Link->AnswerLast(*GoldenReply(TEXT("launcher.options"), 0));
	const FVerseLauncherState& L = R.Ctl.Launcher();
	TestEqual(TEXT("ready"), L.Phase, EVerseLauncherPhase::Ready);
	TestEqual(TEXT("active workspace preselected"), L.Workspaces[L.Workspace].Id, FString(TEXT("ws_91")));
	TestEqual(TEXT("an installed agent preselected"), L.Agents[L.Agent].Id, FString(TEXT("claude")));
	R.Ctl.LauncherSelectAgent(1);
	TestEqual(TEXT("a missing CLI cannot be picked"), L.Agents[L.Agent].Id, FString(TEXT("claude")));
	R.Ctl.LauncherSetCount(9);
	TestEqual(TEXT("count clamps to 4"), L.Count, 4);
	R.Ctl.LauncherSetCount(2);
	R.Ctl.LauncherSetBrief(TEXT("Write the bridge relay tests."));
	TestTrue(TEXT("start sent"), R.Ctl.LauncherStart());
	TestTrue(TEXT("launcher.start equals the golden request"), SameJson(R.Link->Last(TEXT("launcher.start"))->Data, GoldenData(TEXT("launcher.start"))));
	TestFalse(TEXT("one batch at a time on this side too"), R.Ctl.LauncherStart());
	R.Link->AnswerLast(*GoldenReply(TEXT("launcher.start"), 1));
	TestEqual(TEXT("busy shown"), L.Line, FString(TEXT("error:busy")));
	TestEqual(TEXT("busy not retried"), R.Link->Count(TEXT("launcher.start")), 1);
	TestTrue(TEXT("start again by hand"), R.Ctl.LauncherStart());
	TestTrue(TEXT("starting line"), L.Line.StartsWith(TEXT("Starting 2")));
	R.Ctl.ClosePanel();
	TestEqual(TEXT("closing while starting cancels the batch"), R.Link->Count(TEXT("launcher.cancel")), 1);
	R.Link->Answer(R.Link->Last(TEXT("launcher.start"))->Id, *GoldenReply(TEXT("launcher.start"), 0));
	TestEqual(TEXT("both panes reported"), L.Line, FString(TEXT("2 started.")));
	R.Ctl.HandleStationUsed(TEXT("coding_launcher"), TEXT("master"), FString());
	R.Link->Answer(R.Link->Last(TEXT("launcher.options"))->Id, *GoldenReply(TEXT("launcher.options"), 0));
	R.Ctl.LauncherOpenIde();
	TestEqual(TEXT("ide.open sent"), R.Link->Count(TEXT("ide.open")), 1);

	// Arrivals desk (parity S-09): one create; rate_limited shown, not retried.
	R.Ctl.HandleStationUsed(TEXT("create_agent"), TEXT("arrivals"), FString());
	R.Link->AnswerLast(*GoldenReply(TEXT("agent.create"), 1));
	TestEqual(TEXT("rate_limited shown"), R.Notices.Last(), FString(TEXT("error:rate_limited")));
	TestEqual(TEXT("rate_limited not retried"), R.Link->Count(TEXT("agent.create")), 1);
	const int32 NoticesBefore = R.Notices.Num();
	R.Ctl.HandleStationUsed(TEXT("create_agent"), TEXT("arrivals"), FString());
	R.Link->AnswerLast(*FFakeVerseStationLink::Error(TEXT("conflict")));
	TestEqual(TEXT("a declined create flow is no error"), R.Notices.Num(), NoticesBefore);

	// Armoury: WP18 listens to the hub itself; nothing is sent from here.
	const int32 Sent = R.Link->Sent.Num();
	R.Ctl.HandleStationUsed(TEXT("armoury"), TEXT("hangar_armoury"), FString());
	TestEqual(TEXT("armoury sends no command"), R.Link->Sent.Num(), Sent);
	return true;
}

// WP16.6 to 16.8 end to end: a station event on the hub reaches the station views of that world.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUIStationHub, "Verse.UI.Stations.HubEvent", VERSE_STATION_VIEWS_TEST_FLAGS)
bool FVerseUIStationHub::RunTest(const FString&)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseStationViewsTestWorld"));
	if (!TestNotNull(TEXT("test world"), World))
	{
		return false;
	}
	UVerseEventHub* Hub = World->GetSubsystem<UVerseEventHub>();
	UVerseStationSubsystem* Stations = World->GetSubsystem<UVerseStationSubsystem>();
	UVerseStationUISubsystem* Views = World->GetSubsystem<UVerseStationUISubsystem>();
	if (TestNotNull(TEXT("hub"), Hub) && TestNotNull(TEXT("stations"), Stations) && TestNotNull(TEXT("station views"), Views))
	{
		TSharedRef<FFakeVerseStationLink> Link = MakeShared<FFakeVerseStationLink>();
		Stations->SetLink(Link);
		FVerseStationUsedEvent Event;
		Event.StationId = TEXT("bridge_command");
		Event.Kind = TEXT("agents_list");
		Hub->OnStationUsed.Broadcast(Event);
		TestEqual(TEXT("the hub event sends agents.open_list"), Link->Count(TEXT("agents.open_list")), 1);
		Link->AnswerLast(*FFakeVerseStationLink::Error(TEXT("unavailable")));
		TestEqual(TEXT("the error reaches the notice line"), Views->Notice(FPlatformTime::Seconds()), FString(TEXT("That is not available right now.")));
		Link->Strings.Add(TEXT("verse.station.error.unavailable"), TEXT("Not available (localized)."));
		Hub->OnStationUsed.Broadcast(Event);
		Link->AnswerLast(*FFakeVerseStationLink::Error(TEXT("unavailable")));
		TestEqual(TEXT("error text is localized"), Views->Notice(FPlatformTime::Seconds()), FString(TEXT("Not available (localized).")));
		Event.Kind = TEXT("armoury");
		Hub->OnStationUsed.Broadcast(Event);
		TestEqual(TEXT("the armoury event is left to WP18"), Link->Sent.Num(), 2);
	}
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Combat/VerseCombatTypes.h"
#include "Components/TextRenderComponent.h"
#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewSubsystem.h"
#include "Events/VerseEventHub.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Qa/VerseQaRegistry.h"
#include "Tests/Crew/Fakes/VerseCrewTestWorld.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_CREW_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseCrewLifeTest
{
	const FName DeckBridge(TEXT("bridge"));
	const FName DeckOps(TEXT("ops"));
	const FName DeckEngineering(TEXT("engineering"));
	const FName DeckHangar(TEXT("hangar"));

	int32 PawnsInsideBox(UVerseCrewSubsystem* Crew, const FBox& Box)
	{
		int32 N = 0;
		for (const AVerseCrewPawn* Pawn : Crew->GetPawns())
		{
			const FVector L = Pawn->GetActorLocation();
			N += (L.X > Box.Min.X && L.X < Box.Max.X && L.Y > Box.Min.Y && L.Y < Box.Max.Y) ? 1 : 0;
		}
		return N;
	}
}

using namespace VerseCrewLifeTest;

// A15.1: 40 agents plus 8 panes spawn within 1 s of the snapshot; a delta applies within 200 ms.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewSpawnTest, "Verse.Crew.Life.Spawn", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewSpawnTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("test world"), W.IsValid()) || !TestTrue(FString::Printf(TEXT("decks: %s"), *Error), W.LoadDecks({ DeckBridge, DeckOps, DeckEngineering, DeckHangar }, Error)))
	{
		return false;
	}
	TArray<TSharedRef<FJsonObject>> Agents;
	const TCHAR* OnDuty[] = { TEXT("working"), TEXT("working"), TEXT("working"), TEXT("waiting"), TEXT("error"), TEXT("working"), TEXT("working"), TEXT("waiting") };
	for (int32 I = 0; I < 40; ++I)
	{
		const FString Duty = I < 16 ? OnDuty[I % 8] : TEXT("paused");
		Agents.Add(A::Agent(FString::Printf(TEXT("ag_%03d"), I), FString::Printf(TEXT("Officer %d"), I), Duty, 1 + I, I == 0 ? TEXT("lead") : TEXT("specialist")));
	}
	TArray<TSharedRef<FJsonObject>> Panes;
	const TCHAR* PaneDuty[] = { TEXT("working"), TEXT("working"), TEXT("waiting"), TEXT("error"), TEXT("working"), TEXT("working"), TEXT("waiting"), TEXT("working") };
	for (int32 I = 0; I < 8; ++I)
	{
		Panes.Add(A::Pane(FString::Printf(TEXT("ws_1:T%d"), I + 1), PaneDuty[I]));
	}
	const double Start = FPlatformTime::Seconds();
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot(Agents, Panes));
	W.Crew->Tick(1.f / 60.f);
	const double SpawnMs = (FPlatformTime::Seconds() - Start) * 1000.0;
	TestEqual(TEXT("pawns after the snapshot"), W.Crew->GetPawns().Num(), 48);
	TestTrue(FString::Printf(TEXT("spawned within 1 s (%.1f ms)"), SpawnMs), SpawnMs <= 1000.0);
	for (int32 I = 0; I < 40; ++I)
	{
		TestNotNull(FString::Printf(TEXT("ag_%03d has a pawn"), I), W.Crew->FindPawn(FString::Printf(TEXT("ag_%03d"), I)));
	}

	// Delta: five duty changes, one new agent, one pane gone.
	TArray<TSharedRef<FJsonObject>> Up;
	for (int32 I = 16; I < 21; ++I)
	{
		const TSharedRef<FJsonObject> Patch = MakeShared<FJsonObject>();
		Patch->SetStringField(TEXT("agent_id"), FString::Printf(TEXT("ag_%03d"), I));
		Patch->SetStringField(TEXT("duty"), TEXT("error"));
		Up.Add(Patch);
	}
	const double DeltaStart = FPlatformTime::Seconds();
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta(Up, {}, {}, { TEXT("ws_1:T8") }));
	W.Crew->Tick(1.f / 60.f);
	const double DeltaMs = (FPlatformTime::Seconds() - DeltaStart) * 1000.0;
	TestTrue(FString::Printf(TEXT("delta applied within 200 ms (%.1f ms)"), DeltaMs), DeltaMs <= 200.0);
	const AVerseCrewPawn* Changed = W.Crew->FindPawn(TEXT("ag_016"));
	TestTrue(TEXT("changed duty shows on the pawn"), Changed && Changed->Duty == EVerseCrewDuty::Error);
	TestEqual(TEXT("no resync needed"), W.Crew->GetStats().Resyncs, 0);
	const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetNumberField(TEXT("snapshot_to_pawns_ms"), SpawnMs);
	Report->SetNumberField(TEXT("delta_to_pawns_ms"), DeltaMs);
	Report->SetNumberField(TEXT("pawns"), 48);
	A::WriteProof(TEXT("WP15.1"), TEXT("spawn.json"), Report);
	return true;
}

// bridge-protocol.md 1: a delta whose base is not the last frame of its topic asks for resync;
// golden roster fixtures and the roster_churn scenario apply cleanly.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewRosterFeedTest, "Verse.Crew.Feeds.Roster", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewRosterFeedTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("test world"), W.IsValid()) || !TestTrue(TEXT("decks"), W.LoadDecks({ DeckBridge, DeckEngineering }, Error)))
	{
		return false;
	}
	const TArray<TSharedRef<FJsonObject>> Snapshots = FFakeVerseCrewBridge::GoldenFrames(TEXT("roster.snapshot"));
	const TArray<TSharedRef<FJsonObject>> Deltas = FFakeVerseCrewBridge::GoldenFrames(TEXT("roster.delta"));
	if (!TestTrue(TEXT("golden roster fixtures"), Snapshots.Num() > 0 && Deltas.Num() >= 2))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), Snapshots[0]->GetObjectField(TEXT("data")).ToSharedRef());
	FVerseCrewMember M;
	TestTrue(TEXT("golden agent present"), W.Crew->GetRoster().FindMember(TEXT("ag_7f1"), M));
	TestEqual(TEXT("golden agent duty"), static_cast<int32>(M.Duty), static_cast<int32>(EVerseCrewDuty::Waiting));
	TestEqual(TEXT("golden agent name"), M.Name, FString(TEXT("Mara")));
	TestTrue(TEXT("golden pane present"), W.Crew->GetRoster().FindMember(TEXT("ws_91:T1"), M));
	TestEqual(TEXT("pane is a technician"), static_cast<int32>(M.Role), static_cast<int32>(EVerseCrewRole::Technician));
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), Deltas[0]->GetObjectField(TEXT("data")).ToSharedRef());
	W.Crew->GetRoster().FindMember(TEXT("ag_7f1"), M);
	TestEqual(TEXT("partial upsert changes duty"), static_cast<int32>(M.Duty), static_cast<int32>(EVerseCrewDuty::Working));
	TestEqual(TEXT("partial upsert keeps the name"), M.Name, FString(TEXT("Mara")));
	W.Crew->GetRoster().FindMember(TEXT("ws_91:T1"), M);
	TestEqual(TEXT("pane duty from the delta"), static_cast<int32>(M.Duty), static_cast<int32>(EVerseCrewDuty::Waiting));
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), Deltas[1]->GetObjectField(TEXT("data")).ToSharedRef());
	TestFalse(TEXT("removed agent is gone"), W.Crew->GetRoster().Contains(TEXT("ag_7f1")));
	TestEqual(TEXT("commander level from the delta"), W.Crew->GetRoster().GetCommander().Level, 15);
	TestEqual(TEXT("no resync on a clean sequence"), W.Bridge.Count(TEXT("resync")), 0);

	// A gap: base points at an older frame.
	const TSharedRef<FJsonObject> Patch = MakeShared<FJsonObject>();
	Patch->SetStringField(TEXT("pane_id"), TEXT("ws_91:T1"));
	Patch->SetStringField(TEXT("duty"), TEXT("error"));
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({}, {}, { Patch }), TOptional<int64>(3));
	TestEqual(TEXT("a gap asks for resync"), W.Bridge.Count(TEXT("resync")), 1);
	TestEqual(TEXT("resync names the topic"), W.Bridge.Commands.Last().Data->GetStringField(TEXT("topic")), FString(TEXT("roster")));
	W.Crew->GetRoster().FindMember(TEXT("ws_91:T1"), M);
	TestEqual(TEXT("a delta after a gap is not applied"), static_cast<int32>(M.Duty), static_cast<int32>(EVerseCrewDuty::Waiting));

	// The roster_churn scenario of fake_bridge.py: arrivals, leavers, unknown enum values.
	FVerseCrewTestWorld C;
	if (!TestTrue(TEXT("decks"), C.LoadDecks({ DeckBridge, DeckOps, DeckEngineering }, Error)))
	{
		return false;
	}
	const int32 Frames = C.Bridge.PlayScenario(C.Crew, TEXT("roster_churn"));
	TestTrue(TEXT("roster_churn plays"), Frames > 5);
	C.Run(1.f);
	TestEqual(TEXT("roster_churn needs no resync"), C.Bridge.Count(TEXT("resync")), 0);
	for (const FVerseCrewMember& Member : C.Crew->GetRoster().Members())
	{
		const FString Raw = C.Crew->GetRoster().RawDuty(Member.Id);
		EVerseCrewDuty Strict;
		if (!VerseCrew::TryParseDuty(Raw, Strict))
		{
			TestEqual(FString::Printf(TEXT("unknown duty '%s' of %s is idle"), *Raw, *Member.Id), static_cast<int32>(Member.Duty), static_cast<int32>(EVerseCrewDuty::Idle));
		}
		if (const AVerseCrewPawn* Pawn = C.Crew->FindPawn(Member.Id))
		{
			TestEqual(FString::Printf(TEXT("%s pawn shows its duty"), *Member.Id), static_cast<int32>(Pawn->Duty), static_cast<int32>(Member.Duty));
		}
	}
	return true;
}

// parity C-14, C-15: members on the deck when it opens stand in place; later ones come by lift;
// leavers walk to the lift and vanish.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewEntryLeaveTest, "Verse.Crew.Life.EntryAndLeave", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewEntryLeaveTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckBridge }, Error)))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_a"), TEXT("Ada"), TEXT("working")) }, {}));
	W.Crew->Tick(0.02f);
	const FVerseCrewDeck* Deck = W.Crew->FindDeck(DeckBridge);
	const FVerseCrewDeckPlan* Plan = W.Crew->FindPlan(DeckBridge);
	const AVerseCrewPawn* Ada = W.Crew->FindPawn(TEXT("ag_a"));
	if (!TestNotNull(TEXT("Ada spawned"), Ada) || !TestNotNull(TEXT("plan"), Plan))
	{
		return false;
	}
	const FVerseCrewSocket& Seat = Deck->Sockets[Plan->Placements[TEXT("ag_a")].SocketIndex];
	TestTrue(TEXT("on the deck when it opened: placed at the console"), FVector::Dist2D(Ada->GetActorLocation(), Seat.Location) < 5.f);
	TestEqual(TEXT("working officer types"), static_cast<int32>(Ada->Activity), static_cast<int32>(EVerseCrewActivity::SitType));

	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({ A::Agent(TEXT("ag_b"), TEXT("Bo"), TEXT("working")) }));
	W.Crew->Tick(0.02f);
	const AVerseCrewPawn* Bo = W.Crew->FindPawn(TEXT("ag_b"));
	if (!TestNotNull(TEXT("Bo spawned"), Bo))
	{
		return false;
	}
	TestTrue(TEXT("a later member comes out of the lift"), FVector::Dist2D(Bo->GetActorLocation(), Deck->Lift()->Location) < 5.f);
	W.Run(60.f);
	const FVerseCrewSocket& BoSeat = Deck->Sockets[W.Crew->FindPlan(DeckBridge)->Placements[TEXT("ag_b")].SocketIndex];
	TestTrue(TEXT("Bo reached the console"), FVector::Dist2D(Bo->GetActorLocation(), BoSeat.Location) < 5.f);

	const TSharedRef<FJsonObject> Pause = MakeShared<FJsonObject>();
	Pause->SetStringField(TEXT("agent_id"), TEXT("ag_a"));
	Pause->SetStringField(TEXT("duty"), TEXT("paused"));
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({ Pause }));
	W.Crew->Tick(0.02f);
	TestNotNull(TEXT("the leaver is still walking"), W.Crew->FindPawn(TEXT("ag_a")));
	W.Run(90.f);
	TestNull(TEXT("the leaver vanished at the lift"), W.Crew->FindPawn(TEXT("ag_a")));
	TestEqual(TEXT("no stuck pawns"), W.Crew->GetStats().StuckEvents, 0);
	return true;
}

// 15.4 / parity C-13: a new agent arrives at the hangar shuttle and walks to the lift.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewArrivalTest, "Verse.Crew.Life.Arrival", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewArrivalTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckHangar }, Error)))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_a"), TEXT("Ada"), TEXT("working")) }, {}));
	W.Crew->Tick(0.02f);
	TestNull(TEXT("agents in the first snapshot do not arrive"), W.Crew->FindPawn(TEXT("ag_a")));
	// The agent.create golden reply's agent then shows up in a roster delta.
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({ A::Agent(TEXT("ag_new"), TEXT("Nova"), TEXT("idle")) }));
	W.Crew->Tick(0.02f);
	const FVerseCrewDeck* Deck = W.Crew->FindDeck(DeckHangar);
	const AVerseCrewPawn* Nova = W.Crew->FindPawn(TEXT("ag_new"));
	if (!TestNotNull(TEXT("the newcomer spawned on the hangar"), Nova))
	{
		return false;
	}
	TestTrue(TEXT("it spawned at the shuttle's arrival spawn"), FVector::Dist2D(Nova->GetActorLocation(), Deck->ArrivalSpawn()->Location) < 5.f);
	TestTrue(TEXT("it counts as arriving"), W.Crew->IsArriving(TEXT("ag_new")));
	float Closest = TNumericLimits<float>::Max();
	double ReachedAt = -1.0;
	for (int32 Step = 0; Step < 40 * 30; ++Step)
	{
		W.Crew->Tick(1.f / 30.f);
		if (const AVerseCrewPawn* P = W.Crew->FindPawn(TEXT("ag_new")))
		{
			Closest = FMath::Min(Closest, static_cast<float>(FVector::Dist2D(P->GetActorLocation(), Deck->Lift()->Location)));
		}
		else if (ReachedAt < 0.0)
		{
			ReachedAt = W.Crew->GetClockSeconds();
		}
	}
	TestTrue(FString::Printf(TEXT("it walked to the lift (closest %.0f cm)"), Closest), Closest < 60.f);
	TestTrue(FString::Printf(TEXT("and took it within 40 s (%.1f s)"), ReachedAt), ReachedAt > 0.0 && ReachedAt < 40.0);
	TestEqual(TEXT("no stuck pawns"), W.Crew->GetStats().StuckEvents, 0);
	return true;
}

// 15.5 / parity C-11: a team round gathers its members at the briefing table; team_briefing
// is reported once per round while the commander is on the bridge.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewMeetingsTest, "Verse.Crew.Life.Meetings", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewMeetingsTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckBridge, DeckOps }, Error)))
	{
		return false;
	}
	W.Crew->SetCommanderDeck(DeckBridge);
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_000"), TEXT("Mara"), TEXT("idle")),
		A::Agent(TEXT("ag_001"), TEXT("Oren"), TEXT("idle")), A::Agent(TEXT("ag_002"), TEXT("Tavi"), TEXT("idle")) }, {}));
	const TSharedPtr<FJsonObject> Scenario = FFakeVerseCrewBridge::Scenario(TEXT("meetings"));
	if (!TestTrue(TEXT("meetings scenario"), Scenario.IsValid()))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("groups.snapshot"), Scenario->GetObjectField(TEXT("state"))->GetObjectField(TEXT("groups.snapshot")).ToSharedRef());
	const TArray<TSharedPtr<FJsonValue>>& Steps = Scenario->GetArrayField(TEXT("steps"));
	auto Play = [&](int32 Index) {
		const TSharedPtr<FJsonObject> Frame = Steps[Index]->AsObject()->GetObjectField(TEXT("frame"));
		W.Bridge.Send(W.Crew, Frame->GetStringField(TEXT("type")), Frame->GetObjectField(TEXT("data")).ToSharedRef());
	};
	Play(0);
	W.Run(30.f);
	const AVerseCrewPawn* Speaker = W.Crew->FindPawn(TEXT("ag_000"));
	const AVerseCrewPawn* Listener = W.Crew->FindPawn(TEXT("ag_001"));
	if (!TestNotNull(TEXT("speaker pawn"), Speaker) || !TestNotNull(TEXT("listener pawn"), Listener))
	{
		return false;
	}
	const FVerseCrewDeckPlan* Plan = W.Crew->FindPlan(DeckBridge);
	TestTrue(TEXT("speaker is at the briefing table"), Plan->Placements.Contains(TEXT("ag_000")) && Plan->Placements[TEXT("ag_000")].Intent.Venue == EVerseCrewVenue::Briefing);
	TestEqual(TEXT("speaker talks"), static_cast<int32>(Speaker->Activity), static_cast<int32>(EVerseCrewActivity::Talk));
	TestEqual(TEXT("member listens"), static_cast<int32>(Listener->Activity), static_cast<int32>(EVerseCrewActivity::Listen));
	TestEqual(TEXT("team_briefing reported once"), W.Bridge.Count(TEXT("progression.action"), TEXT("team_briefing")), 1);
	Play(1);
	W.Run(20.f);
	TestEqual(TEXT("the talk clip moved to the new speaker"), static_cast<int32>(W.Crew->FindPawn(TEXT("ag_001"))->Activity), static_cast<int32>(EVerseCrewActivity::Talk));
	TestEqual(TEXT("the old speaker listens"), static_cast<int32>(W.Crew->FindPawn(TEXT("ag_000"))->Activity), static_cast<int32>(EVerseCrewActivity::Listen));
	TestEqual(TEXT("no second team_briefing within the round"), W.Bridge.Count(TEXT("progression.action"), TEXT("team_briefing")), 1);
	for (const FFakeVerseCrewBridge::FCommand& Cmd : W.Bridge.Commands)
	{
		if (Cmd.Type == TEXT("progression.action"))
		{
			TestEqual(TEXT("team_briefing ref is the group id"), Cmd.Data->GetStringField(TEXT("ref")), FString(TEXT("grp_a")));
		}
	}
	// The round settles; a new one later reports again.
	const TSharedRef<FJsonObject> Settle = MakeShared<FJsonObject>();
	Settle->SetStringField(TEXT("group_id"), TEXT("grp_a"));
	Settle->SetBoolField(TEXT("running"), false);
	W.Bridge.Send(W.Crew, TEXT("meetings.update"), Settle);
	W.Run(2.f);
	TestFalse(TEXT("settled: nobody at briefing"), W.Crew->FindPlan(DeckBridge)->Placements.Contains(TEXT("ag_000"))
		&& W.Crew->FindPlan(DeckBridge)->Placements[TEXT("ag_000")].Intent.Venue == EVerseCrewVenue::Briefing);
	Play(0);
	W.Run(2.f);
	TestEqual(TEXT("a new round reports again"), W.Bridge.Count(TEXT("progression.action"), TEXT("team_briefing")), 2);
	// Off the bridge nothing is reported.
	W.Crew->SetCommanderDeck(DeckOps);
	W.Bridge.Send(W.Crew, TEXT("meetings.update"), Settle);
	Play(0);
	W.Run(2.f);
	TestEqual(TEXT("commander off the bridge: no team_briefing"), W.Bridge.Count(TEXT("progression.action"), TEXT("team_briefing")), 2);
	return true;
}

// 15.6 / A15.3 / parity C-21, W-04: the drone follows at heel; walk_together every 50 m with
// the drone within 2.5 m, none during the 20 s cooldown.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewCompanionTest, "Verse.Crew.Life.Companion", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewCompanionTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	const TArray<TSharedRef<FJsonObject>> Snap = FFakeVerseCrewBridge::GoldenFrames(TEXT("companion.snapshot"));
	const TArray<TSharedRef<FJsonObject>> Update = FFakeVerseCrewBridge::GoldenFrames(TEXT("companion.update"));
	if (!TestTrue(TEXT("companion fixtures"), Snap.Num() > 0 && Update.Num() > 0))
	{
		return false;
	}
	auto Walk = [](FVerseCrewTestWorld& W, float Metres, float Speed, float& MaxHeelAfter2s) {
		const float Dt = 1.f / 30.f;
		float X = 0.f;
		float T = 0.f;
		MaxHeelAfter2s = 0.f;
		while (X < Metres * 100.f)
		{
			X += Speed * 100.f * Dt;
			T += Dt;
			W.Crew->SetCommanderOverride(FVector(X, 0.f, 90.f), 0.f);
			W.Crew->Tick(Dt);
			if (T > 2.f && W.Crew->GetDrone())
			{
				MaxHeelAfter2s = FMath::Max(MaxHeelAfter2s, static_cast<float>(FVector::Dist2D(W.Crew->GetDrone()->GetActorLocation(), FVector(X, 0.f, 0.f))));
			}
		}
		W.Run(1.f);
	};
	{
		FVerseCrewTestWorld W;
		W.Crew->SetCommanderOverride(FVector(0.f, 0.f, 90.f), 0.f);
		W.Bridge.Send(W.Crew, TEXT("companion.snapshot"), Snap[0]->GetObjectField(TEXT("data")).ToSharedRef());
		W.Crew->Tick(0.02f);
		if (!TestNotNull(TEXT("the companion drone flies"), W.Crew->GetDrone()))
		{
			return false;
		}
		TestEqual(TEXT("drone wears the pet's look"), W.Crew->GetDrone()->Look, FString(TEXT("drone_brass")));
		float Heel = 0.f;
		Walk(W, 120.f, 1.45f, Heel);
		TestEqual(TEXT("120 m at heel: exactly 2 walk_together"), W.Bridge.Count(TEXT("progression.action"), TEXT("walk_together")), 2);
		TestTrue(FString::Printf(TEXT("drone within 2.5 m after 2 s (max %.0f cm)"), Heel), Heel <= 250.f);
		for (const FFakeVerseCrewBridge::FCommand& Cmd : W.Bridge.Commands)
		{
			TestEqual(TEXT("walk_together ref is empty"), Cmd.Data->GetStringField(TEXT("ref")), FString());
		}
	}
	{
		FVerseCrewTestWorld W;
		W.Bridge.Send(W.Crew, TEXT("companion.snapshot"), Snap[0]->GetObjectField(TEXT("data")).ToSharedRef());
		float Heel = 0.f;
		Walk(W, 200.f, 6.5f, Heel);
		const int32 Sent = W.Bridge.Count(TEXT("progression.action"), TEXT("walk_together"));
		TestTrue(TEXT("sprinting 200 m still pays"), Sent >= 1);
		double Last = -1.0e9;
		for (const FFakeVerseCrewBridge::FCommand& Cmd : W.Bridge.Commands)
		{
			if (Cmd.Type == TEXT("progression.action"))
			{
				TestTrue(FString::Printf(TEXT("no action within the 20 s cooldown (gap %.1f s)"), Cmd.At - Last), Cmd.At - Last >= 20.0 - 0.01);
				Last = Cmd.At;
			}
		}
		TestTrue(FString::Printf(TEXT("drone keeps up with a sprint (max %.0f cm)"), Heel), Heel <= 250.f);
	}
	{
		FVerseCrewTestWorld W;
		W.Bridge.Send(W.Crew, TEXT("companion.snapshot"), Snap[0]->GetObjectField(TEXT("data")).ToSharedRef());
		W.Bridge.Send(W.Crew, TEXT("companion.update"), Update[0]->GetObjectField(TEXT("data")).ToSharedRef());
		float Heel = 0.f;
		Walk(W, 120.f, 1.45f, Heel);
		TestNull(TEXT("hidden pet: no drone"), W.Crew->GetDrone());
		TestEqual(TEXT("120 m without the drone: 0 walk_together"), W.Bridge.Count(TEXT("progression.action"), TEXT("walk_together")), 0);
	}
	{
		// The drone held back: far away, never at heel.
		FVerseCrewWalkTogether Meter;
		const FVector Far(0.f, 10000.f, 0.f);
		int32 Sent = 0;
		for (int32 I = 0; I <= 240; ++I)
		{
			Sent += Meter.Sample(FVector(I * 50.f, 0.f, 0.f), &Far, I * 0.5) ? 1 : 0;
		}
		TestEqual(TEXT("120 m with the drone held back: 0 actions"), Sent, 0);
	}
	return true;
}

// 15.7 / A15.4 / parity B-08: 0 crew pawns inside the arena bounds 2 s after the switch.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewArenaTest, "Verse.Crew.Life.Arena", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewArenaTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckHangar, DeckBridge }, Error)))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_a"), TEXT("Ada"), TEXT("working")) }, {}));
	TArray<TSharedRef<FJsonObject>> New;
	for (int32 I = 0; I < 6; ++I)
	{
		New.Add(A::Agent(FString::Printf(TEXT("ag_n%d"), I), FString::Printf(TEXT("New %d"), I), TEXT("idle")));
	}
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta(New));
	W.Run(3.f);
	const FBox Arena = W.Crew->ArenaBoundsWorld();
	const int32 Before = PawnsInsideBox(W.Crew, Arena);
	TestTrue(FString::Printf(TEXT("arrivals cross the flight deck before the switch (%d)"), Before), Before > 0);
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("event hub"), Hub))
	{
		return false;
	}
	FVerseArenaSwitchEvent On;
	On.bArenaOn = true;
	On.Deck = DeckHangar;
	Hub->OnArenaSwitch.Broadcast(On);
	W.Run(2.f);
	TestEqual(TEXT("0 crew pawns inside the arena 2 s after the switch"), PawnsInsideBox(W.Crew, Arena), 0);
	// Newcomers during the duel never enter the arena.
	W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({ A::Agent(TEXT("ag_late"), TEXT("Late"), TEXT("idle")) }));
	int32 MaxInside = 0;
	for (int32 I = 0; I < 30 * 30; ++I)
	{
		W.Crew->Tick(1.f / 30.f);
		MaxInside = FMath::Max(MaxInside, PawnsInsideBox(W.Crew, Arena));
	}
	TestEqual(TEXT("never inside while the arena is on"), MaxInside, 0);
	TestNotNull(TEXT("crew off the hangar is untouched"), W.Crew->FindPawn(TEXT("ag_a")));
	FVerseArenaSwitchEvent Off;
	Off.bArenaOn = false;
	Off.Deck = DeckHangar;
	Hub->OnArenaSwitch.Broadcast(Off);
	W.Crew->Tick(0.1f);
	TestFalse(TEXT("arena off"), W.Crew->IsArenaOn());
	const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetNumberField(TEXT("inside_before"), Before);
	Report->SetNumberField(TEXT("inside_2s_after"), PawnsInsideBox(W.Crew, Arena));
	Report->SetNumberField(TEXT("max_inside_during_duel"), MaxInside);
	A::WriteProof(TEXT("WP15.7"), TEXT("arena.json"), Report);
	return true;
}

// 15.8: first click selects and shows the nameplate; a second click opens the member in the
// app (agent.open / pane.open); open commands stay under 4/s.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewInteractionTest, "Verse.Crew.Life.Interaction", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewInteractionTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckBridge, DeckEngineering }, Error)))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_7f1"), TEXT("Mara"), TEXT("working")) }, { A::Pane(TEXT("ws_91:T1"), TEXT("working")) }));
	W.Crew->Tick(0.02f);
	AVerseCrewPawn* Mara = W.Crew->FindPawn(TEXT("ag_7f1"));
	if (!TestNotNull(TEXT("officer pawn"), Mara))
	{
		return false;
	}
	TestTrue(TEXT("nameplate hidden before selection"), Mara->Nameplate->bHiddenInGame);
	TestTrue(TEXT("first click selects"), W.Crew->ClickActor(Mara));
	TestEqual(TEXT("selected"), W.Crew->GetSelected(), FString(TEXT("ag_7f1")));
	TestFalse(TEXT("nameplate shows"), Mara->Nameplate->bHiddenInGame);
	TestEqual(TEXT("nameplate reads the name"), Mara->Nameplate->Text.ToString(), FString(TEXT("Mara")));
	TestEqual(TEXT("selecting sends nothing"), W.Bridge.Commands.Num(), 0);
	TestTrue(TEXT("second click opens"), W.Crew->ClickActor(Mara));
	if (TestEqual(TEXT("one command"), W.Bridge.Commands.Num(), 1))
	{
		TestEqual(TEXT("agent.open"), W.Bridge.Commands[0].Type, FString(TEXT("agent.open")));
		TestEqual(TEXT("agent.open carries the agent id"), W.Bridge.Commands[0].Data->GetStringField(TEXT("agent_id")), FString(TEXT("ag_7f1")));
	}
	AVerseCrewPawn* Tech = W.Crew->FindPawn(TEXT("ws_91:T1"));
	TestTrue(TEXT("click on a technician selects it"), Tech && W.Crew->ClickActor(Tech));
	TestTrue(TEXT("the old selection's nameplate hides"), Mara->Nameplate->bHiddenInGame);
	W.Crew->ClickActor(Tech);
	TestEqual(TEXT("pane.open for a technician"), W.Bridge.Commands.Last().Type, FString(TEXT("pane.open")));
	TestEqual(TEXT("pane.open carries the pane id"), W.Bridge.Commands.Last().Data->GetStringField(TEXT("pane_id")), FString(TEXT("ws_91:T1")));
	// Hammering the second click: at most 4 open commands per second.
	const int32 Before = W.Bridge.Commands.Num();
	for (int32 I = 0; I < 10; ++I)
	{
		W.Crew->ClickMember(TEXT("ws_91:T1"));
		W.Crew->Tick(0.01f);
	}
	TestTrue(FString::Printf(TEXT("at most 4 opens per second (%d)"), W.Bridge.Commands.Num() - Before + 1), W.Bridge.Commands.Num() - Before + 1 <= 4);
	TestFalse(TEXT("unknown member is not clickable"), W.Crew->ClickMember(TEXT("ag_nobody")));
	return true;
}

// parity C-24: Verse.QA.SetDuty forces a member's duty; none releases it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewQaSetDutyTest, "Verse.Crew.QA.SetDuty", VERSE_CREW_TEST_FLAGS)
bool FVerseCrewQaSetDutyTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	if (!TestTrue(TEXT("decks"), W.LoadDecks({ DeckBridge, DeckOps }, Error)))
	{
		return false;
	}
	W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), A::Snapshot({ A::Agent(TEXT("ag_q"), TEXT("Quill"), TEXT("paused")) }, {}));
	W.Crew->Tick(0.02f);
	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!TestNotNull(TEXT("QA registry"), Registry))
	{
		return false;
	}
	TestTrue(TEXT("Verse.QA.SetDuty registered"), Registry->IsRegistered(TEXT("Verse.QA.SetDuty")));
	FString Result;
	TestTrue(TEXT("SetDuty runs"), Registry->ExecuteLine(TEXT("Verse.QA.SetDuty ag_q working"), Result));
	W.Crew->Tick(0.02f);
	const AVerseCrewPawn* Pawn = W.Crew->FindPawn(TEXT("ag_q"));
	TestTrue(TEXT("forced to working"), Pawn && Pawn->Duty == EVerseCrewDuty::Working);
	TestTrue(TEXT("forced member goes to a bridge console"), W.Crew->FindPlan(DeckBridge)->Placements.Contains(TEXT("ag_q")));
	TestTrue(TEXT("SetDuty none runs"), Registry->ExecuteLine(TEXT("Verse.QA.SetDuty ag_q none"), Result));
	W.Crew->Tick(0.02f);
	TestFalse(TEXT("released: back off the bridge consoles"), W.Crew->FindPlan(DeckBridge)->Placements.Contains(TEXT("ag_q")));
	Registry->ExecuteLine(TEXT("Verse.QA.SetDuty ag_q dancing"), Result);
	TestTrue(TEXT("bad duty answers an error"), Result.Contains(TEXT("error")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

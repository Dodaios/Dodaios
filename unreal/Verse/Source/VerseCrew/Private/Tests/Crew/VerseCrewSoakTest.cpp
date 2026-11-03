#include "Crew/VerseCrewPawn.h"
#include "Crew/VerseCrewSubsystem.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Tests/Crew/Fakes/VerseCrewTestWorld.h"

#if WITH_DEV_AUTOMATION_TESTS

// 15.9 / A15.5: 30 minutes (crew clock, 30 Hz ticks) with 40 crew plus 8 panes on all four
// decks walking over Recast, roster churn every 20 s, arrivals and leavers, team rounds and the
// commander walking with the drone: 0 stuck pawns, and the game thread spends at most 1 ms on
// crew life in every frame, the first snapshot included. A frame's cost is the bridge frames
// handed over in it plus the tick, measured as this thread's CPU time (the box is shared, so
// wall time also counts other processes holding the core; it is reported next to it).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewSoakTest, "Verse.Crew.Perf.Soak",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseCrewSoakTest::RunTest(const FString&)
{
	using A = FVerseCrewTestWorld;
	FVerseCrewTestWorld W;
	FString Error;
	const FName Decks[] = { FName(TEXT("bridge")), FName(TEXT("ops")), FName(TEXT("engineering")), FName(TEXT("hangar")) };
	double NavBuildMs = 0.0;
	if (!TestTrue(TEXT("test world"), W.IsValid()) || !TestTrue(FString::Printf(TEXT("decks: %s"), *Error), W.LoadDecks(TArray<FName>(Decks, 4), Error))
		|| !TestTrue(FString::Printf(TEXT("navmesh: %s"), *Error), W.BuildNav(TArray<FName>(Decks, 4), Error, &NavBuildMs)))
	{
		return false;
	}
	FVerseCrewThreadClock Clock;
	Clock.Calibrate();
	const FString Duties[] = { TEXT("working"), TEXT("waiting"), TEXT("idle"), TEXT("paused"), TEXT("error") };
	FRandomStream Rng(15091);
	TArray<TSharedRef<FJsonObject>> Agents;
	TArray<FString> AgentIds;
	for (int32 I = 0; I < 40; ++I)
	{
		const FString Id = FString::Printf(TEXT("ag_%03d"), I);
		// Mostly what a real roster looks like: a third on duty, the rest idle or paused.
		const FString Duty = I < 12 ? Duties[I % 2 == 0 ? 0 : (I % 3 == 0 ? 4 : 1)] : (I < 20 ? Duties[3] : Duties[2]);
		Agents.Add(A::Agent(Id, FString::Printf(TEXT("Officer %d"), I), Duty, 1 + I % 50, I == 0 ? TEXT("lead") : TEXT("specialist")));
		AgentIds.Add(Id);
	}
	TArray<TSharedRef<FJsonObject>> Panes;
	for (int32 I = 0; I < 8; ++I)
	{
		Panes.Add(A::Pane(FString::Printf(TEXT("ws_1:T%d"), I + 1), Duties[I % 3 == 2 ? 2 : I % 2]));
	}
	const TSharedRef<FJsonObject> Snapshot = A::Snapshot(Agents, Panes);
	const TSharedRef<FJsonObject> Groups = MakeShared<FJsonObject>();
	{
		const TSharedRef<FJsonObject> G = MakeShared<FJsonObject>();
		G->SetStringField(TEXT("group_id"), TEXT("grp_soak"));
		G->SetStringField(TEXT("name"), TEXT("Soak crew"));
		G->SetArrayField(TEXT("members"), { MakeShared<FJsonValueString>(TEXT("ag_030")), MakeShared<FJsonValueString>(TEXT("ag_031")), MakeShared<FJsonValueString>(TEXT("ag_032")) });
		G->SetStringField(TEXT("lead"), TEXT("ag_030"));
		Groups->SetArrayField(TEXT("groups"), { MakeShared<FJsonValueObject>(G) });
	}
	const TSharedRef<FJsonObject> CompanionData = FFakeVerseCrewBridge::GoldenFrames(TEXT("companion.snapshot"))[0]->GetObjectField(TEXT("data")).ToSharedRef();
	W.Crew->SetCommanderDeck(FName(TEXT("bridge")));

	const float Dt = 1.f / 30.f;
	const int32 Ticks = 30 * 60 * 30;
	TArray<double> TickMs;
	TickMs.Reserve(Ticks);
	TArray<double> WallMs;
	WallMs.Reserve(Ticks);
	const FVerseCrewDeck* Ops = W.Crew->FindDeck(FName(TEXT("ops")));
	const FVector OpsCentre = Ops ? Ops->OriginCm + FVector(4800.f, 3000.f, 90.f) : FVector::ZeroVector;
	int32 NextAgent = 40;
	int32 Overlaps = 0;
	int32 MaxPawns = 0;
	double MeetingUntil = -1.0;
	for (int32 Tick = 0; Tick < Ticks; ++Tick)
	{
		const double T = Tick * Dt;
		// The frame's crew work starts with the bridge frames that arrive in it.
		const double WallStart = FPlatformTime::Seconds();
		const uint64 CpuStart = FVerseCrewThreadClock::Cycles();
		if (Tick == 0)
		{
			W.Bridge.Send(W.Crew, TEXT("roster.snapshot"), Snapshot);
			W.Bridge.Send(W.Crew, TEXT("groups.snapshot"), Groups);
			W.Bridge.Send(W.Crew, TEXT("companion.snapshot"), CompanionData);
		}
		// The commander walks a 20 m circle on ops with the drone at heel.
		const float Angle = static_cast<float>(T) * 0.07f;
		W.Crew->SetCommanderOverride(OpsCentre + FVector(FMath::Cos(Angle), FMath::Sin(Angle), 0.f) * 2000.f, FMath::RadiansToDegrees(Angle) + 90.f);
		if (Tick > 0 && Tick % (20 * 30) == 0)
		{
			TArray<TSharedRef<FJsonObject>> Up;
			for (int32 K = 0; K < 3; ++K)
			{
				const TSharedRef<FJsonObject> Patch = MakeShared<FJsonObject>();
				Patch->SetStringField(TEXT("agent_id"), AgentIds[Rng.RandRange(0, AgentIds.Num() - 1)]);
				Patch->SetStringField(TEXT("duty"), Duties[Rng.RandRange(0, 4)]);
				Up.Add(Patch);
			}
			const TSharedRef<FJsonObject> PanePatch = MakeShared<FJsonObject>();
			PanePatch->SetStringField(TEXT("pane_id"), FString::Printf(TEXT("ws_1:T%d"), Rng.RandRange(1, 8)));
			PanePatch->SetStringField(TEXT("duty"), Duties[Rng.RandRange(0, 4)]);
			W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta(Up, {}, { PanePatch }));
		}
		if (Tick > 0 && Tick % (90 * 30) == 0)
		{
			// One arrives, one leaves.
			const FString NewId = FString::Printf(TEXT("ag_%03d"), NextAgent++);
			const int32 Gone = Rng.RandRange(1, AgentIds.Num() - 1);
			const FString GoneId = AgentIds[Gone];
			AgentIds.RemoveAt(Gone);
			AgentIds.Add(NewId);
			W.Bridge.Send(W.Crew, TEXT("roster.delta"), A::Delta({ A::Agent(NewId, TEXT("Newcomer"), Duties[Rng.RandRange(0, 2)]) }, { GoneId }));
		}
		if (Tick % (300 * 30) == 0)
		{
			const TSharedRef<FJsonObject> M = MakeShared<FJsonObject>();
			M->SetStringField(TEXT("group_id"), TEXT("grp_soak"));
			M->SetBoolField(TEXT("running"), true);
			M->SetNumberField(TEXT("round"), 1);
			M->SetStringField(TEXT("speaker"), TEXT("ag_030"));
			W.Bridge.Send(W.Crew, TEXT("meetings.update"), M);
			MeetingUntil = T + 120.0;
		}
		if (MeetingUntil > 0.0 && T >= MeetingUntil)
		{
			const TSharedRef<FJsonObject> M = MakeShared<FJsonObject>();
			M->SetStringField(TEXT("group_id"), TEXT("grp_soak"));
			M->SetBoolField(TEXT("running"), false);
			W.Bridge.Send(W.Crew, TEXT("meetings.update"), M);
			MeetingUntil = -1.0;
		}
		W.Crew->Tick(Dt);
		TickMs.Add(Clock.Ms(CpuStart, FVerseCrewThreadClock::Cycles()));
		WallMs.Add((FPlatformTime::Seconds() - WallStart) * 1000.0);
		if (Tick % 30 == 0)
		{
			// Crowd check once a second: walking capsules that overlap (closer than two radii).
			const TArray<AVerseCrewPawn*> Pawns = W.Crew->GetPawns();
			MaxPawns = FMath::Max(MaxPawns, Pawns.Num());
			for (int32 I = 0; I < Pawns.Num(); ++I)
			{
				for (int32 J = I + 1; J < Pawns.Num(); ++J)
				{
					const bool bWalking = Pawns[I]->Activity == EVerseCrewActivity::Walk && Pawns[J]->Activity == EVerseCrewActivity::Walk;
					if (bWalking && FVector::Dist2D(Pawns[I]->GetActorLocation(), Pawns[J]->GetActorLocation()) < 2.f * W.Crew->GetTuning().CrewRadiusCm - 0.5f)
					{
						++Overlaps;
					}
				}
			}
		}
	}
	auto Percentile = [](TArray<double> Values, double Q) {
		Values.Sort();
		return Values[FMath::Min(Values.Num() - 1, static_cast<int32>(Values.Num() * Q))];
	};
	double Sum = 0.0;
	double Max = 0.0;
	int32 Over1Ms = 0;
	for (const double Ms : TickMs)
	{
		Sum += Ms;
		Max = FMath::Max(Max, Ms);
		Over1Ms += Ms > 1.0 ? 1 : 0;
	}
	const double Mean = Sum / TickMs.Num();
	const double P99 = Percentile(TickMs, 0.99);
	const double P999 = Percentile(TickMs, 0.999);
	double WallMax = 0.0;
	int32 WallOver1Ms = 0;
	for (const double Ms : WallMs)
	{
		WallMax = FMath::Max(WallMax, Ms);
		WallOver1Ms += Ms > 1.0 ? 1 : 0;
	}
	const double WallP99 = Percentile(WallMs, 0.99);
	const double WallP999 = Percentile(WallMs, 0.999);
	const FVerseCrewStats& CrewStats = W.Crew->GetStats();
	AddInfo(FString::Printf(TEXT("frames %d: cpu mean %.4f p99 %.4f p99.9 %.4f max %.4f ms (%d over 1 ms); wall p99 %.4f p99.9 %.4f max %.4f ms (%d over 1 ms)"),
		TickMs.Num(), Mean, P99, P999, Max, Over1Ms, WallP99, WallP999, WallMax, WallOver1Ms));
	AddInfo(FString::Printf(TEXT("stuck %d; overlaps %d; yields %d; replans %d; spawned %d (pool reuses %d); nav paths %d, fallbacks %d, blocked %d; worst plan %.3f spawn %.3f path %.3f ms; peak queue %d; walk_together %d"),
		CrewStats.StuckEvents, Overlaps, CrewStats.CrowdYields, CrewStats.Replans, CrewStats.Spawned, CrewStats.PoolReuses, CrewStats.NavPaths, CrewStats.NavFallbacks, CrewStats.NavBlocked,
		CrewStats.MaxPlanDeckMs, CrewStats.MaxSpawnMs, CrewStats.MaxPathMs, CrewStats.PeakQueuedWork, W.Bridge.Count(TEXT("progression.action"), TEXT("walk_together"))));
	TestTrue(FString::Printf(TEXT("thread clock calibrated (%.0f cycles/s)"), Clock.CyclesPerSecond), Clock.CyclesPerSecond > 1.0e8);
	TestEqual(TEXT("0 stuck pawns in 30 minutes"), CrewStats.StuckEvents, 0);
	TestTrue(FString::Printf(TEXT("crew game thread at most 1 ms in every frame (max %.4f ms, %d frames over)"), Max, Over1Ms), Max <= 1.0);
	TestTrue(TEXT("40 crew and more were on the decks"), MaxPawns >= 40);
	TestEqual(TEXT("no resync"), CrewStats.Resyncs, 0);
	TestTrue(FString::Printf(TEXT("the crew walks over Recast (%d paths)"), CrewStats.NavPaths), CrewStats.NavPaths > 100);
	TestEqual(TEXT("no straight-line fallback or blocked walk"), CrewStats.NavFallbacks + CrewStats.NavBlocked, 0);

	const TSharedRef<FJsonObject> Report = MakeShared<FJsonObject>();
	Report->SetStringField(TEXT("test"), TEXT("Verse.Crew.Perf.Soak"));
	Report->SetNumberField(TEXT("crew_clock_minutes"), Ticks * Dt / 60.0);
	Report->SetNumberField(TEXT("tick_hz"), 30);
	Report->SetNumberField(TEXT("ticks"), TickMs.Num());
	Report->SetNumberField(TEXT("agents"), 40);
	Report->SetNumberField(TEXT("panes"), 8);
	Report->SetNumberField(TEXT("max_pawns"), MaxPawns);
	Report->SetStringField(TEXT("frame_cost"), TEXT("bridge frames handled in the frame plus UVerseCrewSubsystem::Tick, game thread CPU time"));
	Report->SetNumberField(TEXT("frame_cpu_ms_mean"), Mean);
	Report->SetNumberField(TEXT("frame_cpu_ms_p99"), P99);
	Report->SetNumberField(TEXT("frame_cpu_ms_p999"), P999);
	Report->SetNumberField(TEXT("frame_cpu_ms_max"), Max);
	Report->SetNumberField(TEXT("frames_cpu_over_1ms"), Over1Ms);
	Report->SetNumberField(TEXT("frame_wall_ms_p99"), WallP99);
	Report->SetNumberField(TEXT("frame_wall_ms_p999"), WallP999);
	Report->SetNumberField(TEXT("frame_wall_ms_max"), WallMax);
	Report->SetNumberField(TEXT("frames_wall_over_1ms"), WallOver1Ms);
	Report->SetNumberField(TEXT("tick_budget_ms"), W.Crew->GetTuning().TickBudgetMs);
	Report->SetNumberField(TEXT("nav_build_ms"), NavBuildMs);
	Report->SetNumberField(TEXT("nav_paths"), CrewStats.NavPaths);
	Report->SetNumberField(TEXT("nav_fallbacks"), CrewStats.NavFallbacks);
	Report->SetNumberField(TEXT("nav_blocked"), CrewStats.NavBlocked);
	Report->SetNumberField(TEXT("worst_plan_deck_ms"), CrewStats.MaxPlanDeckMs);
	Report->SetNumberField(TEXT("worst_spawn_ms"), CrewStats.MaxSpawnMs);
	Report->SetNumberField(TEXT("worst_path_ms"), CrewStats.MaxPathMs);
	Report->SetNumberField(TEXT("peak_queued_work"), CrewStats.PeakQueuedWork);
	Report->SetNumberField(TEXT("frames_with_backlog"), static_cast<double>(CrewStats.TicksWithBacklog));
	Report->SetNumberField(TEXT("pool_reuses"), CrewStats.PoolReuses);
	Report->SetNumberField(TEXT("crowd_yields"), CrewStats.CrowdYields);
	Report->SetNumberField(TEXT("stuck"), CrewStats.StuckEvents);
	Report->SetNumberField(TEXT("walker_overlaps"), Overlaps);
	Report->SetNumberField(TEXT("replans"), CrewStats.Replans);
	Report->SetNumberField(TEXT("spawned"), CrewStats.Spawned);
	Report->SetNumberField(TEXT("despawned"), CrewStats.Despawned);
	Report->SetNumberField(TEXT("arrivals"), CrewStats.Arrivals);
	Report->SetNumberField(TEXT("walk_together"), W.Bridge.Count(TEXT("progression.action"), TEXT("walk_together")));
	Report->SetNumberField(TEXT("team_briefing"), W.Bridge.Count(TEXT("progression.action"), TEXT("team_briefing")));
	A::WriteProof(TEXT("WP15.9"), TEXT("soak.json"), Report);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

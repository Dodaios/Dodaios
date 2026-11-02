#include "Bot/VerseBotTier.h"
#include "Misc/AutomationTest.h"
#include "Tactics/VerseBotTactics.h"
#include "Tests/Brain/Fakes/FakeVerseBotWorld.h"
#include "Tests/Brain/Fakes/FakeVerseDuelSim.h"
#include "Tests/Brain/VerseBotTestProof.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotTacticsTest
{
	using EState = EVerseBotState;

	/** A scripted context over the standard arena: the bot at the origin's south, belief north. */
	struct FScene
	{
		FFakeVerseBotWorldQueries World;
		FFakeVerseBotBelief Belief;
		FVerseBotBeliefSummary Summary;
		FVerseSelfPercept Self;
		FVersePerceptFrame Frame;
		FVerseBotQueryCache Cache;
		FVerseSightPercept Sight;
		UVerseBotTier* Tier = nullptr;
		FVerseBotTacticsContext Ctx;

		explicit FScene(FName TierId)
		{
			FFakeVerseBotWorldQueries::BuildStandardArena(World);
			Tier = NewObject<UVerseBotTier>();
			Tier->AddToRoot();
			UVerseBotTier::ApplyStartValues(TierId, *Tier);
			Self.Location = FVector(0.f, -1200.f, 0.f);
			Self.EyeLocation = Self.Location + FVector(0, 0, 165.f);
			Self.ViewRotation = FRotator(0.f, 90.f, 0.f);
			Self.Health = 100.f;
			Self.MaxHealth = 100.f;
			Self.Magazine = 30;
			Self.Reserve = 90;
			Summary.State = EVerseBeliefState::Tracked;
			Summary.TopCenter = FVector(0.f, 1200.f, 0.f);
			Summary.Confidence = 0.7f;
			Summary.SupportAgeS = 0.5f;
			Summary.bPriorOnly = false;
			Summary.SpreadCm = 300.f;
			Summary.FacingYawDeg = 90.f; // facing away from the bot (north)
			Summary.FacingAgeS = 1.f;
			Summary.SinceSightingS = 3.f;
		}
		~FScene() { Tier->RemoveFromRoot(); }

		FVerseBotTacticsContext& Build()
		{
			Belief.S = Summary;
			Frame.Self = Self;
			Ctx = FVerseBotTacticsContext();
			Ctx.Query.Self = &Self;
			Ctx.Query.Belief = &Summary;
			Ctx.Query.BeliefMap = &Belief;
			Ctx.Query.World = &World;
			Ctx.Query.Tier = Tier;
			Ctx.Query.PreferredRangeCm = Tier->PreferredRangeM * 100.f;
			Ctx.Frame = &Frame;
			Ctx.Cache = &Cache;
			Ctx.SinceSightS = Summary.SinceSightingS;
			Ctx.HealthFrac = Self.Health / Self.MaxHealth;
			Ctx.MagazineFrac = float(Self.Magazine) / 30.f;
			return Ctx;
		}

		EState Best()
		{
			float U[VerseBot::NumStates];
			VerseBotTactics::Utilities(Build(), U);
			int32 B = 0;
			for (int32 i = 1; i < VerseBot::NumStates; ++i)
			{
				B = U[i] > U[B] ? i : B;
			}
			return EState(B);
		}
	};
}

// 8.3-8.5: each state wins its own scenario (bot.md 5.1 utility terms).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotTacticsUtilityTest, "Verse.Bot.Tactics.Utility", VERSE_BOT_TEST_FLAGS)

bool FVerseBotTacticsUtilityTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotTacticsTest;
	{
		FScene S(TEXT("hard"));
		S.Sight.PelvisLocation = FVector(0.f, 0.f, 95.f);
		S.Sight.VisibleMask = 0xff;
		S.Build();
		S.Ctx.Sighting = &S.Sight;
		S.Summary.State = EVerseBeliefState::Known;
		S.Summary.SinceSightingS = 0.f;
		float U[VerseBot::NumStates];
		S.Ctx.SinceSightS = 0.f;
		VerseBotTactics::Utilities(S.Ctx, U);
		int32 B = 0;
		for (int32 i = 1; i < VerseBot::NumStates; ++i) B = U[i] > U[B] ? i : B;
		TestEqual(TEXT("Attack on a sighting"), EState(B), EState::Attack);
	}
	{
		FScene S(TEXT("hard"));
		S.Self.Health = 20.f;
		TestEqual(TEXT("Retreat when low against a healthy estimate"), S.Best(), EState::Retreat);
	}
	{
		FScene S(TEXT("hard"));
		S.Self.Magazine = 3;
		S.Summary.State = EVerseBeliefState::Lost;
		S.Summary.Confidence = 0.1f;
		TestEqual(TEXT("Reload with a low magazine and no threat"), S.Best(), EState::Reload);
	}
	{
		FScene S(TEXT("hard"));
		S.Summary.State = EVerseBeliefState::Lost;
		S.Summary.Confidence = 0.1f;
		TestEqual(TEXT("Search when the belief is lost"), S.Best(), EState::Search);
	}
	{
		FScene S(TEXT("hard"));
		S.Summary.SinceSightingS = 0.8f;
		S.Summary.Velocity = FVector(0.f, -400.f, 0.f); // toward the bot
		S.Cache.Cover[int32(EVerseBotCoverMode::Near)].bFound = true;
		S.Cache.Cover[int32(EVerseBotCoverMode::Near)].Point.Location = FVector(0.f, -700.f, 0.f);
		TestEqual(TEXT("Hold with cover and an approaching belief"), S.Best(), EState::Hold);
	}
	{
		FScene S(TEXT("elite"));
		S.Summary.SinceSightingS = 3.f;
		TestEqual(TEXT("Flank a still belief after 1.5-8 s without sight"), S.Best(), EState::Flank);
	}
	{
		FScene S(TEXT("elite"));
		S.Summary.SinceSightingS = 9.f;
		S.Summary.SpreadCm = 150.f;
		S.Cache.Finisher.bFound = true;
		TestEqual(TEXT("Stalk a static, facing-away belief with Spread < 2 m"), S.Best(), EState::StalkForFinisher);
	}
	{
		FScene S(TEXT("elite"));
		S.Summary.SinceSightingS = 9.f;
		S.Build();
		S.Ctx.bBulwarkReady = true;
		float U[VerseBot::NumStates];
		VerseBotTactics::Utilities(S.Ctx, U);
		int32 B = 0;
		for (int32 i = 1; i < VerseBot::NumStates; ++i) B = U[i] > U[B] ? i : B;
		TestEqual(TEXT("DeployBulwark with no cover within 6 m"), EState(B), EState::DeployBulwark);
	}
	{
		FScene S(TEXT("elite"));
		S.Summary.SinceSightingS = 9.f;
		S.Cache.Breach.bFound = true;
		S.Cache.Breach.Score = 0.5f;
		S.Build();
		S.Ctx.bBreachReady = true;
		float U[VerseBot::NumStates];
		VerseBotTactics::Utilities(S.Ctx, U);
		int32 B = 0;
		for (int32 i = 1; i < VerseBot::NumStates; ++i) B = U[i] > U[B] ? i : B;
		TestEqual(TEXT("Breach a believed-intact piece on the way"), EState(B), EState::Breach);
	}
	{
		FScene S(TEXT("elite"));
		S.Summary.SinceSightingS = 9.f;
		S.Build();
		S.Ctx.bWallbangAuthorised = true;
		float U[VerseBot::NumStates];
		VerseBotTactics::Utilities(S.Ctx, U);
		int32 B = 0;
		for (int32 i = 1; i < VerseBot::NumStates; ++i) B = U[i] > U[B] ? i : B;
		TestEqual(TEXT("Wallbang with authority"), EState(B), EState::Wallbang);
		S.Ctx.bWallbangAuthorised = false;
		VerseBotTactics::Utilities(S.Ctx, U);
		TestTrue(TEXT("no Wallbang without authority"), U[int32(EState::Wallbang)] < 0.f);
	}
	return true;
}

// 8.3-8.5: what the states do (intents).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotTacticsTickTest, "Verse.Bot.Tactics.Tick", VERSE_BOT_TEST_FLAGS)

bool FVerseBotTacticsTickTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotTacticsTest;
	// Hold: Go -> Hide -> Peek -> Hide with the contract times.
	{
		FScene S(TEXT("hard"));
		FVerseBotCoverPoint Cover;
		Cover.Location = S.Self.Location;
		Cover.bHigh = false;
		Cover.EdgeId = 7;
		S.Cache.Cover[int32(EVerseBotCoverMode::Near)].bFound = true;
		S.Cache.Cover[int32(EVerseBotCoverMode::Near)].Point = Cover;
		S.Cache.Peek.bFound = true;
		S.Cache.Peek.Type = EVerseBotPeekType::LeanRight;
		S.Cache.Peek.StandPoint = Cover.Location;
		FVerseBotTacticsMemory Mem;
		FVerseRng Rng(3);
		FVerseBotTacticsContext& Ctx = S.Build();
		VerseBotTactics::Enter(EState::Hold, Ctx, Mem, Rng);
		Ctx.Query.NowS = 0.f;
		VerseBotTactics::Tick(EState::Hold, Ctx, Mem, Rng);
		TestEqual(TEXT("arrived: Hide"), Mem.HoldPhase, EVerseBotHoldPhase::Hide);
		const float HideFor = Mem.PhaseUntilS;
		TestTrue(TEXT("hide U(0.5, 1.1) s"), HideFor >= 0.5f && HideFor <= 1.1f);
		const FVerseBotIntent Hidden = VerseBotTactics::Tick(EState::Hold, Ctx, Mem, Rng);
		TestEqual(TEXT("low cover: crouch while hiding"), Hidden.Stance, EVerseStance::Crouch);
		Ctx.Query.NowS = HideFor + 0.01f;
		VerseBotTactics::Tick(EState::Hold, Ctx, Mem, Rng);
		TestEqual(TEXT("then Peek"), Mem.HoldPhase, EVerseBotHoldPhase::Peek);
		const float PeekFor = Mem.PhaseUntilS - Ctx.Query.NowS;
		TestTrue(TEXT("peek U(0.7, 1.5) s"), PeekFor >= 0.7f && PeekFor <= 1.5f);
		const FVerseBotIntent Peek = VerseBotTactics::Tick(EState::Hold, Ctx, Mem, Rng);
		TestEqual(TEXT("lean peek leans right"), int32(Peek.Lean), 1);
		TestEqual(TEXT("recent peek edge recorded"), Mem.RecentPeekEdges.Num() > 0 ? Mem.RecentPeekEdges.Last() : -1, 7);
		Ctx.Query.NowS += 1.6f;
		VerseBotTactics::Tick(EState::Hold, Ctx, Mem, Rng);
		TestEqual(TEXT("back to Hide"), Mem.HoldPhase, EVerseBotHoldPhase::Hide);
		// No peek with a low magazine.
		S.Self.Magazine = 2;
		FVerseBotTacticsContext& Low = S.Build();
		Low.Query.NowS = Mem.PhaseUntilS + 0.01f;
		VerseBotTactics::Tick(EState::Hold, Low, Mem, Rng);
		TestEqual(TEXT("no peek below the reload threshold"), Mem.HoldPhase, EVerseBotHoldPhase::Hide);
	}
	// StalkForFinisher: silent crouch-walk, melee press inside 1.5 m when the finisher can activate.
	{
		FScene S(TEXT("elite"));
		S.Summary.TopCenter = S.Self.Location + FVector(0.f, 120.f, 0.f);
		FVerseBotTacticsMemory Mem;
		FVerseRng Rng(4);
		FVerseBotTacticsContext& Ctx = S.Build();
		const FVerseBotIntent I = VerseBotTactics::Tick(EState::StalkForFinisher, Ctx, Mem, Rng);
		TestEqual(TEXT("stalk crouches"), I.Stance, EVerseStance::Crouch);
		TestTrue(TEXT("stalk walks"), I.bWalk);
		TestTrue(TEXT("finisher press in range"), I.bMelee);
		S.World.bFinisherReady = false;
		TestFalse(TEXT("no press when the ability cannot activate"), VerseBotTactics::Tick(EState::StalkForFinisher, S.Build(), Mem, Rng).bMelee);
	}
	// DeployBulwark: one GadgetA press at the spot; Breach: GadgetB at the plant point, then wait.
	{
		FScene S(TEXT("elite"));
		S.Self.GadgetCharges[0] = 1;
		FVerseBotTacticsMemory Mem;
		FVerseRng Rng(5);
		FVerseBotTacticsContext& Ctx = S.Build();
		Ctx.bBulwarkReady = true;
		const FVerseBotIntent First = VerseBotTactics::Tick(EState::DeployBulwark, Ctx, Mem, Rng);
		const FVerseBotIntent Second = VerseBotTactics::Tick(EState::DeployBulwark, Ctx, Mem, Rng);
		TestTrue(TEXT("Bulwark deployed once"), First.bGadgetA && !Second.bGadgetA);
	}
	{
		FScene S(TEXT("elite"));
		S.Cache.Breach.bFound = true;
		S.Cache.Breach.PieceIndex = 2;
		S.Cache.Breach.PlantPoint = S.Self.Location;
		S.Cache.Breach.WaitPoint = S.Self.Location + FVector(0.f, -400.f, 0.f);
		FVerseBotTacticsMemory Mem;
		FVerseRng Rng(6);
		FVerseBotTacticsContext& Ctx = S.Build();
		VerseBotTactics::Enter(EState::Breach, Ctx, Mem, Rng);
		const FVerseBotIntent Plant = VerseBotTactics::Tick(EState::Breach, Ctx, Mem, Rng);
		TestTrue(TEXT("plants at the plant point"), Plant.bGadgetB && Mem.bBreachPlanted);
		Ctx.Query.NowS = 1.f;
		const FVerseBotIntent Wait = VerseBotTactics::Tick(EState::Breach, Ctx, Mem, Rng);
		TestTrue(TEXT("steps back to the wait point"), Wait.bHasMoveTarget && Wait.MoveTarget.Equals(S.Cache.Breach.WaitPoint));
	}
	return true;
}

// A8.4 (world-free part, BG12 health): time to contact against a hider, stuck events.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotHealthTest, "Verse.Bot.Tactics.Health", VERSE_BOT_TEST_FLAGS)

bool FVerseBotHealthTest::RunTest(const FString& Parameters)
{
	TArray<float> Contacts;
	int32 Stuck = 0;
	float Minutes = 0.f;
	TArray<double> Us;
	for (int32 Seed = 1; Seed <= 6; ++Seed)
	{
		FFakeVerseDuelSim::FConfig Cfg;
		Cfg.Seed = 500 + Seed;
		Cfg.Model = FFakeVerseDuelSim::EModel::Hider;
		FFakeVerseDuelSim Sim(TEXT("hard"), Cfg);
		Sim.bMeasure = true;
		Sim.Run(10 * 60 * 60);
		Contacts.Append(Sim.TimeToContactS);
		Stuck += Sim.Brain.GetStuckEvents();
		Minutes += 10.f;
		Us.Append(Sim.ThinkUs);
	}
	const float Median = VerseBotTestProof::Median(Contacts);
	const float StuckPer10 = float(Stuck) / (Minutes / 10.f);
	const double P99 = VerseBotTestProof::Percentile(Us, 99.0);
	VerseBotTestProof::Write(TEXT("8.3"), TEXT("bg12_health.json"),
		FString::Printf(TEXT("{\n  \"gate\": \"BG12\",\n  \"opponent\": \"hider\",\n  \"tier\": \"hard\",\n  \"contacts\": %d,\n  \"timeToContactS_median\": %.2f,\n  \"stuckEventsPer10Min\": %.2f,\n  \"thinkUsP99\": %.2f\n}\n"),
			Contacts.Num(), Median, StuckPer10, P99));
	AddInfo(FString::Printf(TEXT("hider: %d contacts, median %.1f s, stuck %.2f per 10 min, p99 %.1f us"), Contacts.Num(), Median, StuckPer10, P99));
	TestTrue(TEXT("the hider is found"), Contacts.Num() >= 6);
	TestTrue(TEXT("timeToContactS median <= 25 s"), Median <= 25.f);
	TestTrue(TEXT("stuck events <= 1 per 10 min"), StuckPer10 <= 1.f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

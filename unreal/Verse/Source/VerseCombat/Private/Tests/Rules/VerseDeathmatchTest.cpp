#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Events/VerseEventHub.h"
#include "Math/RandomStream.h"
#include "Misc/FileHelper.h"
#include "Rules/VersePlayerState.h"
#include "Rules/VerseRulesetConfig.h"
#include "Rules/VerseRuleset_Deathmatch.h"
#include "Rules/VerseSpawnPoint.h"
#include "Rules/VerseSpawnSelection.h"
#include "Tests/Rules/VerseRulesTestWorld.h"

// Verse.Combat.Deathmatch.*: the deathmatch invariants D1-D4 of contracts/combat-state.md 9.4
// and the per-set summaries (work-packages.md A11.3, A11.8). The world is scripted through
// FVerseRulesHost: no pawns, the hangar arena spawns (docs/verse/unreal/arena.md), a few
// occluder boxes for sight and a stand-in path metric.

namespace VerseDeathmatchTest
{
	constexpr float TickS = 1.f / 60.f;

	// Spawn floors of the hangar arena (arena.md, plan metres x 100).
	const FVector SpawnFloors[] = {
		{2600, 500, 0}, {4800, 800, 0}, {7080, 600, 0}, {7100, 4000, 0}, {4850, 4300, 0},
		{3150, 4050, 300}, {2620, 1800, 600}, {5000, 3050, 300}, {5750, 3720, 600},
	};

	// Shuttle hull, booth, the three container rows: enough to make sight matter.
	const FBox Occluders[] = {
		FBox(FVector(4600, 1500, 0), FVector(5400, 3300, 300)),
		FBox(FVector(2500, 3200, 0), FVector(3800, 4400, 930)),
		FBox(FVector(6060, 1100, 0), FVector(6300, 3700, 300)),
		FBox(FVector(6660, 500, 0), FVector(6900, 3900, 300)),
		FBox(FVector(7260, 500, 0), FVector(7500, 4100, 300)),
	};

	bool LineClear(const FVector& A, const FVector& B)
	{
		for (const FBox& Box : Occluders)
		{
			if (FMath::LineBoxIntersection(Box, A, B, B - A))
			{
				return false;
			}
		}
		return true;
	}

	// A path metric that differs from the Euclidean fallback: grid walking plus stairs.
	float PathLength(const FVector& A, const FVector& B)
	{
		return float(FMath::Abs(A.X - B.X) + FMath::Abs(A.Y - B.Y) + 2.0 * FMath::Abs(A.Z - B.Z));
	}

	bool Inside(const FVector& P)
	{
		for (const FBox& Box : Occluders)
		{
			if (Box.IsInsideOrOn(P))
			{
				return true;
			}
		}
		return false;
	}

	/** The scripted duel: two players, positions, a clock and a log of everything that happened. */
	struct FDuel
	{
		FVerseRulesTestWorld TestWorld;
		UVerseRuleset_Deathmatch* Rules = nullptr;
		UVerseRulesetConfig* Config = nullptr;
		AVersePlayerState* Person = nullptr;
		AVersePlayerState* Bot = nullptr;
		TArray<AVerseSpawnPoint*> Spawns;
		TMap<const AVersePlayerState*, FVector> Feet;
		TMap<const AVersePlayerState*, float> LastRespawn;
		TArray<FVerseSetSummary> Summaries;
		float Time = 0.f;
		int32 Respawns = 0;
		TFunction<void(AVersePlayerState*, AVerseSpawnPoint*)> OnRespawn;

		FDuel()
		{
			UWorld* World = TestWorld.World;
			Person = TestWorld.Spawn<AVersePlayerState>();
			Person->SetPlayerId(1);
			Bot = TestWorld.Spawn<AVersePlayerState>();
			Bot->SetPlayerId(2);
			Bot->BotTier = TEXT("normal");
			for (const FVector& Floor : SpawnFloors)
			{
				Spawns.Add(TestWorld.Spawn<AVerseSpawnPoint>(Floor));
			}
			Config = NewObject<UVerseRulesetConfig>(World);
			Rules = NewObject<UVerseRuleset_Deathmatch>(World);
			Rules->bAutoTick = false;

			FVerseRulesHost Host;
			Host.ServerTime = [this]() { return Time; };
			Host.UnixNow = [this]() { return 1.8e9 + Time; };
			Host.Players = [this]() { return TArray<AVersePlayerState*>{Person, Bot}; };
			Host.SpawnPoints = [this]() { return Spawns; };
			Host.SpawnFloor = [](const AVerseSpawnPoint* S) { return S->GetActorLocation(); };
			Host.EyePoint = [this](const AVersePlayerState* P, FVector& Out) {
				const FVector* F = Feet.Find(P);
				if (!F)
				{
					return false;
				}
				Out = *F + FVector(0, 0, 165);
				return true;
			};
			Host.LineClear = &LineClear;
			Host.PathLength = &PathLength;
			Host.PawnNear = [this](const FVector& Floor, float Radius, const AVersePlayerState* Ignore) {
				for (const TPair<const AVersePlayerState*, FVector>& Pair : Feet)
				{
					if (Pair.Key != Ignore && FVector::Dist(Pair.Value, Floor) <= Radius)
					{
						return true;
					}
				}
				return false;
			};
			Host.Respawn = [this](AVersePlayerState* P, AVerseSpawnPoint* S) {
				if (OnRespawn)
				{
					OnRespawn(P, S);
				}
				Feet.Add(P, S ? S->GetActorLocation() : FVector::ZeroVector);
				LastRespawn.Add(P, Time);
				++Respawns;
			};
			Rules->SetHost(Host);
			Rules->Init(nullptr, Config);
			if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
			{
				Hub->OnSetEnded.AddLambda([this](const FVerseSetSummary& S) { Summaries.Add(S); });
			}
		}

		UVerseEventHub* Hub() const { return UVerseEventHub::Get(TestWorld.World); }

		void Kill(AVersePlayerState* Victim, AVersePlayerState* Killer, EVerseDamageSource Cause = EVerseDamageSource::Bolt,
			EVerseHitZone Zone = EVerseHitZone::UpperTorso)
		{
			FVerseDeathEvent E;
			E.VictimId = Victim->GetPlayerId();
			E.KillerId = Killer ? Killer->GetPlayerId() : 0;
			E.Cause = Cause;
			E.LastZone = Zone;
			E.WeaponId = TEXT("graveline");
			E.ServerTime = Time;
			Feet.Remove(Victim);
			Rules->OnKill(E);
		}

		void Fire(AVersePlayerState* Shooter)
		{
			FVerseFireEvent E;
			E.ShooterId = Shooter->GetPlayerId();
			E.WeaponId = TEXT("graveline");
			E.ServerTime = Time;
			Hub()->OnFire.Broadcast(E);
		}

		void TickOnce()
		{
			Time += TickS;
			Rules->Advance(Time);
		}

		AVersePlayerState* Other(AVersePlayerState* P) const { return P == Person ? Bot : Person; }
	};
}

using namespace VerseDeathmatchTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeathmatchSpawnSelectionTest, "Verse.Combat.Deathmatch.SpawnSelection",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseDeathmatchSpawnSelectionTest::RunTest(const FString& Parameters)
{
	auto Make = [](std::initializer_list<FVector> Floors) {
		TArray<FVerseSpawnCandidate> Out;
		for (const FVector& F : Floors)
		{
			FVerseSpawnCandidate& C = Out.AddDefaulted_GetRef();
			C.Floor = F;
		}
		return Out;
	};
	const FVector Eye(4000, 2000, 165);

	// Out of sight wins over a farther candidate in sight; the farthest hidden one wins.
	{
		TArray<FVerseSpawnCandidate> C = Make({{2600, 500, 0}, {7100, 4000, 0}, {6500, 2000, 0}, {9000, 2000, 0}});
		// Wall at x 8000 hides candidate 3 (and only it), wall around the shuttle hides 2.
		auto Clear = [](const FVector& A, const FVector& B) {
			const FBox Walls[] = {FBox(FVector(8000, 0, 0), FVector(8100, 6000, 900)), FBox(FVector(6000, 1500, 0), FVector(6200, 2500, 900))};
			for (const FBox& W : Walls)
			{
				if (FMath::LineBoxIntersection(W, A, B, B - A))
				{
					return false;
				}
			}
			return true;
		};
		auto Euclid = [](const FVector& A, const FVector& B) { return float(FVector::Dist(A, B)); };
		const FVerseSpawnChoice Choice = VerseSpawnSelection::Choose(C, Eye, Clear, Euclid, 7, 0);
		TestEqual(TEXT("farthest hidden spawn chosen"), Choice.Index, 3);
		TestFalse(TEXT("chosen spawn is hidden"), Choice.bVisible);
		TestEqual(TEXT("two hidden candidates in the pool"), Choice.Pool.Num(), 2);
	}
	// Everything visible: the farthest of all.
	{
		TArray<FVerseSpawnCandidate> C = Make({{2600, 500, 0}, {7100, 4000, 0}, {4100, 2100, 0}});
		auto Clear = [](const FVector&, const FVector&) { return true; };
		auto Euclid = [](const FVector& A, const FVector& B) { return float(FVector::Dist(A, B)); };
		const FVerseSpawnChoice Choice = VerseSpawnSelection::Choose(C, Eye, Clear, Euclid, 7, 0);
		TestEqual(TEXT("all visible: farthest"), Choice.Index, 1);
		TestTrue(TEXT("all visible: flagged"), Choice.bVisible);
	}
	// Blocked candidates are skipped unless every one is blocked.
	{
		TArray<FVerseSpawnCandidate> C = Make({{2600, 500, 0}, {7100, 4000, 0}});
		C[1].bBlocked = true;
		auto Clear = [](const FVector&, const FVector&) { return false; };
		auto Euclid = [](const FVector& A, const FVector& B) { return float(FVector::Dist(A, B)); };
		TestEqual(TEXT("blocked candidate skipped"), VerseSpawnSelection::Choose(C, Eye, Clear, Euclid, 7, 0).Index, 0);
		C[0].bBlocked = true;
		TestEqual(TEXT("all blocked: falls back to all"), VerseSpawnSelection::Choose(C, Eye, Clear, Euclid, 7, 0).Index, 1);
	}
	// No path: the Euclidean distance stands in (9.2).
	{
		TArray<FVerseSpawnCandidate> C = Make({{2600, 500, 0}, {4100, 2100, 0}});
		auto Clear = [](const FVector&, const FVector&) { return false; };
		auto NoPath = [](const FVector&, const FVector&) { return -1.f; };
		const FVerseSpawnChoice Choice = VerseSpawnSelection::Choose(C, Eye, Clear, NoPath, 7, 0);
		TestEqual(TEXT("no path: euclidean"), Choice.Index, 0);
		TestTrue(TEXT("no path: distance is euclidean"), FMath::IsNearlyEqual(Choice.DistanceCm, float(FVector::Dist(Eye, C[0].Floor)), 0.5f));
	}
	// Ties within 1 m go to VerseRng(seed, deaths): deterministic, and both sides get picked.
	{
		TArray<FVerseSpawnCandidate> C = Make({{3000, 2000, 0}, {5000, 2000, 0}});
		const FVector Mid(4000, 2000, 165);
		auto Clear = [](const FVector&, const FVector&) { return false; };
		auto Euclid = [](const FVector& A, const FVector& B) { return float(FVector::Dist(A, B)); };
		TSet<int32> Seen;
		for (uint64 Deaths = 0; Deaths < 32; ++Deaths)
		{
			const int32 A = VerseSpawnSelection::Choose(C, Mid, Clear, Euclid, 99, Deaths).Index;
			const int32 B = VerseSpawnSelection::Choose(C, Mid, Clear, Euclid, 99, Deaths).Index;
			TestEqual(TEXT("tie break is deterministic"), A, B);
			Seen.Add(A);
		}
		TestEqual(TEXT("tie break uses both candidates"), Seen.Num(), 2);
		// No opponent (first spawn): every candidate ties.
		const FVerseSpawnChoice First = VerseSpawnSelection::Choose(C, TOptional<FVector>(), Clear, Euclid, 99, 0);
		TestTrue(TEXT("no opponent: a valid pick"), First.Index == 0 || First.Index == 1);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeathmatchInvariantsTest, "Verse.Combat.Deathmatch.Invariants",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// D1-D4 over 200 seeded deaths (A11.3).
bool FVerseDeathmatchInvariantsTest::RunTest(const FString& Parameters)
{
	FDuel Duel;
	FRandomStream Rng(1111);
	int32 D1Fail = 0, D2Fail = 0, D3Fail = 0, D4Fail = 0, Checked = 0, HiddenAvailable = 0;
	TMap<const AVersePlayerState*, float> DiedAt;
	TMap<const AVersePlayerState*, float> FireAt;  // planned first shot after a respawn, or 1e9

	Duel.OnRespawn = [&](AVersePlayerState* P, AVerseSpawnPoint* S) {
		if (const float* Died = DiedAt.Find(P))
		{
			const float Wait = Duel.Time - *Died;
			if (Wait < 3.f - KINDA_SMALL_NUMBER || Wait > 3.f + TickS + KINDA_SMALL_NUMBER)
			{
				++D1Fail;
			}
			DiedAt.Remove(P);
		}
		// D2 and D3, recomputed from the scripted world, not read back from the rules.
		const FVector* OppFeet = Duel.Feet.Find(Duel.Other(P));
		if (OppFeet && S)
		{
			const FVector Eye = *OppFeet + FVector(0, 0, 165);
			auto Hidden = [&](const FVector& Floor) {
				for (const float H : {0.3f, 1.0f, 1.65f})
				{
					if (LineClear(Eye, Floor + FVector(0, 0, H * 100)))
					{
						return false;
					}
				}
				return true;
			};
			float BestHidden = -1.f;
			for (const AVerseSpawnPoint* C : Duel.Spawns)
			{
				const FVector F = C->GetActorLocation();
				if (FVector::Dist(F, *OppFeet) > VerseSpawnSelection::BlockRadiusCm && Hidden(F))
				{
					BestHidden = FMath::Max(BestHidden, PathLength(Eye, F));
				}
			}
			++Checked;
			if (BestHidden >= 0.f)
			{
				++HiddenAvailable;
				if (!Hidden(S->GetActorLocation()))
				{
					++D2Fail;
				}
				else if (PathLength(Eye, S->GetActorLocation()) < BestHidden - VerseSpawnSelection::TieCm)
				{
					++D3Fail;
				}
			}
		}
		FireAt.Add(P, Rng.FRand() < 0.6f ? Duel.Time + Rng.FRandRange(0.1f, 1.9f) : 1e9f);
	};

	Duel.Rules->OnMatchStart();
	int32 Deaths = 0;
	float NextDeath = 2.f;
	float NextWander = 1.f;
	while (Deaths < 200 && Duel.Time < 3600.f)
	{
		Duel.TickOnce();
		for (AVersePlayerState* P : {Duel.Person, Duel.Bot})
		{
			if (!Duel.Rules->IsAlive(P))
			{
				continue;
			}
			const float* Planned = FireAt.Find(P);
			const bool bProtected = Duel.Rules->IsSpawnProtected(P);
			const float SinceSpawn = Duel.Time - Duel.LastRespawn.FindRef(P);
			// D4: no damage while protected; reload and ADS keep it.
			if (bProtected)
			{
				D4Fail += Duel.Rules->CanDamagePlayer(P, EVerseDamageSource::Bolt) ? 1 : 0;
				Duel.Rules->OnPlayerAction(P, EVersePlayerAction::Reload);
				Duel.Rules->OnPlayerAction(P, EVersePlayerAction::Ads);
				D4Fail += Duel.Rules->IsSpawnProtected(P) ? 0 : 1;
				if (SinceSpawn > 2.f + TickS + KINDA_SMALL_NUMBER)
				{
					++D4Fail;  // protection outlived SpawnProtectionMax
				}
			}
			if (Planned && Duel.Time >= *Planned)
			{
				const bool bWasProtected = Duel.Rules->IsSpawnProtected(P);
				Duel.Fire(P);
				FireAt.Add(P, 1e9f);
				// The first own shot ends protection on that tick.
				if (bWasProtected && (Duel.Rules->IsSpawnProtected(P) || !Duel.Rules->CanDamagePlayer(P, EVerseDamageSource::Bolt)))
				{
					++D4Fail;
				}
			}
		}
		if (Duel.Time >= NextWander)
		{
			NextWander += 1.f;
			for (AVersePlayerState* P : {Duel.Person, Duel.Bot})
			{
				if (Duel.Feet.Contains(P))
				{
					FVector Pos;
					do
					{
						Pos = FVector(Rng.FRandRange(2600, 7400), Rng.FRandRange(500, 4300), 0);
					} while (Inside(Pos + FVector(0, 0, 50)));
					Duel.Feet.Add(P, Pos);
				}
			}
		}
		if (Duel.Time >= NextDeath && Duel.Rules->IsAlive(Duel.Person) && Duel.Rules->IsAlive(Duel.Bot))
		{
			AVersePlayerState* Victim = Rng.FRand() < 0.5f ? Duel.Person : Duel.Bot;
			DiedAt.Add(Victim, Duel.Time);
			Duel.Kill(Victim, Duel.Other(Victim));
			++Deaths;
			NextDeath = Duel.Time + Rng.FRandRange(0.5f, 4.f);
		}
	}
	// Let the last respawn happen.
	for (int32 i = 0; i < 240; ++i)
	{
		Duel.TickOnce();
	}

	TestEqual(TEXT("200 seeded deaths"), Deaths, 200);
	TestEqual(TEXT("D1: every respawn at 3.0 s within one tick"), D1Fail, 0);
	TestEqual(TEXT("D2: out of sight whenever a candidate is"), D2Fail, 0);
	TestEqual(TEXT("D3: farthest by path among the hidden"), D3Fail, 0);
	TestEqual(TEXT("D4: protected takes no damage, first shot ends it on that tick"), D4Fail, 0);
	TestTrue(TEXT("the sight rule was exercised"), HiddenAvailable > 100 && Checked >= 200);
	TestEqual(TEXT("2 first spawns + one per death"), Duel.Respawns, 202);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeathmatchSetSummaryTest, "Verse.Combat.Deathmatch.SetSummary",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// 50 scripted sets: one FVerseSetSummary each with the kills of the server log; leaving
// mid-set raises exactly one Unfinished summary (A11.8).
bool FVerseDeathmatchSetSummaryTest::RunTest(const FString& Parameters)
{
	FDuel Duel;
	FRandomStream Rng(5050);
	Duel.Rules->OnMatchStart();
	struct FLog
	{
		int32 Person = 0, Bot = 0, PersonHead = 0, BotFinishers = 0;
	};
	TArray<FLog> Logs;
	Logs.AddDefaulted();
	int32 Kills = 0;
	while (Duel.Summaries.Num() < 50 && Kills < 2000)
	{
		// Both must be alive for a kill: wait out the respawn.
		while (!(Duel.Rules->IsAlive(Duel.Person) && Duel.Rules->IsAlive(Duel.Bot)))
		{
			Duel.TickOnce();
		}
		for (int32 i = 0; i < 30; ++i)
		{
			Duel.TickOnce();
		}
		const bool bPersonKills = Rng.FRand() < 0.45f;
		const bool bHead = Rng.FRand() < 0.3f;
		const bool bFinisher = !bHead && Rng.FRand() < 0.1f;
		FLog& L = Logs.Last();
		if (bPersonKills)
		{
			L.Person += 1;
			L.PersonHead += bHead ? 1 : 0;
			Duel.Kill(Duel.Bot, Duel.Person, EVerseDamageSource::Bolt, bHead ? EVerseHitZone::Head : EVerseHitZone::UpperTorso);
		}
		else
		{
			L.Bot += 1;
			L.BotFinishers += bFinisher ? 1 : 0;
			Duel.Kill(Duel.Person, Duel.Bot, bFinisher ? EVerseDamageSource::Finisher : EVerseDamageSource::Bolt);
		}
		++Kills;
		if (Duel.Summaries.Num() == Logs.Num())
		{
			Logs.AddDefaulted();
		}
	}
	TestEqual(TEXT("50 finished sets"), Duel.Summaries.Num(), 50);
	TSet<FString> Ids;
	for (int32 i = 0; i < FMath::Min(50, Duel.Summaries.Num()); ++i)
	{
		const FVerseSetSummary& S = Duel.Summaries[i];
		const FLog& L = Logs[i];
		const bool bWon = L.Person == 10;
		TestEqual(FString::Printf(TEXT("set %d index"), i), S.SetIndex, i + 1);
		TestEqual(FString::Printf(TEXT("set %d person kills"), i), S.Person.Kills, L.Person);
		TestEqual(FString::Printf(TEXT("set %d opponent kills"), i), S.Opponent.Kills, L.Bot);
		TestEqual(FString::Printf(TEXT("set %d person deaths"), i), S.Person.Deaths, L.Bot);
		TestEqual(FString::Printf(TEXT("set %d headshots"), i), S.Person.Headshots, L.PersonHead);
		TestEqual(FString::Printf(TEXT("set %d finishers"), i), S.Opponent.Finishers, L.BotFinishers);
		TestTrue(FString::Printf(TEXT("set %d first to 10"), i), FMath::Max(L.Person, L.Bot) == 10);
		TestTrue(FString::Printf(TEXT("set %d outcome"), i), S.Outcome == (bWon ? EVerseSetOutcome::Won : EVerseSetOutcome::Lost));
		TestTrue(TEXT("ruleset id"), S.RulesetId == FName(TEXT("endless/1")));
		TestTrue(TEXT("bot tier"), S.BotTier == FName(TEXT("normal")));
		TestTrue(TEXT("person line is the person"), !S.Person.bIsBot && S.Opponent.bIsBot);
		TestTrue(TEXT("set time counted"), S.MatchTimeS > 0.f && S.EndedAtUnix >= S.StartedAtUnix);
		Ids.Add(S.MatchId);
	}
	TestEqual(TEXT("match ids unique"), Ids.Num(), Duel.Summaries.Num());

	// Leave mid-set: a couple of kills into set 51, then the arena closes.
	while (!(Duel.Rules->IsAlive(Duel.Person) && Duel.Rules->IsAlive(Duel.Bot)))
	{
		Duel.TickOnce();
	}
	Duel.Kill(Duel.Bot, Duel.Person);
	FVerseArenaSwitchEvent Off;
	Off.bArenaOn = false;
	Off.Deck = TEXT("hangar");
	Duel.Hub()->OnArenaSwitch.Broadcast(Off);
	Duel.Hub()->OnArenaSwitch.Broadcast(Off);  // a second close changes nothing
	Duel.Rules->EndMatch();
	TestEqual(TEXT("exactly one unfinished summary"), Duel.Summaries.Num(), 51);
	if (Duel.Summaries.Num() == 51)
	{
		const FVerseSetSummary& U = Duel.Summaries.Last();
		TestTrue(TEXT("unfinished outcome"), U.Outcome == EVerseSetOutcome::Unfinished);
		TestEqual(TEXT("unfinished set index"), U.SetIndex, 51);
		TestEqual(TEXT("unfinished kills"), U.Person.Kills, 1);
	}
	TestFalse(TEXT("match stopped"), Duel.Rules->IsMatchRunning());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeathmatchRulesJsonTest, "Verse.Combat.Deathmatch.RulesJson",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseDeathmatchRulesJsonTest::RunTest(const FString& Parameters)
{
	FString Text;
	const FString Path = UVerseRulesetConfig::RulesFilePath(TEXT("deathmatch"));
	if (!TestTrue(TEXT("Data/rules/deathmatch.json exists"), FFileHelper::LoadFileToString(Text, *Path)))
	{
		return false;
	}
	UVerseRulesetConfig* Config = NewObject<UVerseRulesetConfig>();
	FString Error;
	TestTrue(FString::Printf(TEXT("parses (%s)"), *Error), Config->ApplyJson(Text, Error));
	TestEqual(TEXT("respawn 3.0 s"), Config->RespawnDelay, 3.f);
	TestEqual(TEXT("protection 2.0 s"), Config->SpawnProtectionMax, 2.f);
	TestEqual(TEXT("first to 10"), Config->KillsPerSet, 10);
	TestEqual(TEXT("no regeneration"), Config->HealthRegenPerSec, 0.f);
	TestEqual(TEXT("armor inert"), Config->MaxArmor, 0.f);
	TestTrue(TEXT("deathmatch class"), Config->RulesetClass == UVerseRuleset_Deathmatch::StaticClass());

	UVerseRulesetConfig* Bad = NewObject<UVerseRulesetConfig>();
	TestFalse(TEXT("unknown key refused"), Bad->ApplyJson(TEXT("{\"schema\":\"verse.rules/1\",\"respawn\":3}"), Error));
	TestFalse(TEXT("wrong schema refused"), Bad->ApplyJson(TEXT("{\"schema\":\"verse.rules/2\"}"), Error));
	TestFalse(TEXT("bad slot refused"), Bad->ApplyJson(TEXT("{\"schema\":\"verse.rules/1\",\"loadout\":{\"Sidearm\":\"/Game/Verse/X.X\"}}"), Error));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

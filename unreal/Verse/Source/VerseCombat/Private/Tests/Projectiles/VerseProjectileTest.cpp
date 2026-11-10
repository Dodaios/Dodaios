#include "Components/BoxComponent.h"
#include "Damage/VerseDamageMath.h"
#include "Destruction/VersePenetrationTable.h"
#include "Events/VerseEventHub.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Tests/Projectiles/Fakes/VerseFakeDestruction.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Projectile.*: bolt flight (A2.5), the trace order and penetration loop of
// combat-state.md 5 and 6, the latency advance, and the cost gate (A2.8).

namespace VerseProjectileTest
{
	FVerseFireEvent Fire(const FVector& Origin, const FVector& Dir, uint16 Counter = 1, FName Weapon = TEXT("graveline"))
	{
		FVerseFireEvent E;
		E.WeaponId = Weapon;
		E.ShotCounter = Counter;
		E.Origin = Origin;
		E.Direction = Dir;
		return E;
	}

	/** Manager on a test world with a manual clock. */
	struct FRig
	{
		VerseWp02Test::FTestWorld World;
		UVerseProjectileManager* Manager = nullptr;
		UVerseLagCompSubsystem* Lag = nullptr;
		double Now = 100.0;
		TArray<FVerseBoltResult> Results;

		FRig()
		{
			Manager = UVerseProjectileManager::Get(World.World);
			Lag = UVerseLagCompSubsystem::Get(World.World);
			Manager->SetManualStepping(true);
			Manager->SetClock([this]() { return Now; });
			Manager->OnBoltResolved.AddLambda([this](const FVerseBoltResult& R) { Results.Add(R); });
		}

		void Step(int32 Ticks = 1)
		{
			for (int32 I = 0; I < Ticks; ++I)
			{
				Now += VerseWp02Test::Tick;
				Lag->Record(Now);
				Manager->StepAll(VerseWp02Test::Tick, Now);
			}
		}
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseProjectileFlight, "Verse.Combat.Projectile.Flight", VERSE_WP02_TEST_FLAGS)
bool FVerseProjectileFlight::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		VerseProjectileTest::FRig Rig;
		const FVector Origin(0, 0, 5000); // far above the empty world
		const FVector Dir = FVector(1, 0.2, 0).GetSafeNormal();
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir, 1, W->WeaponId), *W, 0.f, nullptr);
		TestEqual(TEXT("one bolt in flight"), Rig.Manager->NumActive(), 1);
		const double Start = Rig.Now;
		double MaxDropErr = 0.0;
		int32 Ticks = 0;
		double SpeedErr = 0.0;
		while (Rig.Manager->NumActive() > 0 && Ticks < 10000)
		{
			const FVector Before = Rig.Manager->GetBolts()[0].Position;
			Rig.Step();
			++Ticks;
			if (Rig.Manager->NumActive() > 0)
			{
				const FVerseBolt& B = Rig.Manager->GetBolts()[0];
				const double Speed = FVector::Dist(Before, B.Position) / VerseWp02Test::Tick;
				SpeedErr = FMath::Max(SpeedErr, FMath::Abs(Speed - W->ProjectileSpeed * 100.0) / (W->ProjectileSpeed * 100.0));
				// Drop: the bullet follows the gravity arc (0.5 g t^2 below the firing line).
				const double T = Rig.Now - Start;
				const FVector Want = UVerseProjectileManager::BallisticPosition(Origin, Dir, W->ProjectileSpeed * 100.0, T);
				MaxDropErr = FMath::Max(MaxDropErr, FVector::Dist(B.Position, Want));
			}
		}
		const FString Id = W->WeaponId.ToString();
		TestTrue(FString::Printf(TEXT("%s: speed within 0.5 %% (%.4f %%)"), *Id, SpeedErr * 100.0), SpeedErr <= 0.005);
		TestTrue(FString::Printf(TEXT("%s: on the gravity arc within 0.5 cm (%.4f cm)"), *Id, MaxDropErr), MaxDropErr < 0.5);
		if (TestEqual(TEXT("resolved once"), Rig.Results.Num(), 1))
		{
			const double Range = W->MaxRange * 100.0;
			TestEqual(TEXT("expired as a miss"), Rig.Results[0].Result, EVerseShotResult::Miss);
			TestTrue(FString::Printf(TEXT("%s: despawn at MaxRange + at most 5 m (%.1f cm)"), *Id, Rig.Results[0].Travelled),
				Rig.Results[0].Travelled >= Range - 1.0 && Rig.Results[0].Travelled <= Range + 500.0);
			const double FlightS = Rig.Now - Start;
			TestTrue(TEXT("flight time = range / speed (+1 tick)"), FMath::Abs(FlightS - W->MaxRange / W->ProjectileSpeed) <= VerseWp02Test::Tick + 1e-6);
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseProjectileLatencyAdvance, "Verse.Combat.Projectile.LatencyAdvance", VERSE_WP02_TEST_FLAGS)
bool FVerseProjectileLatencyAdvance::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	// A rifle round covers its whole range in range / speed (about 170 ms): a latency advance past
	// that ends the round as a miss on the spot, so the advance is checked inside the flight time.
	const double FlightS = G->MaxRange / G->ProjectileSpeed;
	for (const float Latency : {0.f, 0.03f, 0.06f, 0.12f, float(FlightS) - 0.01f})
	{
		VerseProjectileTest::FRig Rig;
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(FVector(0, 0, 5000), FVector(1, 0, 0)), *G, Latency, nullptr);
		if (!TestEqual(TEXT("bolt alive"), Rig.Manager->NumActive(), 1))
		{
			continue;
		}
		const double Want = Latency * G->ProjectileSpeed * 100.0;
		TestEqual(FString::Printf(TEXT("latency %.2f s advances %.0f cm"), Latency, Want), Rig.Manager->GetBolts()[0].Travelled, Want, 0.5);
	}
	// Beyond the flight time (and the 250 ms cap) the round is gone at once.
	for (const float Latency : {float(FlightS) + 0.02f, 0.25f, 0.3f, 2.f})
	{
		VerseProjectileTest::FRig Rig;
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(FVector(0, 0, 5000), FVector(1, 0, 0)), *G, Latency, nullptr);
		TestEqual(FString::Printf(TEXT("latency %.2f s: the round has used up its range"), Latency), Rig.Manager->NumActive(), 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseProjectileTraceOrder, "Verse.Combat.Projectile.TraceOrder", VERSE_WP02_TEST_FLAGS)
bool FVerseProjectileTraceOrder::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseWeaponDefinition* T = VerseWp02Test::Weapon(*this, TEXT("tallow"));
	if (!G || !T)
	{
		return false;
	}
	const FVector Origin(0, 0, 5000);
	const FVector Dir(1, 0, 0);
	auto Wall = [](uint16 Index, EVersePenetrationMaterial M, double X, double ThicknessCm)
	{
		FFakeVersePiece P;
		P.PieceIndex = Index;
		P.Material = M;
		P.Bounds = FBox(FVector(X, -200, 4800), FVector(X + ThicknessCm, 200, 5200));
		return P;
	};
	const TArray<FVersePenetrationRow> Rows = UVersePenetrationTable::MakeContractRows();
	const float Container = Rows[int32(EVersePenetrationMaterial::ContainerWall)].RefThicknessCm;

	// A target behind two container walls: the rifle passes both and keeps 0.75 x 0.75.
	{
		VerseProjectileTest::FRig Rig;
		FFakeVersePenetrationQuery QueryStorage;
		FFakeVersePenetrationQuery* Query = &QueryStorage;
		FFakeVersePieceDamage PieceDamage;
		Query->Pieces = {Wall(1, EVersePenetrationMaterial::ContainerWall, 520, Container),
			Wall(2, EVersePenetrationMaterial::ContainerWall, 910, Container)};
		Rig.Manager->SetPenetrationQuery(Query);
		Rig.Manager->SetPieceDamage(&PieceDamage);
		APawn* Target = VerseWp02Test::SpawnTarget(Rig.World.World, FVector(1500, 0, 5000 - 135), 1000.f);
		Rig.Lag->RegisterTarget(Target, [Target](FTransform& Root, TArray<FVerseHitCapsule>& Out)
		{
			Root = Target->GetActorTransform();
			VerseWp02Test::HumanCapsules(Target->GetActorLocation(), Out);
		});
		TArray<FVersePenetrationEvent> Pens;
		TArray<FVerseHitEvent> Hits;
		UVerseEventHub::Get(Rig.World.World)->OnPenetration.AddLambda([&Pens](const FVersePenetrationEvent& E) { Pens.Add(E); });
		UVerseEventHub::Get(Rig.World.World)->OnHit.AddLambda([&Hits](const FVerseHitEvent& E) { Hits.Add(E); });
		Rig.Lag->Record(Rig.Now);
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir), *G, 0.f, nullptr);
		Rig.Step(10);
		TestEqual(TEXT("two passes"), Pens.Num(), 2);
		TestEqual(TEXT("piece damage on each wall"), PieceDamage.Calls.Num(), 2);
		if (PieceDamage.Calls.Num() == 2)
		{
			TestEqual(TEXT("first piece first"), int32(PieceDamage.Calls[0].PieceIndex), 1);
			TestEqual(TEXT("bolt cause"), PieceDamage.Calls[0].Cause, EVerseFractureCause::Bolt);
			TestEqual(TEXT("piece hp per hit"), PieceDamage.Calls[0].Amount, G->PieceDamage);
		}
		if (TestEqual(TEXT("body hit behind the walls"), Hits.Num(), 1))
		{
			TestEqual(TEXT("upper torso"), Hits[0].Zone, EVerseHitZone::UpperTorso);
			TestEqual(TEXT("damage x 0.5625"), Hits[0].Damage, G->BaseDamage * 0.5625f, 1e-3f);
			TestEqual(TEXT("two penetrations on the hit"), int32(Hits[0].PenetrationCount), 2);
		}
		if (Pens.Num() == 2)
		{
			// One 14.7 m chord carries the traced thickness through float precision: 0.01 of 100 power.
			TestEqual(TEXT("power 100 - 25 - 25"), Pens[1].PowerAfter, 50.f, 1e-2f);
		}
		TestTrue(TEXT("HitBody result"), Rig.Results.Num() == 1 && Rig.Results[0].Result == EVerseShotResult::HitBody);
	}

	// The pistol (50, two passes): 50 - 25 - 25 passes two container walls and stops at the third; concrete stops everything.
	{
		VerseProjectileTest::FRig Rig;
		FFakeVersePenetrationQuery QueryStorage;
		FFakeVersePenetrationQuery* Query = &QueryStorage;
		FFakeVersePieceDamage PieceDamage;
		// Slightly under the reference thickness, so 25 + 25 fits the 50 exactly without float edge.
		const double Thin = Container * 0.95;
		Query->Pieces = {Wall(1, EVersePenetrationMaterial::ContainerWall, 310, Thin), Wall(2, EVersePenetrationMaterial::ContainerWall, 410, Thin),
			Wall(3, EVersePenetrationMaterial::ContainerWall, 460, Thin)};
		Rig.Manager->SetPenetrationQuery(Query);
		Rig.Manager->SetPieceDamage(&PieceDamage);
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir), *T, 0.f, nullptr);
		Rig.Step(5);
		TestTrue(TEXT("pistol stops at a piece"), Rig.Results.Num() == 1 && Rig.Results[0].Result == EVerseShotResult::HitPiece);
		TestEqual(TEXT("pistol: piece damage on all three walls"), PieceDamage.Calls.Num(), 3);
	}
	{
		VerseProjectileTest::FRig Rig;
		FFakeVersePenetrationQuery QueryStorage;
		FFakeVersePenetrationQuery* Query = &QueryStorage;
		FFakeVersePieceDamage PieceDamage;
		Query->Pieces = {Wall(7, EVersePenetrationMaterial::Concrete, 300, 30.0)};
		Rig.Manager->SetPenetrationQuery(Query);
		Rig.Manager->SetPieceDamage(&PieceDamage);
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir), *G, 0.f, nullptr);
		Rig.Step(5);
		TestTrue(TEXT("concrete stops the rifle"), Rig.Results.Num() == 1 && Rig.Results[0].Result == EVerseShotResult::HitPiece);
	}

	// MaxPenetrations cap: four thin sheets, the rifle (3 passes) stops at the 4th.
	{
		VerseProjectileTest::FRig Rig;
		FFakeVersePenetrationQuery QueryStorage;
		FFakeVersePenetrationQuery* Query = &QueryStorage;
		FFakeVersePieceDamage PieceDamage;
		for (uint16 I = 0; I < 4; ++I)
		{
			Query->Pieces.Add(Wall(10 + I, EVersePenetrationMaterial::Glass, 300 + 50 * I, 2.4));
		}
		Rig.Manager->SetPenetrationQuery(Query);
		Rig.Manager->SetPieceDamage(&PieceDamage);
		TArray<FVersePenetrationEvent> Pens;
		UVerseEventHub::Get(Rig.World.World)->OnPenetration.AddLambda([&Pens](const FVersePenetrationEvent& E) { Pens.Add(E); });
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir), *G, 0.f, nullptr);
		Rig.Step(5);
		TestEqual(TEXT("three passes, the fourth stops"), Pens.Num(), 3);
		TestTrue(TEXT("stopped on the 4th"), Rig.Results.Num() == 1 && Rig.Results[0].Result == EVerseShotResult::HitPiece);
	}

	// A body in front of a wall is hit first; a body behind concrete is never hit.
	{
		VerseProjectileTest::FRig Rig;
		FFakeVersePenetrationQuery QueryStorage;
		FFakeVersePenetrationQuery* Query = &QueryStorage;
		Query->Pieces = {Wall(1, EVersePenetrationMaterial::Concrete, 800, 30.0)};
		FFakeVersePieceDamage PieceDamage;
		Rig.Manager->SetPenetrationQuery(Query);
		Rig.Manager->SetPieceDamage(&PieceDamage);
		APawn* Front = VerseWp02Test::SpawnTarget(Rig.World.World, FVector(400, 0, 5000 - 135), 1000.f);
		APawn* Behind = VerseWp02Test::SpawnTarget(Rig.World.World, FVector(1200, 0, 5000 - 135), 1000.f);
		for (APawn* P : {Front, Behind})
		{
			Rig.Lag->RegisterTarget(P, [P](FTransform& Root, TArray<FVerseHitCapsule>& Out)
			{
				Root = P->GetActorTransform();
				VerseWp02Test::HumanCapsules(P->GetActorLocation(), Out);
			});
		}
		Rig.Lag->Record(Rig.Now);
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir, 1), *G, 0.f, nullptr);
		Rig.Step(3);
		TestTrue(TEXT("front body hit first"), Rig.Results.Num() == 1 && Rig.Results[0].HitActor.Get() == Front);
		TestEqual(TEXT("the wall behind is untouched"), PieceDamage.Calls.Num(), 0);

		Rig.Lag->UnregisterTarget(Front);
		Rig.Results.Reset();
		Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(Origin, Dir, 2), *G, 0.f, nullptr);
		Rig.Step(5);
		TestTrue(TEXT("concrete hides the body behind"), Rig.Results.Num() == 1 && Rig.Results[0].Result == EVerseShotResult::HitPiece);
		TestEqual(TEXT("behind untouched"), VerseWp02Test::HealthOf(Behind), 1000.f);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseProjectileCost, "Verse.Combat.Projectile.Cost", VERSE_WP02_TEST_FLAGS)
bool FVerseProjectileCost::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	VerseProjectileTest::FRig Rig;
	for (int32 I = 0; I < 2; ++I)
	{
		APawn* P = VerseWp02Test::SpawnTarget(Rig.World.World, FVector(2000, 3000 * (I ? 1 : -1), 0), 1000.f);
		Rig.Lag->RegisterTarget(P, [P](FTransform& Root, TArray<FVerseHitCapsule>& Out)
		{
			Root = P->GetActorTransform();
			VerseWp02Test::HumanCapsules(P->GetActorLocation(), Out);
		});
	}
	// Real work for the traces: two container walls across the whole fan (every bolt passes both),
	// 30 pieces beside it, and 24 bolt-blocking pillars in the world off the fan.
	FFakeVersePenetrationQuery Query;
	FFakeVersePieceDamage PieceDamage;
	const double WallCm = UVersePenetrationTable::MakeContractRows()[int32(EVersePenetrationMaterial::ContainerWall)].RefThicknessCm;
	for (int32 I = 0; I < 2; ++I)
	{
		FFakeVersePiece Wall;
		Wall.PieceIndex = uint16(I + 1);
		Wall.Material = EVersePenetrationMaterial::ContainerWall;
		Wall.Bounds = FBox(FVector(1500 + 400 * I, -2000, 0), FVector(1500 + 400 * I + WallCm, 2000, 400));
		Query.Pieces.Add(Wall);
	}
	for (int32 I = 0; I < 30; ++I)
	{
		FFakeVersePiece Side;
		Side.PieceIndex = uint16(100 + I);
		Side.Material = EVersePenetrationMaterial::Concrete;
		const double X = 500.0 * I;
		Side.Bounds = FBox(FVector(X, -9000, 0), FVector(X + 30, -8800, 400));
		Query.Pieces.Add(Side);
	}
	Rig.Manager->SetPenetrationQuery(&Query);
	Rig.Manager->SetPieceDamage(&PieceDamage);
	for (int32 I = 0; I < 24; ++I)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AActor* Pillar = Rig.World.World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
		UBoxComponent* Box = NewObject<UBoxComponent>(Pillar, TEXT("Box"));
		Box->SetBoxExtent(FVector(50, 50, 300));
		Box->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
		Box->SetCollisionResponseToAllChannels(ECR_Block);
		Pillar->SetRootComponent(Box);
		Box->RegisterComponent();
		Pillar->SetActorLocation(FVector(1000.0 + 500.0 * I, (I % 2) ? 9500.0 : -9500.0, 300.0));
	}
	Rig.World.TickFrames(2);
	Rig.Lag->Record(Rig.Now);

	// Twenty waves of 64 rounds, 6 measured ticks each (a 150 m round at 880 m/s lives about 10 ticks), after two warm-up ticks.
	TArray<double> Ms;
	int32 MinAlive = 64;
	for (int32 Wave = 0; Wave < 20; ++Wave)
	{
		Rig.Manager->Clear();
		for (int32 I = 0; I < 64; ++I)
		{
			const FVector Dir = FRotator(0.0, -30.0 + I * 0.95, 0.0).Vector();
			Rig.Manager->SpawnBoltFrom(VerseProjectileTest::Fire(FVector(0, 0, 150), Dir, uint16(Wave * 64 + I + 1)), *G, 0.f, nullptr);
		}
		Rig.Step(2);
		for (int32 I = 0; I < 6; ++I)
		{
			Rig.Step();
			Ms.Add(Rig.Manager->GetLastStepSeconds() * 1000.0);
			MinAlive = FMath::Min(MinAlive, Rig.Manager->NumActive());
		}
	}
	TestEqual(TEXT("64 in flight through every measured tick"), MinAlive, 64);
	TestTrue(TEXT("bolts passed the walls"), PieceDamage.Calls.Num() >= 64 * 20);
	Ms.Sort();
	const double Median = Ms[Ms.Num() / 2];
	const double P99 = Ms[FMath::Min(Ms.Num() - 1, int32(FMath::CeilToInt(Ms.Num() * 0.99)) - 1)];
	const double Max = Ms.Last();
	AddInfo(FString::Printf(TEXT("projectile manager, 64 bolts, %d ticks: median %.4f ms, p99 %.4f ms, max %.4f ms per tick"), Ms.Num(), Median, P99, Max));
	TestTrue(FString::Printf(TEXT("A2.8: p99 %.4f ms <= 0.2 ms"), P99), P99 <= 0.2);

	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	Proof->SetNumberField(TEXT("bolts"), 64);
	Proof->SetNumberField(TEXT("median_ms"), Median);
	Proof->SetNumberField(TEXT("p99_ms"), P99);
	Proof->SetNumberField(TEXT("max_ms"), Max);
	Proof->SetNumberField(TEXT("ticks"), Ms.Num());
	VerseWp02Test::WriteProof(TEXT("2.7"), TEXT("projectile_cost.json"), Proof);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

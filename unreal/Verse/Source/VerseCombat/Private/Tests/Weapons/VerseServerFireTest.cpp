#include "Components/BoxComponent.h"
#include "Events/VerseEventHub.h"
#include "Gadgets/VerseBulwark.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Misc/AutomationTest.h"
#include "Projectiles/VerseBoltPresentation.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Tests/Projectiles/Fakes/VerseFakeDestruction.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "Weapons/VerseRecoil.h"
#include "Weapons/VerseSpread.h"
#include "Weapons/VerseWeaponComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// The server half of the fire path against a client that lies (combat-state.md 4.4, 11.2):
// Verse.Combat.FireRate.ServerClock (forged timestamps), Verse.Combat.Spread.ServerDirection
// (no spread, steered shots), Verse.Combat.Recoil.ClientServerMatch (R5: the server's own recoil
// and spread for the owner's requests), and Verse.Combat.Presentation.ServerStops (bolts end at
// pieces and Bulwarks on the server's own viewer).

namespace VerseServerFireTest
{
	struct FShooterRig
	{
		VerseWp02Test::FTestWorld World;
		UVerseProjectileManager* Manager = nullptr;
		APawn* Pawn = nullptr;
		UVerseWeaponComponent* Weapon = nullptr;
		UVerseInventoryComponent* Inv = nullptr;
		uint16 Counter = 0;

		explicit FShooterRig(const UVerseWeaponDefinition* Primary)
		{
			Manager = UVerseProjectileManager::Get(World.World);
			Manager->SetManualStepping(true);
			Pawn = VerseWp02Test::SpawnTarget(World.World, FVector::ZeroVector);
			Inv = NewObject<UVerseInventoryComponent>(Pawn, TEXT("Inventory"));
			Inv->RegisterComponent();
			TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*> Loadout;
			Loadout.Add(EVerseLoadoutSlot::Primary, Primary);
			Inv->GiveLoadout(Loadout, World.World->GetTimeSeconds());
			Weapon = NewObject<UVerseWeaponComponent>(Pawn, TEXT("Weapon"));
			Weapon->RegisterComponent();
			Weapon->SetMatchSeed(1234);
			World.TickFrames(60); // past the equip time
		}

		float Now() const
		{
			return World.World->GetTimeSeconds();
		}

		uint32 SeedOf(uint16 C) const
		{
			return FVerseSpread::ShotSeed(uint32(Weapon->GetShooterId()), C, Weapon->MatchSeed);
		}

		/** A request with a correct seed for the next counter. */
		EVerseShotResult Send(float ClientTime, const FVector& Dir)
		{
			const uint16 C = ++Counter;
			return Weapon->HandleServerFire(C, SeedOf(C), Pawn->GetPawnViewLocation(), Dir, ClientTime);
		}
	};

	double AngleDeg(const FVector& A, const FVector& B)
	{
		return FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(A.GetSafeNormal(), B.GetSafeNormal()), -1.0, 1.0)));
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFireRateServerClock, "Verse.Combat.FireRate.ServerClock", VERSE_WP02_TEST_FLAGS)
bool FVerseFireRateServerClock::RunTest(const FString&)
{
	using namespace VerseServerFireTest;
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	const float Interval = G->FireInterval();

	// A backlog of correctly spaced past timestamps, all sent in one server frame: the server clock
	// lets the burst allowance through and no more.
	{
		FShooterRig Rig(G);
		Rig.Weapon->bServerValidates = false; // cadence only
		const float Now = Rig.Now();
		int32 Accepted = 0;
		for (int32 K = 0; K < 5; ++K)
		{
			Accepted += Rig.Send(Now - 0.45f + K * Interval, FVector(1, 0, 0)) != EVerseShotResult::Rejected ? 1 : 0;
		}
		TestEqual(TEXT("bunched past timestamps: only the burst allowance"), float(Accepted), UVerseWeaponComponent::ServerBurstShots);
	}

	// Timestamps outside the window around the server clock are rejected.
	{
		FShooterRig Rig(G);
		Rig.Weapon->bServerValidates = false;
		TestEqual(TEXT("1 s in the future rejected"), Rig.Send(Rig.Now() + 1.f, FVector(1, 0, 0)), EVerseShotResult::Rejected);
		TestEqual(TEXT("2 s in the past rejected"), Rig.Send(Rig.Now() - 2.f, FVector(1, 0, 0)), EVerseShotResult::Rejected);
		TestTrue(TEXT("now accepted"), Rig.Send(Rig.Now(), FVector(1, 0, 0)) != EVerseShotResult::Rejected);
	}

	// A client whose timestamps run four times faster than real time: over two seconds of server
	// time the accepted rate stays at the weapon's RPM.
	{
		FShooterRig Rig(G);
		Rig.Weapon->bServerValidates = false;
		float Forged = Rig.Now();
		int32 Accepted = 0;
		const int32 Ticks = 120;
		const float Start = Rig.Now();
		for (int32 T = 0; T < Ticks; ++T)
		{
			Rig.World.TickFrames(1);
			for (int32 K = 0; K < 3; ++K)
			{
				Forged += Interval;
				const uint16 C = ++Rig.Counter;
				// Refill the magazine so ammo never limits the count.
				if (const FVerseWeaponSlotState* S = Rig.Inv->GetActiveState())
				{
					FVerseMagazine::InitFull(*const_cast<FVerseWeaponSlotState*>(S), *G);
				}
				Accepted += Rig.Weapon->HandleServerFire(C, Rig.SeedOf(C), Rig.Pawn->GetPawnViewLocation(), FVector(1, 0, 0), Forged) !=
					EVerseShotResult::Rejected ? 1 : 0;
			}
		}
		const float Elapsed = Rig.Now() - Start;
		const int32 Allowed = FMath::CeilToInt(Elapsed / Interval + UVerseWeaponComponent::ServerBurstShots) + 1;
		AddInfo(FString::Printf(TEXT("forged 4x clock: %d accepted in %.2f s (RPM %.0f, allowed %d)"), Accepted, Elapsed, 60.f * Accepted / Elapsed, Allowed));
		TestTrue(FString::Printf(TEXT("accepted %d <= %d"), Accepted, Allowed), Accepted <= Allowed);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSpreadServerDirection, "Verse.Combat.Spread.ServerDirection", VERSE_WP02_TEST_FLAGS)
bool FVerseSpreadServerDirection::RunTest(const FString&)
{
	using namespace VerseServerFireTest;
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	FShooterRig Rig(G);
	const FVector Forward(1, 0, 0);
	FVerseSpreadInput Hip; // standing, hip fire, still

	// What the server derives for the next request at time T.
	auto Derived = [&](float T, uint16 C, float& OutSigma, int32& OutIndex)
	{
		FVerseSpread Spread = Rig.Weapon->GetServerSpread();
		FVerseRecoilState Recoil = Rig.Weapon->GetServerRecoil();
		Spread.DecayUntilShot(*G, T);
		Recoil.BeginShot(*G, T);
		OutSigma = Spread.SigmaFor(*G, Hip, T);
		OutIndex = Recoil.ShotIndex;
		return FVerseSpread::ShotDirection(Forward, OutSigma, Rig.SeedOf(C), OutIndex);
	};

	int32 ExactAccepted = 0;
	int32 SteeredRejected = 0;
	int32 TightRejected = 0;
	bool bSteerChecked = false;
	for (int32 Shot = 0; Shot < 28 && (TightRejected == 0 || !bSteerChecked); ++Shot)
	{
		Rig.World.TickFrames(FMath::CeilToInt(G->FireInterval() / VerseWp02Test::Tick));
		const float T = Rig.Now();
		const uint16 C = Rig.Counter + 1;
		float Sigma = 0.f;
		int32 Index = 0;
		const FVector Exact = Derived(T, C, Sigma, Index);
		const double Offset = AngleDeg(Exact, Forward);
		if (Shot >= 3 && !bSteerChecked)
		{
			// Steered 2.5 deg off the derived direction, still inside the old sigma + 1.5 cone.
			const FVector Steered = FRotator(0.0, 2.5, 0.0).RotateVector(Exact);
			const bool bInsideOldCone = AngleDeg(Steered, Forward) <= FVerseSpread::RestingSigma(*G, Hip, G->BloomMax) + 1.5;
			const EVerseShotResult R = Rig.Send(T, Steered);
			SteeredRejected += R == EVerseShotResult::Rejected ? 1 : 0;
			bSteerChecked = bInsideOldCone;
			continue;
		}
		if (Offset > 2.0 && Sigma > 2.0)
		{
			// No spread at all: a direction no honest client can produce for this seed.
			TightRejected += Rig.Send(T, Forward) == EVerseShotResult::Rejected ? 1 : 0;
			continue;
		}
		ExactAccepted += Rig.Send(T, Exact) != EVerseShotResult::Rejected ? 1 : 0;
	}
	TestTrue(TEXT("derived directions are accepted"), ExactAccepted >= 3);
	TestTrue(TEXT("a steered shot inside the old cone was tried"), bSteerChecked);
	TestTrue(TEXT("steered shots are rejected"), SteeredRejected >= 1);
	TestEqual(TEXT("a zero-spread shot under bloom is rejected"), TightRejected, 1);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseRecoilClientServerMatch, "Verse.Combat.Recoil.ClientServerMatch", VERSE_WP02_TEST_FLAGS)
bool FVerseRecoilClientServerMatch::RunTest(const FString&)
{
	using namespace VerseServerFireTest;
	// R5: the owner's StepFire computes its kicks; the server path the request goes through computes
	// its own from the request alone (time, counter, seed) and the server's stance and ADS.
	for (const TCHAR* Id : {TEXT("graveline"), TEXT("tallow")})
	{
		const UVerseWeaponDefinition* W = VerseWp02Test::Weapon(*this, Id);
		if (!W)
		{
			return false;
		}
		FShooterRig Rig(W);
		int32 Compared = 0;
		double MaxKickErr = 0.0;
		double MaxSigmaErr = 0.0;
		int32 IndexMismatch = 0;
		for (int32 Tick = 0; Tick < 60 * 6; ++Tick)
		{
			Rig.World.TickFrames(1);
			const float Now = Rig.Now();
			Rig.Weapon->StepAds(FMath::Fmod(Now, 1.3f) < 0.6f, VerseWp02Test::Tick);
			if (const FVerseWeaponSlotState* S = Rig.Inv->GetActiveState())
			{
				if (FVerseMagazine::RoundsReady(*S, *W) == 0)
				{
					FVerseMagazine::InitFull(*const_cast<FVerseWeaponSlotState*>(S), *W);
				}
			}
			FVerseFireContext Ctx;
			Ctx.Now = Now;
			Ctx.Dt = VerseWp02Test::Tick;
			// Semi needs fresh presses; sprays with pauses for the auto rifle.
			Ctx.bTriggerDown = W->FireMode == EVerseFireMode::Semi ? (Tick % 8) < 4 : FMath::Fmod(Now, 1.0f) < 0.7f;
			Ctx.Eye = Rig.Pawn->GetPawnViewLocation();
			TArray<FVerseShotOut> Shots;
			Rig.Weapon->StepFire(Ctx, &Shots);
			if (Shots.Num() > 0)
			{
				const FVerseShotOut& Last = Shots.Last();
				MaxKickErr = FMath::Max(MaxKickErr, double((Last.Kick - Rig.Weapon->GetLastServerKick()).Size()));
				MaxSigmaErr = FMath::Max(MaxSigmaErr, double(FMath::Abs(Last.Sigma - Rig.Weapon->GetLastServerSigma())));
				IndexMismatch += Last.ShotIndex != Rig.Weapon->GetLastServerShotIndex() ? 1 : 0;
				++Compared;
			}
		}
		AddInfo(FString::Printf(TEXT("%s: %d shots, max kick diff %.6f deg, max sigma diff %.4f deg"), Id, Compared, MaxKickErr, MaxSigmaErr));
		TestTrue(FString::Printf(TEXT("%s: shots compared"), Id), Compared >= 20);
		TestTrue(FString::Printf(TEXT("%s: server kicks equal the client's"), Id), MaxKickErr < 1e-4);
		TestEqual(FString::Printf(TEXT("%s: shot index matches"), Id), IndexMismatch, 0);
		// Both sides decay bloom up to the shot's own time: the same sigma.
		TestTrue(FString::Printf(TEXT("%s: sigma equals the client's"), Id), MaxSigmaErr <= 1e-4);
		TestTrue(FString::Printf(TEXT("%s: server spray index equals the client's"), Id),
			Rig.Weapon->GetServerRecoil().ShotIndex == Rig.Weapon->GetRecoil().ShotIndex);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePresentationServerStops, "Verse.Combat.Presentation.ServerStops", VERSE_WP02_TEST_FLAGS)
bool FVersePresentationServerStops::RunTest(const FString&)
{
	using namespace VerseServerFireTest;
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseGadgetDefinition* Def = VerseWp02Test::Gadget(*this, TEXT("bulwark"));
	if (!G || !Def)
	{
		return false;
	}
	// The host of a match against bots is the server and a viewer: its own bolts must end where the
	// server resolves them, at a world hit, a piece or a Bulwark (standalone takes the same authority
	// path as a listen server: not a dedicated server, authority, a local viewer).
	enum class EStop : uint8 { World, Piece, Bulwark };
	for (const EStop Stop : {EStop::World, EStop::Piece, EStop::Bulwark})
	{
		FShooterRig Rig(G);
		UVerseBoltPresentation* P = UVerseBoltPresentation::Get(Rig.World.World);
		if (!TestNotNull(TEXT("presentation on the host"), P))
		{
			return false;
		}
		P->LocalPlayerIdOverride = Rig.Weapon->GetShooterId();
		TArray<FVerseHitEvent> Impacts;
		UVerseEventHub::Get(Rig.World.World)->OnHit.AddLambda([&Impacts](const FVerseHitEvent& E)
		{
			if (E.VictimId == -1)
			{
				Impacts.Add(E);
			}
		});

		FFakeVersePenetrationQuery Query;
		FFakeVersePieceDamage PieceDamage;
		AActor* Blocker = nullptr;
		const double StopX = 900.0; // beyond the latency advance of the first tick (at most 5 m)
		const FVector Eye = Rig.Pawn->GetPawnViewLocation();
		if (Stop == EStop::Piece)
		{
			FFakeVersePiece Wall;
			Wall.PieceIndex = 3;
			Wall.Material = EVersePenetrationMaterial::Concrete;
			Wall.Bounds = FBox(FVector(StopX, -400, Eye.Z - 400), FVector(StopX + 30, 400, Eye.Z + 400));
			Query.Pieces.Add(Wall);
			Rig.Manager->SetPenetrationQuery(&Query);
			Rig.Manager->SetPieceDamage(&PieceDamage);
		}
		else if (Stop == EStop::Bulwark)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AVerseBulwark* B = Rig.World.World->SpawnActor<AVerseBulwark>(AVerseBulwark::StaticClass(), FVector(StopX, 0, Eye.Z - 100),
				FRotator(0, 180, 0), Params);
			B->InitBulwark(*Def, nullptr, Rig.Now());
			Blocker = B;
		}
		else
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			Blocker = Rig.World.World->SpawnActor<AActor>(AActor::StaticClass(), FTransform::Identity, Params);
			UBoxComponent* Box = NewObject<UBoxComponent>(Blocker, TEXT("Box"));
			Box->SetBoxExtent(FVector(10, 400, 400));
			Box->SetCollisionEnabled(ECollisionEnabled::QueryOnly);
			Box->SetCollisionResponseToAllChannels(ECR_Block);
			Blocker->SetRootComponent(Box);
			Box->RegisterComponent();
			Blocker->SetActorLocation(FVector(StopX + 10, 0, Eye.Z));
		}
		Rig.World.TickFrames(2);

		FVerseFireContext Ctx;
		Ctx.Now = Rig.Now();
		Ctx.Dt = VerseWp02Test::Tick;
		Ctx.bTriggerDown = true;
		Ctx.Eye = Eye;
		TArray<FVerseShotOut> Shots;
		Rig.Weapon->StepFire(Ctx, &Shots);
		const TCHAR* Name = Stop == EStop::World ? TEXT("world") : (Stop == EStop::Piece ? TEXT("piece") : TEXT("Bulwark"));
		if (!TestEqual(FString::Printf(TEXT("%s: one shot"), Name), Shots.Num(), 1))
		{
			continue;
		}
		TestEqual(FString::Printf(TEXT("%s: own bolt drawn on the host"), Name), P->NumOwn(), 1);
		Rig.Manager->StepAll(VerseWp02Test::Tick, Rig.Now() + VerseWp02Test::Tick);
		TestEqual(FString::Printf(TEXT("%s: bolt resolved on the server"), Name), Rig.Manager->NumActive(), 0);
		TestEqual(FString::Printf(TEXT("%s: one cosmetic impact on the host's hub"), Name), Impacts.Num(), 1);
		TestEqual(FString::Printf(TEXT("%s: the drawn bolt ends there"), Name), P->NumOwn(), 0);
		TestEqual(FString::Printf(TEXT("%s: impact placed"), Name), P->GetImpacts().Num(), 1);
		if (Impacts.Num() == 1)
		{
			TestTrue(FString::Printf(TEXT("%s: impact at the stop (x %.1f)"), Name, Impacts[0].ImpactWorld.X),
				FMath::Abs(Impacts[0].ImpactWorld.X - StopX) < 40.0);
			TestEqual(FString::Printf(TEXT("%s: impact carries the shot"), Name), int32(Impacts[0].ShotCounter), int32(Shots[0].Counter));
		}
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

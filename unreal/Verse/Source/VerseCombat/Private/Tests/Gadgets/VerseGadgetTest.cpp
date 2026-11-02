#include "Components/BoxComponent.h"
#include "Events/VerseEventHub.h"
#include "Gadgets/VerseBreachCharge.h"
#include "Gadgets/VerseBulwark.h"
#include "Gadgets/VerseGadgetAbilities.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Misc/AutomationTest.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Tests/Projectiles/Fakes/VerseFakeDestruction.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "VerseCollision.h"
#include "VerseGameplayTags.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Gadget.*: the Bulwark (GD1, A2.10), the breach charge (GD2-GD4, A2.11) and the gadget
// component behind the two GAS abilities (WP02.12, WP02.13).

namespace VerseGadgetTest
{
	UVerseGadgetDefinition* Copy(const UVerseGadgetDefinition* Src)
	{
		UVerseGadgetDefinition* D = DuplicateObject<UVerseGadgetDefinition>(Src, GetTransientPackage());
		D->AddToRoot();
		return D;
	}

	AVerseBulwark* SpawnBulwark(UWorld* World, const UVerseGadgetDefinition& Def, const FVector& Floor, AActor* Owner)
	{
		FActorSpawnParameters P;
		P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		AVerseBulwark* B = World->SpawnActor<AVerseBulwark>(AVerseBulwark::StaticClass(), Floor, FRotator(0, 180, 0), P);
		B->InitBulwark(Def, Owner, World->GetTimeSeconds());
		return B;
	}

	struct FScene
	{
		VerseWp02Test::FTestWorld World;
		UVerseProjectileManager* Manager = nullptr;
		UVerseLagCompSubsystem* Lag = nullptr;
		TArray<FVerseBoltResult> Results;

		FScene()
		{
			Manager = UVerseProjectileManager::Get(World.World);
			Lag = UVerseLagCompSubsystem::Get(World.World);
			Manager->SetManualStepping(true);
			Manager->OnBoltResolved.AddLambda([this](const FVerseBoltResult& R) { Results.Add(R); });
		}

		void Step(int32 Ticks)
		{
			for (int32 I = 0; I < Ticks; ++I)
			{
				World.TickFrames(1);
				Manager->StepAll(VerseWp02Test::Tick, World.World->GetTimeSeconds());
			}
		}

		APawn* TargetBehind(const FVector& Root)
		{
			APawn* T = VerseWp02Test::SpawnTarget(World.World, Root, 1e6f);
			Lag->RegisterTarget(T, [T](FTransform& R, TArray<FVerseHitCapsule>& Out)
			{
				R = T->GetActorTransform();
				VerseWp02Test::HumanCapsules(T->GetActorLocation(), Out);
			});
			return T;
		}

		void FireAt(const UVerseWeaponDefinition& W, const FVector& From, const FVector& To, uint16 Counter)
		{
			FVerseFireEvent E;
			E.WeaponId = W.WeaponId;
			E.ShotCounter = Counter;
			E.Origin = From;
			E.Direction = (To - From).GetSafeNormal();
			Manager->SpawnBoltFrom(E, W, 0.f, nullptr);
		}
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGadgetBulwark, "Verse.Combat.Gadget.Bulwark", VERSE_WP02_TEST_FLAGS)
bool FVerseGadgetBulwark::RunTest(const FString&)
{
	const UVerseGadgetDefinition* Def = VerseWp02Test::Gadget(*this, TEXT("bulwark"));
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!Def || !G)
	{
		return false;
	}

	// GD1: 1,000 seeded bolts at an intact Bulwark, 0 pass; 1,000 sight traces, all pass.
	{
		VerseGadgetTest::FScene Scene;
		UVerseGadgetDefinition* Tough = VerseGadgetTest::Copy(Def);
		Tough->MaxHealth = 1e6f; // intact for the whole volley
		AVerseBulwark* B = VerseGadgetTest::SpawnBulwark(Scene.World.World, *Tough, FVector(1000, 0, 0), nullptr);
		APawn* Behind = Scene.TargetBehind(FVector(1400, 0, 0));
		Scene.World.TickFrames(2);
		TArray<FVerseGadgetEvent> Gadgets;
		UVerseEventHub::Get(Scene.World.World)->OnGadget.AddLambda([&Gadgets](const FVerseGadgetEvent& E) { Gadgets.Add(E); });

		FVerseRng Rng(2026);
		int32 Fired = 0;
		for (int32 Volley = 0; Volley < 20; ++Volley)
		{
			for (int32 I = 0; I < 50; ++I)
			{
				const FVector From(0, Rng.Range(-60.0, 60.0), Rng.Range(20.0, 130.0));
				const FVector To(1000, Rng.Range(-85.0, 85.0), Rng.Range(5.0, 135.0));
				Scene.FireAt(*G, From, To, uint16(++Fired));
			}
			Scene.Step(4);
		}
		Scene.Step(10);
		TestEqual(TEXT("1,000 bolts resolved"), Scene.Results.Num(), 1000);
		const int32 Blocked = Scene.Results.FilterByPredicate([](const FVerseBoltResult& R) { return R.Result == EVerseShotResult::Blocked; }).Num();
		TestEqual(TEXT("GD1: every bolt stopped by the field"), Blocked, 1000);
		TestEqual(TEXT("nothing reached the pawn behind"), double(VerseWp02Test::HealthOf(Behind)), 1e6, 1e-3);
		TestTrue(TEXT("field took the damage"), B->GetHealth() < Tough->MaxHealth);

		int32 SightBlocked = 0;
		for (int32 I = 0; I < 1000; ++I)
		{
			const FVector From(0, Rng.Range(-60.0, 60.0), Rng.Range(20.0, 130.0));
			const FVector To(1400, Rng.Range(-85.0, 85.0), Rng.Range(5.0, 135.0));
			FHitResult Hit;
			FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseTestSight), false);
			if (Scene.World.World->LineTraceSingleByChannel(Hit, From, To, VerseCollision::Sight, Params) && Hit.GetActor() == B)
			{
				++SightBlocked;
			}
		}
		TestEqual(TEXT("GD1: every sight trace passes the field"), SightBlocked, 0);
		FHitResult BoltHit;
		TestTrue(TEXT("the field blocks the VerseBolt channel"),
			Scene.World.World->LineTraceSingleByChannel(BoltHit, FVector(0, 0, 70), FVector(1400, 0, 70), VerseCollision::Bolt) && BoltHit.GetActor() == B);
		TestEqual(TEXT("field blocks pawns"), B->Field->GetCollisionResponseToChannel(ECC_Pawn), ECR_Block);
	}

	// It disappears on the tick its health reaches 0; the next bolt goes through.
	{
		VerseGadgetTest::FScene Scene;
		TArray<FVerseGadgetEvent> Gadgets;
		TArray<FVerseNoiseEvent> Noises;
		UVerseEventHub::Get(Scene.World.World)->OnGadget.AddLambda([&Gadgets](const FVerseGadgetEvent& E) { Gadgets.Add(E); });
		UVerseEventHub::Get(Scene.World.World)->OnNoise.AddLambda([&Noises](const FVerseNoiseEvent& E) { Noises.Add(E); });
		AVerseBulwark* B = VerseGadgetTest::SpawnBulwark(Scene.World.World, *Def, FVector(1000, 0, 0), nullptr);
		TestTrue(TEXT("deploy event"), Gadgets.Num() == 1 && Gadgets[0].Kind == EVerseGadgetEventKind::Deploy);
		TestTrue(TEXT("deploy noise"), Noises.Num() == 1 && Noises[0].Noise == VerseTags::Noise_Gadget_BulwarkDeploy);
		APawn* Behind = Scene.TargetBehind(FVector(1400, 0, -100));
		Scene.World.TickFrames(2);
		const int32 BoltsToBreak = FMath::CeilToInt(Def->MaxHealth / G->BaseDamage);
		uint16 Counter = 0;
		for (int32 I = 0; I < BoltsToBreak; ++I)
		{
			TestTrue(FString::Printf(TEXT("intact before bolt %d"), I + 1), B->IsActive());
			Scene.FireAt(*G, FVector(0, 0, 50), FVector(1400, 0, 50), ++Counter);
			Scene.Step(3);
		}
		TestFalse(TEXT("gone on the tick its health reached 0"), B->IsActive());
		TestTrue(TEXT("destroyed event"), Gadgets.Num() >= 2 && Gadgets.Last().Kind == EVerseGadgetEventKind::Destroyed);
		const int32 Before = Scene.Results.Num();
		Scene.FireAt(*G, FVector(0, 0, 50), FVector(1400, 0, 50), ++Counter);
		Scene.Step(8);
		TestTrue(TEXT("the next bolt passes where the field was"),
			Scene.Results.Num() == Before + 1 && Scene.Results.Last().Result == EVerseShotResult::HitBody && Scene.Results.Last().HitActor.Get() == Behind);
	}

	// Lifetime: 25 s after deploy.
	{
		VerseGadgetTest::FScene Scene;
		AVerseBulwark* B = VerseGadgetTest::SpawnBulwark(Scene.World.World, *Def, FVector(1000, 0, 0), nullptr);
		const double Deployed = Scene.World.World->GetTimeSeconds();
		TArray<FVerseGadgetEvent> Gadgets;
		UVerseEventHub::Get(Scene.World.World)->OnGadget.AddLambda([&Gadgets](const FVerseGadgetEvent& E) { Gadgets.Add(E); });
		B->ServerAdvance(Deployed + Def->Lifetime - 0.001);
		TestTrue(TEXT("alive just before its lifetime"), B->IsActive());
		B->ServerAdvance(Deployed + Def->Lifetime);
		TestFalse(TEXT("gone at its lifetime"), B->IsActive());
		TestTrue(TEXT("expired event"), Gadgets.Num() == 1 && Gadgets[0].Kind == EVerseGadgetEventKind::Expired);
	}

	// Owner death removes it.
	{
		VerseGadgetTest::FScene Scene;
		APawn* Owner = VerseWp02Test::SpawnTarget(Scene.World.World, FVector::ZeroVector);
		AVerseBulwark* B = VerseGadgetTest::SpawnBulwark(Scene.World.World, *Def, FVector(1000, 0, 0), Owner);
		FVerseDeathEvent Death;
		Death.VictimId = VerseCombatIds::IdOf(Owner);
		UVerseEventHub::Get(Scene.World.World)->OnDeath.Broadcast(Death);
		TestFalse(TEXT("owner death removes the field"), B->IsActive());
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGadgetBreach, "Verse.Combat.Gadget.Breach", VERSE_WP02_TEST_FLAGS)
bool FVerseGadgetBreach::RunTest(const FString&)
{
	const UVerseGadgetDefinition* Def = VerseWp02Test::Gadget(*this, TEXT("breach_charge"));
	const UVerseGadgetDefinition* BulwarkDef = VerseWp02Test::Gadget(*this, TEXT("bulwark"));
	if (!Def || !BulwarkDef)
	{
		return false;
	}
	auto Spawn = [](UWorld* World, const FVector& At)
	{
		FActorSpawnParameters P;
		P.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		return World->SpawnActor<AVerseBreachCharge>(AVerseBreachCharge::StaticClass(), At, FRotator::ZeroRotator, P);
	};

	// GD2: detonation FuseTime after the plant, within one tick.
	{
		VerseWp02Test::FTestWorld World;
		FFakeVersePieceDamage Pieces;
		AVerseBreachCharge* C = Spawn(World.World, FVector(0, 0, 100));
		C->SetPieceDamage(&Pieces);
		const double Plant = 10.0;
		C->InitCharge(*Def, nullptr, 3, FVector(-1, 0, 0), Plant);
		double T = Plant;
		while (!C->HasDetonated() && T < Plant + 10.0)
		{
			T += VerseWp02Test::Tick;
			C->ServerAdvance(T);
		}
		TestTrue(TEXT("detonated"), C->HasDetonated());
		TestTrue(FString::Printf(TEXT("GD2: %.4f s after the plant, within one tick of %.2f"), C->GetDetonatedTime() - Plant, Def->Lifetime),
			FMath::Abs(C->GetDetonatedTime() - Plant - Def->Lifetime) <= VerseWp02Test::Tick + 1e-6);
	}

	// GD3: pawn damage at 0, 1.5 and 3.0 m: 120, 60, 0 to 1e-4 hp, owner included.
	{
		VerseWp02Test::FTestWorld World;
		const FVector At(0, 0, 100);
		APawn* Owner = VerseWp02Test::SpawnTarget(World.World, At + FVector(0, 150, 0), 1000.f);
		APawn* Zero = VerseWp02Test::SpawnTarget(World.World, At, 1000.f);
		APawn* Mid = VerseWp02Test::SpawnTarget(World.World, At + FVector(-150, 0, 0), 1000.f);
		APawn* Edge = VerseWp02Test::SpawnTarget(World.World, At + FVector(300, 0, 0), 1000.f);
		AVerseBulwark* Near = VerseGadgetTest::SpawnBulwark(World.World, *BulwarkDef, At + FVector(0, -250, -100), nullptr);
		AVerseBulwark* Far = VerseGadgetTest::SpawnBulwark(World.World, *BulwarkDef, At + FVector(0, -600, -100), nullptr);
		FFakeVersePieceDamage Pieces;
		AVerseBreachCharge* C = Spawn(World.World, At);
		C->SetPieceDamage(&Pieces);
		C->InitCharge(*Def, Owner, 7, FVector(0, 0, 1), 0.0);
		C->Detonate(2.5);
		TestEqual(TEXT("GD3: 0 m takes 120"), double(1000.f - VerseWp02Test::HealthOf(Zero)), 120.0, 1e-4);
		TestEqual(TEXT("GD3: 1.5 m takes 60"), double(1000.f - VerseWp02Test::HealthOf(Mid)), 60.0, 1e-4);
		TestEqual(TEXT("GD3: owner at 1.5 m takes 60"), double(1000.f - VerseWp02Test::HealthOf(Owner)), 60.0, 1e-4);
		TestEqual(TEXT("GD3: 3.0 m takes 0"), double(1000.f - VerseWp02Test::HealthOf(Edge)), 0.0, 1e-4);
		TestFalse(TEXT("a Bulwark within 3 m goes"), Near->IsActive());
		TestTrue(TEXT("a Bulwark beyond 3 m stays"), Far->IsActive());
		if (TestEqual(TEXT("one piece damage call"), Pieces.Calls.Num(), 1))
		{
			TestEqual(TEXT("breach cause"), Pieces.Calls[0].Cause, EVerseFractureCause::Breach);
			TestEqual(TEXT("target piece"), int32(Pieces.Calls[0].PieceIndex), 7);
			TestEqual(TEXT("breach radius"), Pieces.Calls[0].BreachRadiusCm, Def->PieceBreachRadius);
		}
	}

	// GD4: 100 of 100 plants drive their target piece to its breach result (the request reaches
	// destruction with Cause = Breach; WP06 maps it to the breach state, its own GD4 half).
	{
		VerseWp02Test::FTestWorld World;
		FFakeVersePieceDamage Pieces;
		for (uint16 I = 0; I < 100; ++I)
		{
			AVerseBreachCharge* C = Spawn(World.World, FVector(I * 1000.0, 0, 100));
			C->SetPieceDamage(&Pieces);
			C->InitCharge(*Def, nullptr, uint16(100 + I), FVector(1, 0, 0), 0.0);
			C->ServerAdvance(Def->Lifetime);
		}
		int32 Good = 0;
		for (int32 I = 0; I < Pieces.Calls.Num(); ++I)
		{
			const FVersePieceDamage& D = Pieces.Calls[I];
			Good += (D.Cause == EVerseFractureCause::Breach && D.PieceIndex == 100 + I && D.BreachRadiusCm == Def->PieceBreachRadius) ? 1 : 0;
		}
		TestEqual(TEXT("GD4: 100 of 100 plants reach their piece"), Good, 100);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGadgetComponent, "Verse.Combat.Gadget.Component", VERSE_WP02_TEST_FLAGS)
bool FVerseGadgetComponent::RunTest(const FString&)
{
	const UVerseGadgetDefinition* BulwarkDef = VerseWp02Test::Gadget(*this, TEXT("bulwark"));
	const UVerseGadgetDefinition* BreachDef = VerseWp02Test::Gadget(*this, TEXT("breach_charge"));
	if (!BulwarkDef || !BreachDef)
	{
		return false;
	}
	VerseWp02Test::FTestWorld World;
	APawn* Pawn = VerseWp02Test::SpawnTarget(World.World, FVector::ZeroVector);
	UVerseGadgetComponent* Gadgets = NewObject<UVerseGadgetComponent>(Pawn, TEXT("Gadgets"));
	UVerseGadgetDefinition* TwoBulwarks = VerseGadgetTest::Copy(BulwarkDef);
	TwoBulwarks->Charges = 2;
	Gadgets->Bulwark = TwoBulwarks;
	Gadgets->BreachCharge = BreachDef;
	Gadgets->PlacementOverride = [](EVerseLoadoutSlot Slot)
	{
		FVerseGadgetPlacement P;
		P.bValid = true;
		P.Location = Slot == EVerseLoadoutSlot::GadgetA ? FVector(150, 0, 0) : FVector(150, 0, 100);
		P.PieceIndex = 4;
		P.Normal = FVector(-1, 0, 0);
		return P;
	};
	FFakeVersePieceDamage Pieces;
	Gadgets->SetPieceDamage(&Pieces);
	Gadgets->RegisterComponent();
	Gadgets->ResetForLife(); // as on spawn; BeginPlay does the same when the pawn begins play
	TestEqual(TEXT("charges per life"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA), 2);
	TestEqual(TEXT("breach charges per life"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB), 2);

	UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Pawn);
	State->BeginSpawnProtection(0.f, 100.f);
	TestTrue(TEXT("deploy starts"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetA, 1.f));
	TestFalse(TEXT("gadget use ends spawn protection"), State->bSpawnProtected);
	TestFalse(TEXT("busy while deploying"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetB, 1.1f));
	Gadgets->ServerAdvance(1.f + TwoBulwarks->UseTime - 0.01f);
	TestNull(TEXT("not yet deployed"), Gadgets->GetActiveBulwark());
	Gadgets->ServerAdvance(1.f + TwoBulwarks->UseTime);
	AVerseBulwark* First = Gadgets->GetActiveBulwark();
	TestNotNull(TEXT("deployed after the use time"), First);
	TestEqual(TEXT("one charge left"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA), 1);

	TestTrue(TEXT("second deploy"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetA, 2.f));
	Gadgets->ServerAdvance(2.f + TwoBulwarks->UseTime);
	TestFalse(TEXT("a second deploy removes the first"), First && First->IsActive());
	TestNotNull(TEXT("the second stands"), Gadgets->GetActiveBulwark());
	TestFalse(TEXT("out of charges"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetA, 3.f));

	// Damage interrupts a plant and keeps the charge.
	TestTrue(TEXT("plant starts"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetB, 4.f));
	FVerseHitEvent Hit;
	Hit.VictimId = VerseCombatIds::IdOf(Pawn);
	Hit.Damage = 10.f;
	UVerseEventHub::Get(World.World)->OnHit.Broadcast(Hit);
	TestFalse(TEXT("damage interrupts"), Gadgets->IsUsing());
	Gadgets->ServerAdvance(10.f);
	TestEqual(TEXT("charge kept"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB), 2);
	TestTrue(TEXT("plant again"), Gadgets->ServerBeginUse(EVerseLoadoutSlot::GadgetB, 11.f));
	Gadgets->ServerAdvance(11.f + BreachDef->UseTime);
	TestEqual(TEXT("one charge planted"), Gadgets->NumPlantedCharges(), 1);
	TestEqual(TEXT("one breach charge left"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB), 1);

	// The Bulwark's charge returns Cooldown after the field is gone.
	AVerseBulwark* Second = Gadgets->GetActiveBulwark();
	if (!TestNotNull(TEXT("second Bulwark still up"), Second))
	{
		return false;
	}
	Second->RemoveBulwark(EVerseGadgetEventKind::Destroyed);
	const float CooldownEnd = Gadgets->GetCooldownEndsAt();
	TestTrue(TEXT("cooldown counts from the field being gone"), CooldownEnd >= TwoBulwarks->Cooldown - 1e-3f);
	Gadgets->ServerAdvance(CooldownEnd - 0.01f);
	TestEqual(TEXT("cooling down"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA), 0);
	Gadgets->ServerAdvance(CooldownEnd);
	TestEqual(TEXT("charge back after the cooldown"), Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA), 1);

	// The abilities are local-predicted.
	const UVerseGA_Bulwark* Ga = GetDefault<UVerseGA_Bulwark>();
	TestEqual(TEXT("Bulwark ability slot"), Ga->GadgetSlot, EVerseLoadoutSlot::GadgetA);
	TestTrue(TEXT("local predicted"), Ga->GetNetExecutionPolicy() == EGameplayAbilityNetExecutionPolicy::LocalPredicted);
	TestEqual(TEXT("breach ability slot"), GetDefault<UVerseGA_BreachCharge>()->GadgetSlot, EVerseLoadoutSlot::GadgetB);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

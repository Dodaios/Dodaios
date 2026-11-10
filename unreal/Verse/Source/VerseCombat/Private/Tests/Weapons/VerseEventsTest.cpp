#include "Damage/VerseCombatStateComponent.h"
#include "Events/VerseEventHub.h"
#include "Gadgets/VerseBreachCharge.h"
#include "Gadgets/VerseBulwark.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Misc/AutomationTest.h"
#include "Projectiles/VerseBoltPresentation.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "VerseGameplayTags.h"
#include "Weapons/VerseCombatTags.h"
#include "Weapons/VerseWeaponComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Events.*: the hub events Fire, Hit, Penetration, Death, Reload and Gadget with the
// transports of combat-state.md 5.1 (WP02.10), and the authority fire path end to end.
// Verse.Combat.Presentation.*: bullets with yellow-white tracers on tracer rounds only,
// gravity drop, casings, removal rules (WP02.11, ballistics decision).

namespace VerseEventsTest
{
	void CheckRpc(FAutomationTestBase& Test, UClass* Class, const TCHAR* Name, EFunctionFlags Kind, bool bReliable)
	{
		const UFunction* F = Class->FindFunctionByName(Name);
		if (!Test.TestNotNull(FString::Printf(TEXT("%s::%s exists"), *Class->GetName(), Name), F))
		{
			return;
		}
		Test.TestTrue(FString::Printf(TEXT("%s is a net function of the right kind"), Name), F->HasAllFunctionFlags(FUNC_Net | Kind));
		Test.TestEqual(FString::Printf(TEXT("%s reliability"), Name), F->HasAnyFunctionFlags(FUNC_NetReliable), bReliable);
	}

	/** A shooter pawn with inventory, weapon and combat state, Graveline and Tallow drawn. */
	APawn* SpawnShooter(UWorld* World, const UVerseWeaponDefinition* Primary, const UVerseWeaponDefinition* Secondary)
	{
		APawn* Pawn = VerseWp02Test::SpawnTarget(World, FVector::ZeroVector);
		UVerseInventoryComponent* Inv = NewObject<UVerseInventoryComponent>(Pawn, TEXT("Inventory"));
		Inv->RegisterComponent();
		TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*> Loadout;
		Loadout.Add(EVerseLoadoutSlot::Primary, Primary);
		Loadout.Add(EVerseLoadoutSlot::Secondary, Secondary);
		Inv->GiveLoadout(Loadout, World->GetTimeSeconds());
		UVerseWeaponComponent* Weapon = NewObject<UVerseWeaponComponent>(Pawn, TEXT("Weapon"));
		Weapon->RegisterComponent();
		Weapon->MatchSeed = 99;
		return Pawn;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseEventsTransports, "Verse.Combat.Events.Transports", VERSE_WP02_TEST_FLAGS)
bool FVerseEventsTransports::RunTest(const FString&)
{
	using namespace VerseEventsTest;
	CheckRpc(*this, UVerseWeaponComponent::StaticClass(), TEXT("ServerFire"), FUNC_NetServer, false);
	CheckRpc(*this, UVerseWeaponComponent::StaticClass(), TEXT("ClientConfirmShot"), FUNC_NetClient, true);
	CheckRpc(*this, UVerseWeaponComponent::StaticClass(), TEXT("MulticastFire"), FUNC_NetMulticast, false);
	CheckRpc(*this, UVerseWeaponComponent::StaticClass(), TEXT("MulticastHitCosmetic"), FUNC_NetMulticast, false);
	CheckRpc(*this, UVerseWeaponComponent::StaticClass(), TEXT("MulticastPenetration"), FUNC_NetMulticast, false);
	CheckRpc(*this, UVerseCombatStateComponent::StaticClass(), TEXT("ClientReceiveHit"), FUNC_NetClient, true);
	CheckRpc(*this, UVerseCombatStateComponent::StaticClass(), TEXT("MulticastDeath"), FUNC_NetMulticast, true);
	CheckRpc(*this, UVerseInventoryComponent::StaticClass(), TEXT("ClientReloadEvent"), FUNC_NetClient, true);
	CheckRpc(*this, UVerseInventoryComponent::StaticClass(), TEXT("ServerReload"), FUNC_NetServer, true);
	CheckRpc(*this, UVerseInventoryComponent::StaticClass(), TEXT("ServerSwitchSlot"), FUNC_NetServer, true);
	CheckRpc(*this, AVerseBulwark::StaticClass(), TEXT("MulticastGadgetEvent"), FUNC_NetMulticast, false);
	CheckRpc(*this, AVerseBreachCharge::StaticClass(), TEXT("MulticastGadgetEvent"), FUNC_NetMulticast, false);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseEventsFirePath, "Verse.Combat.Events.FirePath", VERSE_WP02_TEST_FLAGS)
bool FVerseEventsFirePath::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseWeaponDefinition* T = VerseWp02Test::Weapon(*this, TEXT("tallow"));
	if (!G || !T)
	{
		return false;
	}
	VerseWp02Test::FTestWorld World;
	UVerseEventHub* Hub = UVerseEventHub::Get(World.World);
	UVerseProjectileManager* Manager = UVerseProjectileManager::Get(World.World);
	UVerseLagCompSubsystem* Lag = UVerseLagCompSubsystem::Get(World.World);
	Manager->SetManualStepping(true);

	TArray<FVerseFireEvent> Fires;
	TArray<FVerseHitEvent> Hits;
	TArray<FVerseDeathEvent> Deaths;
	TArray<FVerseNoiseEvent> Noises;
	TArray<FVerseReloadEvent> Reloads;
	Hub->OnFire.AddLambda([&Fires](const FVerseFireEvent& E) { Fires.Add(E); });
	Hub->OnHit.AddLambda([&Hits](const FVerseHitEvent& E) { Hits.Add(E); });
	Hub->OnDeath.AddLambda([&Deaths](const FVerseDeathEvent& E) { Deaths.Add(E); });
	Hub->OnNoise.AddLambda([&Noises](const FVerseNoiseEvent& E) { Noises.Add(E); });
	Hub->OnReload.AddLambda([&Reloads](const FVerseReloadEvent& E) { Reloads.Add(E); });

	APawn* Shooter = VerseEventsTest::SpawnShooter(World.World, G, T);
	APawn* Target = VerseWp02Test::SpawnTarget(World.World, FVector(500, 0, 64 - 135));
	Lag->RegisterTarget(Target, [Target](FTransform& Root, TArray<FVerseHitCapsule>& Out)
	{
		Root = Target->GetActorTransform();
		VerseWp02Test::HumanCapsules(Target->GetActorLocation(), Out);
	});
	UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Shooter);
	UVerseInventoryComponent* Inv = UVerseInventoryComponent::FindOn(Shooter);
	UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Shooter);
	State->BeginSpawnProtection(World.World->GetTimeSeconds(), 2.f);

	Weapon->StepAds(true, 1.f); // full ADS: the spread stays inside the torso at 5 m

	TArray<EVerseShotResult> Answers;
	Weapon->OnShotAnswered.AddLambda([&Answers](uint16, EVerseShotResult R) { Answers.Add(R); });

	// Hold the trigger with the aim on the target's chest until it dies.
	int32 ShotsFired = 0;
	for (int32 I = 0; I < 120 && Deaths.Num() == 0; ++I)
	{
		World.TickFrames(1);
		const float Now = World.World->GetTimeSeconds();
		Lag->Record(Now);
		FVerseFireContext Ctx;
		Ctx.Now = Now;
		Ctx.Dt = VerseWp02Test::Tick;
		Ctx.bTriggerDown = true;
		Ctx.Eye = Shooter->GetPawnViewLocation();
		Ctx.Control = FRotator::ZeroRotator;
		TArray<FVerseShotOut> Shots;
		Weapon->StepFire(Ctx, &Shots);
		ShotsFired += Shots.Num();
		Manager->StepAll(VerseWp02Test::Tick, Now);
	}
	TestFalse(TEXT("the first shot ended spawn protection"), State->bSpawnProtected);
	TestTrue(TEXT("shots were fired"), ShotsFired >= 4);
	TestEqual(TEXT("one fire event per shot"), Fires.Num(), ShotsFired);
	const int32 ShotNoises = Noises.FilterByPredicate([](const FVerseNoiseEvent& N) { return N.Noise == VerseTags::Noise_Shot; }).Num();
	TestEqual(TEXT("one shot noise per shot"), ShotNoises, ShotsFired);
	TestEqual(TEXT("target died once"), Deaths.Num(), 1);
	TestTrue(TEXT("hits raised"), Hits.Num() >= 4);
	TestTrue(TEXT("every shot answered"), Answers.Num() >= Hits.Num());
	TestTrue(TEXT("answers include body hits"), Answers.Contains(EVerseShotResult::HitBody));
	if (Fires.Num() > 0)
	{
		TestEqual(TEXT("fire event carries the weapon"), Fires[0].WeaponId, G->WeaponId);
		TestEqual(TEXT("fire event carries the shooter"), Fires[0].ShooterId, VerseCombatIds::IdOf(Shooter));
	}
	TestEqual(TEXT("rounds spent on the server"), FVerseMagazine::RoundsReady(*Inv->GetActiveState(), *G), G->MagazineSize - ShotsFired);

	// A tampered request is rejected and spends nothing.
	const int32 Before = FVerseMagazine::RoundsReady(*Inv->GetActiveState(), *G);
	const EVerseShotResult Bad = Weapon->HandleServerFire(60000, 1, Shooter->GetPawnViewLocation() + FVector(0, 0, 100), FVector(1, 0, 0),
		World.World->GetTimeSeconds() + 10.f);
	TestEqual(TEXT("bad seed / origin rejected"), Bad, EVerseShotResult::Rejected);
	TestEqual(TEXT("rejected shot spends nothing"), FVerseMagazine::RoundsReady(*Inv->GetActiveState(), *G), Before);

	// Reload: event plus noise.
	const int32 NoisesBefore = Noises.Num();
	TestTrue(TEXT("reload"), Inv->ServerStartReload(World.World->GetTimeSeconds()));
	TestEqual(TEXT("reload event"), Reloads.Num(), 1);
	TestTrue(TEXT("reload noise"), Noises.Num() == NoisesBefore + 1 && Noises.Last().Noise == VerseTags::Noise_Reload);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePresentationBolts, "Verse.Combat.Presentation.BoltColors", VERSE_WP02_TEST_FLAGS)
bool FVersePresentationBolts::RunTest(const FString&)
{
	VerseWp02Test::FTestWorld World;
	UVerseBoltPresentation* P = UVerseBoltPresentation::Get(World.World);
	if (!TestNotNull(TEXT("presentation exists on a viewer world"), P))
	{
		return false;
	}
	double Clock = 10.0;
	P->ClockOverride = [&Clock]() { return Clock; };
	P->LocalPlayerIdOverride = 1;
	UVerseEventHub* Hub = UVerseEventHub::Get(World.World);

	FVerseFireEvent Own;
	Own.ShooterId = 1;
	Own.WeaponId = TEXT("graveline");
	Own.ShotCounter = 5;
	Own.Origin = FVector::ZeroVector;
	Own.Direction = FVector(1, 0, 0);
	FVerseFireEvent Foe = Own;
	Foe.ShooterId = 2;
	Foe.ShotCounter = 9;
	Hub->OnFire.Broadcast(Own);
	Hub->OnFire.Broadcast(Foe);
	TestEqual(TEXT("one own round"), P->NumOwn(), 1);
	TestEqual(TEXT("one foe round"), P->NumFoe(), 1);
	const FLinearColor Tracer = UVerseBoltPresentation::TracerColor();
	for (const FVerseVisualBolt& B : P->GetBolts())
	{
		TestTrue(TEXT("one tracer colour for every shooter"), B.Color.Equals(Tracer));
	}
	TestTrue(TEXT("tracer is yellow-white, not a coloured bolt"), Tracer.R > 0.9f && Tracer.G > 0.65f && Tracer.B > 0.3f && Tracer.B < Tracer.G);
	TestEqual(TEXT("each shot ejects a casing"), P->GetCasings().Num(), 2);
	TestEqual(TEXT("the opponent's muzzle flashes (the viewmodel draws the own one)"), P->GetMuzzleFlashes().Num(), 1);
	TestTrue(TEXT("powder smoke at the muzzles"), P->GetPuffs().Num() >= 2);

	// Echo of the own shot is not drawn twice.
	Hub->OnFire.Broadcast(Own);
	TestEqual(TEXT("no duplicate"), P->NumOwn(), 1);

	// Flight: 880 m/s with gravity drop, drawn ahead of the muzzle.
	Clock += 0.1;
	P->Advance(Clock);
	const FVector Head = UVerseBoltPresentation::HeadAt(P->GetBolts()[0], Clock);
	TestEqual(TEXT("head at 88 m after 0.1 s"), Head.X, 8800.0, 1.0);
	TestEqual(TEXT("dropped 4.9 cm after 0.1 s"), Head.Z, -0.5 * 981.0 * 0.01, 0.01);

	// Rejected removes the own bolt; the cosmetic hit ends the foe bolt with an impact.
	UVerseWeaponComponent::OnAnyShotRejected.Broadcast(1, 5);
	TestEqual(TEXT("rejected own bolt removed"), P->NumOwn(), 0);
	TestEqual(TEXT("no impact from a rejection"), P->GetImpacts().Num(), 0);
	FVerseHitEvent Hit;
	Hit.InstigatorId = 2;
	Hit.ShotCounter = 9;
	Hit.ImpactWorld = FVector(500, 0, 0);
	Hub->OnHit.Broadcast(Hit);
	TestEqual(TEXT("foe bolt ended at the hit"), P->NumFoe(), 0);
	TestEqual(TEXT("impact flash from the hit event"), P->GetImpacts().Num(), 1);
	Clock += 1.0;
	P->Advance(Clock);
	TestEqual(TEXT("impact flash is short"), P->GetImpacts().Num(), 0);

	// A bolt that never hits leaves at its range.
	Hub->OnFire.Broadcast(Foe);
	Clock += 1.0;
	P->Advance(Clock);
	TestEqual(TEXT("bolt gone after MaxRange"), P->GetBolts().Num(), 0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Damage/VerseDamageMath.h"
#include "Damage/VerseDamageService.h"
#include "Events/VerseEventHub.h"
#include "Misc/AutomationTest.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Damage.*: the damage formula of combat-state.md 5 (A2.2) and the server damage path
// (WP02.9): GAS effect, armor first, spawn protection, finisher immunity, ruleset hooks, death.

namespace VerseDamageTest
{
	const EVerseHitZone Zones[] = {EVerseHitZone::Head, EVerseHitZone::Neck, EVerseHitZone::UpperTorso, EVerseHitZone::LowerTorso,
		EVerseHitZone::Arm, EVerseHitZone::Leg};

	/** The formula written out independently of FVerseDamageMath. */
	double Expected(const UVerseWeaponDefinition& W, EVerseHitZone Zone, double D)
	{
		double F = 1.0;
		if (D > W.FalloffStart)
		{
			F = D >= W.FalloffEnd ? W.FalloffMinFraction
								  : 1.0 + (W.FalloffMinFraction - 1.0) * (D - W.FalloffStart) / (W.FalloffEnd - W.FalloffStart);
		}
		const float* Z = W.ZoneMultipliers.Find(Zone);
		return double(W.BaseDamage) * double(Z ? *Z : 1.f) * F;
	}

	FVerseHitEvent BoltHit(const UVerseWeaponDefinition& W, EVerseHitZone Zone, float DistanceM)
	{
		FVerseHitEvent H;
		H.WeaponId = W.WeaponId;
		H.Source = EVerseDamageSource::Bolt;
		H.Zone = Zone;
		H.DistanceM = DistanceM;
		H.Damage = FVerseDamageMath::BoltDamage(W, Zone, DistanceM, 1.f);
		return H;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDamageZonesAndFalloff, "Verse.Combat.Damage.ZonesAndFalloff", VERSE_WP02_TEST_FLAGS)
bool FVerseDamageZonesAndFalloff::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const double Mid = 0.5 * (W->FalloffStart + W->FalloffEnd);
		const double Distances[] = {0.0, W->FalloffStart, Mid, W->FalloffEnd, W->FalloffEnd + 20.0};
		for (const EVerseHitZone Zone : VerseDamageTest::Zones)
		{
			TestTrue(FString::Printf(TEXT("%s has every zone"), *W->WeaponId.ToString()), W->ZoneMultipliers.Contains(Zone));
			for (const double D : Distances)
			{
				const double Got = FVerseDamageMath::BoltDamage(*W, Zone, float(D), 1.f);
				const double Want = VerseDamageTest::Expected(*W, Zone, D);
				if (FMath::Abs(Got - Want) > 1e-4)
				{
					AddError(FString::Printf(TEXT("%s zone %d at %.1f m: %.6f != %.6f"), *W->WeaponId.ToString(), int32(Zone), D, Got, Want));
				}
			}
		}
		TestEqual(TEXT("penetration factor multiplies"), FVerseDamageMath::BoltDamage(*W, EVerseHitZone::UpperTorso, 0.f, 0.5625f),
			W->BaseDamage * 0.5625f, 1e-4f);
		TestEqual(TEXT("zone None does nothing"), FVerseDamageMath::BoltDamage(*W, EVerseHitZone::None, 0.f, 1.f), 0.f);
	}

	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	for (const float D : {0.f, 10.f, 25.f})
	{
		TestEqual(FString::Printf(TEXT("Graveline: 4 upper-torso hits kill at %.0f m"), D),
			FVerseDamageMath::HitsToKill(*G, EVerseHitZone::UpperTorso, D, 100.f), 4);
	}
	TestTrue(TEXT("Graveline: 2 head hits kill at any range"), FVerseDamageMath::HitsToKill(*G, EVerseHitZone::Head, 150.f, 100.f) <= 2);

	// Through GAS on a real victim: exact to 1e-4 hp.
	VerseWp02Test::FTestWorld World;
	UVerseDamageService* Service = UVerseDamageService::Get(World.World);
	APawn* Shooter = VerseWp02Test::SpawnTarget(World.World, FVector(-1000, 0, 0));
	for (const EVerseHitZone Zone : VerseDamageTest::Zones)
	{
		APawn* Victim = VerseWp02Test::SpawnTarget(World.World, FVector(0, 0, 0), 1000.f);
		FVerseHitEvent Hit = VerseDamageTest::BoltHit(*G, Zone, 35.f);
		Service->ApplyHit(Shooter, Victim, Hit);
		TestEqual(FString::Printf(TEXT("GAS applies zone %d exactly"), int32(Zone)), double(VerseWp02Test::HealthOf(Victim)),
			1000.0 - VerseDamageTest::Expected(*G, Zone, 35.0), 1e-3);
	}
	APawn* Victim = VerseWp02Test::SpawnTarget(World.World, FVector(0, 0, 0));
	int32 Hits = 0;
	while (VerseWp02Test::HealthOf(Victim) > 0.f && Hits < 10)
	{
		FVerseHitEvent Hit = VerseDamageTest::BoltHit(*G, EVerseHitZone::UpperTorso, 25.f);
		Service->ApplyHit(Shooter, Victim, Hit);
		++Hits;
		TestEqual(TEXT("killing blow only on the last hit"), Hit.bKillingBlow != 0, VerseWp02Test::HealthOf(Victim) <= 0.f);
	}
	TestEqual(TEXT("4 upper-torso hits at 25 m through the damage path"), Hits, 4);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDamageRulesAndDeath, "Verse.Combat.Damage.RulesAndDeath", VERSE_WP02_TEST_FLAGS)
bool FVerseDamageRulesAndDeath::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	// Armor first (inert at MaxArmor 0).
	const FVerseDamageSplit Inert = FVerseDamageMath::Split(30.f, 100.f, 50.f, 0.f);
	TestEqual(TEXT("MaxArmor 0: all to health"), Inert.ToHealth, 30.f);
	const FVerseDamageSplit Armored = FVerseDamageMath::Split(30.f, 100.f, 20.f, 50.f);
	TestEqual(TEXT("armor absorbs first"), Armored.ToArmor, 20.f);
	TestEqual(TEXT("rest to health"), Armored.HealthAfter, 90.f);

	VerseWp02Test::FTestWorld World;
	UVerseDamageService* Service = UVerseDamageService::Get(World.World);
	UVerseEventHub* Hub = UVerseEventHub::Get(World.World);
	TArray<FVerseHitEvent> Hits;
	TArray<FVerseDeathEvent> Deaths;
	Hub->OnHit.AddLambda([&Hits](const FVerseHitEvent& E) { Hits.Add(E); });
	Hub->OnDeath.AddLambda([&Deaths](const FVerseDeathEvent& E) { Deaths.Add(E); });

	APawn* Shooter = VerseWp02Test::SpawnTarget(World.World, FVector(-1000, 0, 0));
	APawn* Victim = VerseWp02Test::SpawnTarget(World.World, FVector::ZeroVector);
	UVerseCombatStateComponent* State = UVerseCombatStateComponent::FindOn(Victim);
	const float Now = Service->Now();

	// Spawn protection: no damage, the hit still raised with the marker.
	State->BeginSpawnProtection(Now, 2.f);
	FVerseHitEvent Protected = VerseDamageTest::BoltHit(*G, EVerseHitZone::Head, 5.f);
	Service->ApplyHit(Shooter, Victim, Protected);
	TestEqual(TEXT("protected: full health"), VerseWp02Test::HealthOf(Victim), 100.f);
	TestTrue(TEXT("protected: marker set"), Protected.bBlockedBySpawnProtection != 0);
	TestEqual(TEXT("protected: hit event raised"), Hits.Num(), 1);
	State->NotifyOffensiveAction(Now);
	TestFalse(TEXT("own action ends protection"), State->IsSpawnProtected(Now));

	// Finisher victim: only the finisher's own damage.
	State->SetPhase(EVerseCombatPhase::FinisherVictim);
	FVerseHitEvent Bolt = VerseDamageTest::BoltHit(*G, EVerseHitZone::Head, 5.f);
	Service->ApplyHit(Shooter, Victim, Bolt);
	TestEqual(TEXT("finisher victim ignores bolts"), VerseWp02Test::HealthOf(Victim), 100.f);
	State->SetPhase(EVerseCombatPhase::Alive);

	// Ruleset hooks (the WP11 fake allows all; here they refuse, then scale).
	Service->Rules.CanDamage = [](const FVerseDamageQuery& Q) { return Q.Source != EVerseDamageSource::Bolt; };
	FVerseHitEvent Refused = VerseDamageTest::BoltHit(*G, EVerseHitZone::UpperTorso, 5.f);
	Service->ApplyHit(Shooter, Victim, Refused);
	TestEqual(TEXT("CanDamage false: no damage"), VerseWp02Test::HealthOf(Victim), 100.f);
	Service->Rules.CanDamage = nullptr;
	Service->Rules.ModifyDamage = [](const FVerseDamageQuery&, float D) { return D * 0.5f; };
	FVerseHitEvent Halved = VerseDamageTest::BoltHit(*G, EVerseHitZone::UpperTorso, 5.f);
	Service->ApplyHit(Shooter, Victim, Halved);
	TestEqual(TEXT("ModifyDamage applied"), VerseWp02Test::HealthOf(Victim), 100.f - 14.f, 1e-4f);
	Service->Rules.ModifyDamage = nullptr;

	// Death: one event, killer and cause, phase Dead, nothing after.
	FVerseHitEvent Head1 = VerseDamageTest::BoltHit(*G, EVerseHitZone::Head, 5.f);
	FVerseHitEvent Head2 = VerseDamageTest::BoltHit(*G, EVerseHitZone::Head, 5.f);
	Service->ApplyHit(Shooter, Victim, Head1);
	Service->ApplyHit(Shooter, Victim, Head2);
	TestEqual(TEXT("one death"), Deaths.Num(), 1);
	TestTrue(TEXT("killing blow flagged"), Head2.bKillingBlow != 0);
	TestTrue(TEXT("headshot flagged"), Head2.bHeadshot != 0);
	TestEqual(TEXT("phase Dead"), State->Phase, EVerseCombatPhase::Dead);
	if (Deaths.Num() == 1)
	{
		TestEqual(TEXT("killer id"), Deaths[0].KillerId, VerseCombatIds::IdOf(Shooter));
		TestEqual(TEXT("victim id"), Deaths[0].VictimId, VerseCombatIds::IdOf(Victim));
		TestEqual(TEXT("cause"), Deaths[0].Cause, EVerseDamageSource::Bolt);
		TestEqual(TEXT("last zone"), Deaths[0].LastZone, EVerseHitZone::Head);
		TestEqual(TEXT("respawn at +3 s"), Deaths[0].RespawnAt, Deaths[0].ServerTime + 3.f, 1e-5f);
	}
	const int32 HitsBefore = Hits.Num();
	FVerseHitEvent Late = VerseDamageTest::BoltHit(*G, EVerseHitZone::Head, 5.f);
	Service->ApplyHit(Shooter, Victim, Late);
	TestEqual(TEXT("dead victims take no more hits"), Hits.Num(), HitsBefore);
	TestEqual(TEXT("still one death"), Deaths.Num(), 1);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

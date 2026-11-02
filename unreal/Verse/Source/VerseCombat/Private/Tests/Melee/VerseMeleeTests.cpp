#include "Combat/VerseMeleeDefinition.h"
#include "Events/VerseEventHub.h"
#include "Finisher/VerseFinisherTimeline.h"
#include "Melee/VerseMeleeComponent.h"
#include "Melee/VerseMeleeImport.h"
#include "Melee/VerseMeleeRules.h"
#include "Misc/AutomationTest.h"
#include "Tests/Melee/Fakes/VerseFakeMeleeWorld.h"
#include "Tests/Melee/Fakes/VerseMeleeTestWorld.h"
#include "VerseGameplayTags.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_MELEE_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseMeleeTest
{
	/** combat-state.md 7.2 written out again over nominal values, as the oracle of A4.1. */
	EVerseMeleeOutcome Oracle(double ThetaDeg, double PhiDeg, double RCm, double DzCm, bool bEligible, bool bSweep)
	{
		if (RCm == 0.0)
		{
			ThetaDeg = 0.0; // d undefined: the attacker counts as in front, looking at the victim
			PhiDeg = 0.0;
		}
		const bool bFlankOrBack = ThetaDeg > 60.0;
		if (bFlankOrBack && RCm <= 150.0 && PhiDeg <= 45.0 && FMath::Abs(DzCm) <= 60.0 && bEligible && bSweep)
		{
			return EVerseMeleeOutcome::Finisher;
		}
		if (FMath::Sqrt(RCm * RCm + DzCm * DzCm) <= 200.0 && PhiDeg <= 30.0)
		{
			return EVerseMeleeOutcome::Strike;
		}
		return EVerseMeleeOutcome::Whiff;
	}

	FVector2D Rotate(const FVector2D& V, double Deg)
	{
		const double R = FMath::DegreesToRadians(Deg);
		return FVector2D(V.X * FMath::Cos(R) - V.Y * FMath::Sin(R), V.X * FMath::Sin(R) + V.Y * FMath::Cos(R));
	}
}

// A4.1: grid 0-180 deg in 5 deg steps x 0-2.5 m in 0.1 m x dz -1..1 m in 0.2 m (plus attacker
// facings and both eligibility inputs): 100 % match with 7.2.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMeleeClassifyTest, "Verse.Combat.Melee.Classify", VERSE_MELEE_TEST_FLAGS)
bool FVerseMeleeClassifyTest::RunTest(const FString& Parameters)
{
	using namespace VerseMeleeTest;
	const UVerseMeleeDefinition& Def = *GetDefault<UVerseMeleeDefinition>();
	const double VictimYaw = 37.0;
	const FVector2D VictimFacing = Rotate(FVector2D(1.0, 0.0), VictimYaw);
	const double Phis[] = {0.0, 25.0, 30.0, 45.0, 50.0, 90.0, 180.0};
	int32 Total = 0;
	int32 Mismatches = 0;
	int32 Counts[3] = {0, 0, 0};
	for (int32 K = 0; K <= 36; ++K)
	{
		const double Theta = 5.0 * K;
		const double Side = (K % 2 == 0) ? 1.0 : -1.0;
		const FVector2D D = Rotate(VictimFacing, Side * Theta);
		for (int32 I = 0; I <= 25; ++I)
		{
			const double R = 10.0 * I;
			for (int32 J = -5; J <= 5; ++J)
			{
				const double Dz = 20.0 * J;
				for (const double Phi : Phis)
				{
					const double Turn = (J % 2 == 0) ? Phi : -Phi;
					const FVector2D Look = Rotate(-D, Turn);
					const FTransform Victim(FRotator(0.0, VictimYaw, 0.0), FVector(120.0, -340.0, 15.0));
					const FVector AttackerLoc = Victim.GetLocation() + FVector(D.X * R, D.Y * R, Dz);
					const FTransform Attacker(FRotator(0.0, FMath::RadiansToDegrees(FMath::Atan2(Look.Y, Look.X)), 0.0), AttackerLoc);
					for (int32 Flags = 0; Flags < 4; ++Flags)
					{
						const bool bEligible = (Flags & 1) != 0;
						const bool bSweep = (Flags & 2) != 0;
						const EVerseMeleeOutcome Got = UVerseMeleeComponent::Classify(Attacker, Victim, Def, bEligible, bSweep);
						const EVerseMeleeOutcome Want = Oracle(Theta, Phi, R, Dz, bEligible, bSweep);
						++Total;
						++Counts[uint8(Got)];
						if (Got != Want)
						{
							if (++Mismatches <= 10)
							{
								AddError(FString::Printf(TEXT("theta %g phi %g r %g cm dz %g cm eligible %d sweep %d: got %d want %d"),
									Theta, Phi, R, Dz, bEligible, bSweep, int32(Got), int32(Want)));
							}
						}
					}
				}
			}
		}
	}
	AddInfo(FString::Printf(TEXT("A4.1: %d cases, %d mismatches (whiff %d, strike %d, finisher %d)"), Total, Mismatches,
		Counts[0], Counts[1], Counts[2]));
	TestEqual(TEXT("100 % match with 7.2"), Mismatches, 0);
	TestTrue(TEXT("grid reaches every outcome"), Counts[0] > 0 && Counts[1] > 0 && Counts[2] > 0);

	// The boundaries named in 7.1/7.2, measured from transforms.
	auto At = [&](double Theta, double R, double Dz, double Phi)
	{
		const FVector2D D = Rotate(VictimFacing, Theta);
		const FTransform Victim(FRotator(0.0, VictimYaw, 0.0), FVector::ZeroVector);
		const FVector2D Look = Rotate(-D, Phi);
		const FTransform Attacker(FRotator(0.0, FMath::RadiansToDegrees(FMath::Atan2(Look.Y, Look.X)), 0.0), FVector(D.X * R, D.Y * R, Dz));
		return UVerseMeleeComponent::Classify(Attacker, Victim, Def, true, true);
	};
	TestEqual(TEXT("theta 60 is Front: strike"), At(60.0, 100.0, 0.0, 0.0), EVerseMeleeOutcome::Strike);
	TestEqual(TEXT("theta 61 is Flank: finisher"), At(61.0, 100.0, 0.0, 0.0), EVerseMeleeOutcome::Finisher);
	TestEqual(TEXT("r 1.5 m inclusive"), At(150.0, 150.0, 0.0, 0.0), EVerseMeleeOutcome::Finisher);
	TestEqual(TEXT("r 1.51 m: strike"), At(150.0, 151.0, 0.0, 0.0), EVerseMeleeOutcome::Strike);
	TestEqual(TEXT("|dz| 0.6 m inclusive"), At(150.0, 100.0, -60.0, 0.0), EVerseMeleeOutcome::Finisher);
	TestEqual(TEXT("phi 46 deg: no finisher, outside the 30 deg cone"), At(150.0, 100.0, 0.0, 46.0), EVerseMeleeOutcome::Whiff);
	TestEqual(TEXT("2.0 m strike reach inclusive"), At(0.0, 200.0, 0.0, 0.0), EVerseMeleeOutcome::Strike);
	TestEqual(TEXT("2.01 m whiffs"), At(0.0, 201.0, 0.0, 0.0), EVerseMeleeOutcome::Whiff);

	// Eligibility (7.2 condition list).
	FVerseMeleeParticipant A;
	FVerseMeleeParticipant V;
	TestTrue(TEXT("both standing and alive: eligible"), VerseMelee::IsFinisherEligible(A, V));
	V.bSpawnProtected = true;
	TestFalse(TEXT("spawn-protected victim"), VerseMelee::IsFinisherEligible(A, V));
	V = {};
	V.Stance = EVerseStance::Prone;
	TestFalse(TEXT("prone victim"), VerseMelee::IsFinisherEligible(A, V));
	V = {};
	V.bMantling = true;
	TestFalse(TEXT("mantling victim"), VerseMelee::IsFinisherEligible(A, V));
	V = {};
	V.Phase = EVerseCombatPhase::FinisherVictim;
	TestFalse(TEXT("victim already in a finisher"), VerseMelee::IsFinisherEligible(A, V));
	V = {};
	V.Stance = EVerseStance::Crouch;
	TestTrue(TEXT("crouched victim is eligible"), VerseMelee::IsFinisherEligible(A, V));
	A.bAirborne = true;
	TestFalse(TEXT("airborne attacker"), VerseMelee::IsFinisherEligible(A, V));
	A = {};
	A.Stance = EVerseStance::Prone;
	TestFalse(TEXT("prone attacker"), VerseMelee::IsFinisherEligible(A, V));
	return true;
}

// WP04.1: the importer reads the shipped text surface and rejects malformed files.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMeleeImportTest, "Verse.Combat.Melee.Import", VERSE_MELEE_TEST_FLAGS)
bool FVerseMeleeImportTest::RunTest(const FString& Parameters)
{
	UVerseMeleeDefinition* Def = NewObject<UVerseMeleeDefinition>(GetTransientPackage());
	FVerseMeleePresentationTuning Tuning;
	FString Error;
	const bool bOk = FVerseMeleeImport::FromFile(FVerseMeleeImport::DefaultPath(), *Def, Tuning, Error);
	TestTrue(FString::Printf(TEXT("hookbill.json imports (%s)"), *Error), bOk);
	TestEqual(TEXT("StrikeDamage"), Def->StrikeDamage, 55.f);
	TestEqual(TEXT("StrikeHitDelay"), Def->StrikeHitDelay, 0.15f);
	TestEqual(TEXT("StrikeCooldown"), Def->StrikeCooldown, 0.7f);
	TestEqual(TEXT("StrikeRange"), Def->StrikeRange, 2.f);
	TestEqual(TEXT("StrikeConeHalfAngle"), Def->StrikeConeHalfAngle, 30.f);
	TestEqual(TEXT("FinisherRange"), Def->FinisherRange, 1.5f);
	TestEqual(TEXT("FinisherMaxHeightDelta"), Def->FinisherMaxHeightDelta, 0.6f);
	TestEqual(TEXT("FrontHalfAngle"), Def->FrontHalfAngle, 60.f);
	TestEqual(TEXT("AttackerFacingMax"), Def->AttackerFacingMax, 45.f);
	TestEqual(TEXT("FinisherDuration"), Def->FinisherDuration, 2.5f);
	TestEqual(TEXT("FinisherKillTime"), Def->FinisherKillTime, 2.1f);
	TestEqual(TEXT("weapon id"), Tuning.WeaponId, FName(TEXT("hookbill")));
	TestEqual(TEXT("paired offset in cm"), Tuning.PairedOffsetCm, 70.0, 1e-9);
	TestTrue(TEXT("equip never delays the contact frame"), Tuning.EquipS <= Def->StrikeHitDelay + 1e-6);

	FString Text;
	FFileHelper::LoadFileToString(Text, *FVerseMeleeImport::DefaultPath());
	struct FCase
	{
		const TCHAR* What;
		FString From;
		FString To;
	};
	const FCase Cases[] = {
		{TEXT("wrong schema"), TEXT("verse.melee/1"), TEXT("verse.melee/2")},
		{TEXT("missing damage"), TEXT("\"damage\""), TEXT("\"damage_x\"")},
		{TEXT("negative cooldown"), TEXT("\"cooldown_s\": 0.7"), TEXT("\"cooldown_s\": -0.7")},
		{TEXT("duration off the frozen timeline"), TEXT("\"duration_s\": 2.5"), TEXT("\"duration_s\": 3.0")},
		{TEXT("kill time off the frozen timeline"), TEXT("\"kill_time_s\": 2.1"), TEXT("\"kill_time_s\": 2.0")},
		{TEXT("missing presentation"), TEXT("\"presentation\""), TEXT("\"presentation_x\"")},
	};
	for (const FCase& Case : Cases)
	{
		TestTrue(FString::Printf(TEXT("fixture contains '%s'"), *Case.From), Text.Contains(Case.From));
		const FString Broken = Text.Replace(*Case.From, *Case.To);
		UVerseMeleeDefinition* Scratch = NewObject<UVerseMeleeDefinition>(GetTransientPackage());
		FVerseMeleePresentationTuning ScratchTuning;
		FString CaseError;
		TestFalse(FString::Printf(TEXT("rejects: %s"), Case.What), FVerseMeleeImport::FromJsonString(Broken, *Scratch, ScratchTuning, CaseError));
		TestFalse(FString::Printf(TEXT("says why: %s"), Case.What), CaseError.IsEmpty());
	}
	TestFalse(TEXT("rejects non-JSON"), FVerseMeleeImport::FromJsonString(TEXT("[1,2"), *Def, Tuning, Error));
	return true;
}

// A4.2: 55 damage, 2 strikes kill from 100, cooldown 0.7 s within 1 tick; noise on every press.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMeleeStrikeTest, "Verse.Combat.Melee.Strike", VERSE_MELEE_TEST_FLAGS)
bool FVerseMeleeStrikeTest::RunTest(const FString& Parameters)
{
	// Pure clock: presses on every 60 Hz tick are accepted exactly every 0.7 s.
	{
		FVerseMeleeClock Clock;
		TArray<double> Accepted;
		for (int32 T = 0; T <= 150; ++T)
		{
			const double Now = 100.0 + T / 60.0;
			if (Clock.TryPress(Now, 0.7))
			{
				Accepted.Add(Now);
			}
		}
		TestEqual(TEXT("clock: presses accepted in 2.5 s"), Accepted.Num(), 4);
		for (int32 I = 1; I < Accepted.Num(); ++I)
		{
			TestTrue(FString::Printf(TEXT("clock: interval %d is 0.7 s within 1 tick (%.4f)"), I, Accepted[I] - Accepted[I - 1]),
				FMath::Abs(Accepted[I] - Accepted[I - 1] - 0.7) <= FVerseMeleeTestWorld::Tick + 1e-9);
		}
	}

	FVerseMeleeTestWorld W;
	ACharacter* Attacker = W.Spawn(FVector(0.0, 0.0, 0.0), 0.0);
	ACharacter* Victim = W.Spawn(FVector(150.0, 0.0, 0.0), 180.0);
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	TArray<FVerseHitEvent> Hits;
	TArray<double> HitTimes;
	TArray<FVerseDeathEvent> Deaths;
	int32 MeleeNoises = 0;
	Hub->OnHit.AddLambda([&](const FVerseHitEvent& E) { Hits.Add(E); HitTimes.Add(W.Now()); });
	Hub->OnDeath.AddLambda([&](const FVerseDeathEvent& E) { Deaths.Add(E); });
	Hub->OnNoise.AddLambda([&](const FVerseNoiseEvent& E) { MeleeNoises += E.Noise == VerseTags::Noise_Melee.GetTag() ? 1 : 0; });

	UVerseMeleeComponent* Melee = FVerseMeleeTestWorld::Melee(Attacker);
	TArray<double> Presses;
	TArray<EVerseMeleeOutcome> Outcomes;
	for (int32 T = 0; T < 100; ++T)
	{
		EVerseMeleeOutcome Outcome;
		if (Melee->HandleMeleePress(W.Now(), Outcome))
		{
			Presses.Add(W.Now());
			Outcomes.Add(Outcome);
		}
		W.Step();
	}
	TestEqual(TEXT("presses accepted in 1.67 s"), Presses.Num(), 3);
	if (Presses.Num() >= 3)
	{
		TestEqual(TEXT("first press strikes"), Outcomes[0], EVerseMeleeOutcome::Strike);
		TestEqual(TEXT("second press strikes"), Outcomes[1], EVerseMeleeOutcome::Strike);
		TestEqual(TEXT("third press finds only a dead pawn: whiff"), Outcomes[2], EVerseMeleeOutcome::Whiff);
		TestTrue(FString::Printf(TEXT("cooldown 0.7 s within 1 tick (%.4f)"), Presses[1] - Presses[0]),
			FMath::Abs(Presses[1] - Presses[0] - 0.7) <= FVerseMeleeTestWorld::Tick + 1e-6);
	}
	TestEqual(TEXT("two hits"), Hits.Num(), 2);
	if (Hits.Num() == 2 && Presses.Num() >= 2)
	{
		TestEqual(TEXT("first strike: 55 damage"), Hits[0].Damage, 55.f);
		TestEqual(TEXT("source Melee"), Hits[0].Source, EVerseDamageSource::Melee);
		TestEqual(TEXT("knife weapon id"), Hits[0].WeaponId, FName(TEXT("hookbill")));
		TestFalse(TEXT("first strike is not a kill"), bool(Hits[0].bKillingBlow));
		TestEqual(TEXT("second strike: the remaining 45"), Hits[1].Damage, 45.f);
		TestTrue(TEXT("second strike kills"), bool(Hits[1].bKillingBlow));
		TestTrue(FString::Printf(TEXT("hit delay 0.15 s within 1 tick (%.4f)"), HitTimes[0] - Presses[0]),
			FMath::Abs(HitTimes[0] - Presses[0] - 0.15) <= FVerseMeleeTestWorld::Tick + 1e-6);
	}
	TestEqual(TEXT("one death"), Deaths.Num(), 1);
	if (Deaths.Num() == 1)
	{
		TestEqual(TEXT("death cause Melee"), Deaths[0].Cause, EVerseDamageSource::Melee);
	}
	TestEqual(TEXT("victim health 0"), W.Port().GetHealth(Victim), 0.f);
	TestEqual(TEXT("victim Dead"), FVerseMeleeTestWorld::State(Victim)->Phase, EVerseCombatPhase::Dead);
	TestEqual(TEXT("Noise.Melee on every accepted press"), MeleeNoises, 3);

	// A spawn-protected target takes nothing; the hit still says so (combat-state.md 9.3).
	ACharacter* Fresh = W.Spawn(FVector(0.0, 400.0, 0.0), 0.0);
	ACharacter* Protected = W.Spawn(FVector(100.0, 400.0, 0.0), 180.0);
	FVerseMeleeTestWorld::State(Protected)->bSpawnProtected = true;
	FVerseMeleeTestWorld::State(Fresh)->bSpawnProtected = true;
	Hits.Reset();
	EVerseMeleeOutcome Outcome;
	TestTrue(TEXT("protected attacker may press"), FVerseMeleeTestWorld::Melee(Fresh)->HandleMeleePress(W.Now(), Outcome));
	TestFalse(TEXT("the press ends the attacker's own protection"), FVerseMeleeTestWorld::State(Fresh)->bSpawnProtected);
	W.Step(12);
	TestEqual(TEXT("one blocked hit"), Hits.Num(), 1);
	if (Hits.Num() == 1)
	{
		TestTrue(TEXT("blocked by spawn protection"), bool(Hits[0].bBlockedBySpawnProtection));
		TestEqual(TEXT("no damage"), Hits[0].Damage, 0.f);
	}
	TestEqual(TEXT("protected health untouched"), W.Port().GetHealth(Protected), 100.f);
	return true;
}

// WP02.8 stand-in: the server classifies at the attacker's view time, not at the current pose.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMeleeRewindTest, "Verse.Combat.Melee.Rewind", VERSE_MELEE_TEST_FLAGS)
bool FVerseMeleeRewindTest::RunTest(const FString& Parameters)
{
	FVerseMeleeTestWorld W;
	ACharacter* Attacker = W.Spawn(FVector(0.0, 0.0, 0.0), 0.0);
	ACharacter* Victim = W.Spawn(FVector(400.0, 0.0, 0.0), 0.0);
	TSharedPtr<FFakeMeleeWorld> Fake = MakeShared<FFakeMeleeWorld>(W.World);
	W.World->GetSubsystem<UVerseMeleeWorldSubsystem>()->SetWorld(Fake);
	W.Step(30);
	const double Now = W.Now();
	// 100 ms ago the victim stood 1 m in front of the attacker with its back turned.
	auto Record = [&Fake](const APawn* Pawn, double T0, const FVector& L0, double T1, const FVector& L1)
	{
		TArray<TPair<double, FTransform>>& Samples = Fake->History.FindOrAdd(Pawn);
		Samples.Emplace(T0, FTransform(L0));
		Samples.Emplace(T1, FTransform(L1));
	};
	Record(Victim, Now - 0.1, FVector(100.0, 0.0, 0.0), Now, FVector(400.0, 0.0, 0.0));
	EVerseMeleeOutcome Outcome;
	TestTrue(TEXT("press accepted"), FVerseMeleeTestWorld::Melee(Attacker)->HandleMeleePress(Now - 0.1, Outcome));
	TestEqual(TEXT("rewound pose: finisher from the back"), Outcome, EVerseMeleeOutcome::Finisher);
	W.Step(160);

	// Rewind is capped at 250 ms: a view time 0.4 s old reads the pose at now - 0.25 s.
	ACharacter* A2 = W.Spawn(FVector(0.0, 1000.0, 0.0), 0.0);
	ACharacter* V2 = W.Spawn(FVector(500.0, 1000.0, 0.0), 0.0);
	const double Now2 = W.Now();
	Record(V2, Now2 - 0.4, FVector(100.0, 1000.0, 0.0), Now2 - 0.25, FVector(500.0, 1000.0, 0.0));
	TestTrue(TEXT("second press accepted"), FVerseMeleeTestWorld::Melee(A2)->HandleMeleePress(Now2 - 0.4, Outcome));
	TestEqual(TEXT("capped rewind: target out of reach"), Outcome, EVerseMeleeOutcome::Whiff);

	// Movement flags come from the movement query: a prone victim gets a strike, not a finisher.
	ACharacter* A3 = W.Spawn(FVector(0.0, 2000.0, 0.0), 0.0);
	ACharacter* V3 = W.Spawn(FVector(100.0, 2000.0, 0.0), 0.0);
	FVerseMeleeParticipant Prone;
	Prone.Stance = EVerseStance::Prone;
	Fake->Movement.Add(V3, Prone);
	TestTrue(TEXT("third press accepted"), FVerseMeleeTestWorld::Melee(A3)->HandleMeleePress(W.Now(), Outcome));
	TestEqual(TEXT("prone victim from the back: strike"), Outcome, EVerseMeleeOutcome::Strike);
	W.World->GetSubsystem<UVerseMeleeWorldSubsystem>()->SetWorld(nullptr);
	return true;
}

// WP04.7: predicted swing, whiff, quick equip.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMeleeKnifeTest, "Verse.Combat.Melee.KnifePresentation", VERSE_MELEE_TEST_FLAGS)
bool FVerseMeleeKnifeTest::RunTest(const FString& Parameters)
{
	FVerseKnifePresentation K;
	K.EquipS = 0.12;
	K.HitDelayS = 0.15;
	K.RecoverS = 0.3;
	TestEqual(TEXT("before any press, another slot: hidden"), K.Evaluate(0.0), EVerseKnifeAnim::Hidden);
	K.Press(10.0, false);
	TestEqual(TEXT("quick knife draws first"), K.Evaluate(10.05), EVerseKnifeAnim::Equipping);
	TestEqual(TEXT("then swings"), K.Evaluate(10.13), EVerseKnifeAnim::Swinging);
	TestEqual(TEXT("contact frame at the hit delay"), K.ContactTime(), 10.15, 1e-9);
	TestEqual(TEXT("follow-through after contact"), K.Evaluate(10.2), EVerseKnifeAnim::Recovering);
	TestEqual(TEXT("knife put away again"), K.Evaluate(10.5), EVerseKnifeAnim::Hidden);
	TestFalse(TEXT("unconfirmed is not a whiff yet"), K.IsWhiff());
	K.Confirm(EVerseMeleeOutcome::Whiff);
	TestTrue(TEXT("server answer: whiff"), K.IsWhiff());

	K.Press(20.0, true);
	TestEqual(TEXT("knife slot active: no equip, swing at once"), K.Evaluate(20.01), EVerseKnifeAnim::Swinging);
	TestEqual(TEXT("knife slot rests ready"), K.Evaluate(21.0), EVerseKnifeAnim::Ready);
	K.Confirm(EVerseMeleeOutcome::Strike);
	TestFalse(TEXT("strike is not a whiff"), K.IsWhiff());

	K.Press(30.0, true);
	K.Confirm(EVerseMeleeOutcome::Finisher);
	TestEqual(TEXT("finisher takes the knife over"), K.Evaluate(30.05), EVerseKnifeAnim::Hidden);

	// The component predicts locally and then asks the server; in a standalone world both run here.
	FVerseMeleeTestWorld W;
	ACharacter* Attacker = W.Spawn(FVector(0.0, 0.0, 0.0), 0.0);
	UVerseMeleeComponent* Melee = FVerseMeleeTestWorld::Melee(Attacker);
	Melee->PressMelee(false);
	TestEqual(TEXT("component: predicted swing starts on the press"), Melee->GetKnifeAnim(), EVerseKnifeAnim::Equipping);
	TestTrue(TEXT("component: server answered whiff (nobody near)"), Melee->GetKnife().IsWhiff());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Abilities/VerseCloak.h"

#define VERSE_ABILITIES_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// The spring half of Z-02: port of the cloak tests of `abilities/sovereign.test.ts` (still at rest, lift on walk,
// sideways on strafe, lower lags upper). Verse.Parity.Z.02 adds the posed bones on the Sovereign mesh.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesCloakSprings, "Verse.Abilities.Cloak.Springs", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseAbilitiesCloakSprings::RunTest(const FString&)
{
	using namespace VerseCloak;
	TestEqual(TEXT("bone R1"), BoneName(0, 0), FName(TEXT("Cloak_R1")));
	TestEqual(TEXT("bone C2"), BoneName(1, 1), FName(TEXT("Cloak_C2")));
	TestEqual(TEXT("bone L1"), BoneName(2, 0), FName(TEXT("Cloak_L1")));

	// Hangs still when the body stands.
	const FAngles Rest = Target(0.f, 0.f, 0.f, 0);
	TestEqual(TEXT("rest lift"), Rest.Lift, 0.f, 1e-5f);
	TestEqual(TEXT("rest swing"), Rest.Swing, 0.f, 1e-5f);
	// Lifts behind a walking body; swings against a strafe; barely forward when backing off.
	TestTrue(TEXT("lifts on a walk"), Target(1.4f, 0.f, 0.f, 0).Lift > 0.3f);
	TestTrue(TEXT("strafe right: hem swings left"), Target(0.f, 1.f, 0.f, 0).Swing < 0.f);
	TestTrue(TEXT("strafe left: hem swings right"), Target(0.f, -1.f, 0.f, 0).Swing > 0.f);
	TestTrue(TEXT("turn right: hem swings left"), Target(0.f, 0.f, 2.f, 0).Swing < 0.f);
	TestTrue(TEXT("backing off"), Target(-2.f, 0.f, 0.f, 0).Lift >= -0.08f);
	// Columns spread outward while moving.
	TestTrue(TEXT("right column swings right"), Target(1.4f, 0.f, 0.f, -1).Swing > Target(1.4f, 0.f, 0.f, 0).Swing);

	// The springs: still at rest, lift while walking forward, the lower segment lags behind the upper.
	FSim Sim;
	const float Dt = 1.f / 60.f;
	for (int32 I = 0; I < 60; ++I)
	{
		Sim.Update(Dt, FVector(0.0, 0.0, 90.0), 30.f);
	}
	TestEqual(TEXT("still at rest"), Sim.Column(1).Upper.Lift, 0.f, 1e-4f);
	// Walk 140 cm/s along the facing (yaw 30).
	const FVector Dir = FRotator(0.0, 30.0, 0.0).Vector();
	FVector At(0.0, 0.0, 90.0);
	float UpperAtHalf = 0.f;
	float LowerAtHalf = 0.f;
	for (int32 I = 0; I < 120; ++I)
	{
		At += Dir * (140.0 * Dt);
		Sim.Update(Dt, At, 30.f);
		if (I == 14)
		{
			UpperAtHalf = Sim.Column(1).Upper.Lift;
			LowerAtHalf = Sim.Column(1).Lower.Lift;
		}
	}
	TestTrue(FString::Printf(TEXT("lifted while walking (%.3f)"), Sim.Column(1).Upper.Lift), Sim.Column(1).Upper.Lift > 0.2f);
	TestTrue(TEXT("the lower segment lags"), LowerAtHalf < 0.45f * UpperAtHalf);
	TestTrue(TEXT("the lower segment follows"), Sim.Column(1).Lower.Lift > 0.05f);
	// Stop: the upper settles first, the hem whips after it.
	float UpperPeakFrame = -1.f;
	float LowerPeakFrame = -1.f;
	float UpperMin = 1.f;
	float LowerMin = 1.f;
	for (int32 I = 0; I < 120; ++I)
	{
		Sim.Update(Dt, At, 30.f);
		if (Sim.Column(1).Upper.Lift < UpperMin)
		{
			UpperMin = Sim.Column(1).Upper.Lift;
			UpperPeakFrame = I;
		}
		if (Sim.Column(1).Lower.Lift < LowerMin)
		{
			LowerMin = Sim.Column(1).Lower.Lift;
			LowerPeakFrame = I;
		}
	}
	TestTrue(TEXT("hem lags on stop"), LowerPeakFrame > UpperPeakFrame);
	TestTrue(TEXT("settles back"), FMath::Abs(Sim.Column(1).Upper.Lift) < 0.05f);
	// Strafe right: the centre column swings left (negative), the flutter only rides on top.
	FSim Strafe;
	FVector P(0.0, 0.0, 90.0);
	for (int32 I = 0; I < 90; ++I)
	{
		P += FVector(0.0, 1.0, 0.0) * (120.0 * Dt);
		Strafe.Update(Dt, P, 0.f);
	}
	TestTrue(TEXT("swings against a strafe"), Strafe.Column(1).Upper.Swing < -0.03f);
	// A teleport is not a sprint.
	FSim Jump;
	Jump.Update(Dt, FVector::ZeroVector, 0.f);
	Jump.Update(Dt, FVector(5000.0, 0.0, 0.0), 0.f);
	TestEqual(TEXT("teleport ignored"), Jump.GetForward(), 0.f);
	// Reset forgets the motion.
	Sim.Reset();
	TestEqual(TEXT("reset"), Sim.Column(0).Upper.Lift, 0.f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

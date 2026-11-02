#include "Aim/VerseBotAimController.h"
#include "Aim/VerseBotAimSystem.h"
#include "Aim/VerseBotFireGate.h"
#include "Aim/VerseBotNoSightFire.h"
#include "Aim/VerseBotReaction.h"
#include "Aim/VerseBotRecoilControl.h"
#include "Aim/VerseBotTargetTracker.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Tests/Aim/Fakes/FakeVerseDuelRig.h"
#include "Tests/Tiers/VerseBotTierTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Aim.*: the aim model of bot.md 8.1-8.4 (WP09.2, 9.3, 9.4, 9.6), acceptance A9.1-A9.4.

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotAimTest
{
	const TCHAR* const TierNames[] = {TEXT("normal"), TEXT("hard"), TEXT("elite")};

	double Sd(const TArray<double>& Values)
	{
		double Mean = 0.0;
		for (const double V : Values) Mean += V;
		Mean /= FMath::Max(1, Values.Num());
		double Var = 0.0;
		for (const double V : Values) Var += (V - Mean) * (V - Mean);
		return FMath::Sqrt(Var / FMath::Max(1, Values.Num() - 1));
	}

	bool LoadOrFail(FAutomationTestBase& Test, VerseBotTierTest::FTierSet& Set)
	{
		Set = VerseBotTierTest::LoadTierSet();
		for (const FString& Error : Set.Errors)
		{
			Test.AddError(Error);
		}
		return Set.IsValid();
	}

	/** "[a, b, ...]" with %.4g numbers (evidence JSON; VerseBot links no JSON module). */
	FString NumberArray(const TArray<double>& Values)
	{
		TArray<FString> Parts;
		for (const double V : Values) Parts.Add(FString::Printf(TEXT("%.4g"), V));
		return TEXT("[") + FString::Join(Parts, TEXT(", ")) + TEXT("]");
	}

	FString BoolArray(const TArray<bool>& Values)
	{
		TArray<FString> Parts;
		for (const bool V : Values) Parts.Add(V ? TEXT("true") : TEXT("false"));
		return TEXT("[") + FString::Join(Parts, TEXT(", ")) + TEXT("]");
	}
}

// A9.1: stationary sd of the OU wander within 5 % of AimNoiseDeg over 100,000 ticks (pitch x 0.6).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimOuTest, "Verse.Bot.Aim.OU", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimOuTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	for (const TCHAR* Name : VerseBotAimTest::TierNames)
	{
		const UVerseBotTier& Tier = *Set.Get(Name);
		FVerseBotAimController Aim;
		Aim.Reset(FVerseBotAimParams::FromTier(Tier), 0xA11ull, FVector2D::ZeroVector);
		const double Dt = 1.0 / 60.0;
		for (int32 I = 0; I < 2000; ++I)
		{
			Aim.StepNoise(Dt); // burn-in to the stationary distribution
		}
		TArray<double> Pitch;
		TArray<double> Yaw;
		Pitch.Reserve(100000);
		Yaw.Reserve(100000);
		for (int32 I = 0; I < 100000; ++I)
		{
			Aim.StepNoise(Dt);
			Pitch.Add(Aim.GetNoise().X);
			Yaw.Add(Aim.GetNoise().Y);
		}
		const double YawSd = VerseBotAimTest::Sd(Yaw);
		const double PitchSd = VerseBotAimTest::Sd(Pitch);
		const double Want = Tier.AimNoiseDeg;
		AddInfo(FString::Printf(TEXT("%s: yaw sd %.4f (want %.4f), pitch sd %.4f (want %.4f)"), Name, YawSd, Want, PitchSd, Want * 0.6));
		TestTrue(FString::Printf(TEXT("%s yaw sd within 5 %%"), Name), FMath::Abs(YawSd / Want - 1.0) <= 0.05);
		TestTrue(FString::Printf(TEXT("%s pitch sd within 5 %% of 0.6 x"), Name), FMath::Abs(PitchSd / (Want * 0.6) - 1.0) <= 0.05);
	}
	return true;
}

// A9.2: reaction mean within 3 % of ReactionMs, 0 samples under the 0.6 x mean floor over 10,000 draws.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimReactionTest, "Verse.Bot.Aim.Reaction", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimReactionTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	for (const TCHAR* Name : VerseBotAimTest::TierNames)
	{
		const FVerseBotReactionParams Params = FVerseBotReactionParams::FromTier(*Set.Get(Name));
		FVerseRng Rng(0xBEEFull, 0, EVerseRngSalt::Aim);
		double Sum = 0.0;
		int32 UnderFloor = 0;
		const double Floor = FVerseBotReaction::FloorOfMean * Params.MeanMs;
		for (int32 I = 0; I < 10000; ++I)
		{
			const double Ms = FVerseBotReaction::SampleMs(Rng, Params);
			Sum += Ms;
			UnderFloor += Ms < Floor - 1.0e-9 ? 1 : 0;
		}
		const double Mean = Sum / 10000.0;
		AddInfo(FString::Printf(TEXT("%s: mean %.2f ms (want %.2f)"), Name, Mean, Params.MeanMs));
		TestTrue(FString::Printf(TEXT("%s mean within 3 %%"), Name), FMath::Abs(Mean / Params.MeanMs - 1.0) <= 0.03);
		TestEqual(FString::Printf(TEXT("%s samples under the floor"), Name), UnderFloor, 0);

		// The multipliers of bot.md 8.1 apply on top of the floor.
		FVerseRng A(1, 0, EVerseRngSalt::Aim);
		FVerseRng B(1, 0, EVerseRngSalt::Aim);
		FVerseRng C(1, 0, EVerseRngSalt::Aim);
		const double Plain = FVerseBotReaction::SampleMs(A, Params);
		TestTrue(TEXT("sound x 0.9"), FMath::IsNearlyEqual(FVerseBotReaction::SampleMs(B, Params, EVerseBotStimulus::Sound), Plain * 0.9, 1.0e-9));
		TestTrue(TEXT("peripheral and partial multiply"),
			FMath::IsNearlyEqual(FVerseBotReaction::SampleMs(C, Params, EVerseBotStimulus::Peripheral | EVerseBotStimulus::PartialExposure),
				Plain * Params.PeripheralMul * Params.PartialExposureMul, 1.0e-9));
	}
	return true;
}

// A9.3: no tick turns faster than TurnRateDegS, through flicks, strafing and recoil control.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimTurnCapTest, "Verse.Bot.Aim.TurnCap", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimTurnCapTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	for (const TCHAR* Name : VerseBotAimTest::TierNames)
	{
		const UVerseBotTier& Tier = *Set.Get(Name);
		VerseBotFakes::FFakeDuelRig Rig;
		Rig.Init(Tier, 0x7C0ull);
		FVerseRng Script(42, 0, EVerseRngSalt::Harness);
		int32 Over = 0;
		double MaxRate = 0.0;
		for (int32 T = 0; T < 6000; ++T)
		{
			if (T % 40 == 0)
			{
				// Teleport the target anywhere around the bot: flicks up to 180 deg.
				const double Yaw = Script.Range(-180.0, 180.0);
				const double Dist = Script.Range(300.0, 4000.0);
				Rig.TargetPelvis = FVector(FMath::Cos(FMath::DegreesToRadians(Yaw)) * Dist, FMath::Sin(FMath::DegreesToRadians(Yaw)) * Dist,
					Script.Range(-300.0, 600.0));
				Rig.TargetVelocity = FVector(Script.Range(-450.0, 450.0), Script.Range(-450.0, 450.0), 0.0);
				Rig.bTargetVisible = Script.Chance(0.8);
			}
			Rig.Step();
			const double Rate = FVector2D(Rig.Last.LookDeltaDeg.X, Rig.Last.LookDeltaDeg.Y).Size() / Rig.Dt;
			MaxRate = FMath::Max(MaxRate, Rate);
			Over += Rate > Tier.TurnRateDegS * (1.0 + 1.0e-5) ? 1 : 0;
		}
		AddInfo(FString::Printf(TEXT("%s: max turn %.1f deg/s, cap %.1f, shots %d"), Name, MaxRate, Tier.TurnRateDegS, Rig.ShotsFired));
		TestEqual(FString::Printf(TEXT("%s ticks above TurnRateDegS"), Name), Over, 0);
		TestTrue(FString::Printf(TEXT("%s reaches the cap on flicks"), Name), MaxRate > Tier.TurnRateDegS * 0.95);
	}
	return true;
}

// A9.4: over a 30-round spray the view keeps (1 - RecoilPatternComp) of the pattern climb, within 0.05.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimRecoilTest, "Verse.Bot.Aim.Recoil", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimRecoilTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	TArray<FString> ProofRows;
	for (const TCHAR* Name : VerseBotAimTest::TierNames)
	{
		const UVerseBotTier& Tier = *Set.Get(Name);
		constexpr int32 Seeds = 40;
		double RatioSum = 0.0;
		TArray<double> Ratios;
		for (int32 Seed = 0; Seed < Seeds; ++Seed)
		{
			VerseBotFakes::FFakeDuelRig Rig;
			Rig.Init(Tier, 1000ull + Seed);
			Rig.RecoilSeed = 99ull + Seed * 31ull;
			Rig.bRecovery = false; // measure climb, not the weapon's recovery
			Rig.TargetPelvis = FVector(1500, 0, 160 - 34);
			Rig.Intent.bEngage = false;
			for (int32 T = 0; T < 150; ++T)
			{
				Rig.Step(); // acquire and settle on the target
			}
			// The pattern sum the spray will produce, from the same curves the weapon uses.
			double PatternPitch = 0.0;
			for (int32 N = 0; N < 30; ++N)
			{
				PatternPitch += Rig.Weapon->PatternAt(N).X;
			}
			const double PitchBefore = Rig.View.X;
			const double NoiseBefore = Rig.Aim.GetController().GetErrorDeg(Rig.TimeS).X;
			Rig.bForceFire = true;
			while (Rig.ShotsFired < 30)
			{
				Rig.Step();
			}
			Rig.bForceFire = false;
			const double LastShot = Rig.LastShotS;
			while (Rig.TimeS < LastShot + 0.30)
			{
				Rig.Step();
			}
			const double NoiseAfter = Rig.Aim.GetController().GetErrorDeg(Rig.TimeS).X;
			// The wander is not recoil: take its change out of the climb.
			const double Climb = (Rig.View.X - PitchBefore) - (NoiseAfter - NoiseBefore);
			const double Ratio = Climb / PatternPitch;
			Ratios.Add(Ratio);
			RatioSum += Ratio;
		}
		const double Mean = RatioSum / Seeds;
		const double Want = 1.0 - Tier.RecoilPatternComp;
		AddInfo(FString::Printf(TEXT("%s: remaining climb %.4f of the pattern (want %.4f), sd over seeds %.4f"), Name, Mean, Want,
			VerseBotAimTest::Sd(Ratios)));
		TestTrue(FString::Printf(TEXT("%s remaining climb = 1 - RecoilPatternComp within 0.05"), Name), FMath::Abs(Mean - Want) <= 0.05);
		ProofRows.Add(FString::Printf(TEXT("\"%s\": {\"remaining\": %.5f, \"want\": %.5f, \"sd\": %.5f, \"seeds\": %d}"), Name, Mean, Want,
			VerseBotAimTest::Sd(Ratios), Seeds));
	}
	FFileHelper::SaveStringToFile(TEXT("{") + FString::Join(ProofRows, TEXT(", ")) + TEXT("}"),
		*FPaths::Combine(VerseBotTierTest::ProofDir(TEXT("WP09.3")), TEXT("recoil_remaining_climb.json")));
	return true;
}

// WP09.3 parts: the predictive pull and the residual correction after the track latency.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimRecoilControlTest, "Verse.Bot.Aim.RecoilControl", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimRecoilControlTest::RunTest(const FString& Parameters)
{
	FVerseBotRecoilParams Params;
	Params.PatternComp = 0.7;
	Params.ResidualGain = 0.5;
	Params.TrackLatencyMs = 120.0;
	FVerseBotRecoilControl Recoil;
	Recoil.Reset(Params);
	const FVector2D Pattern(0.5, 0.1);
	const FVector2D Random(0.06, -0.04);
	Recoil.OnShot(0.0, Pattern, 0.05, 0.35);
	TestTrue(TEXT("pulls against the known pattern at once"), Recoil.GetHandOffsetDeg().Equals(-0.7 * Pattern, 1.0e-9));
	Recoil.ObserveUnexplainedMotion(0.02, (Pattern + Random) * 0.5);
	Recoil.ObserveUnexplainedMotion(0.04, (Pattern + Random) * 0.5);
	Recoil.ObserveUnexplainedMotion(0.20, FVector2D(-1.0, 0.0)); // outside the kick window: not recoil
	Recoil.Tick(0.10);
	TestTrue(TEXT("the random part is unknown before the latency"), Recoil.GetResidualSeen().IsNearlyZero(1.0e-9));
	Recoil.Tick(0.121);
	TestTrue(TEXT("after the latency the residual is seen"), Recoil.GetResidualSeen().Equals(Random, 1.0e-9));
	TestTrue(TEXT("and corrected with the residual gain"), Recoil.GetHandOffsetDeg().Equals(-0.7 * Pattern - 0.5 * Random, 1.0e-9));
	TestTrue(TEXT("spraying"), Recoil.IsSpraying());
	Recoil.Tick(0.36);
	TestFalse(TEXT("the spray ends after PatternResetTime"), Recoil.IsSpraying());
	TestTrue(TEXT("and the offset returns to zero"), Recoil.GetHandOffsetDeg().IsNearlyZero(1.0e-12));

	// PatternKick follows combat-state.md 4.1: m = stance x lerp(1, ADS, ads).
	TStrongObjectPtr<UVerseWeaponDefinition> Rifle(VerseBotFakes::MakeRifle());
	const FVector2D K = FVerseBotRecoilControl::PatternKick(*Rifle, 0, EVerseStance::Crouch, 1.0);
	TestTrue(TEXT("pattern kick multiplier"), FMath::IsNearlyEqual(K.X, 0.45 * 0.8 * 0.8, 1.0e-6));
	return true;
}

// WP09.2 tracking: latency, lead and the strafing read.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimTrackingTest, "Verse.Bot.Aim.Tracking", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimTrackingTest::RunTest(const FString& Parameters)
{
	// Constant lateral run at 4 m/s, 15 m ahead: the aim point leads by flight x LeadSkill.
	FVerseBotTrackParams P;
	P.TrackLatencyMs = 100.0;
	P.LeadSkill = 0.9;
	P.LeadNoise = 0.0;
	P.HeadAimChance = 0.0;
	FVerseBotTargetTracker Tracker;
	Tracker.Reset(P, 3);
	Tracker.BeginEngagement();
	const FVector Eye(0, 0, 160);
	const FVector V(0, 400, 0);
	for (int32 T = 0; T <= 60; ++T)
	{
		FVerseSightPercept S;
		S.PelvisLocation = FVector(1500, -600 + V.Y * T / 60.0, 126);
		S.Velocity = V;
		S.VisibleMask = 0xFF;
		Tracker.Push(T / 60.0, S);
	}
	FVerseBotTrackedTarget Target;
	TestTrue(TEXT("perceived"), Tracker.Perceived(1.0, Target));
	const FVector TruePelvis(1500, -600 + V.Y * 1.0, 126);
	// Latency 0.1 s extrapolated with LeadSkill 0.9: lags by 0.1 x 0.1 x 400 = 4 cm.
	TestTrue(TEXT("latency extrapolated with LeadSkill"), FMath::IsNearlyEqual(TruePelvis.Y - Target.PelvisLocation.Y, 4.0, 0.7));
	const FVerseBotAimPoint Point = Tracker.AimPoint(Target, Eye, 300.0);
	const double FlightS = FVector::Dist(Eye, Point.Location) / 30000.0;
	TestTrue(TEXT("leads by bolt flight x LeadSkill"),
		FMath::IsNearlyEqual(Point.Location.Y - Target.PelvisLocation.Y, 400.0 * FlightS * 0.9, 1.0));
	TestEqual(TEXT("torso when not aiming at the head"), Point.Sample, EVerseSightSample::UpperTorso);
	TestTrue(TEXT("half-width from the torso radius"), FMath::IsNearlyEqual(Point.HalfWidthDeg, FMath::RadiansToDegrees(FMath::Atan(20.0 / FVector::Dist(Eye, Point.Location))), 1.0e-6));

	// Only the knees visible: the visible point closest to the torso.
	Target.VisibleMask = (1u << uint8(EVerseSightSample::KneeLeft)) | (1u << uint8(EVerseSightSample::KneeRight));
	TestTrue(TEXT("partial exposure aims at a visible knee"),
		Tracker.AimPoint(Target, Eye, 300.0).Sample == EVerseSightSample::KneeLeft || Tracker.AimPoint(Target, Eye, 300.0).Sample == EVerseSightSample::KneeRight);

	// A-D strafing (reverse every 0.3 s around y = 0): the motion window reads the middle.
	auto StrafeError = [](double WindowMs)
	{
		FVerseBotTrackParams Q;
		Q.TrackLatencyMs = 100.0;
		Q.MotionWindowMs = WindowMs;
		Q.LeadSkill = 0.9;
		Q.LeadNoise = 0.0;
		FVerseBotTargetTracker Tr;
		Tr.Reset(Q, 5);
		Tr.BeginEngagement();
		double Y = 0.0;
		double Dir = 1.0;
		double ErrSum = 0.0;
		int32 Count = 0;
		for (int32 T = 0; T < 600; ++T)
		{
			if (T % 18 == 0) Dir = -Dir;
			Y += Dir * 400.0 / 60.0;
			FVerseSightPercept S;
			S.PelvisLocation = FVector(1500, Y, 126);
			S.Velocity = FVector(0, Dir * 400.0, 0);
			S.VisibleMask = 0xFF;
			Tr.Push(T / 60.0, S);
			FVerseBotTrackedTarget Tg;
			if (T > 120 && Tr.Perceived(T / 60.0, Tg))
			{
				ErrSum += FMath::Abs(Tr.AimPoint(Tg, FVector(0, 0, 160), 300.0).Location.Y - 0.0);
				++Count;
			}
		}
		return ErrSum / FMath::Max(1, Count);
	};
	const double Chasing = StrafeError(0.0);
	const double Reading = StrafeError(300.0);
	AddInfo(FString::Printf(TEXT("strafing: mean distance of the aim from the wobble centre %.1f cm chasing, %.1f cm with the 300 ms read"),
		Chasing, Reading));
	TestTrue(TEXT("the motion window aims nearer the middle of the wobble"), Reading < Chasing);
	return true;
}

// WP09.4 fire discipline.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimFireGateTest, "Verse.Bot.Aim.FireGate", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimFireGateTest::RunTest(const FString& Parameters)
{
	FVerseBotFireParams P;
	P.FireTolerance = 1.6;
	P.AdsRangeM = 9.0;
	P.BurstRangeM = 22.0;
	P.MaxBurstShots = 5;
	P.bTapsAtLongRange = false;
	FVerseBotFireGate Gate;
	Gate.Reset(P);

	FVerseBotFireGateInput In;
	In.bHasTarget = true;
	In.TargetHalfWidthDeg = 1.0;
	In.RangeM = 8.0;
	In.AimErrorDeg = 1.7;
	TestTrue(TEXT("off target beyond tolerance x half-width"), Gate.Evaluate(In).Block == EVerseBotFireBlock::OffTarget);
	In.AimErrorDeg = 1.5;
	FVerseBotFireGateOutput Out = Gate.Evaluate(In);
	TestTrue(TEXT("fires within tolerance"), Out.bHoldFire && Out.bPressFire);
	TestFalse(TEXT("no ADS inside AdsRangeM"), Out.bAds);
	In.NowS = 0.02;
	Out = Gate.Evaluate(In);
	TestTrue(TEXT("auto holds the trigger without a new press"), Out.bHoldFire && !Out.bPressFire);

	In.bTargetSpawnProtected = true;
	TestTrue(TEXT("never at a spawn-protected target"), Gate.Evaluate(In).Block == EVerseBotFireBlock::SpawnProtectedTarget);
	In.bTargetSpawnProtected = false;

	In.RangeM = 12.0;
	TestTrue(TEXT("ADS beyond AdsRangeM"), Gate.Evaluate(In).bAds);
	In.bSprinting = true;
	TestFalse(TEXT("no ADS while sprinting"), Gate.Evaluate(In).bAds);
	In.bSprinting = false;
	In.bSliding = true;
	TestFalse(TEXT("no ADS while sliding"), Gate.Evaluate(In).bAds);
	In.bSliding = false;

	// Bursts beyond BurstRangeM: at most MaxBurstShots, then wait for the spray to settle.
	Gate.Reset(P);
	In.RangeM = 25.0;
	In.FireIntervalS = 0.087;
	In.PatternResetS = 0.35;
	int32 Shots = 0;
	int32 MaxRun = 0;
	int32 Run = 0;
	double LastShot = -1.0;
	for (int32 T = 0; T < 240; ++T)
	{
		In.NowS = T / 60.0;
		In.bRecoilSettled = In.NowS - LastShot >= 0.35;
		const FVerseBotFireGateOutput O = Gate.Evaluate(In);
		if (O.bHoldFire && In.NowS - LastShot >= In.FireIntervalS)
		{
			Gate.NotifyShot(In.NowS);
			LastShot = In.NowS;
			++Shots;
			++Run;
			MaxRun = FMath::Max(MaxRun, Run);
		}
		else if (!O.bHoldFire)
		{
			Run = 0;
		}
	}
	TestEqual(TEXT("bursts are at most MaxBurstShots long"), MaxRun, 5);
	TestTrue(TEXT("and fire again after the pause"), Shots > 5);

	// Elite taps beyond 30 m with the first-shot rest between them.
	P.bTapsAtLongRange = true;
	Gate.Reset(P);
	In.RangeM = 35.0;
	In.FirstShotRestS = 0.3;
	LastShot = -1.0;
	double MinGap = 1.0e9;
	for (int32 T = 0; T < 240; ++T)
	{
		In.NowS = T / 60.0;
		const FVerseBotFireGateOutput O = Gate.Evaluate(In);
		if (O.bPressFire)
		{
			if (LastShot >= 0.0) MinGap = FMath::Min(MinGap, In.NowS - LastShot);
			Gate.NotifyShot(In.NowS);
			LastShot = In.NowS;
		}
	}
	TestTrue(TEXT("taps wait the first-shot rest"), MinGap >= 0.3 - 1.0e-9);

	// Taps belong to elite (and adaptive past s = 0.75).
	VerseBotTierTest::FTierSet Set;
	if (VerseBotAimTest::LoadOrFail(*this, Set))
	{
		TestTrue(TEXT("elite taps"), FVerseBotFireParams::FromTier(*Set.Elite).bTapsAtLongRange);
		TestFalse(TEXT("hard does not tap"), FVerseBotFireParams::FromTier(*Set.Hard).bTapsAtLongRange);
		TestTrue(TEXT("adaptive taps from s = 0.75"), FVerseBotFireParams::FromTier(*Set.Hard, 0.8f).bTapsAtLongRange);
		TestFalse(TEXT("adaptive below 0.75 does not"), FVerseBotFireParams::FromTier(*Set.Elite, 0.6f).bTapsAtLongRange);
	}
	return true;
}

// WP09.6 fire without sight: suppression 0.35 s within 2 m, the prefire rule, nothing else.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimNoSightTest, "Verse.Bot.Aim.NoSight", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimNoSightTest::RunTest(const FString& Parameters)
{
	FVerseBotNoSightParams P;
	P.PrefireChance = 1.0;
	P.PrefireMinBelief = 0.4;
	FVerseBotNoSightFire Fire;
	Fire.Reset(P, 11);

	FVerseBotNoSightInput In;
	In.NowS = 10.0;
	In.LastSeenS = 9.70;
	In.LastSeenLocation = FVector(1000, 0, 100);
	In.AimPoint = FVector(1000, 150, 100);
	TestTrue(TEXT("suppression within 0.35 s and 2 m"), Fire.Classify(In) == EVerseBotFireAuthority::Suppression);
	In.AimPoint = FVector(1000, 250, 100);
	TestTrue(TEXT("not beyond 2 m of the last seen position"), Fire.Classify(In) == EVerseBotFireAuthority::None);
	In.AimPoint = FVector(1000, 150, 100);
	In.NowS = 10.06;
	TestTrue(TEXT("not after 0.35 s"), Fire.Classify(In) == EVerseBotFireAuthority::None);

	In.LastSeenS = -1.0;
	In.bHasPeekEdge = true;
	In.PeekEdgeLocation = FVector(2000, 500, 100);
	In.AimPoint = In.PeekEdgeLocation;
	In.HeardS = 9.0;
	In.HeardLocation = FVector(2300, 600, 100);
	In.BeliefMassAtEdge = 0.5;
	In.ApproachId = 1;
	TestTrue(TEXT("prefire: heard within 2 s within 6 m of the edge, belief above the tier minimum"),
		Fire.Classify(In) == EVerseBotFireAuthority::Prefire);
	In.HeardS = 7.9;
	TestTrue(TEXT("not with an older heard percept"), Fire.Classify(In) == EVerseBotFireAuthority::None);
	In.HeardS = 9.0;
	In.BeliefMassAtEdge = 0.35;
	TestTrue(TEXT("not below the tier belief minimum"), Fire.Classify(In) == EVerseBotFireAuthority::None);
	In.BeliefMassAtEdge = 0.5;
	In.HeardLocation = FVector(2700, 500, 100);
	TestTrue(TEXT("not when the noise is more than 6 m from the edge"), Fire.Classify(In) == EVerseBotFireAuthority::None);

	// The contract floor 0.25 holds even if a tier asked for less.
	P.PrefireMinBelief = 0.1;
	Fire.Reset(P, 11);
	In.HeardLocation = FVector(2300, 600, 100);
	In.BeliefMassAtEdge = 0.2;
	TestTrue(TEXT("never below the contract floor"), Fire.Classify(In) == EVerseBotFireAuthority::None);

	// PrefireChance is one roll per approach.
	P.PrefireChance = 0.35;
	P.PrefireMinBelief = 0.3;
	Fire.Reset(P, 12);
	In.BeliefMassAtEdge = 0.6;
	int32 Allowed = 0;
	for (uint32 Approach = 1; Approach <= 4000; ++Approach)
	{
		In.ApproachId = Approach;
		const EVerseBotFireAuthority First = Fire.Classify(In);
		TestTrue(TEXT("the roll holds for the approach"), Fire.Classify(In) == First);
		Allowed += First == EVerseBotFireAuthority::Prefire ? 1 : 0;
	}
	AddInfo(FString::Printf(TEXT("prefire share %.3f (want 0.35)"), Allowed / 4000.0));
	TestTrue(TEXT("PrefireChance per approach"), FMath::Abs(Allowed / 4000.0 - 0.35) <= 0.03);

	In.bHasPeekEdge = false;
	In.bWallShotAuthorised = true;
	TestTrue(TEXT("wall shot only with the brain's authority"), Fire.Classify(In) == EVerseBotFireAuthority::WallShot);
	In.bWallShotAuthorised = false;
	TestTrue(TEXT("anything else is not allowed"), Fire.Classify(In) == EVerseBotFireAuthority::None);

	// In the aim system: no Fire bit without authority, Suppression right after losing sight.
	VerseBotTierTest::FTierSet Set;
	if (VerseBotAimTest::LoadOrFail(*this, Set))
	{
		VerseBotFakes::FFakeDuelRig Rig;
		Rig.Init(*Set.Hard, 5);
		Rig.TargetPelvis = FVector(1200, 50, 126);
		for (int32 T = 0; T < 120; ++T)
		{
			Rig.Step();
		}
		TestTrue(TEXT("fires at the visible target"), Rig.ShotsFired > 0);
		Rig.bTargetVisible = false;
		Rig.Intent.bHasLookTarget = true;
		Rig.Intent.LookTarget = Rig.TargetPelvis + FVector(0, 0, 34);
		Rig.Intent.bWantNoSightFire = true;
		Rig.Intent.NoSight.LastSeenS = Rig.TimeS - Rig.Dt;
		Rig.Intent.NoSight.LastSeenLocation = Rig.TargetPelvis;
		int32 Unauthorised = 0;
		bool bSuppressed = false;
		for (int32 T = 0; T < 90; ++T)
		{
			Rig.Step();
			const bool bFire = (Rig.Last.Buttons & uint32(EVerseInputButton::Fire)) != 0;
			Unauthorised += bFire && Rig.Last.Authority == EVerseBotFireAuthority::None ? 1 : 0;
			bSuppressed |= bFire && Rig.Last.Authority == EVerseBotFireAuthority::Suppression;
			TestFalse(TEXT("no suppression after 0.35 s"), bFire && Rig.TimeS - Rig.Intent.NoSight.LastSeenS > 0.35 + Rig.Dt);
		}
		TestEqual(TEXT("no unclassified fire"), Unauthorised, 0);
		TestTrue(TEXT("suppression fire right after losing sight"), bSuppressed);
	}
	return true;
}

// B5 for the aim layer: the same seed, tier and frames give bit-identical outputs.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimDeterminismTest, "Verse.Bot.Aim.Determinism", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimDeterminismTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	auto Run = [&Set](uint64 Seed)
	{
		VerseBotFakes::FFakeDuelRig Rig;
		Rig.Init(*Set.Elite, Seed);
		Rig.TargetVelocity = FVector(0, 350, 0);
		TArray<uint32> Bits;
		for (int32 T = 0; T < 1200; ++T)
		{
			if (T % 200 == 100) Rig.TargetVelocity *= -1.0;
			Rig.bTargetVisible = (T / 150) % 3 != 2;
			Rig.Step();
			Bits.Add(*reinterpret_cast<const uint32*>(&Rig.Last.LookDeltaDeg.X));
			Bits.Add(*reinterpret_cast<const uint32*>(&Rig.Last.LookDeltaDeg.Y));
			Bits.Add(Rig.Last.Buttons);
		}
		return Bits;
	};
	TestTrue(TEXT("same seed: bit-identical"), Run(77) == Run(77));
	TestFalse(TEXT("another seed differs"), Run(77) == Run(78));
	return true;
}

// Evidence (work-packages WP09): error vs time for 5 engagements per tier, JSON under Saved/Harness/proof/WP09/WP09.2/.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotAimTraceTest, "Verse.Bot.Aim.Trace", VERSE_BOT_TEST_FLAGS)
bool FVerseBotAimTraceTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set;
	if (!VerseBotAimTest::LoadOrFail(*this, Set))
	{
		return false;
	}
	TMap<FString, double> MeanSettled;
	for (const TCHAR* Name : VerseBotAimTest::TierNames)
	{
		TArray<FString> Engagements;
		double SettledSum = 0.0;
		int32 SettledCount = 0;
		for (int32 E = 0; E < 5; ++E)
		{
			FVerseRng Script(500 + E, 0, EVerseRngSalt::Harness);
			VerseBotFakes::FFakeDuelRig Rig;
			Rig.Init(*Set.Get(Name), 900 + E);
			Rig.bInfiniteAmmo = true;
			// Start looking away; the target appears 8-30 deg off, 10-25 m away, strafing 2-4 m/s.
			Rig.bTargetVisible = false;
			for (int32 T = 0; T < 30; ++T) Rig.Step();
			const double Off = Script.Range(8.0, 30.0) * (Script.Chance(0.5) ? 1.0 : -1.0);
			const double Dist = Script.Range(1000.0, 2500.0);
			Rig.TargetPelvis = FVector(FMath::Cos(FMath::DegreesToRadians(Off)) * Dist, FMath::Sin(FMath::DegreesToRadians(Off)) * Dist, 126);
			const double Speed = Script.Range(200.0, 400.0);
			Rig.TargetVelocity = FVector(0, Speed, 0);
			Rig.bTargetVisible = true;
			const double Start = Rig.TimeS;
			TArray<double> T;
			TArray<double> Err;
			TArray<bool> Fire;
			for (int32 Tick = 0; Tick < 150; ++Tick)
			{
				if (Tick % 45 == 44) Rig.TargetVelocity *= -1.0;
				Rig.Step();
				const double Error = Rig.TrueErrorDeg();
				T.Add(Rig.TimeS - Start);
				Err.Add(Error);
				Fire.Add((Rig.Last.Buttons & uint32(EVerseInputButton::Fire)) != 0);
				if (Tick >= 90)
				{
					SettledSum += Error;
					++SettledCount;
				}
			}
			Engagements.Add(FString::Printf(TEXT("{\"offDeg\": %.3f, \"rangeM\": %.3f, \"speedMps\": %.3f, \"t\": %s, \"errorDeg\": %s, \"fire\": %s}"),
				Off, Dist / 100.0, Speed / 100.0, *VerseBotAimTest::NumberArray(T), *VerseBotAimTest::NumberArray(Err),
				*VerseBotAimTest::BoolArray(Fire)));
		}
		const FString Json = FString::Printf(TEXT("{\"tier\": \"%s\", \"engagements\": [%s]}"), Name, *FString::Join(Engagements, TEXT(", ")));
		FFileHelper::SaveStringToFile(Json,
			*FPaths::Combine(VerseBotTierTest::ProofDir(TEXT("WP09.2")), FString::Printf(TEXT("aim_trace_%s.json"), Name)));
		MeanSettled.Add(Name, SettledSum / FMath::Max(1, SettledCount));
		AddInfo(FString::Printf(TEXT("%s: mean error after 1.5 s %.3f deg"), Name, MeanSettled[Name]));
	}
	TestTrue(TEXT("elite settles tighter than normal"), MeanSettled[TEXT("elite")] < MeanSettled[TEXT("normal")]);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

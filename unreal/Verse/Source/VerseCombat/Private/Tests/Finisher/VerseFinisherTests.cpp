#include "Combat/VerseMeleeDefinition.h"
#include "Events/VerseEventHub.h"
#include "Finisher/VerseFinisherTimeline.h"
#include "Melee/VerseMeleeComponent.h"
#include "Melee/VerseMeleeRules.h"
#include "Misc/AutomationTest.h"
#include "Tests/Melee/Fakes/VerseMeleeTestWorld.h"
#include "VerseGameplayTags.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_FINISHER_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseFinisherTest
{
	constexpr double ServerTick = 1.0 / 60.0;

	const EVerseFinisherPhase TimedPhases[] = {EVerseFinisherPhase::Takedown, EVerseFinisherPhase::Struggle,
		EVerseFinisherPhase::Kill, EVerseFinisherPhase::Recover};

	/** One lagged client of the netcode simulation (architecture 3.1: PktLag=60, variance 10, loss 1 %). */
	struct FSimClient
	{
		const TCHAR* Name;
		double FrameHz;
		double ClockErrorS;     // server-time estimate minus true server time
		double FramePhaseS;     // first frame offset
		double MaxLatencyS;     // cap for this client's one-way latency
	};

	/** Reliable, ordered arrival times for events sent at SendTimes. */
	TArray<double> Deliver(const TArray<double>& SendTimes, FVerseRng& Rng, double MaxLatencyS)
	{
		TArray<double> Out;
		double Last = -1.0e9;
		for (const double Sent : SendTimes)
		{
			double Latency = FMath::Min(Rng.Range(0.050, 0.070), MaxLatencyS);
			if (Rng.Chance(0.01))
			{
				Latency += 2.0 * Latency; // lost once, resent after a round trip
			}
			Last = FMath::Max(Last, Sent + Latency);
			Out.Add(Last);
		}
		return Out;
	}

	/** {"Phase": seconds after Start, ...} (VerseCombat does not link the Json module). */
	FString PhaseTimes(const TMap<FString, double>& Times, double Start)
	{
		TArray<FString> Parts;
		for (const TPair<FString, double>& P : Times)
		{
			Parts.Add(FString::Printf(TEXT("\"%s\": %.6f"), *P.Key, P.Value - Start));
		}
		return TEXT("{") + FString::Join(Parts, TEXT(", ")) + TEXT("}");
	}

	FString PhaseName(EVerseFinisherPhase Phase)
	{
		return StaticEnum<EVerseFinisherPhase>()->GetNameStringByValue(int64(Phase));
	}

}

// A4.3: phase times 0.25/0.9/1.8/2.1/2.5 s within 1 tick on the server and on two lagged
// clients. The clients play the timeline from the server's stamp in the Locked event.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherTimelineTest, "Verse.Combat.Finisher.Timeline", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherTimelineTest::RunTest(const FString& Parameters)
{
	using namespace VerseFinisherTest;
	TestEqual(TEXT("PhaseAt 0"), VerseFinisher::PhaseAt(0.0), EVerseFinisherPhase::Locked);
	TestEqual(TEXT("PhaseAt 0.25"), VerseFinisher::PhaseAt(0.25), EVerseFinisherPhase::Takedown);
	TestEqual(TEXT("PhaseAt 0.89"), VerseFinisher::PhaseAt(0.89), EVerseFinisherPhase::Takedown);
	TestEqual(TEXT("PhaseAt 0.9"), VerseFinisher::PhaseAt(0.9), EVerseFinisherPhase::Struggle);
	TestEqual(TEXT("PhaseAt 1.8"), VerseFinisher::PhaseAt(1.8), EVerseFinisherPhase::Kill);
	TestEqual(TEXT("PhaseAt 2.1"), VerseFinisher::PhaseAt(2.1), EVerseFinisherPhase::Recover);
	TestFalse(TEXT("not over at 2.49"), VerseFinisher::IsOver(2.49));
	TestTrue(TEXT("over at 2.5"), VerseFinisher::IsOver(2.5));

	const FSimClient Clients[] = {
		{TEXT("client_a"), 120.0, +0.003, 0.0041, 0.25},
		{TEXT("client_b"), 90.0, -0.003, 0.0077, 0.25},
	};
	const double Expected[] = {VerseFinisher::TakedownAt, VerseFinisher::StruggleAt, VerseFinisher::KillAt,
		VerseFinisher::RecoverAt, VerseFinisher::EndAt};
	const TCHAR* ExpectedNames[] = {TEXT("Takedown"), TEXT("Struggle"), TEXT("Kill"), TEXT("Recover"), TEXT("End")};

	TArray<FString> Runs;
	double WorstError = 0.0;
	const int32 RunCount = 50;
	for (int32 Run = 0; Run < RunCount; ++Run)
	{
		FVerseRng Rng(0x5EED0400ull, uint64(Run), EVerseRngSalt::Harness);
		// The press lands on a server tick.
		const double Start = 1000.0 + Rng.RangeInt(0, 600) * ServerTick;
		FVerseFinisherSession Session;
		Session.Start(Start);
		TArray<double> SendTimes = {Start};
		TMap<FString, double> ServerTimes;
		for (int32 N = 1; N < 400; ++N)
		{
			const double Now = Start + N * ServerTick;
			TArray<FVerseFinisherStep> Steps;
			const bool bReleased = Session.Advance(Now, FVerseFinisherSession::NoDeath, Steps);
			for (const FVerseFinisherStep& Step : Steps)
			{
				ServerTimes.Add(PhaseName(Step.Phase), Step.ServerTime);
				SendTimes.Add(Step.ServerTime);
			}
			if (bReleased)
			{
				ServerTimes.Add(TEXT("End"), Now);
				break;
			}
		}
		TestTrue(TEXT("server applied the kill"), Session.bKillApplied);

		FString RunObj = FString::Printf(TEXT("{\"run\": %d, \"server\": %s"), Run, *PhaseTimes(ServerTimes, Start));
		for (int32 I = 0; I < 5; ++I)
		{
			const double* Got = ServerTimes.Find(ExpectedNames[I]);
			const double Error = Got ? FMath::Abs(*Got - Start - Expected[I]) : 1.0e9;
			WorstError = FMath::Max(WorstError, Error);
			if (Error > ServerTick + 1e-9)
			{
				AddError(FString::Printf(TEXT("run %d server %s off by %.4f s"), Run, ExpectedNames[I], Error));
			}
		}

		for (const FSimClient& Client : Clients)
		{
			const TArray<double> Arrivals = Deliver(SendTimes, Rng, Client.MaxLatencyS);
			const double LockedArrives = Arrivals[0];
			TMap<FString, double> Shown;
			for (int32 K = 0; K < 2000; ++K)
			{
				const double Frame = Start - 0.05 + Client.FramePhaseS + K / Client.FrameHz;  // true server time
				if (Frame < LockedArrives)
				{
					continue;
				}
				const double Estimate = Frame + Client.ClockErrorS;
				const double Elapsed = Estimate - Start;   // SequenceStartServerTime from the event
				const FString Name = VerseFinisher::IsOver(Elapsed) ? FString(TEXT("End")) : PhaseName(VerseFinisher::PhaseAt(Elapsed));
				if (!Shown.Contains(Name))
				{
					// Phases skipped by a late Locked are shown at the receive frame.
					Shown.Add(Name, Frame);
				}
				if (Name == TEXT("End"))
				{
					break;
				}
			}
			RunObj += FString::Printf(TEXT(", \"%s\": %s"), Client.Name, *PhaseTimes(Shown, Start));
			for (int32 I = 0; I < 5; ++I)
			{
				const double* Got = Shown.Find(ExpectedNames[I]);
				const double Error = Got ? FMath::Abs(*Got - Start - Expected[I]) : 1.0e9;
				WorstError = FMath::Max(WorstError, Error);
				if (Error > ServerTick + 1e-9)
				{
					AddError(FString::Printf(TEXT("run %d %s %s off by %.4f s"), Run, Client.Name, ExpectedNames[I], Error));
				}
			}
		}
		Runs.Add(RunObj + TEXT("}"));
	}

	const FString Json = FString::Printf(TEXT("{\"test\": \"Verse.Combat.Finisher.Timeline\", \"kind\": \"simulated netcode: 60 Hz server, reliable ordered delivery 50-70 ms one way, 1 %% loss resent after a round trip, clients at 120 and 90 Hz with +-3 ms clock error\", \"tick_s\": %.6f, \"worst_error_s\": %.6f, \"runs\": [\n%s\n]}\n"),
		ServerTick, WorstError, *FString::Join(Runs, TEXT(",\n")));
	TestTrue(TEXT("timeline JSON written"), VerseWp04WriteProof(TEXT("4.3"), TEXT("finisher_timeline.json"), Json));
	AddInfo(FString::Printf(TEXT("A4.3: %d runs, worst phase error %.4f s (tick %.4f s)"), RunCount, WorstError, ServerTick));
	TestTrue(TEXT("every phase within 1 tick"), WorstError <= ServerTick + 1e-9);
	return true;
}

// A4.4 (D5): 500 seeded finishers: 100 % kill unless the attacker dies before 2.1 s; aborts
// leave the victim's health unchanged. A4.6 rides along: other damage to the victim is refused
// on every tick, damage to the attacker goes through.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherD5Test, "Verse.Combat.Finisher.D5", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherD5Test::RunTest(const FString& Parameters)
{
	using namespace VerseFinisherTest;
	int32 Kills = 0;
	int32 Aborts = 0;
	int32 Failures = 0;
	for (int32 Seed = 0; Seed < 500; ++Seed)
	{
		FVerseRng Rng(0xD5D5ull, uint64(Seed), EVerseRngSalt::Harness);
		const double Start = 50.0 + Rng.Range(0.0, 100.0);
		const float VictimHealth = float(Rng.RangeInt(1, 100));
		const bool bAttackerDies = Rng.Chance(0.5);
		const double DeathOffset = bAttackerDies ? Rng.Range(0.0, 3.0) : FVerseFinisherSession::NoDeath;
		const double TickPhase = Rng.Range(0.0, ServerTick);

		FVerseFinisherSession Session;
		Session.Start(Start);
		float Health = VictimHealth;
		double AttackerDeath = FVerseFinisherSession::NoDeath;
		bool bOtherDamageLeaked = false;
		bool bAttackerImmune = false;
		for (int32 N = 1; N < 400 && !Session.bReleased; ++N)
		{
			const double Now = Start + TickPhase + N * ServerTick;
			if (bAttackerDies && Start + DeathOffset <= Now)
			{
				AttackerDeath = Start + DeathOffset;   // FVerseDeathEvent::ServerTime
			}
			TArray<FVerseFinisherStep> Steps;
			Session.Advance(Now, AttackerDeath, Steps);
			for (const FVerseFinisherStep& Step : Steps)
			{
				if (Step.Phase == EVerseFinisherPhase::Recover && VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Finisher))
				{
					Health = 0.f;
				}
			}
			if (Session.bActive)
			{
				bOtherDamageLeaked |= VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Bolt)
					|| VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Gadget)
					|| VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Melee);
				bAttackerImmune |= !VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherAttacker, EVerseDamageSource::Bolt);
			}
		}
		const bool bShouldKill = !bAttackerDies || DeathOffset >= VerseFinisher::RecoverAt;
		bool bOk = Session.bReleased && !bOtherDamageLeaked && !bAttackerImmune;
		if (bShouldKill)
		{
			bOk &= Session.bKillApplied && !Session.bAborted && Health == 0.f;
			Kills += Session.bKillApplied ? 1 : 0;
		}
		else
		{
			bOk &= Session.bAborted && !Session.bKillApplied && Health == VictimHealth;
			Aborts += Session.bAborted ? 1 : 0;
		}
		if (!bOk && ++Failures <= 10)
		{
			AddError(FString::Printf(TEXT("seed %d: dies %d at +%.4f s, killed %d aborted %d health %g of %g"), Seed,
				bAttackerDies, DeathOffset, Session.bKillApplied, Session.bAborted, Health, VictimHealth));
		}
	}
	AddInfo(FString::Printf(TEXT("D5: 500 finishers, %d kills, %d aborts, %d failures"), Kills, Aborts, Failures));
	TestEqual(TEXT("D5 holds for every seed"), Failures, 0);
	TestTrue(TEXT("both branches exercised"), Kills > 100 && Aborts > 100);

	// The exact boundary: dying at 2.1 s or later keeps the kill, any earlier aborts.
	for (const double Offset : {2.0999, 2.1, 2.1001})
	{
		FVerseFinisherSession S;
		S.Start(0.0);
		TArray<FVerseFinisherStep> Steps;
		for (int32 N = 1; N <= 160; ++N)
		{
			S.Advance(N * ServerTick, Offset <= N * ServerTick ? Offset : FVerseFinisherSession::NoDeath, Steps);
		}
		TestEqual(FString::Printf(TEXT("attacker dies at %.4f s"), Offset), S.bKillApplied, Offset >= 2.1);
	}

	// The vulnerability table of 7.4 (A4.6).
	TestFalse(TEXT("victim: no bolt damage"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Bolt));
	TestFalse(TEXT("victim: no gadget damage"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Gadget));
	TestFalse(TEXT("victim: no world damage"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::World));
	TestTrue(TEXT("victim: the finisher's own kill"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherVictim, EVerseDamageSource::Finisher));
	TestTrue(TEXT("attacker: bolts hurt"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherAttacker, EVerseDamageSource::Bolt));
	TestTrue(TEXT("attacker: breach charge hurts"), VerseMelee::AllowsDamage(EVerseCombatPhase::FinisherAttacker, EVerseDamageSource::Gadget));
	TestFalse(TEXT("dead pawns take nothing"), VerseMelee::AllowsDamage(EVerseCombatPhase::Dead, EVerseDamageSource::Bolt));
	return true;
}

// A4.5: attacker position error at Takedown at most 5 cm, on the server and on both lagged clients.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherWarpTest, "Verse.Combat.Finisher.Warp", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherWarpTest::RunTest(const FString& Parameters)
{
	using namespace VerseFinisherTest;
	const double OffsetCm = 70.0;
	double WorstServer = 0.0;
	double WorstClient = 0.0;
	TArray<FString> Samples;
	for (int32 Seed = 0; Seed < 200; ++Seed)
	{
		FVerseRng Rng(0xA45ull, uint64(Seed), EVerseRngSalt::Harness);
		const FTransform Victim(FRotator(0.0, Rng.Range(-180.0, 180.0), 0.0), FVector(Rng.Range(-2000.0, 2000.0), Rng.Range(-2000.0, 2000.0), 88.0));
		const double Theta = Rng.Range(65.0, 180.0) * (Rng.Chance(0.5) ? 1.0 : -1.0);
		const FVector Back = Victim.GetRotation().RotateVector(FRotator(0.0, Theta, 0.0).RotateVector(FVector::ForwardVector));
		const double R = Rng.Range(40.0, 150.0);
		const FVector AttackerLoc = Victim.GetLocation() + Back * R + FVector(0.0, 0.0, Rng.Range(-60.0, 60.0));
		const FTransform Attacker((-Back).Rotation(), AttackerLoc);

		FTransform VictimPaired;
		FTransform Target;
		FVerseFinisherPose::ComputePaired(Attacker, Victim, OffsetCm, VictimPaired, Target);
		TestEqual(TEXT("target is the paired offset from the victim"), FVector::Dist2D(Target.GetLocation(), VictimPaired.GetLocation()), OffsetCm, 1e-6);
		const FVerseMeleeGeometry Paired = FVerseMeleeGeometry::Measure(Target, VictimPaired);
		TestTrue(TEXT("paired pose: attacker straight behind the victim"), Paired.ThetaDeg > 179.9 && Paired.PhiDeg < 0.1);

		// Server: warp starts at Locked (elapsed 0) and is sampled on the tick Takedown is entered.
		const double TakedownTick = FMath::CeilToDouble(VerseFinisher::TakedownAt / ServerTick - 1e-6) * ServerTick;
		const double ServerError = FVerseFinisherPose::PositionErrorCm(FVerseFinisherPose::EvaluateWarp(Attacker, 0.0, Target, TakedownTick), Target);
		WorstServer = FMath::Max(WorstServer, ServerError);

		// Two lagged clients: the attacker's local pose at receipt carries interpolation error,
		// the Locked event arrives 50-70 ms late (one client capped at the 250 ms extreme).
		for (int32 C = 0; C < 2; ++C)
		{
			const double Latency = C == 0 ? Rng.Range(0.050, 0.070) : Rng.Range(0.050, 0.250);
			const double FrameHz = C == 0 ? 120.0 : 90.0;
			const double ClockError = C == 0 ? 0.003 : -0.003;
			const FTransform LocalStart(Attacker.GetRotation(), Attacker.GetLocation() + Rng.UnitVector() * Rng.Range(0.0, 10.0));
			// First client frame at or after the server's Takedown time.
			const double Frame = FMath::CeilToDouble((VerseFinisher::TakedownAt) * FrameHz) / FrameHz;
			const double Elapsed = FMath::Max(Frame, Latency) + ClockError;
			const FTransform Pose = FVerseFinisherPose::EvaluateWarp(LocalStart, Latency + ClockError, Target, Elapsed);
			const double Error = FVerseFinisherPose::PositionErrorCm(Pose, Target);
			WorstClient = FMath::Max(WorstClient, Error);
			if (Seed < 20)
			{
				Samples.Add(FString::Printf(TEXT("{\"seed\": %d, \"client\": %d, \"latency_s\": %.4f, \"error_cm\": %.6f}"), Seed, C, Latency, Error));
			}
		}
	}
	VerseWp04WriteProof(TEXT("4.4"), TEXT("finisher_warp.json"), FString::Printf(
		TEXT("{\"test\": \"Verse.Combat.Finisher.Warp\", \"pairs\": 200, \"worst_server_error_cm\": %.6f, \"worst_client_error_cm\": %.6f, \"samples\": [\n%s\n]}\n"),
		WorstServer, WorstClient, *FString::Join(Samples, TEXT(",\n"))));
	AddInfo(FString::Printf(TEXT("A4.5: worst warp error at Takedown: server %.3f cm, clients %.3f cm"), WorstServer, WorstClient));
	TestTrue(TEXT("server error at most 5 cm"), WorstServer <= 5.0);
	TestTrue(TEXT("client error at most 5 cm"), WorstClient <= 5.0);
	return true;
}

// WP04.5: cameras. Both third person from Locked, first person with the weapon at 2.5 s;
// gore Reduced cuts to black from Takedown to Recover.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherCameraTest, "Verse.Combat.Finisher.Camera", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherCameraTest::RunTest(const FString& Parameters)
{
	for (double T = 0.0; T < 2.5 - 1e-3; T += 1.0 / 120.0)
	{
		const FVerseFinisherViewState Full = VerseFinisher::EvaluateView(T, false, EVerseGoreLevel::Full);
		if (Full.View != EVerseFinisherView::ThirdPerson || !Full.bKnifeInHand || Full.bActiveWeaponEquipped)
		{
			AddError(FString::Printf(TEXT("Full at %.3f s is not third person with the knife"), T));
		}
		const FVerseFinisherViewState Reduced = VerseFinisher::EvaluateView(T, false, EVerseGoreLevel::Reduced);
		const bool bCut = T + 1e-4 >= VerseFinisher::TakedownAt && T + 1e-4 < VerseFinisher::RecoverAt;
		const EVerseFinisherView Want = bCut ? EVerseFinisherView::Black : EVerseFinisherView::ThirdPerson;
		if (Reduced.View != Want)
		{
			AddError(FString::Printf(TEXT("Reduced at %.3f s: view %d, want %d"), T, int32(Reduced.View), int32(Want)));
		}
	}
	const FVerseFinisherViewState End = VerseFinisher::EvaluateView(2.5, false, EVerseGoreLevel::Full);
	TestEqual(TEXT("2.5 s: first person"), End.View, EVerseFinisherView::FirstPerson);
	TestTrue(TEXT("2.5 s: active weapon re-equipped"), End.bActiveWeaponEquipped);
	TestFalse(TEXT("2.5 s: knife put away"), End.bKnifeInHand);
	const FVerseFinisherViewState Aborted = VerseFinisher::EvaluateView(1.0, true, EVerseGoreLevel::Reduced);
	TestEqual(TEXT("abort: first person at once"), Aborted.View, EVerseFinisherView::FirstPerson);
	TestTrue(TEXT("abort: weapon back"), Aborted.bActiveWeaponEquipped);

	const FTransform A(FRotator::ZeroRotator, FVector(0.0, 0.0, 88.0));
	const FTransform V(FRotator::ZeroRotator, FVector(70.0, 0.0, 88.0));
	const FTransform Cam = VerseFinisher::CameraTransform(A, V, 260.0, 120.0);
	const FVector Mid(35.0, 0.0, 88.0);
	TestTrue(TEXT("camera stands off the pair"), FVector::Dist2D(Cam.GetLocation(), Mid) > 200.0);
	TestTrue(TEXT("camera is above the pair"), Cam.GetLocation().Z > Mid.Z + 100.0);
	const FVector ToMid = (Mid - Cam.GetLocation()).GetSafeNormal();
	TestTrue(TEXT("camera looks at the pair"), FVector::DotProduct(Cam.GetRotation().GetForwardVector(), ToMid) > 0.95);
	return true;
}

// WP04.6: the victim's client smooths into the paired pose on Locked.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherSnapTest, "Verse.Combat.Finisher.VictimSnap", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherSnapTest::RunTest(const FString& Parameters)
{
	const FTransform Attacker(FRotator(0.0, 10.0, 0.0), FVector(0.0, 0.0, 88.0));
	const FTransform Victim(FRotator(0.0, 140.0, 0.0), FVector(100.0, 40.0, 90.0));
	FTransform Paired;
	FTransform Target;
	FVerseFinisherPose::ComputePaired(Attacker, Victim, 70.0, Paired, Target);
	const FTransform Derived = FVerseFinisherPose::VictimFromWarpTarget(Target, 70.0, Victim.GetLocation().Z);
	TestTrue(TEXT("client derives the server's paired victim pose from WarpTarget"),
		FVerseFinisherPose::PositionErrorCm(Derived, Paired) < 1e-6 && Derived.GetRotation().Equals(Paired.GetRotation(), 1e-6));
	TestTrue(TEXT("victim keeps its location in the paired pose"), FVerseFinisherPose::PositionErrorCm(Paired, Victim) < 1e-6);

	// A client whose local victim pose is off by 12 cm and 30 deg.
	const FTransform Local(FRotator(0.0, Paired.Rotator().Yaw + 30.0, 0.0), Paired.GetLocation() + FVector(12.0, 0.0, 0.0));
	const double SnapS = 0.1;
	TestTrue(TEXT("snap starts at the local pose"), FVerseFinisherPose::PositionErrorCm(FVerseFinisherPose::EvaluateSnap(Local, Paired, 0.0, SnapS), Local) < 1e-6);
	TestTrue(TEXT("snap ends on the paired pose"), FVerseFinisherPose::PositionErrorCm(FVerseFinisherPose::EvaluateSnap(Local, Paired, SnapS, SnapS), Paired) < 1e-6);
	double Last = 1.0e9;
	double LargestStep = 0.0;
	FTransform Prev = Local;
	for (int32 I = 0; I <= 12; ++I)
	{
		const FTransform Pose = FVerseFinisherPose::EvaluateSnap(Local, Paired, I * SnapS / 12.0, SnapS);
		const double Remaining = FVerseFinisherPose::PositionErrorCm(Pose, Paired);
		TestTrue(TEXT("error shrinks monotonically"), Remaining <= Last + 1e-9);
		LargestStep = FMath::Max(LargestStep, FVerseFinisherPose::PositionErrorCm(Pose, Prev));
		Last = Remaining;
		Prev = Pose;
	}
	TestTrue(FString::Printf(TEXT("no pop: largest per-frame step %.2f cm of 12"), LargestStep), LargestStep < 2.5);
	TestTrue(TEXT("zero snap time snaps"), FVerseFinisherPose::PositionErrorCm(FVerseFinisherPose::EvaluateSnap(Local, Paired, 0.0, 0.0), Paired) < 1e-6);
	return true;
}

// End to end on a game world: press from the back, lock, phases, warp, noise, kill, release;
// invulnerability of the victim (A4.6) and an abort that leaves the victim's health unchanged.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseFinisherWorldTest, "Verse.Combat.Finisher.World", VERSE_FINISHER_TEST_FLAGS)
bool FVerseFinisherWorldTest::RunTest(const FString& Parameters)
{
	using namespace VerseFinisherTest;
	FVerseMeleeTestWorld W;
	ACharacter* Attacker = W.Spawn(FVector(0.0, 0.0, 0.0), 0.0);
	ACharacter* Victim = W.Spawn(FVector(100.0, 30.0, 0.0), 10.0);
	W.Step(3);
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	TArray<TPair<EVerseFinisherPhase, double>> Phases;
	TArray<FVerseFinisherEvent> Events;
	TArray<FVerseDeathEvent> Deaths;
	TArray<TPair<APawn*, FVerseFinisherViewState>> Views;
	int32 FinisherNoises = 0;
	Hub->OnFinisher.AddLambda([&](const FVerseFinisherEvent& E) { Phases.Emplace(E.Phase, W.Now()); Events.Add(E); });
	Hub->OnDeath.AddLambda([&](const FVerseDeathEvent& E) { Deaths.Add(E); });
	Hub->OnNoise.AddLambda([&](const FVerseNoiseEvent& E) { FinisherNoises += E.Noise == VerseTags::Noise_Finisher.GetTag() ? 1 : 0; });
	UVerseMeleeComponent* Melee = FVerseMeleeTestWorld::Melee(Attacker);
	Melee->OnFinisherView.AddLambda([&](APawn* Viewer, const FVerseFinisherViewState& S) { Views.Emplace(Viewer, S); });

	const double Start = W.Now();
	EVerseMeleeOutcome Outcome;
	TestTrue(TEXT("press accepted"), Melee->HandleMeleePress(Start, Outcome));
	TestEqual(TEXT("from the back within 1.5 m: finisher"), Outcome, EVerseMeleeOutcome::Finisher);
	TestEqual(TEXT("attacker locked"), FVerseMeleeTestWorld::State(Attacker)->Phase, EVerseCombatPhase::FinisherAttacker);
	TestEqual(TEXT("victim locked"), FVerseMeleeTestWorld::State(Victim)->Phase, EVerseCombatPhase::FinisherVictim);
	EVerseMeleeOutcome Second;
	TestFalse(TEXT("no second press during the finisher"), Melee->HandleMeleePress(W.Now(), Second));
	const FTransform WarpTarget = Events.Num() > 0 ? Events[0].WarpTarget : FTransform::Identity;

	double TakedownError = -1.0;
	bool bInvulnerabilityChecked = false;
	while (W.Now() - Start < 2.7)
	{
		W.Step();
		const double Elapsed = W.Now() - Start;
		if (TakedownError < 0.0 && Elapsed + 1e-4 >= VerseFinisher::TakedownAt)
		{
			TakedownError = FVerseFinisherPose::PositionErrorCm(Attacker->GetActorTransform(), WarpTarget);
		}
		if (!bInvulnerabilityChecked && Elapsed >= 1.0)
		{
			bInvulnerabilityChecked = true;
			FVerseHitEvent Bolt;
			Bolt.Source = EVerseDamageSource::Bolt;
			Bolt.Damage = 40.f;
			W.Port().ApplyMeleeHit(nullptr, Victim, Bolt);
			TestEqual(TEXT("A4.6: the victim takes 0 other damage"), Bolt.Damage, 0.f);
			FVerseHitEvent Shot;
			Shot.Source = EVerseDamageSource::Bolt;
			Shot.Damage = 40.f;
			W.Port().ApplyMeleeHit(nullptr, Attacker, Shot);
			TestEqual(TEXT("A4.6: the attacker takes damage normally"), Shot.Damage, 40.f);
		}
	}
	const EVerseFinisherPhase Order[] = {EVerseFinisherPhase::Locked, EVerseFinisherPhase::Takedown,
		EVerseFinisherPhase::Struggle, EVerseFinisherPhase::Kill, EVerseFinisherPhase::Recover};
	TestEqual(TEXT("five phase events"), Phases.Num(), 5);
	for (int32 I = 0; I < FMath::Min(5, Phases.Num()); ++I)
	{
		TestEqual(FString::Printf(TEXT("phase %d"), I), Phases[I].Key, Order[I]);
		const double Error = FMath::Abs(Phases[I].Value - Start - VerseFinisher::PhaseOffset(Order[I]));
		TestTrue(FString::Printf(TEXT("phase %d within 1 tick (%.4f s)"), I, Error), Error <= ServerTick + 1e-6);
		TestEqual(FString::Printf(TEXT("phase %d stamp"), I), double(Events[I].SequenceStartServerTime), Start, 1e-3);
	}
	TestTrue(FString::Printf(TEXT("A4.5 world: warp error at Takedown %.3f cm"), TakedownError), TakedownError >= 0.0 && TakedownError <= 5.0);
	TestEqual(TEXT("Noise.Finisher once, at Takedown"), FinisherNoises, 1);
	TestEqual(TEXT("one death"), Deaths.Num(), 1);
	if (Deaths.Num() == 1)
	{
		TestEqual(TEXT("cause Finisher"), Deaths[0].Cause, EVerseDamageSource::Finisher);
		TestEqual(TEXT("killer is the attacker"), Deaths[0].KillerId, VerseMelee::PlayerIdOf(Attacker));
		TestTrue(TEXT("death at 2.1 s within 1 tick"), FMath::Abs(Deaths[0].ServerTime - Start - 2.1) <= ServerTick + 1e-3);
	}
	TestEqual(TEXT("victim Dead"), FVerseMeleeTestWorld::State(Victim)->Phase, EVerseCombatPhase::Dead);
	TestEqual(TEXT("attacker released"), FVerseMeleeTestWorld::State(Attacker)->Phase, EVerseCombatPhase::Alive);
	TestEqual(TEXT("attacker kept the bolt damage"), W.Port().GetHealth(Attacker), 60.f);
	TestFalse(TEXT("finisher over"), Melee->IsInFinisher());
	bool bAttackerThird = false;
	bool bVictimThird = false;
	bool bBackToFirst = false;
	for (const TPair<APawn*, FVerseFinisherViewState>& V : Views)
	{
		bAttackerThird |= V.Key == Attacker && V.Value.View == EVerseFinisherView::ThirdPerson;
		bVictimThird |= V.Key == Victim && V.Value.View == EVerseFinisherView::ThirdPerson;
		bBackToFirst |= V.Key == Attacker && V.Value.View == EVerseFinisherView::FirstPerson && V.Value.bActiveWeaponEquipped;
	}
	TestTrue(TEXT("attacker view went third person"), bAttackerThird);
	TestTrue(TEXT("victim view went third person"), bVictimThird);
	TestTrue(TEXT("attacker back in first person with the weapon"), bBackToFirst);

	// Abort: the attacker dies at 1.0 s; the victim is released with full health.
	ACharacter* A2 = W.Spawn(FVector(0.0, 800.0, 0.0), 90.0);
	ACharacter* V2 = W.Spawn(FVector(0.0, 900.0, 0.0), 90.0);
	W.Step(2);
	Phases.Reset();
	Deaths.Reset();
	const double Start2 = W.Now();
	TestTrue(TEXT("abort case: press accepted"), FVerseMeleeTestWorld::Melee(A2)->HandleMeleePress(Start2, Outcome));
	TestEqual(TEXT("abort case: finisher"), Outcome, EVerseMeleeOutcome::Finisher);
	bool bKilledAttacker = false;
	while (W.Now() - Start2 < 2.7)
	{
		W.Step();
		if (!bKilledAttacker && W.Now() - Start2 >= 1.0)
		{
			bKilledAttacker = true;
			FVerseHitEvent Shot;
			Shot.Source = EVerseDamageSource::Bolt;
			Shot.VictimId = VerseMelee::PlayerIdOf(A2);
			Shot.Damage = 500.f;
			W.Port().ApplyMeleeHit(nullptr, A2, Shot);
		}
	}
	TestTrue(TEXT("abort event raised"), Phases.ContainsByPredicate([](const TPair<EVerseFinisherPhase, double>& P) { return P.Key == EVerseFinisherPhase::Aborted; }));
	TestFalse(TEXT("no Recover after the abort"), Phases.ContainsByPredicate([](const TPair<EVerseFinisherPhase, double>& P) { return P.Key == EVerseFinisherPhase::Recover; }));
	TestEqual(TEXT("only the attacker died"), Deaths.Num(), 1);
	TestEqual(TEXT("victim released Alive"), FVerseMeleeTestWorld::State(V2)->Phase, EVerseCombatPhase::Alive);
	TestEqual(TEXT("victim health unchanged"), W.Port().GetHealth(V2), 100.f);
	TestEqual(TEXT("attacker stays Dead"), FVerseMeleeTestWorld::State(A2)->Phase, EVerseCombatPhase::Dead);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

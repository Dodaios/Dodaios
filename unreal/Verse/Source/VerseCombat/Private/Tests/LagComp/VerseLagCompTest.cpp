#include "Misc/AutomationTest.h"
#include "Projectiles/VerseProjectileManager.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.LagComp.*: the 1 s per-bone ring buffer, the 250 ms rewind cap and lag-compensated
// bolt hits on a strafing target (A2.7).

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseLagCompRingBuffer, "Verse.Combat.LagComp.RingBuffer", VERSE_WP02_TEST_FLAGS)
bool FVerseLagCompRingBuffer::RunTest(const FString&)
{
	FVerseHitBodyHistory H;
	for (int32 I = 0; I < 200; ++I)
	{
		FVerseHitBodyPose P;
		P.Time = I / 60.0;
		P.Root.SetLocation(FVector(I * 10.0, 0, 0));
		FVerseHitCapsule& C = P.Capsules.AddDefaulted_GetRef();
		C.Bone = TEXT("Head");
		C.A = C.B = FVector(I * 10.0, 0, 170);
		C.Radius = 10.f;
		H.Push(MoveTemp(P));
	}
	TestTrue(TEXT("holds at least 1 s"), H.NewestTime() - H.OldestTime() >= 1.0);
	TestTrue(TEXT("holds no more than 1.2 s"), H.NewestTime() - H.OldestTime() <= 1.2);
	FVerseHitBodyPose Mid;
	TestTrue(TEXT("sample"), H.Sample(H.NewestTime() - 0.5 / 60.0, Mid));
	TestEqual(TEXT("interpolated between ticks"), Mid.Capsules[0].A.X, 199 * 10.0 - 5.0, 1e-6);
	FVerseHitBodyPose Old;
	H.Sample(-100.0, Old);
	TestEqual(TEXT("clamped to the oldest"), Old.Time, H.OldestTime());

	TestEqual(TEXT("rewind clamps to 250 ms"), UVerseLagCompSubsystem::ClampRewindTime(10.0, 9.7), 9.75, 1e-9);
	TestEqual(TEXT("rewind never into the future"), UVerseLagCompSubsystem::ClampRewindTime(10.0, 10.5), 10.0, 1e-9);
	TestEqual(TEXT("60 ms kept"), UVerseLagCompSubsystem::ClampRewindTime(10.0, 9.94), 9.94, 1e-9);

	// Ray against capsule: side, cap, miss, start inside.
	const FVector A(0, 0, 0), B(0, 0, 100);
	TestEqual(TEXT("side hit"), UVerseLagCompSubsystem::RayCapsule(FVector(-100, 0, 50), FVector(1, 0, 0), A, B, 10.0), 90.0, 1e-6);
	TestEqual(TEXT("cap hit"), UVerseLagCompSubsystem::RayCapsule(FVector(0, 0, 300), FVector(0, 0, -1), A, B, 10.0), 190.0, 1e-6);
	TestTrue(TEXT("miss"), UVerseLagCompSubsystem::RayCapsule(FVector(-100, 50, 50), FVector(1, 0, 0), A, B, 10.0) < 0.0);
	TestEqual(TEXT("inside"), UVerseLagCompSubsystem::RayCapsule(FVector(0, 0, 50), FVector(1, 0, 0), A, B, 10.0), 0.0);

	TestEqual(TEXT("Head zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("Head")), EVerseHitZone::Head);
	TestEqual(TEXT("Neck zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("Neck")), EVerseHitZone::Neck);
	TestEqual(TEXT("Spine_03 zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("Spine_03")), EVerseHitZone::UpperTorso);
	TestEqual(TEXT("Hips zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("Hips")), EVerseHitZone::LowerTorso);
	TestEqual(TEXT("LowerArm_L zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("LowerArm_L")), EVerseHitZone::Arm);
	TestEqual(TEXT("Calf_R zone"), UVerseLagCompSubsystem::ZoneForBone(TEXT("Calf_R")), EVerseHitZone::Leg);
	return true;
}

namespace VerseLagCompTest
{
	constexpr double StrafeCmS = 650.0; // 6.5 m/s
	constexpr double T0 = 100.0;
	const FVector Muzzle(0, 0, 135);

	struct FScene
	{
		VerseWp02Test::FTestWorld World;
		UVerseProjectileManager* Manager = nullptr;
		UVerseLagCompSubsystem* Lag = nullptr;
		APawn* Target = nullptr;
		double Now = T0;
		TArray<FVerseBoltResult> Results;

		FScene()
		{
			Manager = UVerseProjectileManager::Get(World.World);
			Lag = UVerseLagCompSubsystem::Get(World.World);
			Manager->SetManualStepping(true);
			Manager->SetClock([this]() { return Now; });
			Manager->OnBoltResolved.AddLambda([this](const FVerseBoltResult& R) { Results.Add(R); });
			Target = VerseWp02Test::SpawnTarget(World.World, RootAt(T0), 10000.f);
			Lag->RegisterTarget(Target, [this](FTransform& Root, TArray<FVerseHitCapsule>& Out)
			{
				Root = FTransform(RootAt(Now));
				VerseWp02Test::HumanCapsules(RootAt(Now), Out);
			});
		}

		static FVector RootAt(double T)
		{
			// 20 m downrange, strafing along Y (a back-and-forth every 2 s).
			const double Phase = FMath::Fmod(T - T0, 4.0);
			const double Y = Phase < 2.0 ? StrafeCmS * Phase : StrafeCmS * (4.0 - Phase);
			return FVector(2000.0, Y - 650.0, 0.0);
		}

		void Advance(double To)
		{
			while (Now + 1e-9 < To)
			{
				Now += VerseWp02Test::Tick;
				Lag->Record(Now);
				Manager->StepAll(VerseWp02Test::Tick, Now);
			}
		}

		/** The client's aim: lead the target as it shows it (pose at view time V) to where bolt and target meet. */
		static FVector AimFor(double ViewTime)
		{
			double Tau = 0.06;
			for (int32 I = 0; I < 20; ++I)
			{
				const FVector Chest = RootAt(ViewTime + Tau) + FVector(0, 0, 135);
				Tau = FVector::Dist(Chest, Muzzle) / 30000.0;
			}
			return (RootAt(ViewTime + Tau) + FVector(0, 0, 135) - Muzzle).GetSafeNormal();
		}

		/** Fires at server time S with lag L, aiming from the client's picture at ViewLag. */
		EVerseShotResult Shoot(const UVerseWeaponDefinition& W, double Lag_, double AimLag)
		{
			Results.Reset();
			FVerseFireEvent E;
			E.WeaponId = W.WeaponId;
			E.ShotCounter = 1;
			E.Origin = Muzzle;
			E.Direction = AimFor(Now - AimLag);
			Manager->SpawnBoltFrom(E, W, float(Lag_), nullptr);
			Advance(Now + 0.5);
			return Results.Num() == 1 ? Results[0].Result : EVerseShotResult::Rejected;
		}
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseLagCompRewind, "Verse.Combat.LagComp.Rewind", VERSE_WP02_TEST_FLAGS)
bool FVerseLagCompRewind::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	for (const double Lag : {0.06, 0.12, 0.25})
	{
		int32 HitsCount = 0;
		const int32 Shots = 12;
		VerseLagCompTest::FScene Scene;
		Scene.Advance(VerseLagCompTest::T0 + 1.2); // fill the ring buffer
		for (int32 I = 0; I < Shots; ++I)
		{
			// Shots across the strafe, including the turn-around points.
			Scene.Advance(Scene.Now + 0.31);
			HitsCount += Scene.Shoot(*G, Lag, Lag) == EVerseShotResult::HitBody ? 1 : 0;
		}
		TestEqual(FString::Printf(TEXT("strafing target hit at %.0f ms lag"), Lag * 1000.0), HitsCount, Shots);
		Proof->SetNumberField(FString::Printf(TEXT("hits_at_%d_ms"), int32(Lag * 1000.0 + 0.5)), HitsCount);
	}

	// 300 ms: the rewind clamps to 250 ms. Aim from the clamped picture hits; aim from the true
	// 300 ms picture lands 32.5 cm behind a 6.5 m/s target and misses the 18 cm torso.
	{
		VerseLagCompTest::FScene Scene;
		Scene.Advance(VerseLagCompTest::T0 + 0.5);
		TestEqual(TEXT("300 ms clamps to 250 ms"), UVerseLagCompSubsystem::ClampRewindTime(Scene.Now, Scene.Now - 0.3), Scene.Now - 0.25, 1e-9);
		TestEqual(TEXT("300 ms with the clamped picture hits"), Scene.Shoot(*G, 0.3, 0.25), EVerseShotResult::HitBody);
		Scene.Advance(Scene.Now + 0.1);
		TestNotEqual(TEXT("300 ms picture is not rewound past the cap"), Scene.Shoot(*G, 0.3, 0.3), EVerseShotResult::HitBody);
		Proof->SetNumberField(TEXT("clamp_ms"), 250);
	}
	VerseWp02Test::WriteProof(TEXT("2.8"), TEXT("lagcomp_rewind.json"), Proof);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

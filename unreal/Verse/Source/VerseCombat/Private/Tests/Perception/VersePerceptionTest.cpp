#include "Bot/VerseBotTier.h"
#include "Bot/VersePerceptTypes.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Noise/VerseAudibilityTable.h"
#include "Perception/VersePerceptionModel.h"
#include "Perception/VersePerceptionService.h"
#include "Serialization/MemoryWriter.h"
#include "Tests/Perception/Fakes/FakeVersePenetrationQuery.h"
#include "VerseGameplayTags.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Perception.*: the fairness boundary of contracts/bot.md 3 (WP07.1-7.4) and the
// percept-boundary acceptance tests A7.1 (F2), A7.2 (heard error) and A7.6 (perception cost).

#define VERSE_PERCEPTION_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseCombatPerceptionTests
{
	constexpr int32 ObserverId = 1;
	constexpr int32 TargetId = 2;
	constexpr float TickS = 1.f / 60.f;

	FString ProofDir(const TCHAR* SubTask)
	{
		return FPaths::ProjectSavedDir() / TEXT("Harness/proof/WP07") / SubTask;
	}

	void SaveProof(const TCHAR* SubTask, const TCHAR* File, const FString& Json)
	{
		const FString Dir = ProofDir(SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		FFileHelper::SaveStringToFile(Json, *(Dir / File));
	}

	struct FPerceptionScene
	{
		FFakeVersePenetrationQuery Sight;
		UVerseAudibilityTable* Audibility = nullptr;
		FVersePerceptionModel Model;
		FVersePerceptionObserverInput Observer;
		FVersePerceptionBody Target;
		uint32 NowMs = 1000;

		explicit FPerceptionScene(uint32 Seed = 7)
		{
			Audibility = NewObject<UVerseAudibilityTable>();
			Audibility->AddToRoot();
			FVersePerceptionProfile Profile;
			Profile.Seed = Seed;
			Model.AddObserver(ObserverId, Profile);
			Observer.Self.Location = FVector(0.0, 0.0, 0.0);
			Observer.Self.EyeLocation = FVector(0.0, 0.0, 165.0);
			Observer.Self.ViewRotation = FRotator(0.f, 0.f, 0.f);
			Target.PlayerId = TargetId;
			SetTarget(FVector(1000.0, 0.0, 95.0));
		}

		~FPerceptionScene()
		{
			Audibility->RemoveFromRoot();
		}

		void SetTarget(const FVector& Pelvis, EVerseStance Stance = EVerseStance::Stand)
		{
			Target.Pelvis = Pelvis;
			Target.Stance = Stance;
			Target.SetSamplePointsFromStance();
		}

		FVersePerceptionWorld World() const
		{
			FVersePerceptionWorld Out;
			const FFakeVersePenetrationQuery* Query = &Sight;
			Out.TestSight = [Query](const FVector& Eye, const FVector& Point) { return Query->TestSight(Eye, Point); };
			Out.Audibility = Audibility;
			return Out;
		}

		FVersePerceptFrame Tick()
		{
			NowMs += 17;
			const FVersePerceptionBody Bodies[1] = {Target};
			return Model.BuildFrame(ObserverId, Observer, Bodies, World(), NowMs, TickS);
		}

		FVerseNoiseEvent Noise(const FGameplayTag& Tag, const FVector& Location) const
		{
			FVerseNoiseEvent Event;
			Event.Noise = Tag;
			Event.SourceId = TargetId;
			Event.Location = Location;
			Event.ServerTime = float(double(NowMs) / 1000.0);
			return Event;
		}
	};

	TArray<uint8> FrameBytes(const FVersePerceptFrame& Frame)
	{
		TArray<uint8> Bytes;
		FMemoryWriter Writer(Bytes);
		FVersePerceptFrame Copy = Frame;
		FVersePerceptFrame::StaticStruct()->SerializeItem(Writer, &Copy, nullptr);
		return Bytes;
	}
}

using namespace VerseCombatPerceptionTests;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionConeTest, "Verse.Combat.Perception.Cone", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionConeTest::RunTest(const FString& Parameters)
{
	using EZone = FVersePerceptionModel::EConeZone;
	const FVector Eye(0.0, 0.0, 0.0);
	const FRotator View(0.f, 0.f, 0.f);
	const FVersePerceptionModel::FCone Hip = FVersePerceptionModel::ConeFor(false, 70.f);
	auto At = [&](float YawDeg, float PitchDeg) { return FRotator(PitchDeg, YawDeg, 0.f).Vector() * 1000.0; };

	TestEqual(TEXT("hip cone half-angle 55"), Hip.HalfAngleDeg, 55.f);
	TestTrue(TEXT("ahead is inside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(0.f, 0.f)) == EZone::Inside);
	TestTrue(TEXT("54 deg inside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(54.f, 0.f)) == EZone::Inside);
	TestTrue(TEXT("56 deg peripheral"), FVersePerceptionModel::Classify(Eye, View, Hip, At(-56.f, 0.f)) == EZone::Peripheral);
	TestTrue(TEXT("79 deg peripheral"), FVersePerceptionModel::Classify(Eye, View, Hip, At(79.f, 0.f)) == EZone::Peripheral);
	TestTrue(TEXT("81 deg outside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(81.f, 0.f)) == EZone::Outside);
	TestTrue(TEXT("behind outside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(180.f, 0.f)) == EZone::Outside);
	TestTrue(TEXT("39 deg up inside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(0.f, 39.f)) == EZone::Inside);
	TestTrue(TEXT("41 deg up outside"), FVersePerceptionModel::Classify(Eye, View, Hip, At(0.f, 41.f)) == EZone::Outside);

	const FVersePerceptionModel::FCone Ads = FVersePerceptionModel::ConeFor(true, 70.f);
	TestEqual(TEXT("ADS half-angle = half ADS FOV + 3"), Ads.HalfAngleDeg, 38.f);
	TestEqual(TEXT("ADS vertical 35"), Ads.VerticalHalfAngleDeg, 35.f);
	TestTrue(TEXT("ADS 40 deg is peripheral"), FVersePerceptionModel::Classify(Eye, View, Ads, At(40.f, 0.f)) == EZone::Peripheral);
	TestTrue(TEXT("ADS 36 deg up outside"), FVersePerceptionModel::Classify(Eye, View, Ads, At(0.f, 36.f)) == EZone::Outside);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionSightTest, "Verse.Combat.Perception.Sight", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionSightTest::RunTest(const FString& Parameters)
{
	{
		FPerceptionScene Scene;
		const FVersePerceptFrame Frame = Scene.Tick();
		if (TestEqual(TEXT("open view: one sighting"), Frame.Sightings.Num(), 1))
		{
			const FVerseSightPercept& Sight = Frame.Sightings[0];
			TestEqual(TEXT("all 8 sample points visible"), int32(Sight.VisibleMask), 0xFF);
			TestFalse(TEXT("not peripheral"), Sight.bPeripheral);
			TestEqual(TEXT("pelvis reported"), Sight.PelvisLocation, Scene.Target.Pelvis);
			TestTrue(TEXT("percept id set"), Sight.PerceptId != 0);
		}
	}
	{
		// Low cover: only head, neck, shoulders and upper torso over a 120 cm wall.
		FPerceptionScene Scene;
		Scene.Sight.AddWall(FVector(900.0, -200.0, 0.0), FVector(920.0, 200.0, 120.0));
		const FVersePerceptFrame Frame = Scene.Tick();
		if (TestEqual(TEXT("partial: one sighting"), Frame.Sightings.Num(), 1))
		{
			const uint8 Mask = Frame.Sightings[0].VisibleMask;
			TestTrue(TEXT("head visible"), (Mask & (1 << int32(EVerseSightSample::Head))) != 0);
			TestTrue(TEXT("knees hidden"), (Mask & (1 << int32(EVerseSightSample::KneeLeft))) == 0);
			TestTrue(TEXT("pelvis hidden"), (Mask & (1 << int32(EVerseSightSample::Pelvis))) == 0);
		}
	}
	{
		// Peripheral band: slow target not noticed, fast or firing target noticed.
		FPerceptionScene Scene;
		Scene.SetTarget(FRotator(0.f, 70.f, 0.f).Vector() * 1000.0 + FVector(0.0, 0.0, 95.0));
		Scene.Target.Velocity = FVector(100.0, 0.0, 0.0);
		TestEqual(TEXT("peripheral slow: unseen"), Scene.Tick().Sightings.Num(), 0);
		Scene.Target.Velocity = FVector(300.0, 0.0, 0.0);
		const FVersePerceptFrame Fast = Scene.Tick();
		if (TestEqual(TEXT("peripheral fast: seen"), Fast.Sightings.Num(), 1))
		{
			TestTrue(TEXT("flagged peripheral"), Fast.Sightings[0].bPeripheral);
		}
		Scene.Target.Velocity = FVector::ZeroVector;
		Scene.Target.bFiring = true;
		TestEqual(TEXT("peripheral firing: seen"), Scene.Tick().Sightings.Num(), 1);
	}
	{
		// Awareness: behind the observer within 2 m is noticed, at 2.5 m it is not.
		FPerceptionScene Scene;
		Scene.SetTarget(FVector(-150.0, 0.0, 95.0));
		TestEqual(TEXT("1.5 m behind: felt"), Scene.Tick().Sightings.Num(), 1);
		Scene.SetTarget(FVector(-250.0, 0.0, 95.0));
		TestEqual(TEXT("2.5 m behind: unseen"), Scene.Tick().Sightings.Num(), 0);
	}
	{
		// Dark zone: VisibilityFactor 0.5 delays the first sighting by ReactionMs mean (320 ms).
		FPerceptionScene Scene;
		FVersePerceptionWorld World = Scene.World();
		World.VisibilityFactor = [](const FVector&) { return 0.5f; };
		const FVersePerceptionBody Bodies[1] = {Scene.Target};
		int32 FirstSeenMs = -1;
		const uint32 Start = Scene.NowMs;
		for (int32 Tick = 0; Tick < 60 && FirstSeenMs < 0; ++Tick)
		{
			Scene.NowMs += 10;
			if (Scene.Model.BuildFrame(ObserverId, Scene.Observer, Bodies, World, Scene.NowMs, 0.01f).Sightings.Num() > 0)
			{
				FirstSeenMs = int32(Scene.NowMs - Start);
			}
		}
		TestTrue(TEXT("dark zone: seen after about 320 ms"), FirstSeenMs >= 320 && FirstSeenMs <= 340);
	}
	{
		// Dead bodies and the observer's own body are never sighted.
		FPerceptionScene Scene;
		Scene.Target.bAlive = false;
		TestEqual(TEXT("dead: unseen"), Scene.Tick().Sightings.Num(), 0);
		Scene.Target.bAlive = true;
		Scene.Target.PlayerId = ObserverId;
		TestEqual(TEXT("own body: unseen"), Scene.Tick().Sightings.Num(), 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionF2Test, "Verse.Combat.Perception.F2", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionF2Test::RunTest(const FString& Parameters)
{
	TMap<FString, double> Report;

	// A7.1 a: opaque piece, silent opponent: 0 sightings and 0 heard over 60 s, while the view sweeps.
	{
		FPerceptionScene Scene;
		Scene.Sight.AddWall(FVector(500.0, -400.0, 0.0), FVector(520.0, 400.0, 400.0));
		Scene.SetTarget(FVector(700.0, 0.0, 95.0));
		int32 Sightings = 0;
		int32 Heard = 0;
		for (int32 Tick = 0; Tick < 3600; ++Tick)
		{
			Scene.Observer.Self.ViewRotation.Yaw = float(FMath::Fmod(Tick * 0.5, 360.0));
			const FVersePerceptFrame Frame = Scene.Tick();
			Sightings += Frame.Sightings.Num();
			Heard += Frame.Heard.Num();
		}
		TestEqual(TEXT("A7.1 opaque: 0 sightings over 60 s"), Sightings, 0);
		TestEqual(TEXT("A7.1 opaque: 0 heard over 60 s"), Heard, 0);
		Report.Add(TEXT("opaqueSightings"), Sightings);
		Report.Add(TEXT("opaqueHeard"), Heard);
	}

	// A7.1 b: wall with a hole: seen exactly on the ticks where TestSight passes for a sample in the cone.
	{
		FPerceptionScene Scene;
		FFakeOccluder& Wall = Scene.Sight.AddWall(FVector(500.0, -600.0, 0.0), FVector(520.0, 600.0, 400.0));
		Wall.Holes.Add(FBox(FVector(495.0, -40.0, 110.0), FVector(525.0, 40.0, 190.0)));
		const FVersePerceptionModel::FCone Cone = FVersePerceptionModel::ConeFor(false, 70.f);
		int32 Seen = 0;
		int32 Mismatch = 0;
		for (int32 Tick = 0; Tick < 1200; ++Tick)
		{
			// Walks back and forth behind the wall, 4 m behind it.
			const double Y = -500.0 + FMath::Fmod(Tick * 2.0, 1000.0);
			Scene.SetTarget(FVector(900.0, Y, 95.0));
			bool bExpected = false;
			for (const FVector& Point : Scene.Target.SamplePoints)
			{
				bExpected |= FVersePerceptionModel::Classify(Scene.Observer.Self.EyeLocation, Scene.Observer.Self.ViewRotation,
					Cone, Point) == FVersePerceptionModel::EConeZone::Inside &&
					Scene.Sight.TestSight(Scene.Observer.Self.EyeLocation, Point);
			}
			const bool bSeen = Scene.Tick().Sightings.Num() > 0;
			Seen += bSeen ? 1 : 0;
			Mismatch += bSeen != bExpected ? 1 : 0;
		}
		TestEqual(TEXT("A7.1 hole: seen only when TestSight passes"), Mismatch, 0);
		TestTrue(TEXT("A7.1 hole: seen through the hole sometimes"), Seen > 0 && Seen < 1200);
		Report.Add(TEXT("holeTicksSeen"), Seen);
		Report.Add(TEXT("holeMismatches"), Mismatch);
	}

	// A7.1 c: crouch walking raises no noise event (bot.md 3.2); at 3 m for 60 s nothing is heard.
	// Walking does raise Noise.Footstep.Walk (4 m): heard at 3 m, not at 5 m.
	{
		FPerceptionScene Scene;
		Scene.Sight.AddWall(FVector(150.0, -400.0, 0.0), FVector(170.0, 400.0, 400.0));
		Scene.SetTarget(FVector(300.0, 0.0, 60.0), EVerseStance::Crouch);
		int32 CrouchHeard = 0;
		for (int32 Tick = 0; Tick < 3600; ++Tick)
		{
			CrouchHeard += Scene.Tick().Heard.Num();
		}
		TestEqual(TEXT("A7.1 crouch walk at 3 m: never heard"), CrouchHeard, 0);
		Report.Add(TEXT("crouchHeard"), CrouchHeard);

		int32 WalkHeard3 = 0;
		for (int32 Step = 0; Step < 100; ++Step)
		{
			Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Footstep_Walk, FVector(300.0, 0.0, 0.0)));
			WalkHeard3 += Scene.Tick().Heard.Num();
		}
		int32 WalkHeard5 = 0;
		for (int32 Step = 0; Step < 100; ++Step)
		{
			Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Footstep_Walk, FVector(500.0, 0.0, 0.0)));
			WalkHeard5 += Scene.Tick().Heard.Num();
		}
		TestEqual(TEXT("walk at 3 m: heard every step"), WalkHeard3, 100);
		TestEqual(TEXT("walk at 5 m: never heard (4 m range)"), WalkHeard5, 0);
		Report.Add(TEXT("walkHeardAt3m"), WalkHeard3);
		Report.Add(TEXT("walkHeardAt5m"), WalkHeard5);
	}

	FString Json = TEXT("{\n  \"test\": \"F2 percept boundary (A7.1)\",\n");
	for (const TPair<FString, double>& Item : Report)
	{
		Json += FString::Printf(TEXT("  \"%s\": %g,\n"), *Item.Key, Item.Value);
	}
	Json += FString::Printf(TEXT("  \"pass\": %s\n}\n"), HasAnyErrors() ? TEXT("false") : TEXT("true"));
	SaveProof(TEXT("7.9"), TEXT("f2_percept_boundary.json"), Json);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionHeardErrorTest, "Verse.Combat.Perception.HeardError", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionHeardErrorTest::RunTest(const FString& Parameters)
{
	// A7.2: 10,000 heard shots at random positions, half behind a wall (x 1.5). The error divided by
	// the model sd has sd 1 within 10 %; no percept equals the true location.
	FPerceptionScene Scene(1234);
	Scene.Sight.AddWall(FVector(100.0, -5000.0, 0.0), FVector(120.0, 5000.0, 3000.0));
	FVerseRng Rng(99);
	const FVersePerceptionProfile Profile = *Scene.Model.FindProfile(ObserverId);
	double SumZ2 = 0.0;
	double SumZ = 0.0;
	int32 Count = 0;
	int32 EqualTrue = 0;
	int32 SdMismatch = 0;
	int32 LevelCorrect = 0;
	int32 NoLos = 0;
	for (int32 Sample = 0; Sample < 10000; ++Sample)
	{
		const double Dist = Rng.Range(200.0, 4000.0);
		const double Angle = Rng.Range(0.0, 2.0 * UE_DOUBLE_PI);
		const FVector Truth(Dist * FMath::Cos(Angle), Dist * FMath::Sin(Angle), 100.0);
		Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Shot, Truth));
		const FVersePerceptFrame Frame = Scene.Tick();
		if (Frame.Heard.Num() != 1)
		{
			AddError(TEXT("a shot is heard across the arena"));
			return false;
		}
		const FVerseHeardPercept& Heard = Frame.Heard[0];
		const bool bLos = Scene.Sight.TestSight(Scene.Observer.Self.EyeLocation, Truth);
		NoLos += bLos ? 0 : 1;
		const double DistM = FVector::Dist(Scene.Observer.Self.EyeLocation, Truth) / 100.0;
		const double ModelSdM =
			(Profile.HearingErrorBaseM + Profile.HearingErrorPerM * DistM) * 1.0 * (bLos ? 1.0 : 1.5);
		SdMismatch += FMath::Abs(Heard.ErrorSdM - ModelSdM) > 1e-3 ? 1 : 0;
		EqualTrue += (Heard.Location.X == Truth.X && Heard.Location.Y == Truth.Y && Heard.Location.Z == Truth.Z) ? 1 : 0;
		const double Zx = (Heard.Location.X - Truth.X) / (ModelSdM * 100.0);
		const double Zy = (Heard.Location.Y - Truth.Y) / (ModelSdM * 100.0);
		SumZ2 += Zx * Zx + Zy * Zy;
		SumZ += Zx + Zy;
		Count += 2;
		LevelCorrect += Heard.LevelGuess == EVerseArenaLevel::Floor ? 1 : 0;
	}
	const double Mean = SumZ / Count;
	const double Sd = FMath::Sqrt(SumZ2 / Count - Mean * Mean);
	const double LevelRate = double(LevelCorrect) / 10000.0;
	TestTrue(FString::Printf(TEXT("A7.2 error sd ratio %.4f within 10 %% of the model"), Sd), Sd >= 0.9 && Sd <= 1.1);
	TestEqual(TEXT("A7.2 no percept equals the true location"), EqualTrue, 0);
	TestEqual(TEXT("reported sd equals the model sd"), SdMismatch, 0);
	TestTrue(TEXT("both line-of-sight cases sampled"), NoLos > 500 && NoLos < 9500);
	TestTrue(FString::Printf(TEXT("level guess correct rate %.3f about 0.9"), LevelRate), FMath::Abs(LevelRate - 0.9) < 0.015);

	SaveProof(TEXT("7.3"), TEXT("heard_error.json"),
		FString::Printf(TEXT("{\n  \"test\": \"A7.2 heard error\",\n  \"samples\": 10000,\n  \"errorSdOverModelSd\": %.5f,\n")
						TEXT("  \"meanZ\": %.5f,\n  \"equalToTruth\": %d,\n  \"noLineOfSight\": %d,\n  \"levelCorrectRate\": %.4f,\n")
						TEXT("  \"pass\": %s\n}\n"),
			Sd, Mean, EqualTrue, NoLos, LevelRate, HasAnyErrors() ? TEXT("false") : TEXT("true")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionHearingRulesTest, "Verse.Combat.Perception.Hearing", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionHearingRulesTest::RunTest(const FString& Parameters)
{
	FPerceptionScene Scene;
	// Own noises are never heard.
	FVerseNoiseEvent Own = Scene.Noise(VerseTags::Noise_Shot, FVector(100.0, 0.0, 0.0));
	Own.SourceId = ObserverId;
	Scene.Model.OnNoise(Own);
	TestEqual(TEXT("own shot not heard"), Scene.Tick().Heard.Num(), 0);

	// An unknown tag is never heard.
	Scene.Model.OnNoise(Scene.Noise(FGameplayTag(), FVector(100.0, 0.0, 0.0)));
	TestEqual(TEXT("untagged event not heard"), Scene.Tick().Heard.Num(), 0);

	// Ranges: reload 7 m, fracture scales with loudness (x 40 m).
	Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Reload, FVector(650.0, 0.0, 0.0)));
	TestEqual(TEXT("reload at 6.5 m heard"), Scene.Tick().Heard.Num(), 1);
	Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Reload, FVector(750.0, 0.0, 0.0)));
	TestEqual(TEXT("reload at 7.5 m not heard"), Scene.Tick().Heard.Num(), 0);
	FVerseNoiseEvent Fracture = Scene.Noise(VerseTags::Noise_Fracture, FVector(1500.0, 0.0, 0.0));
	Fracture.SourceId = -1;
	Fracture.Loudness = 0.5f;
	Scene.Model.OnNoise(Fracture);
	TestEqual(TEXT("tile fracture (0.5) at 15 m heard (20 m)"), Scene.Tick().Heard.Num(), 1);
	Fracture.Loudness = 0.2f;
	Scene.Model.OnNoise(Fracture);
	TestEqual(TEXT("bolt hole (0.2) at 15 m not heard (8 m)"), Scene.Tick().Heard.Num(), 0);

	// Impact: exact point, sd 0.
	Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Impact, FVector(200.0, 50.0, 30.0)));
	const FVersePerceptFrame Impact = Scene.Tick();
	if (TestEqual(TEXT("impact within 3 m heard"), Impact.Heard.Num(), 1))
	{
		TestEqual(TEXT("impact at the impact point"), Impact.Heard[0].Location, FVector(200.0, 50.0, 30.0));
		TestEqual(TEXT("impact sd 0"), Impact.Heard[0].ErrorSdM, 0.f);
	}

	// Heard Z is the guessed level's height, never the true height.
	Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Shot, FVector(800.0, 0.0, 123.0)));
	const FVersePerceptFrame Shot = Scene.Tick();
	if (TestEqual(TEXT("shot heard"), Shot.Heard.Num(), 1))
	{
		TestTrue(TEXT("Z from the level guess"), Shot.Heard[0].Location.Z != 123.0);
	}

	// Profile from the tier.
	UVerseBotTier* Tier = NewObject<UVerseBotTier>();
	if (TestTrue(TEXT("hard start values"), UVerseBotTier::ApplyStartValues(TEXT("hard"), *Tier)))
	{
		const FVersePerceptionProfile Profile = FVersePerceptionModel::MakeProfile(*Tier, 42);
		TestEqual(TEXT("hard hearing base 1.9"), Profile.HearingErrorBaseM, 1.9f);
		TestEqual(TEXT("hard hearing per m 0.065"), Profile.HearingErrorPerM, 0.065f);
		TestEqual(TEXT("hard reaction mean 270"), Profile.ReactionMs.X, 270.f);
		TestTrue(TEXT("seed carried"), Profile.Seed == 42u);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionEventsTest, "Verse.Combat.Perception.Events", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionEventsTest::RunTest(const FString& Parameters)
{
	FPerceptionScene Scene;
	Scene.SetTarget(FVector(-3000.0, 0.0, 95.0)); // behind, unseen

	// Hurt: direction toward the shooter within +-8 deg.
	FVerseHitEvent Hit;
	Hit.InstigatorId = TargetId;
	Hit.VictimId = ObserverId;
	Hit.Direction = FVector(1.0, 0.0, 0.0); // bolt flies +X, shooter is at -X
	Hit.Damage = 20.f;
	Scene.Model.OnHit(Hit);
	Scene.Model.OnHit(Hit);
	const FVersePerceptFrame Hurt = Scene.Tick();
	TestTrue(TEXT("hurt percept"), Hurt.bHasHurt);
	TestEqual(TEXT("hurt damage summed"), Hurt.Hurt.Damage, 40.f);
	const double HurtAngle = FMath::RadiansToDegrees(FMath::Acos(FVector::DotProduct(Hurt.Hurt.IncomingDirection, FVector(-1.0, 0.0, 0.0))));
	TestTrue(TEXT("hurt direction within 8 deg"), HurtAngle <= 8.0 + 1e-3);
	TestFalse(TEXT("hurt is one tick"), Scene.Tick().bHasHurt);

	// Hit markers to the instigator only; spawn-protected hits give nothing.
	FVersePerceptionProfile Profile;
	Scene.Model.AddObserver(TargetId, Profile);
	FVerseHitEvent Own;
	Own.InstigatorId = ObserverId;
	Own.VictimId = TargetId;
	Own.bHeadshot = true;
	Scene.Model.OnHit(Own);
	const FVersePerceptFrame Marker = Scene.Tick();
	if (TestEqual(TEXT("one hit marker"), Marker.Hud.Num(), 1))
	{
		TestTrue(TEXT("headshot marker"), Marker.Hud[0].Kind == EVerseHudEventKind::HeadshotMarker);
	}
	Own.bBlockedBySpawnProtection = true;
	Scene.Model.OnHit(Own);
	TestEqual(TEXT("blocked hit: no marker"), Scene.Tick().Hud.Num(), 0);

	// Kill feed and respawn feed; the victim's kill cam shows the killer's position.
	FVersePerceptionBody Killer = Scene.Target;
	FVerseDeathEvent Death;
	Death.VictimId = ObserverId;
	Death.KillerId = TargetId;
	Death.ServerTime = float(double(Scene.NowMs) / 1000.0);
	Death.RespawnAt = Death.ServerTime + 3.f;
	Scene.Model.OnDeath(Death, &Killer);
	const FVersePerceptFrame Kill = Scene.Tick();
	if (TestEqual(TEXT("kill feed entry"), Kill.Hud.Num(), 1))
	{
		TestTrue(TEXT("kind kill"), Kill.Hud[0].Kind == EVerseHudEventKind::Kill);
		TestTrue(TEXT("kill cam shows killer"), Kill.Hud[0].bKillerPositionShown);
		TestEqual(TEXT("killer position"), Kill.Hud[0].KillerPosition, Killer.Pelvis);
	}
	FVerseDeathEvent Other = Death;
	Other.VictimId = TargetId;
	Other.KillerId = ObserverId;
	Scene.Model.OnDeath(Other, nullptr);
	int32 Respawned = 0;
	for (int32 Tick = 0; Tick < 240; ++Tick)
	{
		for (const FVerseHudEvent& Hud : Scene.Tick().Hud)
		{
			Respawned += Hud.Kind == EVerseHudEventKind::OpponentRespawned && Hud.VictimId == TargetId ? 1 : 0;
		}
	}
	TestEqual(TEXT("opponent respawn in the feed once"), Respawned, 1);

	// Bolts: an opponent bolt crossing the view is seen; the observer's own bolt is not.
	FPerceptionScene Bolts;
	FVerseFireEvent Fire;
	Fire.ShooterId = TargetId;
	Fire.Origin = FVector(2000.0, -1000.0, 150.0);
	Fire.Direction = FVector(0.0, 1.0, 0.0);
	Fire.ServerTime = float(double(Bolts.NowMs) / 1000.0);
	Bolts.Model.OnFire(Fire);
	Bolts.SetTarget(FVector(-3000.0, 0.0, 95.0));
	int32 BoltPercepts = 0;
	for (int32 Tick = 0; Tick < 30; ++Tick)
	{
		BoltPercepts += Bolts.Tick().Bolts.Num();
	}
	TestTrue(TEXT("opponent bolt seen in flight"), BoltPercepts > 0);
	FPerceptionScene OwnBolt;
	Fire.ShooterId = ObserverId;
	Fire.ServerTime = float(double(OwnBolt.NowMs) / 1000.0);
	OwnBolt.Model.OnFire(Fire);
	int32 OwnPercepts = 0;
	for (int32 Tick = 0; Tick < 30; ++Tick)
	{
		OwnPercepts += OwnBolt.Tick().Bolts.Num();
	}
	TestEqual(TEXT("own bolt is no percept"), OwnPercepts, 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionDeterminismTest, "Verse.Combat.Perception.Determinism", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionDeterminismTest::RunTest(const FString& Parameters)
{
	// Same seed, same events: bit-identical frames (B5). Different seed: different hearing error.
	auto Run = [](uint32 Seed) {
		FPerceptionScene Scene(Seed);
		TArray<uint8> All;
		for (int32 Tick = 0; Tick < 600; ++Tick)
		{
			if (Tick % 7 == 0)
			{
				Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Footstep_Run, FVector(400.0, 300.0, 0.0)));
			}
			Scene.Observer.Self.ViewRotation.Yaw = float(Tick % 360);
			All.Append(FrameBytes(Scene.Tick()));
		}
		return All;
	};
	TestTrue(TEXT("same seed: identical frames"), Run(5) == Run(5));
	TestTrue(TEXT("other seed: other frames"), Run(5) != Run(6));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionCostTest, "Verse.Combat.Perception.Cost", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionCostTest::RunTest(const FString& Parameters)
{
	// A7.6: perception at most 0.15 ms per observer per tick (sight traces through the fake query;
	// the real trace cost belongs to WP03's TestSight).
	FPerceptionScene Scene;
	for (int32 Index = 0; Index < 40; ++Index)
	{
		const double X = 300.0 + Index * 70.0;
		Scene.Sight.AddWall(FVector(X, -800.0 + Index * 10.0, 0.0), FVector(X + 20.0, -700.0 + Index * 10.0, 300.0));
	}
	Scene.SetTarget(FVector(1500.0, 200.0, 95.0));
	double Best = TNumericLimits<double>::Max();
	double Total = 0.0;
	int32 Frames = 0;
	for (int32 Batch = 0; Batch < 5; ++Batch)
	{
		const double Start = FPlatformTime::Seconds();
		for (int32 Tick = 0; Tick < 600; ++Tick)
		{
			if (Tick % 10 == 0)
			{
				Scene.Model.OnNoise(Scene.Noise(VerseTags::Noise_Footstep_Sprint, FVector(800.0, 300.0, 0.0)));
			}
			Scene.Target.Velocity = FVector(450.0, 0.0, 0.0);
			Scene.Tick();
		}
		const double Elapsed = FPlatformTime::Seconds() - Start;
		Best = FMath::Min(Best, Elapsed / 600.0);
		Total += Elapsed;
		Frames += 600;
	}
	const double BestMs = Best * 1000.0;
	const double MeanMs = Total / Frames * 1000.0;
	TestTrue(FString::Printf(TEXT("A7.6 perception %.4f ms per observer per tick <= 0.15"), BestMs), BestMs <= 0.15);
	SaveProof(TEXT("7.6"), TEXT("perception_cost.json"),
		FString::Printf(TEXT("{\n  \"test\": \"A7.6 perception cost\",\n  \"msPerObserverTickBestBatch\": %.5f,\n")
						TEXT("  \"msPerObserverTickMean\": %.5f,\n  \"budgetMs\": 0.15,\n  \"occluders\": 40,\n  \"pass\": %s\n}\n"),
			BestMs, MeanMs, HasAnyErrors() ? TEXT("false") : TEXT("true")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePerceptionServiceTest, "Verse.Combat.Perception.Service", VERSE_PERCEPTION_TEST_FLAGS)

bool FVersePerceptionServiceTest::RunTest(const FString& Parameters)
{
	// WP07.1: the service exists in a game world, registers observers and sends one frame per step.
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VersePerceptionServiceTest"));
	if (!TestNotNull(TEXT("world"), World))
	{
		return false;
	}
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);

	UVersePerceptionService* Service = UVersePerceptionService::Get(World);
	if (TestNotNull(TEXT("service in a game world"), Service))
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		APlayerController* Controller = World->SpawnActor<APlayerController>(Params);
		if (TestNotNull(TEXT("controller"), Controller))
		{
			int32 Frames = 0;
			const FDelegateHandle Handle = Service->OnPerceptFrame.AddLambda(
				[&Frames, Controller](AController* Observer, const FVersePerceptFrame&) { Frames += Observer == Controller ? 1 : 0; });
			Service->RegisterObserver(Controller, FVersePerceptionProfile());
			TestTrue(TEXT("registered"), Service->IsRegistered(Controller));
			Service->StepPerception(TickS);
			Service->StepPerception(TickS);
			TestEqual(TEXT("one frame per step"), Frames, 2);
			Service->UnregisterObserver(Controller);
			TestFalse(TEXT("unregistered"), Service->IsRegistered(Controller));
			Service->StepPerception(TickS);
			TestEqual(TEXT("no frame after unregister"), Frames, 2);
			Service->OnPerceptFrame.Remove(Handle);
		}
	}

	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

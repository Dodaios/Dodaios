#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBelief.h"
#include "Learning/VerseBotMatchMemory.h"
#include "Misc/AutomationTest.h"
#include "Tests/Brain/Fakes/FakeVerseDuelSim.h"
#include "Tests/Brain/VerseBotTestProof.h"
#include "UObject/UnrealType.h"
#include "VerseGameplayTags.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// 8.9: what the memory records, its weight bound, decay and the biases' inputs.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotLearningModelTest, "Verse.Bot.Learning.Model", VERSE_BOT_TEST_FLAGS)

bool FVerseBotLearningModelTest::RunTest(const FString& Parameters)
{
	using FLayer = FVerseBotMatchMemory::ELayer;
	for (const TCHAR* Id : {TEXT("normal"), TEXT("hard"), TEXT("elite")})
	{
		UVerseBotTier* T = NewObject<UVerseBotTier>();
		UVerseBotTier::ApplyStartValues(Id, *T);
		FVerseBotMatchMemory M;
		M.Configure(*T);
		// w = LearnWeightMax x n / (n + LearnSamplesHalf), never above 0.35.
		const float W = M.Weight(T->LearnSamplesHalf);
		TestTrue(FString::Printf(TEXT("%s: w at n = half is LearnWeightMax / 2"), Id), FMath::IsNearlyEqual(W, T->LearnWeightMax * 0.5f, 1e-5f));
		TestTrue(FString::Printf(TEXT("%s: w bounded"), Id), M.Weight(1.0e9f) <= FMath::Min(T->LearnWeightMax, 0.35f) + 1e-6f);
		TestEqual(FString::Printf(TEXT("%s: w = 0 with no samples"), Id), M.Weight(0.f), 0.f);
	}
	{
		// The contract cap holds even for a tier above it.
		UVerseBotTier* T = NewObject<UVerseBotTier>();
		T->LearnWeightMax = 0.9f;
		FVerseBotMatchMemory M;
		M.Configure(*T);
		TestTrue(TEXT("cap 0.35"), M.Weight(1.0e9f) <= 0.35f + 1e-6f);
	}
	{
		UVerseBotTier* T = NewObject<UVerseBotTier>();
		UVerseBotTier::ApplyStartValues(TEXT("hard"), *T);
		FVerseBotMatchMemory M;
		M.Configure(*T);
		const FVector P(300.f, 400.f, 0.f);
		M.RecordSighting(P, 0.f, true);
		M.RecordSighting(P, 0.f, false);
		M.RecordHeard(P, 0.f);
		TestTrue(TEXT("heat weights 2 + 1 + 0.3"), FMath::IsNearlyEqual(M.Heat(FLayer::Position, P, 0.f), 3.3f, 1e-4f));
		TestTrue(TEXT("half-life decay"), FMath::IsNearlyEqual(M.Heat(FLayer::Position, P, T->HabitHalfLifeS), 1.65f, 1e-3f));
		M.RecordShotFrom(P, 0.f, true);
		TestTrue(TEXT("shooting layer"), M.HeatShare(FLayer::Shooting, P, 200.f, 0.f) > 0.99f);
		// Peek habits.
		M.RecordPeek(4, EVerseBotPeekType::LeanLeft, 10.f);
		M.RecordPeek(4, EVerseBotPeekType::LeanLeft, 11.5f);
		M.RecordPeek(9, EVerseBotPeekType::JumpPeek, 30.f);
		float N = 0.f;
		TestTrue(TEXT("peek share"), FMath::IsNearlyEqual(M.PeekShare(4, N), 2.f / 3.f, 1e-5f) && N == 2.f);
		TestTrue(TEXT("fast re-peek share"), FMath::IsNearlyEqual(M.RepeekShare(4), 0.5f, 1e-5f));
		TArray<int32> Top;
		M.TopPeekEdges(2, Top);
		TestTrue(TEXT("top peek edges"), Top.Num() == 2 && Top[0] == 4 && Top[1] == 9);
		// Routes.
		M.RecordZone(1, 0.f);
		M.RecordZone(2, 1.f);
		M.RecordZone(1, 2.f);
		M.RecordZone(2, 3.f);
		M.RecordZone(3, 4.f);
		TestTrue(TEXT("route probability"), FMath::IsNearlyEqual(M.ZoneTransitionProb(1, 2), 1.f, 1e-5f));
		TestEqual(TEXT("most likely next zone"), M.MostLikelyNextZone(2), 1);
		// Ranges: the person loses most at 10-20 m, the preferred band (12 m) stays; at 5-10 m it shifts.
		for (int32 i = 0; i < 4; ++i)
		{
			M.RecordEngagementEnd(700.f, true);
			M.RecordEngagementEnd(1500.f, false);
		}
		TestEqual(TEXT("range band stays where the person loses"), M.RangeBinShift(1200.f), 0);
		TestEqual(TEXT("range band moves toward the person's weak bin"), M.RangeBinShift(700.f), 1);
		M.RecordHabit(TEXT("slide"));
		TestEqual(TEXT("habit counter"), M.HabitCount(TEXT("slide")), 1);
		// Learning off records nothing.
		FVerseBotMatchMemory Off;
		Off.Configure(*T);
		Off.SetEnabled(false);
		Off.RecordSighting(P, 0.f, true);
		Off.RecordPeek(1, EVerseBotPeekType::StepOut, 0.f);
		TestTrue(TEXT("learning off records nothing"), Off.IsEmpty() && Off.Weight(10.f) == 0.f);
	}
	return true;
}

// A8.6 (BG9 reset and L1, world-free part): nothing carried into match 2; no reflected or
// serialisable field holds learned data.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotLearningResetTest, "Verse.Bot.Learning.Reset", VERSE_BOT_TEST_FLAGS)

bool FVerseBotLearningResetTest::RunTest(const FString& Parameters)
{
	// Match 1 against a patrol opponent fills the memory; ResetMatch empties it.
	FFakeVerseDuelSim::FConfig Cfg;
	Cfg.Seed = 77;
	FFakeVerseDuelSim Sim(TEXT("hard"), Cfg);
	Sim.Run(3 * 60 * 60);
	TestFalse(TEXT("match 1 learned something"), Sim.Brain.GetMemory().IsEmpty());
	Sim.Brain.ResetMatch();
	TestTrue(TEXT("match end drops everything"), Sim.Brain.GetMemory().IsEmpty());
	TestEqual(TEXT("audit cleared with the match"), Sim.Brain.GetFireAudit().Num(), 0);

	// Match 2 from a reset brain equals a brand-new brain on the same frames (nothing carried over).
	FFakeVerseDuelSim A(TEXT("hard"), Cfg);
	A.bRecordFrames = true;
	A.bRecordOutputs = true;
	A.Run(60 * 60);
	FVerseBotBrainCore Reused;
	FVerseBotBrainCore::FConfig C;
	C.Seed = Cfg.Seed;
	C.SelfId = FFakeVerseDuelSim::BotId;
	Reused.Init(*A.Tier, C);
	for (const FVersePerceptFrame& F : A.RecordedFrames)
	{
		Reused.Think(F, A.World);
	}
	Reused.Init(*A.Tier, C); // match end and a new match
	TArray<uint8> Out;
	for (const FVersePerceptFrame& F : A.RecordedFrames)
	{
		FVerseBotTape::AppendOutput(Out, Reused.Think(F, A.World));
	}
	TestTrue(TEXT("match 2 equals match 1 bit for bit"), Out == A.Outputs);

	// L1: the memory object has no reflected property (nothing to save, cook, replicate or bridge).
	int32 Reflected = 0;
	for (TFieldIterator<FProperty> It(UVerseBotMatchMemory::StaticClass(), EFieldIteratorFlags::ExcludeSuper); It; ++It)
	{
		++Reflected;
	}
	TestEqual(TEXT("UVerseBotMatchMemory has no reflected fields"), Reflected, 0);
	TestTrue(TEXT("UVerseBotMatchMemory is transient"), UVerseBotMatchMemory::StaticClass()->HasAnyClassFlags(CLASS_Transient));
	VerseBotTestProof::Write(TEXT("8.9"), TEXT("bg9_l1_reset.json"),
		FString::Printf(TEXT("{\n  \"gate\": \"BG9/L1 (world-free part)\",\n  \"resetEmpties\": %s,\n  \"match2EqualsMatch1\": %s,\n  \"reflectedFields\": %d\n}\n"),
			Sim.Brain.GetMemory().IsEmpty() ? TEXT("true") : TEXT("false"), Out == A.Outputs ? TEXT("true") : TEXT("false"), Reflected));
	return true;
}

// 8.9 / 7.2: the belief consumes the learned zone transitions and the 1 % heatmap prior, and a
// contact-lost engagement is no decision for the range bias.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotLearningBiasTest, "Verse.Bot.Learning.Bias", VERSE_BOT_TEST_FLAGS)

bool FVerseBotLearningBiasTest::RunTest(const FString& Parameters)
{
	UVerseBotTier* T = NewObject<UVerseBotTier>();
	T->AddToRoot();
	UVerseBotTier::ApplyStartValues(TEXT("hard"), *T);
	auto Frame = [](uint32 Ms)
	{
		FVersePerceptFrame F;
		F.ServerTimeMs = Ms;
		F.Self.Location = FVector(0.f, -5000.f, 0.f);
		F.Self.EyeLocation = FVector(0.f, -5000.f, 165.f);
		F.Self.ViewRotation = FRotator(0.f, -90.f, 0.f);
		return F;
	};
	{
		// Zone transitions: the person keeps moving from zone 1 (around the origin) to zone 2 (20 m east).
		FVerseBotMatchMemory M;
		M.Configure(*T);
		for (int32 i = 0; i < 6; ++i)
		{
			M.RecordZone(1, FVector(0.f, 0.f, 0.f), float(2 * i));
			M.RecordZone(2, FVector(2000.f, 0.f, 0.f), float(2 * i + 1));
		}
		FVerseBotCoarseBelief WithMemory, Without;
		for (FVerseBotCoarseBelief* B : {&WithMemory, &Without})
		{
			B->Reset();
			FVersePerceptFrame F = Frame(100);
			FVerseHeardPercept H;
			H.PerceptId = 1;
			H.Noise = VerseTags::Noise_Footstep_Run;
			H.Location = FVector::ZeroVector;
			H.ErrorSdM = 1.f;
			F.Heard.Add(H);
			const FVerseBotMatchMemory* Mem = B == &WithMemory ? &M : nullptr;
			B->Step(F, 0.1f, Mem, {});
			for (int32 i = 0; i < 10; ++i)
			{
				B->Step(Frame(200 + 100 * i), 0.1f, Mem, {});
			}
		}
		const float Lean = float(WithMemory.Summary().TopCenter.X - Without.Summary().TopCenter.X);
		TestTrue(FString::Printf(TEXT("belief leans toward the learned next zone (%.1f cm)"), Lean), Lean > 100.f);
	}
	{
		// Heatmap prior: a lost belief keeps 1 % of mass on the person's hottest spot, prior-only.
		FVerseBotMatchMemory M;
		M.Configure(*T);
		const FVector Hot(2000.f, 2000.f, 0.f);
		for (int32 i = 0; i < 5; ++i)
		{
			M.RecordSighting(Hot, 1.f, false);
		}
		FVerseBotCoarseBelief WithMemory, Without;
		WithMemory.Reset();
		Without.Reset();
		WithMemory.Step(Frame(1000), 0.1f, &M, {});
		Without.Step(Frame(1000), 0.1f, nullptr, {});
		const float Mass = WithMemory.MassWithin(Hot, 300.f);
		TestTrue(FString::Printf(TEXT("heatmap prior mixed in (%.4f)"), Mass), Mass > 0.005f && Mass < 0.02f);
		TestEqual(TEXT("no prior without learning"), Without.MassWithin(Hot, 300.f), 0.f);
		TestEqual(TEXT("the prior is never support"), WithMemory.SupportedMassWithin(Hot, 300.f), 0.f);
	}
	{
		// Contact lost is no decision: it does not count as a bot win in the range bin.
		FVerseBotMatchMemory M;
		M.Configure(*T);
		for (int32 i = 0; i < 4; ++i)
		{
			M.RecordEngagementEnd(700.f, true);
			M.RecordEngagementEnd(1500.f, true);
			M.RecordEngagementEnd(1500.f, false);
			// 20-35 m: the person wins only one in four, so the band moves out one bin.
			M.RecordEngagementEnd(2500.f, i == 0);
		}
		const int32 Before = M.RangeBinShift(1200.f);
		TestEqual(TEXT("range band moves toward the person's weakest bin"), Before, 1);
		for (int32 i = 0; i < 20; ++i)
		{
			M.RecordEngagementNoDecision(1500.f);
		}
		TestEqual(TEXT("no-decision engagements leave the range bias alone"), M.RangeBinShift(1200.f), Before);
		TestEqual(TEXT("no-decision engagements are counted apart"), M.NoDecisionCount(FVerseBotMatchMemory::RangeBin(1500.f)), 20);
	}
	T->RemoveFromRoot();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

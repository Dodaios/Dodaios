#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBrainCore.h"
#include "Controller/VerseBotEngineQueries.h"
#include "Misc/AutomationTest.h"
#include "Tests/Brain/Fakes/FakeVerseBotWorld.h"
#include "VerseGameplayTags.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotReactionTest
{
	constexpr uint32 TickMs = 17;

	FVersePerceptFrame BaseFrame(uint32 TimeMs, const FVector& At, const FRotator& View, float Health)
	{
		FVersePerceptFrame F;
		F.ServerTimeMs = TimeMs;
		F.Self.Health = Health;
		F.Self.MaxHealth = 100.f;
		F.Self.Magazine = 30;
		F.Self.bChambered = true;
		F.Self.Reserve = 90;
		F.Self.Location = At;
		F.Self.EyeLocation = At + FVector(0, 0, 165.f);
		F.Self.ViewRotation = View;
		F.Self.Phase = EVerseCombatPhase::Alive;
		return F;
	}

	bool SameOutput(const FVerseInputFrame& A, const FVerseInputFrame& B)
	{
		return A.Buttons == B.Buttons && A.Pressed == B.Pressed && A.Move == B.Move && A.LookDeltaDeg == B.LookDeltaDeg;
	}

	enum class EStimulus : uint8 { Sighting, CloseSighting, Hurt };

	/**
	 * Two brains, same seed: B never gets the stimulus, A gets it from tick Start on. Returns the
	 * ticks A held the stimulus back, and whether every output and state was identical meanwhile.
	 */
	struct FResult
	{
		int32 PendingTicks = 0;
		bool bIdenticalWhilePending = true;
		bool bReactedAfter = false;
	};

	FResult Run(EStimulus Stimulus, uint64 Seed, UVerseBotTier& Tier)
	{
		FFakeVerseBotWorldQueries WorldA, WorldB;
		FFakeVerseBotWorldQueries::BuildStandardArena(WorldA);
		FFakeVerseBotWorldQueries::BuildStandardArena(WorldB);
		FVerseBotBrainCore A, B;
		FVerseBotBrainCore::FConfig Config;
		Config.Seed = Seed;
		Config.SelfId = 1;
		A.Init(Tier, Config);
		B.Init(Tier, Config);
		const FVector At(-2200.f, -1700.f, 0.f);
		const FVector Opp = Stimulus == EStimulus::CloseSighting ? At + FVector(150.f, 0.f, 0.f) : At + FVector(900.f, 0.f, 0.f);
		const FRotator View(0.f, 0.f, 0.f);
		constexpr int32 Start = 60;
		FResult R;
		bool bReleased = false;
		for (int32 t = 0; t < Start + 90; ++t)
		{
			const uint32 Ms = TickMs * uint32(t + 1);
			const bool bOn = t >= Start;
			FVersePerceptFrame FB = BaseFrame(Ms, At, View, 100.f);
			FVersePerceptFrame FA = BaseFrame(Ms, At, View, (bOn && Stimulus == EStimulus::Hurt) ? 75.f : 100.f);
			if (bOn && Stimulus != EStimulus::Hurt)
			{
				FVerseSightPercept S;
				S.PerceptId = 1000 + t;
				S.PelvisLocation = Opp + FVector(0, 0, 95.f);
				S.FacingYawDeg = 180.f;
				S.VisibleMask = 0xff;
				FA.Sightings.Add(S);
			}
			if (t == Start && Stimulus == EStimulus::Hurt)
			{
				FA.bHasHurt = true;
				FA.Hurt.PerceptId = 5000;
				FA.Hurt.Damage = 25.f;
				FA.Hurt.IncomingDirection = FVector(1, 0, 0);
				FA.Hurt.ServerTimeMs = Ms;
			}
			const FVerseInputFrame OA = A.Think(FA, WorldA);
			const FVerseInputFrame OB = B.Think(FB, WorldB);
			if (!bOn)
			{
				continue;
			}
			if (A.IsReactionPending() && !bReleased)
			{
				++R.PendingTicks;
				R.bIdenticalWhilePending &= SameOutput(OA, OB) && A.GetState() == B.GetState() && A.GetDecisionCount() == B.GetDecisionCount();
			}
			else
			{
				bReleased = true;
				// The answer: a forced re-decide on release, or different input or state.
				R.bReactedAfter |= A.GetDecisionCount() != B.GetDecisionCount() || !SameOutput(OA, OB) || A.GetState() != B.GetState();
			}
		}
		return R;
	}
}

// 5.2 / 8.1: a first sighting or a hit taken changes no button and no state before the sampled
// reaction; the knife reflex at 1.5 m waits for it too.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotReactionGateTest, "Verse.Bot.Brain.ReactionGate", VERSE_BOT_TEST_FLAGS)

bool FVerseBotReactionGateTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotReactionTest;
	UVerseBotTier* Tier = NewObject<UVerseBotTier>();
	Tier->AddToRoot();
	UVerseBotTier::ApplyStartValues(TEXT("elite"), *Tier);
	Tier->KnifeChoice = 1.f;
	const int32 FloorTicks = FMath::FloorToInt32(0.6f * Tier->ReactionMs.X / float(TickMs)) - 1;
	const TCHAR* Names[3] = {TEXT("sighting"), TEXT("close sighting"), TEXT("hurt")};
	for (int32 k = 0; k < 3; ++k)
	{
		for (uint64 Seed = 1; Seed <= 5; ++Seed)
		{
			const FResult R = Run(EStimulus(k), Seed, *Tier);
			TestTrue(FString::Printf(TEXT("%s seed %llu: reaction held at least the floor (%d ticks >= %d)"), Names[k], Seed, R.PendingTicks, FloorTicks),
				R.PendingTicks >= FloorTicks);
			TestTrue(FString::Printf(TEXT("%s seed %llu: no button or state change before the reaction"), Names[k], Seed), R.bIdenticalWhilePending);
			TestTrue(FString::Printf(TEXT("%s seed %llu: the bot answers after the reaction"), Names[k], Seed), R.bReactedAfter);
		}
	}
	Tier->RemoveFromRoot();
	return true;
}

// 8.4 / 7.2: the prefire mode occurs (PrefireChance per approach) at the peek edge a fresh heard
// percept is near, and never without the roll.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotPrefireTest, "Verse.Bot.Brain.Prefire", VERSE_BOT_TEST_FLAGS)

bool FVerseBotPrefireTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotReactionTest;
	UVerseBotTier* Tier = NewObject<UVerseBotTier>();
	Tier->AddToRoot();
	UVerseBotTier::ApplyStartValues(TEXT("elite"), *Tier);
	int32 Prefires[2] = {0, 0};
	for (int32 Pass = 0; Pass < 2; ++Pass)
	{
		Tier->PrefireChance = Pass == 0 ? 1.f : 0.f;
		FFakeVerseBotWorldQueries World;
		FFakeVerseBotWorldQueries::BuildStandardArena(World);
		const FVerseBotCoverPoint* Edge = World.Cover.FindByPredicate([](const FVerseBotCoverPoint& P) { return P.EdgeId != INDEX_NONE; });
		if (!TestNotNull(TEXT("arena has a peek edge"), Edge))
		{
			break;
		}
		const FVector EdgeAt = Edge->Location;
		const FVector At = EdgeAt - Edge->Facing.GetSafeNormal2D() * 800.f;
		FRotator View = (EdgeAt + FVector(0, 0, 120.f) - (At + FVector(0, 0, 165.f))).Rotation();
		FVerseBotBrainCore Brain;
		FVerseBotBrainCore::FConfig Config;
		Config.Seed = 77;
		Config.SelfId = 1;
		Brain.Init(*Tier, Config);
		Brain.GetFireAudit().SetCaptureAll(true);
		uint32 Id = 1;
		for (int32 t = 0; t < 120; ++t)
		{
			const uint32 Ms = TickMs * uint32(t + 1);
			FVersePerceptFrame F = BaseFrame(Ms, At, View, 100.f);
			if (t % 30 == 0)
			{
				FVerseHeardPercept H;
				H.PerceptId = Id++;
				H.Noise = VerseTags::Noise_Footstep_Run;
				H.Location = EdgeAt;
				H.ErrorSdM = 0.3f;
				H.ServerTimeMs = Ms;
				F.Heard.Add(H);
			}
			const FVerseInputFrame Out = Brain.Think(F, World);
			View.Pitch = FMath::Clamp(float(View.Pitch) + Out.LookDeltaDeg.X, -89.f, 89.f);
			View.Yaw = FRotator::NormalizeAxis(float(View.Yaw) + Out.LookDeltaDeg.Y);
		}
		Prefires[Pass] = Brain.GetFireAudit().Count(EVerseBotFireMode::Prefire);
	}
	TestTrue(FString::Printf(TEXT("prefire shots with the roll passing (%d)"), Prefires[0]), Prefires[0] > 0);
	TestEqual(TEXT("no prefire without the roll"), Prefires[1], 0);
	Tier->RemoveFromRoot();
	return true;
}

// The engine stand-in's believed-intact piece rule: a segment through a piece's intact bounds is
// blocked whatever the live proxy shows.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotEngineQueriesPieceTest, "Verse.Bot.Controller.PieceBelief", VERSE_BOT_TEST_FLAGS)

bool FVerseBotEngineQueriesPieceTest::RunTest(const FString& Parameters)
{
	const FBox Wall(FVector(-50.f, -200.f, 0.f), FVector(50.f, 200.f, 300.f));
	TestTrue(TEXT("a line through the wall is blocked"), FVerseBotEngineQueries::SegmentHitsBox(Wall, FVector(-500.f, 0.f, 150.f), FVector(500.f, 0.f, 150.f)));
	TestFalse(TEXT("a line past the wall is clear"), FVerseBotEngineQueries::SegmentHitsBox(Wall, FVector(-500.f, 400.f, 150.f), FVector(500.f, 400.f, 150.f)));
	TestFalse(TEXT("a line over the wall is clear"), FVerseBotEngineQueries::SegmentHitsBox(Wall, FVector(-500.f, 0.f, 400.f), FVector(500.f, 0.f, 400.f)));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

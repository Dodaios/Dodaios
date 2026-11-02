#include "Brain/VerseBotUtility.h"
#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// 8.2: utility selection, +0.18 hysteresis, U(0, UtilityNoise) noise, 0.4 s dwell, interrupts.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotUtilityTest, "Verse.Bot.Brain.Utility", VERSE_BOT_TEST_FLAGS)

bool FVerseBotUtilityTest::RunTest(const FString& Parameters)
{
	using EState = EVerseBotState;
	float NoBonus[VerseBot::NumStates] = {};
	auto Utils = [](float Attack, float Hold, float Search)
	{
		TArray<float> U;
		U.Init(-1.f, VerseBot::NumStates);
		U[int32(EState::Attack)] = Attack;
		U[int32(EState::Hold)] = Hold;
		U[int32(EState::Search)] = Search;
		return U;
	};
	auto Run = [&](FVerseBotUtilitySelector& Sel, const TArray<float>& U, float Noise, bool bInterrupt, float Now, FVerseRng& Rng, const float (&Bonus)[VerseBot::NumStates])
	{
		float A[VerseBot::NumStates];
		for (int32 i = 0; i < VerseBot::NumStates; ++i)
		{
			A[i] = U[i];
		}
		return Sel.Decide(A, Bonus, Noise, bInterrupt, Now, Rng);
	};

	// Hysteresis: a challenger needs more than +0.18 to take over (no noise).
	{
		FVerseBotUtilitySelector Sel;
		Sel.Reset(EState::Search, 0.f);
		FVerseRng Rng(1);
		TestEqual(TEXT("0.17 better does not switch"), Run(Sel, Utils(0.67f, -1.f, 0.5f), 0.f, false, 1.f, Rng, NoBonus).State, EState::Search);
		TestEqual(TEXT("0.19 better switches"), Run(Sel, Utils(0.69f, -1.f, 0.5f), 0.f, false, 2.f, Rng, NoBonus).State, EState::Attack);
		TestEqual(TEXT("hysteresis constant"), FVerseBotUtilitySelector::Hysteresis, 0.18f);
	}
	// Dwell: inside 0.4 s no switch without an interrupt; an interrupt switches at once.
	{
		FVerseBotUtilitySelector Sel;
		Sel.Reset(EState::Search, 10.f);
		FVerseRng Rng(2);
		TestEqual(TEXT("dwell holds at 0.3 s"), Run(Sel, Utils(2.f, -1.f, 0.1f), 0.f, false, 10.3f, Rng, NoBonus).State, EState::Search);
		TestEqual(TEXT("interrupt lifts the dwell"), Run(Sel, Utils(2.f, -1.f, 0.1f), 0.f, true, 10.3f, Rng, NoBonus).State, EState::Attack);
		Sel.Reset(EState::Search, 20.f);
		TestEqual(TEXT("dwell over at 0.41 s"), Run(Sel, Utils(2.f, -1.f, 0.1f), 0.f, false, 20.41f, Rng, NoBonus).State, EState::Attack);
	}
	// A state that cannot run is left even inside the dwell.
	{
		FVerseBotUtilitySelector Sel;
		Sel.Reset(EState::Attack, 0.f);
		FVerseRng Rng(3);
		TestEqual(TEXT("unrunnable current state is left"), Run(Sel, Utils(-1.f, 0.3f, 0.2f), 0.f, false, 0.1f, Rng, NoBonus).State, EState::Hold);
	}
	// Noise: scores stay within [utility, utility + noise] and the draw stream is one per state.
	{
		FVerseBotUtilitySelector Sel;
		Sel.Reset(EState::Search, 0.f);
		FVerseRng Rng(4);
		bool bBounded = true;
		int32 Wins[3] = {};
		for (int32 i = 0; i < 10000; ++i)
		{
			Sel.Reset(EState::Flank, 0.f);
			const FVerseBotUtilitySelector::FDecision D = Run(Sel, Utils(0.5f, 0.5f, 0.5f), 0.08f, true, 1.f, Rng, NoBonus);
			for (const EState S : {EState::Attack, EState::Hold, EState::Search})
			{
				const float Sc = D.Scores[int32(S)];
				bBounded &= Sc >= 0.5f && Sc < 0.58f;
			}
			Wins[D.State == EState::Attack ? 0 : D.State == EState::Hold ? 1 : 2]++;
		}
		TestTrue(TEXT("noise within U(0, 0.08)"), bBounded);
		for (int32 w = 0; w < 3; ++w)
		{
			TestTrue(FString::Printf(TEXT("equal utilities split evenly (%d)"), Wins[w]), Wins[w] > 2900 && Wins[w] < 3800);
		}
	}
	// Bonus (forced triggers, 5.2): Attack +0.4 on acquired sight.
	{
		FVerseBotUtilitySelector Sel;
		Sel.Reset(EState::Hold, 0.f);
		FVerseRng Rng(5);
		float Bonus[VerseBot::NumStates] = {};
		Bonus[int32(EState::Attack)] = 0.4f;
		TestEqual(TEXT("acquire bonus wins over hysteresis"), Run(Sel, Utils(0.5f, 0.6f, -1.f), 0.f, true, 1.f, Rng, Bonus).State, EState::Attack);
	}
	// Determinism: same seed, same decisions.
	{
		FVerseBotUtilitySelector S1, S2;
		S1.Reset(EState::Search, 0.f);
		S2.Reset(EState::Search, 0.f);
		FVerseRng R1(99), R2(99);
		bool bSame = true;
		for (int32 i = 0; i < 1000; ++i)
		{
			const TArray<float> U = Utils(0.4f + 0.001f * float(i % 50), 0.45f, 0.42f);
			bSame &= Run(S1, U, 0.08f, false, float(i) * 0.3f, R1, NoBonus).State == Run(S2, U, 0.08f, false, float(i) * 0.3f, R2, NoBonus).State;
		}
		TestTrue(TEXT("deterministic per seed"), bSame);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

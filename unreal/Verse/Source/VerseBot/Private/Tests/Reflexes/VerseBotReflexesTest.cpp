#include "Misc/AutomationTest.h"
#include "Reflexes/VerseBotReflexes.h"
#include "Tests/Tiers/VerseBotTierTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Reflexes.*: the reflex layer of bot.md 8.3 and 5.2 (WP09.5).

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotReflexTest
{
	constexpr double Dt = 1.0 / 60.0;

	FVerseBotReflexParams Params(double Chance)
	{
		FVerseBotReflexParams P;
		P.LeanUse = Chance;
		P.CrouchPeekUse = Chance;
		P.ProneUse = Chance;
		P.SlideUse = Chance;
		P.SoundDiscipline = Chance;
		P.KnifeChoice = Chance;
		P.PistolSwitchChance = Chance;
		P.Reaction.MeanMs = 250.0;
		P.Reaction.SdMs = 40.0;
		return P;
	}

	/** Bot at the origin facing +X; the opponent at Offset (cm), facing FacingYaw. */
	FVerseBotReflexContext Close(const FVector& Offset, float FacingYaw)
	{
		FVerseBotReflexContext C;
		C.Magazine = 20;
		C.bChambered = true;
		C.bTargetVisible = true;
		C.TargetLocation = Offset;
		C.TargetFacingYawDeg = FacingYaw;
		return C;
	}

	/** Runs ticks until the reflex fires; returns the time it fired (or a negative value). */
	double RunUntil(FVerseBotReflexes& R, FVerseBotReflexContext C, EVerseBotReflex Want, double MaxS, uint32* OutPressed = nullptr)
	{
		for (double T = 0.0; T <= MaxS; T += Dt)
		{
			C.NowS = T;
			const FVerseBotReflexOutput Out = R.Tick(C);
			if (Out.Fired == Want)
			{
				if (OutPressed) *OutPressed = Out.Pressed;
				return T;
			}
		}
		return -1.0;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotReflexMeleeTest, "Verse.Bot.Reflexes.Melee", VERSE_BOT_TEST_FLAGS)
bool FVerseBotReflexMeleeTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotReflexTest;
	// Finisher: within 1.5 m behind the opponent (it faces away, theta 180), after a reaction.
	FVerseBotReflexes R;
	R.Reset(Params(0.0), 1);
	uint32 Pressed = 0;
	const double At = RunUntil(R, Close(FVector(120, 0, 0), 0.f), EVerseBotReflex::Finisher, 2.0, &Pressed);
	TestTrue(TEXT("finisher from behind"), At >= 0.0);
	TestTrue(TEXT("after a reaction time (>= 0.6 x mean)"), At >= 0.6 * 0.25 - 1.0e-9);
	TestTrue(TEXT("through a melee press"), (Pressed & uint32(EVerseInputButton::Melee)) != 0);

	// Flank (theta 90) counts too.
	R.Reset(Params(0.0), 2);
	TestTrue(TEXT("finisher from the flank"), RunUntil(R, Close(FVector(0, 120, 0), 0.f), EVerseBotReflex::Finisher, 2.0) >= 0.0);

	// Not when the ability cannot activate, not beyond 1.5 m, not against a spawn-protected opponent.
	R.Reset(Params(0.0), 3);
	FVerseBotReflexContext NoAbility = Close(FVector(120, 0, 0), 0.f);
	NoAbility.bFinisherAvailable = false;
	TestTrue(TEXT("no finisher without the ability"), RunUntil(R, NoAbility, EVerseBotReflex::Finisher, 1.0) < 0.0);
	R.Reset(Params(0.0), 4);
	TestTrue(TEXT("no finisher at 1.7 m"), RunUntil(R, Close(FVector(170, 0, 0), 0.f), EVerseBotReflex::Finisher, 1.0) < 0.0);
	R.Reset(Params(0.0), 5);
	FVerseBotReflexContext Protected = Close(FVector(120, 0, 0), 0.f);
	Protected.bTargetSpawnProtected = true;
	TestTrue(TEXT("no melee at a spawn-protected opponent"), RunUntil(R, Protected, EVerseBotReflex::Finisher, 1.0) < 0.0);

	// Front within 2 m: knife only with an empty magazine or the KnifeChoice roll.
	const FVerseBotReflexContext Front = Close(FVector(150, 0, 0), 180.f);
	R.Reset(Params(0.0), 6);
	TestTrue(TEXT("front with ammo and no knife roll: keep shooting"), RunUntil(R, Front, EVerseBotReflex::Knife, 1.0) < 0.0);
	FVerseBotReflexContext Empty = Front;
	Empty.Magazine = 0;
	Empty.bChambered = false;
	R.Reset(Params(0.0), 7);
	TestTrue(TEXT("front with an empty magazine: knife"), RunUntil(R, Empty, EVerseBotReflex::Knife, 1.0) >= 0.0);
	R.Reset(Params(1.0), 8);
	TestTrue(TEXT("front with the knife roll: knife"), RunUntil(R, Front, EVerseBotReflex::Knife, 1.0) >= 0.0);

	// KnifeChoice is drawn once per close contact.
	int32 Knives = 0;
	for (int32 Contact = 0; Contact < 2000; ++Contact)
	{
		FVerseBotReflexes Rk;
		Rk.Reset(Params(0.35), 100 + Contact);
		Knives += RunUntil(Rk, Front, EVerseBotReflex::Knife, 0.6) >= 0.0 ? 1 : 0;
	}
	AddInfo(FString::Printf(TEXT("knife share %.3f (want 0.35)"), Knives / 2000.0));
	TestTrue(TEXT("KnifeChoice share"), FMath::Abs(Knives / 2000.0 - 0.35) <= 0.035);

	// The finisher pre-empts a pending DuckOnHit and keeps its reaction clock (no second reaction).
	{
		FVerseBotReflexes Rd;
		Rd.Reset(Params(1.0), 13);
		FVerseBotReflexContext Far = Close(FVector(1500, 0, 0), 180.f);
		Far.bHitThisTick = true;
		Far.bBehindLowCover = true;
		Far.NowS = 0.0;
		const FVerseBotReflexOutput First = Rd.Tick(Far);
		TestTrue(TEXT("hit behind cover schedules a reflex, not yet fired"), First.Fired == EVerseBotReflex::None);
		// One tick later the opponent is right behind the bot's target (rear arc, 1.2 m).
		FVerseBotReflexContext Behind = Close(FVector(120, 0, 0), 0.f);
		double FinisherAt = -1.0;
		bool bDucked = false;
		for (double T = Dt; T <= 2.0; T += Dt)
		{
			Behind.NowS = T;
			const FVerseBotReflexOutput Out = Rd.Tick(Behind);
			bDucked |= Out.Fired == EVerseBotReflex::DuckOnHit;
			if (Out.Fired == EVerseBotReflex::Finisher)
			{
				FinisherAt = T;
				break;
			}
		}
		TestTrue(TEXT("finisher fires over a pending duck"), FinisherAt >= 0.0 && !bDucked);
		// Reference run with the same seed: when the duck itself would have fired. The finisher
		// keeps that clock, so it fires on the same tick instead of after a second reaction.
		FVerseBotReflexes Ref;
		Ref.Reset(Params(1.0), 13);
		Ref.Tick(Far);
		FVerseBotReflexContext Quiet = Far;
		Quiet.bHitThisTick = false;
		double DuckAt = -1.0;
		for (double T = Dt; T <= 2.0 && DuckAt < 0.0; T += Dt)
		{
			Quiet.NowS = T;
			if (Ref.Tick(Quiet).Fired == EVerseBotReflex::DuckOnHit)
			{
				DuckAt = T;
			}
		}
		AddInfo(FString::Printf(TEXT("duck would fire at %.4f s, finisher fired at %.4f s"), DuckAt, FinisherAt));
		TestTrue(TEXT("finisher keeps the duck's reaction clock"), DuckAt >= 0.0 && FMath::Abs(FinisherAt - DuckAt) < 1.0e-6);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotReflexEmptyTest, "Verse.Bot.Reflexes.PistolSwitch", VERSE_BOT_TEST_FLAGS)
bool FVerseBotReflexEmptyTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotReflexTest;
	FVerseBotReflexContext C = Close(FVector(1500, 0, 0), 180.f);
	C.Magazine = 0;
	C.bChambered = false;
	int32 Switches = 0;
	int32 Retreats = 0;
	for (int32 I = 0; I < 2000; ++I)
	{
		FVerseBotReflexes R;
		R.Reset(Params(0.6), 300 + I);
		bool bSwitched = false;
		bool bRetreat = false;
		for (double T = 0.0; T < 1.0; T += Dt)
		{
			C.NowS = T;
			const FVerseBotReflexOutput Out = R.Tick(C);
			bSwitched |= Out.Fired == EVerseBotReflex::PistolSwitch && (Out.Pressed & uint32(EVerseInputButton::SlotSecondary)) != 0;
			bRetreat |= Out.bWantRetreat;
		}
		Switches += bSwitched ? 1 : 0;
		Retreats += bRetreat ? 1 : 0;
		TestTrue(TEXT("exactly one of switch or retreat"), bSwitched != bRetreat);
	}
	AddInfo(FString::Printf(TEXT("pistol switch share %.3f (want 0.6)"), Switches / 2000.0));
	TestTrue(TEXT("PistolSwitchChance share"), FMath::Abs(Switches / 2000.0 - 0.6) <= 0.035);

	// Dead-zone case: empty magazine, opponent 1 m away in the rear arc, finisher unavailable.
	// Neither knife (front arc only) nor finisher can answer, so switch or retreat must.
	{
		FVerseBotReflexContext Rear = Close(FVector(100, 0, 0), 0.f);
		Rear.Magazine = 0;
		Rear.bChambered = false;
		Rear.bFinisherAvailable = false;
		FVerseBotReflexes Rs;
		Rs.Reset(Params(1.0), 11);
		TestTrue(TEXT("empty, rear arc, no finisher: pistol switch"), RunUntil(Rs, Rear, EVerseBotReflex::PistolSwitch, 1.0) >= 0.0);
		bool bRetreat = false;
		FVerseBotReflexes Rr;
		Rr.Reset(Params(0.0), 12);
		for (double T = 0.0; T < 1.0 && !bRetreat; T += Dt)
		{
			Rear.NowS = T;
			bRetreat = Rr.Tick(Rear).bWantRetreat;
		}
		TestTrue(TEXT("empty, rear arc, no finisher, no switch roll: retreat"), bRetreat);
	}

	FVerseBotReflexes R;
	R.Reset(Params(1.0), 9);
	C.bTargetVisible = false;
	TestTrue(TEXT("no switch without a target in sight"), RunUntil(R, C, EVerseBotReflex::PistolSwitch, 1.0) < 0.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotReflexStanceTest, "Verse.Bot.Reflexes.Stance", VERSE_BOT_TEST_FLAGS)
bool FVerseBotReflexStanceTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotReflexTest;
	auto Has = [](uint32 Bits, EVerseInputButton B) { return (Bits & uint32(B)) != 0; };

	// Lean on peeks: LeanUse per peek, toward the peek side, only while peeking.
	int32 Leans = 0;
	FVerseBotReflexes R;
	R.Reset(Params(0.6), 20);
	for (uint32 Peek = 1; Peek <= 2000; ++Peek)
	{
		FVerseBotReflexContext C;
		C.Magazine = 20;
		C.bPeeking = true;
		C.PeekId = Peek;
		C.PeekSide = (Peek % 2) ? -1 : 1;
		const uint32 First = R.Tick(C).Buttons;
		const uint32 Second = R.Tick(C).Buttons;
		TestTrue(TEXT("the lean roll holds for the whole peek"), (Has(First, EVerseInputButton::LeanLeft) || Has(First, EVerseInputButton::LeanRight))
			== (Has(Second, EVerseInputButton::LeanLeft) || Has(Second, EVerseInputButton::LeanRight)));
		if (Has(First, C.PeekSide < 0 ? EVerseInputButton::LeanLeft : EVerseInputButton::LeanRight))
		{
			++Leans;
		}
		C.bPeeking = false;
		TestFalse(TEXT("no lean when not peeking"), Has(R.Tick(C).Buttons, EVerseInputButton::LeanLeft) || Has(R.Tick(C).Buttons, EVerseInputButton::LeanRight));
	}
	AddInfo(FString::Printf(TEXT("lean share %.3f (want 0.6)"), Leans / 2000.0));
	TestTrue(TEXT("LeanUse share toward the peek side"), FMath::Abs(Leans / 2000.0 - 0.6) <= 0.035);

	// Duck when hit behind low cover, after a reaction, until the next peek.
	R.Reset(Params(1.0), 21);
	FVerseBotReflexContext Cover;
	Cover.Magazine = 20;
	Cover.bBehindLowCover = true;
	Cover.bHitThisTick = true;
	Cover.NowS = 0.0;
	TestFalse(TEXT("not before the reaction"), Has(R.Tick(Cover).Buttons, EVerseInputButton::Crouch));
	Cover.bHitThisTick = false;
	bool bDucked = false;
	for (double T = Dt; T < 1.0; T += Dt)
	{
		Cover.NowS = T;
		bDucked |= Has(R.Tick(Cover).Buttons, EVerseInputButton::Crouch);
	}
	TestTrue(TEXT("ducks behind low cover when hit"), bDucked);
	Cover.bPeeking = true;
	Cover.PeekId = 1;
	TestFalse(TEXT("rises for the peek"), Has(R.Tick(Cover).Buttons, EVerseInputButton::Crouch));

	// Prone only while holding at long range.
	R.Reset(Params(1.0), 22);
	FVerseBotReflexContext Hold;
	Hold.Magazine = 20;
	TestFalse(TEXT("no prone outside a long-range hold"), Has(R.Tick(Hold).Buttons, EVerseInputButton::Prone));
	Hold.bHoldingLongRange = true;
	Hold.HoldId = 1;
	TestTrue(TEXT("prone in a long-range hold"), Has(R.Tick(Hold).Buttons, EVerseInputButton::Prone));

	// Sound discipline: crouch-walk within 6 m, walk within 15 m, sprint beyond.
	R.Reset(Params(1.0), 23);
	FVerseBotReflexContext Move;
	Move.Magazine = 20;
	Move.bWantsMove = true;
	Move.bWantsSprint = true;
	Move.ApproachId = 1;
	Move.TopClusterDistanceM = 20.0;
	FVerseBotReflexOutput Out = R.Tick(Move);
	TestTrue(TEXT("sprints far from the belief"), Has(Out.Buttons, EVerseInputButton::Sprint) && Out.MoveScale == 1.f);
	Move.TopClusterDistanceM = 10.0;
	Out = R.Tick(Move);
	TestTrue(TEXT("walks within 15 m"), !Has(Out.Buttons, EVerseInputButton::Sprint) && Out.MoveScale == FVerseBotReflexes::WalkMoveScale);
	Move.TopClusterDistanceM = 4.0;
	Out = R.Tick(Move);
	TestTrue(TEXT("crouch-walks within 6 m"), !Has(Out.Buttons, EVerseInputButton::Sprint) && Has(Out.Buttons, EVerseInputButton::Crouch));

	// Slide to cross open ground: SlideUse per crossing, one slide each.
	R.Reset(Params(1.0), 24);
	FVerseBotReflexContext Cross;
	Cross.Magazine = 20;
	Cross.bWantsMove = true;
	Cross.bWantsSprint = true;
	Cross.bCrossingOpenGround = true;
	Cross.CrossingId = 1;
	int32 Slides = 0;
	for (int32 T = 0; T < 60; ++T)
	{
		Slides += Has(R.Tick(Cross).Pressed, EVerseInputButton::Crouch) ? 1 : 0;
	}
	TestEqual(TEXT("one slide per crossing"), Slides, 1);
	Cross.CrossingId = 2;
	TestTrue(TEXT("a new crossing may slide again"), Has(R.Tick(Cross).Pressed, EVerseInputButton::Crouch));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

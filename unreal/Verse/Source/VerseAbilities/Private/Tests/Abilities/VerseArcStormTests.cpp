#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Abilities/VerseArcSound.h"
#include "Abilities/VerseArcStorm.h"
#include "Abilities/VerseArcStormComponent.h"
#include "Events/VerseEventHub.h"
#include "Misc/CoreDelegates.h"
#include "Tests/Abilities/VerseAbilitiesTestWorld.h"

#define VERSE_ABILITIES_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseArcTest
{
	using namespace VerseAbilitiesTest;

	/** A commander on a floor with Arc Storm; hands fixed at chest height either side of the body. */
	struct FCaster
	{
		FWorld W;
		APawn* Pawn = nullptr;
		UVerseArcStormComponent* Arc = nullptr;

		FCaster()
		{
			W.AddFloor();
			Pawn = W.AddPawn(FVector(0.0, 0.0, 90.0), 0.0);
			Arc = NewObject<UVerseArcStormComponent>(Pawn, TEXT("ArcStorm"));
			Arc->SetupAttachment(Pawn->GetRootComponent());
			Arc->RegisterComponent();
			Arc->SetComponentTickEnabled(false);
			Arc->SetHandsOverride({FVector(20.0, -25.0, 130.0), FVector(20.0, 25.0, 130.0)});
		}

		void Run(double Seconds, double Dt = 1.0 / 60.0)
		{
			for (double T = 0.0; T < Seconds - 1e-9; T += Dt)
			{
				Arc->Step(float(Dt));
			}
		}

		int32 Count(FVerseArcSoundEvent::EKind Kind) const
		{
			int32 N = 0;
			for (const FVerseArcSoundEvent& E : Arc->GetSoundLog())
			{
				N += E.Kind == Kind ? 1 : 0;
			}
			return N;
		}
	};
}

// Z-06: port of the three bolt tests of `abilities/sovereign.test.ts` on the bolt's control points.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ06, "Verse.Parity.Z.06", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ06::RunTest(const FString&)
{
	using namespace VerseArc;
	// The generator is the reference's mulberry32, value for value.
	FRand Seven(7);
	TestEqual(TEXT("rng(7) #1"), double(Seven()), 0.011704753153026104, 1e-7);
	TestEqual(TEXT("rng(7) #2"), double(Seven()), 0.06195825757458806, 1e-7);
	FRand One(1);
	TestEqual(TEXT("rng(1) #1"), double(One()), 0.6270739405881613, 1e-7);

	{
		const FVector A(0.0, 0.0, 130.0);
		const FVector B(500.0, 0.0, 100.0);
		FRand Rand(7);
		const TArray<FVector> P = BoltPoints(A, B, 16, 0.3f, Rand);
		TestEqual(TEXT("16 segments are 17 points"), P.Num(), 17);
		TestTrue(TEXT("starts at the hand"), P[0].Equals(A, 0.0));
		TestTrue(TEXT("ends at the target"), P[16].Equals(B, 0.0));
	}
	{
		const FVector A(0.0, 0.0, 0.0);
		const FVector B(400.0, 0.0, 0.0);
		FRand Rand(3);
		for (const FVector& P : BoltPoints(A, B, 16, 0.3f, Rand))
		{
			TestTrue(TEXT("near the line"), FMath::Sqrt(P.Y * P.Y + P.Z * P.Z) < 400.0 * 0.3);
			TestTrue(TEXT("not behind the hand"), P.X > -50.0);
			TestTrue(TEXT("not past the target"), P.X < 450.0);
		}
	}
	{
		const FVector A(100.0, 100.0, 100.0);
		const FVector B(300.0, 200.0, 0.0);
		FRand R1(11);
		FRand R2(11);
		TestTrue(TEXT("same seed, same bolt"), BoltPoints(A, B, 8, 0.3f, R1) == BoltPoints(A, B, 8, 0.3f, R2));
		FRand R3(12);
		FRand R4(11);
		TestFalse(TEXT("another seed, another bolt"), BoltPoints(A, B, 8, 0.3f, R3) == BoltPoints(A, B, 8, 0.3f, R4));
	}
	{
		// A strike: every main bolt has the fixed segment count and leaves from a hand; none lands under the floor.
		const TArray<FVector> Hands = {FVector(0.0, -25.0, 130.0), FVector(0.0, 25.0, 130.0)};
		const FStrike S = PlanStrike(Hands, FVector(1.0, 0.0, -0.1), 0.f, 5);
		int32 Mains = 0;
		for (const FBolt& Bolt : S.Bolts)
		{
			TestTrue(TEXT("above the floor"), Bolt.Points.Last().Z >= 5.0 - 1e-3 || Bolt.Kind != FBolt::EKind::Main);
			if (Bolt.Kind == FBolt::EKind::Main)
			{
				++Mains;
				TestEqual(TEXT("main bolt segments"), Bolt.Points.Num(), Segments + 1);
				TestTrue(TEXT("leaves from a hand"), Bolt.Points[0].Equals(Hands[0]) || Bolt.Points[0].Equals(Hands[1]));
				TestTrue(TEXT("within reach"), FVector::Dist(Bolt.Points[0], Bolt.Points.Last()) < ReachCm * 1.2);
			}
		}
		TestEqual(TEXT("three main bolts per hand"), Mains, 2 * BoltsPerHand);
		TestTrue(TEXT("lands ahead of the hands"), S.Impact.X > 200.0);
		const FStrike Again = PlanStrike(Hands, FVector(1.0, 0.0, -0.1), 0.f, 5);
		TestTrue(TEXT("same seed, same strike"), Again.Bolts.Num() == S.Bolts.Num() && Again.Bolts.Last().Points == S.Bolts.Last().Points);
	}
	return true;
}

// Z-08: the colours follow the palette (no violet, no cyan); the screenshot half is GPU (Verse.Visual.Abilities).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ08, "Verse.Parity.Z.08", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ08::RunTest(const FString&)
{
	using namespace VerseArc;
	// The check itself: violet and cyan are banned, amber and a cool white are not.
	TestTrue(TEXT("violet is banned"), IsBannedHue(FLinearColor::FromSRGBColor(FColor(0xa0, 0x20, 0xf0))));
	TestTrue(TEXT("cyan is banned"), IsBannedHue(FLinearColor::FromSRGBColor(FColor(0x00, 0xe5, 0xff))));
	TestFalse(TEXT("core colour allowed"), IsBannedHue(CoreColor()));
	TestFalse(TEXT("glow colour allowed"), IsBannedHue(GlowColor()));
	const FLinearColor CoreHsv = FLinearColor::FromSRGBColor(CoreColor().ToFColorSRGB()).LinearRGBToHSV();
	TestTrue(TEXT("core is a near-white"), CoreHsv.G < 0.2f && CoreHsv.B > 0.9f);
	const FColor Glow = GlowColor().ToFColorSRGB();
	const FLinearColor GlowHsv = FLinearColor(Glow.R / 255.f, Glow.G / 255.f, Glow.B / 255.f).LinearRGBToHSV();
	TestTrue(TEXT("glow is amber (hue 20-50)"), GlowHsv.R >= 20.f && GlowHsv.R <= 50.f);
	return true;
}

// Z-05: hold F -> the level rises, both hands emit, the aim follows the view at eye level (the
// body's facing in overview); release -> it fades.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ05, "Verse.Parity.Z.05", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ05::RunTest(const FString&)
{
	VerseArcTest::FCaster C;
	if (!TestNotNull(TEXT("world"), C.W.World))
	{
		return false;
	}
	C.Run(0.5);
	TestEqual(TEXT("idle: level 0"), C.Arc->GetLevel(), 0.f);
	TestEqual(TEXT("idle: nothing drawn"), C.Arc->GetDrawnSegments(), 0);

	C.Arc->SetHeld(true);
	C.Run(0.09);
	TestTrue(TEXT("level rises while held"), C.Arc->GetLevel() > 0.4f && C.Arc->GetLevel() < 0.6f);
	TestFalse(TEXT("no bolts before the arms are up"), C.Arc->IsStriking());
	C.Run(0.12);
	TestEqual(TEXT("full after 0.18 s"), C.Arc->GetLevel(), 1.f);
	TestTrue(TEXT("bolts out"), C.Arc->IsStriking());
	const int32 Before = C.Arc->GetStrikeCount();
	C.Run(1.0);
	const int32 PerSecond = C.Arc->GetStrikeCount() - Before;
	TestTrue(FString::Printf(TEXT("re-strikes many times a second (%d)"), PerSecond), PerSecond >= 14 && PerSecond <= 30);
	TestTrue(TEXT("segments drawn"), C.Arc->GetDrawnSegments() > 100);
	TestTrue(TEXT("hand light lit"), C.Arc->GetHandLightIntensity() > 0.f);

	// Both hands emit.
	const TArray<FVector> Hands = C.Arc->GetHands();
	int32 FromHand[2] = {0, 0};
	for (const VerseArc::FBolt& Bolt : C.Arc->GetLastStrike().Bolts)
	{
		if (Bolt.Kind == VerseArc::FBolt::EKind::Main)
		{
			FromHand[0] += Bolt.Points[0].Equals(Hands[0]) ? 1 : 0;
			FromHand[1] += Bolt.Points[0].Equals(Hands[1]) ? 1 : 0;
		}
	}
	TestEqual(TEXT("left hand bolts"), FromHand[0], VerseArc::BoltsPerHand);
	TestEqual(TEXT("right hand bolts"), FromHand[1], VerseArc::BoltsPerHand);

	// Aim: the view at eye level, with a controller.
	APlayerController* Pc = C.W.Possess(C.Pawn);
	Pc->SetControlRotation(FRotator(-8.0, 40.0, 0.0));
	TestTrue(TEXT("aim follows the view"), C.Arc->GetAim().Equals(FRotator(-8.0, 40.0, 0.0).Vector(), 1e-4));
	C.Run(0.1);
	const FVector Toward = (C.Arc->GetLastStrike().Impact - C.Arc->GetLastStrike().HandsMid).GetSafeNormal2D();
	TestTrue(TEXT("bolts land toward the view"), FVector::DotProduct(Toward, FRotator(0.0, 40.0, 0.0).Vector()) > 0.85);
	// Overview: the body's facing, level, whatever the view.
	C.Arc->SetAimMode(EVerseArcAim::Facing);
	C.Pawn->SetActorRotation(FRotator(0.0, -70.0, 0.0));
	TestTrue(TEXT("aim follows the facing"), C.Arc->GetAim().Equals(FRotator(0.0, -70.0, 0.0).Vector(), 1e-4));

	// Release: it fades within 0.12 s and draws nothing.
	C.Arc->SetHeld(false);
	C.Run(0.05);
	TestFalse(TEXT("bolts stop at once"), C.Arc->IsStriking());
	TestTrue(TEXT("level falling"), C.Arc->GetLevel() > 0.f && C.Arc->GetLevel() < 1.f);
	C.Run(0.1);
	TestEqual(TEXT("faded"), C.Arc->GetLevel(), 0.f);
	TestEqual(TEXT("nothing drawn"), C.Arc->GetDrawnSegments(), 0);
	C.Run(0.3);
	TestTrue(TEXT("light died away"), C.Arc->GetHandLightIntensity() < 1.f);
	return true;
}

// Z-07: the sound log has the hum on press, a crackle per strike tied to the level, a stop on
// release; the synth is silent at level 0 and the crackle is louder than the hum alone.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ07, "Verse.Parity.Z.07", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ07::RunTest(const FString&)
{
	using EKind = FVerseArcSoundEvent::EKind;
	VerseArcTest::FCaster C;
	C.Arc->SetHeld(true);
	C.Run(1.0 / 60.0);
	TestTrue(TEXT("hum on press"), C.Arc->GetSoundLog().Num() == 1 && C.Arc->GetSoundLog()[0].Kind == EKind::HumOn);
	C.Run(1.0);
	TestEqual(TEXT("one crackle per strike"), C.Count(EKind::Crackle), C.Arc->GetStrikeCount());
	for (const FVerseArcSoundEvent& E : C.Arc->GetSoundLog())
	{
		if (E.Kind == EKind::Crackle)
		{
			TestTrue(TEXT("crackle tied to the level"), E.Value >= 0.25f * VerseArc::OnLevel && E.Value <= 1.15f);
		}
	}
	TestEqual(TEXT("no stop while held"), C.Count(EKind::Stop), 0);
	C.Arc->SetHeld(false);
	C.Run(0.3);
	TestEqual(TEXT("stop on release"), C.Count(EKind::Stop), 1);
	TestEqual(TEXT("log ends with the stop"), C.Arc->GetSoundLog().Last().Kind, EKind::Stop);

	auto Rms = [](FVerseArcSynth& Synth, int32 Samples)
	{
		TArray<float> Buffer;
		Buffer.SetNumZeroed(Samples);
		Synth.Render(Buffer.GetData(), Samples);
		double Sum = 0.0;
		for (int32 I = Samples / 2; I < Samples; ++I)
		{
			Sum += double(Buffer[I]) * Buffer[I];
		}
		return FMath::Sqrt(Sum / (Samples - Samples / 2));
	};
	FVerseArcSynth Silent;
	Silent.SetTargets(0.f, 1.f, 0.45f);
	TestTrue(TEXT("silent at level 0"), Rms(Silent, 9600) < 1e-4);
	FVerseArcSynth HumOnly;
	HumOnly.SetTargets(1.f, 0.f, 0.45f);
	const double Hum = Rms(HumOnly, 9600);
	TestTrue(TEXT("the hum sounds"), Hum > 1e-3);
	FVerseArcSynth Crackling;
	Crackling.SetTargets(1.f, 1.f, 0.45f);
	TestTrue(TEXT("a strike's crackle is louder"), Rms(Crackling, 9600) > Hum * 1.2);
	return true;
}

// Arena on: F does nothing and a held storm drops at once (the Arc Storm half of Z-10).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesArcArena, "Verse.Abilities.ArcStorm.ArenaOff", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseAbilitiesArcArena::RunTest(const FString&)
{
	VerseArcTest::FCaster C;
	C.Arc->SetHeld(true);
	C.Run(0.3);
	TestTrue(TEXT("striking on the deck"), C.Arc->IsStriking());
	FVerseArenaSwitchEvent On;
	On.bArenaOn = true;
	On.Deck = TEXT("hangar");
	UVerseEventHub* Hub = UVerseEventHub::Get(C.W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	Hub->OnArenaSwitch.Broadcast(On);
	TestFalse(TEXT("off in the arena"), C.Arc->IsAllowed());
	TestEqual(TEXT("level dropped"), C.Arc->GetLevel(), 0.f);
	TestEqual(TEXT("nothing drawn"), C.Arc->GetDrawnSegments(), 0);
	C.Arc->SetHeld(true);
	C.Run(0.5);
	TestEqual(TEXT("F does nothing in the arena"), C.Arc->GetLevel(), 0.f);
	FVerseArenaSwitchEvent Off;
	Hub->OnArenaSwitch.Broadcast(Off);
	C.Arc->SetHeld(true);
	C.Run(0.3);
	TestTrue(TEXT("back on the deck"), C.Arc->IsStriking());
	return true;
}

// K-07 (Arc Storm part): losing focus releases the held key, so the storm stops.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesArcFocus, "Verse.Abilities.ArcStorm.FocusLoss", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseAbilitiesArcFocus::RunTest(const FString&)
{
	VerseArcTest::FCaster C;
	C.Arc->SetHeld(true);
	C.Run(0.3);
	TestTrue(TEXT("striking"), C.Arc->IsStriking());
	FCoreDelegates::ApplicationWillDeactivateDelegate.Broadcast();
	TestFalse(TEXT("released on focus loss"), C.Arc->IsHeld());
	C.Run(0.3);
	TestEqual(TEXT("faded"), C.Arc->GetLevel(), 0.f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

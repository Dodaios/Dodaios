#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Abilities/VerseArcStormComponent.h"
#include "Abilities/VerseHoverboard.h"
#include "Abilities/VerseHoverboardComponent.h"
#include "Events/VerseEventHub.h"
#include "Tests/Abilities/VerseAbilitiesTestWorld.h"

#define VERSE_ABILITIES_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBoardTest
{
	using namespace VerseAbilitiesTest;

	/** A commander (a plain character) standing on a floor (feet at z = 0) with the board, a wall at x = 600. */
	struct FRider
	{
		FWorld W;
		ACharacter* Pawn = nullptr;
		UVerseHoverboardComponent* Board = nullptr;
		UVerseArcStormComponent* Arc = nullptr;

		FRider()
		{
			W.AddFloor();
			W.AddBox(FVector(620.0, 0.0, 150.0), FVector(40.0, 2000.0, 300.0));
			Pawn = W.AddCharacter(FVector(0.0, 0.0, 0.0), 0.0);
			Board = NewObject<UVerseHoverboardComponent>(Pawn, TEXT("Hoverboard"));
			Board->SetupAttachment(Pawn->GetRootComponent());
			Board->RegisterComponent();
			Board->SetComponentTickEnabled(false);
			Arc = NewObject<UVerseArcStormComponent>(Pawn, TEXT("ArcStorm"));
			Arc->SetupAttachment(Pawn->GetRootComponent());
			Arc->RegisterComponent();
			Arc->SetComponentTickEnabled(false);
			Arc->SetHandsOverride({FVector(20.0, -25.0, 130.0), FVector(20.0, 25.0, 130.0)});
		}

		/** `Seconds` of riding with `Dir` held (zero coasts). */
		double FeetZ() const { return Pawn->GetActorLocation().Z - Pawn->GetCapsuleComponent()->GetScaledCapsuleHalfHeight(); }

		void Ride(double Seconds, FVector2D Dir, bool bBoost = false, double Dt = 1.0 / 60.0)
		{
			for (double T = 0.0; T < Seconds - 1e-9; T += Dt)
			{
				Board->SetMoveInput(Dir, bBoost);
				Board->Step(float(Dt));
				Arc->Step(float(Dt));
			}
		}
	};
}

// Z-09: port of `actors/hoverboard.test.ts`, top speed 550 cm/s +- 5 % on a real ride, the notice keys.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ09, "Verse.Parity.Z.09", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ09::RunTest(const FString&)
{
	using namespace VerseBoard;
	// Rides several times faster than a walk, and faster still with Shift.
	TestEqual(TEXT("cruise"), BoardSpeed(false), SpeedCm);
	TestEqual(TEXT("boost"), BoardSpeed(true), BoostCm);
	TestTrue(TEXT("over 3.5 walks"), SpeedCm > WalkCm * 3.5f);
	TestTrue(TEXT("boost is faster"), BoostCm > SpeedCm);
	{
		// Speeds up toward the held direction and reaches cruising speed within about a second.
		const FVector2D Dir(0.0, -1.0);
		FVector2D V = Glide(FVector2D::ZeroVector, &Dir, false, 1.f / 60.f);
		TestTrue(TEXT("moves the held way"), V.Y < 0.0);
		TestTrue(TEXT("gently at first"), FMath::Abs(V.Y) < SpeedCm * 0.1f);
		for (int32 I = 0; I < 60; ++I)
		{
			V = Glide(V, &Dir, false, 1.f / 60.f);
		}
		TestTrue(TEXT("near cruise after a second"), FMath::Abs(V.Y) > SpeedCm * 0.9f);
		TestEqual(TEXT("no sideways drift"), V.X, 0.0);
	}
	{
		// Coasts to a full stop once the keys are let go.
		FVector2D V = Glide(FVector2D(SpeedCm, 0.0), nullptr, false, 0.1f);
		TestTrue(TEXT("coasting"), V.X > 0.0 && V.X < SpeedCm);
		for (int32 I = 0; I < 300; ++I)
		{
			V = Glide(V, nullptr, false, 1.f / 60.f);
		}
		TestTrue(TEXT("stopped"), V.IsZero());
	}
	{
		// Loses the speed it could not travel against a wall; sliding along keeps the part that moved.
		TestTrue(TEXT("wall eats it"), Absorb(FVector2D(500.0, 0.0), FVector2D(50.0, 0.0), FVector2D::ZeroVector, 0.1f).IsZero());
		TestTrue(TEXT("free run keeps it"), Absorb(FVector2D(500.0, 0.0), FVector2D(50.0, 0.0), FVector2D(50.0, 0.0), 0.1f) == FVector2D(500.0, 0.0));
		const FVector2D Slide = Absorb(FVector2D(400.0, 300.0), FVector2D(40.0, 30.0), FVector2D(40.0, 0.0), 0.1f);
		TestEqual(TEXT("slide keeps x"), Slide.X, 400.0, 1e-3);
		TestEqual(TEXT("slide drops y"), Slide.Y, 0.0, 1e-3);
	}
	{
		// Folds out and away over a short beat, at once with reduced motion.
		float S = DeployStep(0.f, true, 0.1f, false);
		TestTrue(TEXT("unfolding"), S > 0.f && S < 1.f);
		for (int32 I = 0; I < 10; ++I)
		{
			S = DeployStep(S, true, 0.1f, false);
		}
		TestEqual(TEXT("out"), S, 1.f);
		TestEqual(TEXT("away"), DeployStep(S, false, 1.f, false), 0.f);
		TestEqual(TEXT("reduced: at once"), DeployStep(0.f, true, 0.001f, true), 1.f);
		TestEqual(TEXT("scale 0"), DeployScale(0.f), 0.f, 1e-4f);
		TestEqual(TEXT("scale 1"), DeployScale(1.f), 1.f, 1e-4f);
	}
	{
		// Lifts the rider off the floor and keeps still with reduced motion; leans into speed and turns.
		TestEqual(TEXT("folded: no lift"), HoverHeight(0.f, 1.f, 0.f, false), 0.f);
		const float H = HoverHeight(1.f, 1.f, 0.f, false);
		TestTrue(TEXT("hand's breadth up"), H > LiftCm * 0.8f && H < LiftCm * 1.2f);
		TestEqual(TEXT("reduced: no bob"), HoverHeight(1.f, 1.f, 0.f, true), LiftCm);
		TestTrue(TEXT("reduced: no lean"), Lean(BoostCm, 2.f, true).IsZero());
		const FVector2D L = Lean(SpeedCm, 2.f, false);
		TestTrue(TEXT("pitches into speed"), L.X > 0.f);
		TestTrue(TEXT("rolls into a right turn"), L.Y > 0.f);
	}

	// A real ride on the component: B out, glide to 550 cm/s +- 5 %, feet lifted, a wall eats the speed.
	VerseBoardTest::FRider R;
	TArray<bool> Notices;
	R.Board->OnToggled.AddLambda([&Notices](bool bOn) { Notices.Add(bOn); });
	TestTrue(TEXT("B toggles"), R.Board->Toggle());
	TestTrue(TEXT("out"), R.Board->IsOn());
	R.Ride(0.4, FVector2D::ZeroVector);
	TestEqual(TEXT("folded out after 0.32 s"), R.Board->GetShare(), 1.f);
	TestTrue(TEXT("board shown"), R.Board->IsBoardVisible());
	TestTrue(FString::Printf(TEXT("feet lifted (%.1f cm)"), R.FeetZ()), R.FeetZ() > VerseBoard::LiftCm * 0.8 && R.FeetZ() < VerseBoard::LiftCm * 1.2);
	R.Pawn->SetActorLocation(FVector(-1500.0, 0.0, R.Pawn->GetActorLocation().Z));
	R.Ride(2.5, FVector2D(1.0, 0.0));
	TestTrue(FString::Printf(TEXT("top speed %.0f within 5 %% of 550"), R.Board->GetSpeed()),
		FMath::Abs(R.Board->GetSpeed() - 550.f) <= 550.f * 0.05f);
	TestTrue(TEXT("faces the glide"), FMath::Abs(R.Pawn->GetActorRotation().Yaw) < 1.0);
	R.Ride(3.0, FVector2D(1.0, 0.0));
	TestTrue(TEXT("stopped at the wall"), R.Pawn->GetActorLocation().X < 600.0);
	TestTrue(TEXT("the wall ate the speed"), R.Board->GetSpeed() < 50.f);
	R.Pawn->SetActorLocation(FVector(-3000.0, 0.0, R.Pawn->GetActorLocation().Z));
	R.Ride(2.0, FVector2D(1.0, 0.0));
	R.Ride(4.0, FVector2D::ZeroVector);
	TestEqual(TEXT("coasted to a stop"), R.Board->GetSpeed(), 0.f);
	TestTrue(TEXT("B folds away"), R.Board->Toggle());
	R.Ride(0.4, FVector2D::ZeroVector);
	TestFalse(TEXT("board hidden"), R.Board->IsBoardVisible());
	TestTrue(TEXT("notices on then off"), Notices == TArray<bool>({true, false}));
	TestEqual(TEXT("notice key on"), FString(UVerseHoverboardComponent::NoticeKey(true)), FString(TEXT("verse.board.on")));
	TestEqual(TEXT("notice key off"), FString(UVerseHoverboardComponent::NoticeKey(false)), FString(TEXT("verse.board.off")));
	return true;
}

// Z-10: in arena mode F and B do nothing and the board folds away.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityZ10, "Verse.Parity.Z.10", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseParityZ10::RunTest(const FString&)
{
	VerseBoardTest::FRider R;
	R.Board->Toggle();
	R.Arc->SetHeld(true);
	R.Ride(0.5, FVector2D(1.0, 0.0));
	TestTrue(TEXT("riding on the deck"), R.Board->IsBoardVisible() && R.Board->GetSpeed() > 0.f);
	TestTrue(TEXT("storm on the deck"), R.Arc->IsStriking());
	UVerseEventHub* Hub = UVerseEventHub::Get(R.W.World);
	if (!TestNotNull(TEXT("hub"), Hub))
	{
		return false;
	}
	FVerseArenaSwitchEvent On;
	On.bArenaOn = true;
	On.Deck = TEXT("hangar");
	Hub->OnArenaSwitch.Broadcast(On);
	TestFalse(TEXT("board off"), R.Board->IsOn());
	TestFalse(TEXT("board folded away at once"), R.Board->IsBoardVisible());
	TestFalse(TEXT("storm off"), R.Arc->IsStriking());
	TestFalse(TEXT("B does nothing"), R.Board->Toggle());
	R.Arc->SetHeld(true);
	R.Ride(0.5, FVector2D(1.0, 0.0));
	TestFalse(TEXT("still no board"), R.Board->IsOn() || R.Board->IsBoardVisible());
	TestEqual(TEXT("F does nothing"), R.Arc->GetLevel(), 0.f);
	FVerseArenaSwitchEvent Off;
	Hub->OnArenaSwitch.Broadcast(Off);
	TestTrue(TEXT("B works again on the deck"), R.Board->Toggle());
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

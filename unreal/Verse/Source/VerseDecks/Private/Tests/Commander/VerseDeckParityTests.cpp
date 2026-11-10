#include "Camera/VerseDeckView.h"
#include "Commander/VerseDeckNavGrid.h"
#include "Commander/VerseDeckWalk.h"
#include "EnhancedActionKeyMapping.h"
#include "GameFramework/InputSettings.h"
#include "HangarSwitch/VerseHangarSwitchSubsystem.h"
#include "InputAction.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "InputMappingContext.h"
#include "Input/VerseDeckInput.h"
#include "Misc/AutomationTest.h"
#include "Tests/Commander/VerseDeckCommanderTestWorld.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Parity.V/K/B/S/H.*: the deck commander and the deck's keys and mouse (stream S5,
// parity.md sections V, K, B, S, H). Each test is the row's AT (or ST) against the three.js
// behaviour it names; world tests run on a 40 x 40 m test deck (VerseDeckCommanderTestWorld.h).

#define VERSE_PARITY_DECK_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseDeckParityTests
{
	using namespace Verse::DeckWalk;
	using namespace Verse::DeckInput;

	bool HasMapping(const FContext& Input, EAction Action, const FKey& Key)
	{
		for (const FEnhancedActionKeyMapping& Mapping : Input.Context->GetMappings())
		{
			if (Mapping.Action == Input.Get(Action) && Mapping.Key == Key)
			{
				return true;
			}
		}
		return false;
	}

	double YawOff(double A, double B)
	{
		return FMath::Abs(WrapDeg(A - B));
	}
}

// V-12 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV12Test, "Verse.Parity.V.12", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV12Test::RunTest(const FString& Parameters)
{
	using namespace VerseDeckParityTests;
	// views.test.tsx:222-237, ported: the view looks toward +Y (yaw 90).
	const double View = 90.0;
	const FFacing Forward = BodyFacing(View, FVector2D(0.0, 1.0));
	TestTrue(TEXT("faces the view walking forward"), YawOff(Forward.YawDeg, View) < 1e-6 && !Forward.bReverse);
	// The view's right is yaw + 90: -X here.
	const FFacing Strafe = BodyFacing(View, FVector2D(-1.0, 0.0));
	TestFalse(TEXT("a strafe is no backpedal"), Strafe.bReverse);
	TestEqual(TEXT("leans exactly 45 degrees into a strafe"), YawOff(Strafe.YawDeg, View), StrafeLeanDeg, 1e-6);
	const FFacing Back = BodyFacing(View, FVector2D(0.0, -1.0));
	TestTrue(TEXT("walks backwards facing the view"), Back.bReverse && YawOff(Back.YawDeg, View) < 1e-6);

	// W walks away from the camera and D to its right, in third and first person alike.
	const TOptional<FVector2D> W = WalkDirection(View, FVector2D(0.0, 1.0));
	const TOptional<FVector2D> D = WalkDirection(View, FVector2D(1.0, 0.0));
	TestTrue(TEXT("W walks along the view"), W.IsSet() && W->Equals(FVector2D(0.0, 1.0), 1e-6));
	TestTrue(TEXT("D walks to the view's right"), D.IsSet() && D->Equals(FVector2D(-1.0, 0.0), 1e-6));
	TestFalse(TEXT("A and D together cancel"), WalkDirection(View, FVector2D::ZeroVector).IsSet());

	// In the world: driving with D in third person, the body leans into the strafe, never more.
	FVerseDeckCommanderTestWorld W2;
	W2.Control->PickView(EVerseDeckView::Third);
	W2.Camera->Rig.YawDeg = 0.0;
	W2.Control->SetMoveAxes(FVector2D(1.0, 0.0));
	const FVector Start = W2.Commander()->GetFeet();
	W2.Step(60);
	W2.Control->SetMoveAxes(FVector2D::ZeroVector);
	const FVector Moved = W2.Commander()->GetFeet() - Start;
	AddInfo(FString::Printf(TEXT("strafe moved %s, yaw %.1f"), *Moved.ToString(), W2.Commander()->GetActorRotation().Yaw));
	TestTrue(TEXT("D walks toward +Y when the view looks along +X"), Moved.Y > 80.0 && FMath::Abs(Moved.X) < 15.0);
	TestEqual(TEXT("the body leans 45 degrees into the strafe"), YawOff(W2.Commander()->GetActorRotation().Yaw, 0.0), StrafeLeanDeg, 2.0);
	W2.Control->SetMoveAxes(FVector2D(0.0, -1.0));
	W2.Step(40);
	TestTrue(TEXT("S backpedals facing the view"), W2.Commander()->IsBackpedalling() && YawOff(W2.Commander()->GetActorRotation().Yaw, 0.0) < 2.0);
	return true;
}

// V-13 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV13Test, "Verse.Parity.V.13", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV13Test::RunTest(const FString& Parameters)
{
	using namespace VerseDeckParityTests;
	TestEqual(TEXT("the commander's pace is 1.45 m/s"), Speed(false), 145.0);
	TestEqual(TEXT("Shift hurries at 1.75 times the pace"), Speed(true), 145.0 * 1.75);
	auto Distance = [](bool bHurry)
	{
		FVerseDeckCommanderTestWorld W;
		W.Control->PickView(EVerseDeckView::Third);
		W.Camera->Rig.YawDeg = 0.0;
		W.Control->SetHurry(bHurry);
		W.Control->SetMoveAxes(FVector2D(0.0, 1.0));
		W.Step(30);
		const double From = W.Commander()->GetFeet().X;
		W.Step(60);
		return W.Commander()->GetFeet().X - From;
	};
	const double Walk = Distance(false);
	const double Hurry = Distance(true);
	AddInfo(FString::Printf(TEXT("one second: walk %.1f cm, hurry %.1f cm"), Walk, Hurry));
	TestEqual(TEXT("walks about 1.45 m in a second"), Walk, 145.0, 10.0);
	TestEqual(TEXT("hurries about 2.54 m in a second"), Hurry, 145.0 * 1.75, 15.0);
	return true;
}

// V-03, K-09 -------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityK09Test, "Verse.Parity.K.09", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityK09Test::RunTest(const FString& Parameters)
{
	using namespace VerseDeckParityTests;
	UObject* Outer = CreatePackage(*MakeUniqueObjectName(nullptr, UPackage::StaticClass(), TEXT("/Temp/VerseDeckK09")).ToString());
	const FContext Input = BuildContext(Outer);
	TestNotNull(TEXT("IMC_VerseDeck"), Input.Context);
	TestEqual(TEXT("IMC name"), Input.Context->GetFName(), FName(TEXT("IMC_VerseDeck")));
	// The key map of VerseStage.tsx:690-718.
	const TArray<TPair<EAction, FKey>> Expected = {
		{ EAction::Move, EKeys::W }, { EAction::Move, EKeys::A }, { EAction::Move, EKeys::S }, { EAction::Move, EKeys::D },
		{ EAction::Move, EKeys::Up }, { EAction::Move, EKeys::Down }, { EAction::Move, EKeys::Left }, { EAction::Move, EKeys::Right },
		{ EAction::Hurry, EKeys::LeftShift }, { EAction::CycleView, EKeys::V },
		{ EAction::ViewOverview, EKeys::One }, { EAction::ViewThird, EKeys::Two }, { EAction::ViewFirst, EKeys::Three },
		{ EAction::Use, EKeys::E }, { EAction::MouseLook, EKeys::L }, { EAction::Power, EKeys::F }, { EAction::Board, EKeys::B },
		{ EAction::ZoomIn, EKeys::Equals }, { EAction::ZoomIn, EKeys::Add }, { EAction::ZoomOut, EKeys::Hyphen }, { EAction::ZoomOut, EKeys::Subtract },
		{ EAction::Debug, EKeys::F9 },
	};
	for (const TPair<EAction, FKey>& Pair : Expected)
	{
		TestTrue(FString::Printf(TEXT("%s on %s"), ActionName(Pair.Key), *Pair.Value.ToString()), HasMapping(Input, Pair.Key, Pair.Value));
	}
	TestEqual(TEXT("move shares the person's IA_Move (one rebinding moves both)"), Input.Get(EAction::Move)->GetFName(), FName(TEXT("IA_Move")));
	TestEqual(TEXT("move is a stick"), Input.Get(EAction::Move)->ValueType, EInputActionValueType::Axis2D);

	// Each action does its job.
	FVerseDeckCommanderTestWorld W;
	W.Control->PickView(EVerseDeckView::Third);
	TestTrue(TEXT("2: third person"), W.Camera->GetView() == EVerseDeckView::Third);
	W.Control->CycleView();
	TestTrue(TEXT("V: first person"), W.Camera->GetView() == EVerseDeckView::First);
	W.Control->ToggleMouseLook();
	TestFalse(TEXT("L: mouse look off"), W.Control->IsMouseLook());
	int32 Board = 0;
	W.Control->OnBoard.AddLambda([&Board]() { ++Board; });
	W.Control->OnBoard.Broadcast();
	TestEqual(TEXT("B reaches the hoverboard owner"), Board, 1);
	const double Distance = W.Camera->Rig.DistanceCm;
	W.Control->PickView(EVerseDeckView::Third);
	W.Control->ZoomStep(false);
	TestTrue(TEXT("-: zooms out"), W.Camera->Rig.DistanceCm > Distance - 1e-6);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV03Test, "Verse.Parity.V.03", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV03Test::RunTest(const FString& Parameters)
{
	using namespace VerseDeckParityTests;
	UObject* Outer = CreatePackage(*MakeUniqueObjectName(nullptr, UPackage::StaticClass(), TEXT("/Temp/VerseDeckV03")).ToString());
	const FContext Input = BuildContext(Outer);
	TestTrue(TEXT("1 picks the overview"), HasMapping(Input, EAction::ViewOverview, EKeys::One) && HasMapping(Input, EAction::ViewOverview, EKeys::NumPadOne));
	TestTrue(TEXT("2 picks third person"), HasMapping(Input, EAction::ViewThird, EKeys::Two) && HasMapping(Input, EAction::ViewThird, EKeys::NumPadTwo));
	TestTrue(TEXT("3 picks first person"), HasMapping(Input, EAction::ViewFirst, EKeys::Three) && HasMapping(Input, EAction::ViewFirst, EKeys::NumPadThree));
	FVerseDeckCommanderTestWorld W;
	for (const EVerseDeckView View : { EVerseDeckView::Overview, EVerseDeckView::First, EVerseDeckView::Third })
	{
		W.Control->PickView(View);
		TestTrue(FString::Printf(TEXT("picks %s"), Verse::DeckView::Name(View)), W.Camera->GetView() == View);
	}
	return true;
}

// V-07, V-08 -------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV07Test, "Verse.Parity.V.07", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV07Test::RunTest(const FString& Parameters)
{
	FVerseShoulderRig Rig;
	FVerseRigBody Body;
	Rig.Update(1.0 / 60.0, Body, {});
	Rig.SetPerson(EVerseDeckPerson::First);
	double ReachedAt = -1.0;
	double HalfAt = -1.0;
	for (int32 Frame = 1; Frame <= 60; ++Frame)
	{
		Rig.Update(1.0 / 60.0, Body, {});
		const double T = Frame / 60.0;
		if (HalfAt < 0.0 && Rig.FirstShare >= 0.5)
		{
			HalfAt = T;
		}
		if (ReachedAt < 0.0 && Rig.FirstShare >= 0.95)
		{
			ReachedAt = T;
		}
	}
	AddInfo(FString::Printf(TEXT("shoulder to eyes: half at %.3f s, 95%% at %.3f s"), HalfAt, ReachedAt));
	TestTrue(TEXT("the blend is under way in the first 0.1 s"), HalfAt > 0.0 && HalfAt <= 0.12);
	TestTrue(TEXT("the blend is done in about 0.2 s"), ReachedAt > 0.1 && ReachedAt <= 0.3);
	TestEqual(TEXT("the FOV blends to first person's"), Rig.Hfov(), Rig.FovFirstDeg, 1.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV08Test, "Verse.Parity.V.08", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV08Test::RunTest(const FString& Parameters)
{
	FVerseShoulderRig Rig;
	double ThirdMin = 0.0;
	double ThirdMax = 0.0;
	Rig.PitchLimits(ThirdMin, ThirdMax);
	Rig.SetPerson(EVerseDeckPerson::First);
	double FirstMin = 0.0;
	double FirstMax = 0.0;
	Rig.PitchLimits(FirstMin, FirstMax);
	TestTrue(TEXT("first person looks further down and up than third"), FirstMin < ThirdMin && FirstMax > ThirdMax);
	Rig.PitchDeg = FirstMin;
	Rig.SetPerson(EVerseDeckPerson::Third);
	FVerseRigBody Body;
	Rig.Update(1.0 / 60.0, Body, {});
	TestTrue(TEXT("back in third person the pitch is clamped to third's range"), Rig.PitchDeg >= ThirdMin - 1e-6 && Rig.PitchDeg <= ThirdMax + 1e-6);
	return true;
}

// V-11 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV11Test, "Verse.Parity.V.11", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV11Test::RunTest(const FString& Parameters)
{
	using namespace VerseDeckParityTests;
	FVerseDeckCommanderTestWorld W;
	for (const FEnhancedActionKeyMapping& Mapping : W.Control->GetInputContext().Context->GetMappings())
	{
		if (Mapping.Action == W.Control->GetInputContext().Get(EAction::Look))
		{
			TestEqual(TEXT("mouse look takes the deltas as they come (no modifiers)"), Mapping.Modifiers.Num(), 0);
			TestEqual(TEXT("from Mouse2D"), Mapping.Key, EKeys::Mouse2D);
		}
	}
	TestTrue(TEXT("no smoothing on mouse deltas"), !GetDefault<UInputSettings>()->bEnableMouseSmoothing);
	W.Control->PickView(EVerseDeckView::Third);
	TestTrue(TEXT("captured look hides the cursor: the viewport takes raw high precision deltas"), W.Control->IsMouseLook() && !W.Controller->ShouldShowMouseCursor());
	// One captured delta turns the view by exactly LockDegPerPx * sensitivity.
	const double Yaw = W.Camera->Rig.YawDeg;
	W.Control->LookDelta(FVector2D(10.0, 0.0));
	TestEqual(TEXT("ten pixels turn ten steps"), Verse::DeckWalk::WrapDeg(W.Camera->Rig.YawDeg - Yaw), 10.0 * W.Camera->Rig.Tuning.LockDegPerPx * W.Camera->Rig.Sensitivity, 1e-6);
	return true;
}

// V-14 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV14Test, "Verse.Parity.V.14", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV14Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Overview(FVector::ZeroVector);
	const FVector Feet = W.Commander()->GetFeet();
	const FVector Centre = W.Camera->Overview.CentreCm;
	W.Control->SetMoveAxes(FVector2D(0.0, 1.0));
	W.Step(30);
	W.Control->SetMoveAxes(FVector2D::ZeroVector);
	TestTrue(TEXT("W pans the map"), !W.Camera->Overview.CentreCm.Equals(Centre, 1.0));
	TestTrue(TEXT("the commander stays where they stand"), W.Commander()->GetFeet().Equals(Feet, 5.0));
	const double Distance = W.Camera->Overview.DistanceCm;
	W.Control->ZoomStep(true);
	TestTrue(TEXT("+ zooms in about the centre"), W.Camera->Overview.DistanceCm < Distance);
	const double Zoomed = W.Camera->Overview.DistanceCm;
	W.Control->Wheel(-1.f);
	TestTrue(TEXT("the wheel zooms out"), W.Camera->Overview.DistanceCm > Zoomed);
	// A drag turns the view and is no click.
	const double Yaw = W.Camera->Overview.YawDeg;
	int32 Activated = 0;
	W.Control->OnStationActivated.AddLambda([&Activated](const FVerseDeckStation&) { ++Activated; });
	W.Control->PointerDown(FVector2D(900.0, 500.0));
	W.Control->LookDelta(FVector2D(120.0, 0.0));
	W.Control->PointerUp(FVector2D(1020.0, 500.0));
	TestTrue(TEXT("a drag turns the overview"), FMath::Abs(Verse::DeckWalk::WrapDeg(W.Camera->Overview.YawDeg - Yaw)) > 1.0);
	TestFalse(TEXT("a drag sends nobody walking"), W.Commander()->IsWalking());
	return true;
}

// V-15 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV15Test, "Verse.Parity.V.15", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV15Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Overview(FVector(-500.0, 0.0, 0.0));
	// Click the floor beyond the wall: the commander walks around its end to the point.
	const FVector Target(600.0, 300.0, 0.0);
	W.Control->Click(W.ToScreen(Target));
	TestTrue(TEXT("a floor click starts a walk"), W.Commander()->IsWalking());
	const TOptional<FVector> Goal = W.Commander()->GetWalkGoal();
	TestTrue(TEXT("the path ends on the clicked point"), Goal.IsSet() && FVector::Dist2D(Goal.GetValue(), Target) < 25.0);
	const bool bArrived = W.StepUntil([&W]() { return !W.Commander()->IsWalking(); }, 30.0);
	AddInfo(FString::Printf(TEXT("feet after the walk: %s"), *W.Commander()->GetFeet().ToString()));
	TestTrue(TEXT("the commander gets there round the wall"), bArrived && FVector::Dist2D(W.Commander()->GetFeet(), Target) < 40.0);

	// The wall's top seen from above is no floor: a click on it walks nobody.
	const FVerseDeckPick OnWall = W.Control->PickAt(W.ToScreen(FVector(0.0, 0.0, 300.0)));
	TestTrue(TEXT("the wall's top is no floor"), OnWall.Kind == FVerseDeckPick::EKind::Wall);
	W.Control->Click(W.ToScreen(FVector(0.0, 0.0, 300.0)));
	TestFalse(TEXT("a click on the wall walks nobody"), W.Commander()->IsWalking());
	// A point next to the wall snaps to the floor within 1.2 m; one in a blocked block far from floor does not.
	TestTrue(TEXT("a point beside the wall snaps to the floor"), W.Control->WalkTo(FVector(-10.0, 0.0, 0.0)));
	return true;
}

// V-16 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV16Test, "Verse.Parity.V.16", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV16Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	ACharacter* Seen = W.Person(FVector(-1000.0, 400.0, 0.0));
	ACharacter* Hidden = W.Person(FVector(400.0, 0.0, 0.0));
	const FVector Eye(-1500.0, 0.0, 165.0);
	const FVerseDeckPick Plain = W.Control->PickRay(Eye, (Seen->GetActorLocation() - Eye).GetSafeNormal());
	TestTrue(TEXT("a crew member in plain view is picked"), Plain.Kind == FVerseDeckPick::EKind::Crew && Plain.Actor.Get() == Seen);
	const FVerseDeckPick Behind = W.Control->PickRay(Eye, (Hidden->GetActorLocation() - Eye).GetSafeNormal());
	TestTrue(TEXT("one behind the wall is never picked"), Behind.Kind == FVerseDeckPick::EKind::Wall);
	// Selecting by click: the first click selects, the second opens the card.
	W.Overview(FVector(-1000.0, 400.0, 0.0));
	int32 Opened = 0;
	W.Control->OnCrewOpened.AddLambda([&Opened](AActor*) { ++Opened; });
	W.Control->Click(W.ToScreen(Seen->GetActorLocation()));
	TestTrue(TEXT("a click selects"), W.Control->GetSelected() == Seen);
	W.Control->Click(W.ToScreen(Seen->GetActorLocation()));
	TestEqual(TEXT("a second click opens the card"), Opened, 1);
	return true;
}

// V-18 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV18Test, "Verse.Parity.V.18", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV18Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	ACharacter* Member = W.Person(FVector(-1500.0, 900.0, 0.0));
	W.Control->PickView(EVerseDeckView::Third);
	W.Camera->Rig.YawDeg = 0.0;
	W.Control->ShowActor(Member);
	TestEqual(TEXT("at eye level the view turns toward them"), W.Camera->Rig.YawDeg, 90.0, 0.5);
	W.Overview(FVector::ZeroVector);
	W.Control->ShowActor(Member);
	TestTrue(TEXT("in the overview the map centres on them"), FVector::Dist2D(W.Camera->Overview.CentreCm, Member->GetActorLocation()) < 1.0);
	return true;
}

// V-19, V-20 -------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV19Test, "Verse.Parity.V.19", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV19Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Control->PickView(EVerseDeckView::Third);
	TestTrue(TEXT("third person starts with mouse look"), W.Control->IsMouseLook());
	W.Control->ToggleMouseLook();
	TestFalse(TEXT("L gives the mouse back"), W.Control->IsMouseLook());
	TestTrue(TEXT("with the cursor shown"), W.Controller->ShouldShowMouseCursor());
	W.Control->ToggleMouseLook();
	TestTrue(TEXT("L takes it again"), W.Control->IsMouseLook() && W.Camera->bMouseLocked);
	W.Control->PickView(EVerseDeckView::Overview);
	W.Control->ToggleMouseLook();
	TestFalse(TEXT("L does nothing in the overview"), W.Control->IsMouseLook());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityV20Test, "Verse.Parity.V.20", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityV20Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Control->PickView(EVerseDeckView::Overview);
	TestFalse(TEXT("the overview leaves the mouse free"), W.Control->IsMouseLook());
	W.Control->PickView(EVerseDeckView::First);
	TestTrue(TEXT("first person takes the mouse at once"), W.Control->IsMouseLook());
	W.Control->PickView(EVerseDeckView::Overview);
	TestFalse(TEXT("the overview gives it back"), W.Control->IsMouseLook());
	W.Control->CycleView();
	TestTrue(TEXT("V into third person takes it too"), W.Camera->GetView() == EVerseDeckView::Third && W.Control->IsMouseLook());
	// The wheel handing third to first keeps the mouse as it is.
	W.Control->ToggleMouseLook();
	for (int32 I = 0; I < 40 && W.Camera->GetView() == EVerseDeckView::Third; ++I)
	{
		W.Control->ZoomStep(true);
	}
	TestTrue(TEXT("the wheel reached first person"), W.Camera->GetView() == EVerseDeckView::First);
	TestFalse(TEXT("and left the mouse free"), W.Control->IsMouseLook());
	return true;
}

// K-01, K-04, K-05 -------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityK01Test, "Verse.Parity.K.01", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityK01Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	TestTrue(TEXT("focused: the deck takes keys"), W.Control->TakesKeys());
	TestFalse(TEXT("a text field's keys are never the deck's"), Verse::DeckInput::TakesKeys(true, true, false));
	W.Control->PickView(EVerseDeckView::Third);
	W.Camera->Rig.YawDeg = 0.0;
	W.Control->SetMoveAxes(FVector2D(0.0, 1.0));
	W.Control->SetHurry(true);
	W.Step(10);
	TestTrue(TEXT("walking"), W.Commander()->GetFloorSpeed() > 50.0);
	W.bFocused = false;
	W.Step(2);
	TestFalse(TEXT("unfocused: no keys"), W.Control->TakesKeys());
	TestFalse(TEXT("losing focus gives the mouse back"), W.Control->IsMouseLook());
	const double X = W.Commander()->GetFeet().X;
	W.Step(60);
	TestTrue(TEXT("losing focus lets go of held keys: the commander stops"), W.Commander()->GetFeet().X - X < 40.0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityK04Test, "Verse.Parity.K.04", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityK04Test::RunTest(const FString& Parameters)
{
	using namespace Verse::DeckInput;
	for (const FKey& Key : { EKeys::LeftControl, EKeys::RightControl, EKeys::LeftAlt, EKeys::RightAlt, EKeys::LeftCommand, EKeys::RightCommand })
	{
		TestTrue(FString::Printf(TEXT("%s makes a chord"), *Key.ToString()), IsChordModifier(Key));
	}
	TestFalse(TEXT("Shift is no chord (it hurries)"), IsChordModifier(EKeys::LeftShift));
	FVerseDeckCommanderTestWorld W;
	W.bChord = true;
	TestFalse(TEXT("with Ctrl, Alt or Cmd held the deck takes no key"), W.Control->TakesKeys());
	// The deck binds no chord: no mapping carries a Ctrl/Alt/Cmd key.
	for (const FEnhancedActionKeyMapping& Mapping : W.Control->GetInputContext().Context->GetMappings())
	{
		TestFalse(FString::Printf(TEXT("%s is no chord key"), *Mapping.Key.ToString()), IsChordModifier(Mapping.Key));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityK05Test, "Verse.Parity.K.05", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityK05Test::RunTest(const FString& Parameters)
{
	using namespace Verse::DeckInput;
	TestTrue(TEXT("rule: look first"), EscapeStep(true, true) == EEscape::EndMouseLook);
	TestTrue(TEXT("rule: then the card"), EscapeStep(false, true) == EEscape::CloseCard);
	TestTrue(TEXT("rule: then through"), EscapeStep(false, false) == EEscape::PassThrough);
	FVerseDeckCommanderTestWorld W;
	ACharacter* Member = W.Person(FVector(-1000.0, 400.0, 0.0));
	W.Overview(Member->GetActorLocation());
	W.Control->Click(W.ToScreen(Member->GetActorLocation()));
	TestTrue(TEXT("selected"), W.Control->GetSelected() == Member);
	W.Control->PickView(EVerseDeckView::Third);
	TestTrue(TEXT("mouse look on"), W.Control->IsMouseLook());
	TestTrue(TEXT("Esc ends mouse look first"), UVerseDeckControlComponent::TryEscape(W.World) && !W.Control->IsMouseLook());
	TestTrue(TEXT("the card is still open"), W.Control->GetSelected() == Member);
	TestTrue(TEXT("Esc then closes the card"), UVerseDeckControlComponent::TryEscape(W.World) && W.Control->GetSelected() == nullptr);
	TestFalse(TEXT("with nothing open Esc goes through to the menu"), UVerseDeckControlComponent::TryEscape(W.World));
	return true;
}

// B-07 -------------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityB07Test, "Verse.Parity.B.07", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityB07Test::RunTest(const FString& Parameters)
{
	FVerseWalkOrders Orders;
	Orders.Give(TEXT("hangar"), FVector(100.0, 0.0, 0.0));
	TestTrue(TEXT("the order holds on its deck"), Orders.TargetOn(TEXT("hangar")).IsSet());
	TestFalse(TEXT("never on another"), Orders.TargetOn(TEXT("bridge")).IsSet());
	Orders.Arrive(TEXT("bridge"));
	Orders.Arrive(TEXT("hangar"));
	TestFalse(TEXT("riding back does not revive it"), Orders.TargetOn(TEXT("hangar")).IsSet());

	FVerseDeckCommanderTestWorld W;
	W.Overview(FVector::ZeroVector);
	TestTrue(TEXT("a walk is ordered"), W.Control->WalkTo(FVector(-1500.0, 1200.0, 0.0)));
	W.Step(30);
	// Ride the lift away and come back: the commander stands where they come aboard.
	W.Control->OnDeckArrived(TEXT("otherdeck"), W.Manifest, W.Arrival, W.Camera);
	W.Control->OnDeckArrived(FVerseDeckCommanderTestWorld::DeckId, W.Manifest, W.Arrival, W.Camera);
	TestFalse(TEXT("no walk to the old target"), W.Commander()->IsWalking());
	W.Step(60);
	TestTrue(TEXT("the commander stands at the arrival"), FVector::Dist2D(W.Commander()->GetFeet(), W.Arrival.GetLocation()) < 10.0);
	return true;
}

// S-11, S-14, S-18 -------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityS11Test, "Verse.Parity.S.11", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityS11Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	const FVector Station = W.Manifest.Stations[0].Transform.GetLocation();
	TestTrue(TEXT("the station is more than 10 m away"), FVector::Dist2D(W.Commander()->GetFeet(), Station) > 1000.0);
	int32 Activated = 0;
	W.Control->OnStationActivated.AddLambda([&Activated](const FVerseDeckStation& S) { Activated += S.Id == FVerseDeckCommanderTestWorld::StationId ? 1 : 0; });
	TestTrue(TEXT("activated"), W.Control->ActivateStation(FVerseDeckCommanderTestWorld::StationId));
	TestEqual(TEXT("the station's owner hears it"), Activated, 1);
	const TOptional<FVector> Goal = W.Commander()->GetWalkGoal();
	TestTrue(TEXT("the commander's path ends at the station's spot"), Goal.IsSet() && FVector::Dist2D(Goal.GetValue(), Station) <= Verse::DeckWalk::StationReachCm);
	W.StepUntil([&W]() { return !W.Commander()->IsWalking(); }, 30.0);
	TestTrue(TEXT("and they get there"), FVector::Dist2D(W.Commander()->GetFeet(), Station) <= Verse::DeckWalk::StationReachCm);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityS14Test, "Verse.Parity.S.14", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityS14Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	const FVector Station = W.Manifest.Stations[0].Transform.GetLocation();
	W.Overview(Station);
	W.Mouse = W.ToScreen(Station + FVector(20.0, 10.0, 0.0));
	W.Step(1);
	const FVerseDeckPointerState& Pointer = W.Control->GetPointer();
	TestEqual(TEXT("hovering a station names it"), Pointer.HoverStation, FVerseDeckCommanderTestWorld::StationId);
	const FString Label = Pointer.HoverLabel.ToString();
	AddInfo(FString::Printf(TEXT("label: %s"), *Label));
	TestTrue(TEXT("name and action"), Label.Contains(TEXT("Service record")) && Label.Contains(TEXT("open")));
	TestFalse(TEXT("no key glyph"), Label.Contains(TEXT("["), ESearchCase::CaseSensitive) || Label.EndsWith(TEXT(" E"), ESearchCase::CaseSensitive));
	W.Mouse = W.ToScreen(FVector(-1200.0, -1200.0, 0.0));
	W.Step(1);
	TestTrue(TEXT("off the station the label goes"), W.Control->GetPointer().HoverStation.IsNone());
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityS18Test, "Verse.Parity.S.18", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityS18Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	const FVector Station = W.Manifest.Stations[0].Transform.GetLocation();
	W.Overview(Station);
	int32 Activated = 0;
	W.Control->OnStationActivated.AddLambda([&Activated](const FVerseDeckStation&) { ++Activated; });
	W.Control->PointerDown(W.ToScreen(Station));
	W.Control->PointerUp(W.ToScreen(Station));
	TestEqual(TEXT("a click on a station in the overview uses it"), Activated, 1);
	TestTrue(TEXT("and walks the commander there"), W.Commander()->IsWalking());
	return true;
}

// H-09, H-10 -------------------------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH09Test, "Verse.Parity.H.09", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityH09Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Control->PickView(EVerseDeckView::First);
	W.Camera->Rig.YawDeg = 0.0;
	W.Camera->Rig.PitchDeg = 0.0;
	W.Step(30);
	TestTrue(TEXT("eye level with mouse look: the reticle"), W.Control->GetPointer().bReticle);
	TestFalse(TEXT("nothing usable ahead: plain"), W.Control->GetPointer().bReticleMarked);
	// A crew member straight ahead of the eyes marks it.
	const FVector Eye = W.Camera->GetActorLocation();
	W.Person(FVector(Eye.X + 400.0, Eye.Y, 0.0));
	W.Step(2);
	TestTrue(TEXT("someone under the reticle marks it"), W.Control->GetPointer().bReticleMarked);
	W.Control->PickView(EVerseDeckView::Overview);
	W.Step(1);
	TestFalse(TEXT("no reticle in the overview"), W.Control->GetPointer().bReticle);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityH10Test, "Verse.Parity.H.10", VERSE_PARITY_DECK_FLAGS)
bool FVerseParityH10Test::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Control->PickView(EVerseDeckView::Third);
	W.Control->ToggleMouseLook();
	W.Step(1);
	TestTrue(TEXT("focused, eye level, mouse free: click to look"), W.Control->GetPointer().bClickToLook);
	TestFalse(TEXT("the hint has words"), W.Control->ClickToLookHint.IsEmpty());
	W.Control->Click(FVector2D(960.0, 540.0));
	W.Step(1);
	TestTrue(TEXT("a click takes the mouse"), W.Control->IsMouseLook());
	TestFalse(TEXT("and the hint goes"), W.Control->GetPointer().bClickToLook);
	W.Control->ToggleMouseLook();
	W.bFocused = false;
	W.Step(1);
	TestFalse(TEXT("without window focus there is no hint"), W.Control->GetPointer().bClickToLook);
	return true;
}

// Nav grid (supports V-15, S-11) ------------------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeckNavGridTest, "Verse.Decks.Commander.NavGrid", VERSE_PARITY_DECK_FLAGS)
bool FVerseDeckNavGridTest::RunTest(const FString& Parameters)
{
	// A 2 m x 2 m grid of 20 cm cells with a wall across the middle and a gap at the top.
	FVerseDeckNavGrid Grid;
	Grid.Init(FBox2D(FVector2D(0.0, 0.0), FVector2D(200.0, 200.0)), 20.0);
	for (int32 Index = 0; Index < Grid.NumCols() * Grid.NumRows(); ++Index)
	{
		const FVector2D C = Grid.CellCentre(Index);
		const bool bWall = C.X > 80.0 && C.X < 120.0 && C.Y < 150.0;
		Grid.SetCell(Index, !bWall, 0.0);
	}
	TArray<FVector> Path;
	TestTrue(TEXT("a way round the wall"), Grid.FindPath(FVector(30.0, 30.0, 0.0), FVector(170.0, 30.0, 0.0), Path));
	TestTrue(TEXT("string pulled to a few legs"), Path.Num() >= 3 && Path.Num() <= 5);
	for (int32 I = 1; I < Path.Num(); ++I)
	{
		TestTrue(TEXT("every leg walkable"), Grid.LineOfWalk(FVector2D(Path[I - 1]), FVector2D(Path[I])));
	}
	TestFalse(TEXT("no straight walk through the wall"), Grid.LineOfWalk(FVector2D(30.0, 30.0), FVector2D(170.0, 30.0)));
	const TOptional<FVector> Snap = Grid.NearestWalkable(FVector2D(100.0, 50.0), 120.0);
	TestTrue(TEXT("a point in the wall snaps beside it"), Snap.IsSet() && Grid.IsWalkable(FVector2D(Snap->X, Snap->Y)));
	// A step too high blocks the way.
	for (const double Y : { 150.0, 170.0, 190.0 })
	{
		Grid.SetCell(Grid.CellIndex(FVector2D(90.0, Y)), true, 80.0);
		Grid.SetCell(Grid.CellIndex(FVector2D(110.0, Y)), true, 80.0);
	}
	TestFalse(TEXT("no way over an 80 cm step"), Grid.FindPath(FVector(30.0, 30.0, 0.0), FVector(170.0, 30.0, 0.0), Path));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeckSaluteUniformTest, "Verse.Decks.Commander.SaluteAndUniform", VERSE_PARITY_DECK_FLAGS)
bool FVerseDeckSaluteUniformTest::RunTest(const FString& Parameters)
{
	FVerseDeckCommanderTestWorld W;
	W.Control->WalkTo(FVector(-1500.0, 1200.0, 0.0));
	W.Control->Salute();
	TestTrue(TEXT("saluting"), W.Commander()->IsSaluting());
	TestFalse(TEXT("a salute stops the walk"), W.Commander()->IsWalking());
	W.Step(20);
	const FVector Hand = W.Commander()->RightArm->GetComponentLocation() + W.Commander()->RightArm->GetUpVector() * -W.Commander()->RightArm->GetComponentScale().Z * 50.0;
	const FVector Head = W.Commander()->Head->GetComponentLocation();
	AddInfo(FString::Printf(TEXT("hand %s, head %s"), *Hand.ToString(), *Head.ToString()));
	TestTrue(TEXT("the hand is at the brow"), FVector::Dist(Hand, Head) < 30.0);
	W.Step(int32(AVerseDeckCommander::SaluteS * 60.0) + 5);
	TestFalse(TEXT("the salute ends"), W.Commander()->IsSaluting());
	W.Control->WearUniform(TEXT("dress"), FLinearColor(0.30f, 0.05f, 0.04f, 1.f));
	TestEqual(TEXT("uniform worn"), W.Commander()->GetUniform(), FName(TEXT("dress")));
	UMaterialInstanceDynamic* Material = Cast<UMaterialInstanceDynamic>(W.Commander()->Torso->GetMaterial(0));
	TestTrue(TEXT("the body material carries the uniform colour"), Material && Material->K2_GetVectorParameterValue(TEXT("Color")).Equals(FLinearColor(0.30f, 0.05f, 0.04f, 1.f), 1e-3f));
	return true;
}


// The mouse between the deck and the duel ---------------------------------------------------------

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDeckMouseToDuelTest, "Verse.Decks.Commander.MouseToDuel", VERSE_PARITY_DECK_FLAGS)
bool FVerseDeckMouseToDuelTest::RunTest(const FString& Parameters)
{
	// The deck hands the mouse to the duel captured (game-only, hidden cursor). It used to leave the
	// controller in game-and-UI, where the viewport captures only while a button is held, so moving
	// the mouse did not turn the duel camera.
	FVerseDeckCommanderTestWorld W;
	UVerseHangarSwitchSubsystem* Switch = UVerseHangarSwitchSubsystem::Get(W.World);
	if (!TestNotNull(TEXT("hangar switch"), Switch))
	{
		return false;
	}
	W.Control->PickView(EVerseDeckView::Overview);
	TestTrue(TEXT("the overview leaves the cursor free"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Free && W.Controller->ShouldShowMouseCursor());
	W.Control->PickView(EVerseDeckView::Third);
	TestTrue(TEXT("eye level looks with a captured mouse"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Look && !W.Controller->ShouldShowMouseCursor());

	TestTrue(TEXT("arena requested"), Switch->RequestArena(true));
	const bool bArena = W.StepUntil([&]() { Switch->Step(); return Switch->IsArenaOn() && !W.Control->IsDeckActive(); }, 10.0);
	TestTrue(TEXT("the duel takes the hangar"), bArena);
	TestTrue(TEXT("the duel gets a captured mouse, not a free cursor"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Game && !W.Controller->ShouldShowMouseCursor());
	TestTrue(TEXT("a closing menu gives the duel its captured mouse back"), UVerseDeckControlComponent::RestoreInputMode(W.World) && W.Control->GetMouseMode() == EVerseDeckMouseMode::Game);
	W.bFocused = false;
	W.Step(2);
	W.bFocused = true;
	W.Step(2);
	TestTrue(TEXT("focus round trips in the duel keep the mouse captured"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Game);
	W.Control->SetMouseLook(false);
	TestTrue(TEXT("deck mouse calls in the duel cannot free the cursor"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Game && !W.Controller->ShouldShowMouseCursor());

	// Started straight into the duel (-VerseDuel, quick_start_duel from the app): the arrival on the
	// deck finds the arena on and must not free the cursor either.
	W.Control->OnDeckArrived(FVerseDeckCommanderTestWorld::DeckId, W.Manifest, W.Arrival, W.Camera);
	TestTrue(TEXT("arrival during the duel keeps the mouse captured"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Game && !W.Controller->ShouldShowMouseCursor());

	TestTrue(TEXT("day requested"), Switch->RequestArena(false));
	const bool bDay = W.StepUntil([&]() { Switch->Step(); return !Switch->IsArenaOn() && !Switch->IsSwitching() && W.Control->IsDeckActive(); }, 10.0);
	TestTrue(TEXT("the deck takes the hangar back"), bDay);
	TestTrue(TEXT("back on the deck the deck's own mode applies"), W.Control->GetMouseMode() == EVerseDeckMouseMode::Free || W.Control->GetMouseMode() == EVerseDeckMouseMode::Look);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

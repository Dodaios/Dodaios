#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/BoxComponent.h"
#include "Components/InputComponent.h"
#include "Engine/World.h"
#include "Fixture/VerseMovementCourse.h"
#include "GameFramework/Controller.h"
#include "InputCoreTypes.h"
#include "Serialization/MemoryReader.h"
#include "Serialization/MemoryWriter.h"
#include "Tests/Movement/VerseMovementTestWorld.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseMovementNetworking.h"

namespace
{
	constexpr EAutomationTestFlags NetEyeTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;
	using namespace VerseMovementCourse;

	void HoldFor(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, uint32 Buttons, const FVector2f& Move, float Seconds, uint32& Prev,
		TFunctionRef<void()> PerTick = [] {}, const FVector2f& Look = FVector2f::ZeroVector)
	{
		const int32 Ticks = FMath::Max(1, FMath::RoundToInt(Seconds / FVerseMovementTestWorld::Dt));
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			W.Drive(Pawn, VerseTestFrame(Move, Buttons, Prev, Look));
			Prev = Buttons;
			W.Tick();
			PerTick();
		}
	}

	/** Fires the pawn's own key binding for Key and Event, as the player input would. */
	int32 FireKey(UInputComponent& Input, const FKey& Key, EInputEvent Event)
	{
		int32 Fired = 0;
		for (FInputKeyBinding& Binding : Input.KeyBindings)
		{
			if (Binding.Chord.Key == Key && Binding.KeyEvent == Event)
			{
				Binding.KeyDelegate.Execute(Key);
				++Fired;
			}
		}
		return Fired;
	}

	int32 FireAxis(UInputComponent& Input, const FKey& Key, float Value)
	{
		int32 Fired = 0;
		for (FInputAxisKeyBinding& Binding : Input.AxisKeyBindings)
		{
			if (Binding.AxisKey == Key)
			{
				Binding.AxisDelegate.Execute(Value);
				++Fired;
			}
		}
		return Fired;
	}
}

// bot.md 3.1: the eye is the skeleton's Camera bone, the bone the person's camera uses. Camera,
// bone, the bot's view point and the movement's eye agree in every stance and lean.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementEyeTest, "Verse.Movement.Eye", NetEyeTestFlags)
bool FVerseMovementEyeTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, OpenFloorY, 0.f), 20.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	const FVerseMovementTuningValues& T = M->Tuning();
	if (!TestTrue(TEXT("SK_Test_Human has the Camera bone"), Pawn->GetMesh()->GetBoneIndex(AVerseCharacter::CameraBoneName) != INDEX_NONE))
	{
		return false;
	}
	struct FCase { const TCHAR* Name; uint32 Buttons; float Seconds; };
	const FCase Cases[] = {
		{TEXT("stand"), 0u, 1.f},
		{TEXT("crouch"), uint32(EVerseInputButton::Crouch), 1.f},
		{TEXT("lean left"), uint32(EVerseInputButton::LeanLeft), 1.f},
		{TEXT("lean right"), uint32(EVerseInputButton::LeanRight), 1.f},
		{TEXT("crouch lean right"), uint32(EVerseInputButton::Crouch) | uint32(EVerseInputButton::LeanRight), 1.f},
		{TEXT("prone"), uint32(EVerseInputButton::Prone), 1.6f},
	};
	uint32 Prev = 0;
	for (const FCase& Case : Cases)
	{
		W.Place(*Pawn, FVector(0.f, OpenFloorY, 0.f), 20.f);
		HoldFor(W, *Pawn, 0u, FVector2f::ZeroVector, 1.f, Prev);
		HoldFor(W, *Pawn, Case.Buttons, FVector2f::ZeroVector, Case.Seconds, Prev);
		const FVector Camera = Pawn->GetEyeLocation();
		const FVector Bone = Pawn->GetCameraBoneLocation();
		FVector View;
		FRotator ViewRotation;
		Pawn->GetActorEyesViewPoint(View, ViewRotation);
		const FVector Model = M->GetLeanedEyeLocation(M->GetLean());
		AddInfo(FString::Printf(TEXT("%s: camera %s, bone off %.3f cm, model off %.3f cm, eye %.1f cm over the feet"), Case.Name,
			*Camera.ToCompactString(), FVector::Dist(Camera, Bone), FVector::Dist(Camera, Model), Camera.Z - FVerseMovementTestWorld::Feet(*Pawn).Z));
		TestTrue(FString::Printf(TEXT("%s: camera on the Camera bone (0.5 cm)"), Case.Name), FVector::Dist(Camera, Bone) <= 0.5);
		TestTrue(FString::Printf(TEXT("%s: bot view point is the camera"), Case.Name), FVector::Dist(Camera, View) <= 0.01);
		TestTrue(FString::Printf(TEXT("%s: movement eye model matches the camera (1 cm)"), Case.Name), FVector::Dist(Camera, Model) <= 1.0);
	}
	// Prone: the eye moved forward with the lying head, at the prone eye height.
	const FVector Camera = Pawn->GetEyeLocation();
	TestTrue(TEXT("prone eye sits ahead of the capsule, over the head"), ((Camera - Pawn->GetActorLocation()) | Pawn->GetActorForwardVector()) > 15.f);
	TestEqual(TEXT("prone eye height"), float(Camera.Z - FVerseMovementTestWorld::Feet(*Pawn).Z), T.ProneEyeHeight * 100.f, 2.f);
	return true;
}

// WP01.2: the person's default keys (holds, toggles, axes) produce the frames a bot would send,
// and a key-driven pawn walks the same capsule path as a bot fed those frames.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementPersonKeysTest, "Verse.Movement.PersonKeys", NetEyeTestFlags)
bool FVerseMovementPersonKeysTest::RunTest(const FString& Parameters)
{
	using EB = EVerseInputButton;
	{
		FVerseMovementTestWorld W;
		if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
		AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, OpenFloorY, 0.f), 0.f, FVerseMovementTestWorld::EDriver::Person);
		if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
		UInputComponent* Input = NewObject<UInputComponent>(Pawn);
		Pawn->SetupPlayerInputComponent(Input);
		FVerseInputFrameBuilder& B = Pawn->GetPersonInput();
		B.Reset();
		TestTrue(TEXT("W is bound"), FireKey(*Input, VerseKey(TEXT("W")), IE_Pressed) > 0);
		TestTrue(TEXT("W: forward"), B.Consume(0).Move.Equals(FVector2f(1.f, 0.f), 1e-4f));
		FireKey(*Input, VerseKey(TEXT("D")), IE_Pressed);
		TestTrue(TEXT("W+D: forward right"), B.Consume(0).Move.Equals(FVector2f(1.f, 1.f), 1e-4f));
		FireKey(*Input, VerseKey(TEXT("W")), IE_Released);
		FireKey(*Input, VerseKey(TEXT("D")), IE_Released);
		FireKey(*Input, VerseKey(TEXT("A")), IE_Pressed);
		TestTrue(TEXT("A: left"), B.Consume(0).Move.Equals(FVector2f(0.f, -1.f), 1e-4f));
		FireKey(*Input, VerseKey(TEXT("A")), IE_Released);
		TestTrue(TEXT("released: still"), B.Consume(0).Move.Equals(FVector2f::ZeroVector, 1e-4f));

		FireKey(*Input, VerseKey(TEXT("C")), IE_Pressed);
		FVerseInputFrame Frame = B.Consume(0);
		TestTrue(TEXT("C toggles crouch on, pressed this frame"), Frame.IsHeld(EB::Crouch) && Frame.WasPressed(EB::Crouch));
		TestTrue(TEXT("crouch stays held without a key event"), B.Consume(0).IsHeld(EB::Crouch));
		FireKey(*Input, VerseKey(TEXT("Z")), IE_Pressed);
		Frame = B.Consume(0);
		TestTrue(TEXT("Z toggles prone on and releases crouch"), Frame.IsHeld(EB::Prone) && !Frame.IsHeld(EB::Crouch));
		FireKey(*Input, VerseKey(TEXT("Z")), IE_Pressed);
		TestFalse(TEXT("Z again toggles prone off"), B.Consume(0).IsHeld(EB::Prone));
		FireKey(*Input, VerseKey(TEXT("LeftShift")), IE_Pressed);
		FireKey(*Input, VerseKey(TEXT("E")), IE_Pressed);
		Frame = B.Consume(0);
		TestTrue(TEXT("shift holds sprint, E holds lean right"), Frame.IsHeld(EB::Sprint) && Frame.IsHeld(EB::LeanRight));
		FireKey(*Input, VerseKey(TEXT("LeftShift")), IE_Released);
		FireKey(*Input, VerseKey(TEXT("E")), IE_Released);
		Frame = B.Consume(0);
		TestTrue(TEXT("releasing ends the holds"), !Frame.IsHeld(EB::Sprint) && !Frame.IsHeld(EB::LeanRight));
		FireKey(*Input, VerseKey(TEXT("SpaceBar")), IE_Pressed);
		Frame = B.Consume(0);
		TestTrue(TEXT("space presses and holds jump"), Frame.WasPressed(EB::Jump) && Frame.IsHeld(EB::Jump));
		FireKey(*Input, VerseKey(TEXT("SpaceBar")), IE_Released);
		B.Consume(0);
		TestTrue(TEXT("mouse X is bound"), FireAxis(*Input, VerseKey(TEXT("MouseX")), 2.f) > 0);
		FireAxis(*Input, VerseKey(TEXT("MouseY")), -1.f);
		Frame = B.Consume(0);
		TestEqual(TEXT("mouse look in degrees (yaw)"), Frame.LookDeltaDeg.Y, 2.f * VersePersonInput::MouseDegPerValue);
		TestEqual(TEXT("mouse look in degrees (pitch)"), Frame.LookDeltaDeg.X, -1.f * VersePersonInput::MouseDegPerValue);
		FireAxis(*Input, VerseKey(TEXT("Gamepad_LeftY")), 0.6f);
		FireAxis(*Input, VerseKey(TEXT("Gamepad_LeftX")), -0.3f);
		TestTrue(TEXT("gamepad stick moves"), B.Consume(0).Move.Equals(FVector2f(0.6f, -0.3f), 1e-4f));
	}

	// The same 20 s through keys (person) and through frames (bot).
	struct FEvent { int32 Tick; FKey Key; EInputEvent Event; };
	const TArray<FEvent> Events = {
		{0, VerseKey(TEXT("W")), IE_Pressed}, {60, VerseKey(TEXT("LeftShift")), IE_Pressed}, {300, VerseKey(TEXT("LeftShift")), IE_Released},
		{360, VerseKey(TEXT("C")), IE_Pressed}, {600, VerseKey(TEXT("C")), IE_Pressed}, {700, VerseKey(TEXT("Z")), IE_Pressed}, {900, VerseKey(TEXT("Z")), IE_Pressed},
		{1000, VerseKey(TEXT("E")), IE_Pressed}, {1100, VerseKey(TEXT("E")), IE_Released}, {1150, VerseKey(TEXT("D")), IE_Pressed}};
	auto ButtonsAt = [](int32 Tick)
	{
		uint32 Buttons = 0;
		if (Tick >= 60 && Tick < 300) Buttons |= uint32(EB::Sprint);
		if (Tick >= 360 && Tick < 600) Buttons |= uint32(EB::Crouch);
		if (Tick >= 700 && Tick < 900) Buttons |= uint32(EB::Prone);
		if (Tick >= 1000 && Tick < 1100) Buttons |= uint32(EB::LeanRight);
		return Buttons;
	};
	constexpr int32 Ticks = 1200;
	constexpr float YawPerTick = 0.4f;
	TArray<FVector> PersonPath;
	TArray<FVector> BotPath;
	for (const bool bPerson : {true, false})
	{
		FVerseMovementTestWorld W;
		if (!TestTrue(TEXT("parity world"), W.IsValid())) return false;
		AVerseCharacter* Pawn = W.SpawnPawn(FVector(-1500.f, 2400.f, 0.f), 0.f,
			bPerson ? FVerseMovementTestWorld::EDriver::Person : FVerseMovementTestWorld::EDriver::Bot);
		if (!TestNotNull(TEXT("parity pawn"), Pawn)) return false;
		UInputComponent* Input = NewObject<UInputComponent>(Pawn);
		Pawn->SetupPlayerInputComponent(Input);
		Pawn->GetPersonInput().Reset();
		TArray<FVector>& Path = bPerson ? PersonPath : BotPath;
		uint32 Prev = 0;
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			if (bPerson)
			{
				for (const FEvent& Event : Events)
				{
					if (Event.Tick == Tick)
					{
						FireKey(*Input, Event.Key, Event.Event);
					}
				}
				FireAxis(*Input, VerseKey(TEXT("MouseX")), YawPerTick / VersePersonInput::MouseDegPerValue);
			}
			else
			{
				const uint32 Buttons = ButtonsAt(Tick);
				const FVector2f Move(1.f, Tick >= 1150 ? 1.f : 0.f);
				W.Drive(*Pawn, VerseTestFrame(Move, Buttons, Prev, FVector2f(0.f, YawPerTick)));
				Prev = Buttons;
			}
			W.Tick();
			Path.Add(Pawn->GetActorLocation());
		}
	}
	double MaxError = 0.0;
	for (int32 Index = 0; Index < Ticks; ++Index)
	{
		MaxError = FMath::Max(MaxError, FVector::Dist(PersonPath[Index], BotPath[Index]));
	}
	const double Travel = FVector::Dist2D(PersonPath[0], PersonPath.Last());
	AddInfo(FString::Printf(TEXT("keys vs frames: max capsule distance %.4f cm, %.1f m from the start"), MaxError, Travel / 100.0));
	TestTrue(TEXT("the key-driven pawn moved"), Travel > 1000.0);
	TestTrue(TEXT("key and frame paths within 0.1 cm"), MaxError <= 0.1);
	return true;
}

// WP01.4: the prone body never pushes into walls, whether the pawn turns or crawls backwards.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementProneWallsTest, "Verse.Movement.Prone.Walls", NetEyeTestFlags)
bool FVerseMovementProneWallsTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	const FVector Open(-2400.f, OpenFloorY, 0.f);
	// A wall along the pawn's left at 45 cm, and one behind the prone feet end.
	W.AddBox(Open + FVector(0.f, -65.f, 100.f), FVector(400.f, 20.f, 100.f));
	W.AddBox(Open + FVector(-200.f, 0.f, 100.f), FVector(20.f, 40.f, 100.f));
	AVerseCharacter* Pawn = W.SpawnPawn(Open, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	uint32 Prev = 0;
	HoldFor(W, *Pawn, 0u, FVector2f::ZeroVector, 0.5f, Prev);
	HoldFor(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 1.2f, Prev);
	if (!TestTrue(TEXT("prone beside the wall"), M->IsProne()))
	{
		return false;
	}
	int32 Inside = 0;
	auto Check = [&]
	{
		if (M->ProneBodyBlocked(FVerseMovementTestWorld::Feet(*Pawn), Pawn->GetActorRotation().Yaw))
		{
			++Inside;
		}
	};
	const float YawStart = Pawn->GetActorRotation().Yaw;
	// Turn right at the full prone rate for 2 s: the trailing legs swing into the left wall.
	HoldFor(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 2.f, Prev, Check, FVector2f(0.f, 90.f * FVerseMovementTestWorld::Dt));
	const float Turned = FMath::Abs(FRotator::NormalizeAxis(Pawn->GetActorRotation().Yaw - YawStart));
	AddInfo(FString::Printf(TEXT("turned %.1f deg toward the wall before the body stopped it"), Turned));
	TestTrue(TEXT("the wall stopped the turn"), Turned < 60.f);
	TestTrue(TEXT("the pawn could still turn a little"), Turned > 1.f);
	// Crawl backwards into the wall behind for 3 s.
	W.Place(*Pawn, Open, 0.f);
	Prev = 0;
	HoldFor(W, *Pawn, 0u, FVector2f::ZeroVector, 1.2f, Prev);
	HoldFor(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 1.2f, Prev);
	HoldFor(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f(-1.f, 0.f), 3.f, Prev, Check);
	const float FeetEnd = Pawn->GetActorLocation().X - (M->Tuning().ProneBodyLength * 100.f - M->Tuning().ProneRadius * 200.f);
	AddInfo(FString::Printf(TEXT("crawled back to x %.1f, feet end at %.1f (wall face at %.1f)"), Pawn->GetActorLocation().X, FeetEnd, Open.X - 180.f));
	TestTrue(TEXT("the feet end stays in front of the wall behind"), FeetEnd >= Open.X - 181.f);
	TestTrue(TEXT("the pawn crawled backwards"), Pawn->GetActorLocation().X < Open.X - 5.f);
	TestEqual(TEXT("the prone body never ends a move inside a wall"), Inside, 0);
	return true;
}

// WP01.4: the prone turn cap is enforced by the movement itself (server authoritative), not only by the input.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementProneTurnCapTest, "Verse.Movement.Prone.ServerTurnCap", NetEyeTestFlags)
bool FVerseMovementProneTurnCapTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, OpenFloorY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	uint32 Prev = 0;
	HoldFor(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 1.5f, Prev);
	float MaxStep = 0.f;
	for (int32 Tick = 0; Tick < 30; ++Tick)
	{
		// A controller that sets its rotation directly (as a modified client's ServerMove would).
		AController* Controller = Pawn->GetController();
		FRotator Rotation = Controller->GetControlRotation();
		Rotation.Yaw = FRotator::NormalizeAxis(Rotation.Yaw + 30.f);
		Controller->SetControlRotation(Rotation);
		const float Before = Pawn->GetActorRotation().Yaw;
		W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, uint32(EVerseInputButton::Prone), Prev));
		W.Tick();
		MaxStep = FMath::Max(MaxStep, FMath::Abs(FRotator::NormalizeAxis(Pawn->GetActorRotation().Yaw - Before)));
	}
	const float Cap = M->Tuning().ProneTurnCapDegPerSec * FVerseMovementTestWorld::Dt;
	AddInfo(FString::Printf(TEXT("largest yaw step %.3f deg per tick (cap %.3f)"), MaxStep, Cap));
	TestTrue(TEXT("yaw per move stays within the prone cap"), MaxStep <= Cap * 1.05f + 0.06f);
	TestTrue(TEXT("the pawn still turned at the cap"), MaxStep >= Cap * 0.9f);
	return true;
}

// WP01.10: corrections carry the server's state; a replayed move restores only its inputs and
// facing; corrections are booked by the kind of the corrected move.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementNetStateTest, "Verse.Movement.NetState", NetEyeTestFlags)
bool FVerseMovementNetStateTest::RunTest(const FString& Parameters)
{
	for (const bool bMantling : {false, true})
	{
		FVerseMoveState A;
		A.Stance = EVerseStance::Crouch;
		A.BodyShape = EVerseBodyShape::Crouch;
		A.LeanQuantized = -77;
		A.LeanValue = -0.6f;
		A.ProneTransitionRemaining = 0.25f;
		A.bProneExiting = true;
		A.SlideElapsed = 0.4f;
		A.SlideCooldownRemaining = 0.7f;
		A.bMantleLatched = true;
		A.MantleElapsed = bMantling ? 0.2f : -1.f;
		A.MantlePlanDuration = 0.85f;
		A.MantleRiseDuration = 0.4f;
		A.MantleRise = FVector(1.f, 2.f, 3.f);
		A.MantleTarget = FVector(4.f, 5.f, 6.f);
		A.LastMoveYaw = 123.5f;
		A.bHasLastMoveYaw = true;
		A.bYawClamped = true;
		TArray<uint8> Bytes;
		FMemoryWriter Writer(Bytes);
		A.Serialize(Writer);
		FVerseMoveState B;
		FMemoryReader Reader(Bytes);
		B.Serialize(Reader);
		const FString Tag = bMantling ? TEXT(" (mantling)") : TEXT("");
		TestEqual(TEXT("stance round trip") + Tag, int32(B.Stance), int32(A.Stance));
		TestEqual(TEXT("shape round trip") + Tag, int32(B.BodyShape), int32(A.BodyShape));
		TestEqual(TEXT("lean round trip") + Tag, int32(B.LeanQuantized), int32(A.LeanQuantized));
		TestEqual(TEXT("prone timer round trip") + Tag, B.ProneTransitionRemaining, A.ProneTransitionRemaining);
		TestTrue(TEXT("flags round trip") + Tag, B.bProneExiting && B.bMantleLatched && B.bHasLastMoveYaw && B.bYawClamped && !B.bMantleVault);
		TestEqual(TEXT("slide timers round trip") + Tag, B.SlideCooldownRemaining + B.SlideElapsed, A.SlideCooldownRemaining + A.SlideElapsed);
		TestEqual(TEXT("yaw round trip") + Tag, B.LastMoveYaw, A.LastMoveYaw);
		TestEqual(TEXT("mantle time round trip") + Tag, B.MantleElapsed, A.MantleElapsed);
		if (bMantling)
		{
			TestTrue(TEXT("mantle plan round trip"), B.MantleTarget.Equals(A.MantleTarget) && B.MantleRise.Equals(A.MantleRise) && B.MantlePlanDuration == A.MantlePlanDuration);
		}
	}

	FVerseSavedMove Move;
	Move.StartKind = EVerseMoveKind::Walk;
	Move.EndKind = EVerseMoveKind::Mantle;
	TestEqual(TEXT("a move that starts a mantle books as mantle"), int32(Move.GetCorrectionKind()), int32(EVerseMoveKind::Mantle));
	Move.StartKind = EVerseMoveKind::Prone;
	Move.EndKind = EVerseMoveKind::Walk;
	TestEqual(TEXT("a move leaving prone books as prone"), int32(Move.GetCorrectionKind()), int32(EVerseMoveKind::Prone));
	Move.StartKind = EVerseMoveKind::Walk;
	Move.EndKind = EVerseMoveKind::Airborne;
	TestEqual(TEXT("otherwise the end kind"), int32(Move.GetCorrectionKind()), int32(EVerseMoveKind::Airborne));

	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, OpenFloorY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	FVerseSavedMove Replayed;
	Replayed.StartState.Stance = EVerseStance::Prone;
	Replayed.StartState.BodyShape = EVerseBodyShape::Prone;
	Replayed.StartState.MantleElapsed = 0.3f;
	Replayed.StartRotation = FRotator(0.f, 45.f, 0.f);
	Replayed.SavedLeanTarget = 127;
	Replayed.PrepMoveFor(Pawn);
	TestEqual(TEXT("replay keeps the simulated stance (no restore of the old prediction)"), int32(M->GetStance()), int32(EVerseStance::Stand));
	TestFalse(TEXT("replay does not restart an old mantle"), M->IsMantling());
	TestEqual(TEXT("replay restores the move's facing"), float(Pawn->GetActorRotation().Yaw), 45.f, 0.01f);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

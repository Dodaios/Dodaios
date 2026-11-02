#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Camera/CameraComponent.h"
#include "Components/BoxComponent.h"
#include "Engine/World.h"
#include "Fixture/VerseMovementCourse.h"
#include "Tests/Movement/VerseMovementTestWorld.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseRng.h"

namespace
{
	constexpr EAutomationTestFlags MovesTestFlags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;
	using namespace VerseMovementCourse;

	/** Holds Buttons and Move for Seconds; Pressed only on the first tick. */
	void Hold(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, uint32 Buttons, const FVector2f& Move, float Seconds, uint32& Prev,
		TFunctionRef<void()> PerTick = [] {})
	{
		const int32 Ticks = FMath::Max(1, FMath::RoundToInt(Seconds / FVerseMovementTestWorld::Dt));
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			W.Drive(Pawn, VerseTestFrame(Move, Buttons, Prev));
			Prev = Buttons;
			W.Tick();
			PerTick();
		}
	}

	void Settle(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, uint32& Prev)
	{
		Hold(W, Pawn, 0u, FVector2f::ZeroVector, 0.9f, Prev);
	}
}

// A1.3: prone passes the 0.75 m tunnel, standing and crouch do not; prone never starts with less
// than 0.4 m clearance.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementProneClearanceTest, "Verse.Movement.Prone.Clearance", MovesTestFlags)
bool FVerseMovementProneClearanceTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	const FVector Entry(TunnelEntryX - 120.f, CrawlTunnelY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Entry, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	const float Exit = TunnelEntryX + TunnelLength;
	uint32 Prev = 0;
	struct FCase { const TCHAR* Name; uint32 Buttons; float Seconds; bool bPasses; };
	const FCase Cases[] = {
		{TEXT("standing"), 0u, 4.f, false},
		{TEXT("crouched"), uint32(EVerseInputButton::Crouch), 6.f, false},
		{TEXT("prone"), uint32(EVerseInputButton::Prone), 8.f, true},
	};
	for (const FCase& Case : Cases)
	{
		W.Place(*Pawn, Entry, 0.f);
		Settle(W, *Pawn, Prev);
		Hold(W, *Pawn, Case.Buttons, FVector2f(1.f, 0.f), Case.Seconds, Prev);
		const float X = Pawn->GetActorLocation().X;
		AddInfo(FString::Printf(TEXT("%s reached x = %.1f (tunnel %0.f..%0.f)"), Case.Name, X, TunnelEntryX, Exit));
		TestTrue(FString::Printf(TEXT("%s %s the 0.75 m tunnel"), Case.Name, Case.bPasses ? TEXT("passes") : TEXT("is blocked by")), (X > Exit) == Case.bPasses);
		Hold(W, *Pawn, Case.Buttons, FVector2f(-1.f, 0.f), Case.Seconds, Prev);
	}
	// Crouch passes the 1.2 m tunnel, standing does not.
	const FVector CrouchEntry(TunnelEntryX - 120.f, CrouchTunnelY, 0.f);
	for (const bool bCrouch : {false, true})
	{
		W.Place(*Pawn, CrouchEntry, 0.f);
		Settle(W, *Pawn, Prev);
		Hold(W, *Pawn, bCrouch ? uint32(EVerseInputButton::Crouch) : 0u, FVector2f(1.f, 0.f), 4.f, Prev);
		TestTrue(FString::Printf(TEXT("%s %s the 1.2 m tunnel"), bCrouch ? TEXT("crouch") : TEXT("standing"), bCrouch ? TEXT("passes") : TEXT("is blocked by")),
			(Pawn->GetActorLocation().X > Exit) == bCrouch);
	}

	// Seeded clearance poses: a slab over the prone body footprint at a random height.
	FVerseRng Rng(4242, 0, EVerseRngSalt::Harness);
	const FVector Open(0.f, OpenFloorY, 0.f);
	int32 Refused = 0;
	int32 Allowed = 0;
	int32 Violations = 0;
	for (int32 Pose = 0; Pose < 200; ++Pose)
	{
		const float Bottom = float(Rng.Range(20.0, 70.0));
		const float Along = float(Rng.Range(-150.0, -55.0)); // behind the standing capsule, over the prone legs
		UBoxComponent* Slab = W.AddBox(Open + FVector(Along, 0.f, Bottom + 25.f), FVector(15.f, 60.f, 25.f));
		W.Place(*Pawn, Open, 0.f);
		Settle(W, *Pawn, Prev);
		Hold(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f::ZeroVector, 0.2f, Prev);
		const bool bProne = M->IsProne();
		const bool bBodyUnder = Along - 15.f < 40.f && Along + 15.f > -140.f;
		if (bProne && Bottom < 40.f && bBodyUnder)
		{
			++Violations;
		}
		(bProne ? Allowed : Refused) += 1;
		Hold(W, *Pawn, 0u, FVector2f::ZeroVector, 1.0f, Prev);
		Slab->GetOwner()->Destroy();
	}
	AddInfo(FString::Printf(TEXT("clearance poses: %d prone, %d refused, %d under 0.4 m"), Allowed, Refused, Violations));
	TestEqual(TEXT("prone never starts under 0.4 m clearance"), Violations, 0);
	TestTrue(TEXT("prone starts where it fits"), Allowed > 20);
	TestTrue(TEXT("prone is refused where it does not"), Refused > 20);
	return true;
}

// WP01.4: prone transitions (enter 0.7 s, exit 0.6 s, no movement meanwhile) and the 90 deg/s turn cap.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementProneTransitionsTest, "Verse.Movement.Prone.Transitions", MovesTestFlags)
bool FVerseMovementProneTransitionsTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	const FVector Open(0.f, OpenFloorY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Open, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	const FVerseMovementTuningValues& T = M->Tuning();
	uint32 Prev = 0;
	Settle(W, *Pawn, Prev);
	const FVector Before = Pawn->GetActorLocation();
	int32 Frozen = 0;
	Hold(W, *Pawn, uint32(EVerseInputButton::Prone), FVector2f(1.f, 0.f), 1.5f, Prev, [&]
	{
		if (M->GetProneTransitionAlpha() > 0.f)
		{
			++Frozen;
		}
	});
	const float EnterSeconds = Frozen * FVerseMovementTestWorld::Dt;
	AddInfo(FString::Printf(TEXT("prone enter %.3f s"), EnterSeconds));
	TestEqual(TEXT("prone enter takes 0.7 s (within a tick)"), EnterSeconds, T.ProneEnterTime, FVerseMovementTestWorld::Dt * 1.5f);
	TestTrue(TEXT("prone crawls after the transition"), FVector::Dist2D(Pawn->GetActorLocation(), Before) > 30.f);
	TestEqual(TEXT("prone stance"), int32(M->GetStance()), int32(EVerseStance::Prone));
	TestTrue(TEXT("prone capsule is 0.4 m"), FMath::IsNearlyEqual(Pawn->GetSimpleCollisionHalfHeight() * 2.f, T.ProneMinClearance * 100.f, 1.f));

	// Turn cap: ask for 600 deg/s.
	const float YawBefore = Pawn->GetControlRotation().Yaw;
	for (int32 Tick = 0; Tick < 60; ++Tick)
	{
		W.Drive(*Pawn, VerseTestFrame(FVector2f::ZeroVector, uint32(EVerseInputButton::Prone), Prev, FVector2f(0.f, 10.f)));
		Prev = uint32(EVerseInputButton::Prone);
		W.Tick();
	}
	const float Turned = FMath::Abs(FRotator::NormalizeAxis(Pawn->GetControlRotation().Yaw - YawBefore));
	AddInfo(FString::Printf(TEXT("prone turned %.1f deg in 1 s"), Turned));
	TestTrue(TEXT("prone turn capped at 90 deg/s"), Turned <= T.ProneTurnCapDegPerSec + 0.5f && Turned >= T.ProneTurnCapDegPerSec - 2.f);

	// Exit.
	const FVector Down = Pawn->GetActorLocation();
	int32 ExitFrozen = 0;
	Hold(W, *Pawn, 0u, FVector2f(1.f, 0.f), 1.2f, Prev, [&]
	{
		if (M->GetProneTransitionAlpha() < 0.f)
		{
			++ExitFrozen;
		}
	});
	TestEqual(TEXT("prone exit takes 0.6 s (within a tick)"), ExitFrozen * FVerseMovementTestWorld::Dt, T.ProneExitTime, FVerseMovementTestWorld::Dt * 1.5f);
	TestEqual(TEXT("standing again"), int32(M->GetStance()), int32(EVerseStance::Stand));
	TestTrue(TEXT("standing capsule restored"), FMath::IsNearlyEqual(Pawn->GetSimpleCollisionHalfHeight(), T.StandHalfHeightCm(), 0.5f));
	TestTrue(TEXT("walks off after standing"), FVector::Dist2D(Pawn->GetActorLocation(), Down) > 10.f);
	return true;
}

// A1.4: slide only from sprint at 5.5 m/s or more; ends in crouch within 1.1 s; a second slide is blocked for 1.0 s.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementSlideTest, "Verse.Movement.Slide", MovesTestFlags)
bool FVerseMovementSlideTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	const FVector Start(-2600.f, OpenFloorY, 0.f);
	AVerseCharacter* Pawn = W.SpawnPawn(Start, 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	const FVerseMovementTuningValues& T = M->Tuning();
	const uint32 Sprint = uint32(EVerseInputButton::Sprint);
	const uint32 Crouch = uint32(EVerseInputButton::Crouch);
	uint32 Prev = 0;

	// Walk speed: no slide.
	Hold(W, *Pawn, 0u, FVector2f(1.f, 0.f), 1.5f, Prev);
	Hold(W, *Pawn, Crouch, FVector2f(1.f, 0.f), 0.2f, Prev);
	TestFalse(TEXT("no slide from a walk"), M->IsSliding());
	// Sprint key held but still below 5.5 m/s.
	W.Place(*Pawn, Start, 0.f);
	Settle(W, *Pawn, Prev);
	Hold(W, *Pawn, Sprint, FVector2f(1.f, 0.f), 0.08f, Prev);
	const float EarlySpeed = Pawn->GetVelocity().Size2D() / 100.f;
	Hold(W, *Pawn, Sprint | Crouch, FVector2f(1.f, 0.f), 0.1f, Prev);
	AddInfo(FString::Printf(TEXT("early crouch at %.2f m/s"), EarlySpeed));
	TestTrue(TEXT("slow sprint below the floor"), EarlySpeed < T.SlideMinEntrySpeed);
	TestFalse(TEXT("no slide below 5.5 m/s"), M->IsSliding());

	// Full sprint: slide.
	W.Place(*Pawn, Start, 0.f);
	Settle(W, *Pawn, Prev);
	Hold(W, *Pawn, Sprint, FVector2f(1.f, 0.f), 1.5f, Prev);
	TestTrue(TEXT("sprinting at full speed"), Pawn->GetVelocity().Size2D() >= T.SlideMinEntrySpeed * 100.f);
	int32 SlideTicks = 0;
	float PeakSpeed = 0.f;
	bool bStarted = false;
	// Hold sprint and crouch until the slide has ended (the cooldown starts there).
	for (int32 Tick = 0; Tick < 150; ++Tick)
	{
		W.Drive(*Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Sprint | Crouch, Prev));
		Prev = Sprint | Crouch;
		W.Tick();
		if (M->IsSliding())
		{
			bStarted = true;
			++SlideTicks;
			PeakSpeed = FMath::Max(PeakSpeed, float(Pawn->GetVelocity().Size2D()));
		}
		else if (bStarted)
		{
			break;
		}
	}
	const float SlideSeconds = SlideTicks * FVerseMovementTestWorld::Dt;
	AddInfo(FString::Printf(TEXT("slide %.3f s, peak %.2f m/s"), SlideSeconds, PeakSpeed / 100.f));
	TestTrue(TEXT("slide starts from sprint"), bStarted);
	TestTrue(TEXT("slide ends within 1.1 s"), SlideSeconds <= T.SlideMaxDuration + FVerseMovementTestWorld::Dt * 0.5f);
	TestTrue(TEXT("slide boosts toward 7.5 m/s"), PeakSpeed >= T.SlideBoostSpeed * 100.f - 30.f);
	TestEqual(TEXT("slide ends in crouch"), int32(M->GetStance()), int32(EVerseStance::Crouch));

	// Cooldown: stand, sprint up again and try within 1.0 s, then after.
	Hold(W, *Pawn, Sprint, FVector2f(1.f, 0.f), 0.5f, Prev);
	TestTrue(TEXT("back to sprint speed within the cooldown"), Pawn->GetVelocity().Size2D() >= T.SlideMinEntrySpeed * 100.f);
	TestTrue(TEXT("cooldown still running"), M->GetSlideCooldownRemaining() > 0.f);
	Hold(W, *Pawn, Sprint | Crouch, FVector2f(1.f, 0.f), 0.1f, Prev);
	TestFalse(TEXT("second slide blocked during the 1.0 s cooldown"), M->IsSliding());
	Hold(W, *Pawn, Sprint, FVector2f(1.f, 0.f), 0.8f, Prev);
	TestEqual(TEXT("cooldown over"), M->GetSlideCooldownRemaining(), 0.f);
	Hold(W, *Pawn, Sprint | Crouch, FVector2f(1.f, 0.f), 0.1f, Prev);
	TestTrue(TEXT("slide allowed after the cooldown"), M->IsSliding());
	return true;
}

namespace
{
	struct FMantleResult
	{
		bool bMantled = false;
		bool bOnTop = false;
		int32 MantleTicks = 0;
	};

	/** One seeded approach at ledge Index: walk or sprint in, press jump at PressDistance. */
	FMantleResult Approach(FVerseMovementTestWorld& W, AVerseCharacter& Pawn, int32 Index, FVerseRng& Rng)
	{
		UVerseCharacterMovement* M = Pawn.GetVerseMovement();
		const float Height = LedgeHeights[Index];
		const float Distance = float(Rng.Range(120.0, 420.0));
		const float Lateral = float(Rng.Range(-80.0, 80.0));
		const float Yaw = float(Rng.Range(-20.0, 20.0));
		const bool bSprint = Rng.Chance(0.5);
		const float PressAt = float(Rng.Range(45.0, 140.0)); // capsule centre to face, cm
		W.Place(Pawn, FVector(LedgeFaceX - Distance, LedgeLaneY(Index) + Lateral, 0.f), Yaw);
		uint32 Prev = 0;
		Hold(W, Pawn, 0u, FVector2f::ZeroVector, 0.1f, Prev);
		const int32 Before = M->GetMantleCount();
		FMantleResult Result;
		for (int32 Tick = 0; Tick < 180; ++Tick)
		{
			const float ToFace = LedgeFaceX - Pawn.GetActorLocation().X;
			uint32 Buttons = bSprint ? uint32(EVerseInputButton::Sprint) : 0u;
			if (ToFace <= PressAt / FMath::Cos(FMath::DegreesToRadians(Yaw)))
			{
				Buttons |= uint32(EVerseInputButton::Jump);
			}
			W.Drive(Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Buttons, Prev));
			Prev = Buttons;
			const bool bBefore = M->IsMantling();
			W.Tick();
			if (bBefore || M->IsMantling())
			{
				++Result.MantleTicks; // every tick that simulated part of the mantle
			}
			if (bBefore && !M->IsMantling())
			{
				break;
			}
		}
		Hold(W, Pawn, 0u, FVector2f::ZeroVector, 0.1f, Prev);
		Result.bMantled = M->GetMantleCount() > Before;
		Result.bOnTop = FMath::Abs(FVerseMovementTestWorld::Feet(Pawn).Z - Height) < 6.f && Pawn.GetActorLocation().X > LedgeFaceX;
		return Result;
	}
}

// A1.2: 1,000 seeded approaches: 0.5-2.0 m succeed at least 99.5 %; 2.1 m never mantles; time within a tick.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementMantleTest, "Verse.Movement.Mantle.Ledges", MovesTestFlags)
bool FVerseMovementMantleTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, LedgeLaneY(0), 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	const FVerseMovementTuningValues& T = Pawn->GetVerseMovement()->Tuning();
	FVerseRng Rng(90210, 0, EVerseRngSalt::Harness);
	int32 Attempts[LedgeCount] = {};
	int32 Successes[LedgeCount] = {};
	int32 Mantled[LedgeCount] = {};
	int32 TimingMisses = 0;
	for (int32 Run = 0; Run < 1000; ++Run)
	{
		const int32 Index = Run % LedgeCount;
		const FMantleResult Result = Approach(W, *Pawn, Index, Rng);
		++Attempts[Index];
		Successes[Index] += Result.bOnTop ? 1 : 0;
		Mantled[Index] += Result.bMantled ? 1 : 0;
		if (Result.bMantled && Index < LedgeCount - 1)
		{
			const float Expected = LedgeHeights[Index] > T.MantleLowMaxHeight * 100.f ? T.MantleHighDuration : T.MantleLowDuration;
			const float Seconds = Result.MantleTicks * FVerseMovementTestWorld::Dt;
			if (FMath::Abs(Seconds - Expected) > FVerseMovementTestWorld::Dt + KINDA_SMALL_NUMBER)
			{
				++TimingMisses;
				AddInfo(FString::Printf(TEXT("mantle %.0f cm took %.3f s, want %.3f s"), LedgeHeights[Index], Seconds, Expected));
			}
		}
		if (Index == LedgeCount - 1 && Result.bMantled)
		{
			AddError(FString::Printf(TEXT("approach %d mantled the 2.1 m wall"), Run));
		}
	}
	for (int32 Index = 0; Index < LedgeCount; ++Index)
	{
		const float Rate = float(Successes[Index]) / FMath::Max(Attempts[Index], 1);
		AddInfo(FString::Printf(TEXT("ledge %.1f m: on top %d / %d (%.1f %%), mantled %d"), LedgeHeights[Index] / 100.f, Successes[Index], Attempts[Index], Rate * 100.f, Mantled[Index]));
		if (Index < LedgeCount - 1)
		{
			TestTrue(FString::Printf(TEXT("ledge %.1f m succeeds at least 99.5 %%"), LedgeHeights[Index] / 100.f), Rate >= 0.995f);
		}
		else
		{
			TestEqual(TEXT("2.1 m never mantles"), Mantled[Index], 0);
			TestEqual(TEXT("2.1 m is never climbed"), Successes[Index], 0);
		}
	}
	TestEqual(TEXT("mantle time within one tick of the DataAsset"), TimingMisses, 0);
	return true;
}

// WP01.6: mantle through a low breach (destruction.md 6.1 mantle links): crouched, ends beyond the wall.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementMantleBreachTest, "Verse.Movement.Mantle.Breach", MovesTestFlags)
bool FVerseMovementMantleBreachTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(BreachWallX - 200.f, BreachY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	FVerseRng Rng(777, 0, EVerseRngSalt::Harness);
	int32 Through = 0;
	const int32 Runs = 50;
	for (int32 Run = 0; Run < Runs; ++Run)
	{
		W.Place(*Pawn, FVector(BreachWallX - float(Rng.Range(110.0, 300.0)), BreachY + float(Rng.Range(-60.0, 60.0)), 0.f), float(Rng.Range(-10.0, 10.0)));
		uint32 Prev = 0;
		Hold(W, *Pawn, 0u, FVector2f::ZeroVector, 0.1f, Prev);
		bool bCrouchedMantle = false;
		for (int32 Tick = 0; Tick < 240; ++Tick)
		{
			const float ToWall = BreachWallX - Pawn->GetActorLocation().X;
			const uint32 Buttons = ToWall < 95.f ? uint32(EVerseInputButton::Jump) : 0u;
			W.Drive(*Pawn, VerseTestFrame(FVector2f(1.f, 0.f), Buttons, Prev));
			Prev = Buttons;
			W.Tick();
			bCrouchedMantle |= M->IsMantling() && Pawn->GetSimpleCollisionHalfHeight() < M->Tuning().StandHalfHeightCm() - 1.f;
		}
		const bool bBeyond = Pawn->GetActorLocation().X > BreachWallX + 25.f + 30.f && FVerseMovementTestWorld::Feet(*Pawn).Z < 10.f;
		Through += (bBeyond && bCrouchedMantle) ? 1 : 0;
	}
	AddInfo(FString::Printf(TEXT("breach mantles: %d / %d"), Through, Runs));
	TestTrue(TEXT("mantle through the low breach at least 98 %"), Through >= Runs - 1);
	return true;
}

// WP01.7: lean offset, roll and enter time in free space.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementLeanValuesTest, "Verse.Movement.Lean.Values", MovesTestFlags)
bool FVerseMovementLeanValuesTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(0.f, OpenFloorY, 0.f), 30.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	const FVerseMovementTuningValues& T = M->Tuning();
	uint32 Prev = 0;
	Settle(W, *Pawn, Prev);
	const FVector Eye = Pawn->GetEyeLocation();
	int32 TicksToFull = -1;
	int32 Tick = 0;
	Hold(W, *Pawn, uint32(EVerseInputButton::LeanRight), FVector2f::ZeroVector, 0.5f, Prev, [&]
	{
		++Tick;
		if (TicksToFull < 0 && M->GetLeanQuantized() == 127)
		{
			TicksToFull = Tick;
		}
	});
	const FVector Offset = Pawn->GetEyeLocation() - Eye;
	const float Side = Offset | Pawn->GetActorRightVector();
	AddInfo(FString::Printf(TEXT("lean right: %.2f cm, roll %.2f deg, %d ticks"), Side, Pawn->GetEyeRotation().Roll, TicksToFull));
	TestEqual(TEXT("lean camera offset 35 cm"), Side, T.LeanCameraOffset * 100.f, 0.5f);
	TestEqual(TEXT("lean roll 12 deg"), float(FMath::Abs(Pawn->GetEyeRotation().Roll)), T.LeanRollDeg, 0.2f);
	TestEqual(TEXT("lean enters in 0.15 s"), TicksToFull * FVerseMovementTestWorld::Dt, T.LeanEnterTime, FVerseMovementTestWorld::Dt * 1.01f);
	Hold(W, *Pawn, uint32(EVerseInputButton::LeanLeft), FVector2f::ZeroVector, 0.5f, Prev);
	TestEqual(TEXT("lean left reaches -127"), int32(M->GetLeanQuantized()), -127);
	Hold(W, *Pawn, uint32(EVerseInputButton::LeanLeft) | uint32(EVerseInputButton::Sprint), FVector2f(1.f, 0.f), 0.8f, Prev);
	TestEqual(TEXT("sprinting cancels the lean"), int32(M->GetLeanQuantized()), 0);
	return true;
}

// A1.5: leaning against a wall never puts the camera inside geometry (0 of 500 seeded corner poses).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseMovementLeanWallTest, "Verse.Movement.Lean.Wall", MovesTestFlags)
bool FVerseMovementLeanWallTest::RunTest(const FString& Parameters)
{
	FVerseMovementTestWorld W;
	if (!TestTrue(TEXT("test world"), W.IsValid())) return false;
	AVerseCharacter* Pawn = W.SpawnPawn(FVector(CornerEndX - 200.f, CornerLaneY, 0.f), 0.f);
	if (!TestNotNull(TEXT("pawn"), Pawn)) return false;
	UVerseCharacterMovement* M = Pawn->GetVerseMovement();
	UWorld* World = W.GetWorld();
	FVerseRng Rng(31337, 0, EVerseRngSalt::Harness);
	int32 Inside = 0;
	int32 Limited = 0;
	int32 Full = 0;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseLeanTest), false, Pawn);
	for (int32 Pose = 0; Pose < 500; ++Pose)
	{
		// Corridor between the walls (faces at +-85 cm from the lane), the capsule radius keeps 34 cm.
		const float Y = CornerLaneY + float(Rng.Range(-50.0, 50.0));
		const float X = CornerEndX - float(Rng.Range(-60.0, 500.0));
		const float Yaw = float(Rng.Range(-180.0, 180.0));
		const bool bCrouch = Rng.Chance(0.3);
		const uint32 Lean = Rng.Chance(0.5) ? uint32(EVerseInputButton::LeanLeft) : uint32(EVerseInputButton::LeanRight);
		W.Place(*Pawn, FVector(X, Y, 0.f), Yaw);
		uint32 Prev = 0;
		const uint32 Base = bCrouch ? uint32(EVerseInputButton::Crouch) : 0u;
		Hold(W, *Pawn, Base, FVector2f::ZeroVector, 0.3f, Prev);
		Hold(W, *Pawn, Base | Lean, FVector2f::ZeroVector, 0.35f, Prev);
		const FVector Camera = Pawn->GetEyeLocation();
		const FVector Eye = M->GetUnleanedEyeLocation();
		FHitResult Hit;
		const bool bOverlap = World->OverlapBlockingTestByChannel(Camera, FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(5.f), Params);
		const bool bBlocked = World->LineTraceSingleByChannel(Hit, Eye, Camera, ECC_Visibility, Params);
		if (bOverlap || bBlocked)
		{
			++Inside;
			AddInfo(FString::Printf(TEXT("pose %d: camera inside geometry at %s (lean %d)"), Pose, *Camera.ToCompactString(), int32(M->GetLeanQuantized())));
		}
		(FMath::Abs(M->GetLeanQuantized()) == 127 ? Full : Limited) += 1;
		Hold(W, *Pawn, 0u, FVector2f::ZeroVector, 0.3f, Prev);
	}
	AddInfo(FString::Printf(TEXT("lean poses: %d full, %d limited by the wall check, %d inside geometry"), Full, Limited, Inside));
	TestEqual(TEXT("camera never inside geometry"), Inside, 0);
	TestTrue(TEXT("the wall check limited some leans"), Limited > 20);
	TestTrue(TEXT("open leans reach full"), Full > 20);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

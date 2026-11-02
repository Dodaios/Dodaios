#include "VerseMovementScripts.h"

#include "Fixture/VerseMovementCourse.h"
#include "VerseCharacterMovement.h"
#include "VerseRng.h"

namespace
{
	enum class ESegment : uint8
	{
		Run,
		Sprint,
		SprintSlide,
		CrouchWalk,
		ProneCrawl,
		LeanPeek,
		Jump,
		MantleRun,
		Count
	};

	struct FSoakState
	{
		FVerseRng Rng;
		ESegment Segment = ESegment::Run;
		float SegmentEnd = 0.f;
		float SegmentStart = 0.f;
		float TurnRate = 0.f;
		FVector Goal = FVector::ZeroVector;
		bool bHasGoal = false;
		bool bJumped = false;
		explicit FSoakState(uint64 Seed) : Rng(Seed, 0, EVerseRngSalt::Harness) {}
	};

	float SteerYaw(const AVerseCharacter& Pawn, const FVector& Goal, float MaxStep)
	{
		const FVector To = (Goal - Pawn.GetActorLocation()).GetSafeNormal2D();
		if (To.IsNearlyZero())
		{
			return 0.f;
		}
		const float Want = FMath::RadiansToDegrees(FMath::Atan2(To.Y, To.X));
		const float Delta = FRotator::NormalizeAxis(Want - Pawn.GetControlRotation().Yaw);
		return FMath::Clamp(Delta, -MaxStep, MaxStep);
	}
}

FVerseInputScript VerseMovementScripts::MakeSoak(uint64 Seed, float Duration, TWeakObjectPtr<AVerseCharacter> Pawn, const FVector& CourseOrigin)
{
	TSharedRef<FSoakState> State = MakeShared<FSoakState>(Seed);
	return [State, Duration, Pawn, CourseOrigin](float Time, float DeltaSeconds, FVerseInputFrame& Frame) -> bool
	{
		AVerseCharacter* Character = Pawn.Get();
		if (!Character || Time >= Duration)
		{
			return false;
		}
		FSoakState& S = *State;
		const FVector Home = CourseOrigin + FVector(300.f, 2400.f, 0.f);
		if (Time >= S.SegmentEnd)
		{
			S.Segment = ESegment(S.Rng.RangeInt(0, int32(ESegment::Count) - 1));
			S.SegmentStart = Time;
			S.SegmentEnd = Time + float(S.Rng.Range(1.2, 3.5));
			S.TurnRate = float(S.Rng.Range(-60.0, 60.0));
			S.bJumped = false;
			S.bHasGoal = false;
			if (S.Segment == ESegment::MantleRun)
			{
				const int32 Lane = S.Rng.RangeInt(0, 3);
				S.Goal = CourseOrigin + FVector(VerseMovementCourse::LedgeFaceX + 100.f,
					VerseMovementCourse::LedgeLaneY(Lane) + float(S.Rng.Range(-150.0, 150.0)), 0.f);
				S.bHasGoal = true;
				S.SegmentEnd = Time + 6.f;
			}
			else if (FVector::Dist2D(Character->GetActorLocation(), Home) > 2200.f)
			{
				S.Goal = Home;
				S.bHasGoal = true;
			}
		}
		const float Local = Time - S.SegmentStart;
		const float MaxTurn = 240.f * DeltaSeconds;
		float Yaw = S.bHasGoal ? SteerYaw(*Character, S.Goal, MaxTurn) : S.TurnRate * DeltaSeconds;
		uint32 Buttons = 0;
		FVector2f Move(1.f, 0.f);
		switch (S.Segment)
		{
		case ESegment::Run:
			break;
		case ESegment::Sprint:
			Buttons |= uint32(EVerseInputButton::Sprint);
			break;
		case ESegment::SprintSlide:
			Buttons |= uint32(EVerseInputButton::Sprint);
			if (Local > 1.2f && Local < 2.4f)
			{
				Buttons |= uint32(EVerseInputButton::Crouch);
			}
			Yaw *= 0.2f;
			break;
		case ESegment::CrouchWalk:
			Buttons |= uint32(EVerseInputButton::Crouch);
			Move = FVector2f(0.8f, Local > 1.f ? 0.4f : -0.4f);
			break;
		case ESegment::ProneCrawl:
			Buttons |= uint32(EVerseInputButton::Prone);
			Move = Local > 0.9f ? FVector2f(1.f, 0.f) : FVector2f::ZeroVector;
			S.SegmentEnd = FMath::Max(S.SegmentEnd, S.SegmentStart + 3.5f);
			break;
		case ESegment::LeanPeek:
			Move = FVector2f(0.4f, 0.f);
			Buttons |= uint32(FMath::Fmod(Local, 1.2f) < 0.6f ? EVerseInputButton::LeanLeft : EVerseInputButton::LeanRight);
			break;
		case ESegment::Jump:
			if (FMath::Fmod(Local, 0.9f) < 0.15f)
			{
				Buttons |= uint32(EVerseInputButton::Jump);
			}
			break;
		case ESegment::MantleRun:
		{
			const float Distance = FVector::Dist2D(Character->GetActorLocation(), S.Goal);
			if (Distance < 260.f && !S.bJumped)
			{
				Buttons |= uint32(EVerseInputButton::Jump);
				if (Character->GetVerseMovement()->IsMantling())
				{
					S.bJumped = true;
					S.SegmentEnd = FMath::Min(S.SegmentEnd, Time + 1.2f);
				}
			}
			if (S.bJumped)
			{
				S.bHasGoal = false;
				Move = FVector2f(0.5f, 0.f);
			}
			break;
		}
		default:
			break;
		}
		Frame.Move = Move;
		Frame.LookDeltaDeg = FVector2f(0.f, Yaw);
		Frame.Buttons = Buttons;
		Frame.Pressed = Buttons & ~Character->GetLastAppliedFrame().Buttons;
		return true;
	};
}

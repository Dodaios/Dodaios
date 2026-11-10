#include "VerseDuelAutopilot.h"

#include "Damage/VerseCombatStateComponent.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Controller.h"
#include "NavigationPath.h"
#include "NavigationSystem.h"

namespace VerseDuelAutopilot
{
	namespace
	{
		/** Person-like limits (the "average" person model of Data/bot/person_models.json, rounded). */
		constexpr float TurnRateDegS = 420.f;
		constexpr float AimNoiseDeg = 0.9f;
		constexpr float FireConeDeg = 2.5f;
		constexpr float KnifeRangeCm = 180.f;
		constexpr float RepathS = 0.5f;

		struct FState
		{
			FRandomStream Rng;
			float StrafeSign = 1.f;
			float NextStrafeFlipS = 0.f;
			float BurstUntilS = 0.f;
			float PauseUntilS = 0.f;
			float LastSeenS = -100.f;
			float NoSightSinceS = 0.f;
			float NextRepathS = 0.f;
			float LastHealthCheckS = 0.f;
			bool bBulwarkUsed = false;
			bool bChargeUsed = false;
			FVector2f AimNoise = FVector2f::ZeroVector;
			TArray<FVector> Path;
			int32 PathIndex = 0;
		};

		APawn* FindOpponent(const AVerseCharacter& Self)
		{
			const UWorld* World = Self.GetWorld();
			APawn* Best = nullptr;
			double BestDist = TNumericLimits<double>::Max();
			for (TActorIterator<AVerseCharacter> It(World); It; ++It)
			{
				AVerseCharacter* Other = *It;
				if (Other == &Self || !Other->GetController())
				{
					continue;
				}
				const UVerseCombatStateComponent* Combat = Other->FindComponentByClass<UVerseCombatStateComponent>();
				if (Combat && !Combat->IsAlive())
				{
					continue;
				}
				const double Dist = FVector::DistSquared(Other->GetActorLocation(), Self.GetActorLocation());
				if (Dist < BestDist)
				{
					BestDist = Dist;
					Best = Other;
				}
			}
			return Best;
		}

		bool HasSight(const AVerseCharacter& Self, const FVector& Eye, const FVector& Target, const AActor* Opponent)
		{
			FCollisionQueryParams Params(TEXT("VerseAutopilotSight"), false, &Self);
			FHitResult Hit;
			if (!Self.GetWorld()->LineTraceSingleByChannel(Hit, Eye, Target, ECC_Visibility, Params))
			{
				return true;
			}
			return Hit.GetActor() == Opponent;
		}
	}

	FVerseInputScript Make(AVerseCharacter* Pawn, uint32 Seed)
	{
		TSharedRef<FState> State = MakeShared<FState>();
		State->Rng.Initialize(int32(Seed));
		TWeakObjectPtr<AVerseCharacter> Weak(Pawn);
		return [Weak, State](float ScriptTime, float DeltaSeconds, FVerseInputFrame& Out) -> bool
		{
			AVerseCharacter* Self = Weak.Get();
			if (!Self || !Self->GetController())
			{
				return false;
			}
			FState& S = *State;
			const float T = ScriptTime;
			APawn* Opponent = FindOpponent(*Self);
			if (!Opponent)
			{
				return true;
			}
			FVector Eye;
			FRotator EyeRotation;
			Self->GetActorEyesViewPoint(Eye, EyeRotation);
			const FVector Chest = Opponent->GetActorLocation() + FVector(0.0, 0.0, 35.0);
			const bool bSight = HasSight(*Self, Eye, Chest, Opponent);
			const double Distance = FVector::Dist(Self->GetActorLocation(), Opponent->GetActorLocation());

			// Aim: turn toward the chest at the turn rate, plus a slowly wandering error.
			if (T >= S.LastHealthCheckS)
			{
				S.LastHealthCheckS = T + 0.35f;
				S.AimNoise = FVector2f(S.Rng.FRandRange(-AimNoiseDeg, AimNoiseDeg), S.Rng.FRandRange(-AimNoiseDeg, AimNoiseDeg));
			}
			const FRotator Control = Self->GetController()->GetControlRotation();
			const FRotator Want = (Chest - Eye).Rotation();
			const float MaxTurn = TurnRateDegS * DeltaSeconds;
			const float DPitch = FRotator::NormalizeAxis(Want.Pitch - Control.Pitch) + (bSight ? S.AimNoise.X : 0.f);
			const float DYaw = FRotator::NormalizeAxis(Want.Yaw - Control.Yaw) + (bSight ? S.AimNoise.Y : 0.f);
			Out.LookDeltaDeg = FVector2f(FMath::Clamp(DPitch, -MaxTurn, MaxTurn), FMath::Clamp(DYaw, -MaxTurn, MaxTurn));
			const float AimError = FMath::Sqrt(DPitch * DPitch + DYaw * DYaw);

			uint32 Buttons = 0;
			if (bSight)
			{
				S.LastSeenS = T;
				S.NoSightSinceS = T;
				if (Distance < KnifeRangeCm)
				{
					// Up close: knife (from behind it becomes the finisher).
					Out.Pressed |= uint32(EVerseInputButton::Melee);
				}
				else if (AimError < FireConeDeg && T >= S.PauseUntilS)
				{
					if (S.BurstUntilS <= T)
					{
						S.BurstUntilS = T + S.Rng.FRandRange(0.35f, 0.9f);
					}
					Buttons |= uint32(EVerseInputButton::Fire) | uint32(EVerseInputButton::Ads);
					if (S.BurstUntilS - T < DeltaSeconds)
					{
						S.PauseUntilS = T + S.Rng.FRandRange(0.15f, 0.35f);
					}
				}
				else if (Distance > 900.0)
				{
					Buttons |= uint32(EVerseInputButton::Ads);
				}
				// Strafe while fighting.
				if (T >= S.NextStrafeFlipS)
				{
					S.StrafeSign = S.Rng.FRand() < 0.5f ? -1.f : 1.f;
					S.NextStrafeFlipS = T + S.Rng.FRandRange(0.6f, 1.6f);
				}
				Out.Move = FVector2f(Distance > 2500.0 ? 0.5f : 0.f, 0.7f * S.StrafeSign);
				// Under fire with health low: the Bulwark once per life.
				if (!S.bBulwarkUsed && T > 3.f && S.Rng.FRand() < 0.004f)
				{
					S.bBulwarkUsed = true;
					Out.Pressed |= uint32(EVerseInputButton::GadgetA);
				}
			}
			else
			{
				// Hunt along the nav path toward the opponent.
				if (T >= S.NextRepathS)
				{
					S.NextRepathS = T + RepathS;
					S.Path.Reset();
					S.PathIndex = 0;
					if (UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(Self->GetWorld()))
					{
						if (UNavigationPath* Path = Nav->FindPathToLocationSynchronously(Self->GetWorld(), Self->GetActorLocation(), Opponent->GetActorLocation(), Self))
						{
							S.Path = Path->PathPoints;
							S.PathIndex = S.Path.Num() > 1 ? 1 : 0;
						}
					}
				}
				FVector Goal = Opponent->GetActorLocation();
				while (S.Path.IsValidIndex(S.PathIndex) && FVector::Dist2D(S.Path[S.PathIndex], Self->GetActorLocation()) < 80.0)
				{
					++S.PathIndex;
				}
				if (S.Path.IsValidIndex(S.PathIndex))
				{
					Goal = S.Path[S.PathIndex];
				}
				const FVector To = (Goal - Self->GetActorLocation()).GetSafeNormal2D();
				const FRotator YawOnly(0.0, Control.Yaw, 0.0);
				const FVector Fwd = YawOnly.Vector();
				const FVector Right = FRotationMatrix(YawOnly).GetUnitAxis(EAxis::Y);
				Out.Move = FVector2f(float(FVector::DotProduct(To, Fwd)), float(FVector::DotProduct(To, Right)));
				// While hunting, look where the path goes unless the opponent is close.
				if (Distance > 1500.0 && S.Path.IsValidIndex(S.PathIndex))
				{
					const float PathYaw = FRotator::NormalizeAxis(To.Rotation().Yaw - Control.Yaw);
					Out.LookDeltaDeg.Y = FMath::Clamp(PathYaw, -MaxTurn, MaxTurn);
					Out.LookDeltaDeg.X = FMath::Clamp(-Control.Pitch, -MaxTurn, MaxTurn);
				}
				// Long without sight and close: a breach charge into the cover between (once per life).
				if (!S.bChargeUsed && T - S.NoSightSinceS > 8.f && Distance < 1500.0)
				{
					S.bChargeUsed = true;
					Out.Pressed |= uint32(EVerseInputButton::GadgetB);
				}
			}
			Out.Buttons = Buttons;
			return true;
		};
	}
}

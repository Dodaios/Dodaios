#include "Balance/VerseHarnessPerceptFeed.h"

#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"

void UVerseHarnessPerceptFeed::RegisterObserver(AController* Observer, const FVersePerceptionProfile& Profile)
{
	// The null perception has no error model, so the profile (hearing, acquisition, seed) is unused.
	if (Observer && !IsObserving(Observer))
	{
		Observers.Add(Observer);
	}
}

void UVerseHarnessPerceptFeed::UnregisterObserver(AController* Observer)
{
	Observers.RemoveAll([Observer](const TWeakObjectPtr<AController>& Weak)
						{ return !Weak.IsValid() || Weak.Get() == Observer; });
}

bool UVerseHarnessPerceptFeed::IsObserving(const AController* Observer) const
{
	return Observers.ContainsByPredicate([Observer](const TWeakObjectPtr<AController>& Weak)
										 { return Weak.Get() == Observer; });
}

FVerseSelfPercept UVerseHarnessPerceptFeed::SelfOf(const AController& Observer)
{
	FVerseSelfPercept Self;
	Self.ViewRotation = Observer.GetControlRotation();
	const APawn* Own = Observer.GetPawn();
	if (!Own)
	{
		Self.Phase = EVerseCombatPhase::Dead;
		return Self;
	}
	Self.Phase = EVerseCombatPhase::Alive;
	Self.Location = Own->GetActorLocation();
	Self.Velocity = Own->GetVelocity();
	FRotator EyeRotation;
	Own->GetActorEyesViewPoint(Self.EyeLocation, EyeRotation);
	if (const ACharacter* Character = Cast<ACharacter>(Own))
	{
		Self.Stance = Character->bIsCrouched ? EVerseStance::Crouch : EVerseStance::Stand;
	}
	return Self;
}

void UVerseHarnessPerceptFeed::Tick(UWorld* World)
{
	if (!World)
	{
		return;
	}
	const uint32 ServerTimeMs = uint32(FMath::Max(0.0, World->GetTimeSeconds()) * 1000.0);
	// Copy: a handler may unregister (a slot destroyed mid-bout).
	const TArray<TWeakObjectPtr<AController>> Snapshot = Observers;
	for (const TWeakObjectPtr<AController>& Weak : Snapshot)
	{
		AController* Observer = Weak.Get();
		if (!Observer)
		{
			continue;
		}
		FVersePerceptFrame Frame;
		Frame.ServerTimeMs = ServerTimeMs;
		Frame.Self = SelfOf(*Observer);
		OnPerceptFrame.Broadcast(Observer, Frame);
	}
	Observers.RemoveAll([](const TWeakObjectPtr<AController>& Weak)
						{ return !Weak.IsValid(); });
}

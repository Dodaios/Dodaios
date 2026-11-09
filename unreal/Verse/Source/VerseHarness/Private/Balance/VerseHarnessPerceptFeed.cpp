#include "Balance/VerseHarnessPerceptFeed.h"

#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "Perception/VersePerceptionService.h"

void UVerseHarnessPerceptFeed::BeginDestroy()
{
	Unbind();
	Super::BeginDestroy();
}

UVersePerceptionService* UVerseHarnessPerceptFeed::ServiceFor(const AController& Observer) const
{
	return bUseService ? UVersePerceptionService::Get(&Observer) : nullptr;
}

void UVerseHarnessPerceptFeed::Bind(UVersePerceptionService& Service)
{
	if (BoundService.Get() == &Service)
	{
		return;
	}
	Unbind();
	BoundService = &Service;
	ServiceHandle = Service.OnPerceptFrame.AddUObject(this, &UVerseHarnessPerceptFeed::HandleServiceFrame);
}

void UVerseHarnessPerceptFeed::Unbind()
{
	if (UVersePerceptionService* Service = BoundService.Get())
	{
		Service->OnPerceptFrame.Remove(ServiceHandle);
	}
	BoundService.Reset();
	ServiceHandle.Reset();
}

void UVerseHarnessPerceptFeed::RegisterObserver(AController* Observer, const FVersePerceptionProfile& Profile)
{
	if (!Observer || IsObserving(Observer))
	{
		return;
	}
	Observers.Add(Observer);
	// The real perception (bot.md 2, F6): the person model reads the frames the bots read, with
	// its own profile (hearing error, reaction, seed). Worlds without the service (fixtures) keep
	// the null frames of Tick.
	if (UVersePerceptionService* Service = ServiceFor(*Observer))
	{
		Bind(*Service);
		Service->RegisterObserver(Observer, Profile);
		Served.Add(Observer);
	}
}

void UVerseHarnessPerceptFeed::UnregisterObserver(AController* Observer)
{
	if (Observer)
	{
		if (UVersePerceptionService* Service = BoundService.Get())
		{
			if (Served.Contains(Observer))
			{
				Service->UnregisterObserver(Observer);
			}
		}
	}
	auto Gone = [Observer](const TWeakObjectPtr<AController>& Weak) { return !Weak.IsValid() || Weak.Get() == Observer; };
	Observers.RemoveAll(Gone);
	Served.RemoveAll(Gone);
}

bool UVerseHarnessPerceptFeed::IsObserving(const AController* Observer) const
{
	return Observers.ContainsByPredicate([Observer](const TWeakObjectPtr<AController>& Weak)
										 { return Weak.Get() == Observer; });
}

bool UVerseHarnessPerceptFeed::IsServed(const AController* Observer) const
{
	return Served.ContainsByPredicate([Observer](const TWeakObjectPtr<AController>& Weak) { return Weak.Get() == Observer; });
}

void UVerseHarnessPerceptFeed::HandleServiceFrame(AController* Observer, const FVersePerceptFrame& Frame)
{
	// The service serves every observer of the world (bot slots too); only ours are relayed.
	if (Observer && IsServed(Observer))
	{
		OnPerceptFrame.Broadcast(Observer, Frame);
	}
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
		if (!Observer || IsServed(Observer))
		{
			// Served observers get their frames from the service's own tick.
			continue;
		}
		FVersePerceptFrame Frame;
		Frame.ServerTimeMs = ServerTimeMs;
		Frame.Self = SelfOf(*Observer);
		OnPerceptFrame.Broadcast(Observer, Frame);
	}
	auto Gone = [](const TWeakObjectPtr<AController>& Weak) { return !Weak.IsValid(); };
	Observers.RemoveAll(Gone);
	Served.RemoveAll(Gone);
}

#include "VerseIntegrationSubsystem.h"

#include "Core/VerseUiSubsystem.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "Engine/World.h"

bool UVerseIntegrationSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && World->IsGameWorld() && Super::ShouldCreateSubsystem(Outer);
}

void UVerseIntegrationSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	BindKillCamFracture(InWorld);
}

bool UVerseIntegrationSubsystem::BindKillCamFracture(UWorld& World)
{
	UVerseUiSubsystem* Ui = World.GetSubsystem<UVerseUiSubsystem>();
	UVerseDebrisSubsystem* Debris = World.GetSubsystem<UVerseDebrisSubsystem>();
	if (!Ui || !Debris)
	{
		return false;
	}
	TWeakObjectPtr<UVerseDebrisSubsystem> WeakDebris(Debris);
	Ui->OnKillCamFracture = [WeakDebris](const FVerseFractureEvent& Event)
	{
		if (UVerseDebrisSubsystem* Target = WeakDebris.Get())
		{
			Target->ReplayFracture(Event);
		}
	};
	return true;
}

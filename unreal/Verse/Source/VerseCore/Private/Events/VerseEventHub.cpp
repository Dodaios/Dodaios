#include "Events/VerseEventHub.h"

#include "Engine/Engine.h"
#include "Engine/World.h"

UVerseEventHub* UVerseEventHub::Get(const UObject* WorldContextObject)
{
	if (!WorldContextObject || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseEventHub>() : nullptr;
}

void UVerseEventHub::Deinitialize()
{
	OnFire.Clear();
	OnHit.Clear();
	OnPenetration.Clear();
	OnDeath.Clear();
	OnFinisher.Clear();
	OnNoise.Clear();
	OnReload.Clear();
	OnGadget.Clear();
	OnFracture.Clear();
	OnArenaSwitch.Clear();
	OnSetEnded.Clear();
	OnStationUsed.Clear();
	Super::Deinitialize();
}

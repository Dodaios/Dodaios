#include "Weapons/VerseCombatEvents.h"

#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/GameStateBase.h"

namespace VerseCombatEvents
{
	float ServerTime(const UObject* WorldContext)
	{
		const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
		if (!World)
		{
			return 0.f;
		}
		if (const AGameStateBase* Gs = World->GetGameState())
		{
			return float(Gs->GetServerWorldTimeSeconds());
		}
		return World->GetTimeSeconds();
	}

	void RaiseNoise(const UObject* WorldContext, const FGameplayTag& Noise, int32 SourceId, const FVector& Location, float Loudness)
	{
		const UWorld* World = WorldContext ? WorldContext->GetWorld() : nullptr;
		if (!World || World->GetNetMode() == NM_Client)
		{
			return;
		}
		if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
		{
			FVerseNoiseEvent E;
			E.Noise = Noise;
			E.SourceId = SourceId;
			E.Location = Location;
			E.Loudness = Loudness;
			E.ServerTime = ServerTime(WorldContext);
			Hub->OnNoise.Broadcast(E);
		}
	}

	void RaiseFire(const UObject* WorldContext, const FVerseFireEvent& Event)
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
		{
			Hub->OnFire.Broadcast(Event);
		}
	}

	void RaisePenetration(const UObject* WorldContext, const FVersePenetrationEvent& Event)
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
		{
			Hub->OnPenetration.Broadcast(Event);
		}
	}

	void RaiseReload(const UObject* WorldContext, const FVerseReloadEvent& Event)
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
		{
			Hub->OnReload.Broadcast(Event);
		}
	}

	void RaiseGadget(const UObject* WorldContext, const FVerseGadgetEvent& Event)
	{
		if (UVerseEventHub* Hub = UVerseEventHub::Get(WorldContext))
		{
			Hub->OnGadget.Broadcast(Event);
		}
	}
}

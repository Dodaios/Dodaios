#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameplayTagContainer.h"

/**
 * Hub helpers of WP02.10 (combat-state.md 5.1). Every combat event is raised on the server's
 * UVerseEventHub; the per-event network transport lives on the component that owns the event
 * (weapon component: fire, cosmetic hit, penetration; combat state: victim hit copy, death;
 * inventory: reload; gadget actors: gadget events).
 */
namespace VerseCombatEvents
{
	/** Server time of the world: the game state's server clock when there is one, else world time. */
	VERSECOMBAT_API float ServerTime(const UObject* WorldContext);

	/** Raises a FVerseNoiseEvent on the server hub (bot hearing). No-op on clients. */
	VERSECOMBAT_API void RaiseNoise(const UObject* WorldContext, const FGameplayTag& Noise, int32 SourceId, const FVector& Location,
		float Loudness = 1.f);

	VERSECOMBAT_API void RaiseFire(const UObject* WorldContext, const FVerseFireEvent& Event);
	VERSECOMBAT_API void RaisePenetration(const UObject* WorldContext, const FVersePenetrationEvent& Event);
	VERSECOMBAT_API void RaiseReload(const UObject* WorldContext, const FVerseReloadEvent& Event);
	VERSECOMBAT_API void RaiseGadget(const UObject* WorldContext, const FVerseGadgetEvent& Event);
}

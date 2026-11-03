#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Inventory/VerseWeaponSlot.h"

#include "VerseInventoryComponent.generated.h"

class UVerseWeaponDefinition;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseInventoryReload, const FVerseReloadEvent&);

/**
 * Loadout slots (WP02.2, combat-state.md 2.1, 11.2): the per-slot weapon state as a fast array
 * replicated to the owner only, the active slot and the reloading flag replicated to all, equip and
 * holster timing, and the reload state machine (WP02.3) driven on the server. The opponent learns
 * of a reload only through the reload noise event.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseInventoryComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseInventoryComponent();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	static UVerseInventoryComponent* FindOn(const AActor* Actor);

	/** Owner only. */
	UPROPERTY(Replicated)
	FVerseWeaponSlotArray Slots;

	/** All. */
	UPROPERTY(Replicated)
	EVerseLoadoutSlot ActiveSlot = EVerseLoadoutSlot::Primary;

	/** All; animation only, carries no round count. */
	UPROPERTY(Replicated)
	bool bReloading = false;

	UFUNCTION(Server, Reliable)
	void ServerReload(uint16 ClientCounter);

	UFUNCTION(Server, Reliable)
	void ServerSwitchSlot(EVerseLoadoutSlot NewSlot);

	/** The owner-only transport of FVerseReloadEvent (combat-state.md 5.1). */
	UFUNCTION(Client, Reliable)
	void ClientReloadEvent(const FVerseReloadEvent& Event);

	/** Server: full magazines and reserve for every firearm slot, the primary drawn (respawn loadout). */
	void GiveLoadout(const TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*>& Weapons, float Now);

	/** Server: refills every slot (respawn). */
	void RefillAll();

	const FVerseWeaponSlotState* GetSlotState(EVerseLoadoutSlot Slot) const { return Slots.Find(Slot); }
	const FVerseWeaponSlotState* GetActiveState() const { return Slots.Find(ActiveSlot); }
	const UVerseWeaponDefinition* GetActiveWeapon() const;

	/** The active weapon finished equipping at Now. */
	bool IsReady(float Now) const { return Now >= ReadyAt; }
	float GetReadyAt() const { return ReadyAt; }

	/** Server: spends one round of the active weapon; false when it cannot fire. */
	bool ServerConsumeRound(float Now);

	/** Server: starts a reload of the active weapon; raises the event and the noise. */
	bool ServerStartReload(float Now);

	/** Server: cancels a running reload (before the commit the old magazine stays). */
	void ServerCancelReload(float Now);

	/** Server: switches slot, cancelling a reload; the new weapon is ready after holster + equip. */
	void ServerSwitch(EVerseLoadoutSlot NewSlot, float Now);

	/** Server: advances the reload of every slot to Now. TickComponent calls it; tests call it directly. */
	void ServerAdvance(float Now);

	/** Local reload events (server and owner), for UI and tests. */
	FOnVerseInventoryReload OnReloadEvent;

	float Now() const;

private:
	void MarkSlotDirty(FVerseWeaponSlotState& S);
	void SetReloading(bool bNew);
	void RaiseReload(const FVerseWeaponSlotState& S, bool bCancelled);

	/** Server time the active weapon is ready (equip done). */
	float ReadyAt = 0.f;
};

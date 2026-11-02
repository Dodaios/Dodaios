#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseBulwark.generated.h"

class UBoxComponent;
class UStaticMeshComponent;
class UVerseGadgetDefinition;

/**
 * The Bulwark (combat-state.md 2.3): a deployable energy barricade. Blocks pawns and the VerseBolt
 * channel and ignores VerseSight, so both sides see through it and nobody shoots through it. Bolts
 * stop at the field and their damage after all factors goes to its health. It ends at health 0, at
 * the end of its lifetime, on its owner's death or a breach detonation within 3 m. Server spawns it;
 * it replicates to all.
 */
UCLASS()
class VERSECOMBAT_API AVerseBulwark : public AActor
{
	GENERATED_BODY()

public:
	AVerseBulwark();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void Tick(float DeltaSeconds) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	/** Server: sets size, health, lifetime and owner; raises Deploy. Call right after spawning. */
	void InitBulwark(const UVerseGadgetDefinition& Def, AActor* InOwnerPawn, double Now);

	/** Server: a bolt's damage after all factors. Removes the field on the tick its health reaches 0. */
	void ApplyBoltDamage(float Damage, AActor* Instigator);

	/** Server: lifetime and hum. Tick calls it with the server time; tests call it directly. */
	void ServerAdvance(double Now);

	/** Server: removes the field with Destroyed or Expired. */
	void RemoveBulwark(EVerseGadgetEventKind Kind);

	bool IsActive() const { return bActive; }
	float GetHealth() const { return Health; }
	double GetExpireAt() const { return ExpireAt; }
	int32 GetOwnerId() const { return OwnerId; }
	AActor* GetOwnerPawn() const { return OwnerPawn.Get(); }

	/** Every active Bulwark whose centre is within RadiusCm of Location. */
	static TArray<AVerseBulwark*> FindWithin(const UWorld* World, const FVector& Location, double RadiusCm);

	UFUNCTION(NetMulticast, Unreliable)
	void MulticastGadgetEvent(const FVerseGadgetEvent& Event);

	UPROPERTY(VisibleAnywhere, Category = "Verse|Gadget")
	TObjectPtr<UBoxComponent> Field;

	/** Placeholder look: a thin amber slab (WP14 replaces it). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Gadget")
	TObjectPtr<UStaticMeshComponent> Look;

	/** Hum noise interval, s. */
	static constexpr double HumIntervalS = 1.0;

	/** Called on the server when the field goes (cooldown start in the gadget component). */
	TFunction<void(AVerseBulwark*)> OnRemoved;

private:
	void Raise(EVerseGadgetEventKind Kind);

	/** Clients raise the spawn event (Deploy) from replication: a multicast in the spawn frame has no open channel yet. */
	UFUNCTION()
	void OnRep_SpawnEvent();

	UPROPERTY(ReplicatedUsing = OnRep_SpawnEvent)
	FVerseGadgetEvent SpawnEvent;
	void OnOwnerDeath(const FVerseDeathEvent& Death);

	UPROPERTY(Replicated)
	float Health = 0.f;

	UPROPERTY(Replicated)
	float MaxHealth = 0.f;

	UPROPERTY()
	TObjectPtr<const UVerseGadgetDefinition> Definition;

	TWeakObjectPtr<AActor> OwnerPawn;
	int32 OwnerId = -1;
	double ExpireAt = 0.0;
	double NextHumAt = 0.0;
	bool bActive = false;
	FDelegateHandle DeathHandle;
};

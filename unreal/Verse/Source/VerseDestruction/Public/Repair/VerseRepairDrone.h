#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseRepairDrone.generated.h"

class UBoxComponent;
class UStaticMeshComponent;

/**
 * A repair drone (destruction.md 7). The server simulation owns its task and position; this
 * actor only shows it: replicated movement for the cosmetic flight, a bolt-channel hit box with
 * 30 HP that stops bolts, amber weld effects while repairing. It never blocks or harms pawns.
 */
UCLASS(Blueprintable)
class VERSEDESTRUCTION_API AVerseRepairDrone : public AActor
{
	GENERATED_BODY()

public:
	AVerseRepairDrone();

	/** Index of this drone in the manager's simulation. */
	UPROPERTY(Replicated, VisibleAnywhere, Category = "Repair")
	int32 DroneIndex = INDEX_NONE;

	/** EVerseDroneTask as a byte (Docked, Outbound, Repairing, Returning, Down). */
	UPROPERTY(ReplicatedUsing = OnRep_Task, VisibleAnywhere, Category = "Repair")
	uint8 Task = 0;

	/** Bumped each time the drone is shot down; clients drop the old body as debris. */
	UPROPERTY(ReplicatedUsing = OnRep_Generation, VisibleAnywhere, Category = "Repair")
	uint32 Generation = 0;

	UPROPERTY(Replicated, VisibleAnywhere, Category = "Repair")
	float Hp = 30.f;

	UBoxComponent* GetHitBox() const { return HitBox; }

	/** Bolts and melee reach the manager's drone damage through the engine damage path. */
	virtual float TakeDamage(float DamageAmount, const FDamageEvent& DamageEvent, AController* EventInstigator, AActor* DamageCauser) override;

	/** Server: mirror the simulation state. */
	void SyncFromSim(const FVector& Location, uint8 InTask, uint32 InGeneration, float InHp);

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	/** Client cosmetics hooks (weld sparks, falling body) for the Blueprint look. */
	UFUNCTION(BlueprintImplementableEvent, Category = "Repair")
	void OnTaskChanged(uint8 NewTask);

	UFUNCTION(BlueprintImplementableEvent, Category = "Repair")
	void OnShotDown();

protected:
	UFUNCTION()
	void OnRep_Task();

	UFUNCTION()
	void OnRep_Generation();

	UPROPERTY(VisibleAnywhere, Category = "Repair")
	TObjectPtr<UBoxComponent> HitBox;

	UPROPERTY(VisibleAnywhere, Category = "Repair")
	TObjectPtr<UStaticMeshComponent> Body;
};

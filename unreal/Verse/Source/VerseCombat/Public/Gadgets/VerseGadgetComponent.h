#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseGadgetComponent.generated.h"

class AVerseBreachCharge;
class AVerseBulwark;
class IVersePenetrationQuery;
class IVersePieceDamage;
class UVerseGadgetDefinition;

/** Where a gadget goes, as placement found it. */
struct FVerseGadgetPlacement
{
	bool bValid = false;
	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	/** Breach charge: the piece it sticks to and the surface normal. */
	uint16 PieceIndex = 0;
	FVector Normal = FVector::UpVector;
};

/**
 * The two start gadgets of a pawn (WP02.12, 2.13, combat-state.md 2.3): charges per life, cooldown
 * after the Bulwark is gone, the interruptible use time, placement and spawning. Server only; the
 * GAS abilities UVerseGA_Bulwark and UVerseGA_BreachCharge call into it, and the owning client
 * predicts only the deploy or plant animation.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseGadgetComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseGadgetComponent();

	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

	static UVerseGadgetComponent* FindOn(const AActor* Actor);

	/** GadgetA. */
	UPROPERTY(EditAnywhere, Category = "Verse|Gadget")
	TObjectPtr<const UVerseGadgetDefinition> Bulwark;

	/** GadgetB. */
	UPROPERTY(EditAnywhere, Category = "Verse|Gadget")
	TObjectPtr<const UVerseGadgetDefinition> BreachCharge;

	/** Server: charges back to full (respawn). */
	void ResetForLife();

	/** Server: starts deploying (GadgetA) or planting (GadgetB). False when out of charges, cooling down or busy. */
	bool ServerBeginUse(EVerseLoadoutSlot Slot, float Now);

	/** Server: completes a use whose time is over. TickComponent calls it; tests call it directly. */
	void ServerAdvance(float Now);

	/** Server: taking damage interrupts a deploy or plant (the charge is kept). */
	void Interrupt();

	bool IsUsing() const { return bUsing; }
	int32 GetChargesLeft(EVerseLoadoutSlot Slot) const;
	float GetCooldownEndsAt() const { return BulwarkCooldownEndsAt; }
	AVerseBulwark* GetActiveBulwark() const { return ActiveBulwark.Get(); }
	int32 NumPlantedCharges() const;

	/** Placement overrides (tests); unset uses the eye-based placement of 2.3. */
	TFunction<FVerseGadgetPlacement(EVerseLoadoutSlot)> PlacementOverride;

	void SetPenetrationQuery(const IVersePenetrationQuery* Query) { PenetrationQuery = Query; }
	void SetPieceDamage(IVersePieceDamage* Damage) { PieceDamage = Damage; }

	/** Eye-based placement (2.3): Bulwark on the floor in front, breach charge on a breachable piece. */
	FVerseGadgetPlacement FindPlacement(EVerseLoadoutSlot Slot) const;

private:
	const UVerseGadgetDefinition* DefinitionFor(EVerseLoadoutSlot Slot) const;
	void Complete(float Now);
	void OnHubHit(const FVerseHitEvent& Hit);

	int32 BulwarkCharges = 0;
	int32 BreachCharges = 0;
	float BulwarkCooldownEndsAt = 0.f;
	bool bUsing = false;
	EVerseLoadoutSlot UsingSlot = EVerseLoadoutSlot::GadgetA;
	float UseEndsAt = 0.f;
	TWeakObjectPtr<AVerseBulwark> ActiveBulwark;
	TArray<TWeakObjectPtr<AVerseBreachCharge>> Planted;
	const IVersePenetrationQuery* PenetrationQuery = nullptr;
	IVersePieceDamage* PieceDamage = nullptr;
	FDelegateHandle HitHandle;
};

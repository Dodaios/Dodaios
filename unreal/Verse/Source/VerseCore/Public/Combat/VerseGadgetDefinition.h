#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseGadgetDefinition.generated.h"

/**
 * One gadget (combat-state.md 2.3): DA_Gadget_Bulwark, DA_Gadget_BreachCharge; text surface
 * unreal/Verse/Data/weapons/gadgets.json. Fields frozen; the defaults are the Bulwark start values.
 */
UCLASS(BlueprintType)
class VERSECORE_API UVerseGadgetDefinition : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** bulwark, breach_charge */
	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	FName GadgetId;

	UPROPERTY(EditDefaultsOnly, Category = "Identity")
	FText DisplayName;

	/** Per life. */
	UPROPERTY(EditDefaultsOnly, Category = "Use")
	int32 Charges = 1;

	/** After the actor is gone. */
	UPROPERTY(EditDefaultsOnly, Category = "Use", meta = (Units = "s"))
	float Cooldown = 20.f;

	/** Deploy or plant, interruptible by taking damage. */
	UPROPERTY(EditDefaultsOnly, Category = "Use", meta = (Units = "s"))
	float UseTime = 0.6f;

	/** Bulwark lifetime, or the breach charge fuse after the plant completes. */
	UPROPERTY(EditDefaultsOnly, Category = "Use", meta = (Units = "s"))
	float Lifetime = 25.f;

	/** From the eye. */
	UPROPERTY(EditDefaultsOnly, Category = "Use", meta = (Units = "m"))
	float PlaceRange = 1.5f;

	/** hp; unused by the breach charge (it cannot be shot). */
	UPROPERTY(EditDefaultsOnly, Category = "Body")
	float MaxHealth = 400.f;

	/** w x h x d */
	UPROPERTY(EditDefaultsOnly, Category = "Body", meta = (Units = "m"))
	FVector3f Size = FVector3f(1.8f, 1.4f, 0.1f);

	/** hp at the centre, linear falloff to 0 at PawnRadius. */
	UPROPERTY(EditDefaultsOnly, Category = "Damage")
	float PawnDamage = 0.f;

	UPROPERTY(EditDefaultsOnly, Category = "Damage", meta = (Units = "m"))
	float PawnRadius = 0.f;

	/** destruction.md 3.2 */
	UPROPERTY(EditDefaultsOnly, Category = "Damage", meta = (Units = "cm"))
	float PieceBreachRadius = 0.f;

	/** The owner takes the same damage. */
	UPROPERTY(EditDefaultsOnly, Category = "Damage")
	bool bSelfDamage = false;

	/** The falloff of 2.3: PawnDamage x (1 - r / PawnRadius), 0 at and beyond PawnRadius. */
	float PawnDamageAt(float DistanceM) const
	{
		if (PawnRadius <= 0.f || DistanceM >= PawnRadius)
		{
			return 0.f;
		}
		return PawnDamage * (1.f - FMath::Max(0.f, DistanceM) / PawnRadius);
	}
};

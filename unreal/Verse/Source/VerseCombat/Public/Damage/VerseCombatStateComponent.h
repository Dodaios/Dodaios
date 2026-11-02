#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseCombatStateComponent.generated.h"

/**
 * Combat state on the pawn (contracts/combat-state.md 2.1, 11.2). AVerseCharacter is a
 * VerseMovement class, so the combat phase and spawn protection live here; the primary
 * module's default pawn adds this component. Fields only: WP02 adds the behaviour.
 * Replicated to all with the push model.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseCombatStateComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseCombatStateComponent();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	EVerseCombatPhase Phase = EVerseCombatPhase::Alive;

	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	bool bSpawnProtected = false;

	/** Server time at which spawn protection ends (combat-state.md 9.3). */
	UPROPERTY(Replicated, VisibleInstanceOnly, BlueprintReadOnly, Category = "Verse|Combat")
	float SpawnProtectedUntil = 0.f;
};

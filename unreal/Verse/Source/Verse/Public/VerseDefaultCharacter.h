#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Character.h"

#include "VerseDefaultCharacter.generated.h"

class UVerseCombatStateComponent;

/**
 * Default pawn. Carries UVerseCombatStateComponent (contracts/combat-state.md 2.1).
 * Integration (orchestration.md 2.1) re-parents it onto AVerseCharacter once
 * VerseMovement ships that class.
 */
UCLASS()
class VERSE_API AVerseDefaultCharacter : public ACharacter
{
	GENERATED_BODY()

public:
	AVerseDefaultCharacter();

	UVerseCombatStateComponent* GetCombatState() const { return CombatState; }

private:
	UPROPERTY(VisibleAnywhere, Category = "Verse|Combat")
	TObjectPtr<UVerseCombatStateComponent> CombatState;
};

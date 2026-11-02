#include "VerseDefaultCharacter.h"

#include "Damage/VerseCombatStateComponent.h"

AVerseDefaultCharacter::AVerseDefaultCharacter()
{
	CombatState = CreateDefaultSubobject<UVerseCombatStateComponent>(TEXT("CombatState"));
}

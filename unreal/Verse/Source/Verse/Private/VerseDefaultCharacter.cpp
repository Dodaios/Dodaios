#include "VerseDefaultCharacter.h"

#include "AbilitySystemComponent.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Melee/VerseMeleeComponent.h"
#include "VerseCombatDriverComponent.h"
#include "VerseIntegrationSubsystem.h"
#include "Weapons/VerseWeaponComponent.h"

AVerseDefaultCharacter::AVerseDefaultCharacter(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
{
	Abilities = CreateDefaultSubobject<UAbilitySystemComponent>(TEXT("Abilities"));
	Abilities->SetIsReplicated(true);
	// Gameplay effects replicate to the owner only; health is owner-only anyway (2.1).
	Abilities->SetReplicationMode(EGameplayEffectReplicationMode::Mixed);
	// An attribute set that is a default subobject of the owner is picked up by the ability
	// system component when it initializes.
	HealthSet = CreateDefaultSubobject<UVerseHealthSet>(TEXT("Health"));

	CombatState = CreateDefaultSubobject<UVerseCombatStateComponent>(TEXT("CombatState"));
	Inventory = CreateDefaultSubobject<UVerseInventoryComponent>(TEXT("Inventory"));
	Weapon = CreateDefaultSubobject<UVerseWeaponComponent>(TEXT("Weapon"));
	Melee = CreateDefaultSubobject<UVerseMeleeComponent>(TEXT("Melee"));
	Gadgets = CreateDefaultSubobject<UVerseGadgetComponent>(TEXT("Gadgets"));
	CombatDriver = CreateDefaultSubobject<UVerseCombatDriverComponent>(TEXT("CombatDriver"));
}

UAbilitySystemComponent* AVerseDefaultCharacter::GetAbilitySystemComponent() const
{
	return Abilities;
}

void AVerseDefaultCharacter::InitAbilityActorInfo()
{
	if (Abilities)
	{
		Abilities->InitAbilityActorInfo(this, this);
	}
}

void AVerseDefaultCharacter::PossessedBy(AController* NewController)
{
	Super::PossessedBy(NewController);
	InitAbilityActorInfo();
}

void AVerseDefaultCharacter::OnRep_Controller()
{
	Super::OnRep_Controller();
	InitAbilityActorInfo();
}

void AVerseDefaultCharacter::BeginPlay()
{
	Super::BeginPlay();
	// Unpossessed pawns (QA bodies, stand-ins) take damage through the set as well.
	InitAbilityActorInfo();
	// Lag compensation hit bodies and gadget seams (server).
	UVerseIntegrationSubsystem::BindPawn(*this);
}

void AVerseDefaultCharacter::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	UVerseIntegrationSubsystem::UnbindPawn(*this);
	Super::EndPlay(EndPlayReason);
}

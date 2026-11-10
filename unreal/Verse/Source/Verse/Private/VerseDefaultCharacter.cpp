#include "VerseDefaultCharacter.h"

#include "AbilitySystemComponent.h"
#include "Components/InputComponent.h"
#include "InputCoreTypes.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Melee/VerseMeleeComponent.h"
#include "VerseCombatDriverComponent.h"
#include "VerseIntegrationSubsystem.h"
#include "VerseViewmodelComponent.h"
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
	Viewmodel = CreateDefaultSubobject<UVerseViewmodelComponent>(TEXT("Viewmodel"));
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

void AVerseDefaultCharacter::SetupPlayerInputComponent(UInputComponent* PlayerInputComponent)
{
	// Movement keys come from VerseMovement; the combat keys of Data/ui/keys.json join the same
	// person frame here, because Movement never includes Combat (decision C8).
	Super::SetupPlayerInputComponent(PlayerInputComponent);
	if (!PlayerInputComponent)
	{
		return;
	}
	FVerseInputFrameBuilder* Builder = &GetPersonInput();
	auto Hold = [PlayerInputComponent, Builder](const FKey& Key, EVerseInputButton Button)
	{
		for (const EInputEvent Event : {IE_Pressed, IE_Released})
		{
			FInputKeyBinding Binding(FInputChord(Key, false, false, false, false), Event);
			Binding.bConsumeInput = false;
			const bool bDown = Event == IE_Pressed;
			Binding.KeyDelegate.GetDelegateForManualSet().BindLambda([Builder, Button, bDown]() { Builder->SetButton(Button, bDown); });
			PlayerInputComponent->KeyBindings.Emplace(MoveTemp(Binding));
		}
	};
	Hold(EKeys::LeftMouseButton, EVerseInputButton::Fire);
	Hold(EKeys::Gamepad_RightTrigger, EVerseInputButton::Fire);
	Hold(EKeys::RightMouseButton, EVerseInputButton::Ads);
	Hold(EKeys::Gamepad_LeftTrigger, EVerseInputButton::Ads);
	Hold(EKeys::R, EVerseInputButton::Reload);
	Hold(EKeys::Gamepad_FaceButton_Left, EVerseInputButton::Reload);
	Hold(EKeys::V, EVerseInputButton::Melee);
	Hold(EKeys::Gamepad_RightShoulder, EVerseInputButton::Melee);
	Hold(EKeys::G, EVerseInputButton::GadgetA);
	Hold(EKeys::Gamepad_DPad_Left, EVerseInputButton::GadgetA);
	Hold(EKeys::T, EVerseInputButton::GadgetB);
	Hold(EKeys::Gamepad_DPad_Right, EVerseInputButton::GadgetB);
	Hold(EKeys::One, EVerseInputButton::SlotPrimary);
	Hold(EKeys::Two, EVerseInputButton::SlotSecondary);
	Hold(EKeys::Three, EVerseInputButton::SlotMelee);
	Hold(EKeys::Gamepad_FaceButton_Top, EVerseInputButton::SlotSecondary);
	Hold(EKeys::F, EVerseInputButton::Interact);
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

#include "VerseCombatDriverComponent.h"

#include "Controller/VerseBotController.h"
#include "Damage/VerseCombatStateComponent.h"
#include "GameFramework/Controller.h"
#include "GameFramework/Pawn.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Melee/VerseMeleeComponent.h"
#include "Movement/VerseMovementQuery.h"
#include "VerseCharacter.h"
#include "Weapons/VerseCombatEvents.h"
#include "Weapons/VerseWeaponComponent.h"

namespace VerseCombatDriverPrivate
{
	/** Seconds between two automatic reload requests while the trigger is held on an empty magazine. */
	constexpr float AutoReloadRetryS = 0.75f;

	bool Bit(uint32 Bits, EVerseInputButton Button)
	{
		return (Bits & uint32(Button)) != 0;
	}
}

UVerseCombatDriverComponent::UVerseCombatDriverComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = true;
	// After the pawn consumed this tick's frame (AVerseCharacter::Tick) and moved.
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
	SetIsReplicatedByDefault(true);
}

UVerseCombatDriverComponent* UVerseCombatDriverComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseCombatDriverComponent>() : nullptr;
}

void UVerseCombatDriverComponent::BeginPlay()
{
	Super::BeginPlay();
	if (AActor* Owner = GetOwner())
	{
		AddTickPrerequisiteActor(Owner);
	}
}

void UVerseCombatDriverComponent::SetExternalFrame(const FVerseInputFrame& Frame)
{
	External = Frame;
	bHasExternal = true;
	bExternalFresh = true;
}

bool UVerseCombatDriverComponent::ReadFrame(FVerseInputFrame& OutFrame)
{
	APawn* Pawn = Cast<APawn>(GetOwner());
	AController* Controller = Pawn ? Pawn->GetController() : nullptr;
	if (!Controller)
	{
		return false;
	}
	if (Controller->IsPlayerController())
	{
		if (!Pawn->IsLocallyControlled())
		{
			return false;
		}
		const AVerseCharacter* Character = Cast<AVerseCharacter>(Pawn);
		if (!Character)
		{
			return false;
		}
		OutFrame = Character->GetLastAppliedFrame();
		return true;
	}
	if (!Pawn->HasAuthority())
	{
		return false;
	}
	if (const AVerseBotController* Bot = Cast<AVerseBotController>(Controller))
	{
		OutFrame = Bot->GetLastInputFrame();
		// A bot frame holds between thinks; only edges count as presses (computed in Drive).
		OutFrame.Pressed = 0;
		return true;
	}
	if (bHasExternal)
	{
		OutFrame = External;
		if (!bExternalFresh)
		{
			OutFrame.Pressed = 0;
		}
		bExternalFresh = false;
		return true;
	}
	return false;
}

void UVerseCombatDriverComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	FVerseInputFrame Frame;
	if (ReadFrame(Frame))
	{
		Drive(Frame, DeltaTime);
	}
}

void UVerseCombatDriverComponent::SwitchSlot(EVerseLoadoutSlot Slot)
{
	UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(GetOwner());
	if (!Inventory || Inventory->ActiveSlot == Slot)
	{
		return;
	}
	if (Slot != EVerseLoadoutSlot::Melee && !Inventory->GetSlotState(Slot))
	{
		return;
	}
	if (GetOwner()->HasAuthority())
	{
		Inventory->ServerSwitch(Slot, Inventory->Now());
	}
	else
	{
		Inventory->ServerSwitchSlot(Slot);
	}
}

void UVerseCombatDriverComponent::UseGadget(EVerseLoadoutSlot Slot)
{
	if (GetOwner()->HasAuthority())
	{
		ServerUseGadget_Implementation(Slot);
	}
	else
	{
		ServerUseGadget(Slot);
	}
}

void UVerseCombatDriverComponent::ServerUseGadget_Implementation(EVerseLoadoutSlot Slot)
{
	if (Slot != EVerseLoadoutSlot::GadgetA && Slot != EVerseLoadoutSlot::GadgetB)
	{
		return;
	}
	if (UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(GetOwner()))
	{
		Gadgets->ServerBeginUse(Slot, VerseCombatEvents::ServerTime(GetOwner()));
	}
}

void UVerseCombatDriverComponent::Drive(const FVerseInputFrame& Frame, float DeltaSeconds)
{
	using namespace VerseCombatDriverPrivate;
	APawn* Pawn = Cast<APawn>(GetOwner());
	AController* Controller = Pawn ? Pawn->GetController() : nullptr;
	if (!Pawn || !Controller)
	{
		return;
	}
	const uint32 Pressed = Frame.Pressed | (Frame.Buttons & ~PrevButtons);
	PrevButtons = Frame.Buttons;

	const UVerseCombatStateComponent* Combat = Pawn->FindComponentByClass<UVerseCombatStateComponent>();
	if (Combat && !Combat->IsAlive())
	{
		return;
	}
	UVerseMeleeComponent* Melee = Pawn->FindComponentByClass<UVerseMeleeComponent>();
	if (Melee && Melee->IsInFinisher())
	{
		return;
	}
	UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(Pawn);
	UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Pawn);
	const UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Pawn);

	// Slots (1, 2, 3).
	if (Bit(Pressed, EVerseInputButton::SlotPrimary))
	{
		SwitchSlot(EVerseLoadoutSlot::Primary);
	}
	else if (Bit(Pressed, EVerseInputButton::SlotSecondary))
	{
		SwitchSlot(EVerseLoadoutSlot::Secondary);
	}
	else if (Bit(Pressed, EVerseInputButton::SlotMelee))
	{
		SwitchSlot(EVerseLoadoutSlot::Melee);
	}
	const bool bKnifeSlot = Inventory && Inventory->ActiveSlot == EVerseLoadoutSlot::Melee;

	// Gadgets (Bulwark, breach charge).
	if (Bit(Pressed, EVerseInputButton::GadgetA))
	{
		UseGadget(EVerseLoadoutSlot::GadgetA);
	}
	else if (Bit(Pressed, EVerseInputButton::GadgetB))
	{
		UseGadget(EVerseLoadoutSlot::GadgetB);
	}
	const bool bUsingGadget = Gadgets && Gadgets->IsUsing();

	// Knife: the quick melee key, or fire with the knife drawn. A press from behind is the finisher (7).
	if (Melee && !bUsingGadget
		&& (Bit(Pressed, EVerseInputButton::Melee) || (bKnifeSlot && Bit(Pressed, EVerseInputButton::Fire))))
	{
		Melee->PressMelee(bKnifeSlot);
	}

	if (!Weapon || !Inventory)
	{
		return;
	}
	const float Now = VerseCombatEvents::ServerTime(Pawn);
	const FVerseWeaponSlotState* Active = Inventory->GetActiveState();
	const bool bFirearm = !bKnifeSlot && Active && Active->Definition;

	if (bFirearm && Bit(Pressed, EVerseInputButton::Reload))
	{
		Inventory->ServerReload(0);
	}
	const bool bTrigger = bFirearm && !bUsingGadget && Frame.IsHeld(EVerseInputButton::Fire);
	// Empty magazine with the trigger held: reload once (combat-state.md 2.2, the dry trigger reloads).
	if (bTrigger && Active->Definition && FVerseMagazine::RoundsReady(*Active, *Active->Definition) == 0
		&& !FVerseMagazine::IsReloading(*Active) && Active->Reserve > 0 && Now - LastAutoReloadAt > AutoReloadRetryS)
	{
		LastAutoReloadAt = Now;
		Inventory->ServerReload(0);
	}

	Weapon->StepAds(bFirearm && Frame.IsHeld(EVerseInputButton::Ads), DeltaSeconds);

	FVerseFireContext Ctx;
	Ctx.Now = Now;
	Ctx.Dt = FMath::Max(DeltaSeconds, 1.e-4f);
	Ctx.bTriggerDown = bTrigger;
	if (UActorComponent* MovementComponent = Pawn->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
	{
		if (const IVerseMovementQuery* Movement = Cast<IVerseMovementQuery>(MovementComponent))
		{
			Ctx.Stance = Movement->GetStance();
			Ctx.bAirborne = Movement->IsAirborne();
			Ctx.bFiringBlocked = Movement->BlocksFiring();
		}
	}
	Ctx.HorizontalSpeedMps = float(Pawn->GetVelocity().Size2D() / 100.0);
	FRotator EyeRotation;
	Pawn->GetActorEyesViewPoint(Ctx.Eye, EyeRotation);
	Ctx.Control = Controller->GetControlRotation();

	TArray<FVerseShotOut> Shots;
	const FRotator Kick = Weapon->StepFire(Ctx, &Shots);
	ShotsFired += Shots.Num();
	if (!Kick.IsNearlyZero())
	{
		FRotator Control = Controller->GetControlRotation();
		Control.Pitch = FMath::ClampAngle(FRotator::NormalizeAxis(Control.Pitch + Kick.Pitch), -85.f, 85.f);
		Control.Yaw = FRotator::NormalizeAxis(Control.Yaw + Kick.Yaw);
		Controller->SetControlRotation(Control);
	}
}

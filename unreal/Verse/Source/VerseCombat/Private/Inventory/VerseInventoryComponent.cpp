#include "Inventory/VerseInventoryComponent.h"

#include "Combat/VerseWeaponDefinition.h"
#include "Damage/VerseDamageService.h"
#include "GameFramework/Actor.h"
#include "Net/Core/PushModel/PushModel.h"
#include "Net/UnrealNetwork.h"
#include "VerseGameplayTags.h"
#include "Weapons/VerseCombatEvents.h"

UVerseInventoryComponent::UVerseInventoryComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = true;
	SetIsReplicatedByDefault(true);
}

void UVerseInventoryComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);

	FDoRepLifetimeParams OwnerOnly;
	OwnerOnly.bIsPushBased = true;
	OwnerOnly.Condition = COND_OwnerOnly;
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseInventoryComponent, Slots, OwnerOnly);

	FDoRepLifetimeParams All;
	All.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseInventoryComponent, ActiveSlot, All);
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseInventoryComponent, bReloading, All);
}

UVerseInventoryComponent* UVerseInventoryComponent::FindOn(const AActor* Actor)
{
	return Actor ? Actor->FindComponentByClass<UVerseInventoryComponent>() : nullptr;
}

float UVerseInventoryComponent::Now() const
{
	return VerseCombatEvents::ServerTime(this);
}

const UVerseWeaponDefinition* UVerseInventoryComponent::GetActiveWeapon() const
{
	const FVerseWeaponSlotState* S = GetActiveState();
	return S ? S->Definition.Get() : nullptr;
}

void UVerseInventoryComponent::MarkSlotDirty(FVerseWeaponSlotState& S)
{
	Slots.MarkItemDirty(S);
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, Slots, this);
}

void UVerseInventoryComponent::SetReloading(bool bNew)
{
	if (bReloading != bNew)
	{
		bReloading = bNew;
		MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, bReloading, this);
	}
}

void UVerseInventoryComponent::GiveLoadout(const TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*>& Weapons, float InNow)
{
	Slots.Items.Reset();
	for (const TPair<EVerseLoadoutSlot, const UVerseWeaponDefinition*>& Pair : Weapons)
	{
		if (!Pair.Value)
		{
			continue;
		}
		FVerseWeaponSlotState& S = Slots.Items.AddDefaulted_GetRef();
		S.Slot = Pair.Key;
		S.Definition = Pair.Value;
		FVerseMagazine::InitFull(S, *Pair.Value);
	}
	Slots.MarkArrayDirty();
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, Slots, this);
	ActiveSlot = EVerseLoadoutSlot::Primary;
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, ActiveSlot, this);
	SetReloading(false);
	ReadyAt = InNow;
}

void UVerseInventoryComponent::RefillAll()
{
	for (FVerseWeaponSlotState& S : Slots.Items)
	{
		if (const UVerseWeaponDefinition* W = S.Definition.Get())
		{
			FVerseMagazine::InitFull(S, *W);
			Slots.MarkItemDirty(S);
		}
	}
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, Slots, this);
	SetReloading(false);
}

bool UVerseInventoryComponent::ServerConsumeRound(float InNow)
{
	FVerseWeaponSlotState* S = Slots.Find(ActiveSlot);
	const UVerseWeaponDefinition* W = S ? S->Definition.Get() : nullptr;
	if (!W || !IsReady(InNow) || !FVerseMagazine::ConsumeRound(*S, *W))
	{
		return false;
	}
	MarkSlotDirty(*S);
	return true;
}

void UVerseInventoryComponent::RaiseReload(const FVerseWeaponSlotState& S, bool bCancelled)
{
	const UVerseWeaponDefinition* W = S.Definition.Get();
	FVerseReloadEvent E;
	E.PlayerId = VerseCombatIds::IdOf(GetOwner());
	E.WeaponId = W ? W->WeaponId : NAME_None;
	E.bTactical = S.Reload != EVerseReloadPhase::Empty;
	E.StartServerTime = S.ReloadStartedAt;
	E.EndServerTime = S.ReloadEndsAt;
	E.bCancelled = bCancelled;

	VerseCombatEvents::RaiseReload(this, E);
	OnReloadEvent.Broadcast(E);
	ClientReloadEvent(E);
	if (!bCancelled)
	{
		const AActor* Owner = GetOwner();
		VerseCombatEvents::RaiseNoise(this, VerseTags::Noise_Reload, E.PlayerId, Owner ? Owner->GetActorLocation() : FVector::ZeroVector);
	}
}

bool UVerseInventoryComponent::ServerStartReload(float InNow)
{
	FVerseWeaponSlotState* S = Slots.Find(ActiveSlot);
	const UVerseWeaponDefinition* W = S ? S->Definition.Get() : nullptr;
	if (!W || !IsReady(InNow) || !FVerseMagazine::StartReload(*S, *W, InNow))
	{
		return false;
	}
	MarkSlotDirty(*S);
	SetReloading(true);
	RaiseReload(*S, false);
	return true;
}

void UVerseInventoryComponent::ServerCancelReload(float InNow)
{
	for (FVerseWeaponSlotState& S : Slots.Items)
	{
		if (FVerseMagazine::IsReloading(S))
		{
			const FVerseWeaponSlotState Before = S;
			FVerseMagazine::Cancel(S);
			MarkSlotDirty(S);
			FVerseWeaponSlotState Report = Before;
			Report.ReloadEndsAt = InNow;
			RaiseReload(Report, true);
		}
	}
	SetReloading(false);
}

void UVerseInventoryComponent::ServerSwitch(EVerseLoadoutSlot NewSlot, float InNow)
{
	if (NewSlot == ActiveSlot)
	{
		return;
	}
	ServerCancelReload(InNow);
	const UVerseWeaponDefinition* Old = GetActiveWeapon();
	ActiveSlot = NewSlot;
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseInventoryComponent, ActiveSlot, this);
	const UVerseWeaponDefinition* New = GetActiveWeapon();
	ReadyAt = InNow + (Old ? Old->HolsterTime : 0.f) + (New ? New->EquipTime : 0.f);
}

void UVerseInventoryComponent::ServerAdvance(float InNow)
{
	bool bAnyReloading = false;
	for (FVerseWeaponSlotState& S : Slots.Items)
	{
		const UVerseWeaponDefinition* W = S.Definition.Get();
		if (!W)
		{
			continue;
		}
		const EVerseMagazineChange Change = FVerseMagazine::Tick(S, *W, InNow);
		if (Change != EVerseMagazineChange::None)
		{
			MarkSlotDirty(S);
		}
		bAnyReloading |= FVerseMagazine::IsReloading(S);
	}
	SetReloading(bAnyReloading);
}

void UVerseInventoryComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (GetOwner() && GetOwner()->HasAuthority())
	{
		ServerAdvance(Now());
	}
}

void UVerseInventoryComponent::ServerReload_Implementation(uint16 /*ClientCounter*/)
{
	ServerStartReload(Now());
}

void UVerseInventoryComponent::ServerSwitchSlot_Implementation(EVerseLoadoutSlot NewSlot)
{
	ServerSwitch(NewSlot, Now());
}

void UVerseInventoryComponent::ClientReloadEvent_Implementation(const FVerseReloadEvent& Event)
{
	const AActor* Owner = GetOwner();
	if (Owner && !Owner->HasAuthority())
	{
		VerseCombatEvents::RaiseReload(this, Event);
		OnReloadEvent.Broadcast(Event);
	}
}

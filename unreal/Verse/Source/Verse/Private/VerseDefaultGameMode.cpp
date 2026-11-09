#include "VerseDefaultGameMode.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Engine/DataAsset.h"
#include "Engine/World.h"
#include "GameFramework/Pawn.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Rules/VersePlayerState.h"
#include "VerseDefaultCharacter.h"
#include "VerseDefaultPlayerController.h"
#include "Weapons/VerseWeaponRegistry.h"

namespace VerseDefaultGameModePrivate
{
	/** Start loadout of combat-state.md 2.2 (ids as in Data/weapons). */
	const FName PrimaryId(TEXT("graveline"));
	const FName SecondaryId(TEXT("tallow"));
	const FName GadgetAId(TEXT("bulwark"));
	const FName GadgetBId(TEXT("breach_charge"));
}

AVerseDefaultGameMode::AVerseDefaultGameMode()
{
	DefaultPawnClass = AVerseDefaultCharacter::StaticClass();
	PlayerControllerClass = AVerseDefaultPlayerController::StaticClass();
	// PlayerStateClass stays AVersePlayerState (AVerseGameMode).
}

void AVerseDefaultGameMode::SetPlayerDefaults(APawn* PlayerPawn)
{
	Super::SetPlayerDefaults(PlayerPawn);
	if (PlayerPawn && PlayerPawn->HasAuthority())
	{
		GiveLoadout(PlayerPawn);
	}
}

int32 AVerseDefaultGameMode::GiveLoadout(APawn* Pawn)
{
	using namespace VerseDefaultGameModePrivate;
	if (!Pawn)
	{
		return 0;
	}
	TMap<EVerseLoadoutSlot, const UPrimaryDataAsset*> Assets;
	GetLoadout(Pawn->GetPlayerState<AVersePlayerState>(), Assets);
	auto WeaponFor = [&Assets](EVerseLoadoutSlot Slot, FName FallbackId) -> const UVerseWeaponDefinition*
	{
		const UPrimaryDataAsset* const* Found = Assets.Find(Slot);
		const UVerseWeaponDefinition* Def = Found ? Cast<UVerseWeaponDefinition>(*Found) : nullptr;
		return Def ? Def : FVerseWeaponRegistry::FindWeapon(FallbackId);
	};
	auto GadgetFor = [&Assets](EVerseLoadoutSlot Slot, FName FallbackId) -> const UVerseGadgetDefinition*
	{
		const UPrimaryDataAsset* const* Found = Assets.Find(Slot);
		const UVerseGadgetDefinition* Def = Found ? Cast<UVerseGadgetDefinition>(*Found) : nullptr;
		return Def ? Def : FVerseWeaponRegistry::FindGadget(FallbackId);
	};

	int32 Filled = 0;
	if (UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(Pawn))
	{
		TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*> Weapons;
		if (const UVerseWeaponDefinition* Primary = WeaponFor(EVerseLoadoutSlot::Primary, PrimaryId))
		{
			Weapons.Add(EVerseLoadoutSlot::Primary, Primary);
		}
		if (const UVerseWeaponDefinition* Secondary = WeaponFor(EVerseLoadoutSlot::Secondary, SecondaryId))
		{
			Weapons.Add(EVerseLoadoutSlot::Secondary, Secondary);
		}
		const UWorld* World = GetWorld();
		Inventory->GiveLoadout(Weapons, World ? World->GetTimeSeconds() : 0.f);
		Filled += Weapons.Num();
	}
	if (UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Pawn))
	{
		Gadgets->Bulwark = GadgetFor(EVerseLoadoutSlot::GadgetA, GadgetAId);
		Gadgets->BreachCharge = GadgetFor(EVerseLoadoutSlot::GadgetB, GadgetBId);
		Gadgets->ResetForLife();
		Filled += (Gadgets->Bulwark ? 1 : 0) + (Gadgets->BreachCharge ? 1 : 0);
	}
	return Filled;
}

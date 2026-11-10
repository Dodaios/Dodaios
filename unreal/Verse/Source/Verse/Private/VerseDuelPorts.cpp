#include "VerseDuelPorts.h"

#include "Camera/PlayerCameraManager.h"
#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Engine/World.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Kismet/GameplayStatics.h"
#include "Movement/VerseMovementQuery.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelSubsystem.h"
#include "Weapons/VerseCombatEvents.h"
#include "Weapons/VerseSpread.h"
#include "Weapons/VerseWeaponComponent.h"

// ---------------------------------------------------------------------------------------------
// Game port

void FVerseDuelGamePort::StartDuel(FName Tier)
{
	if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World.Get()))
	{
		Duel->StartDuel(Tier);
	}
}

void FVerseDuelGamePort::LeaveDuel()
{
	if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World.Get()))
	{
		Duel->LeaveDuel();
	}
}

void FVerseDuelGamePort::TravelToDeck(FName Deck)
{
	if (UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(World.Get()))
	{
		Decks->RequestDeck(Deck);
	}
}

bool FVerseDuelGamePort::IsDuelRunning() const
{
	const UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World.Get());
	return Duel && Duel->IsDuelRunning();
}

FName FVerseDuelGamePort::GetCurrentDeck() const
{
	const UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(World.Get());
	return Decks ? Decks->GetCurrentDeck() : NAME_None;
}

void FVerseDuelGamePort::SetPaused(bool bPaused)
{
	// The person hosts the duel (combat-state 5.1), so the engine pause holds the bot too.
	if (UWorld* W = World.Get())
	{
		UGameplayStatics::SetGamePaused(W, bPaused);
	}
}

// ---------------------------------------------------------------------------------------------
// HUD source

APlayerController* FVerseDuelHudSource::LocalController() const
{
	UWorld* W = World.Get();
	return W ? W->GetFirstPlayerController() : nullptr;
}

APlayerState* FVerseDuelHudSource::FindPlayer(int32 PlayerId) const
{
	UWorld* W = World.Get();
	AGameStateBase* GameState = W ? W->GetGameState() : nullptr;
	if (!GameState)
	{
		return nullptr;
	}
	for (APlayerState* State : GameState->PlayerArray)
	{
		if (State && State->GetPlayerId() == PlayerId)
		{
			return State;
		}
	}
	return nullptr;
}

int32 FVerseDuelHudSource::GetLocalPlayerId() const
{
	APlayerController* PC = LocalController();
	return PC && PC->PlayerState ? PC->PlayerState->GetPlayerId() : INDEX_NONE;
}

double FVerseDuelHudSource::GetServerTime() const
{
	UWorld* W = World.Get();
	if (!W)
	{
		return 0.0;
	}
	const AGameStateBase* GameState = W->GetGameState();
	return GameState ? GameState->GetServerWorldTimeSeconds() : W->GetTimeSeconds();
}

void FVerseDuelHudSource::GetPawnState(FVerseHudPawnState& Out) const
{
	Out = FVerseHudPawnState();
	APlayerController* PC = LocalController();
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	if (!Pawn)
	{
		return;
	}
	Out.bValid = true;
	Out.bHealthKnown = false;
	if (const AVerseDefaultCharacter* Character = Cast<AVerseDefaultCharacter>(Pawn))
	{
		if (const UVerseHealthSet* Health = Character->GetHealthSet())
		{
			Out.bHealthKnown = true;
			Out.Health = Health->GetHealth();
			Out.MaxHealth = FMath::Max(1.f, Health->GetMaxHealth());
		}
	}
	const double Now = GetServerTime();
	if (const UVerseCombatStateComponent* Combat = Pawn->FindComponentByClass<UVerseCombatStateComponent>())
	{
		Out.Phase = Combat->Phase;
		Out.bSpawnProtected = Combat->bSpawnProtected;
		Out.SpawnProtectionRemaining = Combat->bSpawnProtected ? float(FMath::Max(0.0, Combat->SpawnProtectedUntil - Now)) : 0.f;
	}
	if (UActorComponent* Movement = Pawn->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
	{
		if (const IVerseMovementQuery* Query = Cast<IVerseMovementQuery>(Movement))
		{
			Out.Stance = Query->GetStance();
		}
	}
	if (const UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(Pawn))
	{
		Out.ActiveSlot = Inventory->ActiveSlot;
		const FVerseWeaponSlotState* Slot = Inventory->GetActiveState();
		const UVerseWeaponDefinition* Def = Slot ? Slot->Definition.Get() : nullptr;
		if (Def && Inventory->ActiveSlot != EVerseLoadoutSlot::Melee)
		{
			Out.bHasWeapon = true;
			Out.WeaponId = Def->WeaponId;
			Out.Magazine = Slot->Magazine;
			Out.MagazineSize = Def->MagazineSize;
			Out.bChambered = Slot->bChambered;
			Out.Reserve = Slot->Reserve;
			Out.bReloading = FVerseMagazine::IsReloading(*Slot);
			if (Out.bReloading)
			{
				const double Length = FMath::Max(0.01, double(Slot->ReloadEndsAt - Slot->ReloadStartedAt));
				Out.ReloadProgress = float(FMath::Clamp((Now - Slot->ReloadStartedAt) / Length, 0.0, 1.0));
				Out.bTacticalReload = Slot->Reload == EVerseReloadPhase::Tactical;
			}
		}
		else if (Inventory->ActiveSlot == EVerseLoadoutSlot::Melee)
		{
			Out.bHasWeapon = true;
			Out.WeaponId = TEXT("knife");
		}
	}
	if (const UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Pawn))
	{
		const float Cooldown = FMath::Max(0.f, Gadgets->GetCooldownEndsAt() - float(Now));
		auto Add = [&Out, Gadgets](const UVerseGadgetDefinition* Def, EVerseLoadoutSlot Slot, float CooldownLeft)
		{
			if (!Def)
			{
				return;
			}
			FVerseHudGadgetState State;
			State.GadgetId = Def->GadgetId;
			State.Charges = Gadgets->GetChargesLeft(Slot);
			State.MaxCharges = Def->Charges;
			State.CooldownRemaining = CooldownLeft;
			Out.Gadgets.Add(State);
		};
		Add(Gadgets->Bulwark, EVerseLoadoutSlot::GadgetA, Cooldown);
		Add(Gadgets->BreachCharge, EVerseLoadoutSlot::GadgetB, 0.f);
	}
}

bool FVerseDuelHudSource::GetView(FVerseHudView& Out) const
{
	APlayerController* PC = LocalController();
	if (!PC || !PC->PlayerCameraManager)
	{
		return false;
	}
	const FMinimalViewInfo& View = PC->PlayerCameraManager->GetCameraCacheView();
	Out.Location = View.Location;
	Out.Rotation = View.Rotation;
	Out.HorizontalFovDeg = View.FOV;
	return true;
}

bool FVerseDuelHudSource::GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const
{
	FVerseHudView View;
	if (!GetView(View))
	{
		return false;
	}
	OutDirection = View.Rotation.Vector();
	OutSpreadHalfAngleDeg = 0.f;
	APlayerController* PC = LocalController();
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	const UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Pawn);
	const UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(Pawn);
	const UVerseWeaponDefinition* Def = Inventory ? Inventory->GetActiveWeapon() : nullptr;
	if (!Weapon || !Def)
	{
		return true;
	}
	FVerseSpreadInput In;
	In.AdsBlend = Weapon->GetAdsBlend01();
	In.HorizontalSpeedMps = float(Pawn->GetVelocity().Size2D() / 100.0);
	if (UActorComponent* Movement = Pawn->FindComponentByInterface(UVerseMovementQuery::StaticClass()))
	{
		if (const IVerseMovementQuery* Query = Cast<IVerseMovementQuery>(Movement))
		{
			In.Stance = Query->GetStance();
			In.bAirborne = Query->IsAirborne();
		}
	}
	// 2 sigma covers about 95 % of the bolts.
	OutSpreadHalfAngleDeg = 2.f * Weapon->GetSpread().SigmaFor(*Def, In, float(GetServerTime()));
	return true;
}

FText FVerseDuelHudSource::GetDisplayName(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	return State ? FText::AsCultureInvariant(State->GetPlayerName()) : FText::GetEmpty();
}

bool FVerseDuelHudSource::IsBot(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	return State && State->IsABot();
}

FName FVerseDuelHudSource::GetBotTier(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	if (!State)
	{
		return NAME_None;
	}
	if (const FNameProperty* Prop = FindFProperty<FNameProperty>(State->GetClass(), TEXT("BotTier")))
	{
		return Prop->GetPropertyValue_InContainer(State);
	}
	return NAME_None;
}

float FVerseDuelHudSource::GetBotEffectiveSkill(int32 PlayerId) const
{
	const APlayerState* State = FindPlayer(PlayerId);
	if (!State)
	{
		return -1.f;
	}
	if (const FFloatProperty* Prop = FindFProperty<FFloatProperty>(State->GetClass(), TEXT("BotEffectiveSkill")))
	{
		return Prop->GetPropertyValue_InContainer(State);
	}
	return -1.f;
}

void FVerseDuelHudSource::GetPawnPoses(TArray<FVersePawnPose>& Out) const
{
	Out.Reset();
	UWorld* W = World.Get();
	AGameStateBase* GameState = W ? W->GetGameState() : nullptr;
	if (!GameState)
	{
		return;
	}
	for (APlayerState* State : GameState->PlayerArray)
	{
		const APawn* Pawn = State ? State->GetPawn() : nullptr;
		if (Pawn)
		{
			FVersePawnPose Pose;
			Pose.PlayerId = State->GetPlayerId();
			Pose.Location = Pawn->GetActorLocation();
			Pose.Rotation = Pawn->GetBaseAimRotation();
			Out.Add(Pose);
		}
	}
}

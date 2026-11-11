#include "VerseAudioBridge.h"

#include "Audio/VerseAudioSubsystem.h"
#include "Audio/VerseAudioTypes.h"
#include "Bridge/VerseBridgeClient.h"
#include "Bridge/VerseBridgeFeeds.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Core/VerseUiSubsystem.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Decks/VerseLiftTravel.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Menus/VerseUiMenus.h"
#include "Penetration/VersePenetrationPhysicalMaterial.h"
#include "PhysicalMaterials/PhysicalMaterial.h"
#include "VerseBridgeSubsystem.h"
#include "VerseCharacter.h"
#include "VerseCharacterMovement.h"
#include "VerseGameplayTags.h"

bool UVerseAudioBridge::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE) && Super::ShouldCreateSubsystem(Outer);
}

void UVerseAudioBridge::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency<UVerseEventHub>();
	Collection.InitializeDependency<UVerseAudioSubsystem>();
	Collection.InitializeDependency<UVerseUiSubsystem>();
	Super::Initialize(Collection);
}

UVerseAudioSubsystem* UVerseAudioBridge::Audio() const
{
	return UVerseAudioSubsystem::Get(GetWorld());
}

void UVerseAudioBridge::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (UVerseEventHub* Hub = UVerseEventHub::Get(&InWorld))
	{
		NoiseHandle = Hub->OnNoise.AddUObject(this, &UVerseAudioBridge::HandleNoise);
	}
	if (UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(&InWorld))
	{
		LiftHandle = Decks->OnLiftCue.AddUObject(this, &UVerseAudioBridge::HandleLiftCue);
		ArrivedHandle = Decks->OnDeckArrived.AddUObject(this, &UVerseAudioBridge::HandleDeckArrived);
	}
	if (UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(&InWorld))
	{
		ScreenHandle = Ui->OnScreenChanged.AddUObject(this, &UVerseAudioBridge::HandleScreen);
	}
	UGameInstance* Instance = InWorld.GetGameInstance();
	if (UVerseBridgeSubsystem* Bridge = Instance ? Instance->GetSubsystem<UVerseBridgeSubsystem>() : nullptr)
	{
		TWeakObjectPtr<UVerseAudioBridge> WeakSelf(this);
		AwardHandle = Bridge->Client().Progression.OnAward.AddLambda([WeakSelf](const TSharedPtr<FJsonObject>&)
		{
			if (UVerseAudioSubsystem* Sound = WeakSelf.IsValid() ? WeakSelf->Audio() : nullptr)
			{
				Sound->PlayUi(EVerseUiSound::LevelBell);
			}
		});
	}
	if (UVerseAudioSubsystem* Sound = Audio())
	{
		// Another player's reload plays at their pawn (the audio subsystem cannot look pawns up).
		TWeakObjectPtr<UWorld> WeakWorld(&InWorld);
		Sound->SetPlayerLocationResolver([WeakWorld](int32 PlayerId) -> TOptional<FVector>
		{
			if (UWorld* World = WeakWorld.Get())
			{
				for (TActorIterator<APawn> It(World); It; ++It)
				{
					if (It->GetPlayerState() && It->GetPlayerState()->GetPlayerId() == PlayerId)
					{
						return It->GetActorLocation();
					}
				}
			}
			return {};
		});
	}
	UpdateAmbience();
}

void UVerseAudioBridge::Deinitialize()
{
	UWorld* World = GetWorld();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
	{
		Hub->OnNoise.Remove(NoiseHandle);
	}
	if (UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(World))
	{
		Decks->OnLiftCue.Remove(LiftHandle);
		Decks->OnDeckArrived.Remove(ArrivedHandle);
	}
	if (UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(World))
	{
		Ui->OnScreenChanged.Remove(ScreenHandle);
	}
	UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
	if (UVerseBridgeSubsystem* Bridge = Instance ? Instance->GetSubsystem<UVerseBridgeSubsystem>() : nullptr)
	{
		Bridge->Client().Progression.OnAward.Remove(AwardHandle);
	}
	for (const TWeakObjectPtr<AVerseCharacter>& Weak : BoundPawns)
	{
		if (AVerseCharacter* Pawn = Weak.Get())
		{
			if (UVerseCharacterMovement* Move = Pawn->GetVerseMovement())
			{
				Move->OnFootstep.RemoveAll(this);
			}
		}
	}
	BoundPawns.Reset();
	Super::Deinitialize();
}

EVerseFootSurface UVerseAudioBridge::SurfaceOf(const UPhysicalMaterial* Material)
{
	if (Material == nullptr)
	{
		return EVerseFootSurface::Metal;
	}
	const FString Name = Material->GetName();
	EVerseWorldSurface Role;
	if (VersePenetration::SurfaceFromPhysicalMaterialName(Name, Role))
	{
		return Role == EVerseWorldSurface::StructuralBeam ? EVerseFootSurface::Metal : EVerseFootSurface::Concrete;
	}
	if (Name.Contains(TEXT("Grating")) || Name.Contains(TEXT("Catwalk")))
	{
		return EVerseFootSurface::Grating;
	}
	if (Name.Contains(TEXT("Rubble")) || Name.Contains(TEXT("Debris")))
	{
		return EVerseFootSurface::Rubble;
	}
	if (Name.Contains(TEXT("Concrete")))
	{
		return EVerseFootSurface::Concrete;
	}
	return EVerseFootSurface::Metal;
}

void UVerseAudioBridge::HandleFootstep(const FVerseNoiseEvent& Event, const UPhysicalMaterial* Surface)
{
	UVerseAudioSubsystem* Sound = Audio();
	if (!Sound)
	{
		return;
	}
	if (Event.Noise == VerseTags::Noise_Footstep_Walk || Event.Noise == VerseTags::Noise_Footstep_Run || Event.Noise == VerseTags::Noise_Footstep_Sprint)
	{
		const EVerseGait Gait = Event.Noise == VerseTags::Noise_Footstep_Sprint ? EVerseGait::Sprint
			: Event.Noise == VerseTags::Noise_Footstep_Run ? EVerseGait::Run
			: EVerseGait::Walk;
		Sound->PlayFootstep(Event.SourceId, SurfaceOf(Surface), Gait, Event.Location);
		++Footsteps;
	}
	else if (Event.Noise == VerseTags::Noise_Move_Land)
	{
		Sound->PlayFoley(Event.SourceId, EVerseFoley::Land, Event.Location);
	}
	else if (Event.Noise == VerseTags::Noise_Move_Slide)
	{
		Sound->PlayFoley(Event.SourceId, EVerseFoley::Slide, Event.Location);
	}
	else if (Event.Noise == VerseTags::Noise_Move_Mantle)
	{
		Sound->PlayFoley(Event.SourceId, EVerseFoley::Mantle, Event.Location);
	}
}

void UVerseAudioBridge::HandleNoise(const FVerseNoiseEvent& Event)
{
	// Footsteps come per pawn with their floor (HandleFootstep); the knife swing only as a noise.
	if (Event.Noise == VerseTags::Noise_Melee)
	{
		if (UVerseAudioSubsystem* Sound = Audio())
		{
			Sound->PlayKnifeSwing(Event.SourceId, Event.Location);
		}
	}
}

void UVerseAudioBridge::HandleLiftCue(EVerseLiftCue Cue)
{
	UVerseAudioSubsystem* Sound = Audio();
	if (!Sound)
	{
		return;
	}
	switch (Cue)
	{
	case EVerseLiftCue::DoorClose:
		Sound->PlayLift(EVerseLiftSound::DoorClose);
		break;
	case EVerseLiftCue::Ride:
		Sound->PlayLift(EVerseLiftSound::RideStart);
		break;
	case EVerseLiftCue::DoorOpen:
	case EVerseLiftCue::GaveUp:
		Sound->PlayLift(EVerseLiftSound::RideStop);
		Sound->PlayLift(EVerseLiftSound::DoorOpen);
		break;
	}
}

void UVerseAudioBridge::HandleDeckArrived(FName Deck, bool bByLift)
{
	UpdateAmbience();
}

void UVerseAudioBridge::UpdateAmbience()
{
	UVerseAudioSubsystem* Sound = Audio();
	const UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(GetWorld());
	if (!Sound || !Decks)
	{
		return;
	}
	const FString Deck = Decks->GetCurrentDeck().ToString();
	const EVerseAmbience Bed = Deck == TEXT("bridge") ? EVerseAmbience::Bridge
		: Deck == TEXT("ops") ? EVerseAmbience::Ops
		: Deck == TEXT("engineering") ? EVerseAmbience::Engineering
		: Deck == TEXT("hangar") ? EVerseAmbience::Hangar
		: EVerseAmbience::None;
	Sound->SetAmbience(Bed);
}

void UVerseAudioBridge::HandleScreen(EVerseUiScreen Screen)
{
	const bool bOpen = Screen != EVerseUiScreen::None;
	if (bOpen == bPanelOpen)
	{
		return;
	}
	bPanelOpen = bOpen;
	if (UVerseAudioSubsystem* Sound = Audio())
	{
		Sound->PlayUi(bOpen ? EVerseUiSound::PanelOpen : EVerseUiSound::PanelClose);
	}
}

void UVerseAudioBridge::BindPawns()
{
	for (auto It = BoundPawns.CreateIterator(); It; ++It)
	{
		if (!It->IsValid())
		{
			It.RemoveCurrent();
		}
	}
	for (TActorIterator<AVerseCharacter> It(GetWorld()); It; ++It)
	{
		AVerseCharacter* Pawn = *It;
		if (BoundPawns.Contains(Pawn))
		{
			continue;
		}
		if (UVerseCharacterMovement* Move = Pawn->GetVerseMovement())
		{
			Move->OnFootstep.AddUObject(this, &UVerseAudioBridge::HandleFootstep);
			BoundPawns.Add(Pawn);
		}
	}
}

void UVerseAudioBridge::WatchEquip()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	APawn* Pawn = PC ? PC->GetPawn() : nullptr;
	const UVerseInventoryComponent* Inventory = Pawn ? UVerseInventoryComponent::FindOn(Pawn) : nullptr;
	if (!Inventory)
	{
		EquipPawn.Reset();
		return;
	}
	if (EquipPawn.Get() != Pawn)
	{
		// A new life starts on its weapon without the equip sound.
		EquipPawn = Pawn;
		EquipSlot = Inventory->ActiveSlot;
		return;
	}
	if (Inventory->ActiveSlot == EquipSlot)
	{
		return;
	}
	EquipSlot = Inventory->ActiveSlot;
	const UVerseWeaponDefinition* Weapon = Inventory->GetActiveWeapon();
	if (UVerseAudioSubsystem* Sound = Audio())
	{
		Sound->PlayEquip(Pawn->GetPlayerState() ? Pawn->GetPlayerState()->GetPlayerId() : INDEX_NONE, Weapon ? Weapon->WeaponId : FName(TEXT("knife")));
		++Equips;
	}
}

void UVerseAudioBridge::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	UWorld* World = GetWorld();
	if (!World || !World->HasBegunPlay())
	{
		return;
	}
	BindPawns();
	WatchEquip();
}

TStatId UVerseAudioBridge::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseAudioBridge, STATGROUP_Tickables);
}

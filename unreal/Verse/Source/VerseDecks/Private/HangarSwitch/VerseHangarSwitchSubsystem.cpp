#include "HangarSwitch/VerseHangarSwitchSubsystem.h"

#include "Combat/VerseCombatTypes.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "HAL/PlatformTime.h"
#include "VerseLog.h"
#include "WorldPartition/DataLayer/DataLayerAsset.h"
#include "WorldPartition/DataLayer/DataLayerInstance.h"
#include "WorldPartition/DataLayer/DataLayerManager.h"
#include "WorldPartition/WorldPartitionSubsystem.h"

const FName UVerseHangarSwitchSubsystem::HangarDeck(TEXT("hangar"));
const FName UVerseHangarSwitchSubsystem::QuickStartReason(TEXT("quick_start_duel"));

const TCHAR* FVerseHangarDataLayers::DayLayerPath = TEXT("/Game/Verse/Decks/Hangar/DataLayers/DL_Hangar_Day.DL_Hangar_Day");
const TCHAR* FVerseHangarDataLayers::ArenaLayerPath = TEXT("/Game/Verse/Decks/Hangar/DataLayers/DL_Hangar_Arena.DL_Hangar_Arena");

// ---------------------------------------------------------------------------
// Data layers
// ---------------------------------------------------------------------------

namespace
{
	struct FHangarLayerAssets
	{
		const UDataLayerAsset* Day = nullptr;
		const UDataLayerAsset* Arena = nullptr;
		bool IsValid() const { return Day && Arena; }
	};

	FHangarLayerAssets LoadLayerAssets()
	{
		FHangarLayerAssets Out;
		Out.Day = LoadObject<UDataLayerAsset>(nullptr, FVerseHangarDataLayers::DayLayerPath);
		Out.Arena = LoadObject<UDataLayerAsset>(nullptr, FVerseHangarDataLayers::ArenaLayerPath);
		return Out;
	}
}

bool FVerseHangarDataLayers::Request(bool bArena)
{
	UWorld* W = World.Get();
	UDataLayerManager* Manager = W ? UDataLayerManager::GetDataLayerManager(W) : nullptr;
	const FHangarLayerAssets Assets = LoadLayerAssets();
	if (!Manager || !Assets.IsValid())
	{
		return false;
	}
	// Unload the side that goes away first, so the two sets never stand in each other.
	const bool bA = Manager->SetDataLayerRuntimeState(bArena ? Assets.Day : Assets.Arena, EDataLayerRuntimeState::Unloaded);
	const bool bB = Manager->SetDataLayerRuntimeState(bArena ? Assets.Arena : Assets.Day, EDataLayerRuntimeState::Activated);
	return bA && bB;
}

bool FVerseHangarDataLayers::IsDone(bool bArena) const
{
	UWorld* W = World.Get();
	const UDataLayerManager* Manager = W ? UDataLayerManager::GetDataLayerManager(W) : nullptr;
	const FHangarLayerAssets Assets = LoadLayerAssets();
	if (!Manager || !Assets.IsValid())
	{
		return true;
	}
	const UDataLayerInstance* On = Manager->GetDataLayerInstanceFromAsset(bArena ? Assets.Arena : Assets.Day);
	const UDataLayerInstance* Off = Manager->GetDataLayerInstanceFromAsset(bArena ? Assets.Day : Assets.Arena);
	if (!On || !Off)
	{
		return true;
	}
	if (Manager->GetDataLayerInstanceEffectiveRuntimeState(On) != EDataLayerRuntimeState::Activated
		|| Manager->GetDataLayerInstanceEffectiveRuntimeState(Off) != EDataLayerRuntimeState::Unloaded)
	{
		return false;
	}
	const UWorldPartitionSubsystem* Streaming = W->GetSubsystem<UWorldPartitionSubsystem>();
	return !Streaming || Streaming->IsStreamingCompleted();
}

// ---------------------------------------------------------------------------
// Subsystem
// ---------------------------------------------------------------------------

UVerseHangarSwitchSubsystem* UVerseHangarSwitchSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseHangarSwitchSubsystem>() : nullptr;
}

bool UVerseHangarSwitchSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE);
}

void UVerseHangarSwitchSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency<UVerseEventHub>();
	Super::Initialize(Collection);
	if (!Layers)
	{
		Layers = MakeUnique<FVerseHangarDataLayers>(GetWorld());
	}
}

void UVerseHangarSwitchSubsystem::SetLayers(TUniquePtr<IVerseHangarLayers> InLayers)
{
	Layers = MoveTemp(InLayers);
}

FBox UVerseHangarSwitchSubsystem::ArenaBoundsCm()
{
	// docs/verse/unreal/arena.md: plan x 25..75 m, z 4..44 m, heights up to the fence.
	return FBox(FVector(2500.0, 400.0, -100.0), FVector(7500.0, 4400.0, 1000.0));
}

bool UVerseHangarSwitchSubsystem::HasAuthority() const
{
	const UWorld* World = GetWorld();
	return World && World->GetNetMode() != NM_Client;
}

double UVerseHangarSwitchSubsystem::NowSeconds() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

bool UVerseHangarSwitchSubsystem::HandleLifecycleShow(FName Reason)
{
	return Reason == QuickStartReason && RequestArena(true, Reason);
}

bool UVerseHangarSwitchSubsystem::RequestArena(bool bArena, FName Reason)
{
	if (!HasAuthority())
	{
		return false;
	}
	if (IsSwitching())
	{
		const bool bTarget = Mode == EVerseHangarMode::SwitchingToArena;
		if (bTarget == bArena)
		{
			Pending.Reset();
			return false;
		}
		Pending = bArena;  // applied when the running switch is done
		return true;
	}
	if (IsArenaOn() == bArena)
	{
		return false;
	}
	Mode = bArena ? EVerseHangarMode::SwitchingToArena : EVerseHangarMode::SwitchingToDay;
	RequestedAt = NowSeconds();
	const bool bLayers = Layers && Layers->Request(bArena);
	if (!bLayers)
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("Hangar switch: no hangar data layers in this world; switching without streaming"));
		Finish();
		return true;
	}
	UE_LOG(LogVerseDecks, Log, TEXT("Hangar switch: to %s (%s)"), bArena ? TEXT("arena") : TEXT("day"), *Reason.ToString());
	Step();
	return true;
}

void UVerseHangarSwitchSubsystem::Step()
{
	if (!IsSwitching())
	{
		return;
	}
	const bool bArena = Mode == EVerseHangarMode::SwitchingToArena;
	if (!Layers || Layers->IsDone(bArena))
	{
		Finish();
		return;
	}
	if (NowSeconds() - RequestedAt > SwitchTimeoutS)
	{
		UE_LOG(LogVerseDecks, Error, TEXT("Hangar switch: layers not done after %.1f s; finishing anyway"), SwitchTimeoutS);
		Finish();
	}
}

void UVerseHangarSwitchSubsystem::Finish()
{
	const bool bArena = Mode == EVerseHangarMode::SwitchingToArena;
	Mode = bArena ? EVerseHangarMode::Arena : EVerseHangarMode::Day;
	LastSwitchSeconds = float(NowSeconds() - RequestedAt);
	++SwitchCount;
	if (LastSwitchSeconds > SwitchBudgetS)
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("Hangar switch took %.2f s (budget %.1f s, A11.4)"), LastSwitchSeconds, SwitchBudgetS);
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		FVerseArenaSwitchEvent Event;
		Event.bArenaOn = bArena;
		Event.Deck = HangarDeck;
		const UWorld* World = GetWorld();
		Event.ServerTime = World ? World->GetTimeSeconds() : 0.f;
		Hub->OnArenaSwitch.Broadcast(Event);
	}
	if (Pending.IsSet())
	{
		const bool bNext = Pending.GetValue();
		Pending.Reset();
		RequestArena(bNext, NAME_None);
	}
}

void UVerseHangarSwitchSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Step();
}

TStatId UVerseHangarSwitchSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseHangarSwitchSubsystem, STATGROUP_Tickables);
}

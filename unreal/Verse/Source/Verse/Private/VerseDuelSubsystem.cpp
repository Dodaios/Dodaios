#include "VerseDuelSubsystem.h"
#include "VerseFramePacing.h"

#include "Bot/VerseBotTier.h"
#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Controller/VerseBotController.h"
#include "Core/VerseUiSubsystem.h"
#include "Damage/VerseCombatStateComponent.h"
#include "Damage/VerseHealthSet.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/GameModeBase.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "Abilities/VerseSovereignBody.h"
#include "Commander/VerseDeckCommander.h"
#include "Decks/VerseDeckSubsystem.h"
#include "HangarSwitch/VerseHangarSwitchSubsystem.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Crew/VerseCrewPawn.h"
#include "Misc/App.h"
#include "VerseCrewBody.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/OutputDeviceRedirector.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "NavigationPath.h"
#include "NavigationSystem.h"
#include "NavMesh/RecastNavMesh.h"
#include "Perception/VersePerceptionModel.h"
#include "Perception/VersePerceptionService.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "VerseArenaGraybox.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelAutopilot.h"
#include "VerseDuelPorts.h"
#include "VerseLog.h"
#include "Weapons/VerseCombatEvents.h"
#include "Weapons/VerseWeaponComponent.h"

namespace VerseDuelPrivate
{
	/** Player ids of the duel bots when the engine left them at 0. */
	constexpr int32 BotPlayerIdBase = 9000;

	/** Seconds after the hangar arrived before a command-line duel starts (streaming settles). */
	constexpr double CommandLineStartDelayS = 2.0;

	/** Counts error lines while a scripted run is going (a run with errors is not clean). */
	class FErrorCounter : public FOutputDevice
	{
	public:
		TAtomic<int32> Errors{0};
		virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
		{
			if ((Verbosity & ELogVerbosity::VerbosityMask) <= ELogVerbosity::Error)
			{
				++Errors;
			}
		}
		virtual bool CanBeUsedOnAnyThread() const override { return true; }
	};
	FErrorCounter* GErrorCounter = nullptr;
	int32 GErrorCounterUsers = 0;

	/** DA_BotTier_<Tier> under /Game/Verse/Bot/Tiers (bot.md 9.1); adaptive starts from hard. */
	const UVerseBotTier* LoadTier(FName TierId)
	{
		FString Id = TierId == TEXT("adaptive") ? FString(TEXT("hard")) : TierId.ToString().ToLower();
		if (Id.IsEmpty())
		{
			return nullptr;
		}
		Id[0] = FChar::ToUpper(Id[0]);
		const FString Name = TEXT("DA_BotTier_") + Id;
		const FString Path = FString::Printf(TEXT("/Game/Verse/Bot/Tiers/%s.%s"), *Name, *Name);
		return LoadObject<UVerseBotTier>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
}

namespace VerseDuelPrivate
{
	/** Console: Verse.Duel.Start [normal|hard|elite|adaptive] [bots] [autoplay]; Verse.Duel.Leave. */
	FAutoConsoleCommandWithWorldAndArgs StartCommand(TEXT("Verse.Duel.Start"),
		TEXT("Starts the hangar duel: Verse.Duel.Start [normal|hard|elite|adaptive] [bots] [autoplay]"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>& Args, UWorld* World)
			{
				if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World))
				{
					Duel->SetBotVsBot(Args.Contains(TEXT("bots")));
					Duel->SetAutoplay(Args.Contains(TEXT("autoplay")));
					Duel->StartDuel(Args.Num() > 0 && Args[0] != TEXT("bots") && Args[0] != TEXT("autoplay") ? FName(*Args[0]) : FName(TEXT("hard")));
				}
			}));
	FAutoConsoleCommandWithWorldAndArgs LeaveCommand(TEXT("Verse.Duel.Leave"), TEXT("Leaves the hangar duel"),
		FConsoleCommandWithWorldAndArgsDelegate::CreateLambda([](const TArray<FString>&, UWorld* World)
			{
				if (UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World))
				{
					Duel->LeaveDuel();
				}
			}));
}

void FVerseDuelFrameStats::Add(float DeltaS)
{
	if (DeltaS <= 0.f)
	{
		return;
	}
	++Frames;
	SumS += DeltaS;
	WorstS = FMath::Max(WorstS, double(DeltaS));
	Samples.Add(DeltaS);
}

double FVerseDuelFrameStats::OnePercentLowFps() const
{
	if (Samples.Num() == 0)
	{
		return 0.0;
	}
	TArray<float> Sorted = Samples;
	Sorted.Sort([](float A, float B) { return A > B; });
	const int32 Count = FMath::Max(1, Sorted.Num() / 100);
	double Sum = 0.0;
	for (int32 I = 0; I < Count; ++I)
	{
		Sum += Sorted[I];
	}
	return Sum > 0.0 ? Count / Sum : 0.0;
}

UVerseDuelSubsystem* UVerseDuelSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	return World ? World->GetSubsystem<UVerseDuelSubsystem>() : nullptr;
}

bool UVerseDuelSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE) && Super::ShouldCreateSubsystem(Outer);
}

void UVerseDuelSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency<UVerseEventHub>();
	Super::Initialize(Collection);
	using namespace VerseDuelPrivate;
	if (GErrorCounterUsers++ == 0 && GLog)
	{
		GErrorCounter = new FErrorCounter();
		GLog->AddOutputDevice(GErrorCounter);
	}
}

void UVerseDuelSubsystem::Deinitialize()
{
	if (bDuelRunning)
	{
		FVerseFramePacing::SetDuelRunning(false);
	}
	using namespace VerseDuelPrivate;
	if (UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld()))
	{
		Hub->OnDeath.Remove(DeathHandle);
		Hub->OnFire.Remove(FireHandle);
		Hub->OnHit.Remove(HitHandle);
	}
	if (UVersePerceptionService* Service = UVersePerceptionService::Get(GetWorld()))
	{
		Service->OnPerceptFrame.Remove(PerceptHandle);
	}
	if (UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(GetWorld()))
	{
		Decks->OnDeckArrived.Remove(DeckArrivedHandle);
	}
	if (--GErrorCounterUsers == 0 && GErrorCounter)
	{
		if (GLog)
		{
			GLog->RemoveOutputDevice(GErrorCounter);
		}
		delete GErrorCounter;
		GErrorCounter = nullptr;
	}
	Super::Deinitialize();
}

void UVerseDuelSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	if (UVerseEventHub* Hub = UVerseEventHub::Get(&InWorld))
	{
		DeathHandle = Hub->OnDeath.AddUObject(this, &UVerseDuelSubsystem::HandleDeath);
		FireHandle = Hub->OnFire.AddUObject(this, &UVerseDuelSubsystem::HandleFire);
		HitHandle = Hub->OnHit.AddUObject(this, &UVerseDuelSubsystem::HandleHit);
	}
	if (InWorld.GetNetMode() != NM_Client)
	{
		WirePerception();
	}
	InstallUiPorts();
	if (UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(&InWorld))
	{
		DeckArrivedHandle = Decks->OnDeckArrived.AddUObject(this, &UVerseDuelSubsystem::HandleDeckArrived);
	}
	BuildHallIfOnHangar();
	ReadCommandLine();
}

void UVerseDuelSubsystem::HandleDeckArrived(FName Deck, bool bByLift)
{
	BuildHallIfOnHangar();
	DressCommander();
}

void UVerseDuelSubsystem::DressCommander()
{
	// The person walks the decks as the Sovereign, the skin they designed (stream S7).
	AVerseDeckCommander* Commander = AVerseDeckCommander::Find(GetWorld());
	if (Commander && UVerseSovereignBody::Dress(Commander))
	{
		Commander->RefreshBody();
	}
}

void UVerseDuelSubsystem::DressCrew(float DeltaTime)
{
	// Crew pawns come and go with crew life: give each new one its real body (twice a second).
	CrewDressS -= DeltaTime;
	if (CrewDressS > 0.f)
	{
		return;
	}
	CrewDressS = 0.5f;
	for (TActorIterator<AVerseCrewPawn> It(GetWorld()); It; ++It)
	{
		if (It->FindComponentByClass<UVerseCrewBody>() == nullptr)
		{
			UVerseCrewBody::Dress(*It);
		}
	}
}

void UVerseDuelSubsystem::BuildHallIfOnHangar()
{
	UWorld* World = GetWorld();
	UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(World);
	if (!World || !World->IsGameWorld() || !Decks || Decks->GetCurrentDeck() != UVerseHangarSwitchSubsystem::HangarDeck)
	{
		return;
	}
	// The rooms that hold a deck station (arrivals, lift lobby) stay free of the hall's loose props.
	TArray<FVerseDeckRoom> KeepClear;
	if (const FVerseDeckManifest* Manifest = Decks->GetManifest(UVerseHangarSwitchSubsystem::HangarDeck))
	{
		for (const FVerseDeckRoom& Room : Manifest->Rooms)
		{
			const bool bStation = Manifest->Stations.ContainsByPredicate([&Room](const FVerseDeckStation& S) { return S.Room == Room.Id; });
			if (bStation && !Room.bMain)
			{
				KeepClear.Add(Room);
			}
		}
	}
	// The deck view stands in the same dressed hall as the duel; the duel's full graybox replaces it.
	if (!bDuelRunning)
	{
		AVerseArenaGraybox::BuildHall(*World, KeepClear);
	}
}

void UVerseDuelSubsystem::InstallUiPorts()
{
	UWorld* World = GetWorld();
	UVerseUiSubsystem* Ui = World ? World->GetSubsystem<UVerseUiSubsystem>() : nullptr;
	if (!Ui)
	{
		return;
	}
	Ui->SetGamePort(MakeShared<FVerseDuelGamePort>(World));
	Ui->SetHudSource(MakeShared<FVerseDuelHudSource>(World));
}

void UVerseDuelSubsystem::ReadCommandLine()
{
#if !UE_BUILD_SHIPPING
	const TCHAR* Cmd = FCommandLine::Get();
	FString TierArg;
	if (FParse::Value(Cmd, TEXT("VerseDuel="), TierArg))
	{
		bStartRequested = true;
		Tier = FName(*TierArg);
	}
	else if (FParse::Param(Cmd, TEXT("VerseDuel")))
	{
		bStartRequested = true;
	}
	bBotVsBot = FParse::Param(Cmd, TEXT("VerseDuelBots"));
	bAutoplay = FParse::Param(Cmd, TEXT("VerseDuelAutoplay"));
	FParse::Value(Cmd, TEXT("VerseDuelSeconds="), RunSeconds);
	FParse::Value(Cmd, TEXT("VerseDuelStats="), StatsFile);
	if (bStartRequested)
	{
		UE_LOG(LogVerse, Log, TEXT("[VerseDuel] command line: tier=%s bots=%d autoplay=%d seconds=%.0f"), *Tier.ToString(),
			bBotVsBot ? 1 : 0, bAutoplay ? 1 : 0, RunSeconds);
	}
#endif
}

// ---------------------------------------------------------------------------------------------
// Duel control

AVerseBotController* UVerseDuelSubsystem::SpawnBot(FName BotTier, int32 Index)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.Name = MakeUniqueObjectName(World->GetCurrentLevel(), AVerseBotController::StaticClass(), FName(*FString::Printf(TEXT("DuelBot_%d"), Index)));
	AVerseBotController* Bot = World->SpawnActor<AVerseBotController>(Params);
	if (!Bot)
	{
		UE_LOG(LogVerse, Error, TEXT("[VerseDuel] cannot spawn a bot controller"));
		return nullptr;
	}
	if (const UVerseBotTier* Loaded = VerseDuelPrivate::LoadTier(BotTier))
	{
		Bot->SetTier(Loaded);
	}
	else
	{
		UE_LOG(LogVerse, Warning, TEXT("[VerseDuel] no tier asset for %s; the bot keeps its default"), *BotTier.ToString());
	}
	Bot->SetAdaptive(BotTier == TEXT("adaptive"));
	Bot->SetSeed(FMath::Rand() ^ (uint64(Index) << 32));
	if (APlayerState* State = Bot->PlayerState)
	{
		State->SetPlayerName(Index == 0 && !bBotVsBot ? TEXT("Bot") : FString::Printf(TEXT("Bot %c"), TCHAR('A' + Index)));
		State->SetIsABot(true);
		// Events carry player ids and treat 0 as nobody; a bot's state may come up with 0.
		if (State->GetPlayerId() == 0)
		{
			State->SetPlayerId(VerseDuelPrivate::BotPlayerIdBase + Index);
		}
	}
	Bots.Add(Bot);
	return Bot;
}

void UVerseDuelSubsystem::DestroyBots()
{
	for (const TWeakObjectPtr<AVerseBotController>& Weak : Bots)
	{
		if (AVerseBotController* Bot = Weak.Get())
		{
			if (APawn* Pawn = Bot->GetPawn())
			{
				Bot->UnPossess();
				Pawn->Destroy();
			}
			if (UVersePerceptionService* Service = UVersePerceptionService::Get(GetWorld()))
			{
				Service->UnregisterObserver(Bot);
			}
			Bot->Destroy();
		}
	}
	Bots.Reset();
	Observers.RemoveAll([](const TWeakObjectPtr<AController>& Weak) { return !Weak.IsValid(); });
}

bool UVerseDuelSubsystem::StartDuel(FName InTier)
{
	UWorld* World = GetWorld();
	if (!World || World->GetNetMode() == NM_Client)
	{
		return false;
	}
	if (!InTier.IsNone())
	{
		Tier = InTier;
	}
	DestroyBots();
	const int32 NumBots = bBotVsBot ? 2 : 1;
	for (int32 Index = 0; Index < NumBots; ++Index)
	{
		if (!SpawnBot(Tier, Index))
		{
			return false;
		}
	}
	// The person plays unless bots play each other (spectators never join the deathmatch).
	for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
	{
		APlayerController* PC = It->Get();
		if (PC && PC->PlayerState)
		{
			PC->PlayerState->SetIsSpectator(bBotVsBot);
			PC->PlayerState->SetIsOnlyASpectator(bBotVsBot);
			if (bBotVsBot && PC->GetPawn())
			{
				APawn* Old = PC->GetPawn();
				PC->UnPossess();
				Old->Destroy();
			}
		}
	}
	RegisterObservers();
	ResetStats();
	bDuelRunning = true;
	FVerseFramePacing::SetDuelRunning(true);
	NavChecks = 0;
	MatchStartedAt = World->GetTimeSeconds();

	// The level has no arena yet (arena.md 10): build the WP11 graybox before the match spawns anyone.
	AVerseArenaGraybox::BuildIfMissing(*World);

	UVerseHangarSwitchSubsystem* Switch = UVerseHangarSwitchSubsystem::Get(World);
	const bool bSwitching = Switch && Switch->RequestArena(true, UVerseHangarSwitchSubsystem::QuickStartReason);
	if (!bSwitching)
	{
		// The arena is already on (a restart) or there is no switch: start the match directly.
		if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
		{
			FVerseArenaSwitchEvent Event;
			Event.bArenaOn = true;
			Event.Deck = UVerseHangarSwitchSubsystem::HangarDeck;
			Event.ServerTime = VerseCombatEvents::ServerTime(World);
			Hub->OnArenaSwitch.Broadcast(Event);
		}
	}
	UE_LOG(LogVerse, Log, TEXT("[VerseDuel] duel started: tier=%s bot count=%d autoplay=%d"), *Tier.ToString(), NumBots, bAutoplay ? 1 : 0);
	return true;
}

void UVerseDuelSubsystem::LeaveDuel()
{
	UWorld* World = GetWorld();
	if (!World || World->GetNetMode() == NM_Client)
	{
		return;
	}
	bDuelRunning = false;
	FVerseFramePacing::SetDuelRunning(false);
	if (UVerseHangarSwitchSubsystem* Switch = UVerseHangarSwitchSubsystem::Get(World))
	{
		Switch->RequestArena(false, TEXT("leave_duel"));
	}
	DestroyBots();
	if (AVerseArenaGraybox* Graybox = AVerseArenaGraybox::Find(*World))
	{
		Graybox->Destroy();
	}
	for (FConstPlayerControllerIterator It = World->GetPlayerControllerIterator(); It; ++It)
	{
		APlayerController* PC = It->Get();
		if (!PC)
		{
			continue;
		}
		if (PC->PlayerState)
		{
			PC->PlayerState->SetIsSpectator(false);
			PC->PlayerState->SetIsOnlyASpectator(false);
		}
		if (!PC->GetPawn())
		{
			if (AGameModeBase* Mode = World->GetAuthGameMode())
			{
				Mode->RestartPlayer(PC);
			}
		}
	}
	// The arena is gone; the hangar keeps its hall.
	BuildHallIfOnHangar();
	UE_LOG(LogVerse, Log, TEXT("[VerseDuel] duel left"));
}

double UVerseDuelSubsystem::GetMatchSeconds() const
{
	const UWorld* World = GetWorld();
	return World && bDuelRunning ? World->GetTimeSeconds() - MatchStartedAt : 0.0;
}

APawn* UVerseDuelSubsystem::GetFocusPawn() const
{
	if (bBotVsBot)
	{
		for (const TWeakObjectPtr<AVerseBotController>& Weak : Bots)
		{
			if (const AVerseBotController* Bot = Weak.Get())
			{
				return Bot->GetPawn();
			}
		}
		return nullptr;
	}
	const UWorld* World = GetWorld();
	const APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	return PC ? PC->GetPawn() : nullptr;
}

// ---------------------------------------------------------------------------------------------
// Perception (bot.md 2): the service produces frames, the bots read only those.

void UVerseDuelSubsystem::WirePerception()
{
	UVersePerceptionService* Service = UVersePerceptionService::Get(GetWorld());
	if (!Service || bPerceptionWired)
	{
		return;
	}
	bPerceptionWired = true;
	PerceptHandle = Service->OnPerceptFrame.AddUObject(this, &UVerseDuelSubsystem::HandlePercept);
	Service->SetSelfPerceptFiller([](const APawn& Pawn, FVerseSelfPercept& Self)
	{
		if (const AVerseDefaultCharacter* Character = Cast<AVerseDefaultCharacter>(&Pawn))
		{
			if (const UVerseHealthSet* Health = Character->GetHealthSet())
			{
				Self.Health = Health->GetHealth();
				Self.MaxHealth = Health->GetMaxHealth();
				Self.Armor = Health->GetArmor();
			}
		}
		if (const UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(&Pawn))
		{
			Self.ActiveSlot = Inventory->ActiveSlot;
			if (const FVerseWeaponSlotState* Slot = Inventory->GetActiveState())
			{
				Self.Magazine = Slot->Magazine;
				Self.bChambered = Slot->bChambered;
				Self.Reserve = Slot->Reserve;
			}
		}
		if (const UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(&Pawn))
		{
			const float Now = VerseCombatEvents::ServerTime(&Pawn);
			Self.GadgetCharges[0] = Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA);
			Self.GadgetCharges[1] = Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB);
			Self.GadgetCooldownS[0] = FMath::Max(0.f, Gadgets->GetCooldownEndsAt() - Now);
		}
	});
	Service->SetBodyFiller([](const APawn& Pawn, FVersePerceptionBody& Body)
	{
		if (const UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(&Pawn))
		{
			Body.bAds = Weapon->GetAdsBlend01() > 0.5f;
		}
		if (const UVerseInventoryComponent* Inventory = UVerseInventoryComponent::FindOn(&Pawn))
		{
			const UVerseWeaponDefinition* Active = Inventory->GetActiveWeapon();
			Body.HeldWeaponId = Active ? Active->WeaponId : FName(TEXT("knife"));
			Body.bReloading = Inventory->bReloading;
		}
	});
}

void UVerseDuelSubsystem::RegisterObservers()
{
	UVersePerceptionService* Service = UVersePerceptionService::Get(GetWorld());
	UWorld* World = GetWorld();
	if (!Service || !World)
	{
		return;
	}
	// Every bot controller in the world, ours and the harness's (Gauntlet bot slots).
	for (TActorIterator<AVerseBotController> It(World); It; ++It)
	{
		AVerseBotController* Bot = *It;
		if (!Bot->PlayerState || Service->IsRegistered(Bot))
		{
			continue;
		}
		FVersePerceptionProfile Profile;
		const FName BotTier = Bot->IsAdaptive() ? FName(TEXT("hard")) : Tier;
		if (const UVerseBotTier* Loaded = VerseDuelPrivate::LoadTier(BotTier))
		{
			Profile = FVersePerceptionModel::MakeProfile(*Loaded, uint32(FMath::Rand()));
		}
		Service->RegisterObserver(Bot, Profile);
		Observers.Add(Bot);
	}
}

void UVerseDuelSubsystem::HandlePercept(AController* Observer, const FVersePerceptFrame& Frame)
{
	if (AVerseBotController* Bot = Cast<AVerseBotController>(Observer))
	{
		Bot->ReceivePerceptFrame(Frame);
	}
}

// ---------------------------------------------------------------------------------------------
// Stats

FVerseDuelPlayerStats& UVerseDuelSubsystem::StatsFor(int32 PlayerId)
{
	FVerseDuelPlayerStats& Stats = Players.FindOrAdd(PlayerId);
	Stats.PlayerId = PlayerId;
	if (Stats.Name.IsEmpty())
	{
		if (const UWorld* World = GetWorld())
		{
			if (const AGameStateBase* State = World->GetGameState())
			{
				for (const APlayerState* P : State->PlayerArray)
				{
					if (P && P->GetPlayerId() == PlayerId)
					{
						Stats.Name = P->GetPlayerName();
						Stats.bBot = P->IsABot();
					}
				}
			}
		}
	}
	return Stats;
}

void UVerseDuelSubsystem::HandleDeath(const FVerseDeathEvent& Event)
{
	FVerseDuelPlayerStats& Victim = StatsFor(Event.VictimId);
	++Victim.Deaths;
	if (Event.KillerId != Event.VictimId)
	{
		FVerseDuelPlayerStats& Killer = StatsFor(Event.KillerId);
		++Killer.Kills;
		Killer.Headshots += Event.LastZone == EVerseHitZone::Head ? 1 : 0;
		Killer.Finishers += Event.Cause == EVerseDamageSource::Finisher ? 1 : 0;
		Killer.KnifeKills += Event.Cause == EVerseDamageSource::Melee ? 1 : 0;
		Killer.GadgetKills += Event.Cause == EVerseDamageSource::Gadget ? 1 : 0;
	}
	UE_LOG(LogVerse, Log, TEXT("[VerseDuel] death victim=%d killer=%d cause=%d zone=%d t=%.1f"), Event.VictimId, Event.KillerId,
		int32(Event.Cause), int32(Event.LastZone), Event.ServerTime);
}

void UVerseDuelSubsystem::HandleFire(const FVerseFireEvent& Event)
{
	++StatsFor(Event.ShooterId).Shots;
}

void UVerseDuelSubsystem::HandleHit(const FVerseHitEvent& Event)
{
	if (Event.VictimId > 0 && Event.InstigatorId != Event.VictimId)
	{
		++StatsFor(Event.InstigatorId).Hits;
	}
}

void UVerseDuelSubsystem::ResetStats()
{
	Players.Reset();
	Frames = FVerseDuelFrameStats();
	if (VerseDuelPrivate::GErrorCounter)
	{
		VerseDuelPrivate::GErrorCounter->Errors = 0;
	}
	ErrorsSeen = 0;
	SetsContinued = 0;
}

FString UVerseDuelSubsystem::StatsJson() const
{
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("schema"), TEXT("verse.duel_stats/1"));
	Root->SetStringField(TEXT("tier"), Tier.ToString());
	Root->SetBoolField(TEXT("botVsBot"), bBotVsBot);
	Root->SetBoolField(TEXT("autoplay"), bAutoplay);
	Root->SetNumberField(TEXT("matchSeconds"), GetMatchSeconds());
	Root->SetNumberField(TEXT("errors"), ErrorsSeen);
	Root->SetNumberField(TEXT("setsFinished"), SetsContinued);
	Root->SetNumberField(TEXT("frames"), Frames.Frames);
	Root->SetNumberField(TEXT("fpsAverage"), Frames.AverageFps());
	Root->SetNumberField(TEXT("fpsOnePercentLow"), Frames.OnePercentLowFps());
	Root->SetNumberField(TEXT("worstFrameMs"), Frames.WorstS * 1000.0);
	TArray<TSharedPtr<FJsonValue>> List;
	for (const TPair<int32, FVerseDuelPlayerStats>& Pair : Players)
	{
		const FVerseDuelPlayerStats& S = Pair.Value;
		TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
		P->SetNumberField(TEXT("id"), S.PlayerId);
		P->SetStringField(TEXT("name"), S.Name);
		P->SetBoolField(TEXT("bot"), S.bBot);
		P->SetNumberField(TEXT("kills"), S.Kills);
		P->SetNumberField(TEXT("deaths"), S.Deaths);
		P->SetNumberField(TEXT("headshots"), S.Headshots);
		P->SetNumberField(TEXT("finishers"), S.Finishers);
		P->SetNumberField(TEXT("knifeKills"), S.KnifeKills);
		P->SetNumberField(TEXT("gadgetKills"), S.GadgetKills);
		P->SetNumberField(TEXT("shots"), S.Shots);
		P->SetNumberField(TEXT("hits"), S.Hits);
		List.Add(MakeShared<FJsonValueObject>(P));
	}
	Root->SetArrayField(TEXT("players"), List);
	FString Out;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}

void UVerseDuelSubsystem::FinishRun()
{
	bRunFinished = true;
	const FString Json = StatsJson();
	UE_LOG(LogVerse, Display, TEXT("[VerseDuel] stats %s"), *Json);
	if (!StatsFile.IsEmpty())
	{
		IFileManager::Get().MakeDirectory(*FPaths::GetPath(StatsFile), true);
		FFileHelper::SaveStringToFile(Json, *StatsFile, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}
	if (GEngine)
	{
		GEngine->DeferredCommands.Add(TEXT("EXIT"));
	}
}

// ---------------------------------------------------------------------------------------------
// Tick

void UVerseDuelSubsystem::UpdatePerson()
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	if (bBotVsBot)
	{
		Spectate();
		return;
	}
	if (!bAutoplay)
	{
		return;
	}
	APlayerController* PC = World->GetFirstPlayerController();
	AVerseCharacter* Pawn = PC ? Cast<AVerseCharacter>(PC->GetPawn()) : nullptr;
	if (Pawn && AutoplayPawn.Get() != Pawn)
	{
		AutoplayPawn = Pawn;
		Pawn->SetInputScript(VerseDuelAutopilot::Make(Pawn, uint32(FMath::Rand())));
	}
}

void UVerseDuelSubsystem::Spectate()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	APawn* Focus = GetFocusPawn();
	if (PC && Focus && PC->GetViewTarget() != Focus)
	{
		PC->SetViewTarget(Focus);
	}
}

void UVerseDuelSubsystem::Tick(float DeltaTime)
{
	UWorld* World = GetWorld();
	if (!World || !World->HasBegunPlay())
	{
		return;
	}
	if (bStartRequested && !bDuelRunning)
	{
		if (StartAtWorldS < 0.0)
		{
			StartAtWorldS = World->GetTimeSeconds() + VerseDuelPrivate::CommandLineStartDelayS;
		}
		else if (World->GetTimeSeconds() >= StartAtWorldS)
		{
			bStartRequested = false;
			StartDuel(Tier);
		}
	}
	if (World->GetNetMode() != NM_Client)
	{
		RegisterObservers();
	}
	DressCrew(DeltaTime);
	if (!bDuelRunning)
	{
		return;
	}
	UpdatePerson();
	// Scripted runs play the endless duel on: the end-of-set screen continues by itself.
	if (bAutoplay || bBotVsBot || RunSeconds > 0.0)
	{
		if (UVerseUiSubsystem* Ui = World->GetSubsystem<UVerseUiSubsystem>(); Ui && Ui->GetScreen() == EVerseUiScreen::EndOfSet)
		{
			if (EndOfSetSinceS < 0.0)
			{
				EndOfSetSinceS = FPlatformTime::Seconds();
			}
			else if (FPlatformTime::Seconds() - EndOfSetSinceS > 1.5)
			{
				EndOfSetSinceS = -1.0;
				++SetsContinued;
				Ui->ContinueAfterSet();
			}
		}
	}
	Frames.Add(FApp::GetDeltaTime());
	// Diagnostics for the scripted runs: nav and where the duellists are, early and later.
	if (NavChecks < 2 && GetMatchSeconds() > (NavChecks == 0 ? 5.0 : 20.0))
	{
		++NavChecks;
		LogNavCheck();
	}
	if (VerseDuelPrivate::GErrorCounter)
	{
		ErrorsSeen = VerseDuelPrivate::GErrorCounter->Errors;
	}
	if (RunSeconds > 0.0 && !bRunFinished && GetMatchSeconds() >= RunSeconds)
	{
		FinishRun();
	}
}

void UVerseDuelSubsystem::LogNavCheck() const
{
	UWorld* World = GetWorld();
	UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World);
	const ARecastNavMesh* NavMesh = Nav ? Cast<ARecastNavMesh>(Nav->GetDefaultNavDataInstance(FNavigationSystem::DontCreate)) : nullptr;
	UE_LOG(LogVerse, Log, TEXT("[VerseDuel] nav check at %.0f s: nav mesh %s, %d tiles"), GetMatchSeconds(), NavMesh ? TEXT("present") : TEXT("missing"),
		NavMesh ? NavMesh->GetNavMeshTilesCount() : 0);
	TArray<APawn*> Pawns;
	for (TActorIterator<AVerseDefaultCharacter> It(World); It; ++It)
	{
		APawn* Pawn = *It;
		FNavLocation OnNav;
		const bool bOnNav = Nav && Nav->ProjectPointToNavigation(Pawn->GetActorLocation(), OnNav, FVector(100.0, 100.0, 250.0));
		UE_LOG(LogVerse, Log, TEXT("[VerseDuel]   pawn %s by %s at %s, on nav %d"), *Pawn->GetName(),
			Pawn->GetController() ? *Pawn->GetController()->GetClass()->GetName() : TEXT("nobody"), *Pawn->GetActorLocation().ToCompactString(), bOnNav ? 1 : 0);
		if (const AVerseBotController* Bot = Cast<AVerseBotController>(Pawn->GetController()))
		{
			const FVerseInputFrame& In = Bot->GetLastInputFrame();
			UE_LOG(LogVerse, Log, TEXT("[VerseDuel]     bot state %d, move (%.2f, %.2f), buttons 0x%x"), int32(Bot->GetPresentation().State), In.Move.X,
				In.Move.Y, In.Buttons);
		}
		if (Pawn->GetController())
		{
			Pawns.Add(Pawn);
		}
	}
	if (Nav && Pawns.Num() >= 2)
	{
		const UNavigationPath* Path = Nav->FindPathToLocationSynchronously(World, Pawns[0]->GetActorLocation(), Pawns[1]->GetActorLocation(), Pawns[0]);
		UE_LOG(LogVerse, Log, TEXT("[VerseDuel]   path: %s, %d points, %.0f cm"),
			Path && Path->IsValid() ? (Path->IsPartial() ? TEXT("partial") : TEXT("full")) : TEXT("none"), Path ? Path->PathPoints.Num() : 0,
			Path && Path->IsValid() ? Path->GetPathLength() : 0.0);
	}
}

TStatId UVerseDuelSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseDuelSubsystem, STATGROUP_Tickables);
}

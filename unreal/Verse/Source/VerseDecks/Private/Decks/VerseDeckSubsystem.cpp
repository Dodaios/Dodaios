#include "Decks/VerseDeckSubsystem.h"

#include "Camera/VerseDeckCamera.h"
#include "Commander/VerseDeckCommander.h"
#include "Life/VerseDeckDrone.h"
#include "Decks/VerseDeckLife.h"
#include "Decks/VerseDeckLook.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "EngineUtils.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformTime.h"
#include "Input/VerseDeckControlComponent.h"
#include "Kismet/GameplayStatics.h"
#include "Misc/CommandLine.h"
#include "Misc/DateTime.h"
#include "Misc/Parse.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Space/VerseSpaceView.h"
#include "UObject/UObjectGlobals.h"
#include "VerseLog.h"

namespace VerseDeckSubsystemPrivate
{
	/** Commander sample interval for inspection (`useWorldActions.ts` TICK_MS). */
	constexpr double SampleS = 0.5;

	FString PackageOf(const FString& LevelPath)
	{
		FString Package = LevelPath;
		int32 Dot = INDEX_NONE;
		if (Package.FindChar(TEXT('.'), Dot))
		{
			Package.LeftInline(Dot);
		}
		return Package;
	}

	FString Condensed(const TSharedRef<FJsonObject>& Root)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
			TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Root, Writer);
		return Out;
	}
}

FName UVerseDeckSubsystem::ParseStartupDeck(const TCHAR* CommandLine)
{
#if !UE_BUILD_SHIPPING
	FString Requested;
	if (FParse::Value(CommandLine, TEXT("VerseDeck="), Requested) && Verse::Decks::Find(FName(*Requested)))
	{
		return FName(*Requested);
	}
#endif
	return NAME_None;
}

void UVerseDeckSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	PlacementsDir = Verse::Decks::PlacementsDir();
	Reporter.Sink = [this](const FVerseWorldAction& Action)
	{
		UE_LOG(LogVerseDecks, Log, TEXT("world action %s"), *FVerseWorldActionReporter::ToBridgeJson(Action, TEXT("local"), FDateTime::UtcNow().ToUnixTimestampDecimal()));
		OnWorldAction.Broadcast(Action);
	};

	// Content override for every deck (parity Q-09), non-shipping only.
	StartupDeck = ParseStartupDeck(FCommandLine::Get());

	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateWeakLambda(this, [this](float)
		{
			TickDecks(Now());
			return true;
		}));
	PostLoadHandle = FCoreUObjectDelegates::PostLoadMapWithWorld.AddWeakLambda(this, [this](UWorld* World)
		{
			if (World)
			{
				OnMapLoaded(World->GetPackage()->GetName());
			}
		});
	// World Partition streams cells in as levels after arrival; their ceilings join the cutaway.
	LevelAddedHandle = FWorldDelegates::LevelAddedToWorld.AddWeakLambda(this, [this](ULevel* Level, UWorld* World)
		{
			if (Level && World && World == CurrentWorld())
			{
				AddCeilings(Level->Actors);
			}
		});
	if (GEngine)
	{
		TravelFailureHandle = GEngine->OnTravelFailure().AddWeakLambda(this, [this](UWorld*, ETravelFailure::Type, const FString& Error)
			{
				if (PendingDone)
				{
					UE_LOG(LogVerseDecks, Warning, TEXT("travel to %s failed: %s"), *PendingLevel, *Error);
					TFunction<void(bool)> Done = MoveTemp(PendingDone);
					PendingDone = nullptr;
					PendingLevel.Reset();
					Done(false);
				}
			});
	}
	RegisterQa();
}

void UVerseDeckSubsystem::Deinitialize()
{
	UnregisterQa();
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	FCoreUObjectDelegates::PostLoadMapWithWorld.Remove(PostLoadHandle);
	FWorldDelegates::LevelAddedToWorld.Remove(LevelAddedHandle);
	if (GEngine)
	{
		GEngine->OnTravelFailure().Remove(TravelFailureHandle);
	}
	PendingDone = nullptr;
	Super::Deinitialize();
}

UVerseDeckSubsystem* UVerseDeckSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	const UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
	return Instance ? Instance->GetSubsystem<UVerseDeckSubsystem>() : nullptr;
}

double UVerseDeckSubsystem::Now() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

UWorld* UVerseDeckSubsystem::CurrentWorld() const
{
	const UGameInstance* Instance = GetGameInstance();
	return Instance ? Instance->GetWorld() : nullptr;
}

const FVerseDeckManifest* UVerseDeckSubsystem::GetManifest(FName Deck)
{
	if (const FVerseDeckManifest* Cached = Manifests.Find(Deck))
	{
		return Cached;
	}
	FVerseDeckManifest Manifest;
	FString Error;
	if (!FVerseDeckManifest::Load(Deck, PlacementsDir, Manifest, Error))
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("%s"), *Error);
		return nullptr;
	}
	return &Manifests.Add(Deck, MoveTemp(Manifest));
}

bool UVerseDeckSubsystem::RequestDeck(FName Deck)
{
	if (Verse::Decks::Find(Deck) == nullptr || bLoadInFlight)
	{
		return false;
	}
	if (!Lift.Request(CurrentDeck, Deck, Now(), bReducedMotion))
	{
		return false;
	}
	for (const EVerseLiftCue Cue : Lift.TakeCues())
	{
		OnLiftCue.Broadcast(Cue);
	}
	TickDecks(Now());
	return true;
}

bool UVerseDeckSubsystem::LoadDeckDirect(FName Deck)
{
	if (Verse::Decks::Find(Deck) == nullptr || bLoadInFlight || Lift.IsBusy())
	{
		return false;
	}
	StartLoad(Deck, false);
	return true;
}

void UVerseDeckSubsystem::StartLoad(FName Deck, bool bByLift)
{
	const FVerseDeckInfo* Info = Verse::Decks::Find(Deck);
	check(Info);
	bLoadInFlight = true;
	const int32 Serial = ++LoadSerial;
	const double StartedAt = Now();
	TWeakObjectPtr<UVerseDeckSubsystem> Weak(this);
	TFunction<void(bool)> Done = [Weak, Serial, Deck, bByLift, StartedAt](bool bOk)
	{
		// A load the lift gave up on (or that was superseded) is no longer ours to finish.
		UVerseDeckSubsystem* Self = Weak.Get();
		if (Self && Self->bLoadInFlight && Self->LoadSerial == Serial)
		{
			Self->OnLoaded(Deck, bByLift, bOk, StartedAt);
		}
	};
	if (LevelLoader)
	{
		LevelLoader(*Info, MoveTemp(Done));
	}
	else
	{
		DefaultLoad(*Info, MoveTemp(Done));
	}
}

void UVerseDeckSubsystem::DefaultLoad(const FVerseDeckInfo& Deck, TFunction<void(bool)> Done)
{
	UWorld* World = CurrentWorld();
	if (World == nullptr)
	{
		Done(false);
		return;
	}
	PendingLevel = VerseDeckSubsystemPrivate::PackageOf(Deck.LevelPath);
	PendingDone = MoveTemp(Done);
	UE_LOG(LogVerseDecks, Log, TEXT("opening %s"), *PendingLevel);
	UGameplayStatics::OpenLevel(World, FName(*PendingLevel));
}

void UVerseDeckSubsystem::AbandonLoad(const TCHAR* Why)
{
	if (!bLoadInFlight && !PendingDone)
	{
		return;
	}
	UE_LOG(LogVerseDecks, Warning, TEXT("abandoning the load of %s: %s"), PendingLevel.IsEmpty() ? TEXT("(loader)") : *PendingLevel, Why);
	bLoadInFlight = false;
	++LoadSerial;
	PendingDone = nullptr;
	PendingLevel.Reset();
}

const FVerseDeckInfo* UVerseDeckSubsystem::DeckForPackage(const FString& Package)
{
	for (const FVerseDeckInfo& Info : Verse::Decks::All())
	{
		if (VerseDeckSubsystemPrivate::PackageOf(Info.LevelPath) == Package)
		{
			return &Info;
		}
	}
	return nullptr;
}

void UVerseDeckSubsystem::OnMapLoaded(const FString& Package)
{
	if (PendingDone)
	{
		TFunction<void(bool)> Done = MoveTemp(PendingDone);
		PendingDone = nullptr;
		const bool bOurs = Package == PendingLevel;
		PendingLevel.Reset();
		Done(bOurs);
		if (bOurs)
		{
			return;
		}
		UE_LOG(LogVerseDecks, Warning, TEXT("expected a deck level, %s loaded instead"), *Package);
	}
	// A map nobody waits for: a load that arrived after the lift gave up, or travel that fell back
	// to another map. When it is a deck, that deck is where the commander now is.
	const FVerseDeckInfo* Info = DeckForPackage(Package);
	if (Info && !bLoadInFlight && !LevelLoader && bStartupDone)
	{
		OnLoaded(Info->Id, false, true, Now());
	}
}

void UVerseDeckSubsystem::OnLoaded(FName Deck, bool bByLift, bool bOk, double StartedAt)
{
	bLoadInFlight = false;
	const double NowS = Now();
	if (!bOk)
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("deck %s failed to load"), *Deck.ToString());
		Lift.NotifyFailed(NowS);
		return;
	}
	CurrentDeck = Deck;
	if (bByLift)
	{
		Lift.NotifyArrived(NowS);
	}
	else
	{
		LastColdLoadS = NowS - StartedAt;
	}
	UE_LOG(LogVerseDecks, Log, TEXT("arrived on %s after %.3f s (%s)"), *Deck.ToString(), NowS - StartedAt, bByLift ? TEXT("lift") : TEXT("direct"));
	SpawnDeckActors(CurrentWorld(), Deck, bByLift);
	Reporter.NotifyArrived(Deck);
	OnDeckArrived.Broadcast(Deck, bByLift);
}

void UVerseDeckSubsystem::SpawnDeckActors(UWorld* World, FName Deck, bool bByLift)
{
	const FVerseDeckManifest* Manifest = GetManifest(Deck);
	if (World == nullptr || !World->IsGameWorld() || Manifest == nullptr)
	{
		return;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.ObjectFlags |= RF_Transient;

	AVerseDeckLighting* Lights = World->SpawnActor<AVerseDeckLighting>(Params);
	if (Lights)
	{
		Lights->Build(*Manifest);
		Lighting = Lights;
	}
	if (AVerseDeckLife* Life = World->SpawnActor<AVerseDeckLife>(Params))
	{
		Life->Build(*Manifest);
	}
	SpaceView = World->SpawnActor<AVerseSpaceView>(Params);
	if (SpaceView.IsValid())
	{
		SpaceView->SetOutward(FVerseDeckLook::For(Deck).SpaceOutward);
	}

	AVerseDeckCamera* DeckCamera = World->SpawnActor<AVerseDeckCamera>(Params);
	if (DeckCamera)
	{
		FTransform Arrival;
		if (Manifest->ArrivalTransform(bByLift, Arrival))
		{
			const FVerseDeckLook ArrivalLook = FVerseDeckLook::For(Deck);
			if (ArrivalLook.ArrivalYawDeg.IsSet())
			{
				Arrival.SetRotation(FRotator(0.0, ArrivalLook.ArrivalYawDeg.GetValue(), 0.0).Quaternion());
			}
			if (ArrivalLook.ArrivalLocationCm.IsSet())
			{
				Arrival.SetLocation(ArrivalLook.ArrivalLocationCm.GetValue());
			}
			DeckCamera->FrameArrival(Arrival, ArrivalLook.ArrivalPitchDeg);
			if (APlayerController* Controller = World->GetFirstPlayerController())
			{
				if (APawn* Pawn = Controller->GetPawn())
				{
					float Radius = 0.f;
					float HalfHeight = 0.f;
					Pawn->GetSimpleCollisionCylinder(Radius, HalfHeight);
					const FRotator Body = Arrival.Rotator() + FRotator(0.0, ArrivalLook.ArrivalBodyTurnDeg, 0.0);
					Pawn->SetActorLocationAndRotation(Arrival.GetLocation() + FVector(0.0, 0.0, HalfHeight), Body, false, nullptr, ETeleportType::TeleportPhysics);
					Controller->SetControlRotation(Arrival.Rotator());
				}
				Controller->SetViewTarget(DeckCamera);
				// The commander walks the deck under the deck's own keys and mouse (stream S5).
				if (UVerseDeckControlComponent* Control = UVerseDeckControlComponent::Ensure(Controller))
				{
					FTransform BodyArrival = Arrival;
					BodyArrival.SetRotation((Arrival.Rotator() + FRotator(0.0, ArrivalLook.ArrivalBodyTurnDeg, 0.0)).Quaternion());
					Control->OnDeckArrived(Deck, *Manifest, BodyArrival, DeckCamera);
				}
				// The companion at the commander's heel and the utility drones on their rounds.
				AVerseDeckDrone::SpawnForDeck(World, *Manifest);
			}
		}
		Camera = DeckCamera;
	}
	CollectCeilings(World);
	UpdateCutaway();
}

bool UVerseDeckSubsystem::IsCeilingActor(const AActor& Actor)
{
	for (const FName& Tag : Actor.Tags)
	{
		const FString Text = Tag.ToString();
		if (Text.StartsWith(TEXT("verse.pid:")) && Text.EndsWith(TEXT("_ceiling")))
		{
			return true;
		}
	}
	return false;
}

bool UVerseDeckSubsystem::IsBoundsActor(const AActor& Actor)
{
	for (const FName& Tag : Actor.Tags)
	{
		const FString Text = Tag.ToString();
		if (Text.StartsWith(TEXT("verse.pid:")) && Text.Contains(TEXT("_bounds_")))
		{
			return true;
		}
	}
	return false;
}

void UVerseDeckSubsystem::CollectCeilings(UWorld* World)
{
	Ceilings.Reset();
	BoundsHidden = 0;
	bCutaway = false;
	if (World == nullptr)
	{
		return;
	}
	TArray<AActor*> Actors;
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		Actors.Add(*It);
	}
	AddCeilings(Actors);
	UE_LOG(LogVerseDecks, Log, TEXT("deck %s: %d ceiling actors, %d bounds hidden"), *CurrentDeck.ToString(), Ceilings.Num(), BoundsHidden);
}

void UVerseDeckSubsystem::AddCeilings(TArrayView<AActor* const> Actors)
{
	int32 Added = 0;
	for (AActor* Actor : Actors)
	{
		if (Actor && IsBoundsActor(*Actor))
		{
			// Deck bounds are collision proxies (art-pipeline 5, Verse_ProxyOnly): never drawn in game.
			Actor->SetActorHiddenInGame(true);
			++BoundsHidden;
			continue;
		}
		if (Actor && IsCeilingActor(*Actor) && !Ceilings.Contains(TWeakObjectPtr<AActor>(Actor)))
		{
			Ceilings.Add(Actor);
			// A ceiling that streams in while the overview shows takes the current cutaway state.
			Actor->SetActorHiddenInGame(bCutaway);
			++Added;
		}
	}
	if (Added > 0 && !CurrentDeck.IsNone())
	{
		UE_LOG(LogVerseDecks, Verbose, TEXT("deck %s: %d ceiling actors streamed in"), *CurrentDeck.ToString(), Added);
	}
}

void UVerseDeckSubsystem::SetCutawayOverride(TOptional<bool> Override)
{
	CutawayOverride = Override;
	UpdateCutaway();
}

void UVerseDeckSubsystem::UpdateCutaway()
{
	const AVerseDeckCamera* DeckCamera = Camera.Get();
	const bool bWant = CutawayOverride.IsSet()
		? CutawayOverride.GetValue()
		: DeckCamera != nullptr && DeckCamera->GetView() == EVerseDeckView::Overview;
	if (bWant != bCutaway)
	{
		ApplyCutaway(bWant);
	}
}

void UVerseDeckSubsystem::ApplyCutaway(bool bOn)
{
	bCutaway = bOn;
	for (const TWeakObjectPtr<AActor>& Weak : Ceilings)
	{
		if (AActor* Ceiling = Weak.Get())
		{
			Ceiling->SetActorHiddenInGame(bOn);
		}
	}
}

void UVerseDeckSubsystem::NotifyVisible()
{
	Reporter.NotifyVisible();
}

void UVerseDeckSubsystem::NotifyCommanderFeet(const FVector& FeetCm)
{
	const FVerseDeckManifest* Manifest = CurrentDeck.IsNone() ? nullptr : GetManifest(CurrentDeck);
	if (Manifest)
	{
		Reporter.NotifyPosition(*Manifest, FeetCm, Day ? Day() : FDateTime::Now().ToString(TEXT("%Y-%m-%d")));
	}
}

void UVerseDeckSubsystem::TickDecks(double NowS)
{
	UWorld* World = CurrentWorld();
	if (!bStartupDone && World && World->IsGameWorld() && World->HasBegunPlay())
	{
		bStartupDone = true;
		if (!StartupDeck.IsNone())
		{
			LoadDeckDirect(StartupDeck);
		}
		else if (CurrentDeck.IsNone() && !LevelLoader)
		{
			// Booted straight into a deck level (the default map or a travel URL): that is the arrival.
			if (const FVerseDeckInfo* Info = DeckForPackage(World->GetPackage()->GetName()))
			{
				OnLoaded(Info->Id, false, true, NowS);
			}
		}
	}
	const bool bWasRiding = Lift.IsBusy();
	if (Lift.Tick(NowS))
	{
		StartLoad(Lift.Target(), true);
	}
	const TArray<EVerseLiftCue> Cues = Lift.TakeCues();
	if (bWasRiding && Cues.Contains(EVerseLiftCue::GaveUp))
	{
		// The doors opened without the deck (parity L-03): drop the load so the next ride can start.
		AbandonLoad(TEXT("the lift gave up"));
	}
	UpdateCutaway();
	for (const EVerseLiftCue Cue : Cues)
	{
		OnLiftCue.Broadcast(Cue);
	}
	if (!CurrentDeck.IsNone() && (LastSampleAt < 0.0 || NowS - LastSampleAt >= VerseDeckSubsystemPrivate::SampleS))
	{
		LastSampleAt = NowS;
		const APlayerController* Controller = World ? World->GetFirstPlayerController() : nullptr;
		const UVerseDeckControlComponent* Control = Controller ? Controller->FindComponentByClass<UVerseDeckControlComponent>() : nullptr;
		// On the decks the commander is the body that walks; the controller's own pawn waits for the duel.
		const APawn* Pawn = Control && Control->IsDeckActive() && Control->GetCommander() ? Control->GetCommander() : (Controller ? Controller->GetPawn() : nullptr);
		if (Pawn)
		{
			float Radius = 0.f;
			float HalfHeight = 0.f;
			Pawn->GetSimpleCollisionCylinder(Radius, HalfHeight);
			NotifyCommanderFeet(Pawn->GetActorLocation() - FVector(0.0, 0.0, HalfHeight));
		}
	}
}

FString UVerseDeckSubsystem::StateJson() const
{
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	const FVerseDeckInfo* Info = Verse::Decks::Find(CurrentDeck);
	Root->SetStringField(TEXT("deck"), CurrentDeck.IsNone() ? FString() : CurrentDeck.ToString());
	Root->SetNumberField(TEXT("number"), Info ? Info->Number : 0);
	static const TCHAR* Phases[] = { TEXT("idle"), TEXT("doors_closing"), TEXT("riding"), TEXT("doors_opening") };
	Root->SetStringField(TEXT("lift"), Phases[static_cast<int32>(Lift.Phase())]);
	Root->SetNumberField(TEXT("last_ride_s"), Lift.LastRideS());
	Root->SetNumberField(TEXT("last_load_s"), Lift.LastLoadS());
	Root->SetNumberField(TEXT("last_cold_load_s"), LastColdLoadS);
	Root->SetBoolField(TEXT("deck_missing"), Lift.DeckMissing());
	return VerseDeckSubsystemPrivate::Condensed(Root);
}

#include "Crew/VerseCrewSubsystem.h"

#include "Combat/VerseCombatTypes.h"
#include "Crew/VerseCrewPawn.h"
#include "Engine/EngineTypes.h"
#include "Engine/HitResult.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "AI/NavigationSystemBase.h"
#include "NavigationPath.h"
#include "NavigationSystem.h"
#include "CollisionQueryParams.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformTime.h"
#include "Misc/DateTime.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/UnrealType.h"
#include "VerseLog.h"

namespace VerseCrewQa
{
	// Private/QA/VerseCrewQa.cpp: registers Verse.QA.SetDuty while any crew subsystem lives.
	void AddSubsystem(UVerseCrewSubsystem* Subsystem);
	void RemoveSubsystem(UVerseCrewSubsystem* Subsystem);
}

namespace
{
	const FName CrewDeckHangar(TEXT("hangar"));
	const FName CrewDeckBridge(TEXT("bridge"));
	constexpr float CrewCapsuleHalfHeightCm = 90.f;

	bool IsUpright(EVerseCrewActivity Activity)
	{
		return Activity == EVerseCrewActivity::StandRest || Activity == EVerseCrewActivity::StandGuard || Activity == EVerseCrewActivity::StandWait
			|| Activity == EVerseCrewActivity::StandAlert || Activity == EVerseCrewActivity::Walk;
	}

	bool InsideXY(const FBox& Box, const FVector& P)
	{
		return P.X > Box.Min.X && P.X < Box.Max.X && P.Y > Box.Min.Y && P.Y < Box.Max.Y && P.Z > Box.Min.Z && P.Z < Box.Max.Z;
	}

	/** Typed Recast queries through NavigationSystemV1 (VerseCrew links NavigationSystem, change request #1167). */
	struct FNavCalls
	{
		static const FNavCalls& Get()
		{
			static FNavCalls Calls;
			return Calls;
		}

		/** The navmesh point within Extent of Point, if any. */
		bool ProjectPoint(UWorld* World, const FVector& Point, const FVector& Extent, FVector& Out) const
		{
			FNavLocation Projected;
			UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World);
			if (!Nav || !Nav->ProjectPointToNavigation(Point, Projected, Extent))
			{
				return false;
			}
			Out = Projected.Location;
			return true;
		}

		/** Recast path points between two navmesh points. */
		bool PathPoints(UWorld* World, const FVector& From, const FVector& To, TArray<FVector>& OutPoints) const
		{
			UNavigationPath* Path = UNavigationSystemV1::FindPathToLocationSynchronously(World, From, To);
			if (Path && Path->IsValid())
			{
				OutPoints = Path->PathPoints;
			}
			return OutPoints.Num() >= 2;
		}
	};
}

UVerseCrewSubsystem* UVerseCrewSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseCrewSubsystem>() : nullptr;
}

bool UVerseCrewSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void UVerseCrewSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseEventHub>();
	FString Error;
	if (!Presentation.LoadFrom(FVerseCrewPresentation::DefaultDataDir(), Error))
	{
		UE_LOG(LogVerseCrew, Warning, TEXT("Crew presentation data: %s; built-in values in use."), *Error);
	}
	if (!Tuning.LoadFrom(FVerseCrewTuning::DefaultPath(), Error))
	{
		UE_LOG(LogVerseCrew, Warning, TEXT("Crew tuning: %s; built-in values in use."), *Error);
	}
	WalkTogether.WalkCm = Tuning.WalkTogetherMetres * 100.f;
	WalkTogether.HeelCm = Tuning.HeelMetres * 100.f;
	WalkTogether.CooldownSeconds = Tuning.WalkTogetherCooldownSeconds;
	// Loaded with the world, not in the first tick that spawns a pawn.
	BodyMesh();
	BaseEpochMs = (FDateTime::UtcNow() - FDateTime(1970, 1, 1)).GetTotalMilliseconds();
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		ArenaHandle = Hub->OnArenaSwitch.AddUObject(this, &UVerseCrewSubsystem::HandleArenaSwitch);
	}
	VerseCrewQa::AddSubsystem(this);
}

void UVerseCrewSubsystem::Deinitialize()
{
	VerseCrewQa::RemoveSubsystem(this);
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		Hub->OnArenaSwitch.Remove(ArenaHandle);
	}
	const UWorld* World = GetWorld();
	if (World && !World->bIsTearingDown)
	{
		TArray<FString> Keys;
		Bodies.GetKeys(Keys);
		for (const FString& Key : Keys)
		{
			DespawnBody(Key);
		}
		if (Drone)
		{
			Drone->Destroy();
		}
		for (AVerseCrewPawn* Pooled : PawnPool)
		{
			if (Pooled)
			{
				Pooled->Destroy();
			}
		}
	}
	Bodies.Reset();
	PawnPool.Reset();
	Drone = nullptr;
	Super::Deinitialize();
}

TStatId UVerseCrewSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseCrewSubsystem, STATGROUP_Tickables);
}

int64 UVerseCrewSubsystem::GetNowMs() const
{
	return BaseEpochMs + static_cast<int64>(ClockSeconds * 1000.0);
}

FString UVerseCrewSubsystem::BodyKey(FName Deck, const FString& MemberId)
{
	return Deck.ToString() + TEXT("|") + MemberId;
}

// --- bridge in ------------------------------------------------------------------------------

bool UVerseCrewSubsystem::HandleBridgeFrame(const FString& JsonText)
{
	TSharedPtr<FJsonObject> Frame;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(JsonText);
	if (!FJsonSerializer::Deserialize(Reader, Frame) || !Frame.IsValid())
	{
		return false;
	}
	return HandleBridgeObject(Frame.ToSharedRef());
}

bool UVerseCrewSubsystem::HandleBridgeObject(const TSharedRef<FJsonObject>& Frame)
{
	FString Type;
	if (!Frame->TryGetStringField(TEXT("type"), Type))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* DataPtr = nullptr;
	const TSharedRef<FJsonObject> Data = Frame->TryGetObjectField(TEXT("data"), DataPtr) && DataPtr && DataPtr->IsValid()
		? DataPtr->ToSharedRef()
		: MakeShared<FJsonObject>();
	if (Type == TEXT("roster.snapshot") || Type == TEXT("roster.delta"))
	{
		HandleRoster(Type, Frame, Data);
		return true;
	}
	if (Type == TEXT("groups.snapshot") || Type == TEXT("groups.delta"))
	{
		HandleGroups(Type, Frame, Data);
		return true;
	}
	if (Type == TEXT("meetings.update"))
	{
		if (Meetings.ApplyMeetingUpdate(Data))
		{
			bPlanDirty = true;
		}
		return true;
	}
	if (Type == TEXT("companion.snapshot") || Type == TEXT("companion.update"))
	{
		Companion.Apply(Data);
		return true;
	}
	if (Type == TEXT("progression.awarded"))
	{
		HandleAwarded(Data);
		return true;
	}
	return false;
}

bool UVerseCrewSubsystem::AcceptSequenced(const FString& Topic, const TSharedRef<FJsonObject>& Frame, bool bSnapshot)
{
	double Seq = 0.0;
	const bool bHasSeq = Frame->TryGetNumberField(TEXT("seq"), Seq);
	if (bSnapshot)
	{
		if (bHasSeq)
		{
			LastSeq.Add(Topic, static_cast<int64>(Seq));
		}
		return true;
	}
	const int64* Last = LastSeq.Find(Topic);
	double Base = 0.0;
	if (!Last || !Frame->TryGetNumberField(TEXT("base"), Base) || static_cast<int64>(Base) != *Last)
	{
		RequestResync(Topic);
		return false;
	}
	if (bHasSeq)
	{
		LastSeq.Add(Topic, static_cast<int64>(Seq));
	}
	return true;
}

void UVerseCrewSubsystem::RequestResync(const FString& Topic)
{
	++Stats.Resyncs;
	const TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("topic"), Topic);
	SendCommand(TEXT("resync"), Data);
}

void UVerseCrewSubsystem::HandleRoster(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data)
{
	const bool bSnapshot = Type.EndsWith(TEXT(".snapshot"));
	if (!AcceptSequenced(TEXT("roster"), Frame, bSnapshot))
	{
		return;
	}
	const bool bFirst = !Roster.HasSnapshot();
	const FVerseCrewRosterChange Change = bSnapshot ? Roster.ApplySnapshot(Data) : Roster.ApplyDelta(Data);
	// Agents that join after the first snapshot arrive by shuttle (parity C-13).
	if (!bFirst)
	{
		for (const FString& Id : Change.Added)
		{
			if (!Roster.IsPane(Id))
			{
				ArrivingUntil.Add(Id, ClockSeconds + Tuning.ArrivalSeconds);
				++Stats.Arrivals;
			}
		}
	}
	for (const FString& Id : Change.Removed)
	{
		ArrivingUntil.Remove(Id);
		DutyOverrides.Remove(Id);
		if (SelectedId == Id)
		{
			SelectedId.Reset();
		}
	}
	if (!Change.IsEmpty())
	{
		bPlanDirty = true;
		// Duty changes show on the next tick, before the re-plan moves anyone.
		bDutiesDirty = true;
	}
}

void UVerseCrewSubsystem::HandleGroups(const FString& Type, const TSharedRef<FJsonObject>& Frame, const TSharedRef<FJsonObject>& Data)
{
	const bool bSnapshot = Type.EndsWith(TEXT(".snapshot"));
	if (!AcceptSequenced(TEXT("groups"), Frame, bSnapshot))
	{
		return;
	}
	if (bSnapshot)
	{
		Meetings.ApplyGroupsSnapshot(Data);
	}
	else
	{
		Meetings.ApplyGroupsDelta(Data);
	}
	bPlanDirty = true;
}

void UVerseCrewSubsystem::HandleAwarded(const TSharedRef<FJsonObject>& Data)
{
	FString Kind;
	Data->TryGetStringField(TEXT("subject_kind"), Kind);
	double Level = 0.0;
	double Previous = 0.0;
	if (Kind == TEXT("person") && Data->TryGetNumberField(TEXT("level"), Level) && Data->TryGetNumberField(TEXT("previous_level"), Previous)
		&& Presentation.RankForLevel(static_cast<int32>(Level)).Id != Presentation.RankForLevel(static_cast<int32>(Previous)).Id)
	{
		// A commander promotion: the crew salutes (parity C-19).
		SaluteUntilSeconds = ClockSeconds + Tuning.SaluteSeconds;
	}
}

// --- bridge out -----------------------------------------------------------------------------

bool UVerseCrewSubsystem::SendCommand(const FString& Type, const TSharedRef<FJsonObject>& Data, bool bOpenCommand)
{
	if (bOpenCommand)
	{
		// Open commands: 4/s (bridge-protocol.md 11). Above that the server answers
		// rate_limited; do not send what it would refuse.
		OpenCommandTimes.RemoveAll([this](double T) { return ClockSeconds - T >= 1.0; });
		if (OpenCommandTimes.Num() >= FMath::Max(1, FMath::RoundToInt(Tuning.OpenCommandsPerSecond)))
		{
			++Stats.CommandsRateLimited;
			return false;
		}
		OpenCommandTimes.Add(ClockSeconds);
	}
	++Stats.CommandsSent;
	if (Sink)
	{
		Sink(Type, Data);
	}
	return true;
}

void UVerseCrewSubsystem::SendWorldAction(const FString& Action, const FString& Ref)
{
	const TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("action"), Action);
	Data->SetStringField(TEXT("ref"), Ref);
	SendCommand(TEXT("progression.action"), Data);
}

// --- decks ----------------------------------------------------------------------------------

void UVerseCrewSubsystem::RegisterDeck(const FVerseCrewDeck& Deck)
{
	Decks.Add(Deck.Id, Deck);
	bPlanDirty = true;
}

void UVerseCrewSubsystem::SetLoadedDecks(const TArray<FName>& DeckIds)
{
	for (const FName& Old : LoadedDecks)
	{
		if (!DeckIds.Contains(Old))
		{
			// The deck left the screen: its crew goes with it.
			TArray<FString> Keys;
			for (const TPair<FString, FBody>& Pair : Bodies)
			{
				if (Pair.Value.Deck == Old)
				{
					Keys.Add(Pair.Key);
				}
			}
			for (const FString& Key : Keys)
			{
				DespawnBody(Key);
			}
			DecksPlannedOnce.Remove(Old);
			Plans.Remove(Old);
		}
	}
	LoadedDecks = DeckIds;
	bPlanDirty = true;
}

void UVerseCrewSubsystem::SetCommanderDeck(FName DeckId)
{
	CommanderDeck = DeckId;
	Briefed.Reset();
}

bool UVerseCrewSubsystem::RegisterFixtureDecks(const TMap<FName, FVector>& OriginsCm, FString& OutError)
{
	for (const TPair<FName, FVector>& Pair : OriginsCm)
	{
		FVerseCrewDeck Deck;
		if (!VerseCrew::LoadFixtureDeck(Pair.Key, Pair.Value, Deck, OutError))
		{
			return false;
		}
		RegisterDeck(Deck);
	}
	return true;
}

// --- commander ------------------------------------------------------------------------------

void UVerseCrewSubsystem::SetCommanderOverride(TOptional<FVector> Location, float HeadingDeg)
{
	CommanderOverride = Location;
	CommanderHeadingDeg = HeadingDeg;
}

FVector UVerseCrewSubsystem::GetCommanderLocation() const
{
	if (CommanderOverride.IsSet())
	{
		return CommanderOverride.GetValue();
	}
	const UWorld* World = GetWorld();
	const APlayerController* Controller = World ? World->GetFirstPlayerController() : nullptr;
	const APawn* Pawn = Controller ? Controller->GetPawn() : nullptr;
	return Pawn ? Pawn->GetActorLocation() : FVector::ZeroVector;
}

// --- arena ----------------------------------------------------------------------------------

FBox UVerseCrewSubsystem::ArenaBoundsWorld() const
{
	const FVerseCrewDeck* Hangar = Decks.Find(CrewDeckHangar);
	const FVector Origin = Hangar ? Hangar->OriginCm : FVector::ZeroVector;
	return Tuning.ArenaBoundsCm.ShiftBy(Origin);
}

void UVerseCrewSubsystem::HandleArenaSwitch(const FVerseArenaSwitchEvent& Event)
{
	if (!Event.Deck.IsNone() && Event.Deck != CrewDeckHangar)
	{
		return;
	}
	bArenaOn = Event.bArenaOn;
	if (bArenaOn)
	{
		// Retiring a pawn is cheap (it goes to the pool); the re-plan runs within the budget.
		HideCrewInArena();
	}
	bPlanDirty = true;
}

void UVerseCrewSubsystem::HideCrewInArena()
{
	const FBox Arena = ArenaBoundsWorld();
	TArray<FString> Keys;
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		const AVerseCrewPawn* Pawn = Pair.Value.Pawn.Get();
		if (Pair.Value.Deck == CrewDeckHangar && Pawn && InsideXY(Arena, Pawn->GetActorLocation()))
		{
			Keys.Add(Pair.Key);
		}
	}
	for (const FString& Key : Keys)
	{
		DespawnBody(Key);
	}
}

FVector UVerseCrewSubsystem::ClampOutOfArena(FName Deck, const FVector& Location) const
{
	if (!bArenaOn || Deck != CrewDeckHangar)
	{
		return Location;
	}
	const FBox Arena = ArenaBoundsWorld();
	if (!InsideXY(Arena, Location))
	{
		return Location;
	}
	// Push out through the nearest side.
	const float Margin = Tuning.CrewRadiusCm;
	const float ToMinX = Location.X - Arena.Min.X;
	const float ToMaxX = Arena.Max.X - Location.X;
	const float ToMinY = Location.Y - Arena.Min.Y;
	const float ToMaxY = Arena.Max.Y - Location.Y;
	const float Best = FMath::Min(FMath::Min(ToMinX, ToMaxX), FMath::Min(ToMinY, ToMaxY));
	FVector Out = Location;
	if (Best == ToMinX) Out.X = Arena.Min.X - Margin;
	else if (Best == ToMaxX) Out.X = Arena.Max.X + Margin;
	else if (Best == ToMinY) Out.Y = Arena.Min.Y - Margin;
	else Out.Y = Arena.Max.Y + Margin;
	return Out;
}

TSet<FString> UVerseCrewSubsystem::BlockedSockets(const FVerseCrewDeck& Deck) const
{
	TSet<FString> Blocked;
	if (bArenaOn && Deck.Id == CrewDeckHangar)
	{
		const FBox Arena = ArenaBoundsWorld();
		for (const FVerseCrewSocket& Socket : Deck.Sockets)
		{
			if (InsideXY(Arena, Socket.Location + FVector(0.f, 0.f, 1.f)))
			{
				Blocked.Add(Socket.Key());
			}
		}
	}
	return Blocked;
}

// --- planning -------------------------------------------------------------------------------

TArray<FVerseCrewMember> UVerseCrewSubsystem::EffectiveMembers() const
{
	TArray<FVerseCrewMember> Members = Roster.Members();
	for (FVerseCrewMember& M : Members)
	{
		if (const EVerseCrewDuty* Forced = DutyOverrides.Find(M.Id))
		{
			M.Duty = *Forced;
		}
	}
	return Members;
}

bool UVerseCrewSubsystem::EffectiveMember(const FString& Id, FVerseCrewMember& Out) const
{
	if (!Roster.FindMember(Id, Out))
	{
		return false;
	}
	if (const EVerseCrewDuty* Forced = DutyOverrides.Find(Id))
	{
		Out.Duty = *Forced;
	}
	return true;
}

void UVerseCrewSubsystem::ReplanNow()
{
	BeginPlanPass();
	while (RunOneWorkItem())
	{
	}
}

int32 UVerseCrewSubsystem::NumQueuedWork() const
{
	return PlanQueue.Num() + (SpawnQueue.Num() - SpawnQueueHead) + (PathQueue.Num() - PathQueueHead) + (bDutiesDirty ? 1 : 0)
		+ FMath::Max(0, PawnPool.Num() - Tuning.PawnPoolSize);
}

void UVerseCrewSubsystem::BeginPlanPass()
{
	++Stats.Replans;
	bPlanDirty = false;
	LastReplanSeconds = ClockSeconds;
	PassMembers = EffectiveMembers();
	PassRounds = Meetings.Rounds();
	PassNowMs = GetNowMs();
	PlanQueue = LoadedDecks;
	if (PlanQueue.Num() == 0)
	{
		FinishPlanPass();
	}
}

void UVerseCrewSubsystem::PlanDeck(FName DeckId)
{
	const FVerseCrewDeck* Deck = Decks.Find(DeckId);
	if (!Deck || !LoadedDecks.Contains(DeckId))
	{
		return;
	}
	const TSet<FString> Blocked = BlockedSockets(*Deck);
	TMap<FString, FString>& Previous = PreviousKeys.FindOrAdd(DeckId);
	const FVerseCrewDeckPlan* Last = Plans.Find(DeckId);
	FVerseCrewPlanInput Input;
	Input.Deck = Deck;
	Input.Crew = PassMembers;
	Input.Rounds = &PassRounds;
	Input.NowMs = PassNowMs;
	Input.Previous = &Previous;
	Input.Homes = Last ? &Last->Homes : nullptr;
	Input.Blocked = &Blocked;
	FVerseCrewDeckPlan Plan = VerseCrewPlanner::PlaceOnDeck(Input);
	Previous.Reset();
	for (const TPair<FString, FVerseCrewPlacement>& P : Plan.Placements)
	{
		Previous.Add(P.Key, P.Value.SocketKey);
	}
	ReconcileDeck(*Deck, Plan, PassMembers);
	Plans.Add(DeckId, MoveTemp(Plan));
	DecksPlannedOnce.Add(DeckId);
}

void UVerseCrewSubsystem::FinishPlanPass()
{
	ReconcileArrivals(PassMembers);
	bDutiesDirty = true;
}

int32 UVerseCrewSubsystem::NextWorkKind() const
{
	if (bDutiesDirty)
	{
		return 0;
	}
	if (PlanQueue.Num() > 0)
	{
		return 1;
	}
	if (SpawnQueueHead < SpawnQueue.Num())
	{
		// A new actor is its own item (the costly part); taking it from the pool is cheap.
		return PawnPool.Num() == 0 ? 5 : 2;
	}
	if (PathQueueHead < PathQueue.Num())
	{
		return 3;
	}
	if (PawnPool.Num() > Tuning.PawnPoolSize)
	{
		return 4;
	}
	return INDEX_NONE;
}

void UVerseCrewSubsystem::RunQueuedWork(double TickStartSeconds, double BudgetMs)
{
	// Items run while the tick is inside its budget. An item starts only when its predicted
	// cost (the recent worst of its kind) still fits under the hard cap, so one costly item
	// never pushes the frame over it; an item deferred for many frames runs anyway.
	bool bFirst = true;
	for (;;)
	{
		const int32 Kind = NextWorkKind();
		if (Kind == INDEX_NONE)
		{
			DeferredFrames = 0;
			break;
		}
		const double Elapsed = (FPlatformTime::Seconds() - TickStartSeconds) * 1000.0;
		if (!bFirst && Elapsed >= BudgetMs)
		{
			break;
		}
		if (Elapsed + PredictedCostMs[Kind] > Tuning.TickHardCapMs && DeferredFrames < 10)
		{
			// One costly outlier (a first spawn) must not hold the queue for long: the
			// prediction relaxes on every frame it defers.
			++DeferredFrames;
			PredictedCostMs[Kind] *= 0.8;
			break;
		}
		bFirst = false;
		DeferredFrames = 0;
		const double Start = FPlatformTime::Seconds();
		RunOneWorkItem();
		const double Ms = (FPlatformTime::Seconds() - Start) * 1000.0;
		PredictedCostMs[Kind] = FMath::Max(Ms, PredictedCostMs[Kind] * 0.9);
	}
}

bool UVerseCrewSubsystem::RunOneWorkItem()
{
	if (SpawnQueueHead < SpawnQueue.Num() && PawnPool.Num() == 0 && !bDutiesDirty && PlanQueue.Num() == 0)
	{
		const double Start = FPlatformTime::Seconds();
		if (AVerseCrewPawn* Fresh = NewPooledPawn())
		{
			PawnPool.Add(Fresh);
		}
		else
		{
			// No actor: drop the head of the queue so it cannot block the rest.
			SpawnBodyNow(SpawnQueue[SpawnQueueHead++]);
		}
		Stats.MaxSpawnMs = FMath::Max(Stats.MaxSpawnMs, (FPlatformTime::Seconds() - Start) * 1000.0);
		return true;
	}
	if (bDutiesDirty)
	{
		// Duty looks first: cheap, and what the person sees change.
		bDutiesDirty = false;
		RefreshDuties(EffectiveMembers());
		return true;
	}
	if (PlanQueue.Num() > 0)
	{
		const double Start = FPlatformTime::Seconds();
		const FName DeckId = PlanQueue[0];
		PlanQueue.RemoveAt(0);
		PlanDeck(DeckId);
		if (PlanQueue.Num() == 0)
		{
			FinishPlanPass();
		}
		Stats.MaxPlanDeckMs = FMath::Max(Stats.MaxPlanDeckMs, (FPlatformTime::Seconds() - Start) * 1000.0);
		return true;
	}
	if (SpawnQueueHead < SpawnQueue.Num())
	{
		const FString Key = SpawnQueue[SpawnQueueHead++];
		if (SpawnQueueHead >= SpawnQueue.Num())
		{
			SpawnQueue.Reset();
			SpawnQueueHead = 0;
		}
		SpawnBodyNow(Key);
		return true;
	}
	if (PathQueueHead < PathQueue.Num())
	{
		const FPathJob Job = PathQueue[PathQueueHead++];
		if (PathQueueHead >= PathQueue.Num())
		{
			PathQueue.Reset();
			PathQueueHead = 0;
		}
		BuildPathNow(Job.Key, Job.Serial);
		return true;
	}
	if (PawnPool.Num() > Tuning.PawnPoolSize)
	{
		if (AVerseCrewPawn* Extra = PawnPool.Pop(EAllowShrinking::No))
		{
			Extra->Destroy();
		}
		return true;
	}
	return false;
}

void UVerseCrewSubsystem::ReconcileDeck(const FVerseCrewDeck& Deck, const FVerseCrewDeckPlan& Plan, const TArray<FVerseCrewMember>& Members)
{
	const bool bDeckOpening = !DecksPlannedOnce.Contains(Deck.Id);
	const FVerseCrewSocket* Lift = Deck.Lift();
	TSet<FString> Ids;
	for (const FVerseCrewMember& M : Members)
	{
		Ids.Add(M.Id);
	}
	for (const TPair<FString, FVerseCrewPlacement>& Pair : Plan.Placements)
	{
		if (!Ids.Contains(Pair.Key) || !Deck.Sockets.IsValidIndex(Pair.Value.SocketIndex))
		{
			continue;
		}
		const FVerseCrewSocket& Socket = Deck.Sockets[Pair.Value.SocketIndex];
		const FVector Goal = Socket.Location + FVector(0.f, 0.f, CrewCapsuleHalfHeightCm);
		const FString Key = BodyKey(Deck.Id, Pair.Key);
		FBody* Body = Bodies.Find(Key);
		if (!Body)
		{
			// Members on the deck when it opens stand in place; later ones come by lift (parity C-14).
			const bool bPlaced = bDeckOpening || !Lift;
			const FVector Start = bPlaced ? Goal : Lift->Location + FVector(0.f, 0.f, CrewCapsuleHalfHeightCm);
			Body = &AddBody(Key, Pair.Key, Deck.Id, ClampOutOfArena(Deck.Id, Start), bPlaced ? Socket.HeadingDeg : Lift->HeadingDeg);
		}
		if (Body->Goal != EGoal::Socket || Body->SocketKey != Pair.Value.SocketKey || Body->GoalActivity != Pair.Value.Intent.Activity
			|| Body->bFaceCommander != Pair.Value.Intent.bFaceCommander)
		{
			SetBodyGoal(*Body, EGoal::Socket, Goal, Socket.HeadingDeg, Pair.Value.Intent.Activity, Pair.Value.Intent.bFaceCommander, Pair.Value.SocketKey);
		}
	}
	// Bodies on this deck without a placement: leave by the lift (parity C-15).
	TArray<FString> Gone;
	for (TPair<FString, FBody>& Pair : Bodies)
	{
		FBody& Body = Pair.Value;
		if (Body.Deck != Deck.Id || Body.Goal == EGoal::Arrive || Body.Goal == EGoal::Scripted || Plan.Placements.Contains(Body.MemberId))
		{
			continue;
		}
		if (Body.Goal == EGoal::Leave)
		{
			continue;
		}
		if (!Lift || Body.bSpawnPending)
		{
			Gone.Add(Pair.Key);
			continue;
		}
		SetBodyGoal(Body, EGoal::Leave, Lift->Location + FVector(0.f, 0.f, CrewCapsuleHalfHeightCm), Lift->HeadingDeg, EVerseCrewActivity::Walk, false, Lift->Key());
	}
	for (const FString& Key : Gone)
	{
		DespawnBody(Key);
	}
}

void UVerseCrewSubsystem::ReconcileArrivals(const TArray<FVerseCrewMember>& Members)
{
	for (auto It = ArrivingUntil.CreateIterator(); It; ++It)
	{
		if (ClockSeconds >= It.Value())
		{
			It.RemoveCurrent();
		}
	}
	if (ArrivingUntil.Num() == 0)
	{
		return;
	}
	const FVerseCrewDeck* Hangar = Decks.Find(CrewDeckHangar);
	if (!Hangar || !LoadedDecks.Contains(CrewDeckHangar))
	{
		UE_LOG(LogVerseCrew, Verbose, TEXT("%d newcomer(s) skip the shuttle: the hangar is not loaded."), ArrivingUntil.Num());
		return;
	}
	const FVerseCrewSocket* Spawn = Hangar->ArrivalSpawn();
	const FVerseCrewSocket* Lift = Hangar->Lift();
	if (!Spawn || !Lift)
	{
		UE_LOG(LogVerseCrew, Warning, TEXT("The hangar has no %s socket; newcomers skip the shuttle."), Spawn ? TEXT("lift") : TEXT("spawn"));
		return;
	}
	const FVector SpawnAt = Spawn->Location + FVector(0.f, 0.f, CrewCapsuleHalfHeightCm);
	if (bArenaOn && InsideXY(ArenaBoundsWorld(), SpawnAt))
	{
		// The shuttle stands in the arena while it is on: the newcomer takes the lift directly.
		return;
	}
	const FVerseCrewDeckPlan* Plan = Plans.Find(CrewDeckHangar);
	for (const FVerseCrewMember& M : Members)
	{
		if (!ArrivingUntil.Contains(M.Id) || (Plan && Plan->Placements.Contains(M.Id)))
		{
			continue;
		}
		const FString Key = BodyKey(CrewDeckHangar, M.Id);
		if (Bodies.Contains(Key))
		{
			continue;
		}
		UE_LOG(LogVerseCrew, Log, TEXT("Newcomer %s comes off the shuttle and walks to the lift."), *M.Id);
		FBody& Body = AddBody(Key, M.Id, CrewDeckHangar, SpawnAt, Spawn->HeadingDeg);
		SetBodyGoal(Body, EGoal::Arrive, Lift->Location + FVector(0.f, 0.f, CrewCapsuleHalfHeightCm), Lift->HeadingDeg, EVerseCrewActivity::Walk, false, Lift->Key());
	}
}

bool UVerseCrewSubsystem::IsArriving(const FString& MemberId) const
{
	return ArrivingUntil.Contains(MemberId);
}

USkeletalMesh* UVerseCrewSubsystem::BodyMesh()
{
	if (!bBodyMeshTried)
	{
		bBodyMeshTried = true;
		if (!Tuning.BodyMesh.IsEmpty())
		{
			CachedBodyMesh = LoadObject<USkeletalMesh>(nullptr, *Tuning.BodyMesh, nullptr, LOAD_NoWarn | LOAD_Quiet);
		}
	}
	return CachedBodyMesh;
}

UVerseCrewSubsystem::FBody& UVerseCrewSubsystem::AddBody(const FString& Key, const FString& MemberId, FName Deck, const FVector& Location, float HeadingDeg)
{
	FBody& Body = Bodies.Add(Key);
	Body.MemberId = MemberId;
	Body.Deck = Deck;
	Body.PaceCmS = VerseCrew::WalkPaceCmPerSecond(MemberId);
	Body.LastProgressSeconds = ClockSeconds;
	Body.bSpawnPending = true;
	Body.SpawnLocation = Location;
	Body.SpawnHeading = HeadingDeg;
	SpawnQueue.Add(Key);
	return Body;
}

void UVerseCrewSubsystem::SpawnBodyNow(const FString& Key)
{
	FBody* Body = Bodies.Find(Key);
	if (!Body || !Body->bSpawnPending)
	{
		return;
	}
	const double Start = FPlatformTime::Seconds();
	FVerseCrewMember Member;
	if (Body->ScriptedMember.IsSet())
	{
		Member = Body->ScriptedMember.GetValue();
	}
	else if (!EffectiveMember(Body->MemberId, Member))
	{
		// Left the roster while waiting for its pawn.
		Bodies.Remove(Key);
		return;
	}
	AVerseCrewPawn* Pawn = SpawnPawn(Member, ClampOutOfArena(Body->Deck, Body->SpawnLocation), Body->SpawnHeading);
	if (!Pawn)
	{
		UE_LOG(LogVerseCrew, Warning, TEXT("Crew member %s could not be spawned on %s."), *Body->MemberId, *Body->Deck.ToString());
		Bodies.Remove(Key);
		return;
	}
	Body->Pawn = Pawn;
	Body->bSpawnPending = false;
	Body->LastProgressSeconds = ClockSeconds;
	// Placed at its socket: it sits, types or sleeps from its first frame.
	Pawn->SetActivity(Body->bArrived ? Body->GoalActivity : EVerseCrewActivity::StandRest, Tuning);
	Stats.MaxSpawnMs = FMath::Max(Stats.MaxSpawnMs, (FPlatformTime::Seconds() - Start) * 1000.0);
}

AVerseCrewPawn* UVerseCrewSubsystem::SpawnPawn(const FVerseCrewMember& Member, const FVector& Location, float HeadingDeg)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	AVerseCrewPawn* Pawn = nullptr;
	while (!Pawn && PawnPool.Num() > 0)
	{
		AVerseCrewPawn* Pooled = PawnPool.Pop(EAllowShrinking::No);
		if (IsValid(Pooled))
		{
			Pawn = Pooled;
		}
	}
	if (Pawn)
	{
		Pawn->SetActorLocationAndRotation(Location, FRotator(0.f, HeadingDeg, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
		Pawn->SetActorHiddenInGame(false);
		Pawn->SetActorEnableCollision(true);
		++Stats.PoolReuses;
	}
	else
	{
		Pawn = NewPooledPawn();
		if (!Pawn)
		{
			return nullptr;
		}
		Pawn->SetActorLocationAndRotation(Location, FRotator(0.f, HeadingDeg, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
		Pawn->SetActorHiddenInGame(false);
		Pawn->SetActorEnableCollision(true);
	}
	Pawn->SetupMember(Member, Presentation.LookOf(Member), BodyMesh(), Tuning);
	Pawn->ApplyDuty(Presentation.DutyLook(Member.Duty));
	Pawn->SetSelected(SelectedId == Member.Id);
	++Stats.Spawned;
	return Pawn;
}

AVerseCrewPawn* UVerseCrewSubsystem::NewPooledPawn()
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return nullptr;
	}
	// Deferred, so the body mesh is set before the components register (once, not twice).
	const FTransform Xf(FRotator::ZeroRotator, FVector(0.f, 0.f, -100000.f));
	AVerseCrewPawn* Pawn = World->SpawnActorDeferred<AVerseCrewPawn>(AVerseCrewPawn::StaticClass(), Xf, nullptr, nullptr,
		ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
	if (!Pawn)
	{
		return nullptr;
	}
	Pawn->SetFlags(RF_Transient);
	if (USkeletalMesh* Mesh = BodyMesh())
	{
		Pawn->Body->SetSkeletalMeshAsset(Mesh);
	}
	Pawn->SetActorHiddenInGame(true);
	Pawn->FinishSpawning(Xf);
	Pawn->SetActorEnableCollision(false);
	return Pawn;
}

void UVerseCrewSubsystem::DespawnBody(const FString& Key)
{
	FBody Body;
	if (!Bodies.RemoveAndCopyValue(Key, Body))
	{
		return;
	}
	if (AVerseCrewPawn* Pawn = Body.Pawn.Get())
	{
		// Hidden and kept for the next spawn; RunOneWorkItem destroys what exceeds the pool.
		Pawn->SetSelected(false);
		Pawn->SetActorHiddenInGame(true);
		Pawn->SetActorEnableCollision(false);
		PawnPool.Add(Pawn);
	}
	++Stats.Despawned;
}

void UVerseCrewSubsystem::SetBodyGoal(FBody& Body, EGoal Goal, const FVector& Location, float HeadingDeg, EVerseCrewActivity Activity, bool bFace,
	const FString& SocketKey)
{
	Body.Goal = Goal;
	Body.GoalLocation = Location;
	Body.GoalHeading = HeadingDeg;
	Body.GoalActivity = Activity;
	Body.bFaceCommander = bFace;
	Body.SocketKey = SocketKey;
	Body.BestDistanceCm = TNumericLimits<float>::Max();
	Body.LastProgressSeconds = ClockSeconds;
	Body.bStuckReported = false;
	Body.Path.Reset();
	Body.PathIndex = 0;
	++Body.GoalSerial;
	const AVerseCrewPawn* Pawn = Body.Pawn.Get();
	const FVector From = Pawn ? Pawn->GetActorLocation() : Body.SpawnLocation;
	Body.bArrived = FVector::Dist2D(From, Location) <= Tuning.ArriveToleranceCm && (Goal == EGoal::Socket || Goal == EGoal::Scripted);
	Body.bPathPending = !Body.bArrived;
	if (Body.bPathPending)
	{
		// The path query runs from the work queue, within the tick budget.
		PathQueue.Add({ BodyKey(Body.Deck, Body.MemberId), Body.GoalSerial });
	}
}

void UVerseCrewSubsystem::BuildPathNow(const FString& Key, uint32 Serial)
{
	FBody* Body = Bodies.Find(Key);
	if (!Body || !Body->bPathPending || Body->GoalSerial != Serial)
	{
		return;
	}
	const double Start = FPlatformTime::Seconds();
	const AVerseCrewPawn* Pawn = Body->Pawn.Get();
	BuildPath(*Body, Pawn ? Pawn->GetActorLocation() : Body->SpawnLocation);
	Body->bPathPending = false;
	Body->BestDistanceCm = TNumericLimits<float>::Max();
	Body->LastProgressSeconds = ClockSeconds;
	Stats.MaxPathMs = FMath::Max(Stats.MaxPathMs, (FPlatformTime::Seconds() - Start) * 1000.0);
}

bool UVerseCrewSubsystem::HasNavigation() const
{
	const UWorld* World = GetWorld();
	const UNavigationSystemBase* Nav = World ? World->GetNavigationSystem() : nullptr;
	return Nav && Nav->GetMainNavData() != nullptr;
}

bool UVerseCrewSubsystem::FindNavPath(const FVector& FromCm, const FVector& ToCm, TArray<FVector>& OutPoints) const
{
	const TCHAR* Reason = nullptr;
	return FindNavPathWhy(FromCm, ToCm, OutPoints, Reason);
}

bool UVerseCrewSubsystem::FindNavPathWhy(const FVector& FromCm, const FVector& ToCm, TArray<FVector>& OutPoints, const TCHAR*& OutReason) const
{
	OutPoints.Reset();
	OutReason = TEXT("no navmesh");
	if (!HasNavigation())
	{
		return false;
	}
	UWorld* World = GetWorld();
	const FNavCalls& Calls = FNavCalls::Get();
	const FVector Up(0.f, 0.f, CrewCapsuleHalfHeightCm);
	// A bed or a console can cover more floor than the usual extent: one wider try.
	auto Project = [&](const FVector& Point, FVector& Out) {
		return Calls.ProjectPoint(World, Point - Up, Tuning.NavProjectExtentCm, Out)
			|| Calls.ProjectPoint(World, Point - Up, Tuning.NavProjectExtentCm * FVector(2.f, 2.f, 1.f), Out);
	};
	FVector From;
	FVector To;
	if (!Project(FromCm, From))
	{
		OutReason = TEXT("start is off the navmesh");
		return false;
	}
	if (!Project(ToCm, To))
	{
		OutReason = TEXT("goal is off the navmesh");
		return false;
	}
	TArray<FVector> Points;
	if (!Calls.PathPoints(World, From, To, Points))
	{
		OutReason = TEXT("no path");
		return false;
	}
	// A partial path (ends short of the goal) is no path.
	if (FVector::Dist2D(Points.Last(), To) > Tuning.CrewRadiusCm)
	{
		OutReason = TEXT("partial path");
		return false;
	}
	for (const FVector& P : Points)
	{
		OutPoints.Add(P + Up);
	}
	OutReason = nullptr;
	return true;
}

bool UVerseCrewSubsystem::StraightLineClear(const FVector& From, const FVector& To) const
{
	const UWorld* World = GetWorld();
	if (!World)
	{
		return true;
	}
	// A slimmer capsule lifted off the floor: steps and the floor itself do not count, walls do.
	const float HalfHeight = 50.f;
	const FVector Lift(0.f, 0.f, 20.f);
	FCollisionQueryParams Query(SCENE_QUERY_STAT(VerseCrewStraightLine), false);
	return !World->SweepTestByObjectType(From + Lift, To + Lift, FQuat::Identity, FCollisionObjectQueryParams(ECC_WorldStatic),
		FCollisionShape::MakeCapsule(Tuning.CrewRadiusCm * 0.8f, HalfHeight), Query);
}

void UVerseCrewSubsystem::BuildPath(FBody& Body, const FVector& From)
{
	Body.Path.Reset();
	Body.PathIndex = 0;
	if (HasNavigation())
	{
		TArray<FVector> Nav;
		const TCHAR* Why = nullptr;
		if (FindNavPathWhy(From, Body.GoalLocation, Nav, Why))
		{
			for (int32 I = 1; I < Nav.Num(); ++I)
			{
				Body.Path.Add(Nav[I]);
			}
			Body.Path.Last() = Body.GoalLocation;
			++Stats.NavPaths;
			return;
		}
		++NavWarnings;
		if (NavWarnings <= 5 || NavWarnings % 100 == 0)
		{
			UE_LOG(LogVerseCrew, Warning, TEXT("No nav path for %s on %s from %s to %s: %s (%d so far)."), *Body.MemberId, *Body.Deck.ToString(),
				*From.ToCompactString(), *Body.GoalLocation.ToCompactString(), Why ? Why : TEXT("?"), NavWarnings);
		}
	}
	else
	{
		++Stats.NavMissing;
		if (!bNavMissingLogged)
		{
			bNavMissingLogged = true;
			UE_LOG(LogVerseCrew, Log, TEXT("No navmesh in this world: crew walks straight lines where they are clear of geometry."));
		}
	}
	Body.Path.Add(Body.GoalLocation);
	if (StraightLineClear(From, Body.GoalLocation))
	{
		++Stats.NavFallbacks;
		return;
	}
	// Never walk through a wall: place the member at its goal instead.
	++Stats.NavBlocked;
	UE_LOG(LogVerseCrew, Warning, TEXT("%s on %s: no nav path and the straight line is blocked; placed at its goal."), *Body.MemberId, *Body.Deck.ToString());
	if (AVerseCrewPawn* Pawn = Body.Pawn.Get())
	{
		Pawn->SetActorLocation(Body.GoalLocation, false, nullptr, ETeleportType::TeleportPhysics);
	}
	Body.bArrived = true;
}

void UVerseCrewSubsystem::RefreshDuties(const TArray<FVerseCrewMember>& Members)
{
	TMap<FString, EVerseCrewDuty> Duty;
	for (const FVerseCrewMember& M : Members)
	{
		Duty.Add(M.Id, M.Duty);
	}
	for (TPair<FString, FBody>& Pair : Bodies)
	{
		AVerseCrewPawn* Pawn = Pair.Value.Pawn.Get();
		const EVerseCrewDuty* D = Duty.Find(Pair.Value.MemberId);
		if (Pawn && D && (Pawn->Duty != *D || Pawn->GetDutyLook().LabelKey.IsEmpty()))
		{
			Pawn->ApplyDuty(Presentation.DutyLook(*D));
		}
	}
}

bool UVerseCrewSubsystem::SpawnScriptedWalker(const FString& Id, FName Deck, const FVector& StartCm, const FVector& GoalCm)
{
	const FString Key = BodyKey(Deck, Id);
	if (Bodies.Contains(Key) || Roster.Contains(Id))
	{
		return false;
	}
	FVerseCrewMember Member;
	Member.Id = Id;
	Member.Name = Id;
	FBody& Body = AddBody(Key, Id, Deck, StartCm, (GoalCm - StartCm).Rotation().Yaw);
	Body.ScriptedMember = Member;
	SetBodyGoal(Body, EGoal::Scripted, GoalCm, (GoalCm - StartCm).Rotation().Yaw, EVerseCrewActivity::StandRest, false, FString());
	return true;
}

bool UVerseCrewSubsystem::HasArrived(const FString& MemberId) const
{
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		if (Pair.Value.MemberId == MemberId && Pair.Value.Pawn.IsValid())
		{
			return Pair.Value.bArrived;
		}
	}
	return false;
}

// --- tick -----------------------------------------------------------------------------------

void UVerseCrewSubsystem::Tick(float DeltaSeconds)
{
	const double Start = FPlatformTime::Seconds();
	ClockSeconds += DeltaSeconds;
	if ((bPlanDirty || ClockSeconds - LastReplanSeconds >= Tuning.ReplanSeconds) && PlanQueue.Num() == 0)
	{
		BeginPlanPass();
	}
	StepBodies(DeltaSeconds);
	StepCompanion(DeltaSeconds);
	if (ClockSeconds - LastWorldActionSeconds >= Tuning.WorldActionTickSeconds)
	{
		LastWorldActionSeconds = ClockSeconds;
		StepWorldActions();
	}
	RunQueuedWork(Start, Tuning.TickBudgetMs);
	const int32 Queued = NumQueuedWork();
	Stats.PeakQueuedWork = FMath::Max(Stats.PeakQueuedWork, Queued);
	Stats.TicksWithBacklog += Queued > 0 ? 1 : 0;
	const double Ms = (FPlatformTime::Seconds() - Start) * 1000.0;
	Stats.LastTickMs = Ms;
	Stats.MaxTickMs = FMath::Max(Stats.MaxTickMs, Ms);
	Stats.TotalTickMs += Ms;
	++Stats.Ticks;
}

void UVerseCrewSubsystem::StepBodies(float DeltaSeconds)
{
	if (DeltaSeconds <= 0.f)
	{
		return;
	}
	struct FMover
	{
		FBody* Body;
		AVerseCrewPawn* Pawn;
		FVector Location;
		FRotator Rotation;
		EVerseCrewActivity Activity;
		bool bMoved;
		bool bWalking;
		bool bFinished;
		/** Jammed for a while: squeezes past others until it moves again. */
		bool bStalled;
	};
	TArray<FMover> Movers;
	Movers.Reserve(Bodies.Num());
	TArray<FString> Finished;
	for (TPair<FString, FBody>& Pair : Bodies)
	{
		if (Pair.Value.bSpawnPending)
		{
			continue;
		}
		AVerseCrewPawn* Pawn = Pair.Value.Pawn.Get();
		if (!Pawn)
		{
			Finished.Add(Pair.Key);
			continue;
		}
		Movers.Add({ &Pair.Value, Pawn, Pawn->GetActorLocation(), Pawn->GetActorRotation(), Pair.Value.GoalActivity, false, false, false, false });
	}
	const FVector Commander = GetCommanderLocation();
	const bool bSalute = ClockSeconds < SaluteUntilSeconds;
	const float Radius = Tuning.CrewRadiusCm;
	for (int32 I = 0; I < Movers.Num(); ++I)
	{
		FMover& M = Movers[I];
		FBody& Body = *M.Body;
		FVector Location = M.Location;
		FRotator Rotation = M.Rotation;
		EVerseCrewActivity Activity = Body.GoalActivity;
		bool bMoved = false;
		if (Body.bPathPending)
		{
			// Standing until the work queue computes its path; that wait is not "stuck".
			Body.LastProgressSeconds = ClockSeconds;
			Activity = M.Pawn->Activity;
		}
		else if (!Body.bArrived && Body.Path.Num() > 0)
		{
			const FVector Target = Body.Path[FMath::Min(Body.PathIndex, Body.Path.Num() - 1)];
			FVector ToTarget = Target - Location;
			ToTarget.Z = 0.f;
			const float Dist = ToTarget.Size();
			const float FinalDist = FVector::Dist2D(Location, Body.GoalLocation);
			FVector Desired = Dist > KINDA_SMALL_NUMBER ? ToTarget / Dist * Body.PaceCmS : FVector::ZeroVector;
			// Crowd avoidance: separation from the other bodies on the deck, with a keep-right
			// bias so two walkers on one line pass instead of stalling. It fades out on the last
			// metre so neighbouring seats can still be reached.
			if (FinalDist > 100.f)
			{
				FVector Push = FVector::ZeroVector;
				float Follow = 1.f;
				const FVector Ahead = Desired.GetSafeNormal();
				for (int32 J = 0; J < Movers.Num(); ++J)
				{
					if (J == I || Movers[J].Body->Deck != Body.Deck)
					{
						continue;
					}
					FVector Away = Location - Movers[J].Location;
					Away.Z = 0.f;
					const float D = Away.Size();
					if (D < 3.f * Radius && D > KINDA_SMALL_NUMBER)
					{
						const float Strength = (3.f * Radius - D) / (3.f * Radius);
						const bool bInFront = FVector::DotProduct(-Away / D, Ahead) > 0.5f;
						const FVector Other = Movers[J].Body->Velocity.GetSafeNormal2D();
						const bool bSameWay = !Movers[J].Body->bArrived && FVector::DotProduct(Other, Ahead) > 0.3f;
						if (bInFront && bSameWay)
						{
							// Someone walking the same way just ahead: fall in behind, do not swerve.
							Follow = FMath::Min(Follow, FMath::Clamp((D - 2.f * Radius) / Radius, 0.2f, 1.f));
							continue;
						}
						Push += Away / D * Strength;
						if (bInFront)
						{
							// Oncoming or standing in the way: pass on the right.
							Push += FVector(-Ahead.Y, Ahead.X, 0.f) * 0.5f * Strength;
						}
					}
				}
				// A walker jammed in a doorway long enough squeezes through instead of pushing back.
				M.bStalled = ClockSeconds - Body.LastProgressSeconds > Tuning.YieldSeconds;
				if (M.bStalled)
				{
					Push *= 0.25f;
					Follow = 1.f;
					if (!Body.bYielding)
					{
						Body.bYielding = true;
						++Stats.CrowdYields;
					}
				}
				else
				{
					Body.bYielding = false;
				}
				Desired = Desired * Follow + Push * Body.PaceCmS * Tuning.SeparationGain;
				Desired = Desired.GetClampedToMaxSize(Body.PaceCmS * 1.25f);
			}
			const float Step = Desired.Size() * DeltaSeconds;
			if (Dist <= FMath::Max(Step, Tuning.ArriveToleranceCm) && Body.PathIndex >= Body.Path.Num() - 1)
			{
				Location = Body.GoalLocation;
				Body.bArrived = true;
			}
			else if (Dist <= FMath::Max(Step, Tuning.ArriveToleranceCm))
			{
				Location = FVector(Target.X, Target.Y, Location.Z);
				++Body.PathIndex;
			}
			else
			{
				Location += Desired * DeltaSeconds;
				Location.Z = FMath::FInterpTo(Location.Z, Target.Z, DeltaSeconds, 4.f);
			}
			Location = ClampOutOfArena(Body.Deck, Location);
			Body.Velocity = Desired;
			if (!Desired.IsNearlyZero())
			{
				Rotation = FMath::RInterpTo(Rotation, FRotator(0.f, Desired.Rotation().Yaw, 0.f), DeltaSeconds, 8.f);
			}
			Activity = Body.bArrived ? Body.GoalActivity : EVerseCrewActivity::Walk;
			bMoved = true;
			M.bWalking = !Body.bArrived;
			// Stuck watch: progress along the path within StuckSeconds. A nav path may lead away
			// from the goal around a wall, so what is left to walk is measured along the path.
			float Remaining = 0.f;
			if (!Body.bArrived)
			{
				const int32 Next = FMath::Min(Body.PathIndex, Body.Path.Num() - 1);
				Remaining = FVector::Dist2D(Location, Body.Path[Next]);
				for (int32 P = Next; P + 1 < Body.Path.Num(); ++P)
				{
					Remaining += FVector::Dist2D(Body.Path[P], Body.Path[P + 1]);
				}
			}
			if (Remaining < Body.BestDistanceCm - 5.f)
			{
				Body.BestDistanceCm = Remaining;
				Body.LastProgressSeconds = ClockSeconds;
			}
			else if (!Body.bStuckReported && ClockSeconds - Body.LastProgressSeconds > Tuning.StuckSeconds)
			{
				Body.bStuckReported = true;
				++Stats.StuckEvents;
				UE_LOG(LogVerseCrew, Warning, TEXT("Crew member %s made no progress for %.1f s at %s (%.0f cm of path left, point %d of %d); placing it at its goal."),
					*Body.MemberId, Tuning.StuckSeconds, *Location.ToCompactString(), Remaining, Body.PathIndex, Body.Path.Num());
				Location = Body.GoalLocation;
				Body.bArrived = true;
				M.bWalking = false;
			}
		}
		if (Body.bArrived)
		{
			if (Body.Goal == EGoal::Leave || Body.Goal == EGoal::Arrive)
			{
				if (Body.Goal == EGoal::Arrive)
				{
					// Reported aboard: it took the lift and does not arrive again.
					ArrivingUntil.Remove(Body.MemberId);
				}
				M.bFinished = true;
				Finished.Add(BodyKey(Body.Deck, Body.MemberId));
			}
			else
			{
				float Yaw = Body.GoalHeading;
				if (Body.bFaceCommander)
				{
					const FVector To = Commander - Location;
					if (!To.IsNearlyZero())
					{
						Yaw = To.Rotation().Yaw;
					}
				}
				const FRotator Want(0.f, Yaw, 0.f);
				if (!Rotation.Equals(Want, 0.5f))
				{
					Rotation = FMath::RInterpTo(Rotation, Want, DeltaSeconds, 6.f);
					bMoved = true;
				}
				Activity = bSalute && Body.GoalActivity != EVerseCrewActivity::Sleep ? EVerseCrewActivity::StandGuard : Body.GoalActivity;
			}
		}
		M.Location = Location;
		M.Rotation = Rotation;
		M.Activity = Activity;
		M.bMoved = bMoved;
	}
	// No capsule overlap (parity C-18): push walking capsules out of each other and out of
	// standing ones. Two goals closer than a capsule (neighbouring seats, the lift) cannot both
	// be held apart, so such pairs keep the soft avoidance above only.
	const float MinGap = 2.f * Radius;
	for (int32 Pass = 0; Pass < 4; ++Pass)
	{
		bool bPushed = false;
		for (int32 I = 0; I < Movers.Num(); ++I)
		{
			FMover& A = Movers[I];
			if (A.bFinished)
			{
				continue;
			}
			for (int32 J = I + 1; J < Movers.Num(); ++J)
			{
				FMover& B = Movers[J];
				if (B.bFinished || (!A.bWalking && !B.bWalking) || A.Body->Deck != B.Body->Deck)
				{
					continue;
				}
				// Seated and sleeping crew are in their chair or bunk, furniture the navmesh
				// already keeps walkers off; only upright bodies stand in the walkway.
				if ((!A.bWalking && !IsUpright(A.Activity)) || (!B.bWalking && !IsUpright(B.Activity)) || A.bStalled || B.bStalled)
				{
					continue;
				}
				FVector Apart = A.Location - B.Location;
				Apart.Z = 0.f;
				const float D = Apart.Size();
				if (D >= MinGap)
				{
					continue;
				}
				const FVector GoalA = A.bWalking ? A.Body->GoalLocation : A.Location;
				const FVector GoalB = B.bWalking ? B.Body->GoalLocation : B.Location;
				if (FVector::Dist2D(GoalA, GoalB) < MinGap)
				{
					continue;
				}
				const FVector Dir = D > KINDA_SMALL_NUMBER ? Apart / D : FVector(((I + J) & 1) ? 1.f : -1.f, 0.f, 0.f);
				const float Overlap = MinGap - D + 0.1f;
				if (A.bWalking && B.bWalking)
				{
					A.Location += Dir * (0.5f * Overlap);
					B.Location -= Dir * (0.5f * Overlap);
				}
				else if (A.bWalking)
				{
					A.Location += Dir * Overlap;
				}
				else
				{
					B.Location -= Dir * Overlap;
				}
				A.bMoved = A.bMoved || A.bWalking;
				B.bMoved = B.bMoved || B.bWalking;
				bPushed = true;
			}
		}
		if (!bPushed)
		{
			break;
		}
	}
	for (FMover& M : Movers)
	{
		if (M.bFinished)
		{
			continue;
		}
		if (M.bMoved)
		{
			if (M.bWalking)
			{
				M.Location = ClampOutOfArena(M.Body->Deck, M.Location);
			}
			M.Pawn->SetActorLocationAndRotation(M.Location, M.Rotation, false, nullptr, ETeleportType::TeleportPhysics);
		}
		M.Pawn->SetActivity(M.Activity, Tuning);
		M.Pawn->UpdateBeacon(ClockSeconds);
	}
	for (const FString& Key : Finished)
	{
		DespawnBody(Key);
	}
}

void UVerseCrewSubsystem::StepCompanion(float DeltaSeconds)
{
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	if (!Companion.IsActive())
	{
		if (Drone)
		{
			Drone->Destroy();
			Drone = nullptr;
		}
		return;
	}
	const FVector Commander = GetCommanderLocation();
	float Heading = CommanderHeadingDeg;
	if (!CommanderOverride.IsSet())
	{
		const APlayerController* Controller = World->GetFirstPlayerController();
		if (const APawn* Pawn = Controller ? Controller->GetPawn() : nullptr)
		{
			Heading = Pawn->GetActorRotation().Yaw;
		}
	}
	const FRotator Facing(0.f, Heading, 0.f);
	const FVector Heel = Commander + Facing.RotateVector(FVector(Tuning.CompanionHeelOffsetCm.X, Tuning.CompanionHeelOffsetCm.Y, 0.f))
		+ FVector(0.f, 0.f, Tuning.CompanionHoverCm - CrewCapsuleHalfHeightCm);
	if (!Drone)
	{
		FActorSpawnParameters Params;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		Params.ObjectFlags |= RF_Transient;
		Drone = World->SpawnActor<AVerseCompanionDrone>(AVerseCompanionDrone::StaticClass(), Heel, Facing, Params);
		if (!Drone)
		{
			return;
		}
	}
	Drone->PetId = Companion.PetId;
	Drone->Look = Companion.Look;
	const FVector Now = Drone->GetActorLocation();
	const FVector To = Heel - Now;
	const float Dist = To.Size();
	if (Dist < 1.f)
	{
		return;
	}
	// Cruise at the drone's pace, faster the further behind it is, so it stays at heel even
	// when the commander sprints (parity C-21).
	const float Speed = FMath::Clamp(Tuning.CompanionPaceCmS + Dist * 8.f, Tuning.CompanionPaceCmS, Tuning.CompanionMaxCmS);
	const FVector Next = Dist <= Speed * DeltaSeconds ? Heel : Now + To / Dist * Speed * DeltaSeconds;
	Drone->SetActorLocationAndRotation(Next, FRotator(0.f, To.Rotation().Yaw, 0.f), false, nullptr, ETeleportType::TeleportPhysics);
}

void UVerseCrewSubsystem::StepWorldActions()
{
	const FVector Commander = GetCommanderLocation();
	FVector DroneAt;
	const bool bDrone = Drone && Companion.IsActive();
	if (bDrone)
	{
		DroneAt = Drone->GetActorLocation();
	}
	if (WalkTogether.Sample(Commander, bDrone ? &DroneAt : nullptr, ClockSeconds))
	{
		SendWorldAction(TEXT("walk_together"), FString());
	}
	// team_briefing: a team round running while the commander is on the bridge, once per round.
	const TArray<FString> Running = Meetings.RunningGroups();
	for (auto It = Briefed.CreateIterator(); It; ++It)
	{
		if (!Running.Contains(*It))
		{
			It.RemoveCurrent();
		}
	}
	if (CommanderDeck == CrewDeckBridge)
	{
		for (const FString& Group : Running)
		{
			if (!Briefed.Contains(Group))
			{
				Briefed.Add(Group);
				SendWorldAction(TEXT("team_briefing"), Group);
			}
		}
	}
}

// --- interaction ----------------------------------------------------------------------------

bool UVerseCrewSubsystem::ClickMember(const FString& MemberId)
{
	if (!Roster.Contains(MemberId))
	{
		return false;
	}
	if (SelectedId != MemberId)
	{
		ClearSelection();
		SelectedId = MemberId;
		for (const TPair<FString, FBody>& Pair : Bodies)
		{
			if (Pair.Value.MemberId == MemberId && Pair.Value.Pawn.IsValid())
			{
				Pair.Value.Pawn->SetSelected(true);
			}
		}
		return true;
	}
	// Second click on the selected member opens it in the app (bridge-protocol.md 11).
	const TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	if (Roster.IsPane(MemberId))
	{
		Data->SetStringField(TEXT("pane_id"), MemberId);
		return SendCommand(TEXT("pane.open"), Data, true);
	}
	Data->SetStringField(TEXT("agent_id"), MemberId);
	return SendCommand(TEXT("agent.open"), Data, true);
}

bool UVerseCrewSubsystem::ClickActor(const AActor* Actor)
{
	const AVerseCrewPawn* Pawn = Cast<AVerseCrewPawn>(Actor);
	return Pawn ? ClickMember(Pawn->MemberId) : false;
}

bool UVerseCrewSubsystem::ClickUnderCursor(APlayerController* Controller)
{
	if (!Controller)
	{
		return false;
	}
	FHitResult Hit;
	// Visibility: walls block the trace, so a member behind a wall is never picked (parity V-16).
	if (!Controller->GetHitResultUnderCursor(ECC_Visibility, false, Hit))
	{
		return false;
	}
	return ClickActor(Hit.GetActor());
}

void UVerseCrewSubsystem::ClearSelection()
{
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		if (Pair.Value.Pawn.IsValid() && Pair.Value.Pawn->bSelected)
		{
			Pair.Value.Pawn->SetSelected(false);
		}
	}
	SelectedId.Reset();
}

// --- QA and state ---------------------------------------------------------------------------

void UVerseCrewSubsystem::SetDutyOverride(const FString& MemberId, TOptional<EVerseCrewDuty> Duty)
{
	if (Duty.IsSet())
	{
		DutyOverrides.Add(MemberId, Duty.GetValue());
	}
	else
	{
		DutyOverrides.Remove(MemberId);
	}
	bPlanDirty = true;
	bDutiesDirty = true;
}

AVerseCrewPawn* UVerseCrewSubsystem::FindPawn(const FString& MemberId) const
{
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		if (Pair.Value.MemberId == MemberId && Pair.Value.Pawn.IsValid())
		{
			return Pair.Value.Pawn.Get();
		}
	}
	return nullptr;
}

TArray<AVerseCrewPawn*> UVerseCrewSubsystem::GetPawns() const
{
	TArray<AVerseCrewPawn*> Out;
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		if (Pair.Value.Pawn.IsValid())
		{
			Out.Add(Pair.Value.Pawn.Get());
		}
	}
	return Out;
}

AVerseCompanionDrone* UVerseCrewSubsystem::GetDrone() const
{
	return Drone;
}

TSharedRef<FJsonObject> UVerseCrewSubsystem::DumpJson() const
{
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	TArray<TSharedPtr<FJsonValue>> Crew;
	for (const TPair<FString, FBody>& Pair : Bodies)
	{
		const AVerseCrewPawn* Pawn = Pair.Value.Pawn.Get();
		if (!Pawn)
		{
			continue;
		}
		const TSharedRef<FJsonObject> Row = MakeShared<FJsonObject>();
		const FVector L = Pawn->GetActorLocation();
		Row->SetStringField(TEXT("id"), Pawn->MemberId);
		Row->SetStringField(TEXT("deck"), Pair.Value.Deck.ToString());
		Row->SetStringField(TEXT("duty"), VerseCrew::DutyName(Pawn->Duty));
		Row->SetStringField(TEXT("raw_duty"), Roster.RawDuty(Pawn->MemberId));
		Row->SetStringField(TEXT("activity"), VerseCrew::ActivityName(Pawn->Activity));
		Row->SetStringField(TEXT("socket"), Pair.Value.SocketKey);
		Row->SetStringField(TEXT("rank"), Pawn->RankId);
		Row->SetStringField(TEXT("uniform"), Pawn->Uniform);
		Row->SetNumberField(TEXT("beacon"), static_cast<double>(static_cast<uint8>(Pawn->Beacon)));
		Row->SetBoolField(TEXT("arrived"), Pair.Value.bArrived);
		Row->SetArrayField(TEXT("location"), { MakeShared<FJsonValueNumber>(L.X), MakeShared<FJsonValueNumber>(L.Y), MakeShared<FJsonValueNumber>(L.Z) });
		Row->SetNumberField(TEXT("yaw"), Pawn->GetActorRotation().Yaw);
		Crew.Add(MakeShared<FJsonValueObject>(Row));
	}
	Root->SetArrayField(TEXT("crew"), Crew);
	Root->SetNumberField(TEXT("agents"), Roster.NumAgents());
	Root->SetNumberField(TEXT("panes"), Roster.NumPanes());
	Root->SetBoolField(TEXT("arena_on"), bArenaOn);
	Root->SetStringField(TEXT("companion"), Companion.IsActive() ? Companion.PetId : FString());
	return Root;
}

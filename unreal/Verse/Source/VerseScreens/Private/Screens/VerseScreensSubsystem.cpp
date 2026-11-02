#include "Screens/VerseScreensSubsystem.h"

#include "Cells/VerseTerminalGrid.h"
#include "Dom/JsonValue.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformTime.h"
#include "Screens/VerseChatTailScreenComponent.h"
#include "Screens/VerseTerminalMonitorComponent.h"
#include "Stations/VerseCommandLink.h"
#include "Stations/VerseStationSubsystem.h"
#include "VerseLog.h"

namespace
{
	constexpr float WatchIntervalS = 0.5f;

	/** Adds the elapsed game-thread time to a counter when it goes out of scope. */
	struct FWorkTimer
	{
		double& Sink;
		double Start;
		explicit FWorkTimer(double& InSink) : Sink(InSink), Start(FPlatformTime::Seconds()) {}
		~FWorkTimer() { Sink += FPlatformTime::Seconds() - Start; }
	};

	double ReadNumber(const FJsonObject& O, const TCHAR* Field, double Fallback)
	{
		double V = Fallback;
		O.TryGetNumberField(Field, V);
		return V;
	}
}

UVerseScreensSubsystem* UVerseScreensSubsystem::Get(const UObject* WorldContext)
{
	if (!WorldContext || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseScreensSubsystem>() : nullptr;
}

void UVerseScreensSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Collection.InitializeDependency<UVerseStationSubsystem>();
	Super::Initialize(Collection);
}

void UVerseScreensSubsystem::Deinitialize()
{
	++Generation;
	Monitors.Reset();
	ChatScreens.Reset();
	RefToPane.Reset();
	Super::Deinitialize();
}

IVerseCommandLink* UVerseScreensSubsystem::Link() const
{
	const UWorld* World = GetWorld();
	const UVerseStationSubsystem* Stations = World ? World->GetSubsystem<UVerseStationSubsystem>() : nullptr;
	return Stations ? Stations->GetLink() : nullptr;
}

void UVerseScreensSubsystem::RegisterMonitor(UVerseTerminalMonitorComponent* Monitor)
{
	Monitors.AddUnique(Monitor);
}

void UVerseScreensSubsystem::UnregisterMonitor(UVerseTerminalMonitorComponent* Monitor)
{
	Monitors.Remove(Monitor);
}

void UVerseScreensSubsystem::RegisterChatScreen(UVerseChatTailScreenComponent* Screen)
{
	ChatScreens.AddUnique(Screen);
}

void UVerseScreensSubsystem::UnregisterChatScreen(UVerseChatTailScreenComponent* Screen)
{
	ChatScreens.Remove(Screen);
}

int32 UVerseScreensSubsystem::AddTakeoverTarget(UVerseTerminalMonitorComponent* Monitor)
{
	UWorld* World = GetWorld();
	UVerseStationSubsystem* Stations = World ? World->GetSubsystem<UVerseStationSubsystem>() : nullptr;
	if (!Stations || !Monitor)
	{
		return INDEX_NONE;
	}
	TWeakObjectPtr<UVerseTerminalMonitorComponent> Weak(Monitor);
	TWeakObjectPtr<UVerseScreensSubsystem> Self(this);
	TWeakObjectPtr<UVerseStationSubsystem> WeakStations(Stations);
	FVerseUseTarget Target;
	Target.Owner = Monitor->GetOwner();
	Target.Location = [Weak]() { return Weak.IsValid() ? Weak->GetComponentLocation() : FVector::ZeroVector; };
	Target.CanUse = [Weak, Self]() { return Weak.IsValid() && Self.IsValid() && Weak->OffersTakeover() && Self->Link() != nullptr; };
	Target.Label = [Weak, WeakStations]()
	{
		if (Weak.IsValid() && !Weak->GetPaneTitle().IsEmpty())
		{
			return Weak->GetPaneTitle();
		}
		return WeakStations.IsValid() ? WeakStations->Localize(TEXT("verse.takeover.title"), TEXT("Terminal")) : FString(TEXT("Terminal"));
	};
	Target.Action = [WeakStations]()
	{
		return WeakStations.IsValid() ? WeakStations->Localize(TEXT("verse.takeover.action"), TEXT("Take over the terminal"))
									  : FString(TEXT("Take over the terminal"));
	};
	Target.Use = [Weak, Self](int32)
	{
		if (Weak.IsValid() && Self.IsValid())
		{
			Self->RequestTakeover(Weak.Get());
		}
	};
	return Stations->AddUseTarget(MoveTemp(Target));
}

TArray<FVerseWatchEntry> UVerseScreensSubsystem::PlanWatch(TConstArrayView<FVerseWatchCandidate> Candidates, const FVector& ViewLocation,
	const FVector& ViewDirection, const FVerseWatchSettings& S)
{
	TMap<FString, FVerseWatchEntry> Nearest;
	const FVector Dir = ViewDirection.GetSafeNormal();
	for (const FVerseWatchCandidate& C : Candidates)
	{
		if (C.PaneId.IsEmpty())
		{
			continue;
		}
		const FVector To = C.Location - ViewLocation;
		const double D = To.Size();
		if (D > S.ViewDistanceCm)
		{
			continue;
		}
		const bool bInFront = D < 150.0 || Dir.IsNearlyZero() || FVector::DotProduct(To / D, Dir) > 0.0;
		const int32 FullHz = FMath::Clamp(S.MaxHz, 1, 10);
		const int32 Hz = (D <= S.NearDistanceCm && bInFront) ? FullHz : FMath::Clamp(S.FarHz, 1, FullHz);
		FVerseWatchEntry* Have = Nearest.Find(C.PaneId);
		if (!Have || D < Have->DistanceCm)
		{
			FVerseWatchEntry E;
			E.PaneId = C.PaneId;
			E.Hz = Have ? FMath::Max(Have->Hz, Hz) : Hz;
			E.DistanceCm = D;
			Nearest.Add(C.PaneId, E);
		}
		else
		{
			Have->Hz = FMath::Max(Have->Hz, Hz);
		}
	}
	TArray<FVerseWatchEntry> Out;
	Nearest.GenerateValueArray(Out);
	Out.Sort([](const FVerseWatchEntry& A, const FVerseWatchEntry& B)
	{
		return A.DistanceCm != B.DistanceCm ? A.DistanceCm < B.DistanceCm : A.PaneId < B.PaneId;
	});
	if (Out.Num() > S.MaxPanes)
	{
		Out.SetNum(FMath::Max(0, S.MaxPanes));
	}
	return Out;
}

void UVerseScreensSubsystem::ApplyWelcome(const FJsonObject& WelcomeData)
{
	const TSharedPtr<FJsonObject>* Limits = nullptr;
	if (WelcomeData.TryGetObjectField(TEXT("limits"), Limits) && Limits)
	{
		WatchSettings.MaxPanes = FMath::Clamp(int32(ReadNumber(**Limits, TEXT("screens_max_panes"), 8)), 0, 8);
		WatchSettings.MaxHz = FMath::Clamp(int32(ReadNumber(**Limits, TEXT("screens_max_hz"), 10)), 1, 10);
		MaxChatAgents = FMath::Clamp(int32(ReadNumber(**Limits, TEXT("chat_tails_max_agents"), 6)), 0, 6);
	}
}

void UVerseScreensSubsystem::SetViewOverride(const FVector& Location, const FVector& Direction)
{
	bViewOverride = true;
	OverrideLocation = Location;
	OverrideDirection = Direction;
}

bool UVerseScreensSubsystem::ReadView(FVector& OutLocation, FVector& OutDirection) const
{
	if (bViewOverride)
	{
		OutLocation = OverrideLocation;
		OutDirection = OverrideDirection;
		return true;
	}
	const UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC)
	{
		return false;
	}
	FRotator Rot;
	PC->GetPlayerViewPoint(OutLocation, Rot);
	OutDirection = Rot.Vector();
	return true;
}

FString UVerseScreensSubsystem::PaneForRef(uint16 Ref) const
{
	const FString* Pane = RefToPane.Find(Ref);
	return Pane ? *Pane : FString();
}

TArray<UVerseTerminalMonitorComponent*> UVerseScreensSubsystem::MonitorsFor(const FString& PaneId) const
{
	TArray<UVerseTerminalMonitorComponent*> Out;
	for (const TWeakObjectPtr<UVerseTerminalMonitorComponent>& M : Monitors)
	{
		if (M.IsValid() && M->ShownPaneId() == PaneId)
		{
			Out.Add(M.Get());
		}
	}
	return Out;
}

void UVerseScreensSubsystem::UpdateWatch()
{
	IVerseCommandLink* L = Link();
	FVector View;
	FVector Dir;
	if (!L || !ReadView(View, Dir))
	{
		return;
	}
	// Terminal monitors.
	TArray<FVerseWatchCandidate> Candidates;
	for (const TWeakObjectPtr<UVerseTerminalMonitorComponent>& M : Monitors)
	{
		if (M.IsValid() && !M->ShownPaneId().IsEmpty())
		{
			Candidates.Add({M->ShownPaneId(), M->GetComponentLocation()});
		}
	}
	const TArray<FVerseWatchEntry> Plan = PlanWatch(Candidates, View, Dir, WatchSettings);
	if (Plan != LastSent)
	{
		if (bWatchInFlight)
		{
			bWatchStale = true;
		}
		else
		{
			TArray<TSharedPtr<FJsonValue>> Panes;
			for (const FVerseWatchEntry& E : Plan)
			{
				TSharedRef<FJsonObject> P = MakeShared<FJsonObject>();
				P->SetStringField(TEXT("pane_id"), E.PaneId);
				P->SetNumberField(TEXT("hz"), E.Hz);
				Panes.Add(MakeShared<FJsonValueObject>(P));
			}
			TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
			Data->SetArrayField(TEXT("panes"), Panes);
			LastSent = Plan;
			bWatchInFlight = true;
			bWatchStale = false;
			++Counters.WatchesSent;
			TWeakObjectPtr<UVerseScreensSubsystem> Self(this);
			const int32 Gen = Generation;
			L->SendCommand(TEXT("screens.watch"), Data, [Self, Gen, Plan](const FVerseCommandReply& Reply)
			{
				if (Self.IsValid() && Self->Generation == Gen)
				{
					Self->HandleWatchReply(Plan, Reply);
				}
			});
		}
	}

	// Chat consoles: nearest owners first, at most chat_tails_max_agents.
	TArray<TPair<double, FString>> Owners;
	for (const TWeakObjectPtr<UVerseChatTailScreenComponent>& C : ChatScreens)
	{
		if (C.IsValid() && !C->AgentId.IsEmpty())
		{
			const double D = FVector::Dist(C->GetComponentLocation(), View);
			if (D <= WatchSettings.ViewDistanceCm)
			{
				Owners.Add({D, C->AgentId});
			}
		}
	}
	Owners.Sort([](const TPair<double, FString>& A, const TPair<double, FString>& B) { return A.Key != B.Key ? A.Key < B.Key : A.Value < B.Value; });
	TArray<FString> Agents;
	for (const TPair<double, FString>& O : Owners)
	{
		if (Agents.Num() >= MaxChatAgents)
		{
			break;
		}
		Agents.AddUnique(O.Value);
	}
	if (Agents != LastChatSent)
	{
		TArray<TSharedPtr<FJsonValue>> Values;
		for (const FString& A : Agents)
		{
			Values.Add(MakeShared<FJsonValueString>(A));
		}
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("agents"), Values);
		LastChatSent = Agents;
		++Counters.ChatWatchesSent;
		L->SendCommand(TEXT("chat_tails.watch"), Data, [](const FVerseCommandReply& Reply)
		{
			if (!Reply.bOk)
			{
				UE_LOG(LogVerseScreens, Warning, TEXT("chat_tails.watch failed: %s"), *Reply.ErrorCode);
			}
		});
	}
}

void UVerseScreensSubsystem::HandleWatchReply(const TArray<FVerseWatchEntry>& Sent, const FVerseCommandReply& Reply)
{
	bWatchInFlight = false;
	if (Reply.bOk && Reply.Result.IsValid())
	{
		RefToPane.Reset();
		const TArray<TSharedPtr<FJsonValue>>* Bound = nullptr;
		TSet<FString> BoundPanes;
		if (Reply.Result->TryGetArrayField(TEXT("bound"), Bound))
		{
			for (const TSharedPtr<FJsonValue>& V : *Bound)
			{
				const TSharedPtr<FJsonObject>* O = nullptr;
				FString Pane;
				double Ref = 0;
				if (V.IsValid() && V->TryGetObject(O) && (*O)->TryGetStringField(TEXT("pane_id"), Pane) && (*O)->TryGetNumberField(TEXT("ref"), Ref))
				{
					RefToPane.Add(uint16(Ref), Pane);
					BoundPanes.Add(Pane);
				}
			}
		}
		const TArray<TSharedPtr<FJsonValue>>* Missing = nullptr;
		TSet<FString> MissingPanes;
		if (Reply.Result->TryGetArrayField(TEXT("missing"), Missing))
		{
			for (const TSharedPtr<FJsonValue>& V : *Missing)
			{
				MissingPanes.Add(V.IsValid() ? V->AsString() : FString());
			}
		}
		for (const TWeakObjectPtr<UVerseTerminalMonitorComponent>& M : Monitors)
		{
			if (!M.IsValid())
			{
				continue;
			}
			const FString Pane = M->ShownPaneId();
			const FVerseWatchEntry* Entry = Sent.FindByPredicate([&Pane](const FVerseWatchEntry& E) { return E.PaneId == Pane; });
			M->WatchHz = (Entry && BoundPanes.Contains(Pane)) ? Entry->Hz : 0;
			if (MissingPanes.Contains(Pane))
			{
				M->ShowVacant();
			}
		}
	}
	else
	{
		UE_LOG(LogVerseScreens, Warning, TEXT("screens.watch failed: %s %s"), *Reply.ErrorCode, *Reply.ErrorMessage);
	}
	if (bWatchStale)
	{
		bWatchStale = false;
		UpdateWatch();
	}
}

void UVerseScreensSubsystem::HandleLinkReset()
{
	++Generation;
	RefToPane.Reset();
	ResyncInFlight.Reset();
	LastSent.Reset();
	LastChatSent.Reset();
	bWatchInFlight = false;
	bWatchStale = false;
	bTakeoverInFlight = false;
	for (const TWeakObjectPtr<UVerseTerminalMonitorComponent>& M : Monitors)
	{
		if (M.IsValid())
		{
			M->WatchHz = 0;
		}
	}
}

void UVerseScreensSubsystem::RequestResync(const FString& PaneId)
{
	IVerseCommandLink* L = Link();
	if (!L || ResyncInFlight.Contains(PaneId))
	{
		return;
	}
	ResyncInFlight.Add(PaneId);
	++Counters.Resyncs;
	TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("topic"), TEXT("screens"));
	Data->SetStringField(TEXT("pane_id"), PaneId);
	TWeakObjectPtr<UVerseScreensSubsystem> Self(this);
	const int32 Gen = Generation;
	L->SendCommand(TEXT("resync"), Data, [Self, Gen, PaneId](const FVerseCommandReply& Reply)
	{
		if (!Reply.bOk && Self.IsValid() && Self->Generation == Gen)
		{
			Self->ResyncInFlight.Remove(PaneId);
		}
	});
}

void UVerseScreensSubsystem::ApplyToPane(const FString& PaneId, FVerseCellFrame&& Frame)
{
	TArray<UVerseTerminalMonitorComponent*> Targets = MonitorsFor(PaneId);
	if (Targets.Num() == 0)
	{
		return;
	}
	const bool bSnapshot = Frame.Kind == EVerseCellsKind::Snapshot;
	bool bResync = false;
	bool bApplied = false;
	for (int32 I = 0; I < Targets.Num(); ++I)
	{
		FVerseCellFrame Copy = (I + 1 < Targets.Num()) ? Frame : MoveTemp(Frame);
		if (Targets[I]->ApplyFrame(MoveTemp(Copy)) == FVerseTerminalGrid::EApply::Applied)
		{
			bApplied = true;
		}
		else
		{
			bResync = true;
		}
	}
	if (bApplied)
	{
		++Counters.FramesApplied;
		if (bSnapshot)
		{
			ResyncInFlight.Remove(PaneId);
		}
	}
	if (bResync)
	{
		RequestResync(PaneId);
	}
}

void UVerseScreensSubsystem::HandleBridgeBinary(TConstArrayView<uint8> Bytes)
{
	FWorkTimer Timer(Counters.WorkSeconds);
	Counters.BytesIn += uint64(Bytes.Num());
	++Counters.FramesIn;
	FVerseCellFrame Frame;
	FString Error;
	if (!VerseCells::DecodeBinary(Bytes, Frame, Error))
	{
		++Counters.Rejected;
		UE_LOG(LogVerseScreens, Verbose, TEXT("cells.bin/1 frame rejected: %s"), *Error);
		return;
	}
	const FString* Pane = RefToPane.Find(Frame.Ref);
	if (!Pane)
	{
		++Counters.UnknownRefs;
		return;
	}
	ApplyToPane(*Pane, MoveTemp(Frame));
}

void UVerseScreensSubsystem::HandleBridgeFrame(const FJsonObject& Envelope)
{
	FWorkTimer Timer(Counters.WorkSeconds);
	FString Type;
	Envelope.TryGetStringField(TEXT("type"), Type);
	const TSharedPtr<FJsonObject>* DataPtr = nullptr;
	if (!Envelope.TryGetObjectField(TEXT("data"), DataPtr) || !DataPtr || !DataPtr->IsValid())
	{
		return;
	}
	const FJsonObject& Data = **DataPtr;
	FString Pane;
	Data.TryGetStringField(TEXT("pane_id"), Pane);
	if (Type == TEXT("screens.frame"))
	{
		++Counters.FramesIn;
		FVerseCellFrame Frame;
		FString Error;
		const uint32 Seq = uint32(ReadNumber(Envelope, TEXT("seq"), 0));
		const uint32 Base = uint32(ReadNumber(Envelope, TEXT("base"), 0));
		if (!VerseCells::DecodeJson(Data, Seq, Base, Frame, Error))
		{
			++Counters.Rejected;
			UE_LOG(LogVerseScreens, Verbose, TEXT("cells.json/1 frame rejected: %s"), *Error);
			return;
		}
		for (UVerseTerminalMonitorComponent* M : MonitorsFor(Pane))
		{
			if (Frame.Kind == EVerseCellsKind::Snapshot)
			{
				M->ApplyMeta(Frame.Style, Frame.bCut);
			}
		}
		ApplyToPane(Pane, MoveTemp(Frame));
	}
	else if (Type == TEXT("screens.meta"))
	{
		FString Style;
		bool bCut = false;
		Data.TryGetStringField(TEXT("style"), Style);
		Data.TryGetBoolField(TEXT("cut"), bCut);
		double Ref = 0;
		if (Data.TryGetNumberField(TEXT("ref"), Ref) && !Pane.IsEmpty())
		{
			RefToPane.Add(uint16(Ref), Pane);
		}
		for (UVerseTerminalMonitorComponent* M : MonitorsFor(Pane))
		{
			M->ApplyMeta(Style, bCut);
		}
	}
	else if (Type == TEXT("screens.gone"))
	{
		for (UVerseTerminalMonitorComponent* M : MonitorsFor(Pane))
		{
			M->ShowVacant();
		}
		ResyncInFlight.Remove(Pane);
	}
	else if (Type == TEXT("chat_tails.update"))
	{
		for (const TWeakObjectPtr<UVerseChatTailScreenComponent>& C : ChatScreens)
		{
			if (C.IsValid())
			{
				C->ApplyUpdate(Data);
			}
		}
	}
	else if (Type == TEXT("welcome"))
	{
		ApplyWelcome(Data);
	}
}

int32 UVerseScreensSubsystem::RedrawDirty(double Now)
{
	FWorkTimer Timer(Counters.WorkSeconds);
	int32 Done = 0;
	const int32 N = Monitors.Num();
	for (int32 K = 0; K < N && Done < MaxRedrawsPerFrame; ++K)
	{
		const int32 I = (RedrawCursor + K) % N;
		UVerseTerminalMonitorComponent* M = Monitors[I].Get();
		if (!M || !M->NeedsRedraw(Now))
		{
			continue;
		}
		// Far monitors repaint at their watch rate (2 Hz), near ones as soon as something changed.
		if (M->WatchHz > 0 && M->WatchHz < 10 && M->LastRedrawTime() >= 0.0 && Now - M->LastRedrawTime() < 1.0 / double(M->WatchHz))
		{
			continue;
		}
		Counters.RowsDrawn += M->Redraw(Now, Scratch);
		++Counters.Redraws;
		++Done;
		RedrawCursor = (I + 1) % FMath::Max(1, N);
	}
	for (const TWeakObjectPtr<UVerseChatTailScreenComponent>& C : ChatScreens)
	{
		if (Done >= MaxRedrawsPerFrame)
		{
			break;
		}
		if (C.IsValid() && C->NeedsRedraw())
		{
			Counters.RowsDrawn += C->Redraw(Scratch);
			++Counters.Redraws;
			++Done;
		}
	}
	return Done;
}

bool UVerseScreensSubsystem::RequestTakeover(UVerseTerminalMonitorComponent* Monitor)
{
	IVerseCommandLink* L = Link();
	if (!L || !Monitor || !Monitor->OffersTakeover() || bTakeoverInFlight)
	{
		return false;
	}
	const double Start = FPlatformTime::Seconds();
	bTakeoverInFlight = true;
	TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("pane_id"), Monitor->ShownPaneId());
	TWeakObjectPtr<UVerseScreensSubsystem> Self(this);
	const int32 Gen = Generation;
	L->SendCommand(TEXT("ide.focus_terminal"), Data, [Self, Gen, Start](const FVerseCommandReply& Reply)
	{
		if (!Self.IsValid() || Self->Generation != Gen)
		{
			return;
		}
		Self->bTakeoverInFlight = false;
		IVerseCommandLink* Now = Self->Link();
		if (Reply.bOk)
		{
			if (Now)
			{
				Now->ReturnToApp(TEXT("station"));
			}
			Self->TakeoverMs = (FPlatformTime::Seconds() - Start) * 1000.0;
		}
		else if (UVerseStationSubsystem* Stations = Self->GetWorld() ? Self->GetWorld()->GetSubsystem<UVerseStationSubsystem>() : nullptr)
		{
			// Shown once, never retried: the person presses again if they want to (A16.5).
			Stations->PostNotice(Stations->ErrorText(Reply.ErrorCode));
		}
	});
	return true;
}

void UVerseScreensSubsystem::Tick(float DeltaTime)
{
	SinceWatch += DeltaTime;
	if (SinceWatch >= WatchIntervalS)
	{
		SinceWatch = 0.f;
		UpdateWatch();
	}
	RedrawDirty(FPlatformTime::Seconds());
}

TStatId UVerseScreensSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseScreensSubsystem, STATGROUP_Tickables);
}

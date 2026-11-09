#include "DeckHud/VerseDeckHudSubsystem.h"

#include "Core/VerseUiSubsystem.h"
#include "DeckHud/SVerseDeckHud.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/PlayerController.h"
#include "Lift/SVerseLift.h"
#include "Loading/SVerseLoadingScreen.h"
#include "ServiceRecord/VerseServiceRecordSubsystem.h"
#include "VerseLog.h"

namespace
{
	// Above the HUD and the menus (20), under the service record (40) and its notice (45).
	constexpr int32 HudZOrder = 12;
	constexpr int32 LiftZOrder = 30;
	constexpr int32 DoorsZOrder = 60;
	constexpr int32 LoadingZOrder = 90;
	/** The deck is taken for shown this long after play began even when no view exists (a bare test world). */
	constexpr double FirstFrameGraceSeconds = 5.0;
}

UVerseDeckHudSubsystem* UVerseDeckHudSubsystem::Get(const UObject* WorldContextObject)
{
	const UWorld* World = GEngine ? GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull) : nullptr;
	return World ? World->GetSubsystem<UVerseDeckHudSubsystem>() : nullptr;
}

bool UVerseDeckHudSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE)
		&& !IsRunningDedicatedServer() && World->GetNetMode() != NM_DedicatedServer && Super::ShouldCreateSubsystem(Outer);
}

void UVerseDeckHudSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseUiSubsystem>();
	Collection.InitializeDependency<UVerseEventHub>();
	BindHub();
	if (UVerseServiceRecordSubsystem* Record = GetRecordSubsystem())
	{
		// The record speaks the language of the Verse UI, and shows level-ups only while the Verse is on screen (parity R-13).
		Record->SetStringsProvider([this]() -> const FVerseUiStrings* { const UVerseUiSubsystem* Ui = GetUi(); return Ui ? &Ui->GetStrings() : nullptr; });
		Record->SetOverlayVisible([this]()
		{
			const UVerseUiSubsystem* Ui = GetUi();
			return !Ui || Ui->GetLifecycleState() != FName(TEXT("dormant"));
		});
	}
	Lift.TravelTo = [this](FName Deck)
	{
		if (UVerseUiSubsystem* Ui = GetUi())
		{
			Ui->TravelToDeck(Deck);
		}
	};
	if (UVerseUiSubsystem* Ui = GetUi())
	{
		// Escape closes our dialog (or the promotion notice) and not the Esc menu while one is open.
		Ui->KeyPreHandler = [this](const FKey& Key)
		{
			if (Key != EKeys::Escape)
			{
				return false;
			}
			UVerseServiceRecordSubsystem* Record = GetRecordSubsystem();
			if (Record && Record->IsRecordOpen())
			{
				Record->CloseRecord();
				SyncDialogs();
				return true;
			}
			if (Lift.IsPanelOpen())
			{
				CloseLift();
				return true;
			}
			return Record && Record->DismissNotice();
		};
		SetDeck(Ui->GetGamePort().GetCurrentDeck());
	}
}

void UVerseDeckHudSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	BeganAt = Now();
	TicksSinceBegin = 0;
	BindHub();
	AttachSlate();
	Loading.Begin(Now(), int32(FPlatformTime::Cycles() & 0x7fffffff));
}

void UVerseDeckHudSubsystem::Deinitialize()
{
	if (UVerseUiSubsystem* Ui = GetUi())
	{
		Ui->KeyPreHandler = nullptr;
	}
	if (UVerseServiceRecordSubsystem* Record = GetRecordSubsystem())
	{
		Record->SetStringsProvider(nullptr);
		Record->SetOverlayVisible(nullptr);
	}
	if (bLookIgnored)
	{
		if (APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr)
		{
			PC->SetIgnoreLookInput(false);
		}
		bLookIgnored = false;
	}
	UnbindHub();
	DetachSlate();
	Super::Deinitialize();
}

TStatId UVerseDeckHudSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseDeckHudSubsystem, STATGROUP_Tickables);
}

UVerseUiSubsystem* UVerseDeckHudSubsystem::GetUi() const
{
	return GetWorld() ? GetWorld()->GetSubsystem<UVerseUiSubsystem>() : nullptr;
}

UVerseServiceRecordSubsystem* UVerseDeckHudSubsystem::GetRecordSubsystem() const
{
	const UGameInstance* Instance = GetWorld() ? GetWorld()->GetGameInstance() : nullptr;
	return Instance ? Instance->GetSubsystem<UVerseServiceRecordSubsystem>() : nullptr;
}

TSharedPtr<FVerseServiceRecordModel> UVerseDeckHudSubsystem::GetRecordModel() const
{
	UVerseServiceRecordSubsystem* Record = GetRecordSubsystem();
	return Record ? TSharedPtr<FVerseServiceRecordModel>(Record->GetModel()) : nullptr;
}

const FVerseUiStrings& UVerseDeckHudSubsystem::Strings() const
{
	static const FVerseUiStrings Empty;
	const UVerseUiSubsystem* Ui = GetUi();
	return Ui ? Ui->GetStrings() : Empty;
}

FText UVerseDeckHudSubsystem::S(const FString& Key) const
{
	return Strings().Get(Key);
}

// ---------------------------------------------------------------------------------------------
// Hub

void UVerseDeckHudSubsystem::BindHub()
{
	UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld());
	if (!Hub || BoundHub.Get() == Hub)
	{
		return;
	}
	UnbindHub();
	BoundHub = Hub;
	// The lift station (VerseDecks) raises a station event of kind "lift": it opens the panel (parity L-06).
	StationHandle = Hub->OnStationUsed.AddLambda([this](const FVerseStationUsedEvent& Event)
	{
		UVerseUiSubsystem* Ui = GetUi();
		const int32 Local = Ui ? Ui->GetHudSource().GetLocalPlayerId() : INDEX_NONE;
		if (Event.Kind == FName(TEXT("lift")) && (Local == INDEX_NONE || Event.UserId == Local))
		{
			OpenLift(EVerseLiftSource::Station);
		}
	});
}

void UVerseDeckHudSubsystem::UnbindHub()
{
	if (UVerseEventHub* Hub = BoundHub.Get())
	{
		Hub->OnStationUsed.Remove(StationHandle);
	}
	StationHandle.Reset();
	BoundHub.Reset();
}

// ---------------------------------------------------------------------------------------------
// State

void UVerseDeckHudSubsystem::SetDeck(FName Deck)
{
	if (FVerseDeckIds::IsDeck(Deck) && !Lift.IsRiding())
	{
		Lift.SetCurrentDeck(Deck);
	}
}

void UVerseDeckHudSubsystem::SetCrew(const TArray<FVerseDeckCrewRow>& Rows)
{
	Crew = Rows;
}

FVerseDeckTitle UVerseDeckHudSubsystem::GetTitle() const
{
	return FVerseDeckTitle::Build(Strings(), GetDeck(), FVerseDeckTitle::CountCrew(Crew));
}

void UVerseDeckHudSubsystem::SetView(EVerseDeckView View)
{
	if (View == EVerseDeckView::First && !ToolContext.bFirstAvailable)
	{
		return;
	}
	ToolContext.View = View;
	RefreshHud();
}

void UVerseDeckHudSubsystem::SetToolContext(const FVerseToolRailContext& Context)
{
	ToolContext = Context;
	RefreshHud();
}

bool UVerseDeckHudSubsystem::ShowsClickToLook() const
{
	return FVerseDeckHelp::ShowClickToLook(IsEyeLevel(), bMouseTaken, Dialogs.IsModal() || MenuOpen());
}

void UVerseDeckHudSubsystem::RefreshHud()
{
	if (HudWidget.IsValid())
	{
		HudWidget->Refresh();
	}
}

void UVerseDeckHudSubsystem::ActivateTool(EVerseTool Tool)
{
	EVerseDeckView View;
	if (FVerseToolRail::ViewOfTool(Tool, View))
	{
		if (View == EVerseDeckView::First && !ToolContext.bFirstAvailable)
		{
			PostNoticeKey(TEXT("verse.tools.first_unavailable"));
			return;
		}
		SetView(View);
		switch (View)
		{
		case EVerseDeckView::Overview: PostNoticeKey(TEXT("verse.notice.view_overview")); break;
		case EVerseDeckView::Third: PostNoticeKey(TEXT("verse.notice.view_follow_eye")); break;
		case EVerseDeckView::First: PostNoticeKey(TEXT("verse.notice.view_first")); break;
		}
		OnViewRequested.Broadcast(View);
		return;
	}
	switch (Tool)
	{
	case EVerseTool::Lift:
		OpenLift(EVerseLiftSource::ToolRail);
		break;
	case EVerseTool::Hoverboard:
		ToolContext.bHoverboardOut = !ToolContext.bHoverboardOut;
		RefreshHud();
		OnBoardRequested.Broadcast(ToolContext.bHoverboardOut);
		break;
	case EVerseTool::Commander:
		OnCommanderRequested.Broadcast();
		break;
	case EVerseTool::Duel:
		if (UVerseUiSubsystem* Ui = GetUi())
		{
			Ui->ShowScreen(EVerseUiScreen::Armoury);
		}
		break;
	case EVerseTool::Settings:
		if (UVerseUiSubsystem* Ui = GetUi())
		{
			Ui->ShowScreen(EVerseUiScreen::Settings);
		}
		break;
	case EVerseTool::Help:
		ShowHelp();
		break;
	default:
		break;
	}
}

// ---------------------------------------------------------------------------------------------
// Notices

void UVerseDeckHudSubsystem::PostNoticeKey(const FString& Key)
{
	Notice.PostNotice(S(Key), Now());
}

void UVerseDeckHudSubsystem::ShowHelp()
{
	Notice.PostHelp(FVerseDeckHelp::Build(Strings(), IsEyeLevel(), true), Now());
}

// ---------------------------------------------------------------------------------------------
// Lift

void UVerseDeckHudSubsystem::OpenLift(EVerseLiftSource Source)
{
	if (Lift.IsRiding())
	{
		return;
	}
	Lift.OpenPanel(Source);
	if (!LiftWidget.IsValid())
	{
		UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
		if (Viewport && FSlateApplication::IsInitialized())
		{
			LiftWidget = SNew(SVerseLiftPanel, this);
			Viewport->AddViewportWidgetContent(LiftWidget.ToSharedRef(), LiftZOrder);
		}
	}
	SyncDialogs();
}

void UVerseDeckHudSubsystem::CloseLift()
{
	Lift.ClosePanel();
	if (LiftWidget.IsValid())
	{
		if (UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr)
		{
			Viewport->RemoveViewportWidgetContent(LiftWidget.ToSharedRef());
		}
		LiftWidget.Reset();
	}
	SyncDialogs();
}

bool UVerseDeckHudSubsystem::ChooseDeck(FName Deck)
{
	const bool bRide = Lift.Choose(Deck, Now());
	CloseLift();
	return bRide;
}

void UVerseDeckHudSubsystem::NotifyDeckFrame(FName Deck)
{
	Lift.NotifyDeckReady(Deck, Now());
}

// ---------------------------------------------------------------------------------------------
// Dialogs

bool UVerseDeckHudSubsystem::MenuOpen() const
{
	const UVerseUiSubsystem* Ui = GetUi();
	return Ui && Ui->IsMouseLookReleased();
}

void UVerseDeckHudSubsystem::OpenServiceRecord(int32 TabIndex)
{
	if (UVerseServiceRecordSubsystem* Record = GetRecordSubsystem())
	{
		Record->OpenRecord(EVerseRecordTab(FMath::Clamp(TabIndex, 0, 4)));
		SyncDialogs();
	}
}

void UVerseDeckHudSubsystem::SetDialogOpen(FName Id, bool bOpen)
{
	if (bOpen && !Dialogs.IsOpen(Id))
	{
		// The widgets inside tell their own focus order; the stack tracks the modal state.
		Dialogs.Open(Id, NAME_None, {Id}, Id);
	}
	else if (!bOpen && Dialogs.IsOpen(Id))
	{
		Dialogs.Close(Id);
	}
}

void UVerseDeckHudSubsystem::SyncDialogs()
{
	const UVerseServiceRecordSubsystem* Record = GetRecordSubsystem();
	SetDialogOpen(TEXT("lift"), Lift.IsPanelOpen());
	SetDialogOpen(TEXT("record"), Record && Record->IsRecordOpen());
	SetDialogOpen(TEXT("menu"), MenuOpen());
	// The input mode is set when the set of open dialogs changes, not every frame.
	const int32 Signature = (Dialogs.IsOpen(TEXT("lift")) ? 1 : 0) | (Dialogs.IsOpen(TEXT("record")) ? 2 : 0) | (Dialogs.IsOpen(TEXT("menu")) ? 4 : 0);
	if (Signature != LastDialogSignature)
	{
		LastDialogSignature = Signature;
		ApplyInputMode();
	}
}

void UVerseDeckHudSubsystem::ApplyInputMode()
{
	APlayerController* PC = GetWorld() ? GetWorld()->GetFirstPlayerController() : nullptr;
	if (!PC)
	{
		return;
	}
	const bool bModal = ReleasesMouseLook();
	if (bModal != bLookIgnored)
	{
		PC->SetIgnoreLookInput(bModal);
		bLookIgnored = bModal;
	}
	// The menu screens set the input mode themselves; ours covers the lift and the record.
	if (Dialogs.IsOpen(TEXT("lift")) || Dialogs.IsOpen(TEXT("record")))
	{
		FInputModeGameAndUI Mode;
		Mode.SetHideCursorDuringCapture(false);
		PC->SetInputMode(Mode);
		PC->SetShowMouseCursor(true);
	}
	else if (!MenuOpen())
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->SetShowMouseCursor(false);
	}
}

// ---------------------------------------------------------------------------------------------
// Widgets and tick

void UVerseDeckHudSubsystem::AttachSlate()
{
	UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
	if (!Viewport || HudWidget.IsValid() || !FSlateApplication::IsInitialized())
	{
		return;
	}
	HudWidget = SNew(SVerseDeckHud, this);
	Viewport->AddViewportWidgetContent(HudWidget.ToSharedRef(), HudZOrder);
	DoorsWidget = SNew(SVerseLiftDoors, this);
	Viewport->AddViewportWidgetContent(DoorsWidget.ToSharedRef(), DoorsZOrder);
	if (Loading.IsVisible())
	{
		LoadingWidget = SNew(SVerseLoadingScreen, this);
		Viewport->AddViewportWidgetContent(LoadingWidget.ToSharedRef(), LoadingZOrder);
	}
}

void UVerseDeckHudSubsystem::DetachSlate()
{
	UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr;
	auto Remove = [Viewport](TSharedPtr<SWidget> Widget)
	{
		if (Viewport && Widget.IsValid())
		{
			Viewport->RemoveViewportWidgetContent(Widget.ToSharedRef());
		}
	};
	Remove(HudWidget);
	Remove(LiftWidget);
	Remove(DoorsWidget);
	Remove(LoadingWidget);
	HudWidget.Reset();
	LiftWidget.Reset();
	DoorsWidget.Reset();
	LoadingWidget.Reset();
}

void UVerseDeckHudSubsystem::TickLoading(double Time)
{
	if (Loading.GetPhase() == FVerseLoadingModel::EPhase::Showing && Loading.GetFirstFrameAt() < 0.0)
	{
		// The first frame of the deck: a view exists (the pawn is possessed), or the grace passed.
		FVerseHudView View;
		const UVerseUiSubsystem* Ui = GetUi();
		const bool bView = Ui && Ui->GetHudSource().GetView(View);
		if (TicksSinceBegin > 2 && (bView || Time - BeganAt > FirstFrameGraceSeconds))
		{
			Loading.NotifyFirstDeckFrame(Time);
		}
	}
	Loading.Tick(Time);
	if (LoadingWidget.IsValid())
	{
		if (Loading.IsVisible())
		{
			LoadingWidget->SetRenderOpacity(Loading.Opacity(Time));
		}
		else
		{
			if (UGameViewportClient* Viewport = GetWorld() ? GetWorld()->GetGameViewport() : nullptr)
			{
				Viewport->RemoveViewportWidgetContent(LoadingWidget.ToSharedRef());
			}
			LoadingWidget.Reset();
		}
	}
}

void UVerseDeckHudSubsystem::TickLift(double Time)
{
	if (!Lift.IsRiding())
	{
		// The deck the game is on (a ride, a QA command or the level itself changes it).
		if (const UVerseUiSubsystem* Ui = GetUi())
		{
			SetDeck(Ui->GetGamePort().GetCurrentDeck());
		}
	}
	if (Lift.IsRiding())
	{
		// The game port reports the deck once the level is in; its first tick after that is the first frame.
		const UVerseUiSubsystem* Ui = GetUi();
		if (Ui && Lift.GetDoors() == EVerseDoorState::Closed && Ui->GetGamePort().GetCurrentDeck() == Lift.GetRideTarget())
		{
			Lift.NotifyDeckReady(Lift.GetRideTarget(), Time);
		}
	}
	Lift.Tick(Time);
}

void UVerseDeckHudSubsystem::Tick(float DeltaTime)
{
	const double Time = Now();
	++TicksSinceBegin;
	TickLoading(Time);
	TickLift(Time);
	SyncDialogs();
}

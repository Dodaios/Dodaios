#include "Input/VerseDeckControlComponent.h"

#include "Camera/CameraComponent.h"
#include "Camera/VerseDeckCamera.h"
#include "Commander/VerseDeckCommander.h"
#include "Components/CapsuleComponent.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "Debug/DebugDrawService.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "EnhancedInputComponent.h"
#include "EnhancedInputSubsystems.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/InputSettings.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PawnMovementComponent.h"
#include "HAL/PlatformTime.h"
#include "HangarSwitch/VerseHangarSwitchSubsystem.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "Misc/App.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "VerseLog.h"

namespace VerseDeckControlPrivate
{
	/** Above the person's own context (IMC_VersePerson) so the deck owns its keys on the decks. */
	constexpr int32 ContextPriority = 10;
	/** Rows of the nav grid probed per frame after an arrival. */
	constexpr int32 NavRowsPerFrame = 24;
	/** Picks reach this far, cm. */
	constexpr double PickRangeCm = 10000.0;
	/** A pick lands on a station when it is this close to the station on the plan, cm. */
	constexpr double StationPickCm = 90.0;
	/** Probe capsule: a standing body with some headroom. */
	constexpr float ProbeRadius = 28.f;
	constexpr float ProbeHalfHeight = 60.f;
	/** A floor more than this far above the room's floor is furniture, not floor. */
	constexpr double FloorAboveRoomCm = 60.0;
	/** A third-person camera closer than this to the shoulder pivot hides the body. */
	constexpr double BodyHideCm = 55.0;

	FString Words(FName Kind)
	{
		FString Text = Kind.ToString().Replace(TEXT("_"), TEXT(" "));
		if (Text.Len() > 0)
		{
			Text[0] = FChar::ToUpper(Text[0]);
		}
		return Text;
	}
}

UVerseDeckControlComponent::UVerseDeckControlComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PrePhysics;
	StationLabel = &UVerseDeckControlComponent::DefaultStationLabel;
}

UVerseDeckControlComponent* UVerseDeckControlComponent::Get(const UWorld* World)
{
	const APlayerController* Controller = World ? World->GetFirstPlayerController() : nullptr;
	return Controller ? Controller->FindComponentByClass<UVerseDeckControlComponent>() : nullptr;
}

UVerseDeckControlComponent* UVerseDeckControlComponent::Ensure(APlayerController* Controller)
{
	if (Controller == nullptr)
	{
		return nullptr;
	}
	if (UVerseDeckControlComponent* Existing = Controller->FindComponentByClass<UVerseDeckControlComponent>())
	{
		return Existing;
	}
	UVerseDeckControlComponent* Control = NewObject<UVerseDeckControlComponent>(Controller, TEXT("VerseDeckControl"), RF_Transient);
	Control->RegisterComponent();
	return Control;
}

bool UVerseDeckControlComponent::TryEscape(const UWorld* World)
{
	UVerseDeckControlComponent* Control = Get(World);
	return Control && Control->IsDeckActive() && Control->HandleEscape();
}

FText UVerseDeckControlComponent::DefaultStationLabel(const FVerseDeckStation& Station)
{
	using namespace VerseDeckControlPrivate;
	const FString Action = Station.Kind == TEXT("lift") ? TEXT("call the lift")
		: Station.Kind == TEXT("mess_call") ? TEXT("sound the mess call")
		: Station.Kind == TEXT("create_agent") ? TEXT("enlist")
		: TEXT("open");
	return FText::FromString(FString::Printf(TEXT("%s · %s"), *Words(Station.Kind), *Action));
}

// -------------------------------------------------------------------------------------------------
// Arrival, the pawns and input binding

void UVerseDeckControlComponent::OnDeckArrived(FName InDeck, const FVerseDeckManifest& InManifest, const FTransform& Arrival, AVerseDeckCamera* InCamera)
{
	Deck = InDeck;
	Manifest = InManifest;
	Camera = InCamera;
	// A walk order belongs to the deck it was given on (B-07).
	Orders.Arrive(InDeck);
	ClearSelection();
	MoveAxes = FVector2D::ZeroVector;
	Nav = FVerseDeckNavGrid();
	Nav.InitFromManifest(Manifest);

	AVerseDeckCommander* Body = EnsureCommander(Arrival);
	if (Body)
	{
		Body->PlaceAt(Arrival.GetLocation(), Arrival.Rotator().Yaw);
		TWeakObjectPtr<UVerseDeckControlComponent> Weak(this);
		Body->CanStand = [Weak](const FVector2D& Plan)
		{
			const UVerseDeckControlComponent* Self = Weak.Get();
			// Until the grid is probed the capsule's own collision and ledge rule keep the body safe.
			return Self == nullptr || !Self->Nav.IsComplete() || Self->Nav.IsWalkable(Plan);
		};
	}
	LastGoodFeet = Arrival.GetLocation();
	const UVerseHangarSwitchSubsystem* Switch = UVerseHangarSwitchSubsystem::Get(this);
	bArenaWas = Switch && (Switch->IsArenaOn() || Switch->IsSwitching());
	SetDeckActive(!bArenaWas);
	if (Camera.IsValid())
	{
		ApplyView(Camera->GetView(), false);
	}
}

AVerseDeckCommander* UVerseDeckControlComponent::EnsureCommander(const FTransform& Arrival)
{
	if (Commander.IsValid())
	{
		return Commander.Get();
	}
	UWorld* World = GetWorld();
	if (World == nullptr)
	{
		return nullptr;
	}
	if (AVerseDeckCommander* Existing = AVerseDeckCommander::Find(World))
	{
		Commander = Existing;
		return Existing;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.ObjectFlags |= RF_Transient;
	Params.Name = TEXT("VerseDeckCommander");
	Params.NameMode = FActorSpawnParameters::ESpawnActorNameMode::Requested;
	AVerseDeckCommander* Body = World->SpawnActor<AVerseDeckCommander>(AVerseDeckCommander::StaticClass(), Arrival.GetLocation() + FVector(0.0, 0.0, 92.0), Arrival.Rotator(), Params);
	Commander = Body;
	return Body;
}

void UVerseDeckControlComponent::SetDeckActive(bool bOn)
{
	if (bOn == bActive && (bOn == bBound))
	{
		return;
	}
	bActive = bOn;
	if (AVerseDeckCommander* Body = Commander.Get())
	{
		Body->SetActorHiddenInGame(!bOn);
		Body->SetActorEnableCollision(bOn);
		Body->SetActorTickEnabled(bOn);
		if (!bOn)
		{
			Body->StopWalk();
			Body->Drive(FVector2D::ZeroVector, false, 0.0, true);
		}
	}
	if (bOn)
	{
		ParkPawn();
		BindInput();
	}
	else
	{
		UnbindInput();
		UnparkPawn();
		MoveAxes = FVector2D::ZeroVector;
		bMouseLook = false;
		if (bPower)
		{
			bPower = false;
			OnPower.Broadcast(false);
		}
	}
}

void UVerseDeckControlComponent::ParkPawn()
{
	APlayerController* Controller = Cast<APlayerController>(GetOwner());
	APawn* Pawn = Controller ? Controller->GetPawn() : nullptr;
	if (Pawn == nullptr || Pawn == Commander.Get())
	{
		return;
	}
	Parked = Pawn;
	Pawn->SetActorHiddenInGame(true);
	Pawn->SetActorEnableCollision(false);
	if (UCharacterMovementComponent* Move = Pawn->FindComponentByClass<UCharacterMovementComponent>())
	{
		Move->DisableMovement();
	}
}

void UVerseDeckControlComponent::UnparkPawn()
{
	APawn* Pawn = Parked.Get();
	if (Pawn == nullptr)
	{
		return;
	}
	Pawn->SetActorHiddenInGame(false);
	Pawn->SetActorEnableCollision(true);
	if (UCharacterMovementComponent* Move = Pawn->FindComponentByClass<UCharacterMovementComponent>())
	{
		Move->SetMovementMode(MOVE_Walking);
	}
	Parked.Reset();
}

void UVerseDeckControlComponent::BindInput()
{
	if (bBound)
	{
		return;
	}
	APlayerController* Controller = Cast<APlayerController>(GetOwner());
	if (Controller == nullptr)
	{
		return;
	}
	bBound = true;
	if (Input.Context == nullptr)
	{
		Input = Verse::DeckInput::BuildContext(this);
		InputObjects.Reset();
		InputObjects.Add(Input.Context);
		for (UInputAction* Action : Input.Actions)
		{
			InputObjects.Add(Action);
		}
	}
	// Captured look is raw: no smoothing on top of the OS-free deltas of high precision mode (V-11).
	GetMutableDefault<UInputSettings>()->bEnableMouseSmoothing = false;

	ULocalPlayer* Player = Controller->GetLocalPlayer();
	if (UEnhancedInputLocalPlayerSubsystem* Subsystem = Player ? Player->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>() : nullptr)
	{
		Subsystem->AddMappingContext(Input.Context, VerseDeckControlPrivate::ContextPriority);
	}
	if (DeckInputComponent == nullptr)
	{
		using namespace Verse::DeckInput;
		DeckInputComponent = NewObject<UEnhancedInputComponent>(Controller, TEXT("VerseDeckInput"), RF_Transient);
		DeckInputComponent->Priority = VerseDeckControlPrivate::ContextPriority;
		DeckInputComponent->RegisterComponent();
		UEnhancedInputComponent& In = *DeckInputComponent;
		TWeakObjectPtr<UVerseDeckControlComponent> Weak(this);
		auto On = [&In, Weak, this](EAction Action, ETriggerEvent Event, TFunction<void(UVerseDeckControlComponent&, const FInputActionValue&)> Fn)
		{
			In.BindActionValueLambda(Input.Get(Action), Event, [Weak, Fn](const FInputActionValue& Value)
			{
				if (UVerseDeckControlComponent* Self = Weak.Get())
				{
					Fn(*Self, Value);
				}
			});
		};
		On(EAction::Move, ETriggerEvent::Triggered, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnMoveAction(V); });
		On(EAction::Move, ETriggerEvent::Completed, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnMoveEnd(V); });
		On(EAction::Hurry, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { S.SetHurry(true); });
		On(EAction::Hurry, ETriggerEvent::Completed, [](UVerseDeckControlComponent& S, const FInputActionValue&) { S.SetHurry(false); });
		On(EAction::CycleView, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.CycleView(); } });
		On(EAction::ViewOverview, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.PickView(EVerseDeckView::Overview); } });
		On(EAction::ViewThird, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.PickView(EVerseDeckView::Third); } });
		On(EAction::ViewFirst, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.PickView(EVerseDeckView::First); } });
		On(EAction::Use, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.Use(); } });
		On(EAction::MouseLook, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.ToggleMouseLook(); } });
		On(EAction::Power, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&)
		{
			if (S.TakesKeys() && !S.bPower) { S.bPower = true; S.OnPower.Broadcast(true); }
		});
		On(EAction::Power, ETriggerEvent::Completed, [](UVerseDeckControlComponent& S, const FInputActionValue&)
		{
			if (S.bPower) { S.bPower = false; S.OnPower.Broadcast(false); }
		});
		On(EAction::Board, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.OnBoard.Broadcast(); } });
		On(EAction::ZoomIn, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.ZoomStep(true); } });
		On(EAction::ZoomOut, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { if (S.TakesKeys()) { S.ZoomStep(false); } });
		On(EAction::Wheel, ETriggerEvent::Triggered, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnWheelAction(V); });
		On(EAction::Look, ETriggerEvent::Triggered, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnLookAction(V); });
		On(EAction::Click, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnClickDown(V); });
		On(EAction::Click, ETriggerEvent::Completed, [](UVerseDeckControlComponent& S, const FInputActionValue& V) { S.OnClickUp(V); });
#if !UE_BUILD_SHIPPING
		On(EAction::Debug, ETriggerEvent::Started, [](UVerseDeckControlComponent& S, const FInputActionValue&) { S.OnDebugOverlay.Broadcast(); });
#endif
	}
	Controller->PushInputComponent(DeckInputComponent);
}

void UVerseDeckControlComponent::UnbindInput()
{
	if (!bBound)
	{
		return;
	}
	bBound = false;
	APlayerController* Controller = Cast<APlayerController>(GetOwner());
	if (Controller && DeckInputComponent)
	{
		Controller->PopInputComponent(DeckInputComponent);
	}
	ULocalPlayer* Player = Controller ? Controller->GetLocalPlayer() : nullptr;
	if (UEnhancedInputLocalPlayerSubsystem* Subsystem = Player ? Player->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>() : nullptr)
	{
		if (Input.Context)
		{
			Subsystem->RemoveMappingContext(Input.Context);
		}
	}
	SetMouseLook(false);
}

void UVerseDeckControlComponent::BeginPlay()
{
	Super::BeginPlay();
	DrawHandle = UDebugDrawService::Register(TEXT("Game"), FDebugDrawDelegate::CreateWeakLambda(this, [this](UCanvas* Canvas, APlayerController*)
	{
		DrawOverlay(Canvas);
	}));
}

void UVerseDeckControlComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (DrawHandle.IsValid())
	{
		UDebugDrawService::Unregister(DrawHandle);
		DrawHandle.Reset();
	}
	UnbindInput();
	Super::EndPlay(Reason);
}

// -------------------------------------------------------------------------------------------------
// Focus, chords and escape

bool UVerseDeckControlComponent::IsChordHeld() const
{
	if (ChordProbe)
	{
		return ChordProbe();
	}
	const APlayerController* Controller = Cast<APlayerController>(GetOwner());
	if (Controller == nullptr || Controller->PlayerInput == nullptr)
	{
		return false;
	}
	for (const FKey& Key : { EKeys::LeftControl, EKeys::RightControl, EKeys::LeftAlt, EKeys::RightAlt, EKeys::LeftCommand, EKeys::RightCommand })
	{
		if (Controller->IsInputKeyDown(Key))
		{
			return true;
		}
	}
	return false;
}

bool UVerseDeckControlComponent::TakesKeys() const
{
	const bool bFocused = WindowFocused ? WindowFocused() : FApp::HasFocus();
	// A text field with keyboard focus keeps the keys from the viewport, so the deck never sees them.
	return bActive && Verse::DeckInput::TakesKeys(bFocused, false, IsChordHeld());
}

bool UVerseDeckControlComponent::HandleEscape()
{
	using namespace Verse::DeckInput;
	switch (EscapeStep(bMouseLook, Selected.IsValid()))
	{
	case EEscape::EndMouseLook:
		SetMouseLook(false);
		return true;
	case EEscape::CloseCard:
		ClearSelection();
		return true;
	default:
		return false;
	}
}

// -------------------------------------------------------------------------------------------------
// Views and the mouse

bool UVerseDeckControlComponent::IsEyeLevel() const
{
	return Camera.IsValid() && Camera->GetView() != EVerseDeckView::Overview;
}

void UVerseDeckControlComponent::ApplyView(EVerseDeckView View, bool bTakeMouse)
{
	AVerseDeckCamera* Cam = Camera.Get();
	if (Cam == nullptr)
	{
		return;
	}
	const EVerseDeckView Before = Cam->GetView();
	Cam->SetView(View);
	// Third and first person take the mouse for shooter look at once; the overview gives it back (V-20).
	SetMouseLook(bTakeMouse && Cam->GetView() != EVerseDeckView::Overview);
	if (Cam->GetView() != Before)
	{
		OnViewChanged.Broadcast(Cam->GetView());
	}
}

void UVerseDeckControlComponent::PickView(EVerseDeckView View)
{
	ApplyView(View, true);
}

void UVerseDeckControlComponent::CycleView()
{
	if (AVerseDeckCamera* Cam = Camera.Get())
	{
		ApplyView(Verse::DeckView::Cycle(Cam->GetView(), Cam->bEyeCapable), true);
	}
}

void UVerseDeckControlComponent::ToggleMouseLook()
{
	if (!IsEyeLevel())
	{
		return;
	}
	SetMouseLook(!bMouseLook);
}

void UVerseDeckControlComponent::SetMouseLook(bool bOn)
{
	bOn = bOn && IsEyeLevel() && bActive;
	const bool bChanged = bOn != bMouseLook;
	bMouseLook = bOn;
	if (AVerseDeckCamera* Cam = Camera.Get())
	{
		Cam->bMouseLocked = bOn;
	}
	if (APlayerController* Controller = Cast<APlayerController>(GetOwner()))
	{
		Controller->SetShowMouseCursor(!bOn);
		if (bOn)
		{
			// Game-only input with a hidden cursor puts the viewport in high precision (raw) mouse mode (V-11).
			Controller->SetInputMode(FInputModeGameOnly());
		}
		else
		{
			FInputModeGameAndUI Mode;
			Mode.SetLockMouseToViewportBehavior(EMouseLockMode::DoNotLock);
			Mode.SetHideCursorDuringCapture(false);
			Controller->SetInputMode(Mode);
		}
	}
	if (bChanged)
	{
		OnMouseLookChanged.Broadcast(bOn);
	}
}

void UVerseDeckControlComponent::ZoomStep(bool bIn)
{
	if (AVerseDeckCamera* Cam = Camera.Get())
	{
		const EVerseDeckView Before = Cam->GetView();
		Cam->Zoom(static_cast<float>(bIn ? Verse::DeckInput::ZoomInFactor : Verse::DeckInput::ZoomOutFactor));
		if (Cam->GetView() != Before)
		{
			// The wheel pushed third person into first (or back): the mouse stays as it is.
			OnViewChanged.Broadcast(Cam->GetView());
		}
	}
}

void UVerseDeckControlComponent::Wheel(float Value)
{
	if (!FMath::IsNearlyZero(Value))
	{
		ZoomStep(Value > 0.f);
	}
}

void UVerseDeckControlComponent::LookDelta(const FVector2D& DeltaPx)
{
	AVerseDeckCamera* Cam = Camera.Get();
	if (Cam == nullptr || !bActive)
	{
		return;
	}
	if (bMouseLook)
	{
		Cam->Look(static_cast<float>(DeltaPx.X), static_cast<float>(DeltaPx.Y), true);
		return;
	}
	if (bPressed)
	{
		// A drag with the button held turns the view (V-14) and is no click.
		DragPx += DeltaPx.Size();
		Cam->Look(static_cast<float>(DeltaPx.X), static_cast<float>(DeltaPx.Y), false);
	}
}

void UVerseDeckControlComponent::FocusCommander()
{
	if (AVerseDeckCamera* Cam = Camera.Get())
	{
		Cam->FocusCommander();
	}
}

void UVerseDeckControlComponent::ShowActor(const AActor* Actor)
{
	AVerseDeckCamera* Cam = Camera.Get();
	if (Cam == nullptr || Actor == nullptr)
	{
		return;
	}
	if (Cam->GetView() == EVerseDeckView::Overview)
	{
		Cam->Overview.Focus(Actor->GetActorLocation());
		return;
	}
	if (const AVerseDeckCommander* Body = Commander.Get())
	{
		Cam->Rig.FaceToward(Body->GetFeet(), Actor->GetActorLocation());
	}
}

// -------------------------------------------------------------------------------------------------
// Keys and clicks

void UVerseDeckControlComponent::SetMoveAxes(const FVector2D& Axes)
{
	MoveAxes = Axes;
}

void UVerseDeckControlComponent::SetHurry(bool bHeld)
{
	bHurry = bHeld;
}

void UVerseDeckControlComponent::OnMoveAction(const FInputActionValue& Value)
{
	SetMoveAxes(TakesKeys() ? Value.Get<FVector2D>() : FVector2D::ZeroVector);
}

void UVerseDeckControlComponent::OnMoveEnd(const FInputActionValue&)
{
	SetMoveAxes(FVector2D::ZeroVector);
}

void UVerseDeckControlComponent::OnLookAction(const FInputActionValue& Value)
{
	const FVector2D Delta = Value.Get<FVector2D>();
	// Mouse Y grows up; screen pixels grow down.
	LookDelta(FVector2D(Delta.X, -Delta.Y));
}

void UVerseDeckControlComponent::OnWheelAction(const FInputActionValue& Value)
{
	Wheel(Value.Get<float>());
}

void UVerseDeckControlComponent::OnClickDown(const FInputActionValue&)
{
	const TOptional<FVector2D> At = MousePosition ? MousePosition() : TOptional<FVector2D>();
	FVector2D Screen = At.Get(GetViewportSize() * 0.5);
	if (!At.IsSet())
	{
		if (const APlayerController* Controller = Cast<APlayerController>(GetOwner()))
		{
			float X = 0.f;
			float Y = 0.f;
			if (Controller->GetMousePosition(X, Y))
			{
				Screen = FVector2D(X, Y);
			}
		}
	}
	PointerDown(Screen);
}

void UVerseDeckControlComponent::OnClickUp(const FInputActionValue&)
{
	PointerUp(PressAt);
}

void UVerseDeckControlComponent::PointerDown(const FVector2D& ScreenPx)
{
	bPressed = true;
	PressAt = ScreenPx;
	DragPx = 0.0;
}

void UVerseDeckControlComponent::PointerUp(const FVector2D& ScreenPx)
{
	if (!bPressed)
	{
		return;
	}
	bPressed = false;
	if (DragPx <= Verse::DeckInput::ClickSlopPx && bActive)
	{
		Click(ScreenPx);
	}
}

void UVerseDeckControlComponent::Click(const FVector2D& ScreenPx)
{
	if (!bActive)
	{
		return;
	}
	if (IsEyeLevel())
	{
		if (!bMouseLook)
		{
			// A click while the mouse is free takes it for mouse look ("click to look", H-10).
			SetMouseLook(true);
			return;
		}
		// Shooter look: the click works what the reticle is on, a crew member or a station, never the floor.
		const FVerseDeckPick Pick = PickAt(GetViewportSize() * 0.5);
		if (Pick.Kind == FVerseDeckPick::EKind::Crew)
		{
			Select(Pick.Actor.Get());
		}
		else if (Pick.Kind == FVerseDeckPick::EKind::Station)
		{
			ActivateStation(Pick.Station);
		}
		return;
	}
	CompleteNav();
	const FVerseDeckPick Pick = PickAt(ScreenPx);
	switch (Pick.Kind)
	{
	case FVerseDeckPick::EKind::Crew:
		Select(Pick.Actor.Get());
		return;
	case FVerseDeckPick::EKind::Station:
		ActivateStation(Pick.Station);
		return;
	case FVerseDeckPick::EKind::Floor:
		ClearSelection();
		WalkTo(Pick.Point, true);
		return;
	default:
		// A wall or nothing: no walk (V-15).
		ClearSelection();
		return;
	}
}

void UVerseDeckControlComponent::Select(AActor* Actor)
{
	if (Actor == nullptr)
	{
		return;
	}
	if (Selected.Get() == Actor)
	{
		// A second click on the selected member opens their card.
		OnCrewOpened.Broadcast(Actor);
		return;
	}
	Selected = Actor;
	OnCrewSelected.Broadcast(Actor);
}

void UVerseDeckControlComponent::ClearSelection()
{
	if (Selected.IsValid())
	{
		Selected.Reset();
		OnSelectionCleared.Broadcast();
	}
}

void UVerseDeckControlComponent::Use()
{
	if (!bActive)
	{
		return;
	}
	if (IsEyeLevel())
	{
		const FVerseDeckPick Pick = PickAt(GetViewportSize() * 0.5);
		if (Pick.Kind == FVerseDeckPick::EKind::Crew)
		{
			Select(Pick.Actor.Get());
			return;
		}
		if (Pick.Kind == FVerseDeckPick::EKind::Station)
		{
			ActivateStation(Pick.Station);
			return;
		}
	}
	const AVerseDeckCommander* Body = Commander.Get();
	if (Body == nullptr)
	{
		return;
	}
	const FVector Forward = Body->GetActorForwardVector();
	if (const FVerseDeckStation* Station = Verse::DeckWalk::StationWithin(Manifest.Stations, Body->GetFeet(), FVector2D(Forward.X, Forward.Y)))
	{
		ActivateStation(Station->Id);
	}
}

// -------------------------------------------------------------------------------------------------
// Walking

void UVerseDeckControlComponent::CompleteNav()
{
	StepNav(Nav.NumRows());
}

void UVerseDeckControlComponent::StepNav(int32 Rows)
{
	if (Nav.IsComplete())
	{
		return;
	}
	const double Started = FPlatformTime::Seconds();
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseDeckNavProbe), false);
	// Bodies never make floor: crew walk away, the commander stands anywhere.
	if (const UWorld* World = GetWorld())
	{
		for (TActorIterator<APawn> It(World); It; ++It)
		{
			Params.AddIgnoredActor(*It);
		}
	}
	Nav.ProbeRows(Rows, [this, &Params](const FVector2D& Plan, double RoomZ) { return ProbeFloor(Plan, RoomZ, Params); });
	if (Nav.IsComplete())
	{
		UE_LOG(LogVerse, Log, TEXT("[VerseDeckControl] nav grid of %s: %d x %d cells, %d walkable (last slice %.1f ms)"),
			*Deck.ToString(), Nav.NumCols(), Nav.NumRows(), Nav.NumWalkable(), (FPlatformTime::Seconds() - Started) * 1000.0);
	}
}

TOptional<double> UVerseDeckControlComponent::ProbeFloor(const FVector2D& PlanCm, double RoomZCm, const FCollisionQueryParams& Params) const
{
	using namespace VerseDeckControlPrivate;
	const UWorld* World = GetWorld();
	if (World == nullptr)
	{
		return {};
	}
	const FVector Top(PlanCm.X, PlanCm.Y, RoomZCm + FloorAboveRoomCm + ProbeHalfHeight + 30.0);
	const FVector Bottom(PlanCm.X, PlanCm.Y, RoomZCm - 80.0);
	FHitResult Hit;
	if (!World->SweepSingleByChannel(Hit, Top, Bottom, FQuat::Identity, ECC_Pawn, FCollisionShape::MakeCapsule(ProbeRadius, ProbeHalfHeight), Params))
	{
		return {};
	}
	if (Hit.bStartPenetrating || Hit.ImpactNormal.Z < 0.7 || Hit.ImpactPoint.Z > RoomZCm + FloorAboveRoomCm)
	{
		return {};
	}
	return Hit.ImpactPoint.Z;
}

bool UVerseDeckControlComponent::WalkTo(const FVector& PointCm, bool bSnap)
{
	AVerseDeckCommander* Body = Commander.Get();
	if (Body == nullptr)
	{
		return false;
	}
	CompleteNav();
	FVector Goal = PointCm;
	if (bSnap)
	{
		const TOptional<FVector> Floor = Nav.NearestWalkable(FVector2D(PointCm.X, PointCm.Y), Verse::DeckWalk::ClickSnapCm);
		if (!Floor.IsSet())
		{
			return false;
		}
		Goal = Floor.GetValue();
	}
	TArray<FVector> Points;
	if (!Nav.FindPath(Body->GetFeet(), Goal, Points))
	{
		return false;
	}
	Orders.Give(Deck, Points.Last());
	Body->WalkPath(Points, bHurry);
	return true;
}

bool UVerseDeckControlComponent::ActivateStation(FName StationId)
{
	const FVerseDeckStation* Station = Manifest.FindStation(StationId);
	if (Station == nullptr || !bActive)
	{
		return false;
	}
	ClearSelection();
	CompleteNav();
	// The commander walks to the station's spot: the walkable floor nearest to it (S-11).
	const FVector At = Station->Transform.GetLocation();
	if (const TOptional<FVector> Spot = Nav.NearestWalkable(FVector2D(At.X, At.Y), Verse::DeckWalk::StationReachCm))
	{
		WalkTo(Spot.GetValue(), false);
	}
	OnStationActivated.Broadcast(*Station);
	return true;
}

void UVerseDeckControlComponent::Salute()
{
	if (AVerseDeckCommander* Body = Commander.Get())
	{
		Body->Salute();
	}
}

void UVerseDeckControlComponent::WearUniform(FName Uniform, const FLinearColor& Colour)
{
	if (AVerseDeckCommander* Body = Commander.Get())
	{
		Body->SetUniform(Uniform, Colour);
	}
}

// -------------------------------------------------------------------------------------------------
// Picking

FVector2D UVerseDeckControlComponent::GetViewportSize() const
{
	if (ViewportSize)
	{
		return ViewportSize();
	}
	if (GEngine && GEngine->GameViewport && GEngine->GameViewport->Viewport)
	{
		FVector2D Size;
		GEngine->GameViewport->GetViewportSize(Size);
		if (Size.X > 0 && Size.Y > 0)
		{
			return Size;
		}
	}
	return FVector2D(1920.0, 1080.0);
}

bool UVerseDeckControlComponent::RayThrough(const FVector2D& ScreenPx, FVector& OutOrigin, FVector& OutDirection) const
{
	const AVerseDeckCamera* Cam = Camera.Get();
	if (Cam == nullptr || Cam->Camera == nullptr)
	{
		return false;
	}
	const FVector2D Size = GetViewportSize();
	const FRotator Rotation = Cam->GetActorRotation();
	const FRotationMatrix Basis(Rotation);
	const double TanH = FMath::Tan(FMath::DegreesToRadians(Cam->Camera->FieldOfView * 0.5));
	const double TanV = TanH * Size.Y / FMath::Max(1.0, Size.X);
	const double X = 2.0 * ScreenPx.X / FMath::Max(1.0, Size.X) - 1.0;
	const double Y = 1.0 - 2.0 * ScreenPx.Y / FMath::Max(1.0, Size.Y);
	OutOrigin = Cam->GetActorLocation();
	OutDirection = (Basis.GetUnitAxis(EAxis::X) + Basis.GetUnitAxis(EAxis::Y) * (X * TanH) + Basis.GetUnitAxis(EAxis::Z) * (Y * TanV)).GetSafeNormal();
	return true;
}

FVerseDeckPick UVerseDeckControlComponent::PickAt(const FVector2D& ScreenPx) const
{
	FVector Origin;
	FVector Direction;
	if (!RayThrough(ScreenPx, Origin, Direction))
	{
		return {};
	}
	return PickRay(Origin, Direction);
}

const FVerseDeckStation* UVerseDeckControlComponent::StationNear(const FVector& PointCm, double RadiusCm) const
{
	const FVerseDeckStation* Best = nullptr;
	double BestD = RadiusCm;
	for (const FVerseDeckStation& Station : Manifest.Stations)
	{
		const FVector At = Station.Transform.GetLocation();
		const double D = FVector2D::Distance(FVector2D(At.X, At.Y), FVector2D(PointCm.X, PointCm.Y));
		if (D <= BestD && FMath::Abs(At.Z - PointCm.Z) < 250.0)
		{
			BestD = D;
			Best = &Station;
		}
	}
	return Best;
}

FVerseDeckPick UVerseDeckControlComponent::PickRay(const FVector& Origin, const FVector& Direction) const
{
	using namespace VerseDeckControlPrivate;
	FVerseDeckPick Pick;
	const UWorld* World = GetWorld();
	if (World == nullptr)
	{
		return Pick;
	}
	const UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(this);
	const bool bCutaway = Decks && Decks->IsCutaway();
	// Simple collision, as the deck collision is authored (the sweeps of Verse.Decks.Collision use it too).
	FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseDeckPick), false);
	for (const AActor* Ignored : { static_cast<const AActor*>(Commander.Get()), static_cast<const AActor*>(Parked.Get()) })
	{
		if (Ignored)
		{
			Params.AddIgnoredActor(Ignored);
		}
	}
	FVector From = Origin;
	const FVector End = Origin + Direction * PickRangeCm;
	FHitResult Hit;
	bool bHit = false;
	// The overview is a cutaway: hidden ceilings still collide, so a pick looks through them.
	for (int32 Try = 0; Try < 8; ++Try)
	{
		bHit = World->LineTraceSingleByChannel(Hit, From, End, ECC_Visibility, Params);
		const AActor* Actor = Hit.GetActor();
		const bool bSkip = Actor && ((bCutaway && UVerseDeckSubsystem::IsCeilingActor(*Actor)) || Actor->IsHidden());
		if (!bHit || !bSkip)
		{
			break;
		}
		Params.AddIgnoredActor(Actor);
	}
	// Bodies: capsules ignore the visibility channel, so look for a pawn in front of what the ray met
	// (a crew member behind a wall is never picked, V-16).
	const FVector PawnEnd = bHit ? Hit.ImpactPoint : End;
	FHitResult Body;
	if (World->LineTraceSingleByObjectType(Body, From, PawnEnd, FCollisionObjectQueryParams(ECC_Pawn), Params))
	{
		if (const APawn* Pawn = Cast<APawn>(Body.GetActor()))
		{
			Pick.Kind = FVerseDeckPick::EKind::Crew;
			Pick.Point = Body.ImpactPoint;
			Pick.Actor = Body.GetActor();
			return Pick;
		}
	}
	if (!bHit)
	{
		return Pick;
	}
	Pick.Point = Hit.ImpactPoint;
	Pick.Actor = Hit.GetActor();
	if (const APawn* Pawn = Cast<APawn>(Hit.GetActor()))
	{
		Pick.Kind = FVerseDeckPick::EKind::Crew;
		return Pick;
	}
	if (const FVerseDeckStation* Station = StationNear(Hit.ImpactPoint, StationPickCm))
	{
		Pick.Kind = FVerseDeckPick::EKind::Station;
		Pick.Station = Station->Id;
		return Pick;
	}
	Pick.Kind = FVerseDeckPick::EKind::Wall;
	if (Hit.ImpactNormal.Z >= 0.7)
	{
		// Level and at the deck's floor height: floor. A wall top or a console top seen from above is not.
		const TOptional<FVector> Floor = Nav.IsComplete() ? Nav.NearestWalkable(FVector2D(Hit.ImpactPoint.X, Hit.ImpactPoint.Y), Verse::DeckWalk::ClickSnapCm) : TOptional<FVector>(Hit.ImpactPoint);
		if (Floor.IsSet() && FMath::Abs(Floor->Z - Hit.ImpactPoint.Z) <= FloorAboveRoomCm)
		{
			Pick.Kind = FVerseDeckPick::EKind::Floor;
		}
	}
	return Pick;
}

// -------------------------------------------------------------------------------------------------
// Frame

void UVerseDeckControlComponent::UpdatePointer()
{
	FVerseDeckPointerState Next;
	const bool bFocused = WindowFocused ? WindowFocused() : FApp::HasFocus();
	if (!bActive || !Camera.IsValid())
	{
		Pointer = Next;
		return;
	}
	if (IsEyeLevel())
	{
		Next.bReticle = bMouseLook;
		Next.bClickToLook = !bMouseLook && bFocused;
		if (bMouseLook)
		{
			const FVerseDeckPick Pick = PickAt(GetViewportSize() * 0.5);
			Next.bReticleMarked = Pick.Kind == FVerseDeckPick::EKind::Crew || Pick.Kind == FVerseDeckPick::EKind::Station;
			if (Pick.Kind == FVerseDeckPick::EKind::Crew)
			{
				Next.HoverCrew = Pick.Actor;
			}
		}
		Pointer = Next;
		return;
	}
	TOptional<FVector2D> Mouse = MousePosition ? MousePosition() : TOptional<FVector2D>();
	if (!MousePosition)
	{
		if (const APlayerController* Controller = Cast<APlayerController>(GetOwner()))
		{
			float X = 0.f;
			float Y = 0.f;
			if (Controller->GetMousePosition(X, Y))
			{
				Mouse = FVector2D(X, Y);
			}
		}
	}
	if (Mouse.IsSet())
	{
		const FVerseDeckPick Pick = PickAt(Mouse.GetValue());
		if (Pick.Kind == FVerseDeckPick::EKind::Crew)
		{
			Next.HoverCrew = Pick.Actor;
		}
		else if (Pick.Kind == FVerseDeckPick::EKind::Station)
		{
			if (const FVerseDeckStation* Station = Manifest.FindStation(Pick.Station))
			{
				Next.HoverStation = Station->Id;
				Next.HoverLabel = StationLabel ? StationLabel(*Station) : DefaultStationLabel(*Station);
				Next.LabelScreen = Mouse.GetValue() + FVector2D(18.0, -28.0);
			}
		}
	}
	Pointer = Next;
}

void UVerseDeckControlComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	if (Deck.IsNone())
	{
		return;
	}
	// The hangar as an arena belongs to the duel: hand the person's pawn back, and take it again after (D-11).
	const UVerseHangarSwitchSubsystem* Switch = UVerseHangarSwitchSubsystem::Get(this);
	const bool bArena = Switch && (Switch->IsArenaOn() || Switch->IsSwitching());
	if (bArena != bArenaWas)
	{
		bArenaWas = bArena;
		if (!bArena)
		{
			// Back from the duel: the commander stands where the duel body stood.
			const APlayerController* Controller = Cast<APlayerController>(GetOwner());
			const APawn* Pawn = Controller ? Controller->GetPawn() : nullptr;
			if (Pawn && Pawn != Commander.Get() && Commander.IsValid())
			{
				float Radius = 0.f;
				float HalfHeight = 0.f;
				Pawn->GetSimpleCollisionCylinder(Radius, HalfHeight);
				Commander->PlaceAt(Pawn->GetActorLocation() - FVector(0.0, 0.0, HalfHeight), Pawn->GetActorRotation().Yaw);
			}
			Orders.Arrive(Deck);
		}
		SetDeckActive(!bArena);
	}
	if (!bActive)
	{
		return;
	}
	StepNav(VerseDeckControlPrivate::NavRowsPerFrame);

	// Losing focus lets go of every held key (K-01, K-07).
	const bool bFocused = WindowFocused ? WindowFocused() : FApp::HasFocus();
	if (!bFocused && bWasFocused)
	{
		MoveAxes = FVector2D::ZeroVector;
		bHurry = false;
		bPressed = false;
		SetMouseLook(false);
		if (bPower)
		{
			bPower = false;
			OnPower.Broadcast(false);
		}
	}
	bWasFocused = bFocused;

	AVerseDeckCamera* Cam = Camera.Get();
	AVerseDeckCommander* Body = Commander.Get();
	if (Cam && Body)
	{
		if (Cam->GetView() == EVerseDeckView::Overview)
		{
			// The bird's-eye view: the keys pan the map (V-14); the commander keeps any walk.
			Cam->Pan(MoveAxes, DeltaTime);
			Body->Drive(FVector2D::ZeroVector, bHurry, Cam->Rig.YawDeg, false);
		}
		else
		{
			if (!MoveAxes.IsNearlyZero())
			{
				// The keys take over from a walk order.
				Orders.Clear();
			}
			Body->Drive(MoveAxes, bHurry, Cam->Rig.YawDeg, true);
		}
		// Never lost below the deck: a body that fell for a second stands again where it last stood.
		if (Body->GetCharacterMovement()->IsFalling())
		{
			FallingS += DeltaTime;
			if (FallingS > 1.0)
			{
				Body->PlaceAt(LastGoodFeet, Body->GetActorRotation().Yaw);
				FallingS = 0.0;
			}
		}
		else
		{
			FallingS = 0.0;
			LastGoodFeet = Body->GetFeet();
		}
		// First person looks out of the body; a camera pressed close by a wall would look into it.
		const bool bEyes = Cam->GetView() != EVerseDeckView::Overview && (Cam->Rig.FirstShare > 0.5 || Cam->Rig.ActualCm < VerseDeckControlPrivate::BodyHideCm);
		Body->SetBodyVisible(!bEyes);
	}
	UpdatePointer();
}

FString UVerseDeckControlComponent::StateJson() const
{
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("deck"), Deck.ToString());
	Root->SetBoolField(TEXT("active"), bActive);
	Root->SetBoolField(TEXT("mouse_look"), bMouseLook);
	Root->SetStringField(TEXT("view"), Camera.IsValid() ? Verse::DeckView::Name(Camera->GetView()) : TEXT("none"));
	const AVerseDeckCommander* Body = Commander.Get();
	Root->SetBoolField(TEXT("walking"), Body && Body->IsWalking());
	if (Body)
	{
		const FVector Feet = Body->GetFeet();
		Root->SetStringField(TEXT("feet"), FString::Printf(TEXT("%.0f %.0f %.0f"), Feet.X, Feet.Y, Feet.Z));
		if (const TOptional<FVector> Goal = Body->GetWalkGoal())
		{
			Root->SetStringField(TEXT("goal"), FString::Printf(TEXT("%.0f %.0f %.0f"), Goal->X, Goal->Y, Goal->Z));
		}
		Root->SetStringField(TEXT("uniform"), Body->GetUniform().ToString());
		Root->SetBoolField(TEXT("saluting"), Body->IsSaluting());
	}
	Root->SetStringField(TEXT("selected"), Selected.IsValid() ? Selected->GetName() : FString());
	Root->SetNumberField(TEXT("nav_rows"), Nav.NumRows());
	Root->SetNumberField(TEXT("nav_walkable"), Nav.NumWalkable());
	Root->SetBoolField(TEXT("nav_complete"), Nav.IsComplete());
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}

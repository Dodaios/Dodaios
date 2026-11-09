#include "Core/VerseUiSubsystem.h"

#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "CanvasItem.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/VerseUiDefaultPorts.h"
#include "Core/VerseUiTheme.h"
#include "Input/VerseDeckControlComponent.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "Engine/World.h"
#include "EnhancedInputSubsystems.h"
#include "Events/VerseEventHub.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Character.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/HUD.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "HAL/IConsoleManager.h"
#include "Menus/SVerseUiRoot.h"
#include "Misc/App.h"
#include "Misc/ConfigCacheIni.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "QA/VerseUiQaCommands.h"
#include "Scalability.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Subsystems/WorldSubsystem.h"
#include "UObject/UnrealType.h"
#include "VerseLog.h"

/** Routes key presses to the UI before the game sees them; passes every key the UI does not use. */
class FVerseUiInputProcessor : public IInputProcessor
{
public:
	explicit FVerseUiInputProcessor(UVerseUiSubsystem* InOwner) : Owner(InOwner) {}

	virtual void Tick(const float DeltaTime, FSlateApplication& SlateApp, TSharedRef<ICursor> Cursor) override {}

	virtual bool HandleKeyDownEvent(FSlateApplication& SlateApp, const FKeyEvent& InKeyEvent) override
	{
		return !InKeyEvent.IsRepeat() && Owner.IsValid() && Owner->HandleKey(InKeyEvent.GetKey());
	}

	/** Mouse buttons finish a pending rebind (fire and ADS default to them); else they pass. */
	virtual bool HandleMouseButtonDownEvent(FSlateApplication& SlateApp, const FPointerEvent& MouseEvent) override
	{
		return Owner.IsValid() && Owner->IsListeningForKey() && Owner->HandleKey(MouseEvent.GetEffectingButton());
	}

	virtual bool HandleMouseWheelOrGestureEvent(FSlateApplication& SlateApp, const FPointerEvent& InWheelEvent, const FPointerEvent* InGestureEvent) override
	{
		if (!Owner.IsValid() || !Owner->IsListeningForKey() || InWheelEvent.GetWheelDelta() == 0.f)
		{
			return false;
		}
		return Owner->HandleKey(InWheelEvent.GetWheelDelta() > 0.f ? EKeys::MouseScrollUp : EKeys::MouseScrollDown);
	}

	virtual const TCHAR* GetDebugName() const override { return TEXT("VerseUiInput"); }

	TWeakObjectPtr<UVerseUiSubsystem> Owner;
};

namespace
{
	/** UVerseSettings (combat-state 8) as VerseGore reads it; VerseUI cannot include Verse. */
	const TCHAR* VerseSettingsSection = TEXT("/Script/Verse.VerseSettings");
	const TCHAR* VerseSettingsClass = TEXT("/Script/Verse.VerseSettings");
	const TCHAR* VerseGoreSubsystemClass = TEXT("/Script/VerseGore.VerseGoreSubsystem");

	/**
	 * Console variables mirroring the view settings (duel FOV, sensitivity, invert Y, deck FOVs,
	 * reduced motion, volume) for QA. The contracted values are the UVerseSettings fields of
	 * combat-state.md 8 (WriteViewSettings); gore goes there too and the key bindings into
	 * Enhanced Input.
	 */
	void PublishCVar(const TCHAR* Name, const FString& Value, const TCHAR* Help)
	{
		IConsoleManager& Console = IConsoleManager::Get();
		IConsoleVariable* Var = Console.FindConsoleVariable(Name);
		if (!Var)
		{
			Var = Console.RegisterConsoleVariable(Name, Value, Help, ECVF_Default);
		}
		if (Var)
		{
			Var->Set(*Value, ECVF_SetByCode);
		}
	}
}

UVerseUiSubsystem* UVerseUiSubsystem::Get(const UObject* WorldContextObject)
{
	UWorld* World = WorldContextObject ? WorldContextObject->GetWorld() : nullptr;
	return World ? World->GetSubsystem<UVerseUiSubsystem>() : nullptr;
}

bool UVerseUiSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	// Client runtime only (architecture.md): a dedicated server has no person to show a UI to.
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE)
		&& !IsRunningDedicatedServer() && World->GetNetMode() != NM_DedicatedServer && Super::ShouldCreateSubsystem(Outer);
}

void UVerseUiSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseEventHub>();

	UserSettings = NewObject<UVerseUiUserSettings>(this);
	UserSettings->ReloadFromDisk();

	BridgePort = MakeShared<FVerseUiLogBridgePort>();
	GamePort = MakeShared<FVerseUiQaGamePort>(GetWorld());
	HudSource = MakeShared<FVerseUiWorldHudSource>(GetWorld());

	LoadData();
	KeyMap.SetBindings(UserSettings->KeyBindings);
	KeyMap.SetReturnKey(AppSettings.ReturnKey);
	Armoury.SelectTier(UserSettings->LastTier);
	Hud.Timing.FeedMax = FMath::Max(1, Hud.Timing.FeedMax);

	KillCam.OnReplayFire = [this](const FVerseFireEvent& E)
	{
		AddReplayBolt(E);
		if (OnKillCamFire)
		{
			OnKillCamFire(E);
		}
	};
	KillCam.OnReplayFracture = [this](const FVerseFractureEvent& E) { if (OnKillCamFracture) { OnKillCamFracture(E); } };

	BindHub();
	PostRenderHandle = AHUD::OnHUDPostRender.AddUObject(this, &UVerseUiSubsystem::OnHudPostRender);

	VerseUiQa::RegisterCommands(this);

	// Publish the settings other modules read.
	SetAppSettings(AppSettings);
	SetDuelFov(UserSettings->DuelFov);
}

void UVerseUiSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	BindHub();
	AttachSlate();
	// The saved quality level applies at start, not only when the menu changes it.
	if (!FApp::IsUnattended() && FApp::CanEverRender())
	{
		ApplyScalabilityLevel(UserSettings->Scalability);
	}
}

void UVerseUiSubsystem::Deinitialize()
{
	ApplyKillCamView(false);
	if (bPausedByUi)
	{
		GamePort->SetPaused(false);
		bPausedByUi = false;
	}
	DetachSlate();
	UnbindHub();
	AHUD::OnHUDPostRender.Remove(PostRenderHandle);
	VerseUiQa::Release(this);
	Super::Deinitialize();
}

TStatId UVerseUiSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseUiSubsystem, STATGROUP_Tickables);
}

double UVerseUiSubsystem::LocalNow() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

void UVerseUiSubsystem::LoadData()
{
	FString Error;
	if (!Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir(), &Error))
	{
		UE_LOG(LogVerseUI, Error, TEXT("VerseUI: %s"), *Error);
	}
	if (!KeyMap.LoadFile(FVerseKeyMap::DefaultPath(), &Error))
	{
		UE_LOG(LogVerseUI, Error, TEXT("VerseUI: %s"), *Error);
	}
	if (!Armoury.LoadFile(FVerseArmouryModel::DefaultPath(), &Error))
	{
		UE_LOG(LogVerseUI, Error, TEXT("VerseUI: %s"), *Error);
	}

	FString Json;
	const FString HudPath = FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"), TEXT("hud.json"));
	TSharedPtr<FJsonObject> Root;
	if (FFileHelper::LoadFileToString(Json, *HudPath) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Json), Root) && Root.IsValid())
	{
		double N = 0.0;
		if (Root->TryGetNumberField(TEXT("safe_fraction"), N))
		{
			SafeFraction = float(N);
		}
		const TSharedPtr<FJsonObject>* Timing = nullptr;
		if (Root->TryGetObjectField(TEXT("timing"), Timing))
		{
			FVerseHudTiming& T = Hud.Timing;
			if ((*Timing)->TryGetNumberField(TEXT("hit_marker_s"), N)) { T.HitMarker = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("headshot_marker_s"), N)) { T.HeadshotMarker = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("kill_marker_s"), N)) { T.KillMarker = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("blocked_marker_s"), N)) { T.BlockedMarker = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("damage_indicator_s"), N)) { T.DamageIndicator = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("feed_entry_s"), N)) { T.FeedEntry = float(N); }
			if ((*Timing)->TryGetNumberField(TEXT("feed_max"), N)) { T.FeedMax = int32(N); }
			if ((*Timing)->TryGetNumberField(TEXT("set_target"), N)) { T.SetTarget = int32(N); }
		}
		const TSharedPtr<FJsonObject>* Cam = nullptr;
		if (Root->TryGetObjectField(TEXT("kill_cam"), Cam))
		{
			FVerseKillCamTuning& T = KillCam.Tuning;
			if ((*Cam)->TryGetNumberField(TEXT("window_s"), N)) { KillCamBuffer.Window = N; }
			if ((*Cam)->TryGetNumberField(TEXT("end_margin_s"), N)) { T.EndMarginS = float(N); }
			if ((*Cam)->TryGetNumberField(TEXT("min_length_s"), N)) { T.MinLengthS = float(N); }
			if ((*Cam)->TryGetNumberField(TEXT("camera_back_cm"), N)) { T.CameraBack = float(N); }
			if ((*Cam)->TryGetNumberField(TEXT("camera_up_cm"), N)) { T.CameraUp = float(N); }
			if ((*Cam)->TryGetNumberField(TEXT("camera_right_cm"), N)) { T.CameraRight = float(N); }
			if ((*Cam)->TryGetNumberField(TEXT("finisher_cut_s"), N)) { T.FinisherCutS = float(N); }
		}
		const TArray<TSharedPtr<FJsonValue>>* DeckList = nullptr;
		if (Root->TryGetArrayField(TEXT("decks"), DeckList))
		{
			Decks.Reset();
			for (const TSharedPtr<FJsonValue>& V : *DeckList)
			{
				Decks.Add(FName(*V->AsString()));
			}
		}
	}
	else
	{
		UE_LOG(LogVerseUI, Error, TEXT("VerseUI: cannot read %s"), *HudPath);
	}
}

// ---------------------------------------------------------------------------------------------
// Hub

void UVerseUiSubsystem::BindHub()
{
	UVerseEventHub* HubPtr = UVerseEventHub::Get(GetWorld());
	if (!HubPtr || BoundHub.Get() == HubPtr)
	{
		return;
	}
	UnbindHub();
	BoundHub = HubPtr;
	HubHandles.Add(HubPtr->OnHit.AddUObject(this, &UVerseUiSubsystem::HandleHit));
	HubHandles.Add(HubPtr->OnDeath.AddUObject(this, &UVerseUiSubsystem::HandleDeath));
	HubHandles.Add(HubPtr->OnSetEnded.AddUObject(this, &UVerseUiSubsystem::HandleSetEnded));
	HubHandles.Add(HubPtr->OnFire.AddUObject(this, &UVerseUiSubsystem::HandleFire));
	HubHandles.Add(HubPtr->OnFracture.AddUObject(this, &UVerseUiSubsystem::HandleFracture));
	HubHandles.Add(HubPtr->OnStationUsed.AddUObject(this, &UVerseUiSubsystem::HandleStationUsed));
	HubHandles.Add(HubPtr->OnArenaSwitch.AddLambda([this](const FVerseArenaSwitchEvent& E)
		{
			if (FVerseUiQaGamePort* Qa = static_cast<FVerseUiQaGamePort*>(GamePort.Get()); Qa && bOwnsGamePort)
			{
				Qa->NoteArenaSwitch(E.bArenaOn, E.Deck);
			}
			if (!E.bArenaOn)
			{
				Hud.Reset();
			}
			RebuildScreen();
		}));
}

void UVerseUiSubsystem::UnbindHub()
{
	if (UVerseEventHub* HubPtr = BoundHub.Get())
	{
		FDelegateHandle* H = HubHandles.GetData();
		HubPtr->OnHit.Remove(H[0]);
		HubPtr->OnDeath.Remove(H[1]);
		HubPtr->OnSetEnded.Remove(H[2]);
		HubPtr->OnFire.Remove(H[3]);
		HubPtr->OnFracture.Remove(H[4]);
		HubPtr->OnStationUsed.Remove(H[5]);
		HubPtr->OnArenaSwitch.Remove(H[6]);
	}
	HubHandles.Reset();
	BoundHub.Reset();
}

void UVerseUiSubsystem::HandleHit(const FVerseHitEvent& Event)
{
	Hud.SetLocalPlayerId(HudSource->GetLocalPlayerId());
	Hud.OnHit(Event, LocalNow());
	if (Event.VictimId == Hud.GetLocalPlayerId() && !Event.bBlockedBySpawnProtection)
	{
		TrackedHealth = FMath::Max(0.f, TrackedHealth - Event.Damage);
	}
}

void UVerseUiSubsystem::HandleDeath(const FVerseDeathEvent& Event)
{
	const int32 LocalId = HudSource->GetLocalPlayerId();
	Hud.SetLocalPlayerId(LocalId);
	const double Now = LocalNow();
	Hud.OnDeath(Event, Now);
	if (Event.VictimId == LocalId)
	{
		TrackedHealth = 0.f;
		// Record the killer's last pose of this frame before the clip is copied.
		TArray<FVersePawnPose> Poses;
		HudSource->GetPawnPoses(Poses);
		const double Server = HudSource->GetServerTime();
		for (const FVersePawnPose& Pose : Poses)
		{
			KillCamBuffer.AddPose(Pose.PlayerId, Pose.ServerTime >= 0.0 ? Pose.ServerTime : Server, Pose.Location, Pose.Rotation);
		}
		ReplayBolts.Reset();
		if (KillCam.Begin(KillCamBuffer, Event, LocalId, Now, Server, AppSettings.Gore == EVerseGoreLevel::Reduced))
		{
			ApplyKillCamView(true);
		}
	}
}

void UVerseUiSubsystem::HandleSetEnded(const FVerseSetSummary& Summary)
{
	Hud.OnSetEnded(Summary, LocalNow());
	if (Summary.Outcome == EVerseSetOutcome::Unfinished)
	{
		return;
	}
	Session.AddSet(Summary);
	EndScreen = FVerseEndScreen::Build(Summary, HudSource->GetBotEffectiveSkill(Summary.Opponent.PlayerId), Strings.GetLanguage());
	ShowScreen(EVerseUiScreen::EndOfSet);
}

void UVerseUiSubsystem::HandleFire(const FVerseFireEvent& Event)
{
	KillCamBuffer.AddFire(Event, Event.ServerTime);
}

void UVerseUiSubsystem::HandleFracture(const FVerseFractureEvent& Event)
{
	KillCamBuffer.AddFracture(Event, Event.ServerTimeMs / 1000.0);
}

void UVerseUiSubsystem::HandleStationUsed(const FVerseStationUsedEvent& Event)
{
	if (Event.Kind == FName(TEXT("armoury")) && (Event.UserId == HudSource->GetLocalPlayerId() || HudSource->GetLocalPlayerId() == INDEX_NONE))
	{
		ShowScreen(EVerseUiScreen::Armoury);
	}
}

// ---------------------------------------------------------------------------------------------
// Tick

void UVerseUiSubsystem::Tick(float DeltaTime)
{
	const double Now = LocalNow();
	const double Server = HudSource->GetServerTime();
	const int32 LocalId = HudSource->GetLocalPlayerId();
	Hud.SetLocalPlayerId(LocalId);
	const bool bWasDead = Hud.IsLocalDead();
	Hud.Tick(Now, Server);
	if (bWasDead && !Hud.IsLocalDead())
	{
		TrackedHealth = 100.f;
	}

	TArray<FVersePawnPose> Poses;
	HudSource->GetPawnPoses(Poses);
	for (const FVersePawnPose& Pose : Poses)
	{
		KillCamBuffer.AddPose(Pose.PlayerId, Pose.ServerTime >= 0.0 ? Pose.ServerTime : Server, Pose.Location, Pose.Rotation);
	}
	KillCamBuffer.Trim(Server);
	TickKillCam(Now);
	ReplayBolts.RemoveAll([Now](const FReplayBolt& Bolt) { return Now - Bolt.LocalTime > ReplayBoltLife; });

	// Key bindings follow the contexts the input owners add after possession.
	if (Now >= NextInputRemapAt)
	{
		NextInputRemapAt = Now + 0.25;
		ApplyKeyBindingsToInput();
	}

	const bool bDuel = GamePort->IsDuelRunning();
	if (bDuel != bLastDuelRunning)
	{
		bLastDuelRunning = bDuel;
		RebuildScreen();
	}
}

void UVerseUiSubsystem::TickKillCam(double Now)
{
	if (!KillCam.IsPlaying())
	{
		return;
	}
	KillCam.Tick(Now);
	if (!KillCam.IsPlaying())
	{
		ApplyKillCamView(false);
		return;
	}
	FVector Location;
	FRotator Rotation;
	if (KillCamCamera && KillCam.GetCamera(Location, Rotation))
	{
		KillCamCamera->SetActorLocationAndRotation(Location, Rotation);
	}
	FVector KillerLocation;
	FRotator KillerRotation;
	if (KillCamProxy && KillCam.GetKillerPose(KillerLocation, KillerRotation))
	{
		// The proxy root stands for the recorded capsule; the mesh copy keeps the pawn's mesh offset.
		KillCamProxy->SetActorLocationAndRotation(KillerLocation, FRotator(0.f, KillerRotation.Yaw, 0.f));
	}
}

void UVerseUiSubsystem::ApplyKillCamView(bool bStart)
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (bStart)
	{
		if (!PC || !World->HasBegunPlay())
		{
			return;
		}
		FActorSpawnParameters Params;
		Params.ObjectFlags |= RF_Transient;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		if (!KillCamCamera)
		{
			KillCamCamera = World->SpawnActor<ACameraActor>(Params);
		}
		if (KillCamCamera)
		{
			KillCamCamera->GetCameraComponent()->SetFieldOfView(AppSettings.FovThird);
			KillCamCamera->GetCameraComponent()->bConstrainAspectRatio = false;
			KillCamPreviousTarget = PC->GetViewTarget();
			PC->SetViewTargetWithBlend(KillCamCamera, 0.f);
		}
		// The replayed killer: a pose-following copy of the killer's mesh at the recorded path
		// (WP13's clips replace the live pose once they land); the live killer hides locally.
		APlayerState* KillerState = nullptr;
		if (AGameStateBase* GameState = World->GetGameState())
		{
			for (APlayerState* State : GameState->PlayerArray)
			{
				if (State && State->GetPlayerId() == KillCam.GetKillerId())
				{
					KillerState = State;
				}
			}
		}
		APawn* Killer = KillerState ? KillerState->GetPawn() : nullptr;
		USkeletalMeshComponent* KillerMesh = Killer ? Killer->FindComponentByClass<USkeletalMeshComponent>() : nullptr;
		if (KillerMesh && KillerMesh->GetSkeletalMeshAsset())
		{
			KillCamProxy = SpawnKillCamProxy(World, Params, Killer, KillerMesh);
			// Hide the live killer in this view only: PlayerController::HiddenActors is local
			// and never replicated (AActor::bHidden is, and the person hosts the duel).
			PC->HiddenActors.AddUnique(Killer);
			KillCamHiddenKiller = Killer;
		}
		return;
	}

	if (PC && KillCamCamera && PC->GetViewTarget() == KillCamCamera)
	{
		AActor* Back = KillCamPreviousTarget.IsValid() ? KillCamPreviousTarget.Get() : PC->GetPawn();
		PC->SetViewTargetWithBlend(Back ? Back : PC, AppSettings.bReducedMotion ? 0.f : 0.15f);
	}
	if (KillCamProxy)
	{
		KillCamProxy->Destroy();
		KillCamProxy = nullptr;
	}
	if (PC)
	{
		PC->HiddenActors.Remove(KillCamHiddenKiller.Get());
		PC->HiddenActors.RemoveAll([](const TObjectPtr<AActor>& Actor) { return !IsValid(Actor); });
	}
	KillCamHiddenKiller.Reset();
	ReplayBolts.Reset();
}

AActor* UVerseUiSubsystem::SpawnKillCamProxy(UWorld* World, const FActorSpawnParameters& Params, const APawn* Killer, USkeletalMeshComponent* KillerMesh)
{
	AActor* Proxy = World ? World->SpawnActor<AActor>(Params) : nullptr;
	if (!Proxy || !Killer || !KillerMesh)
	{
		return Proxy;
	}
	// Root = the capsule centre the buffer records; the mesh hangs under it with the pawn's own
	// offset (AVerseCharacter: -half height in Z, -90 deg yaw). On a character the base offsets
	// are used, so a network smoothing offset of the live mesh is not copied.
	USceneComponent* Root = NewObject<USceneComponent>(Proxy, TEXT("KillCamRoot"));
	Proxy->SetRootComponent(Root);
	Root->RegisterComponent();
	FTransform MeshOffset = KillerMesh->GetRelativeTransform();
	if (const ACharacter* Character = Cast<ACharacter>(Killer); Character && Character->GetMesh() == KillerMesh)
	{
		MeshOffset = FTransform(Character->GetBaseRotationOffset(), Character->GetBaseTranslationOffset(), KillerMesh->GetRelativeScale3D());
	}
	USkeletalMeshComponent* Copy = NewObject<USkeletalMeshComponent>(Proxy, TEXT("KillCamMesh"));
	Copy->SetSkeletalMeshAsset(KillerMesh->GetSkeletalMeshAsset());
	Copy->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Copy->SetupAttachment(Root);
	Copy->SetRelativeTransform(MeshOffset);
	Copy->RegisterComponent();
	Copy->SetLeaderPoseComponent(KillerMesh);
	Proxy->SetActorLocationAndRotation(Killer->GetActorLocation(), FRotator(0.f, Killer->GetActorRotation().Yaw, 0.f));
	return Proxy;
}

// ---------------------------------------------------------------------------------------------
// HUD drawing

FVerseUiLayout UVerseUiSubsystem::ComputeLayout(const FVector2D& Viewport) const
{
	FDisplayMetrics Metrics;
	FMargin Padding(0.f);
	if (FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().GetCachedDisplayMetrics(Metrics);
		Padding = FMargin(Metrics.TitleSafePaddingSize.X, Metrics.TitleSafePaddingSize.Y, Metrics.TitleSafePaddingSize.Z, Metrics.TitleSafePaddingSize.W);
	}
	return FVerseUiLayout::Compute(Viewport, SafeFraction, Padding, UserSettings ? UserSettings->TextScale : 1.f);
}

void UVerseUiSubsystem::BuildHudFrame(const FVector2D& Viewport, FVerseHudDrawList& Out) const
{
	FVerseHudFrame Frame;
	Frame.Model = &Hud;
	Frame.Strings = &Strings;
	Frame.Source = HudSource.Get();
	Frame.Layout = ComputeLayout(Viewport);
	HudSource->GetPawnState(Frame.Pawn);
	if (!Frame.Pawn.bHealthKnown)
	{
		Frame.Pawn.Health = TrackedHealth;
		Frame.Pawn.MaxHealth = 100.f;
	}
	Frame.bHasView = HudSource->GetView(Frame.View);
	Frame.Now = LocalNow();
	Frame.ServerTime = HudSource->GetServerTime();
	Frame.bKillCam = KillCam.IsPlaying();
	Frame.KillCamKillerId = KillCam.GetKillerId();
	Frame.SkipKeyName = KeyMap.GetKey(TEXT("skip_kill_cam")).GetDisplayName();
	Frame.bReducedMotion = AppSettings.bReducedMotion;
	Frame.bInDuel = GamePort->IsDuelRunning();
	FVerseHudPainter::Paint(Frame, Out, FVerseHudPainter::DefaultMeasure());
}

void UVerseUiSubsystem::OnHudPostRender(AHUD* InHud, UCanvas* Canvas)
{
	if (!bDrawHudOnPostRender || !InHud || !Canvas || InHud->GetWorld() != GetWorld() || !InHud->PlayerOwner || !InHud->PlayerOwner->IsLocalController())
	{
		return;
	}
	const double Start = FPlatformTime::Seconds();
	BuildHudFrame(FVector2D(Canvas->ClipX, Canvas->ClipY), LastDrawList);
	FVerseHudCanvasRenderer::Render(Canvas, LastDrawList);
	DrawReplayBolts(Canvas);
	HudCostAccum += (FPlatformTime::Seconds() - Start) * 1000.0;
	if (++HudCostFrames >= 120)
	{
		HudCostMs = HudCostAccum / HudCostFrames;
		HudCostAccum = 0.0;
		HudCostFrames = 0;
	}
}

void UVerseUiSubsystem::AddReplayBolt(const FVerseFireEvent& Event)
{
	FReplayBolt Bolt;
	Bolt.Start = Event.Origin;
	Bolt.End = Bolt.Start + FVector(Event.Direction).GetSafeNormal() * 10000.0;
	Bolt.LocalTime = LocalNow();
	if (UWorld* World = GetWorld())
	{
		FCollisionQueryParams Query(SCENE_QUERY_STAT(VerseKillCamBolt), false);
		if (KillCamProxy)
		{
			Query.AddIgnoredActor(KillCamProxy);
		}
		FHitResult Hit;
		if (World->LineTraceSingleByChannel(Hit, Bolt.Start, Bolt.End, ECC_Visibility, Query))
		{
			Bolt.End = Hit.ImpactPoint;
		}
	}
	ReplayBolts.Add(Bolt);
}

void UVerseUiSubsystem::DrawReplayBolts(UCanvas* Canvas)
{
	if (!KillCam.IsPlaying() || ReplayBolts.Num() == 0)
	{
		return;
	}
	const double Now = LocalNow();
	for (const FReplayBolt& Bolt : ReplayBolts)
	{
		const double Age = Now - Bolt.LocalTime;
		if (Age < 0.0 || Age > ReplayBoltLife)
		{
			continue;
		}
		const FVector A = Canvas->Project(Bolt.Start, false);
		const FVector B = Canvas->Project(Bolt.End, false);
		if (A.Z <= 0.0 || B.Z <= 0.0)
		{
			continue;
		}
		FLinearColor Colour = VerseUiTheme::Amber;
		Colour.A = float(1.0 - Age / ReplayBoltLife);
		FCanvasLineItem Line(FVector2D(A.X, A.Y), FVector2D(B.X, B.Y));
		Line.SetColor(Colour);
		Line.LineThickness = 2.f;
		Line.BlendMode = SE_BLEND_Translucent;
		Canvas->DrawItem(Line);
	}
}

// ---------------------------------------------------------------------------------------------
// Slate

void UVerseUiSubsystem::AttachSlate()
{
	UWorld* World = GetWorld();
	UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr;
	if (!Viewport || SlateRoot.IsValid() || !FSlateApplication::IsInitialized())
	{
		return;
	}
	SlateRoot = SNew(SVerseUiRoot, this);
	Viewport->AddViewportWidgetContent(SlateRoot.ToSharedRef(), 20);
	InputProcessor = MakeShared<FVerseUiInputProcessor>(this);
	FSlateApplication::Get().RegisterInputPreProcessor(InputProcessor);
}

void UVerseUiSubsystem::DetachSlate()
{
	if (InputProcessor.IsValid() && FSlateApplication::IsInitialized())
	{
		FSlateApplication::Get().UnregisterInputPreProcessor(InputProcessor);
	}
	InputProcessor.Reset();
	if (SlateRoot.IsValid())
	{
		UWorld* World = GetWorld();
		if (UGameViewportClient* Viewport = World ? World->GetGameViewport() : nullptr)
		{
			Viewport->RemoveViewportWidgetContent(SlateRoot.ToSharedRef());
		}
	}
	SlateRoot.Reset();
}

void UVerseUiSubsystem::RebuildScreen()
{
	if (SlateRoot.IsValid())
	{
		SlateRoot->Refresh();
	}
}

void UVerseUiSubsystem::ApplyInputMode()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	if (!PC || !SlateRoot.IsValid())
	{
		return;
	}
	if (Screen != EVerseUiScreen::None)
	{
		FInputModeGameAndUI Mode;
		Mode.SetWidgetToFocus(SlateRoot);
		Mode.SetHideCursorDuringCapture(false);
		PC->SetInputMode(Mode);
		PC->SetShowMouseCursor(true);
	}
	else
	{
		PC->SetInputMode(FInputModeGameOnly());
		PC->SetShowMouseCursor(false);
	}
}

void UVerseUiSubsystem::ShowScreen(EVerseUiScreen InScreen)
{
	Screen = InScreen;
	if (SlateRoot.IsValid())
	{
		SlateRoot->StopListening();
	}
	RebuildScreen();
	ApplyInputMode();
	UpdatePause();
	OnScreenChanged.Broadcast(Screen);
}

void UVerseUiSubsystem::UpdatePause()
{
	// Escape mid-match pauses (parity D-09); so does the end-of-set screen, so the endless match
	// does not go on behind a panel. The match resumes when the screen closes.
	const bool bWant = GamePort->IsDuelRunning()
		&& (Screen == EVerseUiScreen::EscMenu || Screen == EVerseUiScreen::Settings || Screen == EVerseUiScreen::EndOfSet);
	if (bWant != bPausedByUi)
	{
		bPausedByUi = bWant;
		GamePort->SetPaused(bWant);
	}
}

// ---------------------------------------------------------------------------------------------
// Bridge and settings

void UVerseUiSubsystem::SetBridgePort(TSharedPtr<IVerseUiBridgePort> Port)
{
	BridgePort = Port.IsValid() ? Port : MakeShared<FVerseUiLogBridgePort>();
}

void UVerseUiSubsystem::SetGamePort(TSharedPtr<IVerseUiGamePort> Port)
{
	bOwnsGamePort = !Port.IsValid();
	GamePort = Port.IsValid() ? Port : MakeShared<FVerseUiQaGamePort>(GetWorld());
	RebuildScreen();
}

void UVerseUiSubsystem::SetHudSource(TSharedPtr<IVerseHudSource> Source)
{
	HudSource = Source.IsValid() ? Source : MakeShared<FVerseUiWorldHudSource>(GetWorld());
}

void UVerseUiSubsystem::ApplyWelcome(const TSharedPtr<FJsonObject>& Data)
{
	if (!Data.IsValid())
	{
		return;
	}
	const TSharedPtr<FJsonObject>* Locale = nullptr;
	if (Data->TryGetObjectField(TEXT("locale"), Locale))
	{
		Strings.ApplyBridgeLocale(*Locale);
	}
	const TSharedPtr<FJsonObject>* Settings = nullptr;
	if (Data->TryGetObjectField(TEXT("settings"), Settings))
	{
		AppSettings.ApplyJson(*Settings);
	}
	const TArray<TSharedPtr<FJsonValue>>* DeckList = nullptr;
	if (Data->TryGetArrayField(TEXT("decks"), DeckList))
	{
		Decks.Reset();
		for (const TSharedPtr<FJsonValue>& V : *DeckList)
		{
			Decks.Add(FName(*V->AsString()));
		}
	}
	KeyMap.SetReturnKey(AppSettings.ReturnKey);
	if (LifecycleState == FName(TEXT("booting")))
	{
		LifecycleState = TEXT("visible");
	}
	PublishSettings();
	RebuildScreen();
}

void UVerseUiSubsystem::ApplySettingsChanged(const TSharedPtr<FJsonObject>& Data)
{
	if (!Data.IsValid())
	{
		return;
	}
	AppSettings.ApplyJson(Data);
	Strings.ApplySettingsChanged(Data);
	KeyMap.SetReturnKey(AppSettings.ReturnKey);
	PublishSettings();
	RebuildScreen();
}

void UVerseUiSubsystem::WriteGoreSetting(UWorld* World, EVerseGoreLevel Level)
{
	const FString Value = Level == EVerseGoreLevel::Reduced ? TEXT("Reduced") : TEXT("Full");
	if (GConfig)
	{
		FString Stored;
		if (!GConfig->GetString(VerseSettingsSection, TEXT("GoreLevel"), Stored, GGameUserSettingsIni) || Stored != Value)
		{
			GConfig->SetString(VerseSettingsSection, TEXT("GoreLevel"), *Value, GGameUserSettingsIni);
			GConfig->Flush(false, GGameUserSettingsIni);
		}
	}
	// The class default object, for code that reads GetDefault<UVerseSettings>().
	if (UClass* Class = FindObject<UClass>(nullptr, VerseSettingsClass))
	{
		if (UObject* Defaults = Class->GetDefaultObject())
		{
			if (FEnumProperty* Prop = FindFProperty<FEnumProperty>(Class, TEXT("GoreLevel")))
			{
				Prop->GetUnderlyingProperty()->SetIntPropertyValue(Prop->ContainerPtrToValuePtr<void>(Defaults), int64(Level));
			}
			else if (FByteProperty* Byte = FindFProperty<FByteProperty>(Class, TEXT("GoreLevel")))
			{
				Byte->SetPropertyValue_InContainer(Defaults, uint8(Level));
			}
		}
	}
	// Live switch (WP05.7): a live VerseGore re-reads the level when it offers the call.
	UClass* GoreClass = FindObject<UClass>(nullptr, VerseGoreSubsystemClass);
	if (World && GoreClass && GoreClass->IsChildOf(UWorldSubsystem::StaticClass()))
	{
		if (UWorldSubsystem* Gore = World->GetSubsystemBase(GoreClass))
		{
			if (UFunction* Reload = Gore->FindFunction(TEXT("ReloadLevelFromSettings")))
			{
				Gore->ProcessEvent(Reload, nullptr);
			}
		}
	}
}

EVerseGoreLevel UVerseUiSubsystem::ReadGoreSetting()
{
	// Exactly how VerseGore reads it (UVerseGoreSubsystem::ReloadLevelFromSettings).
	FString Value;
	if (GConfig && GConfig->GetString(VerseSettingsSection, TEXT("GoreLevel"), Value, GGameUserSettingsIni))
	{
		return Value.TrimStartAndEnd().Equals(TEXT("Reduced"), ESearchCase::IgnoreCase) ? EVerseGoreLevel::Reduced : EVerseGoreLevel::Full;
	}
	return EVerseGoreLevel::Full;
}

void UVerseUiSubsystem::SetAppSettings(const FVerseAppSettings& Next)
{
	const TSharedRef<FJsonObject> Diff = AppSettings.Diff(Next);
	AppSettings = Next;
	KeyMap.SetReturnKey(AppSettings.ReturnKey);
	PublishSettings();
	if (Diff->Values.Num() > 0)
	{
		BridgePort->SendSettingsSet(Diff);
	}
}

void UVerseUiSubsystem::SetGore(EVerseGoreLevel Level)
{
	FVerseAppSettings Next = AppSettings;
	Next.Gore = Level;
	SetAppSettings(Next);
}

void UVerseUiSubsystem::SetReducedMotion(bool bReduced)
{
	FVerseAppSettings Next = AppSettings;
	Next.bReducedMotion = bReduced;
	SetAppSettings(Next);
}

void UVerseUiSubsystem::SetReturnKey(const FKey& Key)
{
	RebindKey(FVerseKeyMap::ReturnAction(), Key);
}

void UVerseUiSubsystem::RebindKey(FName Action, const FKey& Key)
{
	if (FVerseKeyMap::IsReserved(Key))
	{
		return;
	}
	KeyMap.Rebind(Action, Key);
	UserSettings->KeyBindings = KeyMap.GetBindings();
	UserSettings->SaveToDisk();
	const FKey NewReturn = KeyMap.GetKey(FVerseKeyMap::ReturnAction());
	if (NewReturn != AppSettings.ReturnKey)
	{
		FVerseAppSettings Next = AppSettings;
		Next.ReturnKey = NewReturn;
		SetAppSettings(Next);
	}
	else
	{
		PublishSettings();
	}
}

void UVerseUiSubsystem::SetDuelFov(float Fov)
{
	UserSettings->DuelFov = Fov;
	UserSettings->SaveToDisk();
	PublishSettings();
}

void UVerseUiSubsystem::ApplyScalabilityLevel(int32 Level)
{
	Scalability::FQualityLevels Levels = Scalability::GetQualityLevels();
	if (Level >= 0)
	{
		Levels.SetFromSingleQualityLevel(FMath::Clamp(Level, 0, 4));
	}
	else
	{
		// Auto: the engine's default levels.
		Levels.SetDefaults();
	}
	Scalability::SetQualityLevels(Levels);
}

void UVerseUiSubsystem::SetScalability(int32 Level)
{
	UserSettings->Scalability = Level;
	UserSettings->SaveToDisk();
	if (!FApp::IsUnattended())
	{
		ApplyScalabilityLevel(UserSettings->Scalability);
	}
}

void UVerseUiSubsystem::ResetSettings()
{
	FVerseAppSettings Next = AppSettings;
	const FVerseAppSettings Defaults;
	Next.Sensitivity = Defaults.Sensitivity;
	Next.bInvertY = Defaults.bInvertY;
	Next.Quality = Defaults.Quality;
	Next.FovThird = Defaults.FovThird;
	Next.FovFirst = Defaults.FovFirst;
	Next.Volume = Defaults.Volume;
	Next.ViewMode = Defaults.ViewMode;
	SetScalability(-1);
	SetAppSettings(Next);
	RebuildScreen();
}

void UVerseUiSubsystem::SetTextScale(float Scale)
{
	UserSettings->TextScale = Scale;
	UserSettings->SaveToDisk();
	RebuildScreen();
}

namespace
{
	/**
	 * The view settings on UVerseSettings (combat-state.md 8), written like GoreLevel: into the
	 * viewer's GameUserSettings and into the class default object that readers use. VerseUI cannot
	 * include Verse, so the fields are set by name through reflection.
	 */
	void WriteViewSettings(float DuelFov, const FVerseAppSettings& S)
	{
		struct FFloatField { const TCHAR* Name; float Value; };
		struct FBoolField { const TCHAR* Name; bool bValue; };
		const FFloatField Floats[] = {
			{ TEXT("DuelFovDeg"), DuelFov },
			{ TEXT("LookSensitivity"), S.Sensitivity },
			{ TEXT("DeckFovThirdDeg"), S.FovThird },
			{ TEXT("DeckFovFirstDeg"), S.FovFirst },
			{ TEXT("MasterVolume"), S.Volume },
		};
		const FBoolField Bools[] = {
			{ TEXT("bInvertLookY"), S.bInvertY },
			{ TEXT("bReducedMotion"), S.bReducedMotion },
		};
		if (GConfig)
		{
			bool bChanged = false;
			for (const FFloatField& F : Floats)
			{
				float Stored = 0.f;
				if (!GConfig->GetFloat(VerseSettingsSection, F.Name, Stored, GGameUserSettingsIni) || !FMath::IsNearlyEqual(Stored, F.Value))
				{
					GConfig->SetFloat(VerseSettingsSection, F.Name, F.Value, GGameUserSettingsIni);
					bChanged = true;
				}
			}
			for (const FBoolField& B : Bools)
			{
				bool bStored = false;
				if (!GConfig->GetBool(VerseSettingsSection, B.Name, bStored, GGameUserSettingsIni) || bStored != B.bValue)
				{
					GConfig->SetBool(VerseSettingsSection, B.Name, B.bValue, GGameUserSettingsIni);
					bChanged = true;
				}
			}
			if (bChanged)
			{
				GConfig->Flush(false, GGameUserSettingsIni);
			}
		}
		UClass* Class = FindObject<UClass>(nullptr, VerseSettingsClass);
		UObject* Defaults = Class ? Class->GetDefaultObject() : nullptr;
		if (!Defaults)
		{
			return;
		}
		for (const FFloatField& F : Floats)
		{
			if (FFloatProperty* Prop = FindFProperty<FFloatProperty>(Class, F.Name))
			{
				Prop->SetPropertyValue_InContainer(Defaults, F.Value);
			}
		}
		for (const FBoolField& B : Bools)
		{
			if (FBoolProperty* Prop = FindFProperty<FBoolProperty>(Class, B.Name))
			{
				Prop->SetPropertyValue_InContainer(Defaults, B.bValue);
			}
		}
	}
}

void UVerseUiSubsystem::PublishSettings()
{
	PublishCVar(TEXT("Verse.Settings.DuelFov"), FString::SanitizeFloat(UserSettings ? UserSettings->DuelFov : 100.f), TEXT("Duel horizontal FOV, 80-110 (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.FovThird"), FString::SanitizeFloat(AppSettings.FovThird), TEXT("Deck third-person FOV (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.FovFirst"), FString::SanitizeFloat(AppSettings.FovFirst), TEXT("Deck first-person FOV (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.Sensitivity"), FString::SanitizeFloat(AppSettings.Sensitivity), TEXT("Look sensitivity (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.InvertY"), AppSettings.bInvertY ? TEXT("1") : TEXT("0"), TEXT("Invert look Y (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.ReducedMotion"), AppSettings.bReducedMotion ? TEXT("1") : TEXT("0"), TEXT("Reduced motion (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.Volume"), FString::SanitizeFloat(AppSettings.Volume), TEXT("Master volume 0-1 (VerseUI)"));
	WriteGoreSetting(GetWorld(), AppSettings.Gore);
	WriteViewSettings(UserSettings ? UserSettings->DuelFov : 100.f, AppSettings);
	ApplyKeyBindingsToInput();
}

int32 UVerseUiSubsystem::ApplyKeyBindingsToInput()
{
	UWorld* World = GetWorld();
	APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
	ULocalPlayer* Player = PC ? PC->GetLocalPlayer() : nullptr;
	UEnhancedInputLocalPlayerSubsystem* Input = Player ? Player->GetSubsystem<UEnhancedInputLocalPlayerSubsystem>() : nullptr;
	return InputRemap.ApplyToPlayer(Input, KeyMap);
}

// ---------------------------------------------------------------------------------------------
// Actions

void UVerseUiSubsystem::StartDuelFromArmoury()
{
	UserSettings->LastTier = Armoury.GetSelectedTier();
	UserSettings->SaveToDisk();
	Session.Reset();
	GamePort->StartDuel(Armoury.GetSelectedTier());
	ShowScreen(EVerseUiScreen::None);
}

void UVerseUiSubsystem::QuickStartDuel()
{
	Session.Reset();
	GamePort->StartDuel(UserSettings->LastTier);
	ShowScreen(EVerseUiScreen::None);
}

void UVerseUiSubsystem::LeaveDuel()
{
	// Endless sets: leaving anywhere but the end-of-set screen leaves a set open (parity D-10;
	// the duel owner reports it as unfinished, W-08). The summary shows the session and "again".
	Session.bLeftMidSet = GamePort->IsDuelRunning() && Screen != EVerseUiScreen::EndOfSet;
	if (bPausedByUi)
	{
		GamePort->SetPaused(false);
		bPausedByUi = false;
	}
	GamePort->LeaveDuel();
	SessionScreen = Session.BuildScreen(Strings.GetLanguage());
	ShowScreen(EVerseUiScreen::SessionSummary);
}

void UVerseUiSubsystem::ReturnToApp(const FString& Reason)
{
	BridgePort->SendReturnToApp(Reason);
}

void UVerseUiSubsystem::TravelToDeck(FName Deck)
{
	GamePort->TravelToDeck(Deck);
	RebuildScreen();
}

void UVerseUiSubsystem::SkipKillCam()
{
	if (KillCam.IsPlaying())
	{
		KillCam.Skip(LocalNow());
		ApplyKillCamView(false);
	}
}

void UVerseUiSubsystem::ContinueAfterSet()
{
	ShowScreen(EVerseUiScreen::None);
}

void UVerseUiSubsystem::ToggleBar()
{
	bBarOpen = !bBarOpen;
	RebuildScreen();
}

bool UVerseUiSubsystem::IsListeningForKey() const
{
	return SlateRoot.IsValid() && SlateRoot->IsListening();
}

bool UVerseUiSubsystem::HandleKey(const FKey& Key)
{
	if (SlateRoot.IsValid() && SlateRoot->IsListening())
	{
		const FName Action = SlateRoot->GetListeningAction();
		SlateRoot->StopListening();
		if (Key != EKeys::Escape)
		{
			RebindKey(Action, Key);
		}
		return true;
	}
	switch (KeyMap.Route(Key))
	{
	case EVerseUiCommand::ReturnToApp:
		ReturnToApp(TEXT("return_key"));
		return true;
	case EVerseUiCommand::EscMenu:
		// On a deck, Escape first ends mouse look, then closes the crew card (parity K-05); only
		// with nothing of the deck's open does it reach the menu.
		if (Screen == EVerseUiScreen::None && UVerseDeckControlComponent::TryEscape(GetWorld()))
		{
			return true;
		}
		ShowScreen(Screen == EVerseUiScreen::None ? EVerseUiScreen::EscMenu
			: Screen == EVerseUiScreen::Settings ? EVerseUiScreen::EscMenu
			: EVerseUiScreen::None);
		return true;
	case EVerseUiCommand::SkipKillCam:
		if (KillCam.IsPlaying())
		{
			SkipKillCam();
			return true;
		}
		return false;
	case EVerseUiCommand::VerseBar:
		ToggleBar();
		return true;
	case EVerseUiCommand::None:
		break;
	}
	return false;
}

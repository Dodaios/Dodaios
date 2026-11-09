#include "Core/VerseUiSubsystem.h"

#include "Audio/VerseAudioSubsystem.h"
#include "Camera/CameraActor.h"
#include "Camera/CameraComponent.h"
#include "CanvasItem.h"
#include "Components/SkeletalMeshComponent.h"
#include "Core/VerseUiDefaultPorts.h"
#include "Core/VerseUiTheme.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/LocalPlayer.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/World.h"
#include "EnhancedInputSubsystems.h"
#include "Events/VerseEventHub.h"
#include "Framework/Application/IInputProcessor.h"
#include "Framework/Application/SlateApplication.h"
#include "GameFramework/Character.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/GameUserSettings.h"
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
#include "Policies/CondensedJsonPrintPolicy.h"
#include "QA/VerseUiQaCommands.h"
#include "Rendering/SlateRenderer.h"
#include "Scalability.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Settings/VerseGameSettings.h"
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

	/** An engine console variable the graphics settings own (set by code, above scalability and ini). */
	void SetEngineCVar(const TCHAR* Name, float Value)
	{
		if (IConsoleVariable* Var = IConsoleManager::Get().FindConsoleVariable(Name))
		{
			Var->Set(Value, ECVF_SetByCode);
		}
	}

	FString JsonText(const TSharedPtr<FJsonValue>& Value)
	{
		if (!Value.IsValid())
		{
			return FString();
		}
		switch (Value->Type)
		{
		case EJson::Boolean: return Value->AsBool() ? TEXT("1") : TEXT("0");
		case EJson::Number: return FString::SanitizeFloat(Value->AsNumber());
		default: return Value->AsString();
		}
	}

	FString CondensedJson(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	const TCHAR* PresetId = TEXT("graphics.preset");
	const TCHAR* TierId = TEXT("gameplay.bot_tier");
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
	LoadSettingsCache();
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

	// Publish the settings other modules read (the engine side waits for play or welcome).
	PublishSettings();
}

void UVerseUiSubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	BindHub();
	AttachSlate();
	// The cached settings apply at start, before the app's welcome brings the stored ones.
	bSettingsLive = true;
	PublishSettings();
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
	if (SettingsPostProcess)
	{
		SettingsPostProcess->Destroy();
		SettingsPostProcess = nullptr;
	}
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
		// settings.game gameplay.kill_cam: off skips the replay; the HUD shows the respawn at once.
		if (AppSettings.Game.GetBool(TEXT("gameplay.kill_cam"))
			&& KillCam.Begin(KillCamBuffer, Event, LocalId, Now, Server, AppSettings.Gore == EVerseGoreLevel::Reduced))
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

	// Frame rate for the HUD's performance stats (real time, not the world's dilated clock).
	const float FrameMs = float(FApp::GetDeltaTime() * 1000.0);
	if (FrameMs > 0.f)
	{
		SmoothedFrameMs = SmoothedFrameMs <= 0.f ? FrameMs : FMath::Lerp(SmoothedFrameMs, FrameMs, 0.1f);
		SmoothedFps = 1000.f / FMath::Max(0.01f, SmoothedFrameMs);
	}

	// audio.mute_unfocused: silent while another window has the focus.
	if (bSettingsLive && !FApp::IsUnattended() && FSlateApplication::IsInitialized())
	{
		const bool bMute = AppSettings.Game.GetBool(TEXT("audio.mute_unfocused")) && !FSlateApplication::Get().IsActive();
		if (bMute != bBackgroundMuted)
		{
			bBackgroundMuted = bMute;
			if (UVerseAudioSubsystem* Audio = UVerseAudioSubsystem::Get(this))
			{
				Audio->SetBackgroundMuted(bMute);
			}
		}
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
	return FVerseUiLayout::Compute(Viewport, SafeFraction, Padding, float(AppSettings.Game.GetNumber(TEXT("access.text_scale"))));
}

void UVerseUiSubsystem::BuildHudFrame(const FVector2D& Viewport, FVerseHudDrawList& Out) const
{
	FVerseHudFrame Frame;
	Frame.Model = &Hud;
	Frame.Strings = &Strings;
	Frame.Source = HudSource.Get();
	Frame.Layout = ComputeLayout(Viewport);
	// settings.game hud.*: the crosshair keeps the viewport's scale, the other blocks take the HUD size.
	Frame.Options = FVerseHudOptions::FromSettings(AppSettings.Game);
	Frame.Options.CrosshairScale = Frame.Layout.Scale;
	Frame.Options.Fps = SmoothedFps;
	Frame.Options.FrameMs = SmoothedFrameMs;
	const float HudScale = FMath::Clamp(float(AppSettings.Game.GetNumber(TEXT("hud.scale"))), 0.5f, 1.5f);
	Frame.Layout.Scale *= HudScale;
	Frame.Layout.TextScale *= HudScale;
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
	if (LifecycleState == FName(TEXT("booting")))
	{
		LifecycleState = TEXT("visible");
	}
	bSettingsLive = true;
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
	bSettingsLive = true;
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
	// The key map swaps a key another action had, so the app gets both changes in one
	// settings.set and its store never sees one key bound twice.
	KeyMap.Rebind(Action, Key);
	FVerseAppSettings Next = AppSettings;
	for (const FVerseKeyMap::FAction& Each : KeyMap.GetActions())
	{
		const FKey Bound = KeyMap.GetKey(Each.Action);
		if (Each.Action == FVerseKeyMap::ReturnAction())
		{
			Next.ReturnKey = Bound;
		}
		else
		{
			Next.Game.SetString(TEXT("keybinds.") + Each.Action.ToString(), Bound.GetFName().ToString());
		}
	}
	SetAppSettings(Next);
}

void UVerseUiSubsystem::SetDuelFov(float Fov)
{
	SetGameSetting(TEXT("controls.fov_duel"), MakeShared<FJsonValueNumber>(FMath::Clamp(Fov, UVerseUiUserSettings::DuelFovMin, UVerseUiUserSettings::DuelFovMax)));
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
	SetGameSetting(PresetId, MakeShared<FJsonValueString>(Level >= 0 ? FVerseGameSettings::QualityName(FMath::Clamp(Level, 0, 4)) : FString(TEXT("auto"))));
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
	Next.Game.SetString(PresetId, TEXT("auto"));
	// One settings.set for the whole reset.
	SetAppSettings(Next);
	RebuildScreen();
}

void UVerseUiSubsystem::SetTextScale(float Scale)
{
	SetGameSetting(TEXT("access.text_scale"), MakeShared<FJsonValueNumber>(FMath::Clamp(Scale, 0.8f, 1.6f)));
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

TSharedPtr<FJsonValue> UVerseUiSubsystem::GetGameSetting(const FString& Id) const
{
	const FVerseGameSettingDef* Def = FVerseGameSettingsCatalogue::Get().Find(Id);
	if (!Def)
	{
		return nullptr;
	}
	if (Def->Path.IsEmpty())
	{
		return AppSettings.Game.GetValue(Id);
	}
	// Settings older than the catalogue keep their place in welcome.settings.
	const FVerseAppSettings& S = AppSettings;
	const FString& P = Def->Path;
	if (P == TEXT("gore")) { return MakeShared<FJsonValueString>(FVerseAppSettings::GoreToString(S.Gore)); }
	if (P == TEXT("reduced_motion")) { return MakeShared<FJsonValueBoolean>(S.bReducedMotion); }
	if (P == TEXT("return_key")) { return MakeShared<FJsonValueString>(S.ReturnKey.GetFName().ToString()); }
	if (P == TEXT("ui_sound")) { return MakeShared<FJsonValueBoolean>(S.bUiSound); }
	if (P == TEXT("level_sound")) { return MakeShared<FJsonValueBoolean>(S.bLevelSound); }
	if (P == TEXT("view.volume")) { return MakeShared<FJsonValueNumber>(S.Volume); }
	if (P == TEXT("view.sensitivity")) { return MakeShared<FJsonValueNumber>(S.Sensitivity); }
	if (P == TEXT("view.invert_y")) { return MakeShared<FJsonValueBoolean>(S.bInvertY); }
	if (P == TEXT("view.fov_first")) { return MakeShared<FJsonValueNumber>(S.FovFirst); }
	if (P == TEXT("view.fov_third")) { return MakeShared<FJsonValueNumber>(S.FovThird); }
	if (P == TEXT("view.mode")) { return MakeShared<FJsonValueString>(S.ViewMode); }
	return Def->Default;
}

bool UVerseUiSubsystem::GetGameBool(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetGameSetting(Id);
	return V.IsValid() && V->Type == EJson::Boolean && V->AsBool();
}

double UVerseUiSubsystem::GetGameNumber(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetGameSetting(Id);
	return V.IsValid() && V->Type == EJson::Number ? V->AsNumber() : 0.0;
}

FString UVerseUiSubsystem::GetGameString(const FString& Id) const
{
	const TSharedPtr<FJsonValue> V = GetGameSetting(Id);
	return V.IsValid() && V->Type == EJson::String ? V->AsString() : FString();
}

bool UVerseUiSubsystem::SetGameSetting(const FString& Id, const TSharedPtr<FJsonValue>& Value)
{
	const FVerseGameSettingsCatalogue& Catalogue = FVerseGameSettingsCatalogue::Get();
	const FVerseGameSettingDef* Def = Catalogue.Find(Id);
	TSharedPtr<FJsonValue> Checked;
	if (!Def || !Def->Check(Value, Checked))
	{
		return false;
	}
	FVerseAppSettings Next = AppSettings;
	if (!Def->Path.IsEmpty())
	{
		// {"view": {"volume": 0.4}} for view.volume, then the usual parser.
		TArray<FString> Parts;
		Def->Path.ParseIntoArray(Parts, TEXT("."));
		TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
		TSharedRef<FJsonObject> Leaf = Root;
		for (int32 I = 0; I + 1 < Parts.Num(); ++I)
		{
			TSharedRef<FJsonObject> Child = MakeShared<FJsonObject>();
			Leaf->SetObjectField(Parts[I], Child);
			Leaf = Child;
		}
		Leaf->SetField(Parts.Last(), Checked);
		Next.ApplyJson(Root);
	}
	else
	{
		Next.Game.Set(Id, Checked);
		// The page's preset rule: a level sets every quality group, one group turns it custom.
		if (Id == PresetId)
		{
			const FString Level = Checked->AsString();
			if (FVerseGameSettings::QualityIndex(Level) >= 0)
			{
				for (const FString& Group : Catalogue.GetPresetGroups())
				{
					Next.Game.SetString(Group, Level);
				}
			}
		}
		else if (Def->bPresetGroup)
		{
			Next.Game.SetString(PresetId, TEXT("custom"));
		}
	}
	SetAppSettings(Next);
	return true;
}

void UVerseUiSubsystem::LoadSettingsCache()
{
	FVerseGameSettings& Game = AppSettings.Game;
	TSharedPtr<FJsonObject> Cached;
	if (!UserSettings->GameSettings.IsEmpty()
		&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(UserSettings->GameSettings), Cached) && Cached.IsValid())
	{
		Game.ApplyJson(Cached);
		return;
	}
	// First start with the catalogue: carry the Unreal-only settings of before over.
	Game.SetNumber(TEXT("controls.fov_duel"), UserSettings->DuelFov);
	Game.SetNumber(TEXT("access.text_scale"), UserSettings->TextScale);
	Game.SetString(TierId, UserSettings->LastTier.ToString());
	if (UserSettings->Scalability >= 0)
	{
		const FString Level = FVerseGameSettings::QualityName(UserSettings->Scalability);
		Game.SetString(PresetId, Level);
		for (const FString& Group : FVerseGameSettingsCatalogue::Get().GetPresetGroups())
		{
			Game.SetString(Group, Level);
		}
	}
	for (const FVerseKeyBinding& Binding : UserSettings->KeyBindings)
	{
		Game.SetString(TEXT("keybinds.") + Binding.Action.ToString(), Binding.Key.GetFName().ToString());
	}
}

void UVerseUiSubsystem::SaveSettingsCache()
{
	if (!UserSettings)
	{
		return;
	}
	const FVerseGameSettings& Game = AppSettings.Game;
	const FString Json = CondensedJson(Game.ToJson());
	const float DuelFov = float(Game.GetNumber(TEXT("controls.fov_duel")));
	const int32 Level = FVerseGameSettings::QualityIndex(Game.GetString(PresetId));
	const float TextScale = float(Game.GetNumber(TEXT("access.text_scale")));
	const FName Tier(*Game.GetString(TierId));
	const TArray<FVerseKeyBinding> Bindings = KeyMap.GetBindings();
	bool bSameBindings = Bindings.Num() == UserSettings->KeyBindings.Num();
	for (int32 I = 0; bSameBindings && I < Bindings.Num(); ++I)
	{
		bSameBindings = Bindings[I].Action == UserSettings->KeyBindings[I].Action && Bindings[I].Key == UserSettings->KeyBindings[I].Key;
	}
	if (Json == UserSettings->GameSettings && bSameBindings && FMath::IsNearlyEqual(DuelFov, UserSettings->DuelFov)
		&& Level == UserSettings->Scalability && FMath::IsNearlyEqual(TextScale, UserSettings->TextScale) && Tier == UserSettings->LastTier)
	{
		return;
	}
	UserSettings->GameSettings = Json;
	UserSettings->DuelFov = DuelFov;
	UserSettings->Scalability = Level;
	UserSettings->TextScale = TextScale;
	UserSettings->LastTier = Tier;
	UserSettings->KeyBindings = Bindings;
	UserSettings->SaveToDisk();
}

void UVerseUiSubsystem::PublishSettings()
{
	const FVerseGameSettings& Game = AppSettings.Game;

	// Key bindings: settings.game keybinds.* and the return key.
	TArray<FVerseKeyBinding> Bindings;
	for (const FVerseKeyMap::FAction& Action : KeyMap.GetActions())
	{
		if (Action.Action == FVerseKeyMap::ReturnAction())
		{
			continue;
		}
		const FKey Key(*Game.GetString(TEXT("keybinds.") + Action.Action.ToString()));
		if (Key.IsValid())
		{
			FVerseKeyBinding Binding;
			Binding.Action = Action.Action;
			Binding.Key = Key;
			Bindings.Add(Binding);
		}
	}
	KeyMap.SetBindings(Bindings);
	KeyMap.SetReturnKey(AppSettings.ReturnKey);

	// The armoury preselects the stored opponent tier.
	const FName Tier(*Game.GetString(TierId));
	if (Armoury.GetSelectedTier() != Tier)
	{
		Armoury.SelectTier(Tier);
	}

	PublishCVar(TEXT("Verse.Settings.DuelFov"), FString::SanitizeFloat(Game.GetNumber(TEXT("controls.fov_duel"))), TEXT("Duel horizontal FOV, 80-110 (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.FovThird"), FString::SanitizeFloat(AppSettings.FovThird), TEXT("Deck third-person FOV (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.FovFirst"), FString::SanitizeFloat(AppSettings.FovFirst), TEXT("Deck first-person FOV (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.Sensitivity"), FString::SanitizeFloat(AppSettings.Sensitivity), TEXT("Look sensitivity (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.InvertY"), AppSettings.bInvertY ? TEXT("1") : TEXT("0"), TEXT("Invert look Y (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.ReducedMotion"), AppSettings.bReducedMotion ? TEXT("1") : TEXT("0"), TEXT("Reduced motion (VerseUI)"));
	PublishCVar(TEXT("Verse.Settings.Volume"), FString::SanitizeFloat(AppSettings.Volume), TEXT("Master volume 0-1 (VerseUI)"));
	// Every catalogue value, for the owners that cannot include VerseUI (input, camera, bot, crew).
	for (const FVerseGameSettingDef& Def : FVerseGameSettingsCatalogue::Get().GetSettings())
	{
		PublishCVar(*(TEXT("Verse.Settings.Game.") + Def.Id), JsonText(GetGameSetting(Def.Id)),
			TEXT("Verse game setting, settings.game (docs/verse/unreal/game-settings.md; VerseUI)"));
	}
	PublishCVar(TEXT("Verse.Settings.ViewMode"), AppSettings.ViewMode, TEXT("Deck view restored from the app config: third, first, overview (VerseUI)"));
	// Z-14, R-12: the app-wide sound switch, the level bell switch and the volume reach the audio subsystem.
	if (UWorld* World = GetWorld())
	{
		if (UVerseAudioSubsystem* Audio = World->GetSubsystem<UVerseAudioSubsystem>())
		{
			Audio->SetUiSoundEnabled(AppSettings.bUiSound);
			Audio->SetLevelSoundEnabled(AppSettings.bLevelSound);
			Audio->SetUserVolume(AppSettings.Volume);
		}
	}
	WriteGoreSetting(GetWorld(), AppSettings.Gore);
	WriteViewSettings(float(Game.GetNumber(TEXT("controls.fov_duel"))), AppSettings);
	ApplyKeyBindingsToInput();

	if (bSettingsLive)
	{
		ApplyGameSettings();
	}
	SaveSettingsCache();
	OnSettingsApplied.Broadcast();
}

void UVerseUiSubsystem::ApplyGameSettings()
{
	const FVerseGameSettings& Game = AppSettings.Game;
	UGameUserSettings* User = GEngine ? GEngine->GetGameUserSettings() : nullptr;
	const FIntPoint Desktop = User ? User->GetDesktopResolution() : FIntPoint(1920, 1080);
	GraphicsPlan = FVerseGraphicsPlan::Build(Game, Desktop);
	ApplyPostProcess(GraphicsPlan);
	ApplyGraphics(GraphicsPlan);
	ApplyAudio();

	// Colour-blind filter on the whole picture (the Slate renderer's colour vision correction).
	// Never in the editor: it would tint the editor's own windows too.
	if (!GIsEditor && !FApp::IsUnattended() && FSlateApplication::IsInitialized())
	{
		if (FSlateRenderer* Renderer = FSlateApplication::Get().GetRenderer())
		{
			const FString Mode = Game.GetString(TEXT("access.colorblind"));
			const EColorVisionDeficiency Type = Mode == TEXT("protanopia") ? EColorVisionDeficiency::Protanope
				: Mode == TEXT("deuteranopia") ? EColorVisionDeficiency::Deuteranope
				: Mode == TEXT("tritanopia") ? EColorVisionDeficiency::Tritanope
				: EColorVisionDeficiency::NormalVision;
			Renderer->SetColorVisionDeficiencyType(Type, FMath::RoundToInt(Game.GetNumber(TEXT("access.colorblind_strength"))), true, false);
		}
	}
}

void UVerseUiSubsystem::ApplyPostProcess(const FVerseGraphicsPlan& Plan)
{
	UWorld* World = GetWorld();
	if (!World || !World->bIsWorldInitialized || !World->PersistentLevel || !World->IsGameWorld())
	{
		return;
	}
	if (!SettingsPostProcess)
	{
		FActorSpawnParameters Params;
		Params.ObjectFlags |= RF_Transient;
		Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		SettingsPostProcess = World->SpawnActor<APostProcessVolume>(Params);
		if (!SettingsPostProcess)
		{
			return;
		}
		// Over every level volume, but it only carries the switches below.
		SettingsPostProcess->bUnbound = true;
		SettingsPostProcess->Priority = 10000.f;
		SettingsPostProcess->BlendWeight = 1.f;
	}
	// A switch that is on leaves the level's own look; off overrides that effect to zero.
	FPostProcessSettings& S = SettingsPostProcess->Settings;
	S.bOverride_MotionBlurAmount = !Plan.bMotionBlur;
	S.MotionBlurAmount = 0.f;
	S.bOverride_DepthOfFieldFocalDistance = !Plan.bDepthOfField;
	S.DepthOfFieldFocalDistance = 0.f;
	S.bOverride_FilmGrainIntensity = !Plan.bFilmGrain;
	S.FilmGrainIntensity = 0.f;
	S.bOverride_SceneFringeIntensity = !Plan.bChromaticAberration;
	S.SceneFringeIntensity = 0.f;
	S.bOverride_LensFlareIntensity = !Plan.bLensFlares;
	S.LensFlareIntensity = 0.f;
	S.bOverride_BloomIntensity = !Plan.bBloom;
	S.BloomIntensity = 0.f;
}

void UVerseUiSubsystem::ApplyGraphics(const FVerseGraphicsPlan& Plan)
{
	// Headless runs and tests compute the plan but leave the engine alone.
	if (FApp::IsUnattended() || !FApp::CanEverRender() || !GEngine)
	{
		return;
	}
	FString Key;
	for (const FVerseGameSettingDef& Def : FVerseGameSettingsCatalogue::Get().GetSettings())
	{
		if (Def.Tab == TEXT("graphics"))
		{
			Key += Def.Id + TEXT("=") + JsonText(AppSettings.Game.GetValue(Def.Id)) + TEXT(";");
		}
	}
	if (Key == AppliedGraphicsKey)
	{
		return; // an audio or HUD change does not touch the display
	}
	AppliedGraphicsKey = Key;

	UGameUserSettings* User = GEngine->GetGameUserSettings();
	if (Plan.bAutoQuality)
	{
		if (User && !GIsEditor && !bBenchmarked)
		{
			// Auto measures this PC once per start (the engine's hardware benchmark).
			User->RunHardwareBenchmark();
			User->ApplyHardwareBenchmarkResults();
			BenchmarkLevels = Scalability::GetQualityLevels();
			bBenchmarked = true;
		}
		else if (GIsEditor)
		{
			ApplyScalabilityLevel(-1);
		}
		else if (User && !GIsEditor)
		{
			Scalability::SetQualityLevels(BenchmarkLevels, true);
		}
	}
	else
	{
		Scalability::SetQualityLevels(Plan.Quality, true);
	}

	if (User && !GIsEditor)
	{
		// The display, and the user settings file the engine reads at its next start.
		const Scalability::FQualityLevels Levels = Scalability::GetQualityLevels();
		User->SetViewDistanceQuality(Levels.ViewDistanceQuality);
		User->SetShadowQuality(Levels.ShadowQuality);
		User->SetGlobalIlluminationQuality(Levels.GlobalIlluminationQuality);
		User->SetReflectionQuality(Levels.ReflectionQuality);
		User->SetTextureQuality(Levels.TextureQuality);
		User->SetVisualEffectQuality(Levels.EffectsQuality);
		User->SetPostProcessingQuality(Levels.PostProcessQuality);
		User->SetFoliageQuality(Levels.FoliageQuality);
		User->SetShadingQuality(Levels.ShadingQuality);
		User->SetAntiAliasingQuality(Levels.AntiAliasingQuality);
		User->SetResolutionScaleValueEx(Plan.ScreenPercentage);
		User->SetFullscreenMode(Plan.WindowMode);
		User->SetScreenResolution(Plan.Resolution);
		User->SetFrameRateLimit(Plan.FrameLimit);
		User->SetVSyncEnabled(Plan.bVSync);
		// HDR needs a restart (catalogue restart flag): only the value at start applies.
		if (!bHdrApplied && User->SupportsHDRDisplayOutput())
		{
			User->EnableHDRDisplayOutput(Plan.bHdr);
		}
		User->ApplySettings(false);
	}
	bHdrApplied = true;

	SetEngineCVar(TEXT("r.AntiAliasingMethod"), float(Plan.AntiAliasingMethod));
	SetEngineCVar(TEXT("r.ScreenPercentage"), Plan.ScreenPercentage);
	SetEngineCVar(TEXT("r.Tonemapper.Sharpen"), Plan.Sharpen);
	GEngine->DisplayGamma = Plan.DisplayGamma;
}

void UVerseUiSubsystem::ApplyAudio()
{
	UVerseAudioSubsystem* Audio = UVerseAudioSubsystem::Get(this);
	if (!Audio)
	{
		return;
	}
	const FVerseAudioPlan Plan = FVerseAudioPlan::Build(AppSettings.Game, AppSettings.bUiSound);
	Audio->SetUserVolume(AppSettings.Volume);
	Audio->SetUserBusGains(Plan.BusGain);
	if (!Plan.bMuteUnfocused && bBackgroundMuted)
	{
		bBackgroundMuted = false;
		Audio->SetBackgroundMuted(false);
	}
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
	// The chosen tier is settings.game gameplay.bot_tier (the app keeps it, the ini caches it).
	const FName Tier = Armoury.GetSelectedTier();
	SetGameSetting(TierId, MakeShared<FJsonValueString>(Tier.ToString()));
	Session.Reset();
	GamePort->StartDuel(Tier);
	ShowScreen(EVerseUiScreen::None);
}

void UVerseUiSubsystem::QuickStartDuel()
{
	Session.Reset();
	GamePort->StartDuel(FName(*AppSettings.Game.GetString(TierId)));
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

#pragma once

#include "Core/VerseUiPorts.h"
#include "Core/VerseUiStrings.h"
#include "CoreMinimal.h"
#include "Hud/VerseHudModel.h"
#include "Hud/VerseHudPainter.h"
#include "KillCam/VerseKillCam.h"
#include "Menus/VerseUiMenus.h"
#include "Settings/VerseUiInputRemap.h"
#include "Settings/VerseUiSettings.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseUiSubsystem.generated.h"

class AActor;
class AHUD;
class ACameraActor;
class APostProcessVolume;
class APawn;
class SVerseUiRoot;
class UCanvas;
class USkeletalMeshComponent;
struct FActorSpawnParameters;
class FVerseUiInputProcessor;
class UVerseEventHub;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseUiScreenChanged, EVerseUiScreen);

/**
 * The Verse UI of one game world (WP18): HUD model and painter, kill cam, armoury, Verse bar,
 * menus, settings, end-of-set screen. It listens to the event hub, draws the HUD on every HUD's
 * post-render (no game mode change needed), puts the Slate menus on the game viewport and
 * routes UI keys through a Slate input pre-processor.
 *
 * WP17 feeds it the bridge (ApplyWelcome, ApplySettingsChanged) and sets the bridge port.
 */
UCLASS()
class VERSEUI_API UVerseUiSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseUiSubsystem* Get(const UObject* WorldContextObject);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	// Bridge (WP17 calls these with the frame's data object).
	void ApplyWelcome(const TSharedPtr<FJsonObject>& Data);
	void ApplySettingsChanged(const TSharedPtr<FJsonObject>& Data);
	void SetBridgePort(TSharedPtr<IVerseUiBridgePort> Port);
	void SetGamePort(TSharedPtr<IVerseUiGamePort> Port);
	void SetHudSource(TSharedPtr<IVerseHudSource> Source);

	// Settings actions (each app-backed change sends exactly one settings.set).
	void SetGore(EVerseGoreLevel Level);
	void SetReducedMotion(bool bReduced);
	void SetReturnKey(const FKey& Key);
	void SetAppSettings(const FVerseAppSettings& Next);
	void RebindKey(FName Action, const FKey& Key);
	/** controls.fov_duel */
	void SetDuelFov(float Fov);
	/** graphics.preset: -1 auto, 0..4 low..cinematic (sets every quality group). */
	void SetScalability(int32 Level);
	/** access.text_scale */
	void SetTextScale(float Scale);

	/**
	 * The one read API of the in-game settings menu (docs/verse/unreal/game-settings.md): the
	 * current value of a catalogue id, settings.game or a legacy place ("controls.view_mode"
	 * reads view.mode). Null for an unknown id. Systems without a VerseUI dependency read the
	 * same values from the console variables Verse.Settings.Game.<id>.
	 */
	TSharedPtr<FJsonValue> GetGameSetting(const FString& Id) const;
	bool GetGameBool(const FString& Id) const;
	double GetGameNumber(const FString& Id) const;
	FString GetGameString(const FString& Id) const;
	/**
	 * Changes one catalogue value through the app settings (one settings.set). A quality preset
	 * sets every quality group; changing one group turns the preset to custom. False when the
	 * catalogue refuses the value.
	 */
	bool SetGameSetting(const FString& Id, const TSharedPtr<FJsonValue>& Value);
	/** Broadcast after the settings were applied (welcome, settings.changed or the menu). */
	FSimpleMulticastDelegate OnSettingsApplied;
	/** What the graphics settings asked of the engine last. */
	const FVerseGraphicsPlan& GetGraphicsPlan() const { return GraphicsPlan; }
	/** The unbound post-process volume that carries the camera effect switches. */
	APostProcessVolume* GetSettingsPostProcess() const { return SettingsPostProcess; }
	/** Settings reset (parity T-01): sensitivity 1, invert off, quality auto, FOV 70/85, volume 0.7, view third. */
	void ResetSettings();

	/** Applies a scalability level: 0..4, or -1 (auto) for the engine's default levels. */
	static void ApplyScalabilityLevel(int32 Level);

	/**
	 * Writes the gore level where VerseGore reads it: UVerseSettings::GoreLevel
	 * ([/Script/Verse.VerseSettings] in GameUserSettings, combat-state 8), on the class default
	 * object and in the ini, and asks a live UVerseGoreSubsystem to re-read it.
	 */
	static void WriteGoreSetting(UWorld* World, EVerseGoreLevel Level);
	/** The gore level stored for VerseGore, read back the way VerseGore reads it. */
	static EVerseGoreLevel ReadGoreSetting();

	// Screens and actions.
	void ShowScreen(EVerseUiScreen InScreen);
	EVerseUiScreen GetScreen() const { return Screen; }
	void StartDuelFromArmoury();
	void QuickStartDuel();
	void LeaveDuel();
	void ReturnToApp(const FString& Reason);
	void TravelToDeck(FName Deck);
	void SkipKillCam();
	void ContinueAfterSet();
	void ToggleBar();
	bool IsBarOpen() const { return bBarOpen; }

	/** Key routing; true when the UI used the key. */
	bool HandleKey(const FKey& Key);
	/**
	 * Asked first with every key; true = used. The deck HUD takes Escape while its own dialog
	 * (the lift, the service record) is open, so Escape closes that and not the Esc menu.
	 */
	TFunction<bool(const FKey&)> KeyPreHandler;
	/** True while a menu screen is open: the cursor is shown and mouse look stops (parity H-13). */
	bool IsMouseLookReleased() const { return Screen != EVerseUiScreen::None; }
	/** True while the controls page waits for the key of a rebind (mouse buttons count too). */
	bool IsListeningForKey() const;

	/** Bridge lifecycle (parity Q-01): booting until welcome, then WP17 sets visible, panel or dormant. */
	void SetLifecycleState(FName State) { LifecycleState = State; }
	FName GetLifecycleState() const { return LifecycleState; }

	/** One replayed bolt the kill cam draws (WP18.5: fire events replayed). */
	struct FReplayBolt
	{
		FVector Start = FVector::ZeroVector;
		FVector End = FVector::ZeroVector;
		double LocalTime = 0.0;
	};
	const TArray<FReplayBolt>& GetReplayBolts() const { return ReplayBolts; }
	/** Seconds a replayed bolt stays drawn. */
	static constexpr double ReplayBoltLife = 0.25;

	/** Session totals for the summary shown on leave (parity D-10). */
	const FVerseSessionSummary& GetSession() const { return Session; }
	const FVerseEndScreen& GetSessionScreen() const { return SessionScreen; }

	/** Rebinds the local player's Enhanced Input contexts to the current keys now (tests, possession). */
	int32 ApplyKeyBindingsToInput();
	FVerseUiInputRemap& GetInputRemap() { return InputRemap; }

	/** The replayed killer: a scene root at the recorded capsule with a copy of the killer's mesh under it at the pawn's mesh offset. */
	AActor* SpawnKillCamProxy(UWorld* World, const FActorSpawnParameters& Params, const APawn* Killer, USkeletalMeshComponent* KillerMesh);
	bool IsPausedByUi() const { return bPausedByUi; }

	// Read access.
	const FVerseUiStrings& GetStrings() const { return Strings; }
	FVerseUiStrings& GetMutableStrings() { return Strings; }
	const FVerseHudModel& GetHudModel() const { return Hud; }
	FVerseHudModel& GetMutableHudModel() { return Hud; }
	const FVerseAppSettings& GetAppSettings() const { return AppSettings; }
	UVerseUiUserSettings* GetUserSettings() const { return UserSettings; }
	const FVerseKeyMap& GetKeyMap() const { return KeyMap; }
	FVerseArmouryModel& GetArmoury() { return Armoury; }
	const FVerseKillCamPlayer& GetKillCam() const { return KillCam; }
	const FVerseKillCamBuffer& GetKillCamBuffer() const { return KillCamBuffer; }
	const TArray<FName>& GetDecks() const { return Decks; }
	IVerseHudSource& GetHudSource() const { return *HudSource; }
	IVerseUiGamePort& GetGamePort() const { return *GamePort; }
	const FVerseHudDrawList& GetLastDrawList() const { return LastDrawList; }
	/** Mean HUD cost on the game thread (draw-list build plus canvas submit), ms, last 120 frames. */
	double GetHudCostMs() const { return HudCostMs; }
	FVerseUiLayout ComputeLayout(const FVector2D& Viewport) const;
	const FVerseEndScreen& GetEndScreen() const { return EndScreen; }

	/** Builds one HUD frame for a viewport size (the post-render draw and the captures use it). */
	void BuildHudFrame(const FVector2D& Viewport, FVerseHudDrawList& Out) const;

	FOnVerseUiScreenChanged OnScreenChanged;
	/**
	 * Kill cam replay of fire and fracture events. The UI draws replayed bolts itself; the
	 * fracture hook is for the destruction client (destruction.md 4) once it binds it.
	 */
	TFunction<void(const FVerseFireEvent&)> OnKillCamFire;
	TFunction<void(const FVerseFractureEvent&)> OnKillCamFracture;

	/** Draw the HUD from AHUD post-render (captures that draw it themselves turn it off). */
	bool bDrawHudOnPostRender = true;

	/** Local clock of the UI (real time seconds); tests may pin it. */
	TFunction<double()> Clock;

private:
	void LoadData();
	void BindHub();
	void UnbindHub();
	void AttachSlate();
	void DetachSlate();
	void RebuildScreen();
	void ApplyInputMode();
	void ApplyKillCamView(bool bStart);
	void TickKillCam(double Now);
	void OnHudPostRender(AHUD* InHud, UCanvas* Canvas);
	void DrawReplayBolts(UCanvas* Canvas);
	void AddReplayBolt(const FVerseFireEvent& Event);
	void UpdatePause();
	double LocalNow() const;
	void PublishSettings();
	/** Seeds the settings from the user settings file cache before welcome arrives. */
	void LoadSettingsCache();
	/** Mirrors the settings into the user settings file (a cache; the app config is the truth). */
	void SaveSettingsCache();
	/** Applies settings.game to the engine, the audio mix, the HUD and the armoury. */
	void ApplyGameSettings();
	void ApplyGraphics(const FVerseGraphicsPlan& Plan);
	void ApplyPostProcess(const FVerseGraphicsPlan& Plan);
	void ApplyAudio();
	/** True once the world plays or the app's welcome arrived: settings then reach the engine. */
	bool bSettingsLive = false;
	bool bBenchmarked = false;
	/** The levels the hardware benchmark chose (preset auto). */
	Scalability::FQualityLevels BenchmarkLevels;
	bool bHdrApplied = false;
	bool bBackgroundMuted = false;
	FString AppliedGraphicsKey;
	FVerseGraphicsPlan GraphicsPlan;
	float SmoothedFps = 0.f;
	float SmoothedFrameMs = 0.f;

	UPROPERTY(Transient)
	TObjectPtr<APostProcessVolume> SettingsPostProcess;

	void HandleHit(const FVerseHitEvent& Event);
	void HandleDeath(const FVerseDeathEvent& Event);
	void HandleSetEnded(const FVerseSetSummary& Summary);
	void HandleFire(const FVerseFireEvent& Event);
	void HandleFracture(const FVerseFractureEvent& Event);
	void HandleStationUsed(const FVerseStationUsedEvent& Event);

	FVerseUiStrings Strings;
	FVerseHudModel Hud;
	FVerseKillCamBuffer KillCamBuffer;
	FVerseKillCamPlayer KillCam;
	FVerseAppSettings AppSettings;
	FVerseKeyMap KeyMap;
	FVerseArmouryModel Armoury;
	FVerseEndScreen EndScreen;
	TArray<FName> Decks;
	EVerseUiScreen Screen = EVerseUiScreen::None;
	bool bBarOpen = false;
	float SafeFraction = 0.025f;

	UPROPERTY(Transient)
	TObjectPtr<UVerseUiUserSettings> UserSettings;

	UPROPERTY(Transient)
	TObjectPtr<ACameraActor> KillCamCamera;

	UPROPERTY(Transient)
	TObjectPtr<AActor> KillCamProxy;

	/** The live killer hidden in the local view only (PlayerController::HiddenActors, not replicated). */
	TWeakObjectPtr<APawn> KillCamHiddenKiller;
	TArray<FReplayBolt> ReplayBolts;
	FVerseSessionSummary Session;
	FVerseEndScreen SessionScreen;
	FVerseUiInputRemap InputRemap;
	double NextInputRemapAt = 0.0;
	bool bPausedByUi = false;
	FName LifecycleState = TEXT("booting");
	/** Own health from own-hit events while the source cannot read it (WP02 attribute set). */
	float TrackedHealth = 100.f;
	bool bLastDuelRunning = false;
	bool bOwnsGamePort = true;

	TWeakObjectPtr<AActor> KillCamPreviousTarget;
	TWeakObjectPtr<UVerseEventHub> BoundHub;
	TArray<FDelegateHandle> HubHandles;
	FDelegateHandle PostRenderHandle;

	TSharedPtr<IVerseUiBridgePort> BridgePort;
	TSharedPtr<IVerseUiGamePort> GamePort;
	TSharedPtr<IVerseHudSource> HudSource;
	TSharedPtr<SVerseUiRoot> SlateRoot;
	TSharedPtr<FVerseUiInputProcessor> InputProcessor;

	FVerseHudDrawList LastDrawList;
	double HudCostMs = 0.0;
	double HudCostAccum = 0.0;
	int32 HudCostFrames = 0;
};

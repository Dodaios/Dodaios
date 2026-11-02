#pragma once

#include "Core/VerseUiPorts.h"
#include "Core/VerseUiStrings.h"
#include "CoreMinimal.h"
#include "Hud/VerseHudModel.h"
#include "Hud/VerseHudPainter.h"
#include "KillCam/VerseKillCam.h"
#include "Menus/VerseUiMenus.h"
#include "Settings/VerseUiSettings.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseUiSubsystem.generated.h"

class AActor;
class AHUD;
class ACameraActor;
class APawn;
class SVerseUiRoot;
class UCanvas;
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
	void SetDuelFov(float Fov);
	void SetScalability(int32 Level);
	void SetTextScale(float Scale);

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
	/** Kill cam replay of fire and fracture events (VFX and the destruction client redraw them). */
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
	double LocalNow() const;
	void PublishSettings();

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

	TWeakObjectPtr<APawn> KillCamHiddenKiller;
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

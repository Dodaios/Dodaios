#pragma once

#include "Containers/Ticker.h"
#include "CoreMinimal.h"
#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseLiftTravel.h"
#include "Subsystems/GameInstanceSubsystem.h"
#include "WorldActions/VerseWorldActionReporter.h"

#include "VerseDeckSubsystem.generated.h"

class AActor;
class AVerseDeckCamera;
class AVerseDeckLighting;
class AVerseSpaceView;
class UWorld;

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseWorldAction, const FVerseWorldAction&);
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseDeckArrived, FName /*Deck*/, bool /*bByLift*/);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseLiftCue, EVerseLiftCue);

/**
 * Deck loading, lift travel and the deck world actions (WP12.1, WP12.11).
 *
 * Each deck is its own World Partition level (`LV_<Deck>`, G0.8); a ride shuts the lift doors,
 * opens the new deck's level and opens the doors on its first frame (`FVerseLiftTravel`). Deck
 * manifests are read once from the zone placement files and kept, so riding back to a deck needs
 * no reparse (parity B-05). On every arrival the subsystem spawns the deck's lights and haze, the
 * space view and the deck camera, and reports `deck_discovered`; it samples the commander every
 * 0.5 s for `inspection`. `OnWorldAction` is what the bridge client (WP17) sends as
 * `progression.action`.
 */
UCLASS()
class VERSEDECKS_API UVerseDeckSubsystem : public UGameInstanceSubsystem
{
	GENERATED_BODY()

public:
	/**
	 * Loads a deck's level; calls Done(true) on its first frame, Done(false) on failure. When the lift
	 * gives up first, the load is abandoned: a later Done is ignored and the next ride can start.
	 */
	using FLevelLoader = TFunction<void(const FVerseDeckInfo& Deck, TFunction<void(bool bOk)> Done)>;

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	static UVerseDeckSubsystem* Get(const UObject* WorldContextObject);

	/**
	 * The deck named by `-VerseDeck=<id>` in `CommandLine` (parity Q-09): the deck the launch loads
	 * instead of the default. NAME_None when absent, unknown, or in a Shipping build.
	 */
	static FName ParseStartupDeck(const TCHAR* CommandLine);
	FName GetStartupDeck() const { return StartupDeck; }

	/** Rides the lift to `Deck`. False when it is the current deck, unknown, or a ride is running. */
	bool RequestDeck(FName Deck);

	/** Loads `Deck` without a ride (start of a launch, `-VerseDeck=<id>`). */
	bool LoadDeckDirect(FName Deck);

	FName GetCurrentDeck() const { return CurrentDeck; }

	/** The deck's manifest, parsed once and cached (parity B-04, B-05); nullptr when it has no placement file. */
	const FVerseDeckManifest* GetManifest(FName Deck);

	const FVerseLiftTravel& GetLift() const { return Lift; }

	/** Reduced motion skips the door phase (parity L-04, from `settings.changed`). */
	void SetReducedMotion(bool bReduced) { bReducedMotion = bReduced; }

	/** The Verse window became Visible (lifecycle); the first time sends `daily_visit` (parity W-01). */
	void NotifyVisible();

	/** The commander's feet, deck-local cm; normally sampled from the first player pawn. */
	void NotifyCommanderFeet(const FVector& FeetCm);

	/** Seconds the last direct (cold) deck load took, -1 before the first one (A12.2). */
	double GetLastColdLoadS() const { return LastColdLoadS; }

	AVerseDeckCamera* GetCamera() const { return Camera.Get(); }

	/**
	 * The overview is a cutaway, as today's plate: the deck's `<zone>_ceiling` meshes (ceilings,
	 * their fixtures and the upper parts of cut walls) are hidden while the deck camera shows
	 * the overview, and shown in third and first person.
	 */
	bool IsCutaway() const { return bCutaway; }
	/** Captures and tests: force the cutaway on or off; unset follows the deck camera. */
	void SetCutawayOverride(TOptional<bool> Override);
	/** Ceiling actors on the current deck, including those World Partition streamed in after arrival. */
	int32 NumCeilingActors() const { return Ceilings.Num(); }
	/** True for an actor placed as `<zone>_ceiling` (tag `verse.pid:<zone>_ceiling`). */
	static bool IsCeilingActor(const AActor& Actor);
	/** True for a deck bounds proxy (`verse.pid:<zone>_bounds_<n>`), hidden in game on arrival. */
	static bool IsBoundsActor(const AActor& Actor);
	/** Bounds proxies hidden on the current deck so far. */
	int32 NumBoundsHidden() const { return BoundsHidden; }
	AVerseSpaceView* GetSpaceView() const { return SpaceView.Get(); }
	FVerseWorldActionReporter& GetReporter() { return Reporter; }

	/** Tests: replace level loading, the clock and the day. */
	void SetLevelLoader(FLevelLoader Loader) { LevelLoader = MoveTemp(Loader); }
	void SetClock(TFunction<double()> InClock) { Clock = MoveTemp(InClock); }
	void SetDayProvider(TFunction<FString()> InDay) { Day = MoveTemp(InDay); }
	/** Tests: the placement folder to read manifests from. */
	void SetPlacementsDir(const FString& Dir) { PlacementsDir = Dir; Manifests.Reset(); }

	/** Advances the lift and the samplers; the engine ticker calls it every frame. */
	void TickDecks(double NowS);

	/** Fired on every arrival (first frame), after the deck's actors exist. */
	FOnVerseDeckArrived OnDeckArrived;
	/** Every world action, in order. */
	FOnVerseWorldAction OnWorldAction;
	/** Lift cues for audio (parity L-07). */
	FOnVerseLiftCue OnLiftCue;

	/** `{deck, number, lift, last_ride_s, last_load_s, last_cold_load_s, deck_missing}` for QA and logs. */
	FString StateJson() const;

private:
	void StartLoad(FName Deck, bool bByLift);
	void OnLoaded(FName Deck, bool bByLift, bool bOk, double StartedAt);
	void SpawnDeckActors(UWorld* World, FName Deck, bool bByLift);
	void DefaultLoad(const FVerseDeckInfo& Deck, TFunction<void(bool)> Done);
	void CollectCeilings(UWorld* World);
	void AddCeilings(TArrayView<AActor* const> Actors);
	void AbandonLoad(const TCHAR* Why);
	void OnMapLoaded(const FString& Package);
	static const FVerseDeckInfo* DeckForPackage(const FString& Package);
	void UpdateCutaway();
	void ApplyCutaway(bool bOn);
	void RegisterQa();
	void UnregisterQa();
	double Now() const;
	UWorld* CurrentWorld() const;

	FTSTicker::FDelegateHandle TickHandle;
	FDelegateHandle PostLoadHandle;
	FDelegateHandle LevelAddedHandle;
	FDelegateHandle TravelFailureHandle;
	/** Bumped by every load start and abandon; a loader's late Done for an older serial is ignored. */
	int32 LoadSerial = 0;
	TFunction<void(bool)> PendingDone;
	FString PendingLevel;

	FLevelLoader LevelLoader;
	TFunction<double()> Clock;
	TFunction<FString()> Day;
	FString PlacementsDir;
	TMap<FName, FVerseDeckManifest> Manifests;
	FVerseLiftTravel Lift;
	FVerseWorldActionReporter Reporter;
	FName CurrentDeck;
	FName StartupDeck;
	bool bReducedMotion = false;
	bool bStartupDone = false;
	bool bLoadInFlight = false;
	double LastColdLoadS = -1.0;
	double LastSampleAt = -1.0;
	TArray<FString> QaCommands;

	TWeakObjectPtr<AVerseDeckCamera> Camera;
	TWeakObjectPtr<AVerseDeckLighting> Lighting;
	TWeakObjectPtr<AVerseSpaceView> SpaceView;
	TArray<TWeakObjectPtr<AActor>> Ceilings;
	TOptional<bool> CutawayOverride;
	int32 BoundsHidden = 0;
	bool bCutaway = false;
};

#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseHangarSwitchSubsystem.generated.h"

/**
 * How the switch reaches the level: the data layers of LV_Hangar by default
 * (FVerseHangarDataLayers), a scripted fake in tests. Both layers move together.
 */
class VERSEDECKS_API IVerseHangarLayers
{
public:
	virtual ~IVerseHangarLayers() = default;
	/** Asks for arena (true) or day (false). Returns false when the layers are missing. */
	virtual bool Request(bool bArena) = 0;
	/** True once the requested side is loaded and activated and the other is unloaded. */
	virtual bool IsDone(bool bArena) const = 0;
};

/** The day/arena state of deck 4. */
UENUM()
enum class EVerseHangarMode : uint8
{
	Day,
	SwitchingToArena,
	Arena,
	SwitchingToDay
};

/**
 * The hangar day/arena switch (work-packages.md WP11.8, README Arena and Duel entry). Server
 * side: it flips the data layers DL_Hangar_Day and DL_Hangar_Arena, waits until streaming is
 * done, then raises FVerseArenaSwitchEvent on the hub. The listeners do the rest: the game
 * mode starts or ends the match, VerseDestruction runs its full reset and nav rebuild,
 * VerseCrew walks the crew out of the hall (VerseDecks never includes Crew or Destruction).
 *
 * Entries: the armoury duel panel and the in-Verse quick start call RequestArena; the bridge's
 * lifecycle.show {reason: "quick_start_duel"} goes through HandleLifecycleShow.
 */
UCLASS()
class VERSEDECKS_API UVerseHangarSwitchSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** Deck id in FVerseArenaSwitchEvent::Deck. */
	static const FName HangarDeck;
	/** lifecycle.show reason that goes straight to the arena (bridge-protocol.md 12). */
	static const FName QuickStartReason;
	/** A switch is slower than this only on a broken level (A11.4: at most 2.0 s each way). */
	static constexpr float SwitchBudgetS = 2.0f;
	/** After this long the switch completes anyway and logs an error (layers stuck). */
	static constexpr float SwitchTimeoutS = 10.0f;

	static UVerseHangarSwitchSubsystem* Get(const UObject* WorldContextObject);

	/** Server: switches to the arena (true) or back to the day deck. False when nothing changes. */
	bool RequestArena(bool bArena, FName Reason = NAME_None);

	/** Server: the bridge's lifecycle.show reason; quick_start_duel turns the arena on. */
	bool HandleLifecycleShow(FName Reason);

	EVerseHangarMode GetMode() const { return Mode; }
	bool IsArenaOn() const { return Mode == EVerseHangarMode::Arena; }
	bool IsSwitching() const { return Mode == EVerseHangarMode::SwitchingToArena || Mode == EVerseHangarMode::SwitchingToDay; }
	/** Seconds the last finished switch took, request to event. */
	float GetLastSwitchSeconds() const { return LastSwitchSeconds; }
	/** Number of FVerseArenaSwitchEvent this subsystem raised. */
	int32 GetSwitchCount() const { return SwitchCount; }

	/** Replaces the data-layer access (tests). Takes ownership. */
	void SetLayers(TUniquePtr<IVerseHangarLayers> InLayers);
	/** Replaces the clock (tests); seconds. */
	void SetClock(TFunction<double()> InClock) { Clock = MoveTemp(InClock); }
	/** Runs the state machine once (Tick calls it; tests call it directly). */
	void Step();

	/** The walkable arena bounds in world cm (arena.md): crew, stations and tests use them. */
	static FBox ArenaBoundsCm();

	// UTickableWorldSubsystem
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

private:
	bool HasAuthority() const;
	double NowSeconds() const;
	void Finish();

	TUniquePtr<IVerseHangarLayers> Layers;
	TFunction<double()> Clock;
	EVerseHangarMode Mode = EVerseHangarMode::Day;
	double RequestedAt = 0.0;
	float LastSwitchSeconds = 0.f;
	int32 SwitchCount = 0;
	/** A request that came in while a switch was running; applied when it finishes. */
	TOptional<bool> Pending;
};

/** IVerseHangarLayers over the LV_Hangar data layers (UDataLayerManager). */
class VERSEDECKS_API FVerseHangarDataLayers : public IVerseHangarLayers
{
public:
	static const TCHAR* DayLayerPath;
	static const TCHAR* ArenaLayerPath;

	explicit FVerseHangarDataLayers(UWorld* InWorld) : World(InWorld) {}
	virtual bool Request(bool bArena) override;
	virtual bool IsDone(bool bArena) const override;

private:
	TWeakObjectPtr<UWorld> World;
};

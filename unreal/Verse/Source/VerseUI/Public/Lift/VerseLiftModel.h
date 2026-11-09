#pragma once

#include "CoreMinimal.h"

/** Where the lift panel was asked for (parity L-06). */
enum class EVerseLiftSource : uint8
{
	Station,
	TitleSwitch,
	ToolRail,
};

enum class EVerseDoorState : uint8
{
	Open,
	Closing,
	Closed,
	Opening,
};

/** One row of the lift panel. */
struct VERSEUI_API FVerseLiftRow
{
	FName Deck;
	/** "04" */
	FString Number;
	FString NameKey;
	FString AboutKey;
	/** The deck the person is on: marked, and the focus starts here. */
	bool bCurrent = false;
	bool bFocused = false;
};

/**
 * The turbolift (parity L-01, L-02, L-05, L-06): the panel that lists the decks top to bottom,
 * and the ride. Choosing another deck closes the doors, the deck changes while they are shut
 * for at least 400 ms, and they open within 150 ms of the first frame of the new deck. Time is
 * the caller's clock.
 */
class VERSEUI_API FVerseLiftModel
{
public:
	static constexpr double DoorCloseSeconds = 0.35;
	static constexpr double DoorOpenSeconds = 0.35;
	/** The doors stay shut at least this long. */
	static constexpr double MinClosedSeconds = 0.4;
	/** The doors start to open within this of the new deck's first frame. */
	static constexpr double MaxOpenDelaySeconds = 0.15;
	/** A ride whose deck never arrives opens the doors again after this. */
	static constexpr double RideTimeoutSeconds = 20.0;

	void SetCurrentDeck(FName Deck);
	FName GetCurrentDeck() const { return CurrentDeck; }

	// Panel
	void OpenPanel(EVerseLiftSource Source);
	void ClosePanel();
	bool IsPanelOpen() const { return bPanelOpen; }
	EVerseLiftSource GetLastSource() const { return LastSource; }
	/** The decks in contract order with the current one marked and focused. */
	TArray<FVerseLiftRow> Rows() const;
	FName GetFocusedDeck() const { return FocusedDeck; }
	void MoveFocus(int32 Direction);

	/**
	 * Picks a deck. The same deck closes the panel and rides nowhere; another deck closes the
	 * panel and starts the ride. True when a ride started.
	 */
	bool Choose(FName Deck, double Now);

	// Ride
	/** Called once, when the doors are shut: switch the deck. */
	TFunction<void(FName Deck)> TravelTo;
	/** The first frame of Deck is on screen. */
	void NotifyDeckReady(FName Deck, double Now);
	void Tick(double Now);

	bool IsRiding() const { return Doors != EVerseDoorState::Open; }
	EVerseDoorState GetDoors() const { return Doors; }
	FName GetRideTarget() const { return Target; }
	/** 0 open .. 1 shut. */
	float DoorFraction(double Now) const;

	double GetClosedAt() const { return ClosedAt; }
	double GetReadyAt() const { return ReadyAt; }
	double GetOpenStartedAt() const { return OpenStartedAt; }

private:
	FName CurrentDeck = TEXT("hangar");
	FName FocusedDeck = TEXT("hangar");
	FName Target;
	bool bPanelOpen = false;
	EVerseLiftSource LastSource = EVerseLiftSource::ToolRail;
	EVerseDoorState Doors = EVerseDoorState::Open;
	double PhaseStartedAt = 0.0;
	double RideStartedAt = 0.0;
	double ClosedAt = -1.0;
	double ReadyAt = -1.0;
	double OpenStartedAt = -1.0;
	bool bTravelled = false;
	bool bReady = false;
};

#pragma once

#include "CoreMinimal.h"

/** Where a lift ride is (parity L-02 to L-05). */
enum class EVerseLiftPhase : uint8
{
	/** Doors open, nothing rides. */
	Idle,
	/** Doors shutting on the old deck. */
	DoorsClosing,
	/** Doors shut, the new deck is loading. */
	Riding,
	/** The new deck is there; doors open. */
	DoorsOpening,
};

/** Cues a ride emits for the audio event log (parity L-07). */
enum class EVerseLiftCue : uint8
{
	DoorClose,
	Ride,
	DoorOpen,
	/** The deck did not load in time; the doors gave up (parity L-03, A-10). */
	GaveUp,
};

/**
 * The turbolift ride as a pure state machine (WP12.1), ported from the three.js stage
 * (`VerseStage.tsx:301-357`): choosing a deck shuts the doors, the deck loads while they are shut,
 * and they open 150 ms after the new deck's first frame; a load that takes longer than 5 s opens
 * them anyway and marks the deck missing. Reduced motion skips the door phase. Times are seconds
 * on any monotonic clock the caller passes in.
 */
class VERSEDECKS_API FVerseLiftTravel
{
public:
	/** Doors take this long to shut before the load starts (`DOORS_MS`). */
	static constexpr double DoorsS = 0.46;
	/** Doors open this long after the new deck's first frame. */
	static constexpr double OpenAfterArrivalS = 0.15;
	/** Doors open on their own this long after they started to shut (`DOORS_GIVE_UP_MS`). */
	static constexpr double GiveUpS = 5.0;
	/** Phase times are compared with this slack, so a clock that lands on a boundary counts as there. */
	static constexpr double EpsilonS = 1e-6;

	/** Starts a ride from `From` to `To`. False (nothing rides) for the same deck or while a ride runs. */
	bool Request(FName From, FName To, double NowS, bool bReducedMotion);

	/** Advances time; returns true exactly once, on the tick the caller must start loading `Target()`. */
	bool Tick(double NowS);

	/** The new deck showed its first frame. */
	void NotifyArrived(double NowS);

	/** The load failed outright; the doors open now and the deck is marked missing. */
	void NotifyFailed(double NowS);

	EVerseLiftPhase Phase() const { return CurrentPhase; }
	bool IsBusy() const { return CurrentPhase != EVerseLiftPhase::Idle; }
	FName Target() const { return TargetDeck; }
	FName Origin() const { return OriginDeck; }
	/** True when the last ride ended without the deck (parity A-10). */
	bool DeckMissing() const { return bDeckMissing; }
	/** Seconds from the request to the doors opening, for the last finished ride. */
	double LastRideS() const { return LastRide; }
	/** Seconds from the load start to the first frame, for the last finished ride. */
	double LastLoadS() const { return LastLoad; }

	/** Every cue since the last call (the caller forwards them to audio and logs). */
	TArray<EVerseLiftCue> TakeCues();

private:
	void Finish(double NowS);

	EVerseLiftPhase CurrentPhase = EVerseLiftPhase::Idle;
	FName OriginDeck;
	FName TargetDeck;
	double RequestedAt = 0.0;
	double LoadStartedAt = 0.0;
	double ArrivedAt = -1.0;
	bool bReduced = false;
	bool bLoadIssued = false;
	bool bDeckMissing = false;
	double LastRide = 0.0;
	double LastLoad = 0.0;
	TArray<EVerseLiftCue> Cues;
};

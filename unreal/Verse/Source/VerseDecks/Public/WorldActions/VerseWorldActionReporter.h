#pragma once

#include "CoreMinimal.h"

struct FVerseDeckManifest;
class FJsonObject;

/** One world action for the level system (bridge-protocol.md 9, `progression.action`). */
struct VERSEDECKS_API FVerseWorldAction
{
	/** daily_visit, deck_discovered or inspection. */
	FString Action;
	/** Deck id; empty for daily_visit (the server uses its own day). */
	FString Ref;

	bool operator==(const FVerseWorldAction& Other) const { return Action == Other.Action && Ref == Other.Ref; }
};

/**
 * The world actions only VerseDecks can see (WP12.11), ported from `progression/useProgressionSync.ts:90-91`
 * and `life/useWorldActions.ts:31-48`:
 *
 * - `daily_visit` on the first Visible state of a launch (parity W-01);
 * - `deck_discovered` with the deck id on the first arrival on each deck (W-02);
 * - `inspection` with the deck id once the commander stood in every room of the deck, once per deck
 *   per day (W-03). The tour is per visit: arriving on a deck again starts it over.
 *
 * Reporting twice is harmless (the server meters, W-07), so this only avoids noise. Pure: no world,
 * no bridge; the deck subsystem forwards `Sink` to the bridge client.
 */
class VERSEDECKS_API FVerseWorldActionReporter
{
public:
	TFunction<void(const FVerseWorldAction&)> Sink;

	/** The Verse window became Visible (lifecycle). */
	void NotifyVisible();

	/** The commander arrived on `Deck` (first frame after a load or a ride); starts a new room tour of it. */
	void NotifyArrived(FName Deck);

	/**
	 * The commander's feet are at `FeetCm` on `Deck`; `Day` is the local calendar day as text
	 * (today's `new Date().toDateString()`), so the inspection key rolls over at midnight.
	 */
	void NotifyPosition(const FVerseDeckManifest& Deck, const FVector& FeetCm, const FString& Day);

	/** Rooms of `Deck` visited during the current visit (sorted names, for QA and tests). */
	TArray<FName> VisitedRooms(FName Deck) const;

	/** The `data` object of the `progression.action` command for `Action` (the bridge sends it). */
	static TSharedPtr<FJsonObject> ToBridgeData(const FVerseWorldAction& Action);

	/** `{"type":"progression.action","id":..,"ts":..,"data":{"action":..,"ref":..}}` (bridge-protocol 9). */
	static FString ToBridgeJson(const FVerseWorldAction& Action, const FString& Id, double Ts);

private:
	void Emit(const FString& Action, const FString& Ref);

	bool bVisitReported = false;
	TSet<FName> Discovered;
	TMap<FName, TSet<FName>> Visited;
	TSet<FString> Inspected;
};

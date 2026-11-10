#pragma once

#include "CoreMinimal.h"

class UVerseDeckSubsystem;
struct FVerseDeckManifest;
class UWorld;

/**
 * The alignment overlay (parity Q-11), non-shipping: `Verse.Debug.Overlay [on|off]` or F9 toggles it.
 * It draws what the deck's placement files say: the room floor polygons (the walkable plan), the
 * waypoint sockets (the route nodes), every other socket and the station markers, so a person can see
 * whether the cooked level lines up with its manifest. The frame readout is the engine's `stat unit`.
 */
namespace VerseDecksOverlay
{
	struct FCounts
	{
		int32 Rooms = 0;
		int32 Waypoints = 0;
		int32 Sockets = 0;
		int32 Stations = 0;
	};

	/** What a draw of this manifest puts on screen. */
	FCounts Count(const FVerseDeckManifest& Manifest);

	/** Draws one frame of the overlay (lines and strings for the frame only). */
	void Draw(UWorld* World, const FVerseDeckManifest& Manifest);

	/** {"on", "deck", "rooms", "waypoints", "sockets", "stations"} for the current deck. */
	FString StateJson(UVerseDeckSubsystem& Decks);

	bool IsOn();
	void SetOn(bool bOn);

	/** The console command, the F9 binding and the per-frame draw while `Decks` lives. */
	void Install(UVerseDeckSubsystem& Decks);
	void Remove(UVerseDeckSubsystem& Decks);
}

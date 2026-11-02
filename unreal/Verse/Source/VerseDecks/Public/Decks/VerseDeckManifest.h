#pragma once

#include "CoreMinimal.h"

/**
 * The decks of the ship and their rooms, sockets and stations (WP12.1).
 *
 * The data comes from the zone placement files `unreal/Verse/Art/Placements/<deck>/<zone>.placement.json`
 * (contracts/art-pipeline.md 4), which `art/verse/kit/deck_import.py` writes from today's cooked deck
 * manifests. Everything here is already in Unreal space (centimetres, deck-local, coordinates.md 2);
 * nothing in this file converts from the three.js frame.
 */

/** One deck of the ship (parity B-01, B-02). */
struct VERSEDECKS_API FVerseDeckInfo
{
	/** Deck id, e.g. "bridge" (`decks.ts:7`, `progression/rules.py` VERSE_DECKS). */
	FName Id;
	/** One-based number shown on the lift and the title (parity B-02). */
	int32 Number = 0;
	/** Folder and level case: "Bridge", level /Game/Verse/Decks/Bridge/LV_Bridge. */
	FString Title;
	/** Level package path, e.g. "/Game/Verse/Decks/Bridge/LV_Bridge". */
	FString LevelPath;
};

namespace Verse::Decks
{
	/** The four decks top to bottom: bridge, ops, engineering, hangar. */
	VERSEDECKS_API TConstArrayView<FVerseDeckInfo> All();
	/** The deck with this id, or nullptr. */
	VERSEDECKS_API const FVerseDeckInfo* Find(FName Deck);
	/** Absolute folder of the placement JSON (`<project>/Art/Placements`). */
	VERSEDECKS_API FString PlacementsDir();
}

/** A room of a deck (art-pipeline 4.2 `rooms[]`, today's `ROOM_` polygons). */
struct VERSEDECKS_API FVerseDeckRoom
{
	FName Id;
	FString Name;
	FName Zone;
	/** Floor polygon on the plan, deck-local centimetres (X, Y). */
	TArray<FVector2D> PolygonCm;
	/** Floor height, deck-local centimetres. */
	double ZCm = 0.0;
	bool bMain = false;

	/** Room height band used for "standing in the room": the floor within 120 cm (`useWorldActions.ts` roomsAt). */
	static constexpr double FloorBandCm = 120.0;

	/** Even-odd point-in-polygon test on the plan, the same rule as today's `insidePolygon`. */
	bool ContainsPlan(const FVector2D& PointCm) const;
	/** True when a body standing at `FeetCm` is in this room (plan polygon and floor band). */
	bool Contains(const FVector& FeetCm) const;
};

/** A world socket (art-pipeline 4.2 `sockets[]`): seats, screens, spawns, lifts, lights, stations. */
struct VERSEDECKS_API FVerseDeckSocket
{
	/** Placement id `<kind>-<manifest id>`, unique per deck. */
	FName Id;
	/** screen, seat, stand, bunk, holo, light, door, spawn, lift, station, waypoint. */
	FName Kind;
	/** Today's manifest id (unique per kind). */
	FName ManifestId;
	FName Zone;
	FName Room;
	FName StationId;
	FName StationKind;
	/** A character standing on it faces local +X. */
	FTransform Transform;
	/** Screen plane size (screens only), centimetres. */
	FVector2D SizeCm = FVector2D::ZeroVector;
	/** Light block (lights only). */
	FName LightType;
	double LightKelvin = 0.0;
	double LightLumen = 0.0;
	double LightAttenuationCm = 0.0;
	double LightSourceSizeCm = 0.0;
	/** Free key/value strings for the consuming package. */
	TMap<FString, FString> Props;
};

/** A station (parity S-01): the `station` socket with its socket groups. */
struct VERSEDECKS_API FVerseDeckStation
{
	FName Id;
	FName Kind;
	FName Room;
	FName Zone;
	FTransform Transform;
	/** Socket group (holo, screen, seat, stand, station, lift) -> manifest ids. */
	TMap<FName, TArray<FName>> Sockets;
};

/** Everything VerseDecks knows about one deck, read from its zone placement files. */
struct VERSEDECKS_API FVerseDeckManifest
{
	FName Deck;
	TArray<FName> Zones;
	TArray<FVerseDeckRoom> Rooms;
	TArray<FVerseDeckSocket> Sockets;
	TArray<FVerseDeckStation> Stations;

	/** Adds one `verse.placement/1` document. False with `OutError` on bad JSON or a different deck. */
	bool AddPlacementJson(const FString& Json, FString& OutError);

	/** Reads every `<deck>/*.placement.json` under `PlacementsDir`. False when none parses. */
	static bool Load(FName Deck, const FString& PlacementsDir, FVerseDeckManifest& Out, FString& OutError);

	const FVerseDeckRoom* FindRoom(FName Room) const;
	const FVerseDeckStation* FindStation(FName Station) const;
	/** The socket of this kind with today's manifest id, e.g. ("spawn", "commander"). */
	const FVerseDeckSocket* FindSocket(FName Kind, FName ManifestId) const;
	/** All sockets of one kind. */
	TArray<const FVerseDeckSocket*> SocketsOfKind(FName Kind) const;
	/** Ids of the rooms a body standing at `FeetCm` is in. */
	TArray<FName> RoomsAt(const FVector& FeetCm) const;

	/** Where the commander comes aboard: the `spawn` socket on a first visit, the lift after a ride (parity B-06). */
	bool ArrivalTransform(bool bByLift, FTransform& Out) const;
};

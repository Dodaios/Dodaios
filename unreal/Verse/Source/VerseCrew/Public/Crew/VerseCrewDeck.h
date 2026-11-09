#pragma once

#include "CoreMinimal.h"

class FJsonObject;

/** Socket kinds of contracts/art-pipeline.md 4 (naming.SOCKET_KINDS) that crew life reads. */
enum class EVerseCrewSocketKind : uint8
{
	Screen,
	Seat,
	Stand,
	Bunk,
	Waypoint,
	Spawn,
	Lift,
	Station,
	Other,
};

/** One world socket of a deck, in Unreal space (cm, deck origin applied). */
struct VERSECREW_API FVerseCrewSocket
{
	FString Id;
	EVerseCrewSocketKind Kind = EVerseCrewSocketKind::Other;
	FVector Location = FVector::ZeroVector;
	/** Heading in degrees; a character on the socket faces this way (local +X). */
	float HeadingDeg = 0.f;
	FString Room;
	/** The station this socket belongs to ("" when none) and that station's kind. */
	FString StationId;
	FString StationKind;
	/** The id without its trailing number ("pit_p_3" -> "pit_p"); a row of consoles, a route. */
	FString Group;
	/** The trailing number of the id, 0 when there is none. */
	int32 Order = 0;

	/** "<kind>:<id>", unique on a deck (planner.ts socketKey). */
	const FString& Key() const;

private:
	mutable FString CachedKey;
	mutable FString CachedId;
	mutable EVerseCrewSocketKind CachedKind = EVerseCrewSocketKind::Other;
};

struct VERSECREW_API FVerseCrewRoom
{
	FString Id;
	TArray<FVector2D> PolygonCm;
	float FloorZCm = 0.f;
	bool bMain = false;
};

/** The crew-relevant content of one deck: sockets and rooms (from verse.placement/1 files). */
struct VERSECREW_API FVerseCrewDeck
{
	FName Id;
	FVector OriginCm = FVector::ZeroVector;
	TArray<FVerseCrewSocket> Sockets;
	TArray<FVerseCrewRoom> Rooms;

	const FVerseCrewSocket* FindSocket(EVerseCrewSocketKind Kind, const FString& Id) const;
	const FVerseCrewSocket* FindByKey(const FString& Key) const;
	const FVerseCrewSocket* FirstOfKind(EVerseCrewSocketKind Kind) const;
	/** The spawn new agents arrive at: the first spawn whose id starts with "arrival", else any spawn. */
	const FVerseCrewSocket* ArrivalSpawn() const;
	const FVerseCrewSocket* Lift() const;

	/** Appends the sockets and rooms of one verse.placement/1 document (zones add up). */
	bool AppendPlacementJson(const TSharedRef<FJsonObject>& Root, FString& OutError);
	bool AppendPlacementFile(const FString& Path, FString& OutError);
	/** Sorts nothing and keeps file order; call after all zones are appended. */
	void Finalize();
};

namespace VerseCrew
{
	/** A socket id's group and order, as content/loadDeck.ts socketGroup. */
	VERSECREW_API void SocketGroup(const FString& Id, FString& OutGroup, int32& OutOrder);
	VERSECREW_API EVerseCrewSocketKind ParseSocketKind(const FString& Kind);
	VERSECREW_API const TCHAR* SocketKindName(EVerseCrewSocketKind Kind);

	/** Folder of the WP15 fixture decks (Content/Verse/Test/WP15/Decks). */
	VERSECREW_API FString FixtureDeckDir();
	/** Loads Content/Verse/Test/WP15/Decks/<deck>.placement.json with the given origin. */
	VERSECREW_API bool LoadFixtureDeck(FName DeckId, const FVector& OriginCm, FVerseCrewDeck& Out, FString& OutError);
}

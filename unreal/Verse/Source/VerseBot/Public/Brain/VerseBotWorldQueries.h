#pragma once

#include "CoreMinimal.h"

// Everything the brain may ask the world (bot.md B5: "the world-query answers" of the BR1 replay).
// Every answer is either static arena data a person learns from the map (cover points, pieces,
// spawn points, zones; bot.md 3.3), the bot's own state (its weapon, its finisher ability), or a
// query evaluated against the bot's piece belief, never against piece truth (bot.md 6, DR6). No
// query takes or returns an opponent actor (F1). All positions are world cm.

/** A cover point from arena data or the auto generator (bot.md 6.2 EQS_Cover). */
struct VERSEBOT_API FVerseBotCoverPoint
{
	int32 Id = INDEX_NONE;
	FVector Location = FVector::ZeroVector;
	/** High cover hides a standing eye (1.7 m); low cover only a crouched one (1.0 m). */
	bool bHigh = true;
	/** A spot where a Bulwark can be deployed. */
	bool bBulwarkSpot = false;
	/** Arena data id of the cover edge (peek habits, 7.1); INDEX_NONE when none. */
	int32 EdgeId = INDEX_NONE;
	/** Unit vector from the cover toward the side it protects against. */
	FVector Facing = FVector::ForwardVector;
	/** 0..1, how much the covering piece costs a bolt (thin sheet low, concrete high). */
	float MaterialProtection = 1.f;
	/** Pieces whose state the cover depends on (destruction 6.2). */
	TArray<uint16, TInlineAllocator<2>> DependsOnPieces;
};

/** A destructible piece as static arena data (material, place); its state comes from belief. */
struct VERSEBOT_API FVerseBotPieceInfo
{
	uint16 PieceIndex = 0;
	FVector Center = FVector::ZeroVector;
	/** Unit normal of the face toward the bot's side is not known; this is the authored +X face. */
	FVector Normal = FVector::ForwardVector;
	/** Breach charge can open it (destruction 2). */
	bool bBreachable = false;
	/** A rifle bolt can pass it (destruction 2). */
	bool bPenetrable = false;
};

/** A path through the belief nav filter (6.1). */
struct VERSEBOT_API FVerseBotPath
{
	bool bValid = false;
	float LengthCm = 0.f;
	TArray<FVector, TInlineAllocator<8>> Waypoints;
};

/** The bot's own held weapon (it is on its HUD, 3.3). */
struct VERSEBOT_API FVerseBotWeaponInfo
{
	float Damage = 30.f;
	float PenetrationPower = 100.f;
	int32 MagazineSize = 30;
	uint8 HoleRadiusMm = 6;
};

/** Result of a believed bolt trace (4.5 Path). */
struct VERSEBOT_API FVerseBotBoltTrace
{
	/** Damage fraction left at the target, 0..1. */
	float DamageFrac = 0.f;
	/** Pieces entered. */
	int32 Pieces = 0;
};

class VERSEBOT_API IVerseBotWorldQueries
{
public:
	virtual ~IVerseBotWorldQueries() = default;

	/** Sight from Eye to Target through the believed pieces (holes the bot has seen honoured). */
	virtual bool TestSight(const FVector& Eye, const FVector& Target) = 0;

	/** The own weapon's bolt from Origin to Target through the believed pieces (at most 3). */
	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon) = 0;

	/** Nav path through UVerseBeliefNavFilter; bCrouch uses the Crouch agent. */
	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) = 0;

	/** Cover points within RadiusCm of Center. */
	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) = 0;

	/** Destructible pieces within RadiusCm of Center. */
	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) = 0;

	/** Spawn points of the arena (public rule, 3.3). */
	virtual void GetSpawnPoints(TArray<FVector>& Out) = 0;

	/** Arena zone id (about 20 zones, 7.1); INDEX_NONE outside the arena. */
	virtual int32 GetZoneId(const FVector& Location) = 0;

	/** The own weapon in the active slot. */
	virtual FVerseBotWeaponInfo GetOwnWeapon() = 0;

	/** The own finisher ability could activate now (it gates on the rules, not on the opponent). */
	virtual bool CanActivateFinisher() = 0;
};

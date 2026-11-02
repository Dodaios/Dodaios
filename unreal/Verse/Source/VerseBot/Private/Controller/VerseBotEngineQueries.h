#pragma once

#include "Brain/VerseBotWorldQueries.h"
#include "CoreMinimal.h"
#include "UObject/WeakObjectPtr.h"

class UWorld;
class AController;

/**
 * The controller's default world queries until the producers land: static geometry only for sight
 * (object type WorldStatic, never pawns, so no opponent truth), straight-line paths (the Recast
 * query behind UVerseBeliefNavFilter needs NavigationSystem in VerseBot.Build.cs), no cover or
 * piece data (WP11 arena data, WP06 pieces), spawn points from the level's player starts, zones as
 * a 10 m grid. Every answer is public map knowledge or the bot's own state (bot.md 3.3).
 */
class FVerseBotEngineQueries final : public IVerseBotWorldQueries
{
public:
	explicit FVerseBotEngineQueries(AController& InOwner) : Owner(&InOwner) {}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) override;
	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& Weapon) override;
	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) override;
	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) override;
	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) override;
	virtual void GetSpawnPoints(TArray<FVector>& Out) override;
	virtual int32 GetZoneId(const FVector& Location) override;
	virtual FVerseBotWeaponInfo GetOwnWeapon() override;
	virtual bool CanActivateFinisher() override;

private:
	TWeakObjectPtr<AController> Owner;
};

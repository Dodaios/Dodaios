#pragma once

#include "Brain/VerseBotWorldQueries.h"
#include "CoreMinimal.h"
#include "Engine/EngineTypes.h"
#include "UObject/WeakObjectPtr.h"

class UWorld;
class AController;

/**
 * The controller's default world queries until the producers land. Every answer is public map
 * knowledge or the bot's own state (bot.md 3.3):
 * - Sight and bolt traces run on the VerseSight channel only (pawns ignore it, so no opponent
 *   truth) and treat every destructible piece as its believed state. Without WP06/WP07
 *   piece belief that is Intact for every piece: a segment that crosses a piece's intact bounds is
 *   blocked, whatever the server's current proxy shows, so a hole the bot never perceived never
 *   opens a line (DR6, F7). Glass follows the channel rules (sight passes, bolts stop).
 * - No world: every line is blocked.
 * - Paths on the nav mesh; cover points from FVerseBotArenaData once the runtime nav mesh is built;
 *   no piece data (WP06); spawn points from the arena's spawn points; zones a 10 m grid.
 */
class VERSEBOT_API FVerseBotEngineQueries final : public IVerseBotWorldQueries
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

	/** Static arena data (cover points); set once the nav mesh is built. */
	void SetArena(TSharedPtr<const struct FVerseBotArenaData> InArena) { Arena = MoveTemp(InArena); }

	/** True when the segment crosses the box (the believed-intact piece rule). */
	static bool SegmentHitsBox(const FBox& Box, const FVector& From, const FVector& To);

private:
	/** Pieces crossed by the segment, counted against their intact bounds. */
	int32 PiecesCrossed(const FVector& From, const FVector& To);
	void CachePieceBounds(UWorld& World);
	bool GlassCrossed(const FVector& From, const FVector& To) const;
	bool TraceSight(UWorld& World, const FVector& From, const FVector& To) const;

	TWeakObjectPtr<AController> Owner;
	/** Intact bounds of every destructible piece, taken once per world before any can break. */
	TArray<FBox> PieceBounds;
	/** Glazing bounds: sight passes them on VerseSight, bolts stop. */
	TArray<FBox> GlassBounds;
	TWeakObjectPtr<UWorld> CachedWorld;
	TSharedPtr<const struct FVerseBotArenaData> Arena;
};

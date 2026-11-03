#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Engine/EngineTypes.h"
#include "Engine/HitResult.h"
#include "Subsystems/WorldSubsystem.h"

#include "VersePenetrationSubsystem.generated.h"

class UPhysicalMaterial;
class UPrimitiveComponent;
class USceneComponent;
class UVerseBoltHoleComponent;
class UVersePenetrationTable;
struct FHitResult;

/** A registered piece proxy: which piece and table row a collision component stands for. */
struct FVersePieceProxyInfo
{
	uint16 PieceIndex = 0;
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::Concrete;
	/** The frame hole records are stored in (piece-local, destruction.md 3.3). */
	TWeakObjectPtr<USceneComponent> Frame;
};

/** One stretch of solid along a ray inside one proxy: where the ray enters and leaves it. */
struct FVersePenetrationRun
{
	FVector Entry = FVector::ZeroVector;
	FVector Exit = FVector::ZeroVector;
};

using FVersePenetrationRuns = TArray<FVersePenetrationRun, TInlineAllocator<4>>;

/** What one query met on one component: its first hit and its solid runs, in ray order. */
struct FVersePenetrationCrossing
{
	const UPrimitiveComponent* Component = nullptr;
	/** Of the first hit: the body it hit and that hit's physical material. */
	FName BoneName;
	TWeakObjectPtr<UPhysicalMaterial> PhysMaterial;
	FVector Entry = FVector::ZeroVector;
	/** Exit of the last solid run. */
	FVector Exit = FVector::ZeroVector;
	/** Sum of the solid runs in cm: the traced thickness, air between shapes left out. */
	double SolidCm = 0.0;
	FVersePenetrationRuns Runs;
	/** More components lay behind this one than one query visits. */
	bool bTruncated = false;
};

/** The crossings of one query; a bolt rarely meets more than a few components. */
using FVersePenetrationCrossings = TArray<FVersePenetrationCrossing, TInlineAllocator<4>>;

/**
 * The penetration and sight queries of destruction.md 2 and 5 (WP03.3, WP03.4), one per world.
 *
 * TraceBolt walks the bolt segment on `VerseBolt` against the current proxies. One overlap-mode
 * multi trace lists every shape; the shapes of one component merge into one piece entry whose
 * traced thickness is the solid along the ray (one reverse component trace per solid run, so a
 * proxy of several convex shapes or a concave Holed proxy is charged once and air is free). It
 * looks up the row (registered pieces by their material, everything else through its physical
 * material, unmapped geometry as `concrete`) and applies the reference-thickness cost formula and
 * the 3-piece limit. A piece whose bolt holes contain the entry and exit point of every solid run
 * is flown through without cost and is not reported.
 *
 * TestSight walks `VerseSight`: intact glass (an overlap on that channel) and catwalk grating are
 * see-through, damaged glass and every other piece block unless the two-point hole test passes,
 * world geometry blocks. Server and bot use exactly this function; the client renders the same
 * hole records.
 *
 * The piece owner (WP06's destruction manager) registers each piece proxy, hands in its
 * IVersePieceQuery and the hole component. Without them every proxy is an anonymous world
 * surface and every piece answers Intact (the Core null stub).
 */
UCLASS()
class VERSEDESTRUCTION_API UVersePenetrationSubsystem : public UWorldSubsystem, public IVersePenetrationQuery
{
	GENERATED_BODY()

public:
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	// IVersePenetrationQuery
	virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power, float Damage,
		uint8 RadiusMm, int32 MaxPieces) const override;
	virtual bool TestSight(const FVector& Eye, const FVector& Target) const override;

	/** The table in use. Starts as the contract table, replaced by Data/destruction/penetration.json when it imports cleanly. */
	const UVersePenetrationTable* GetTable() const { return Table; }
	void SetTable(UVersePenetrationTable* InTable);

	/** Piece truth for the sight rules (glass state). Not owned; pass nullptr before the owner goes. */
	void SetPieceQuery(const IVersePieceQuery* InPieceQuery);

	/** The arena's bolt holes. Not owned. */
	void SetHoleSource(UVerseBoltHoleComponent* InHoles);
	UVerseBoltHoleComponent* GetHoleSource() const { return HoleSource.Get(); }

	void RegisterPieceProxy(UPrimitiveComponent* Proxy, uint16 PieceIndex, EVersePenetrationMaterial Material, USceneComponent* Frame = nullptr);
	void UnregisterPieceProxy(UPrimitiveComponent* Proxy);
	const FVersePieceProxyInfo* FindPieceProxy(const UPrimitiveComponent* Proxy) const;

	/** World to piece-local transform of a piece, from any of its registered proxies. */
	bool GetPieceFrame(uint16 PieceIndex, FTransform& OutPieceToWorld) const;

	/**
	 * Server: records the holes a traced bolt leaves (destruction.md 5): one record per passed
	 * piece that keeps holes, axis through the entry and exit midpoint along the bolt.
	 * Returns how many records were added.
	 */
	int32 RecordBoltHoles(TConstArrayView<FVersePenetrationHit> Hits, const FVector& Dir, uint8 RadiusMm, uint32 ServerTimeMs) const;

	/** Exit of the outermost solid of Component on a ray that entered at Entry, when no other shape entries are known. */
	static bool FindExit(const UPrimitiveComponent& Component, const FVector& Entry, const FVector& Dir, FVector& OutExit);

	/**
	 * Solid runs of Component along Dir from Entry. LaterEntries are the entry points of the
	 * component's other shapes on the same ray, ascending; a run ends where the point just in
	 * front of the next entry is in air. Returns false when the last run found no exit.
	 */
	static bool FindSolidRuns(const UPrimitiveComponent& Component, const FVector& Entry, const FVector& Dir,
		TConstArrayView<FVector> LaterEntries, FVersePenetrationRuns& OutRuns);

	/** The components on Start..End for Channel, one crossing each, in ray order (at most MaxSurfacesPerQuery). */
	void CollectCrossings(const FVector& Start, const FVector& End, ECollisionChannel Channel, FName StatName,
		FVersePenetrationCrossings& OutCrossings) const;

	/** Most components one query visits before it gives up (bolt or sight). */
	static constexpr int32 MaxSurfacesPerQuery = 16;

private:
	UPROPERTY(Transient)
	TObjectPtr<UVersePenetrationTable> Table;

	TWeakObjectPtr<UVerseBoltHoleComponent> HoleSource;
	const IVersePieceQuery* PieceQuery = nullptr;
	TMap<TObjectKey<UPrimitiveComponent>, FVersePieceProxyInfo> Proxies;
	TMap<uint16, TWeakObjectPtr<USceneComponent>> PieceFrames;

	EVersePieceState PieceState(uint16 PieceIndex) const;
	bool PassesHoles(const FVersePieceProxyInfo& Info, const FVector& EntryWorld, const FVector& ExitWorld) const;
	bool PassesHoles(const FVersePieceProxyInfo& Info, const FVersePenetrationCrossing& Crossing) const;
};

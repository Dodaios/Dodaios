#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Subsystems/WorldSubsystem.h"

#include "VersePenetrationSubsystem.generated.h"

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

/**
 * The penetration and sight queries of destruction.md 2 and 5 (WP03.3, WP03.4), one per world.
 *
 * TraceBolt walks the bolt segment on `VerseBolt` against the current proxies: for every
 * component it enters it measures the traced thickness (entry hit, then a reverse trace on that
 * component for the exit), looks up the row (registered pieces by their material, everything
 * else through its physical material, unmapped geometry as `concrete`) and applies the
 * reference-thickness cost formula and the 3-piece limit. A piece whose bolt holes contain both
 * the entry and the exit point is flown through without cost and is not reported.
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

	/** Exit point of a straight ray that entered Component at Entry (reverse trace on that component). */
	static bool FindExit(const UPrimitiveComponent& Component, const FVector& Entry, const FVector& Dir, FVector& OutExit);

	/** Most surfaces one query visits before it gives up (bolt or sight). */
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
};

#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "GameFramework/Actor.h"
#include "Pieces/VersePieceTypes.h"

#include "VerseDestructible.generated.h"

class UGeometryCollection;
class UStaticMesh;
class UStaticMeshComponent;

/** One authored look of a state variant: collision proxy, render mesh, opening centroid. */
USTRUCT(BlueprintType)
struct VERSEDESTRUCTION_API FVersePieceVariant
{
	GENERATED_BODY()

	/** SM_<Piece>_Proxy_<State>[_<n>]: gameplay collision, never rendered. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	TObjectPtr<UStaticMesh> Proxy = nullptr;

	/** Render mesh of this variant; empty = keep the Intact render mesh. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	TObjectPtr<UStaticMesh> Render = nullptr;

	/** Piece-local centre of the opening (variant choice, destruction.md 3.1). */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	FVector OpeningCentroid = FVector::ZeroVector;
};

/**
 * One authored debris burst of a state (destruction.md 10): GC_<Piece>_<State>_<n>, the chunks
 * of the Intact fracture that fly out of that opening (Holed, Breached) or of the whole piece
 * (Destroyed), at most the class's body budget. A piece may ship several sizes per state; the
 * debris subsystem takes the largest one the budget grants.
 */
USTRUCT(BlueprintType)
struct VERSEDESTRUCTION_API FVersePieceDebrisSet
{
	GENERATED_BODY()

	/** Holed, Breached or Destroyed. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	EVersePieceState State = EVersePieceState::Destroyed;

	/** Holed / Breached variant index; ignored for Destroyed. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	uint8 Variant = 0;

	/** Soft, so a server never loads it. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	TSoftObjectPtr<UGeometryCollection> Collection;

	/** Rigid bodies (leaf chunks) of Collection; the validator checks it against the asset. */
	UPROPERTY(EditAnywhere, Category = "Destructible")
	int32 Bodies = 0;
};

/**
 * One breakable thing (architecture 4): wall panel, cladding wall, container wall, glass pane,
 * catwalk segment or ceiling panel. Placed by zone owners from WP06 classes and assets. It never
 * decides its own state: AVerseDestructionManager (server) does and calls ApplyPresentation on
 * server and clients from the replicated item.
 */
UCLASS(Blueprintable)
class VERSEDESTRUCTION_API AVerseDestructible : public AActor
{
	GENERATED_BODY()

public:
	AVerseDestructible();

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Destructible")
	EVersePieceClass PieceClass = EVersePieceClass::WallPanel;

	/** Penetration material; must match the class (validator). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Destructible")
	EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;

	/** SM_<Piece>_Proxy_Intact (Damaged reuses it). */
	UPROPERTY(EditAnywhere, Category = "Destructible|Proxies")
	TObjectPtr<UStaticMesh> IntactProxy = nullptr;

	/** Up to 4 Holed variants. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Proxies")
	TArray<FVersePieceVariant> HoledVariants;

	/** Up to 4 Breached variants. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Proxies")
	TArray<FVersePieceVariant> BreachedVariants;

	/** Optional Remains proxy and look on the floor when Destroyed. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Proxies")
	FVersePieceVariant Remains;

	/** GC_<Piece>, the full fracture (input of the per-state sets); never spawned as a whole. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Debris", meta = (AllowedClasses = "/Script/GeometryCollectionEngine.GeometryCollection"))
	TSoftObjectPtr<UObject> GeometryCollection;

	/** Per-state debris bursts (GC_<Piece>_<State>_<n>); an empty list means no rigid debris. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Debris")
	TArray<FVersePieceDebrisSet> DebrisSets;

	/** The debris sets of a state and variant (Destroyed ignores the variant). */
	TArray<const FVersePieceDebrisSet*> FindDebrisSets(EVersePieceState State, uint8 Variant) const;

	/** Mantle links through a low breach (live while Breached), piece-local. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Nav")
	TArray<FVersePieceNavLink> MantleLinks;

	/** Drop-down links to the floor below (live while Destroyed; catwalks), piece-local. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Nav")
	TArray<FVersePieceNavLink> DropLinks;

	/**
	 * Piece-local vertices of the Intact proxy, captured in the editor (construction, save) so
	 * cooked builds and the dedicated server run the 150 cm breach test on the same points as
	 * the editor (destruction.md 3.2). Empty: the proxy box corners.
	 */
	UPROPERTY(VisibleAnywhere, Category = "Destructible|Proxies")
	TArray<FVector> ProxyVertices;

	/** Fills ProxyVertices from the Intact proxy's source geometry (editor only; no-op in cooked builds). */
	void CaptureProxyVertices();

	/** Used only when no Intact proxy mesh is set (tests, graybox): the Intact proxy box, piece-local. */
	UPROPERTY(EditAnywhere, Category = "Destructible|Proxies")
	FBox FallbackIntactBounds = FBox(ForceInit);

	UStaticMeshComponent* GetRenderComponent() const { return RenderMesh; }
	UStaticMeshComponent* GetProxyComponent() const { return ProxyMesh; }

	/** The One File Per Actor GUID, kept at runtime (destruction.md 8). */
	const FGuid& GetPieceGuid() const { return PieceGuid; }
	void SetPieceGuid(const FGuid& Guid) { PieceGuid = Guid; }

	/** Index in DA_PieceManifest, set by the manager; INDEX_NONE before registration. */
	int32 GetPieceIndex() const { return PieceIndex; }
	void SetPieceIndex(int32 Index) { PieceIndex = Index; }

	/** The static description the simulation runs on. */
	FVersePieceDef MakeDef() const;

	/** Shows the state's proxy and look. bInstant: late join / reset, no transition effects. */
	void ApplyPresentation(EVersePieceState State, uint8 Variant, EVersePieceState RepairFrom);

	EVersePieceState GetPresentedState() const { return PresentedState; }
	uint8 GetPresentedVariant() const { return PresentedVariant; }
	/** The proxy mesh live now (nullptr when the state has no proxy). */
	UStaticMesh* GetPresentedProxy() const;

	virtual void PostLoad() override;
	virtual void OnConstruction(const FTransform& Transform) override;
#if WITH_EDITOR
	virtual void PreSave(FObjectPreSaveContext SaveContext) override;
#endif

protected:
	/** Registers with the arena's manager (World Partition streaming, destruction.md 8). */
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type EndPlayReason) override;

public:

protected:
	UPROPERTY(VisibleAnywhere, Category = "Destructible")
	TObjectPtr<UStaticMeshComponent> RenderMesh;

	UPROPERTY(VisibleAnywhere, Category = "Destructible")
	TObjectPtr<UStaticMeshComponent> ProxyMesh;

	/** Copied from the actor GUID in the editor; actor GUIDs are editor-only. */
	UPROPERTY(VisibleAnywhere, Category = "Destructible")
	FGuid PieceGuid;

private:
	void CaptureGuid();
	const FVersePieceVariant* FindVariant(EVersePieceState State, uint8 Variant) const;

	UPROPERTY(Transient)
	TObjectPtr<UStaticMesh> IntactRender = nullptr;

	int32 PieceIndex = INDEX_NONE;
	EVersePieceState PresentedState = EVersePieceState::Intact;
	uint8 PresentedVariant = 0;
};

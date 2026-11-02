#pragma once

#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

#include "VerseHoleRenderComponent.generated.h"

class UDecalComponent;
class UMaterialInstanceDynamic;
class UMaterialInterface;
class UMeshComponent;
class USceneComponent;
class UTextureRenderTarget2D;
class UVerseBoltHoleComponent;

/**
 * Client presentation of bolt holes (destruction.md 5, WP03.6). Draws exactly the replicated
 * hole records, so what the person sees through a hole is what the bot can see:
 *
 * - a 256 x 256 opacity mask per piece in piece UV space, created on the piece's first hole and
 *   bound to the piece mesh's `HoleMask` texture parameter (black discs = open);
 * - one rim decal per hole, spanning the piece's thickness along the hole axis, with the rim
 *   glow of VerseHoleGlow (white-amber, tau 1.2 s, dull red at 2.5 s, off at 4 s, then charred);
 * - at most 128 glowing holes; the oldest cools first. No dynamic light per hole.
 *
 * Bookkeeping (mask slots, decal slots, the glowing set) runs everywhere; GPU objects are made
 * only where something renders (not on a dedicated server, not under -nullrhi).
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSEDESTRUCTION_API UVerseHoleRenderComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseHoleRenderComponent();

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	void SetHoleSource(UVerseBoltHoleComponent* InHoles);

	/**
	 * A piece's visible mesh. LocalBounds is the piece's solid in its frame; the mask maps the
	 * piece's largest face of those bounds to UV 0..1 (the UV layout the piece builder authors).
	 */
	void RegisterPieceVisual(uint16 PieceIndex, UMeshComponent* Mesh, const FBox& LocalBounds, USceneComponent* Frame = nullptr);

	/** Server time in ms the glow ages against; default: the world's time seconds. */
	void SetServerTimeSource(TFunction<uint32()> InNow);

	/** Brings masks, decals and glow up to date now (normally on the next tick). */
	void Sync();

	/** UV of a piece-local point on the largest face of LocalBounds. */
	static FVector2D HoleUV(const FBox& LocalBounds, const FVector& LocalPointCm);
	/** Mask pixels of a hole radius on that face. */
	static float HoleRadiusPx(const FBox& LocalBounds, float RadiusCm, int32 MaskSize);

	/** True where GPU objects are made (client with a real RHI). */
	static bool CanRender(const UWorld* World);

	int32 NumMaskSlots() const { return MaskPieces.Num(); }
	int32 NumHoleSlots() const { return HoleSlots.Num(); }
	int32 NumGlowing() const { return GlowingCount; }
	bool HasMask(uint16 PieceIndex) const { return MaskPieces.Contains(PieceIndex); }
	UTextureRenderTarget2D* GetMask(uint16 PieceIndex) const;

	UPROPERTY(EditAnywhere, Category = "Verse")
	TSoftObjectPtr<UMaterialInterface> RimDecalMaterial;

	UPROPERTY(EditAnywhere, Category = "Verse")
	FName MaskParameter = TEXT("HoleMask");

	UPROPERTY(EditAnywhere, Category = "Verse")
	FName GlowParameter = TEXT("RimGlow");

	UPROPERTY(EditAnywhere, Category = "Verse")
	FName GlowColorParameter = TEXT("RimGlowColor");

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 MaskSize = 256;

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 GlowingCap = 128;

	UPROPERTY(EditAnywhere, Category = "Verse")
	float GlowTauS = 1.2f;

	UPROPERTY(EditAnywhere, Category = "Verse")
	float GlowEndS = 4.f;

private:
	struct FPieceVisual
	{
		TWeakObjectPtr<UMeshComponent> Mesh;
		TWeakObjectPtr<USceneComponent> Frame;
		FBox LocalBounds = FBox(ForceInit);
	};

	struct FHoleSlot
	{
		FVerseBoltHole Hole;
		TWeakObjectPtr<UDecalComponent> Decal;
		TWeakObjectPtr<UMaterialInstanceDynamic> Material;
		bool bGlowing = false;
	};

	TWeakObjectPtr<UVerseBoltHoleComponent> HoleSource;
	FDelegateHandle HolesChangedHandle;
	TFunction<uint32()> NowMs;
	TMap<uint16, FPieceVisual> Pieces;
	TSet<uint16> MaskPieces;
	TArray<FHoleSlot> HoleSlots;
	int32 GlowingCount = 0;
	bool bDirty = true;
	bool bWarnedNoMaterial = false;

	UPROPERTY(Transient)
	TMap<uint16, TObjectPtr<UTextureRenderTarget2D>> Masks;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UDecalComponent>> DecalPool;

	void HandleHolesChanged();
	uint32 CurrentTimeMs() const;
	void RebuildSlots();
	void RedrawMasks(const TSet<uint16>& PiecesToDraw);
	void UpdateGlow();
	UDecalComponent* AcquireDecal(int32 Index);
};

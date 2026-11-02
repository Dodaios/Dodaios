#pragma once

#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"

#include "VerseBoltHoleComponent.generated.h"

class UVerseBoltHoleComponent;
class UVerseDestructionTuning;

/** What AddHole did. */
UENUM()
enum class EVerseHoleAddResult : uint8
{
	/** The hole is recorded. */
	Added,
	/** Hole 25 on a wall: the piece's holes are cleared and OnPieceHoleCap fired; the piece goes Holed. */
	PieceHoled,
	/** Grating, concrete and armor steel keep no holes (dents and scorches only). */
	NotHoleMaterial,
	/** Only the server records holes (DR1). */
	NotAuthority
};

/** (PieceIndex, hole centroid piece-local cm). The piece owner turns the wall Holed with the variant nearest the centroid. */
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVersePieceHoleCap, uint16, const FVector&);
/** Any change of the hole set, on server and clients (the renderer listens). */
DECLARE_MULTICAST_DELEGATE(FOnVerseHolesChanged);

/**
 * Bolt hole records of one arena (destruction.md 5, WP03.5). Lives on AVerseDestructionManager
 * (always relevant). The records replicate as one array, oldest first; it moves to an
 * FFastArraySerializer once VerseDestruction links NetCore (CCR: the module edges of
 * architecture.md 2 give it Core, CoreUObject, Engine and VerseCore only). Caps: 24 per piece, 512 per arena. Hole 25 on a wall piece clears its holes
 * and asks the owner to turn it Holed; on glass and ceiling panels the piece's oldest hole goes.
 * At the arena cap the oldest hole of the piece with the most holes is dropped. A reset bumps
 * the epoch and clears everything.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSEDESTRUCTION_API UVerseBoltHoleComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseBoltHoleComponent();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	/** Takes the hole caps from DA_DestructionTuning. */
	void ApplyTuning(const UVerseDestructionTuning& Tuning);

	/** Server: record a hole whose axis passes AxisPointLocalCm along AxisDirectionLocal (piece-local). */
	EVerseHoleAddResult AddHole(uint16 PieceIndex, EVersePenetrationMaterial Material, const FVector& AxisPointLocalCm,
		const FVector& AxisDirectionLocal, uint8 RadiusMm, uint32 ServerTimeMs);

	/** Server: the piece went Holed, Breached or Destroyed, or was repaired. */
	void ClearPiece(uint16 PieceIndex);

	/** Server: full reset (destruction.md 11). Every hole goes, the epoch becomes NewEpoch. */
	void ResetAll(uint16 NewEpoch);

	/** Holes of one piece, oldest first (current epoch only). */
	TConstArrayView<FVerseBoltHole> GetPieceHoles(uint16 PieceIndex) const;

	/** Every hole of the current epoch, oldest first. */
	void GetAllHoles(TArray<FVerseBoltHole>& OutHoles) const;

	int32 Num() const;
	int32 NumOnPiece(uint16 PieceIndex) const;
	uint16 GetEpoch() const { return Epoch; }
	int32 GetHolesPerPiece() const { return HolesPerPiece; }
	int32 GetHolesPerArena() const { return HolesPerArena; }

	FOnVersePieceHoleCap OnPieceHoleCap;
	FOnVerseHolesChanged OnHolesChanged;

protected:
	UFUNCTION()
	void OnRep_Holes();

	UFUNCTION()
	void OnRep_Epoch();

private:
	/** Every hole of the arena, oldest first (insertion order). */
	UPROPERTY(ReplicatedUsing = OnRep_Holes)
	TArray<FVerseBoltHole> Holes;

	UPROPERTY(ReplicatedUsing = OnRep_Epoch)
	uint16 Epoch = 0;

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 HolesPerPiece = 24;

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 HolesPerArena = 512;

	mutable TMap<uint16, TArray<FVerseBoltHole>> ByPiece;
	mutable bool bCacheDirty = true;

	bool HasServerAuthority() const;
	void RebuildCache() const;
	void MarkChanged();
	void HandleReplicatedChange();
	void EvictForArenaCap();
	void RemoveOldestOnPiece(uint16 PieceIndex);
};

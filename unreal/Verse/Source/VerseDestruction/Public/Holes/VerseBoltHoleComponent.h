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

/**
 * One replicated slot of the arena's hole records. A slot keeps its index for the life of its
 * hole, so adding or evicting a hole changes one slot and replication sends only that slot.
 * Sequence orders holes by age (server insertion order); 0 marks a free slot.
 */
USTRUCT()
struct VERSEDESTRUCTION_API FVerseBoltHoleSlot
{
	GENERATED_BODY()

	UPROPERTY()
	FVerseBoltHole Hole;

	UPROPERTY()
	uint32 Sequence = 0;

	bool IsUsed() const { return Sequence != 0; }

	bool operator==(const FVerseBoltHoleSlot& Other) const
	{
		return Sequence == Other.Sequence && Hole.PieceIndex == Other.Hole.PieceIndex && Hole.Epoch == Other.Hole.Epoch
			&& Hole.ServerTimeMs == Other.Hole.ServerTimeMs;
	}
};

/** (PieceIndex, hole centroid piece-local cm). The piece owner turns the wall Holed with the variant nearest the centroid. */
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVersePieceHoleCap, uint16, const FVector&);
/**
 * A change of the hole set, on server and clients (the renderer listens): the pieces whose holes
 * changed, or bAll after a reset or an epoch change.
 */
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseHolesChanged, TConstArrayView<uint16> /*Pieces*/, bool /*bAll*/);

/**
 * Bolt hole records of one arena (destruction.md 5, WP03.5). Lives on AVerseDestructionManager
 * (always relevant). Caps: 24 per piece, 512 per arena. Hole 25 on a wall piece clears its
 * holes and asks the owner to turn it Holed; on glass and ceiling panels the piece's oldest hole
 * goes. At the arena cap the oldest hole of the piece with the most holes is dropped. A reset
 * bumps the epoch and clears everything.
 *
 * Replication: the contract asks for an FFastArraySerializer, which needs NetCore, and the
 * module edges of architecture.md 2 give VerseDestruction only Core, CoreUObject, Engine and
 * VerseCore (CCR #1134). Until that edge exists the records are a slot array with stable indices
 * and a free list: an add, an eviction or a clear rewrites only the slots it touches, nothing
 * shifts, and property replication sends exactly those slots. The per-piece view is kept up to
 * date incrementally on the server and from a slot diff on clients.
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

	/**
	 * The two-point hole test of FVerseBoltHole::RayPassesHoles on one piece, with each hole's axis
	 * decoded once when it is recorded instead of on every query (the same arithmetic).
	 */
	bool RayPassesPieceHoles(uint16 PieceIndex, const FVector& EntryLocalCm, const FVector& ExitLocalCm) const;

	/** The raw slots (free ones included); a slot index identifies one hole while it lives. */
	TConstArrayView<FVerseBoltHoleSlot> GetSlots() const { return Slots; }
	/** True when a slot holds a hole of the current epoch. */
	bool IsLiveSlot(int32 SlotIndex) const;

	int32 Num() const { return LiveCount; }
	int32 NumOnPiece(uint16 PieceIndex) const;
	uint16 GetEpoch() const { return Epoch; }
	int32 GetHolesPerPiece() const { return HolesPerPiece; }
	int32 GetHolesPerArena() const { return HolesPerArena; }

	FOnVersePieceHoleCap OnPieceHoleCap;
	FOnVerseHolesChanged OnHolesChanged;

protected:
	UFUNCTION()
	void OnRep_Slots();

	UFUNCTION()
	void OnRep_Epoch();

private:
	/** Every hole of the arena at a stable index; free slots have Sequence 0. */
	UPROPERTY(ReplicatedUsing = OnRep_Slots)
	TArray<FVerseBoltHoleSlot> Slots;

	UPROPERTY(ReplicatedUsing = OnRep_Epoch)
	uint16 Epoch = 0;

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 HolesPerPiece = 24;

	UPROPERTY(EditAnywhere, Category = "Verse")
	int32 HolesPerArena = 512;

	/** One piece's live holes, oldest first, and the slot each one sits in. */
	/** A hole axis as FVerseBoltHole::ContainsPoint reads it, decoded once. */
	struct FHoleAxis
	{
		FVector PointCm = FVector::ZeroVector;
		FVector Direction = FVector::ForwardVector;
		double RadiusSq = 0.0;

		explicit FHoleAxis(const FVerseBoltHole& Hole);
		bool Contains(const FVector& PieceLocalCm) const;
	};

	struct FPieceHoles
	{
		TArray<FVerseBoltHole> Holes;
		TArray<int32> SlotIndices;
		TArray<FHoleAxis> Axes;
	};

	TMap<uint16, FPieceHoles> ByPiece;
	TArray<int32> FreeSlots;
	uint32 NextSequence = 1;
	int32 LiveCount = 0;
	/** Clients: the slots as last seen, to find which pieces a replication update touched. */
	TArray<FVerseBoltHoleSlot> SeenSlots;

	bool HasServerAuthority() const;
	void RemoveSlot(int32 SlotIndex);
	void EvictForArenaCap();
	void RebuildPieces(TConstArrayView<uint16> Pieces);
	void RebuildAll();
	void Broadcast(TConstArrayView<uint16> Pieces, bool bAll);
};

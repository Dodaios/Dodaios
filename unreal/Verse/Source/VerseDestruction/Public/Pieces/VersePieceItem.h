#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Net/Serialization/FastArraySerializer.h"

#include "VersePieceItem.generated.h"

class AVerseDestructionManager;
struct FVersePieceItemArray;

/**
 * One replicated piece (destruction.md 3.3). Items change only on a state change, an HP change
 * of at least one quantum, or a hole; the fast array then sends only that item.
 */
USTRUCT()
struct VERSEDESTRUCTION_API FVersePieceItem : public FFastArraySerializerItem
{
	GENERATED_BODY()

	/** Index into DA_PieceManifest. */
	UPROPERTY()
	uint16 PieceIndex = 0;

	UPROPERTY()
	EVersePieceState State = EVersePieceState::Intact;

	/** round(255 x hp / maxHp) */
	UPROPERTY()
	uint8 HealthQ = 255;

	/** Holed or Breached variant, else 0. */
	UPROPERTY()
	uint8 Variant = 0;

	/** Valid while Repairing. */
	UPROPERTY()
	EVersePieceState RepairFrom = EVersePieceState::Intact;

	UPROPERTY()
	uint32 LastSeed = 0;

	/** 1 unit = 0.1 N s. */
	UPROPERTY()
	int16 LastImpulse[3] = {0, 0, 0};

	/** Piece-local, 1 mm. */
	UPROPERTY()
	int16 LastLocation[3] = {0, 0, 0};

	UPROPERTY()
	uint32 StateTimeMs = 0;

	UPROPERTY()
	uint16 Epoch = 0;

	/** The state whose proxy is live: RepairFrom while Repairing (destruction.md 7). */
	EVersePieceState GetProxyState() const { return State == EVersePieceState::Repairing ? RepairFrom : State; }

	/** True when the item carries a fracture record (seed, impulse or location set). */
	bool HasFractureRecord() const;

	/**
	 * Packed wire form (destruction.md 3.3): PieceIndex 11 bits (<= 2,000 pieces), State 3,
	 * HealthQ 8, Variant 2 (<= 4 per state), RepairFrom 3 only while Repairing, one bit for the
	 * fracture record (Seed 32, Impulse 3 x 16, Location 3 x 16) when it is set, StateTimeMs 32,
	 * Epoch 16. Lossless for every value the simulation writes. The fast array adds its own
	 * 32-bit element id per item and a 16-byte header per delta (FastArraySerializer.h).
	 */
	bool NetSerialize(FArchive& Ar, class UPackageMap* Map, bool& bOutSuccess);

	/** Bytes this item takes on the wire, measured with a bit writer round trip of NetSerialize. */
	static int32 MeasureWireBytes(const FVersePieceItem& Item);
	/** Fast array overhead per delta and per item (header keys and counts, element id). */
	static constexpr int32 FastArrayHeaderBytes = 16;
	static constexpr int32 FastArrayItemIdBytes = 4;
	static constexpr int32 MaxPieceIndexBits = 11;

	void PostReplicatedAdd(const FVersePieceItemArray& InArraySerializer);
	void PostReplicatedChange(const FVersePieceItemArray& InArraySerializer);
};

template <>
struct TStructOpsTypeTraits<FVersePieceItem> : public TStructOpsTypeTraitsBase2<FVersePieceItem>
{
	enum
	{
		WithNetSerializer = true,
	};
};

/** The manager's fast array (destruction.md 3.3). */
USTRUCT()
struct VERSEDESTRUCTION_API FVersePieceItemArray : public FFastArraySerializer
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FVersePieceItem> Items;

	/** Not replicated: the manager that owns this array (client callbacks). */
	UPROPERTY(NotReplicated)
	TObjectPtr<AVerseDestructionManager> Owner = nullptr;

	bool NetDeltaSerialize(FNetDeltaSerializeInfo& DeltaParms)
	{
		return FFastArraySerializer::FastArrayDeltaSerialize<FVersePieceItem, FVersePieceItemArray>(Items, DeltaParms, *this);
	}
};

template <>
struct TStructOpsTypeTraits<FVersePieceItemArray> : public TStructOpsTypeTraitsBase2<FVersePieceItemArray>
{
	enum
	{
		WithNetDeltaSerializer = true,
	};
};

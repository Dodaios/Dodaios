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

	/** Bits of the packed wire form of a full item (budget counter, destruction.md 10). */
	static int32 PackedBits();

	void PostReplicatedAdd(const FVersePieceItemArray& InArraySerializer);
	void PostReplicatedChange(const FVersePieceItemArray& InArraySerializer);
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

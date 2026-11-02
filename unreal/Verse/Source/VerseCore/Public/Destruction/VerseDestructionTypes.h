#pragma once

#include "CoreMinimal.h"

#include "VerseDestructionTypes.generated.h"

// Shared destruction types (contracts/destruction.md). Values and order of every enum are
// frozen; new materials append. Units: centimetres, Z-up, server time in milliseconds.

/** destruction.md 3.1 */
UENUM(BlueprintType)
enum class EVersePieceState : uint8
{
	Intact,
	Damaged,
	Holed,
	Breached,
	Destroyed,
	Repairing
};

/** Material wire ids of DA_PenetrationTable (destruction.md 2), in wire order. */
UENUM(BlueprintType)
enum class EVersePenetrationMaterial : uint8
{
	SheetMetal,
	ContainerWall,
	Glass,
	CladdingPanel,
	CatwalkGrating,
	CeilingPanel,
	Concrete,
	ArmorSteel
};

/** Debris type column of the penetration table. */
UENUM(BlueprintType)
enum class EVerseDebrisType : uint8
{
	MetalShards,
	CorrugatedChunks,
	GlassShards,
	PanelChunks,
	GratingTwisted,
	CeilingTile,
	DustChips,
	SparksOnly
};

/** FVerseFractureEvent::Cause and FVersePieceDamage::Cause (destruction.md 4). */
UENUM(BlueprintType)
enum class EVerseFractureCause : uint8
{
	Bolt,
	Breach,
	Melee,
	Repair,
	Reset
};

/** Piece classes of destruction.md 3.2. */
UENUM(BlueprintType)
enum class EVersePieceClass : uint8
{
	WallPanel,
	CladdingWall,
	ContainerWall,
	GlassPane,
	CatwalkSegment,
	CeilingPanel
};

/** Which destruction change made a Noise.Fracture (destruction.md 6.2). */
UENUM(BlueprintType)
enum class EVerseFractureNoise : uint8
{
	Breach,
	WallBreak,
	Glass,
	Tile,
	BoltHole
};

namespace Verse::Destruction
{
	/** PieceIndex meaning "all pieces" (reset only). */
	inline constexpr uint16 AllPieces = 0xFFFF;
	/** Instigator slot meaning "world" (repair, reset). */
	inline constexpr uint8 WorldInstigator = 0xFF;
	/** One unit of Impulse is 0.1 N s. */
	inline constexpr double ImpulseUnitNs = 0.1;
	/** A bolt passes at most this many pieces (destruction.md 2). */
	inline constexpr int32 MaxPenetrations = 3;
	/** Audible range of a fracture is loudness x this (bot.md 3.2). */
	inline constexpr float FractureRangePerLoudnessM = 40.f;
	/** Repair drone flight and weld loudness (destruction.md 7). */
	inline constexpr float DroneLoudness = 0.15f;

	/** Loudness carried in FVerseNoiseEvent for Noise.Fracture (destruction.md 6.2). */
	VERSECORE_API float FractureLoudness(EVerseFractureNoise Kind);

	/** HealthQ = round(255 x hp / maxHp), clamped to 0..255 (destruction.md 3.2). */
	VERSECORE_API uint8 QuantizeHealth(float Hp, float MaxHp);

	/** Octahedral encoding of a unit direction into two int8 (FVerseBoltHole axis). */
	VERSECORE_API void EncodeOctahedral(const FVector& Direction, int8& OutX, int8& OutY);
	VERSECORE_API FVector DecodeOctahedral(int8 X, int8 Y);
}

/** Replicated and hub-published on every state change, repair and reset (destruction.md 4). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseFractureEvent
{
	GENERATED_BODY()

	/** 0xFFFF = all pieces (reset only). */
	UPROPERTY()
	uint16 PieceIndex = 0;

	UPROPERTY()
	EVersePieceState FromState = EVersePieceState::Intact;

	UPROPERTY()
	EVersePieceState ToState = EVersePieceState::Intact;

	UPROPERTY()
	EVerseFractureCause Cause = EVerseFractureCause::Bolt;

	/** Chosen proxy variant. */
	UPROPERTY()
	uint8 Variant = 0;

	/** Server RNG draw; drives the Chaos strain pattern and Niagara seeds. */
	UPROPERTY()
	uint32 Seed = 0;

	/** World space, 0.1 N s per unit. */
	UPROPERTY()
	int16 Impulse[3] = {0, 0, 0};

	/** Piece-local, 1 mm; impact or charge point. */
	UPROPERTY()
	int16 Location[3] = {0, 0, 0};

	/** Strain field radius, cm. */
	UPROPERTY()
	uint8 Radius = 0;

	/** Player slot, 0xFF = world (repair, reset). */
	UPROPERTY()
	uint8 Instigator = Verse::Destruction::WorldInstigator;

	UPROPERTY()
	uint32 ServerTimeMs = 0;

	/** Events with an old epoch are dropped. */
	UPROPERTY()
	uint16 Epoch = 0;
};

/** One bolt hole (destruction.md 5), about 16 bytes. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseBoltHole
{
	GENERATED_BODY()

	UPROPERTY()
	uint16 PieceIndex = 0;

	/** Axis position, piece-local, 1 mm. */
	UPROPERTY()
	int16 AxisPositionMm[3] = {0, 0, 0};

	/** Axis direction, octahedral. */
	UPROPERTY()
	int8 AxisDirectionOct[2] = {0, 0};

	UPROPERTY()
	uint8 RadiusMm = 0;

	UPROPERTY()
	uint32 ServerTimeMs = 0;

	UPROPERTY()
	uint16 Epoch = 0;

	/** Axis point in piece-local centimetres. */
	FVector GetAxisPointCm() const;
	/** Unit axis direction, piece-local. */
	FVector GetAxisDirection() const;
	/** True if the piece-local point (cm) lies within RadiusMm of the hole axis. */
	bool ContainsPoint(const FVector& PieceLocalCm) const;

	/** Builds a record from piece-local centimetres and a direction (quantised to mm and octahedral int8). */
	static FVerseBoltHole Make(uint16 InPieceIndex, const FVector& AxisPointCm, const FVector& AxisDirection,
		uint8 InRadiusMm, uint32 InServerTimeMs, uint16 InEpoch);

	/**
	 * The two-point sightline test (destruction.md 5): a sight or bolt ray through a piece passes
	 * only if both its entry and exit points lie within the radius of one hole's axis. Server and
	 * bot use exactly this test.
	 */
	static bool RayPassesHoles(TConstArrayView<FVerseBoltHole> Holes, const FVector& EntryLocalCm, const FVector& ExitLocalCm);
};

/** One server piece damage request (IVersePieceDamage::ApplyPieceDamage, destruction.md frozen interface). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePieceDamage
{
	GENERATED_BODY()

	UPROPERTY()
	uint16 PieceIndex = 0;

	/** Piece hp. */
	UPROPERTY()
	float Amount = 0.f;

	/** Bolt, Breach or Melee. */
	UPROPERTY()
	EVerseFractureCause Cause = EVerseFractureCause::Bolt;

	/** World, cm. */
	UPROPERTY()
	FVector Location = FVector::ZeroVector;

	UPROPERTY()
	FVector Direction = FVector::ForwardVector;

	/** Player state id, -1 = world. */
	UPROPERTY()
	int32 InstigatorId = -1;

	/** Breach charge radius, cm (0 for bolts and melee). */
	UPROPERTY()
	float BreachRadiusCm = 0.f;
};

/** One piece a bolt trace entered (IVersePenetrationQuery::TraceBolt). */
USTRUCT(BlueprintType)
struct VERSECORE_API FVersePenetrationHit
{
	GENERATED_BODY()

	UPROPERTY()
	uint16 PieceIndex = 0;

	UPROPERTY()
	uint8 MaterialWireId = 0;

	/** World, cm. */
	UPROPERTY()
	FVector Entry = FVector::ZeroVector;

	UPROPERTY()
	FVector Exit = FVector::ZeroVector;

	UPROPERTY()
	float TracedThicknessCm = 0.f;

	/** Power left after this piece. */
	UPROPERTY()
	float PowerLeft = 0.f;

	/** Damage left after this piece. */
	UPROPERTY()
	float DamageLeft = 0.f;

	UPROPERTY()
	bool bPassed = false;
};

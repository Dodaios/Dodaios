#pragma once

#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Destruction/VerseDestructionInterfaces.h"
#include "Penetration/VersePenetrationPhysicalMaterial.h"
#include "Tests/AutomationCommon.h"
#include "UObject/StrongObjectPtr.h"

class AActor;
class UBoxComponent;
class UVerseBoltHoleComponent;
class UVersePenetrationSubsystem;

/**
 * Piece truth for WP03 tests, standing in for WP06's destruction manager (work-packages.md 0.3).
 * Implements IVersePieceQuery exactly; unknown pieces answer Intact, concrete, an invalid box.
 */
class FFakePieceQuery : public IVersePieceQuery
{
public:
	TMap<uint16, EVersePieceState> States;
	TMap<uint16, EVersePenetrationMaterial> Materials;
	TMap<uint16, FBox> Bounds;

	virtual EVersePieceState GetPieceState(uint16 PieceIndex) const override;
	virtual EVersePenetrationMaterial GetPieceMaterial(uint16 PieceIndex) const override;
	virtual FBox GetPieceBounds(uint16 PieceIndex) const override;
	virtual TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const override;
};

/**
 * A manually ticked game world with the penetration subsystem, a hole component on a stand-in
 * manager actor and the fake piece query wired in. Pieces are AFakePiece-style solid boxes:
 * a plain actor whose root is a box proxy registered with a piece index and material id.
 */
class FVerseWP03World : public FTestWorldWrapper
{
public:
	~FVerseWP03World();

	bool Create();
	/** Steps physics so new and moved proxies are visible to scene queries. */
	void Settle();

	UWorld* World() const { return TestWorld; }

	/** A solid box piece; Thickness along the actor's X axis, Height along Z, Width along Y (cm). */
	AActor* SpawnPiece(uint16 PieceIndex, EVersePenetrationMaterial Material, const FVector& Center, float ThicknessCm,
		float WidthCm = 100.f, float HeightCm = 100.f, const FRotator& Rotation = FRotator::ZeroRotator);

	/** Non-destructible world geometry; null Surface = no Verse physical material at all. */
	AActor* SpawnWorldBox(const EVerseWorldSurface* Surface, const FVector& Center, float ThicknessCm, float WidthCm = 200.f,
		float HeightCm = 200.f);

	UBoxComponent* BoxOf(AActor* Actor) const;
	void DestroyActor(AActor* Actor);

	UVersePenetrationSubsystem* Penetration = nullptr;
	UVerseBoltHoleComponent* Holes = nullptr;
	AActor* Manager = nullptr;
	FFakePieceQuery Query;

private:
	AActor* SpawnBox(const FVector& Center, const FRotator& Rotation, const FVector& HalfExtent, FName Profile, UPhysicalMaterial* PhysMat);
	TArray<TStrongObjectPtr<UPhysicalMaterial>> PhysMats;
};

namespace VerseWP03Test
{
	/** Path of the WP03.1 golden fixture. */
	FString GoldenFixturePath();
}

#endif // WITH_DEV_AUTOMATION_TESTS

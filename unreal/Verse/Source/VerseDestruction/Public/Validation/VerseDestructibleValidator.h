#pragma once

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "UObject/Object.h"

#include "VerseDestructibleValidator.generated.h"

class AVerseDestructible;
class UStaticMesh;
class UVersePieceManifest;

/** A triangle soup in piece-local centimetres (any source: mesh description, render data, tests). */
struct VERSEDESTRUCTION_API FVerseMeshSoup
{
	TArray<FVector> Positions;
	/** Three per triangle, counter-clockwise seen from outside (Unreal winding is irrelevant: both orientations are accepted as long as they are consistent). */
	TArray<int32> Indices;

	void AddBox(const FVector& Min, const FVector& Max);
	void AddQuad(const FVector& A, const FVector& B, const FVector& C, const FVector& D);
	int32 NumTriangles() const { return Indices.Num() / 3; }
};

/** What one check found. */
struct VERSEDESTRUCTION_API FVerseValidationReport
{
	TArray<FString> Errors;
	/** Median inward thickness along the piece's thickness axis, cm (0 if not measured). */
	float MeasuredThicknessCm = 0.f;

	bool IsOk() const { return Errors.Num() == 0; }
	void Merge(const FVerseValidationReport& Other, const FString& Prefix);
};

/**
 * UVerseDestructibleValidator (destruction.md 9): breakable pieces are solid, closed volumes whose
 * thickness matches the material's reference thickness within 10 %; every reachable state has
 * a proxy, the geometry collection is present, the material matches the class, and the piece is
 * in the manifest. Pure checks plus a commandlet entry, so both unreal-static/unreal-build and
 * automation tests run the same code.
 */
UCLASS()
class VERSEDESTRUCTION_API UVerseDestructibleValidator : public UObject
{
	GENERATED_BODY()

public:
	static constexpr float ThicknessTolerance = 0.10f;

	/** Watertight and manifold after welding coincident positions; no zero-area faces. */
	static FVerseValidationReport CheckClosed(const FVerseMeshSoup& Mesh);

	/** Median inward ray distance from faces facing along +-Axis (unit, piece-local). */
	static float MeasureThickness(const FVerseMeshSoup& Mesh, const FVector& Axis);

	/** Closed and, when RefThicknessCm > 0, thickness within 10 % of it. */
	static FVerseValidationReport CheckSolid(const FVerseMeshSoup& Mesh, const FVector& Axis, float RefThicknessCm);

	/** Piece-local axis along which a class measures its thickness. */
	static FVector ThicknessAxis(EVersePieceClass Class);

	/** Reference thickness of the class's material (DA_PenetrationTable). */
	static float RefThicknessCm(EVersePieceClass Class);

	/** Proxies of every reachable state, GC, material and manifest, plus the geometry of every mesh it can read. */
	static FVerseValidationReport ValidatePiece(const AVerseDestructible& Piece, const UVersePieceManifest* Manifest);

	/** Triangles of LOD 0 of a static mesh (render data; cooked meshes need CPU access). False if unreadable. */
	static bool ReadMesh(const UStaticMesh& Mesh, FVerseMeshSoup& Out);
};

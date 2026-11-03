#include "Validation/VerseDestructibleValidator.h"

#include "Destruction/VersePenetrationTable.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VersePieceManifest.h"
#include "Pieces/VersePieceTypes.h"
#include "Debris/VerseDebrisBudget.h"
#include "Debris/VerseDebrisSubsystem.h"
#include "GeometryCollection/GeometryCollectionObject.h"
#include "StaticMeshResources.h"
#if WITH_EDITORONLY_DATA
#include "MeshAttributes.h"
#include "MeshDescription.h"
#endif

void FVerseMeshSoup::AddQuad(const FVector& A, const FVector& B, const FVector& C, const FVector& D)
{
	const int32 Base = Positions.Num();
	Positions.Append({A, B, C, D});
	Indices.Append({Base, Base + 1, Base + 2, Base, Base + 2, Base + 3});
}

void FVerseMeshSoup::AddBox(const FVector& Min, const FVector& Max)
{
	const FVector P[8] = {
		{Min.X, Min.Y, Min.Z}, {Max.X, Min.Y, Min.Z}, {Max.X, Max.Y, Min.Z}, {Min.X, Max.Y, Min.Z},
		{Min.X, Min.Y, Max.Z}, {Max.X, Min.Y, Max.Z}, {Max.X, Max.Y, Max.Z}, {Min.X, Max.Y, Max.Z},
	};
	// Outward, consistent winding.
	AddQuad(P[0], P[3], P[2], P[1]); // bottom
	AddQuad(P[4], P[5], P[6], P[7]); // top
	AddQuad(P[0], P[1], P[5], P[4]); // -Y
	AddQuad(P[2], P[3], P[7], P[6]); // +Y
	AddQuad(P[1], P[2], P[6], P[5]); // +X
	AddQuad(P[3], P[0], P[4], P[7]); // -X
}

void FVerseValidationReport::Merge(const FVerseValidationReport& Other, const FString& Prefix)
{
	for (const FString& Error : Other.Errors)
	{
		Errors.Add(Prefix + Error);
	}
	if (Other.MeasuredThicknessCm > 0.f && MeasuredThicknessCm <= 0.f)
	{
		MeasuredThicknessCm = Other.MeasuredThicknessCm;
	}
}

namespace
{
	/** Weld positions on a 0.01 mm grid. */
	TArray<int32> Weld(const FVerseMeshSoup& Mesh, int32& OutUnique)
	{
		TMap<FIntVector, int32> Grid;
		TArray<int32> Map;
		Map.SetNum(Mesh.Positions.Num());
		for (int32 Index = 0; Index < Mesh.Positions.Num(); ++Index)
		{
			const FVector& P = Mesh.Positions[Index];
			const FIntVector Key(FMath::RoundToInt32(P.X * 1000.0), FMath::RoundToInt32(P.Y * 1000.0), FMath::RoundToInt32(P.Z * 1000.0));
			const int32* Found = Grid.Find(Key);
			Map[Index] = Found ? *Found : Grid.Add(Key, Grid.Num());
		}
		OutUnique = Grid.Num();
		return Map;
	}

	bool RayTriangle(const FVector& Origin, const FVector& Dir, const FVector& A, const FVector& B, const FVector& C, double& OutT)
	{
		const FVector E1 = B - A;
		const FVector E2 = C - A;
		const FVector P = FVector::CrossProduct(Dir, E2);
		const double Det = FVector::DotProduct(E1, P);
		if (FMath::Abs(Det) < 1e-12)
		{
			return false;
		}
		const double Inv = 1.0 / Det;
		const FVector S = Origin - A;
		const double U = FVector::DotProduct(S, P) * Inv;
		if (U < -1e-9 || U > 1.0 + 1e-9)
		{
			return false;
		}
		const FVector Q = FVector::CrossProduct(S, E1);
		const double V = FVector::DotProduct(Dir, Q) * Inv;
		if (V < -1e-9 || U + V > 1.0 + 1e-9)
		{
			return false;
		}
		OutT = FVector::DotProduct(E2, Q) * Inv;
		return OutT > 1e-4;
	}
}

FVerseValidationReport UVerseDestructibleValidator::CheckClosed(const FVerseMeshSoup& Mesh)
{
	FVerseValidationReport Report;
	if (Mesh.NumTriangles() == 0)
	{
		Report.Errors.Add(TEXT("no triangles"));
		return Report;
	}
	int32 Unique = 0;
	const TArray<int32> Map = Weld(Mesh, Unique);
	TMap<TPair<int32, int32>, int32> Directed;
	int32 Degenerate = 0;
	for (int32 Tri = 0; Tri < Mesh.NumTriangles(); ++Tri)
	{
		const int32 V[3] = {Map[Mesh.Indices[Tri * 3]], Map[Mesh.Indices[Tri * 3 + 1]], Map[Mesh.Indices[Tri * 3 + 2]]};
		const FVector& A = Mesh.Positions[Mesh.Indices[Tri * 3]];
		const FVector& B = Mesh.Positions[Mesh.Indices[Tri * 3 + 1]];
		const FVector& C = Mesh.Positions[Mesh.Indices[Tri * 3 + 2]];
		if (V[0] == V[1] || V[1] == V[2] || V[0] == V[2] || FVector::CrossProduct(B - A, C - A).SizeSquared() < 1e-10)
		{
			++Degenerate;
			continue;
		}
		for (int32 Edge = 0; Edge < 3; ++Edge)
		{
			Directed.FindOrAdd(TPair<int32, int32>(V[Edge], V[(Edge + 1) % 3])) += 1;
		}
	}
	if (Degenerate > 0)
	{
		Report.Errors.Add(FString::Printf(TEXT("%d zero-area faces"), Degenerate));
	}
	int32 Open = 0;
	int32 NonManifold = 0;
	for (const TPair<TPair<int32, int32>, int32>& Edge : Directed)
	{
		if (Edge.Value > 1)
		{
			++NonManifold; // two faces wind the same way over one edge: doubled or flipped faces
		}
		const int32* Reverse = Directed.Find(TPair<int32, int32>(Edge.Key.Value, Edge.Key.Key));
		if (!Reverse)
		{
			++Open;
		}
		else if (*Reverse != Edge.Value)
		{
			++NonManifold;
		}
	}
	if (Open > 0)
	{
		Report.Errors.Add(FString::Printf(TEXT("not watertight: %d open edges (one-sided shell or double plane)"), Open));
	}
	if (NonManifold > 0)
	{
		Report.Errors.Add(FString::Printf(TEXT("not manifold: %d edges shared inconsistently"), NonManifold));
	}
	return Report;
}

float UVerseDestructibleValidator::MeasureThickness(const FVerseMeshSoup& Mesh, const FVector& Axis)
{
	struct FSample
	{
		double Distance;
		double Weight;
	};
	TArray<FSample> Samples;
	const FVector UnitAxis = Axis.GetSafeNormal();
	for (int32 Tri = 0; Tri < Mesh.NumTriangles(); ++Tri)
	{
		const FVector& A = Mesh.Positions[Mesh.Indices[Tri * 3]];
		const FVector& B = Mesh.Positions[Mesh.Indices[Tri * 3 + 1]];
		const FVector& C = Mesh.Positions[Mesh.Indices[Tri * 3 + 2]];
		const FVector Cross = FVector::CrossProduct(B - A, C - A);
		const double Area = Cross.Size() * 0.5;
		if (Area < 1e-8)
		{
			continue;
		}
		const FVector Normal = Cross / (Area * 2.0);
		if (FMath::Abs(FVector::DotProduct(Normal, UnitAxis)) < 0.95)
		{
			continue;
		}
		const FVector Centroid = (A + B + C) / 3.0;
		double Best = TNumericLimits<double>::Max();
		// Inward first; a mesh wound inside-out shoots the other way.
		for (const double Sign : {-1.0, 1.0})
		{
			const FVector Dir = Normal * Sign;
			const FVector Origin = Centroid + Dir * 1e-3;
			for (int32 Other = 0; Other < Mesh.NumTriangles(); ++Other)
			{
				if (Other == Tri)
				{
					continue;
				}
				double T = 0.0;
				if (RayTriangle(Origin, Dir, Mesh.Positions[Mesh.Indices[Other * 3]], Mesh.Positions[Mesh.Indices[Other * 3 + 1]],
						Mesh.Positions[Mesh.Indices[Other * 3 + 2]], T))
				{
					Best = FMath::Min(Best, T + 1e-3);
				}
			}
			if (Best < TNumericLimits<double>::Max())
			{
				break;
			}
		}
		if (Best < TNumericLimits<double>::Max())
		{
			Samples.Add({Best, Area});
		}
	}
	if (Samples.Num() == 0)
	{
		return 0.f;
	}
	Samples.Sort([](const FSample& L, const FSample& R) { return L.Distance < R.Distance; });
	double Total = 0.0;
	for (const FSample& Sample : Samples)
	{
		Total += Sample.Weight;
	}
	double Acc = 0.0;
	for (const FSample& Sample : Samples)
	{
		Acc += Sample.Weight;
		if (Acc >= Total * 0.5)
		{
			return float(Sample.Distance);
		}
	}
	return float(Samples.Last().Distance);
}

FVerseValidationReport UVerseDestructibleValidator::CheckSolid(const FVerseMeshSoup& Mesh, const FVector& Axis, float RefThickness)
{
	FVerseValidationReport Report = CheckClosed(Mesh);
	if (RefThickness <= 0.f)
	{
		return Report;
	}
	Report.MeasuredThicknessCm = MeasureThickness(Mesh, Axis);
	if (Report.MeasuredThicknessCm <= 0.f)
	{
		Report.Errors.Add(TEXT("thickness not measurable (no inward hit)"));
	}
	else if (FMath::Abs(Report.MeasuredThicknessCm - RefThickness) > RefThickness * ThicknessTolerance)
	{
		Report.Errors.Add(FString::Printf(TEXT("thickness %.3f cm, the material wants %.3f cm +-10 %%"), Report.MeasuredThicknessCm, RefThickness));
	}
	return Report;
}

FVector UVerseDestructibleValidator::ThicknessAxis(EVersePieceClass Class)
{
	switch (Class)
	{
	case EVersePieceClass::CatwalkSegment:
	case EVersePieceClass::CeilingPanel:
		return FVector::UpVector;
	default:
		return FVector::RightVector; // wall-like pieces: thickness along piece-local Y (art kit convention)
	}
}

float UVerseDestructibleValidator::RefThicknessCm(EVersePieceClass Class)
{
	const FVersePenetrationRow* Row = GetDefault<UVersePenetrationTable>()->FindRow(uint8(VerseMaterialOfClass(Class)));
	return Row ? Row->RefThicknessCm : 0.f;
}

bool UVerseDestructibleValidator::ReadMesh(const UStaticMesh& Mesh, FVerseMeshSoup& Out)
{
	Out = FVerseMeshSoup();
#if WITH_EDITORONLY_DATA
	// The source geometry: for a Nanite mesh LOD 0 render data is only the fallback mesh.
	if (const FMeshDescription* Source = Mesh.GetMeshDescription(0))
	{
		const FMeshConstAttributes Attributes(*Source);
		const TVertexAttributesConstRef<FVector3f> Positions = Attributes.GetVertexPositions();
		TMap<FVertexID, int32> Slot;
		for (const FVertexID Vertex : Source->Vertices().GetElementIDs())
		{
			Slot.Add(Vertex, Out.Positions.Add(FVector(Positions[Vertex])));
		}
		for (const FTriangleID Triangle : Source->Triangles().GetElementIDs())
		{
			for (const FVertexID Vertex : Source->GetTriangleVertices(Triangle))
			{
				Out.Indices.Add(Slot.FindChecked(Vertex));
			}
		}
		if (Out.NumTriangles() > 0)
		{
			return true;
		}
		Out = FVerseMeshSoup();
	}
#endif
	const FStaticMeshRenderData* RenderData = Mesh.GetRenderData();
	if (!RenderData || RenderData->LODResources.Num() == 0)
	{
		return false;
	}
	const FStaticMeshLODResources& Lod = RenderData->LODResources[0];
	const FPositionVertexBuffer& Positions = Lod.VertexBuffers.PositionVertexBuffer;
	if (!Positions.GetAllowCPUAccess() && FPlatformProperties::RequiresCookedData())
	{
		return false;
	}
	for (uint32 Vertex = 0; Vertex < Positions.GetNumVertices(); ++Vertex)
	{
		Out.Positions.Add(FVector(Positions.VertexPosition(Vertex)));
	}
	TArray<uint32> Indices;
	Lod.IndexBuffer.GetCopy(Indices);
	for (const uint32 I : Indices)
	{
		Out.Indices.Add(int32(I));
	}
	return Out.NumTriangles() > 0;
}

FVerseValidationReport UVerseDestructibleValidator::ValidatePiece(const AVerseDestructible& Piece, const UVersePieceManifest* Manifest)
{
	FVerseValidationReport Report;
	const EVersePieceClass Class = Piece.PieceClass;
	if (Piece.Material != VerseMaterialOfClass(Class))
	{
		Report.Errors.Add(FString::Printf(TEXT("material %s does not match class %s"),
			*UEnum::GetValueAsString(Piece.Material), *UEnum::GetValueAsString(Class)));
	}
	if (!Piece.IntactProxy)
	{
		Report.Errors.Add(TEXT("missing proxy: Intact"));
	}
	const bool bWall = Class == EVersePieceClass::WallPanel || Class == EVersePieceClass::CladdingWall || Class == EVersePieceClass::ContainerWall;
	if (bWall)
	{
		auto CheckVariants = [&Report](const TArray<FVersePieceVariant>& Variants, const TCHAR* State)
		{
			if (Variants.Num() == 0)
			{
				Report.Errors.Add(FString::Printf(TEXT("missing proxy: %s"), State));
			}
			if (Variants.Num() > 4)
			{
				Report.Errors.Add(FString::Printf(TEXT("%d %s variants, at most 4"), Variants.Num(), State));
			}
			for (int32 Index = 0; Index < Variants.Num(); ++Index)
			{
				if (!Variants[Index].Proxy)
				{
					Report.Errors.Add(FString::Printf(TEXT("missing proxy: %s variant %d"), State, Index));
				}
			}
		};
		CheckVariants(Piece.HoledVariants, TEXT("Holed"));
		CheckVariants(Piece.BreachedVariants, TEXT("Breached"));
	}
	// Glass breaks into Niagara shards only (destruction.md 2); every other class ships its
	// per-state debris sets (GC_<Piece>_<State>_<n>), each within the per-fracture body cap and
	// declaring the chunk count the asset really has.
	if (Class != EVersePieceClass::GlassPane && Piece.DebrisSets.Num() == 0)
	{
		Report.Errors.Add(TEXT("missing debris geometry collection sets"));
	}
	const int32 MaxPerFracture = FVerseDebrisBudget::FConfig::High().MaxBodiesPerFracture;
	for (int32 Index = 0; Index < Piece.DebrisSets.Num(); ++Index)
	{
		const FVersePieceDebrisSet& Set = Piece.DebrisSets[Index];
		if (Set.Collection.IsNull())
		{
			Report.Errors.Add(FString::Printf(TEXT("debris set %d has no geometry collection"), Index));
			continue;
		}
		if (Set.Bodies <= 0 || Set.Bodies > MaxPerFracture)
		{
			Report.Errors.Add(FString::Printf(TEXT("debris set %d declares %d bodies, allowed 1 to %d"), Index, Set.Bodies, MaxPerFracture));
		}
		if (const UGeometryCollection* Collection = Set.Collection.LoadSynchronous())
		{
			const int32 Real = UVerseDebrisSubsystem::CountBodies(*Collection);
			if (Real != Set.Bodies)
			{
				Report.Errors.Add(FString::Printf(TEXT("debris set %d declares %d bodies, the asset has %d"), Index, Set.Bodies, Real));
			}
		}
		else
		{
			Report.Errors.Add(FString::Printf(TEXT("debris set %d: %s does not load"), Index, *Set.Collection.ToString()));
		}
	}
	if (!Manifest)
	{
		Report.Errors.Add(TEXT("no manifest to check the piece against"));
	}
	else if (Manifest->IndexOf(Piece.GetPieceGuid()) == INDEX_NONE)
	{
		Report.Errors.Add(TEXT("piece is not in the manifest"));
	}
	if (!Piece.GetPieceGuid().IsValid())
	{
		Report.Errors.Add(TEXT("no piece GUID"));
	}

	const FVector Axis = ThicknessAxis(Class);
	const float Ref = RefThicknessCm(Class);
	auto CheckMesh = [&Report, &Axis](const UStaticMesh* Mesh, float Thickness, const FString& Label)
	{
		if (!Mesh)
		{
			return; // a missing mesh is reported by the proxy checks above
		}
		FVerseMeshSoup Soup;
		if (!ReadMesh(*Mesh, Soup))
		{
			Report.Errors.Add(Label + TEXT(": geometry not readable (no source mesh, no CPU-accessible render data)"));
			return;
		}
		Report.Merge(CheckSolid(Soup, Axis, Thickness), Label + TEXT(": "));
	};
	CheckMesh(Piece.GetRenderComponent() ? Piece.GetRenderComponent()->GetStaticMesh() : nullptr, Ref, TEXT("render"));
	CheckMesh(Piece.IntactProxy, Ref, TEXT("proxy Intact"));
	for (int32 Index = 0; Index < Piece.HoledVariants.Num(); ++Index)
	{
		// Proxies keep the exact material thickness in every state (DR5, destruction.md 9).
		CheckMesh(Piece.HoledVariants[Index].Proxy, Ref, FString::Printf(TEXT("proxy Holed %d"), Index));
		CheckMesh(Piece.HoledVariants[Index].Render, Ref, FString::Printf(TEXT("render Holed %d"), Index));
	}
	for (int32 Index = 0; Index < Piece.BreachedVariants.Num(); ++Index)
	{
		CheckMesh(Piece.BreachedVariants[Index].Proxy, Ref, FString::Printf(TEXT("proxy Breached %d"), Index));
		CheckMesh(Piece.BreachedVariants[Index].Render, Ref, FString::Printf(TEXT("render Breached %d"), Index));
	}
	CheckMesh(Piece.Remains.Proxy, 0.f, TEXT("proxy Remains"));
	CheckMesh(Piece.Remains.Render, 0.f, TEXT("render Remains"));
	return Report;
}

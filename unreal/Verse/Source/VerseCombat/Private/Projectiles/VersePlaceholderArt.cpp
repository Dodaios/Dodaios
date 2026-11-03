#include "Projectiles/VersePlaceholderArt.h"

#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "MeshDescription.h"
#include "Misc/App.h"
#include "StaticMeshAttributes.h"

namespace
{
	const TCHAR* MaterialPath = TEXT("/Game/Verse/Test/WP02/M_WP02_Placeholder.M_WP02_Placeholder");
	const FName SlotName(TEXT("Placeholder"));

	struct FBuilder
	{
		FMeshDescription Desc;
		FStaticMeshAttributes Attr;
		FPolygonGroupID Group;

		FBuilder()
			: Attr(Desc)
		{
			Attr.Register();
			Group = Desc.CreatePolygonGroup();
			Attr.GetPolygonGroupMaterialSlotNames()[Group] = SlotName;
		}

		/** One triangle; A, B, C wind clockwise seen from the side the normal N points to. */
		void Tri(const FVector3f& A, const FVector3f& B, const FVector3f& C, const FVector3f& NA, const FVector3f& NB, const FVector3f& NC)
		{
			const FVector3f P[3] = {A, B, C};
			const FVector3f N[3] = {NA, NB, NC};
			TArray<FVertexInstanceID, TFixedAllocator<3>> Corners;
			for (int32 I = 0; I < 3; ++I)
			{
				const FVertexID V = Desc.CreateVertex();
				Attr.GetVertexPositions()[V] = P[I];
				const FVertexInstanceID Inst = Desc.CreateVertexInstance(V);
				Attr.GetVertexInstanceNormals()[Inst] = N[I];
				Attr.GetVertexInstanceUVs()[Inst] = FVector2f(P[I].X / 100.f + 0.5f, P[I].Y / 100.f + 0.5f);
				Corners.Add(Inst);
			}
			Desc.CreateTriangle(Group, Corners);
		}

		void FlatTri(const FVector3f& A, const FVector3f& B, const FVector3f& C)
		{
			const FVector3f N = FVector3f::CrossProduct(C - A, B - A).GetSafeNormal();
			Tri(A, B, C, N, N, N);
		}

		void Quad(const FVector3f& A, const FVector3f& B, const FVector3f& C, const FVector3f& D)
		{
			FlatTri(A, B, C);
			FlatTri(A, C, D);
		}
	};

	void BuildBox(FBuilder& B)
	{
		const float H = 50.f;
		auto P = [H](int32 X, int32 Y, int32 Z) { return FVector3f(X ? H : -H, Y ? H : -H, Z ? H : -H); };
		B.Quad(P(1, 0, 0), P(1, 0, 1), P(1, 1, 1), P(1, 1, 0)); // +X
		B.Quad(P(0, 1, 0), P(0, 1, 1), P(0, 0, 1), P(0, 0, 0)); // -X
		B.Quad(P(1, 1, 0), P(1, 1, 1), P(0, 1, 1), P(0, 1, 0)); // +Y
		B.Quad(P(0, 0, 0), P(0, 0, 1), P(1, 0, 1), P(1, 0, 0)); // -Y
		B.Quad(P(0, 0, 1), P(0, 1, 1), P(1, 1, 1), P(1, 0, 1)); // +Z
		B.Quad(P(0, 1, 0), P(0, 0, 0), P(1, 0, 0), P(1, 1, 0)); // -Z
	}

	void BuildCylinder(FBuilder& B)
	{
		const int32 N = 16;
		const float R = 50.f, H = 50.f;
		for (int32 I = 0; I < N; ++I)
		{
			const float A0 = 2.f * PI * I / N, A1 = 2.f * PI * (I + 1) / N;
			const FVector3f D0(FMath::Cos(A0), FMath::Sin(A0), 0.f), D1(FMath::Cos(A1), FMath::Sin(A1), 0.f);
			const FVector3f B0 = D0 * R - FVector3f(0, 0, H), B1 = D1 * R - FVector3f(0, 0, H);
			const FVector3f T0 = D0 * R + FVector3f(0, 0, H), T1 = D1 * R + FVector3f(0, 0, H);
			B.Tri(B0, T0, T1, D0, D0, D1);
			B.Tri(B0, T1, B1, D0, D1, D1);
			B.FlatTri(FVector3f(0, 0, H), T1, T0);
			B.FlatTri(FVector3f(0, 0, -H), B0, B1);
		}
	}

	void BuildSphere(FBuilder& B)
	{
		const int32 Rings = 8, Segments = 12;
		const float R = 50.f;
		auto P = [R, Rings, Segments](int32 J, int32 I)
		{
			const float T = PI * J / Rings, A = 2.f * PI * I / Segments;
			return FVector3f(FMath::Sin(T) * FMath::Cos(A), FMath::Sin(T) * FMath::Sin(A), FMath::Cos(T)) * R;
		};
		for (int32 J = 0; J < Rings; ++J)
		{
			for (int32 I = 0; I < Segments; ++I)
			{
				const FVector3f A = P(J, I), Bv = P(J + 1, I), C = P(J + 1, I + 1), D = P(J, I + 1);
				if (J > 0)
				{
					B.Tri(A, D, C, A / R, D / R, C / R);
				}
				if (J < Rings - 1)
				{
					B.Tri(A, C, Bv, A / R, C / R, Bv / R);
				}
			}
		}
	}

	void BuildPlane(FBuilder& B)
	{
		B.Quad(FVector3f(-50, -50, 0), FVector3f(-50, 50, 0), FVector3f(50, 50, 0), FVector3f(50, -50, 0));
	}

	UStaticMesh* Build(VersePlaceholderArt::EShape Shape)
	{
		FBuilder B;
		const TCHAR* Name = TEXT("WP02_Placeholder");
		switch (Shape)
		{
		case VersePlaceholderArt::EShape::Box: BuildBox(B); Name = TEXT("WP02_PlaceholderBox"); break;
		case VersePlaceholderArt::EShape::Cylinder: BuildCylinder(B); Name = TEXT("WP02_PlaceholderCylinder"); break;
		case VersePlaceholderArt::EShape::Sphere: BuildSphere(B); Name = TEXT("WP02_PlaceholderSphere"); break;
		case VersePlaceholderArt::EShape::Plane: BuildPlane(B); Name = TEXT("WP02_PlaceholderPlane"); break;
		}
		UStaticMesh* Mesh = NewObject<UStaticMesh>(GetTransientPackage(), MakeUniqueObjectName(GetTransientPackage(), UStaticMesh::StaticClass(), Name),
			RF_Transient);
		Mesh->GetStaticMaterials().Add(FStaticMaterial(VersePlaceholderArt::Material(), SlotName));
		UStaticMesh::FBuildMeshDescriptionsParams Params;
		Params.bFastBuild = true;
		Params.bBuildSimpleCollision = false;
		Params.bCommitMeshDescription = false;
		Params.bMarkPackageDirty = false;
		Mesh->BuildFromMeshDescriptions({&B.Desc}, Params);
		return Mesh;
	}
}

namespace VersePlaceholderArt
{
	UStaticMesh* Mesh(EShape Shape)
	{
		if (!FApp::CanEverRender())
		{
			return nullptr;
		}
		// Rooted for the process: shared by every world, never saved.
		static TWeakObjectPtr<UStaticMesh> Cache[4];
		TWeakObjectPtr<UStaticMesh>& Slot = Cache[int32(Shape)];
		if (!Slot.IsValid())
		{
			UStaticMesh* Built = Build(Shape);
			Built->AddToRoot();
			Slot = Built;
		}
		return Slot.Get();
	}

	UMaterialInterface* Material()
	{
		return LoadObject<UMaterialInterface>(nullptr, MaterialPath);
	}
}

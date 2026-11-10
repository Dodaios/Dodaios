#include "VerseArenaGraybox.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/ExponentialHeightFogComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/PointLight.h"
#include "Components/PointLightComponent.h"
#include "Engine/PostProcessVolume.h"
#include "Engine/RectLight.h"
#include "Engine/SpotLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Events/VerseEventHub.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Holes/VerseHoleRenderComponent.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "MeshDescription.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "NavMesh/RecastNavMesh.h"
#include "NavigationSystem.h"
#include "PhysicsEngine/BodySetup.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Repair/VerseRepairDrone.h"
#include "Rules/VerseSpawnPoint.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "StaticMeshAttributes.h"
#include "UObject/UObjectIterator.h"
#include "VerseCollision.h"
#include "VerseLog.h"

namespace VerseArenaGrayboxPrivate
{
	const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* SpherePath = TEXT("/Engine/BasicShapes/Sphere.Sphere");
	const TCHAR* MaterialPath = TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial");
	const TCHAR* EmissivePath = TEXT("/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Vfx_Sparks.MI_Weapon_Vfx_Sparks");
	/** Lights that cast shadows (the rest light only); keeps the frame inside budget. */
	constexpr int32 MaxShadowedLights = 8;
	/** Capsule half height above a spawn's floor point, cm. */
	constexpr double SpawnLiftCm = 100.0;
	/** Work lights warm, practicals and the fill cool (art-pipeline 8.2 range 4300-6500 K). */
	constexpr float WorkLightKelvin = 4300.f;
	constexpr float PracticalKelvin = 6200.f;
	constexpr float FillKelvin = 6500.f;
	constexpr float FillLux = 18.f;
	/** Soft shadowless bounce stand-ins over the arena (lumens each): faces the work lights miss stay readable. */
	constexpr float BounceLumens = 14000.f;
	/** Largest rendered box edge (cm); bigger boxes render as tiles (collision stays one box). */
	constexpr double MaxTileCm = 600.0;
	/** Repair drone docks (arena.md 7): high on the west, north and east walls, world cm. */
	const FVector DroneDocks[] = {FVector(2620.0, 2400.0, 900.0), FVector(5000.0, 4280.0, 900.0), FVector(7380.0, 2400.0, 900.0)};

	FLinearColor ColorFor(const FString& Look)
	{
		// Stand-in colours for looks whose MI is missing: charcoal hall, muted containers.
		const FString Material = Look.Contains(TEXT("Container")) ? FString(TEXT("container_wall"))
			: Look.Contains(TEXT("Glass")) ? FString(TEXT("glass"))
			: Look.Contains(TEXT("Grating")) ? FString(TEXT("catwalk_grating"))
			: Look.Contains(TEXT("Shuttle")) ? FString(TEXT("cladding_panel"))
			: Look;
		if (Material == TEXT("container_wall"))
		{
			return FLinearColor(0.16f, 0.07f, 0.035f);
		}
		if (Material == TEXT("armor_steel"))
		{
			return FLinearColor(0.14f, 0.14f, 0.15f);
		}
		if (Material == TEXT("sheet_metal"))
		{
			return FLinearColor(0.13f, 0.14f, 0.15f);
		}
		if (Material == TEXT("cladding_panel"))
		{
			return FLinearColor(0.2f, 0.19f, 0.17f);
		}
		if (Material == TEXT("glass"))
		{
			return FLinearColor(0.32f, 0.42f, 0.46f);
		}
		if (Material == TEXT("catwalk_grating"))
		{
			return FLinearColor(0.2f, 0.14f, 0.04f);
		}
		if (Material == TEXT("ceiling_panel"))
		{
			return FLinearColor(0.12f, 0.12f, 0.125f);
		}
		return FLinearColor(0.18f, 0.18f, 0.18f);
	}

	/** Instance group folder of a look (`lib/unreal_materials.py` GROUPS, first match wins). */
	const TCHAR* InstanceGroup(const FString& Look)
	{
		struct FGroup
		{
			const TCHAR* Key;
			const TCHAR* Value;
		};
		static const FGroup Groups[] = {
			{TEXT("Floor_"), TEXT("Floors")}, {TEXT("Deck_"), TEXT("Markings")}, {TEXT("Wall_"), TEXT("Walls")}, {TEXT("Ceiling_"), TEXT("Walls")},
			{TEXT("Recess_"), TEXT("Walls")}, {TEXT("Section_"), TEXT("Walls")}, {TEXT("Struct_"), TEXT("Metal")}, {TEXT("Trim_"), TEXT("Metal")},
			{TEXT("Rubber_"), TEXT("Metal")}, {TEXT("Hull_"), TEXT("Hull")}, {TEXT("Light_"), TEXT("Lights")}, {TEXT("Emit_"), TEXT("Lights")},
			{TEXT("Indicator_"), TEXT("Lights")}, {TEXT("Console_"), TEXT("Consoles")}, {TEXT("Screen"), TEXT("Screens")}, {TEXT("Glass_"), TEXT("Glass")},
		};
		for (const auto& Group : Groups)
		{
			if (Look.StartsWith(Group.Key, ESearchCase::CaseSensitive))
			{
				return Group.Value;
			}
		}
		return TEXT("Props");
	}

	FVector ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object->TryGetArrayField(Field, Values) || Values->Num() < 3)
		{
			return FVector::ZeroVector;
		}
		return FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
	}

	struct FPieceKind
	{
		EVersePieceClass Class = EVersePieceClass::WallPanel;
		EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;
	};

	bool PieceKindFor(const FString& Piece, FPieceKind& Out)
	{
		if (Piece == TEXT("container_wall"))
		{
			Out = {EVersePieceClass::ContainerWall, EVersePenetrationMaterial::ContainerWall};
		}
		else if (Piece == TEXT("wall_panel"))
		{
			Out = {EVersePieceClass::WallPanel, EVersePenetrationMaterial::SheetMetal};
		}
		else if (Piece == TEXT("cladding_wall"))
		{
			Out = {EVersePieceClass::CladdingWall, EVersePenetrationMaterial::CladdingPanel};
		}
		else if (Piece == TEXT("glass"))
		{
			Out = {EVersePieceClass::GlassPane, EVersePenetrationMaterial::Glass};
		}
		else if (Piece == TEXT("catwalk"))
		{
			Out = {EVersePieceClass::CatwalkSegment, EVersePenetrationMaterial::CatwalkGrating};
		}
		else if (Piece == TEXT("ceiling_panel"))
		{
			Out = {EVersePieceClass::CeilingPanel, EVersePenetrationMaterial::CeilingPanel};
		}
		else
		{
			return false;
		}
		return true;
	}

	/** The axis a box is thinnest along (0 X, 1 Y, 2 Z): the one a breach opens through. */
	int32 ThinAxis(const FVector& Size)
	{
		return Size.X <= Size.Y && Size.X <= Size.Z ? 0 : (Size.Y <= Size.Z ? 1 : 2);
	}

	/** The opening of a breach in the unit cube (cm, -50..50): low and wide in a wall, centred in a floor. */
	FBox BreachHole(int32 Axis)
	{
		if (Axis == 2)
		{
			return FBox(FVector(-29.0, -29.0, -60.0), FVector(29.0, 29.0, 60.0));
		}
		const FVector Across = Axis == 0 ? FVector(0.0, 1.0, 0.0) : FVector(1.0, 0.0, 0.0);
		const FVector Through = Axis == 0 ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
		const FVector Min = Across * -28.0 + Through * -60.0 + FVector(0.0, 0.0, -50.0);
		const FVector Max = Across * 28.0 + Through * 60.0 + FVector(0.0, 0.0, 22.0);
		return FBox(Min, Max);
	}

	UStaticMesh* BuildBoxMesh(const TArray<FBox>& Parts, UMaterialInterface* Material, UObject* Outer, const TCHAR* Name, bool bCollision);

	/** Container wall thickness (cm, layout.py `container_wall`): the corrugation is built for it. */
	constexpr double ContainerWallCm = 0.4;

	/**
	 * The intact look of a container wall: the unit slab with vertical ribs proud of both faces, so
	 * the walls read as corrugated steel. Render only; the piece's proxy stays the plain box. The
	 * ribs are sized in unit space for the 4 mm wall, which the piece scales to its real size.
	 */
	UStaticMesh* BuildCorrugated(int32 Axis, UMaterialInterface* Material, UObject* Outer)
	{
		TArray<FBox> Parts;
		Parts.Add(FBox(FVector(-50.0), FVector(50.0)));
		const int32 Along = Axis == 0 ? 1 : 0;           // the horizontal axis the ribs repeat along
		const double Proud = 2.2 / ContainerWallCm * 100.0;  // 2.2 cm in unit space
		const int32 Ribs = 22;
		for (int32 I = 0; I < Ribs; ++I)
		{
			const double Mid = -50.0 + 100.0 * (I + 0.5) / Ribs;
			FVector Min(-50.0), Max(50.0);
			Min[Along] = Mid - 100.0 / Ribs * 0.22;
			Max[Along] = Mid + 100.0 / Ribs * 0.22;
			Min[Axis] = -50.0 - Proud;
			Max[Axis] = 50.0 + Proud;
			Min.Z = -48.0;
			Max.Z = 48.0;
			Parts.Add(FBox(Min, Max));
		}
		return BuildBoxMesh(Parts, Material, Outer, TEXT("GrayboxCorrugated"), false);
	}

	/**
	 * A unit cube with a hole through it along Axis (the breached look and proxy of a graybox
	 * piece), as boxes around the hole: render triangles plus one simple collision box per part.
	 */
	UStaticMesh* BuildBreachFrame(int32 Axis, UMaterialInterface* Material, UObject* Outer)
	{
		const FBox Unit(FVector(-50.0), FVector(50.0));
		const FBox Hole = BreachHole(Axis);
		// The frame parts: the cube minus the hole, split along the two axes across the opening.
		TArray<FBox> Parts;
		const int32 A = Axis == 0 ? 1 : 0;      // first axis across the opening
		const int32 B = Axis == 2 ? 1 : 2;      // second axis across the opening
		auto Clip = [](double V) { return FMath::Clamp(V, -50.0, 50.0); };
		const double A0 = Clip(Hole.Min[A]), A1 = Clip(Hole.Max[A]);
		const double B0 = Clip(Hole.Min[B]), B1 = Clip(Hole.Max[B]);
		auto Make = [&](double MinA, double MaxA, double MinB, double MaxB)
		{
			if (MaxA - MinA < 0.5 || MaxB - MinB < 0.5)
			{
				return;
			}
			FVector Min = Unit.Min, Max = Unit.Max;
			Min[A] = MinA;
			Max[A] = MaxA;
			Min[B] = MinB;
			Max[B] = MaxB;
			Parts.Add(FBox(Min, Max));
		};
		Make(-50.0, A0, -50.0, 50.0);  // one side
		Make(A1, 50.0, -50.0, 50.0);   // other side
		Make(A0, A1, -50.0, B0);       // below (or one end)
		Make(A0, A1, B1, 50.0);        // above (or other end)
		return BuildBoxMesh(Parts, Material, Outer, TEXT("GrayboxBreachFrame"), true);
	}

	/** Boxes (unit-cube cm) as one static mesh, optionally with one simple collision box per part. */
	UStaticMesh* BuildBoxMesh(const TArray<FBox>& Parts, UMaterialInterface* Material, UObject* Outer, const TCHAR* Name, bool bCollision)
	{
		FMeshDescription Desc;
		FStaticMeshAttributes Attr(Desc);
		Attr.Register();
		const FPolygonGroupID Group = Desc.CreatePolygonGroup();
		Attr.GetPolygonGroupMaterialSlotNames()[Group] = TEXT("Frame");
		auto Quad = [&](const FVector3f& P0, const FVector3f& P1, const FVector3f& P2, const FVector3f& P3, const FVector3f& N)
		{
			const FVector3f Corners[2][3] = {{P0, P1, P2}, {P0, P2, P3}};
			for (const auto& Tri : Corners)
			{
				TArray<FVertexInstanceID, TFixedAllocator<3>> Ids;
				for (const FVector3f& P : Tri)
				{
					const FVertexID V = Desc.CreateVertex();
					Attr.GetVertexPositions()[V] = P;
					const FVertexInstanceID I = Desc.CreateVertexInstance(V);
					Attr.GetVertexInstanceNormals()[I] = N;
					Attr.GetVertexInstanceUVs()[I] = FVector2f(P.X / 100.f + P.Z / 100.f, P.Y / 100.f + P.Z / 100.f);
					Ids.Add(I);
				}
				Desc.CreateTriangle(Group, Ids);
			}
		};
		for (const FBox& Part : Parts)
		{
			const FVector3f L(Part.Min), H(Part.Max);
			auto P = [&](int32 X, int32 Y, int32 Z) { return FVector3f(X ? H.X : L.X, Y ? H.Y : L.Y, Z ? H.Z : L.Z); };
			Quad(P(1, 0, 0), P(1, 0, 1), P(1, 1, 1), P(1, 1, 0), FVector3f(1, 0, 0));
			Quad(P(0, 1, 0), P(0, 1, 1), P(0, 0, 1), P(0, 0, 0), FVector3f(-1, 0, 0));
			Quad(P(1, 1, 0), P(1, 1, 1), P(0, 1, 1), P(0, 1, 0), FVector3f(0, 1, 0));
			Quad(P(0, 0, 0), P(0, 0, 1), P(1, 0, 1), P(1, 0, 0), FVector3f(0, -1, 0));
			Quad(P(0, 0, 1), P(0, 1, 1), P(1, 1, 1), P(1, 0, 1), FVector3f(0, 0, 1));
			Quad(P(0, 1, 0), P(0, 0, 0), P(1, 0, 0), P(1, 1, 0), FVector3f(0, 0, -1));
		}
		UStaticMesh* Mesh = NewObject<UStaticMesh>(Outer, MakeUniqueObjectName(Outer, UStaticMesh::StaticClass(), Name), RF_Transient);
		FStaticMaterial Slot(Material, TEXT("Frame"));
		// A cooked game cannot compute UV densities (editor-only data); an uninitialised slot
		// fires three ensures on first render, each stalling a Development build for seconds.
		Slot.UVChannelData = FMeshUVChannelInfo(1.f);
		Mesh->GetStaticMaterials().Add(Slot);
		UStaticMesh::FBuildMeshDescriptionsParams Params;
		Params.bFastBuild = true;
		Params.bBuildSimpleCollision = false;
		Params.bCommitMeshDescription = false;
		Params.bMarkPackageDirty = false;
		Mesh->BuildFromMeshDescriptions({&Desc}, Params);
		if (!bCollision)
		{
			return Mesh;
		}
		Mesh->CreateBodySetup();
		if (UBodySetup* Body = Mesh->GetBodySetup())
		{
			Body->CollisionTraceFlag = CTF_UseSimpleAsComplex;
			for (const FBox& Part : Parts)
			{
				FKBoxElem Elem(Part.GetSize().X, Part.GetSize().Y, Part.GetSize().Z);
				Elem.Center = Part.GetCenter();
				Body->AggGeom.BoxElems.Add(Elem);
			}
			Body->CreatePhysicsMeshes();
		}
		return Mesh;
	}
}

AVerseArenaGraybox::AVerseArenaGraybox()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickInterval = 0.25f;
	SetRootComponent(CreateDefaultSubobject<USceneComponent>(TEXT("Root")));
	RootComponent->SetMobility(EComponentMobility::Static);
}

FString AVerseArenaGraybox::DefaultJsonPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/arena/hangar_graybox.json"));
}

AVerseArenaGraybox* AVerseArenaGraybox::Find(const UWorld& World)
{
	for (TActorIterator<AVerseArenaGraybox> It(&World); It; ++It)
	{
		return *It;
	}
	return nullptr;
}

AVerseArenaGraybox* AVerseArenaGraybox::BuildIfMissing(UWorld& World)
{
	if (AVerseArenaGraybox* Existing = Find(World))
	{
		return Existing;
	}
	for (TActorIterator<AVerseSpawnPoint> It(&World); It; ++It)
	{
		return nullptr;  // the level has its own arena
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AVerseArenaGraybox* Graybox = World.SpawnActor<AVerseArenaGraybox>(Params);
	if (Graybox && !Graybox->Build(DefaultJsonPath()))
	{
		Graybox->Destroy();
		return nullptr;
	}
	return Graybox;
}

UMaterialInterface* AVerseArenaGraybox::MaterialFor(const FString& Look)
{
	using namespace VerseArenaGrayboxPrivate;
	if (TObjectPtr<UMaterialInterface>* Found = Materials.Find(Look))
	{
		return *Found;
	}
	// The kit MI (art-pipeline 7: `MI_<Name>` in the group folder of its name prefix).
	const FString Name = TEXT("MI_") + Look;
	const FString Path = FString::Printf(TEXT("/Game/Verse/Materials/Instances/%s/%s.%s"), InstanceGroup(Look), *Name, *Name);
	UMaterialInterface* Result = LoadObject<UMaterialInterface>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!Result)
	{
		// Not built yet (import_art.py materials): a tinted basic shape keeps the arena readable.
		if (UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, MaterialPath))
		{
			UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, this);
			Mid->SetVectorParameterValue(TEXT("Color"), ColorFor(Look));
			Result = Mid;
		}
		UE_LOG(LogVerse, Warning, TEXT("[VerseArena] no material instance %s, using a flat stand-in"), *Path);
	}
	Materials.Add(Look, Result);
	return Result;
}

UInstancedStaticMeshComponent* AVerseArenaGraybox::SurfaceFor(const FString& Look, bool bSolid, bool bGlass, bool bVisible)
{
	using namespace VerseArenaGrayboxPrivate;
	const FString Key = FString::Printf(TEXT("%s_%d_%d"), *Look, bSolid ? 1 : 0, bGlass ? 1 : 0);
	if (TObjectPtr<UInstancedStaticMeshComponent>* Found = Surfaces.Find(Key))
	{
		return *Found;
	}
	UInstancedStaticMeshComponent* Surface = NewObject<UInstancedStaticMeshComponent>(this, FName(*(TEXT("Surface_") + Key)));
	Surface->SetMobility(EComponentMobility::Static);
	Surface->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, CubePath));
	if (!bVisible)
	{
		// Collision only: the dressing draws what stands here (fences, railings).
		Surface->SetVisibility(false);
		Surface->SetCastShadow(false);
	}
	else if (UMaterialInterface* Material = MaterialFor(Look.EndsWith(TEXT("_Tiles")) ? Look.LeftChop(6) : Look))
	{
		Surface->SetMaterial(0, Material);
		Surface->SetCastShadow(!bGlass);
	}
	if (bSolid)
	{
		Surface->SetCollisionProfileName(bGlass ? VerseCollision::Profile::Glass : VerseCollision::Profile::Architecture);
	}
	else
	{
		Surface->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Surface->SetCanEverAffectNavigation(false);
	}
	Surface->SetupAttachment(RootComponent);
	Surface->RegisterComponent();
	Surfaces.Add(Key, Surface);
	return Surface;
}

void AVerseArenaGraybox::AddSlab(UInstancedStaticMeshComponent* Surface, const FTransform& Transform)
{
	Surface->AddInstance(Transform, true);
	++Boxes;
}

AVerseDestructible* AVerseArenaGraybox::SpawnPiece(UWorld& World, const TSharedPtr<FJsonObject>& Box)
{
	using namespace VerseArenaGrayboxPrivate;
	FPieceKind Kind;
	if (!PieceKindFor(Box->GetStringField(TEXT("piece")), Kind))
	{
		return nullptr;
	}
	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, CubePath);
	UMaterialInterface* Look = MaterialFor(LookFor(Box));
	const FVector Center = ReadVector(Box, TEXT("center"));
	const FVector Size = ReadVector(Box, TEXT("size"));
	const int32 Axis = ThinAxis(Size);
	if (!Cube || !BreachFrames.IsValidIndex(Axis))
	{
		return nullptr;
	}
	const FTransform Transform(FQuat::Identity, Center, Size / 100.0);
	AVerseDestructible* Piece = World.SpawnActorDeferred<AVerseDestructible>(AVerseDestructible::StaticClass(), Transform, this, nullptr,
		ESpawnActorCollisionHandlingMethod::AlwaysSpawn);
	if (!Piece)
	{
		return nullptr;
	}
	Piece->PieceClass = Kind.Class;
	Piece->Material = Kind.Material;
	Piece->IntactProxy = Cube;
	// One breached look: the same box with a hole through its thin axis (proxy and render).
	FVersePieceVariant Breach;
	Breach.Proxy = BreachFrames[Axis];
	Breach.Render = BreachFrames[Axis];
	Breach.OpeningCentroid = BreachHole(Axis).GetCenter().BoundToBox(FVector(-50.0), FVector(50.0));
	Piece->BreachedVariants.Add(Breach);
	// The manager orders pieces by GUID: a stable one from the layout id keeps the order between runs.
	const uint32 Hash = GetTypeHash(Box->GetStringField(TEXT("id")));
	Piece->SetPieceGuid(FGuid(Hash, 0x56455253u, 0x48414E47u, uint32(Kind.Class)));
	if (UStaticMeshComponent* Render = Piece->GetRenderComponent())
	{
		const bool bCorrugated = Kind.Class == EVersePieceClass::ContainerWall && Axis != 2 && FMath::IsNearlyEqual(Size[Axis], ContainerWallCm, 0.01);
		Render->SetStaticMesh(bCorrugated ? BuildCorrugated(Axis, Look, this) : Cube);
		Render->SetMaterial(0, Look);
		Render->SetCastShadow(Kind.Class != EVersePieceClass::GlassPane);
	}
	Piece->FinishSpawning(Transform);
	if (UStaticMeshComponent* Render = Piece->GetRenderComponent())
	{
		// The breached frame takes the piece's colour too.
		Render->SetMaterial(0, Look);
	}
	return Piece;
}

void AVerseArenaGraybox::SpawnDestruction(UWorld& World, const TArray<TSharedPtr<FJsonObject>>& PieceBoxes)
{
	using namespace VerseArenaGrayboxPrivate;
	if (AVerseDestructionManager::Get(&World))
	{
		// The level has its own pieces and manager: the graybox only adds static slabs.
		for (const TSharedPtr<FJsonObject>& Box : PieceBoxes)
		{
			const FString Material = Box->GetStringField(TEXT("material"));
			AddSlab(SurfaceFor(LookFor(Box), true, Material == TEXT("glass")),
				FTransform(FQuat::Identity, ReadVector(Box, TEXT("center")), ReadVector(Box, TEXT("size")) / 100.0));
		}
		return;
	}
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		BreachFrames.Add(BuildBreachFrame(Axis, LoadObject<UMaterialInterface>(nullptr, MaterialPath), this));
	}
	for (const TSharedPtr<FJsonObject>& Box : PieceBoxes)
	{
		if (AVerseDestructible* Piece = SpawnPiece(World, Box))
		{
			Pieces.Add(Piece);
			Spawned.Add(Piece);
		}
	}
	// The manager registers every piece of the world in GUID order when it begins play.
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	Params.bDeferConstruction = true;
	AVerseDestructionManager* NewManager = World.SpawnActor<AVerseDestructionManager>(FVector(5000.0, 2400.0, 0.0), FRotator::ZeroRotator, Params);
	if (NewManager)
	{
		for (const FVector& Dock : DroneDocks)
		{
			NewManager->DroneDocks.Add(Dock);
		}
		NewManager->DroneClass = AVerseRepairDrone::StaticClass();
		NewManager->FinishSpawning(FTransform(FVector(5000.0, 2400.0, 0.0)));
		Manager = NewManager;
		Spawned.Add(NewManager);
	}
	// Bolts find the pieces through the penetration subsystem (proxy to piece index), leave
	// their holes in the manager's hole record and draw them with the hole renderer.
	UVersePenetrationSubsystem* Penetration = World.GetSubsystem<UVersePenetrationSubsystem>();
	if (Manager && Penetration)
	{
		Penetration->SetPieceQuery(Manager);
		UVerseBoltHoleComponent* Holes = NewObject<UVerseBoltHoleComponent>(Manager, TEXT("BoltHoles"));
		Holes->RegisterComponent();
		Penetration->SetHoleSource(Holes);
		TWeakObjectPtr<AVerseDestructionManager> WeakManager(Manager);
		Holes->OnPieceHoleCap.AddLambda([WeakManager](uint16 PieceIndex, const FVector& Centroid)
			{
				if (AVerseDestructionManager* M = WeakManager.Get())
				{
					M->ApplyHoleCap(PieceIndex, Centroid);
				}
			});
		UVerseHoleRenderComponent* HoleLook = NewObject<UVerseHoleRenderComponent>(Manager, TEXT("BoltHoleLook"));
		HoleLook->RegisterComponent();
		HoleLook->SetHoleSource(Holes);
		for (AVerseDestructible* Piece : Pieces)
		{
			if (!Piece || Piece->GetPieceIndex() == INDEX_NONE)
			{
				continue;
			}
			const uint16 Index = uint16(Piece->GetPieceIndex());
			Penetration->RegisterPieceProxy(Piece->GetProxyComponent(), Index, Piece->Material, Piece->GetRootComponent());
			HoleLook->RegisterPieceVisual(Index, Piece->GetRenderComponent(), FBox(FVector(-50.0), FVector(50.0)), Piece->GetRootComponent());
		}
	}
	DressDrones();
	UE_LOG(LogVerse, Log, TEXT("[VerseArena] destruction: %d pieces, manager %s, %d drone docks"), Pieces.Num(), Manager ? TEXT("up") : TEXT("missing"),
		UE_ARRAY_COUNT(DroneDocks));
}

void AVerseArenaGraybox::DressDrones()
{
	using namespace VerseArenaGrayboxPrivate;
	UWorld* World = GetWorld();
	if (!World || !FApp::CanEverRender())
	{
		return;
	}
	// The WP06 drone has a hit box and an empty body: give it a graybox shell and an amber eye.
	for (TActorIterator<AVerseRepairDrone> It(World); It; ++It)
	{
		AVerseRepairDrone* Drone = *It;
		if (Drone->Tags.Contains(TEXT("VerseGrayboxDressed")))
		{
			continue;
		}
		Drone->Tags.Add(TEXT("VerseGrayboxDressed"));
		UStaticMesh* Sphere = LoadObject<UStaticMesh>(nullptr, SpherePath);
		UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, CubePath);
		if (UStaticMeshComponent* Body = Drone->FindComponentByClass<UStaticMeshComponent>())
		{
			Body->SetStaticMesh(Cube);
			Body->SetRelativeScale3D(FVector(0.5, 0.5, 0.2));
			Body->SetMaterial(0, MaterialFor(TEXT("Struct_Gunmetal")));
		}
		UStaticMeshComponent* Eye = NewObject<UStaticMeshComponent>(Drone, TEXT("GrayboxEye"));
		Eye->SetStaticMesh(Sphere);
		Eye->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Eye->SetCastShadow(false);
		Eye->SetRelativeLocation(FVector(26.0, 0.0, 0.0));
		Eye->SetRelativeScale3D(FVector(0.09));
		if (UMaterialInterface* Glow = LoadObject<UMaterialInterface>(nullptr, EmissivePath, nullptr, LOAD_NoWarn | LOAD_Quiet))
		{
			Eye->SetMaterial(0, Glow);
		}
		Eye->SetupAttachment(Drone->GetRootComponent());
		Eye->RegisterComponent();
		for (const FVector& Rotor : {FVector(22.0, 22.0, 12.0), FVector(-22.0, 22.0, 12.0), FVector(22.0, -22.0, 12.0), FVector(-22.0, -22.0, 12.0)})
		{
			UStaticMeshComponent* Pod = NewObject<UStaticMeshComponent>(Drone);
			Pod->SetStaticMesh(Sphere);
			Pod->SetCollisionEnabled(ECollisionEnabled::NoCollision);
			Pod->SetRelativeLocation(Rotor);
			Pod->SetRelativeScale3D(FVector(0.18, 0.18, 0.05));
			Pod->SetMaterial(0, MaterialFor(TEXT("Arena_ShuttleDark")));
			Pod->SetupAttachment(Drone->GetRootComponent());
			Pod->RegisterComponent();
		}
	}
}

void AVerseArenaGraybox::HandleFracture(const FVerseFractureEvent& Event)
{
	using namespace VerseArenaGrayboxPrivate;
	UWorld* World = GetWorld();
	if (!World || !FApp::CanEverRender() || World->GetNetMode() == NM_DedicatedServer || !Manager)
	{
		return;
	}
	const bool bOpen = Event.ToState == EVersePieceState::Breached || Event.ToState == EVersePieceState::Destroyed;
	const bool bHole = Event.ToState == EVersePieceState::Holed;
	if (!bOpen && !bHole)
	{
		return;
	}
	const AVerseDestructible* Piece = Manager->GetPieceActor(Event.PieceIndex);
	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, CubePath);
	if (!Piece || !Cube)
	{
		return;
	}
	// Chunks from the opening (piece-local mm), flying along the blow.
	const FTransform PieceXf = Piece->GetActorTransform();
	const FVector Local(Event.Location[0] * 0.1, Event.Location[1] * 0.1, Event.Location[2] * 0.1);
	const FVector From = Local.IsNearlyZero() ? PieceXf.GetLocation() : PieceXf.TransformPosition(Local);
	FVector Push(Event.Impulse[0], Event.Impulse[1], Event.Impulse[2]);
	Push = Push.IsNearlyZero() ? FVector(FMath::FRandRange(-1.f, 1.f), FMath::FRandRange(-1.f, 1.f), 0.5f) : Push.GetSafeNormal();
	const UStaticMeshComponent* Render = Piece->GetRenderComponent();
	UMaterialInterface* Look = Render ? Render->GetMaterial(0) : nullptr;
	const FVector Extent = Piece->GetComponentsBoundingBox().GetExtent();
	const int32 Count = Event.ToState == EVersePieceState::Destroyed ? 14 : (bOpen ? 10 : 3);
	FRandomStream Rng(int32(Event.Seed));
	for (int32 I = 0; I < Count; ++I)
	{
		if (Debris.Num() >= MaxDebrisChunks)
		{
			if (UStaticMeshComponent* Old = Debris[0].Component.Get())
			{
				Old->DestroyComponent();
			}
			Debris.RemoveAt(0);
		}
		UStaticMeshComponent* Chunk = NewObject<UStaticMeshComponent>(this);
		Chunk->SetStaticMesh(Cube);
		Chunk->SetMaterial(0, Look);
		Chunk->SetMobility(EComponentMobility::Movable);
		const double S = Rng.FRandRange(bHole ? 3.0 : 6.0, bHole ? 6.0 : 18.0) / 100.0;
		const FVector Scatter = Event.ToState == EVersePieceState::Destroyed
			? FVector(Rng.FRandRange(-Extent.X, Extent.X), Rng.FRandRange(-Extent.Y, Extent.Y), Rng.FRandRange(-Extent.Z, Extent.Z)) * 0.8
			: FVector(Rng.FRandRange(-30.0, 30.0), Rng.FRandRange(-30.0, 30.0), Rng.FRandRange(-30.0, 30.0));
		Chunk->SetWorldLocationAndRotation(From + Scatter, FRotator(Rng.FRandRange(0.0, 360.0), Rng.FRandRange(0.0, 360.0), Rng.FRandRange(0.0, 360.0)));
		Chunk->SetWorldScale3D(FVector(S * Rng.FRandRange(0.6, 1.4), S * Rng.FRandRange(0.6, 1.4), S * Rng.FRandRange(0.3, 1.0)));
		Chunk->SetCollisionProfileName(VerseCollision::Profile::Debris);
		Chunk->SetCanEverAffectNavigation(false);
		Chunk->SetCastShadow(S > 0.1);
		Chunk->SetSimulatePhysics(true);
		Chunk->RegisterComponent();
		const FVector Velocity = (Push + FVector(Rng.FRandRange(-0.6, 0.6), Rng.FRandRange(-0.6, 0.6), Rng.FRandRange(0.0, 0.8))).GetSafeNormal()
			* Rng.FRandRange(bHole ? 150.0 : 250.0, bHole ? 350.0 : 700.0);
		Chunk->SetPhysicsLinearVelocity(Velocity);
		Chunk->SetPhysicsAngularVelocityInDegrees(FVector(Rng.FRandRange(-720.0, 720.0), Rng.FRandRange(-720.0, 720.0), Rng.FRandRange(-720.0, 720.0)));
		Debris.Add({Chunk, World->GetTimeSeconds() + DebrisLifeS * Rng.FRandRange(0.7f, 1.0f)});
	}
}

void AVerseArenaGraybox::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	const UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	const double Now = World->GetTimeSeconds();
	Debris.RemoveAll([Now](const FDebrisChunk& Chunk)
		{
			UStaticMeshComponent* C = Chunk.Component.Get();
			if (!C || Now >= Chunk.DieAt)
			{
				if (C)
				{
					C->DestroyComponent();
				}
				return true;
			}
			return false;
		});
	// Drones the manager respawns after a kill get their shell too.
	DressDrones();
}

void AVerseArenaGraybox::ApplyLook(UWorld& World)
{
	using namespace VerseArenaGrayboxPrivate;
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;

	// Post (arena.md 9, layout.py POST): manual exposure, bloom 0.35, vignette 0.25, and a grade with
	// cool shadows against warm highlights so the 4300 K work lights read against the 6500 K fill.
	if (APostProcessVolume* Post = World.SpawnActor<APostProcessVolume>(Params))
	{
		ArenaPost = Post;
		Post->bUnbound = true;
		Post->Priority = 10.f;
		FPostProcessSettings& S = Post->Settings;
		S.bOverride_AutoExposureMethod = true;
		S.AutoExposureMethod = AEM_Manual;
		S.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
		S.AutoExposureApplyPhysicalCameraExposure = true;
		// EV100 = log2(N^2 / t) at ISO 100: f/4 and the shutter that gives ArenaExposureEV100.
		S.bOverride_CameraISO = true;
		S.CameraISO = 100.f;
		S.bOverride_DepthOfFieldFstop = true;
		S.DepthOfFieldFstop = 4.f;
		S.bOverride_CameraShutterSpeed = true;
		S.CameraShutterSpeed = FMath::Pow(2.f, ArenaExposureEV100) / 16.f;
		S.bOverride_LensFlareIntensity = true;
		S.LensFlareIntensity = 0.f;
		// The f-number only sets the exposure: no depth of field (it would blur the viewmodel).
		S.bOverride_DepthOfFieldFocalDistance = true;
		S.DepthOfFieldFocalDistance = 0.f;
		S.bOverride_DepthOfFieldDepthBlurRadius = true;
		S.DepthOfFieldDepthBlurRadius = 0.f;
		S.bOverride_MotionBlurAmount = true;
		S.MotionBlurAmount = 0.2f;
		S.bOverride_AutoExposureBias = true;
		S.AutoExposureBias = 0.f;
		S.bOverride_BloomIntensity = true;
		S.BloomIntensity = 0.35f;
		S.bOverride_BloomThreshold = true;
		S.BloomThreshold = 1.0f;
		S.bOverride_VignetteIntensity = true;
		S.VignetteIntensity = 0.25f;
		S.bOverride_ColorContrast = true;
		S.ColorContrast = FVector4(1.08, 1.08, 1.08, 1.0);
		S.bOverride_ColorSaturation = true;
		S.ColorSaturation = FVector4(0.92, 0.92, 0.92, 1.0);
		S.bOverride_ColorGainShadows = true;
		S.ColorGainShadows = FVector4(0.94, 0.98, 1.08, 1.0);
		S.bOverride_ColorGainHighlights = true;
		S.ColorGainHighlights = FVector4(1.06, 1.0, 0.92, 1.0);
		S.bOverride_LocalExposureHighlightContrastScale = true;
		S.LocalExposureHighlightContrastScale = 0.75f;
		S.bOverride_LocalExposureShadowContrastScale = true;
		S.LocalExposureShadowContrastScale = 0.75f;
		// Lumen GI and reflections (arena.md 9): big boxes render as tiles, so the surface cache
		// stays fine; metal (grating, trusses, the black weapon) needs Lumen's reflections to read.
		// The shadowless bounce points only lift what the bounce misses.
		S.bOverride_DynamicGlobalIlluminationMethod = true;
		S.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::Lumen;
		S.bOverride_ReflectionMethod = true;
		S.ReflectionMethod = EReflectionMethod::Lumen;
		S.bOverride_IndirectLightingIntensity = true;
		S.IndirectLightingIntensity = 1.0f;
		S.bOverride_LumenSceneLightingQuality = true;
		S.LumenSceneLightingQuality = 2.f;
		S.bOverride_LumenFinalGatherQuality = true;
		S.LumenFinalGatherQuality = 2.f;
		S.bOverride_AmbientOcclusionIntensity = true;
		S.AmbientOcclusionIntensity = 0.6f;
		S.bOverride_AmbientOcclusionRadius = true;
		S.AmbientOcclusionRadius = 120.f;
		Spawned.Add(Post);
	}

	// Haze (layout.py HAZE): denser, steeper height fog that starts 4 m out, so the truss lights
	// draw cones; the deck's own fog actor carries it and gets its values back on leave.
	for (TObjectIterator<UExponentialHeightFogComponent> It; It; ++It)
	{
		UExponentialHeightFogComponent* Fog = *It;
		if (!Fog || Fog->GetWorld() != &World || !Fog->IsRegistered())
		{
			continue;
		}
		DeckFog = Fog;
		SavedFogDensity = Fog->FogDensity;
		SavedFogFalloff = Fog->FogHeightFalloff;
		SavedFogStart = Fog->StartDistance;
		bFogSaved = true;
		Fog->SetFogDensity(0.03f);
		Fog->SetFogHeightFalloff(0.12f);
		Fog->SetStartDistance(400.f);
		Fog->SetVolumetricFog(true);
		// Forward scattering: the work-light cones read as soft shafts toward the player.
		SavedFogScattering = Fog->VolumetricFogScatteringDistribution;
		Fog->SetVolumetricFogScatteringDistribution(0.55f);
		break;
	}
}

void AVerseArenaGraybox::SetExposureEV100(float EV100)
{
	if (APostProcessVolume* Post = ArenaPost.Get())
	{
		Post->Settings.CameraShutterSpeed = FMath::Pow(2.f, EV100) / 16.f;
	}
}

void AVerseArenaGraybox::RestoreLook()
{
	for (const TWeakObjectPtr<UDirectionalLightComponent>& Light : MutedLights)
	{
		if (UDirectionalLightComponent* C = Light.Get())
		{
			C->SetVisibility(true);
		}
	}
	MutedLights.Reset();
	if (UExponentialHeightFogComponent* Fog = DeckFog.Get(); Fog && bFogSaved)
	{
		Fog->SetFogDensity(SavedFogDensity);
		Fog->SetFogHeightFalloff(SavedFogFalloff);
		Fog->SetStartDistance(SavedFogStart);
		Fog->SetVolumetricFogScatteringDistribution(SavedFogScattering);
	}
	bFogSaved = false;
}

bool AVerseArenaGraybox::Build(const FString& JsonPath)
{
	using namespace VerseArenaGrayboxPrivate;
	UWorld* World = GetWorld();
	FString Text;
	TSharedPtr<FJsonObject> Root;
	if (!World || !FFileHelper::LoadFileToString(Text, *JsonPath) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root)
	{
		UE_LOG(LogVerse, Error, TEXT("[VerseArena] cannot read %s"), *JsonPath);
		return false;
	}

	// Breakable boxes become WP06 pieces where this machine has authority; a networked client keeps
	// them as slabs (the server's pieces do not replicate as actors).
	const bool bAuthority = World->GetNetMode() != NM_Client;
	TArray<TSharedPtr<FJsonObject>> PieceBoxes;
	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("boxes")))
	{
		const TSharedPtr<FJsonObject> Box = Value->AsObject();
		FPieceKind Kind;
		if (bAuthority && Box->HasField(TEXT("piece")) && PieceKindFor(Box->GetStringField(TEXT("piece")), Kind))
		{
			PieceBoxes.Add(Box);
			continue;
		}
		const FString Material = Box->GetStringField(TEXT("material"));
		const bool bSolid = Box->GetBoolField(TEXT("solid"));
		const FVector Center = ReadVector(Box, TEXT("center"));
		const FVector Size = ReadVector(Box, TEXT("size"));
		const FString Look = LookFor(Box);
		const bool bGlass = Material == TEXT("glass");
		const bool bVisible = Look != TEXT("Hidden");
		const bool bTile = bVisible && !bGlass && FApp::CanEverRender() && Size.GetMax() > MaxTileCm;
		AddSlab(SurfaceFor(Look, bSolid, bGlass, bVisible && !bTile), FTransform(FQuat::Identity, Center, Size / 100.0));
		if (bTile)
		{
			// Big boxes render as tiles of at most MaxTileCm: one huge scaled cube gets a coarse
			// Lumen surface cache, which shows as blocky light on floors and walls.
			UInstancedStaticMeshComponent* Tiles = SurfaceFor(Look + TEXT("_Tiles"), false, false);
			const FIntVector Count(FMath::CeilToInt(Size.X / MaxTileCm), FMath::CeilToInt(Size.Y / MaxTileCm), FMath::CeilToInt(Size.Z / MaxTileCm));
			const FVector Step(Size.X / Count.X, Size.Y / Count.Y, Size.Z / Count.Z);
			const FVector Origin = Center - Size * 0.5 + Step * 0.5;
			for (int32 X = 0; X < Count.X; ++X)
			{
				for (int32 Y = 0; Y < Count.Y; ++Y)
				{
					for (int32 Z = 0; Z < Count.Z; ++Z)
					{
						Tiles->AddInstance(FTransform(FQuat::Identity, Origin + Step * FVector(X, Y, Z), Step / 100.0), true);
					}
				}
			}
		}
	}
	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("ramps")))
	{
		const TSharedPtr<FJsonObject> Ramp = Value->AsObject();
		const FVector Start = ReadVector(Ramp, TEXT("start"));
		const FVector End = ReadVector(Ramp, TEXT("end"));
		const double Width = Ramp->GetNumberField(TEXT("widthCm"));
		const double Thick = Ramp->GetNumberField(TEXT("thicknessCm"));
		const FVector Along = End - Start;
		// X along the slope, Z the slab's up; the top surface runs through Start and End.
		const FMatrix Basis = FRotationMatrix::MakeFromXY(Along.GetSafeNormal(), FVector::CrossProduct(FVector::UpVector, Along).GetSafeNormal());
		const FQuat Rotation = Basis.ToQuat();
		const FVector Up = Rotation.GetUpVector();
		const FVector Center = (Start + End) * 0.5 - Up * (Thick * 0.5);
		AddSlab(SurfaceFor(TEXT("Floor_Grating"), true, false), FTransform(Rotation, Center, FVector(Along.Size(), Width, Thick) / 100.0));
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("spawns")))
	{
		const TSharedPtr<FJsonObject> Spawn = Value->AsObject();
		const FVector At = ReadVector(Spawn, TEXT("location")) + FVector(0.0, 0.0, SpawnLiftCm);
		const FRotator Facing(0.0, Spawn->GetNumberField(TEXT("yaw")), 0.0);
		if (AVerseSpawnPoint* Point = World->SpawnActor<AVerseSpawnPoint>(At, Facing, Params))
		{
			Point->SpawnId = FName(*Spawn->GetStringField(TEXT("id")));
			Spawned.Add(Point);
			++SpawnPoints;
		}
	}
	if (PieceBoxes.Num() > 0)
	{
		SpawnDestruction(*World, PieceBoxes);
	}
	if (FApp::CanEverRender())
	{
		Dress(*World, Root);
		// The duel is played, not debugged: no engine developer lines over it outside the editor
		// (`-ScreenMessages` keeps them).
		if (!GIsEditor && !FParse::Param(FCommandLine::Get(), TEXT("ScreenMessages")))
		{
			GAreScreenMessagesEnabled = false;
		}
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(World))
	{
		FractureHandle = Hub->OnFracture.AddUObject(this, &AVerseArenaGraybox::HandleFracture);
	}

	if (World->GetNetMode() != NM_DedicatedServer)
	{
		// One shadowless cool fill keeps the space between the warm work-light cones readable. One
		// only: two directional lights compete for forward shading and volumetric fog, so other
		// directional lights of the world go dark while the arena stands.
		for (TActorIterator<ADirectionalLight> It(World); It; ++It)
		{
			if (UDirectionalLightComponent* Other = Cast<UDirectionalLightComponent>(It->GetLightComponent()); Other && Other->IsVisible())
			{
				Other->SetVisibility(false);
				MutedLights.Add(Other);
			}
		}
		if (ADirectionalLight* Fill = World->SpawnActor<ADirectionalLight>(FVector(5000.0, 2400.0, 1500.0), FRotator(-26.0, 35.0, 0.0), Params))
		{
			UDirectionalLightComponent* C = CastChecked<UDirectionalLightComponent>(Fill->GetLightComponent());
			C->SetForwardShadingPriority(1);
			C->SetMobility(EComponentMobility::Movable);
			C->SetIntensity(FillLux);
			C->SetUseTemperature(true);
			C->SetTemperature(FillKelvin);
			C->SetCastShadows(false);
			C->SetAtmosphereSunLight(false);
			Spawned.Add(Fill);
		}
		int32 Shadowed = 0;
		for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("lights")))
		{
			const TSharedPtr<FJsonObject> Light = Value->AsObject();
			const FVector At = ReadVector(Light, TEXT("location"));
			const FRotator Aim(Light->GetNumberField(TEXT("pitch")), 0.0, 0.0);
			const bool bSpot = Light->GetStringField(TEXT("type")) == TEXT("spot");
			ULocalLightComponent* Component = nullptr;
			if (bSpot)
			{
				if (ASpotLight* Spot = World->SpawnActor<ASpotLight>(At, Aim, Params))
				{
					USpotLightComponent* C = Spot->SpotLightComponent;
					C->SetMobility(EComponentMobility::Movable);
					C->SetOuterConeAngle(float(Light->GetNumberField(TEXT("coneDeg")) * 0.5));
					C->SetInnerConeAngle(float(Light->GetNumberField(TEXT("coneDeg")) * 0.25));
					C->SetVolumetricScatteringIntensity(1.4f);
					Component = C;
					Spawned.Add(Spot);
				}
			}
			else if (ARectLight* Rect = World->SpawnActor<ARectLight>(At, Aim, Params))
			{
				Rect->RectLightComponent->SetMobility(EComponentMobility::Movable);
				Component = Rect->RectLightComponent;
				Spawned.Add(Rect);
			}
			if (!Component)
			{
				continue;
			}
			Component->SetIntensityUnits(ELightUnits::Lumens);
			Component->SetIntensity(float(Light->GetNumberField(TEXT("lumens"))));
			Component->SetUseTemperature(true);
			// Warm truss and aisle spots, cool practicals (booth, cabin, catwalk ceiling, armoury).
			Component->SetTemperature(bSpot ? WorkLightKelvin : PracticalKelvin);
			Component->SetAttenuationRadius(float(Light->GetNumberField(TEXT("attenuationCm"))));
			Component->SetCastShadows(bSpot && Shadowed++ < MaxShadowedLights);
			// The fixture the light comes from: a lamp housing on a hanger, or a lit panel.
			if (bSpot)
			{
				const double Size = At.Z > 1000.0 ? 90.0 : 50.0;
				AddTrim(TEXT("Struct_Gunmetal"), At + FVector(0.0, 0.0, 22.0), FVector(Size, Size, 36.0));
				AddTrim(TEXT("Arena_LampWarm"), At + FVector(0.0, 0.0, 3.0), FVector(Size - 14.0, Size - 14.0, 2.0), FRotator::ZeroRotator, false);
				if (At.Z > 1000.0)
				{
					AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, (At.Z + 2100.0) * 0.5 + 20.0), FVector(8.0, 8.0, 2100.0 - At.Z - 40.0));
				}
			}
			else
			{
				AddTrim(TEXT("Arena_LedStrip"), At + FVector(0.0, 0.0, 2.0), FVector(160.0, 30.0, 2.0), FRotator::ZeroRotator, false);
			}
		}
		// Bounce: broad, shadowless, cool points high over the arena stand in for the light the
		// floor and walls throw back, so no face the work lights miss renders black.
		for (const double X : {3000.0, 5000.0, 7000.0})
		{
			for (const double Y : {1100.0, 2400.0, 3700.0})
			{
				if (APointLight* Bounce = World->SpawnActor<APointLight>(FVector(X, Y, 1100.0), FRotator::ZeroRotator, Params))
				{
					UPointLightComponent* C = CastChecked<UPointLightComponent>(Bounce->GetLightComponent());
					C->SetMobility(EComponentMobility::Movable);
					C->SetIntensityUnits(ELightUnits::Lumens);
					C->SetIntensity(BounceLumens);
					C->SetAttenuationRadius(2600.f);
					C->SetSourceRadius(300.f);
					C->SetSoftSourceRadius(300.f);
					C->SetUseTemperature(true);
					C->SetTemperature(FillKelvin);
					C->SetCastShadows(false);
					C->SetSpecularScale(0.15f);
					C->SetVolumetricScatteringIntensity(0.f);
					Spawned.Add(Bounce);
				}
			}
		}
		ApplyLook(*World);
	}

	// Navigation: LV_Hangar's bounds volume covers the arena and the nav mesh generates at runtime
	// (Config: RuntimeGeneration=Dynamic), so the new slabs are walked as soon as their tiles rebuild.
	if (UNavigationSystemV1* Nav = FNavigationSystem::GetCurrent<UNavigationSystemV1>(World))
	{
		if (!Nav->GetDefaultNavDataInstance(FNavigationSystem::DontCreate))
		{
			if (ARecastNavMesh* NavMesh = World->SpawnActor<ARecastNavMesh>(Params))
			{
				Spawned.Add(NavMesh);
			}
		}
	}
	UE_LOG(LogVerse, Log, TEXT("[VerseArena] graybox built: %d slabs on %d surfaces, %d pieces, %d actors"), Boxes, Surfaces.Num(), Pieces.Num(),
		Spawned.Num());
	return Boxes > 0;
}

void AVerseArenaGraybox::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (UVerseEventHub* Hub = UVerseEventHub::Get(GetWorld()))
	{
		Hub->OnFracture.Remove(FractureHandle);
	}
	RestoreLook();
	for (const FDebrisChunk& Chunk : Debris)
	{
		if (UStaticMeshComponent* C = Chunk.Component.Get())
		{
			C->DestroyComponent();
		}
	}
	Debris.Reset();
	// The manager first: its EndPlay takes its drones along.
	if (IsValid(Manager))
	{
		Manager->Destroy();
	}
	for (const TObjectPtr<AActor>& Actor : Spawned)
	{
		if (IsValid(Actor))
		{
			Actor->Destroy();
		}
	}
	Spawned.Reset();
	Pieces.Reset();
	Manager = nullptr;
	Super::EndPlay(EndPlayReason);
}

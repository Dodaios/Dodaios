#include "VerseArenaGraybox.h"

#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "VerseCollision.h"
#include "VerseLog.h"

// The dressing of the runtime arena (arena.md 9.2): kit material instances on the boxes and kit
// meshes, trim and markings around them. Nothing here collides or affects navigation, so the
// arena plays exactly as its boxes say; the dressing only changes what the eye sees.

namespace VerseArenaDressingPrivate
{
	const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* Kit = TEXT("/Game/Verse/Kit/");

	/** Hall interior (world cm): hero wall face, near wall face, hull faces, ceiling underside. */
	constexpr double HeroFaceY = 150.0;
	constexpr double NearFaceY = 6160.0;
	constexpr double WestFaceX = 250.0;
	constexpr double EastFaceX = 9750.0;
	constexpr double CeilingZ = 2100.0;
	/** The hall door in the near wall (x range, world cm): no wall modules there. */
	constexpr double DoorMinX = 2960.0;
	constexpr double DoorMaxX = 7040.0;

	FString KitMesh(const TCHAR* Name)
	{
		const bool bProp = FCString::Strncmp(Name, TEXT("SM_Hangar_"), 10) == 0 || FCString::Strncmp(Name, TEXT("SM_Eng_"), 7) == 0;
		return FString::Printf(TEXT("%s%s/%s.%s"), Kit, bProp ? TEXT("Props") : TEXT("Architecture"), Name, Name);
	}

	bool StartsWith(const FString& Id, const TCHAR* Prefix)
	{
		return Id.StartsWith(Prefix, ESearchCase::CaseSensitive);
	}

	/** One of the container paints for a container id (`r2c3_...`): stable per container. */
	FString ContainerLook(const FString& Id)
	{
		static const TCHAR* Paints[] = {TEXT("Arena_ContainerRust"), TEXT("Arena_ContainerSlate"), TEXT("Arena_ContainerOlive"),
			TEXT("Arena_ContainerCharcoal"), TEXT("Arena_ContainerRust"), TEXT("Arena_ContainerOlive")};
		FString Container;
		Id.Split(TEXT("_"), &Container, nullptr);
		return Paints[GetTypeHash(Container) % UE_ARRAY_COUNT(Paints)];
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
}

FString AVerseArenaGraybox::LookFor(const TSharedPtr<FJsonObject>& Box)
{
	using namespace VerseArenaDressingPrivate;
	const FString Id = Box->GetStringField(TEXT("id"));
	const FString Zone = Box->GetStringField(TEXT("zone"));
	const FString Material = Box->GetStringField(TEXT("material"));
	const FString Piece = Box->HasField(TEXT("piece")) ? Box->GetStringField(TEXT("piece")) : FString();

	// Breakable pieces by their class.
	if (Piece == TEXT("container_wall"))
	{
		return ContainerLook(Id);
	}
	if (Piece == TEXT("ceiling_panel"))
	{
		return TEXT("Ceiling_Panel");
	}
	if (Piece == TEXT("catwalk"))
	{
		return TEXT("Floor_Grating");
	}
	if (Piece == TEXT("glass"))
	{
		return TEXT("Glass_Clear");
	}
	if (Piece == TEXT("cladding_wall"))
	{
		return TEXT("Arena_Booth");
	}
	if (Piece == TEXT("wall_panel"))
	{
		return Zone == TEXT("arena_shuttle") ? TEXT("Arena_ShuttleDark") : TEXT("Wall_PaintedDark");
	}

	// The hall shell.
	if (StartsWith(Id, TEXT("floor_")))
	{
		return TEXT("Arena_DeckPlate");
	}
	if (StartsWith(Id, TEXT("well_floor")))
	{
		return TEXT("Arena_DeckPlateWell");
	}
	if (StartsWith(Id, TEXT("fence_")) || StartsWith(Id, TEXT("well_rail")) || Id.EndsWith(TEXT("_rail")) || Id.Contains(TEXT("_rail_")))
	{
		return TEXT("Hidden");  // drawn by the dressing as posts, rails and screens
	}
	if (Zone == TEXT("shell") && Id == TEXT("ceiling"))
	{
		return TEXT("Arena_Ceiling");
	}
	if (StartsWith(Id, TEXT("hero_wall")) || StartsWith(Id, TEXT("near_wall")) || StartsWith(Id, TEXT("hull_west")) || StartsWith(Id, TEXT("hull_east"))
		|| StartsWith(Id, TEXT("well_wall")))
	{
		return TEXT("Arena_HullWall");
	}
	if (StartsWith(Id, TEXT("column_")) || StartsWith(Id, TEXT("cover_column_")))
	{
		return TEXT("Arena_Truss");
	}
	if (Id == TEXT("plinth"))
	{
		return TEXT("Arena_DeckPlate");  // the booth's lower floor
	}
	if (StartsWith(Id, TEXT("barrier_")) || StartsWith(Id, TEXT("cover_wall_")) || StartsWith(Id, TEXT("lowwall_")) || Id == TEXT("hero_pier"))
	{
		return TEXT("Arena_Barrier");
	}
	if (StartsWith(Id, TEXT("screen_")) || StartsWith(Id, TEXT("cover_screen_")))
	{
		return TEXT("Arena_BlastScreen");
	}
	if (Id == TEXT("hung_container"))
	{
		return TEXT("Arena_ContainerRust");
	}

	// The canyon: container roofs share their container's paint.
	if (Zone == TEXT("arena_canyon") && Id.EndsWith(TEXT("_roof")))
	{
		return ContainerLook(Id);
	}

	// The gunship and its pad.
	if (Zone == TEXT("arena_shuttle"))
	{
		if (StartsWith(Id, TEXT("nacelle_")) || StartsWith(Id, TEXT("turret")) || StartsWith(Id, TEXT("bulkhead_")))
		{
			return TEXT("Arena_ShuttleDark");
		}
		if (Material == TEXT("armor_steel"))
		{
			return TEXT("Arena_ShuttleHull");
		}
		if (StartsWith(Id, TEXT("crate_")) || Id == TEXT("fuel_cart"))
		{
			return StartsWith(Id, TEXT("crate_n")) ? TEXT("Arena_ContainerOlive") : TEXT("Arena_ContainerSlate");
		}
		if (Material == TEXT("concrete"))
		{
			return TEXT("Arena_Barrier");
		}
		return TEXT("Arena_ShuttleDark");
	}

	// The booth, the catwalks and the armoury.
	if (Zone == TEXT("arena_booth"))
	{
		if (StartsWith(Id, TEXT("console_")))
		{
			return TEXT("Hidden");  // drawn by the art pass as the kit console (VerseArenaArt.cpp)
		}
		if (StartsWith(Id, TEXT("cover_crate")))
		{
			return TEXT("Arena_ContainerCharcoal");
		}
		if (StartsWith(Id, TEXT("upper_floor")))
		{
			return TEXT("Arena_DeckPlate");
		}
		if (StartsWith(Id, TEXT("upper_roof")))
		{
			return TEXT("Arena_Ceiling");
		}
		return TEXT("Arena_Booth");
	}
	if (Zone == TEXT("arena_catwalks"))
	{
		if (Id == TEXT("gallery_deck"))
		{
			return TEXT("Floor_Grating");
		}
		if (Id == TEXT("gallery_roof"))
		{
			return TEXT("Arena_Ceiling");
		}
		if (Material == TEXT("concrete"))
		{
			return TEXT("Wall_PaintedDark");
		}
		return TEXT("Struct_Gunmetal");
	}
	if (Zone == TEXT("armoury"))
	{
		return Material == TEXT("concrete") ? TEXT("Wall_PaintedDark") : TEXT("Struct_Gunmetal");
	}
	if (Material == TEXT("glass"))
	{
		return TEXT("Glass_Clear");
	}
	if (Material == TEXT("sheet_metal"))
	{
		return TEXT("Struct_Gunmetal");
	}
	if (Material == TEXT("armor_steel"))
	{
		return TEXT("Arena_BlastScreen");
	}
	return TEXT("Arena_Barrier");
}

UInstancedStaticMeshComponent* AVerseArenaGraybox::DressingFor(UStaticMesh* Mesh, UMaterialInterface* Override, bool bShadow)
{
	if (!Mesh)
	{
		return nullptr;
	}
	const FString Key = FString::Printf(TEXT("%s|%s|%d"), *Mesh->GetName(), Override ? *Override->GetName() : TEXT("-"), bShadow ? 1 : 0);
	if (TObjectPtr<UInstancedStaticMeshComponent>* Found = Dressing.Find(Key))
	{
		return *Found;
	}
	UInstancedStaticMeshComponent* Component = NewObject<UInstancedStaticMeshComponent>(this);
	Component->SetMobility(EComponentMobility::Static);
	Component->SetStaticMesh(Mesh);
	if (Override)
	{
		for (int32 Slot = 0; Slot < FMath::Max(1, Mesh->GetStaticMaterials().Num()); ++Slot)
		{
			Component->SetMaterial(Slot, Override);
		}
	}
	Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Component->SetCollisionProfileName(VerseCollision::Profile::NoCollision);
	Component->SetCanEverAffectNavigation(false);
	Component->SetCastShadow(bShadow);
	Component->SetupAttachment(RootComponent);
	Component->RegisterComponent();
	Dressing.Add(Key, Component);
	return Component;
}

void AVerseArenaGraybox::AddDressing(const TCHAR* MeshName, const FTransform& Transform, const TCHAR* Override, bool bShadow)
{
	using namespace VerseArenaDressingPrivate;
	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *KitMesh(MeshName), nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!Mesh)
	{
		// Kit props outside the hangar and engineering families (consoles, lockers) live under Props too.
		Mesh = LoadObject<UStaticMesh>(nullptr, *FString::Printf(TEXT("%sProps/%s.%s"), Kit, MeshName, MeshName), nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
	if (!Mesh)
	{
		return;
	}
	if (UInstancedStaticMeshComponent* Component = DressingFor(Mesh, Override ? MaterialFor(Override) : nullptr, bShadow))
	{
		Component->AddInstance(Transform, true);
		++DressingInstances;
	}
}

void AVerseArenaGraybox::AddTrim(const FString& Look, const FVector& Center, const FVector& Size, const FRotator& Rotation, bool bShadow)
{
	using namespace VerseArenaDressingPrivate;
	UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, CubePath);
	if (UInstancedStaticMeshComponent* Component = DressingFor(Cube, MaterialFor(Look), bShadow))
	{
		Component->AddInstance(FTransform(Rotation, Center, Size / 100.0), true);
		++DressingInstances;
	}
}

void AVerseArenaGraybox::DressBox(const TSharedPtr<FJsonObject>& Box)
{
	using namespace VerseArenaDressingPrivate;
	const FString Id = Box->GetStringField(TEXT("id"));
	const FVector C = ReadVector(Box, TEXT("center"));
	const FVector S = ReadVector(Box, TEXT("size"));
	const FVector Min = C - S * 0.5;
	const FVector Max = C + S * 0.5;
	const bool bAlongX = S.X >= S.Y;
	const double Length = bAlongX ? S.X : S.Y;
	const FVector Along = bAlongX ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
	const FVector Start = bAlongX ? FVector(Min.X, C.Y, 0.0) : FVector(C.X, Min.Y, 0.0);
	DressArtBox(Box);

	// Fences: posts, rails and a faint mesh screen above the barriers (sight passes, as in play).
	if (StartsWith(Id, TEXT("fence_")))
	{
		const int32 Posts = FMath::Max(1, FMath::RoundToInt(Length / 250.0));
		for (int32 I = 0; I <= Posts; ++I)
		{
			const FVector At = Start + Along * (Length * I / Posts);
			AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, C.Z), FVector(12.0, 12.0, S.Z));
		}
		// Open rails only: a glazed screen here veiled the whole hall beyond the fence in grey.
		for (const double Z : {Min.Z + 10.0, Min.Z + S.Z * 0.25, Min.Z + S.Z * 0.5, Min.Z + S.Z * 0.75, Max.Z - 4.0})
		{
			AddTrim(TEXT("Struct_Gunmetal"), FVector(C.X, C.Y, Z), bAlongX ? FVector(Length, 8.0, 8.0) : FVector(8.0, Length, 8.0));
		}
		return;
	}
	// Railings along the hidden rail boxes.
	if (StartsWith(Id, TEXT("well_rail")) || Id.EndsWith(TEXT("_rail")) || Id.Contains(TEXT("_rail_")))
	{
		const int32 Count = FMath::Max(1, FMath::RoundToInt(Length / 240.0));
		const double Step = Length / Count;
		for (int32 I = 0; I < Count; ++I)
		{
			const FVector At = Start + Along * (Step * (I + 0.5));
			AddDressing(TEXT("SM_Railing_240"), FTransform(FRotator(0.0, bAlongX ? 0.0 : 90.0, 0.0), FVector(At.X, At.Y, Min.Z), FVector(Step / 240.0, 1.0, 1.0)));
		}
		return;
	}
	// Blast barriers and cover walls: a hazard band on top, a dark kick plate at the foot.
	if (StartsWith(Id, TEXT("barrier_")) || StartsWith(Id, TEXT("cover_wall_")) || StartsWith(Id, TEXT("lowwall_")))
	{
		const FVector Band = bAlongX ? FVector(Length + 2.0, S.Y + 2.0, 0.0) : FVector(S.X + 2.0, Length + 2.0, 0.0);
		const int32 Blocks = FMath::Max(2, FMath::RoundToInt(Length / 60.0));
		for (int32 I = 0; I < Blocks; ++I)
		{
			const FVector At = Start + Along * (Length * (I + 0.5) / Blocks);
			const FVector Size = bAlongX ? FVector(Length / Blocks, Band.Y, 14.0) : FVector(Band.X, Length / Blocks, 14.0);
			AddTrim(I % 2 ? TEXT("Arena_HazardBlack") : TEXT("Arena_HazardYellow"), FVector(At.X, At.Y, Max.Z - 7.0), Size);
		}
		AddTrim(TEXT("Arena_HazardBlack"), FVector(C.X, C.Y, 10.0), Band + FVector(0.0, 0.0, 20.0));
		return;
	}
	// Columns: steel with a hazard sleeve at the foot and a lamp halfway up.
	if (StartsWith(Id, TEXT("column_")) || StartsWith(Id, TEXT("cover_column_")))
	{
		for (int32 I = 0; I < 5; ++I)
		{
			AddTrim(I % 2 ? TEXT("Arena_HazardBlack") : TEXT("Arena_HazardYellow"), FVector(C.X, C.Y, 8.0 + 16.0 * I), FVector(S.X + 4.0, S.Y + 4.0, 16.0));
		}
		// Flanges every 3 m read as a built-up steel column.
		for (double Z = 300.0; Z < Max.Z - 100.0; Z += 300.0)
		{
			AddTrim(TEXT("Struct_Gunmetal"), FVector(C.X, C.Y, Z), FVector(S.X + 14.0, S.Y + 14.0, 12.0));
		}
		AddTrim(TEXT("Arena_LedStrip"), FVector(C.X + S.X * 0.5 + 1.0, C.Y, 700.0), FVector(2.0, 10.0, 260.0), FRotator::ZeroRotator, false);
		AddTrim(TEXT("Arena_LedStrip"), FVector(C.X - S.X * 0.5 - 1.0, C.Y, 700.0), FVector(2.0, 10.0, 260.0), FRotator::ZeroRotator, false);
		return;
	}
	// Hanging blast screens: a hazard band along the bottom edge, a frame on top.
	if (StartsWith(Id, TEXT("screen_")) || StartsWith(Id, TEXT("cover_screen_")))
	{
		const int32 Blocks = FMath::Max(2, FMath::RoundToInt(Length / 60.0));
		for (int32 I = 0; I < Blocks; ++I)
		{
			const FVector At = Start + Along * (Length * (I + 0.5) / Blocks);
			const FVector Size = bAlongX ? FVector(Length / Blocks, S.Y + 2.0, 30.0) : FVector(S.X + 2.0, Length / Blocks, 30.0);
			AddTrim(I % 2 ? TEXT("Arena_HazardBlack") : TEXT("Arena_HazardYellow"), FVector(At.X, At.Y, Min.Z + 15.0), Size);
		}
		AddTrim(TEXT("Struct_Gunmetal"), FVector(C.X, C.Y, Max.Z - 8.0), bAlongX ? FVector(Length + 10.0, S.Y + 10.0, 16.0) : FVector(S.X + 10.0, Length + 10.0, 16.0));
		// The hangers up to the roof truss.
		for (const double T : {0.15, 0.85})
		{
			const FVector At = Start + Along * (Length * T);
			AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, (Max.Z + CeilingZ) * 0.5), FVector(6.0, 6.0, CeilingZ - Max.Z));
		}
		return;
	}
	// Containers: a steel frame at the roof edge and the corner posts make the walls read as boxes.
	if (Id.EndsWith(TEXT("_roof")) && Box->GetStringField(TEXT("zone")) == TEXT("arena_canyon"))
	{
		const double Top = Max.Z;
		for (const double X : {Min.X + 6.0, Max.X - 6.0})
		{
			for (const double Y : {Min.Y + 6.0, Max.Y - 6.0})
			{
				AddTrim(TEXT("Struct_Gunmetal"), FVector(X, Y, Top * 0.5), FVector(14.0, 14.0, Top + 2.0));
			}
			AddTrim(TEXT("Struct_Gunmetal"), FVector(X, C.Y, Top - 6.0), FVector(14.0, S.Y, 14.0));
			AddTrim(TEXT("Struct_Gunmetal"), FVector(X, C.Y, 6.0), FVector(14.0, S.Y, 12.0));
		}
		for (const double Y : {Min.Y + 6.0, Max.Y - 6.0})
		{
			AddTrim(TEXT("Struct_Gunmetal"), FVector(C.X, Y, Top - 6.0), FVector(S.X, 14.0, 14.0));
		}
		return;
	}
	if (Id == TEXT("hung_container"))
	{
		for (const double X : {Min.X + 300.0, Max.X - 300.0})
		{
			AddTrim(TEXT("Struct_Gunmetal"), FVector(X, C.Y, (Max.Z + CeilingZ) * 0.5), FVector(8.0, 8.0, CeilingZ - Max.Z));
		}
		for (const double Y : {Min.Y - 1.0, Max.Y + 1.0})
		{
			for (int32 I = 0; I < 20; ++I)
			{
				AddTrim(I % 2 ? TEXT("Arena_HazardBlack") : TEXT("Arena_HazardYellow"), FVector(Min.X + S.X * (I + 0.5) / 20.0, Y, Min.Z + 20.0),
					FVector(S.X / 20.0, 2.0, 40.0));
			}
		}
		return;
	}
	// The gunship: a canopy, a red trim line, engine glows and nav lights on the walkable hull.
	if (Id == TEXT("nose"))
	{
		AddTrim(TEXT("PropsInd_GlassDark"), FVector(C.X, Min.Y + 60.0, 268.0), FVector(560.0, 140.0, 30.0), FRotator(0.0, 0.0, -18.0));
		AddTrim(TEXT("Indicator_White"), FVector(Min.X - 2.0, Min.Y + 10.0, 250.0), FVector(6.0, 6.0, 6.0), FRotator::ZeroRotator, false);
		AddTrim(TEXT("Indicator_Red"), FVector(Max.X + 2.0, Min.Y + 10.0, 250.0), FVector(6.0, 6.0, 6.0), FRotator::ZeroRotator, false);
		return;
	}
	if (StartsWith(Id, TEXT("hull_w_")) || StartsWith(Id, TEXT("hull_e_")))
	{
		const double X = StartsWith(Id, TEXT("hull_w_")) ? Min.X - 1.0 : Max.X + 1.0;
		AddTrim(TEXT("Paint_TrimRed"), FVector(X, C.Y, 200.0), FVector(2.0, S.Y, 12.0));
		AddTrim(TEXT("Arena_ShuttleDark"), FVector(X, C.Y, 40.0), FVector(2.0, S.Y, 80.0));
		for (int32 I = 1; I < 4; ++I)
		{
			AddTrim(TEXT("Arena_ShuttleDark"), FVector(X, Min.Y + S.Y * I / 4.0, 150.0), FVector(2.4, 3.0, S.Z - 20.0));
		}
		return;
	}
	if (StartsWith(Id, TEXT("nacelle_")))
	{
		AddTrim(TEXT("Indicator_Amber"), FVector(C.X, Max.Y + 1.0, C.Z), FVector(S.X * 0.4, 2.0, S.Z * 0.3), FRotator::ZeroRotator, false);
		return;
	}
	if (Id == TEXT("roof"))
	{
		AddTrim(TEXT("Paint_TrimRed"), FVector(C.X, C.Y, Max.Z + 0.5), FVector(30.0, S.Y - 100.0, 1.0));
		return;
	}
	// The booth: a lit band under the roof and window frames.
	if (Id == TEXT("upper_roof"))
	{
		AddTrim(TEXT("Arena_LedStrip"), FVector(C.X, Max.Y + 1.0, Min.Z - 8.0), FVector(S.X - 40.0, 2.0, 6.0), FRotator::ZeroRotator, false);
		AddTrim(TEXT("Arena_LedStrip"), FVector(Max.X + 1.0, C.Y, Min.Z - 8.0), FVector(2.0, S.Y - 40.0, 6.0), FRotator::ZeroRotator, false);
		return;
	}
}

void AVerseArenaGraybox::DressHall()
{
	using namespace VerseArenaDressingPrivate;
	// Hull walls: 4.8 m wall modules to 12 m, lit modules above, machinery bays between.
	struct FRun
	{
		double Fixed;
		double From;
		double To;
		bool bAlongX;
		double Yaw;
		double Inward;  // +1 or -1 along the fixed axis toward the hall
	};
	const FRun Runs[] = {
		{HeroFaceY, 300.0, 9700.0, true, 0.0, 1.0},
		{NearFaceY, 300.0, 9700.0, true, 180.0, -1.0},
		{WestFaceX, 400.0, 6000.0, false, -90.0, 1.0},
		{EastFaceX, 400.0, 6000.0, false, 90.0, -1.0},
	};
	for (const FRun& Run : Runs)
	{
		int32 Index = 0;
		for (double T = Run.From + 240.0; T + 240.0 <= Run.To; T += 480.0, ++Index)
		{
			const bool bNearWall = Run.bAlongX && Run.Inward < 0.0;
			if (bNearWall && T > DoorMinX - 240.0 && T < DoorMaxX + 240.0)
			{
				continue;
			}
			const FVector Face = Run.bAlongX ? FVector(T, Run.Fixed, 0.0) : FVector(Run.Fixed, T, 0.0);
			const FVector In = Run.bAlongX ? FVector(0.0, Run.Inward, 0.0) : FVector(Run.Inward, 0.0, 0.0);
			const FRotator Facing(0.0, Run.Yaw, 0.0);
			const FVector Module = Face + In * 30.0;
			if (!Run.bAlongX && Index % 4 == 2)
			{
				AddDressing(Index % 8 == 2 ? TEXT("SM_Eng_WallMachinery_A_12") : TEXT("SM_Eng_WallMachinery_B_12"), FTransform(Facing, Face));
			}
			else
			{
				AddDressing(TEXT("SM_Wall_480_H1200"), FTransform(Facing, Module));
			}
			AddDressing(Index % 6 == 3 ? TEXT("SM_WallLight_480_H540") : TEXT("SM_Wall_480_H540"), FTransform(Facing, Module + FVector(0.0, 0.0, 1200.0)));
			// Services on the walls: cable trays along every module, a power riser at every third.
			AddDressing(TEXT("SM_Eng_CableTray_Wall"), FTransform(Facing, Face + In * 2.0 + FVector(0.0, 0.0, 380.0), FVector(2.0, 1.0, 1.0)));
			if (Index % 3 == 0)
			{
				AddDressing(TEXT("SM_Eng_PowerConduit"), FTransform(Facing, Face + In * 64.0 + (Run.bAlongX ? FVector(-170.0, 0.0, 0.0) : FVector(0.0, -170.0, 0.0))));
			}
			// A dark steel pilaster between modules (the white strips here read as a light show).
			const FVector Seam = Face + In * 8.0 + (Run.bAlongX ? FVector(240.0, 0.0, 0.0) : FVector(0.0, 240.0, 0.0));
			AddTrim(TEXT("Struct_Gunmetal"), Seam + FVector(0.0, 0.0, 860.0), Run.bAlongX ? FVector(22.0, 16.0, 1720.0) : FVector(16.0, 22.0, 1720.0));
		}
	}

	// A continuous light line where the module rows meet, on every hull wall.
	AddTrim(TEXT("Arena_LedStrip"), FVector(5000.0, HeroFaceY + 6.0, 1200.0), FVector(9400.0, 4.0, 8.0), FRotator::ZeroRotator, false);
	AddTrim(TEXT("Arena_LedStrip"), FVector(WestFaceX + 6.0, 3200.0, 1200.0), FVector(4.0, 5600.0, 8.0), FRotator::ZeroRotator, false);
	AddTrim(TEXT("Arena_LedStrip"), FVector(EastFaceX - 6.0, 3200.0, 1200.0), FVector(4.0, 5600.0, 8.0), FRotator::ZeroRotator, false);
	for (const double X : {(300.0 + DoorMinX) * 0.5, (DoorMaxX + 9700.0) * 0.5})
	{
		AddTrim(TEXT("Arena_LedStrip"), FVector(X, NearFaceY - 6.0, 1200.0), FVector(DoorMinX - 300.0, 4.0, 8.0), FRotator::ZeroRotator, false);
	}

	// The 41 m hall door in the near wall.
	AddDressing(TEXT("SM_Hangar_BlastDoor"), FTransform(FRotator(0.0, 180.0, 0.0), FVector(5000.0, NearFaceY - 70.0, 0.0)));

	// Roof trusses: deep girders across the hall and purlins along it.
	for (double X = 600.0; X < 9500.0; X += 800.0)
	{
		AddTrim(TEXT("Arena_Truss"), FVector(X, 3155.0, CeilingZ - 70.0), FVector(40.0, 6010.0, 140.0));
		AddTrim(TEXT("Arena_Truss"), FVector(X, 3155.0, CeilingZ - 180.0), FVector(30.0, 6010.0, 18.0));
		for (double Y = 400.0; Y < 6000.0; Y += 400.0)
		{
			AddTrim(TEXT("Arena_Truss"), FVector(X, Y, CeilingZ - 125.0), FVector(10.0, 10.0, 110.0), FRotator(0.0, 0.0, (int32(Y / 400.0) % 2) ? 35.0 : -35.0));
		}
	}
	for (double Y = 600.0; Y < 6100.0; Y += 1200.0)
	{
		AddTrim(TEXT("Arena_Truss"), FVector(5000.0, Y, CeilingZ - 30.0), FVector(9500.0, 24.0, 60.0));
	}

	// The west and east bays outside the arena: stacked containers, racks and ground vehicles.
	struct FProp
	{
		const TCHAR* Mesh;
		FVector At;
		double Yaw;
	};
	const FProp Props[] = {
		{TEXT("SM_Hangar_Container_L_Charcoal"), FVector(1200.0, 2600.0, 0.0), 90.0},
		{TEXT("SM_Hangar_Container_L_Olive"), FVector(1500.0, 2600.0, 0.0), 90.0},
		{TEXT("SM_Hangar_Container_L_Grey"), FVector(1350.0, 2600.0, 260.0), 90.0},
		{TEXT("SM_Hangar_Container_M_Gunmetal"), FVector(900.0, 3500.0, 0.0), 0.0},
		{TEXT("SM_Hangar_FuelBowser"), FVector(1300.0, 4700.0, 0.0), 90.0},
		{TEXT("SM_Hangar_TowTug"), FVector(1800.0, 5600.0, 0.0), 30.0},
		{TEXT("SM_Hangar_StorageRack"), FVector(520.0, 1200.0, 0.0), -90.0},
		{TEXT("SM_Hangar_StorageRack"), FVector(520.0, 1800.0, 0.0), -90.0},
		{TEXT("SM_Hangar_CrateStack"), FVector(1700.0, 900.0, 0.0), 0.0},
		{TEXT("SM_Hangar_Pallet_Loaded"), FVector(2000.0, 1300.0, 0.0), 15.0},
		{TEXT("SM_Hangar_Pallet_Loaded"), FVector(2000.0, 1500.0, 0.0), -5.0},
		{TEXT("SM_Hangar_ToolCart"), FVector(2100.0, 3800.0, 0.0), 40.0},
		{TEXT("SM_Hangar_Container_L_Grey"), FVector(8400.0, 900.0, 0.0), 90.0},
		{TEXT("SM_Hangar_Container_L_Charcoal"), FVector(8700.0, 900.0, 0.0), 90.0},
		{TEXT("SM_Hangar_Container_L_Olive"), FVector(8550.0, 900.0, 260.0), 90.0},
		{TEXT("SM_Hangar_Container_M_Charcoal"), FVector(9200.0, 2200.0, 0.0), 90.0},
		{TEXT("SM_Hangar_Container_S_Grey"), FVector(8300.0, 2600.0, 0.0), 10.0},
		{TEXT("SM_Hangar_FuelCart"), FVector(8100.0, 3500.0, 0.0), -60.0},
		{TEXT("SM_Hangar_TowTug"), FVector(8600.0, 4000.0, 0.0), 200.0},
		{TEXT("SM_Hangar_StorageRack"), FVector(9480.0, 3200.0, 0.0), 90.0},
		{TEXT("SM_Hangar_StorageRack"), FVector(9480.0, 3800.0, 0.0), 90.0},
		{TEXT("SM_Eng_ToolRack"), FVector(9700.0, 4300.0, 0.0), 90.0},
		{TEXT("SM_Hangar_CrateStack"), FVector(8000.0, 1600.0, 0.0), 90.0},
		{TEXT("SM_Hangar_FuelHydrant"), FVector(4000.0, 5200.0, 0.0), 0.0},
		{TEXT("SM_Hangar_FuelHydrant"), FVector(6000.0, 5200.0, 0.0), 0.0},
		{TEXT("SM_Hangar_Pallet"), FVector(3000.0, 5300.0, 0.0), 0.0},
		{TEXT("SM_Hangar_Container_S_Charcoal"), FVector(2600.0, 5500.0, 0.0), 0.0},
		{TEXT("SM_Hangar_Container_M_Gunmetal"), FVector(7200.0, 5500.0, 0.0), 0.0},
		{TEXT("SM_Hangar_ArmourRack"), FVector(8300.0, 6100.0, 0.0), 180.0},
		{TEXT("SM_Hangar_ArmourRack"), FVector(8650.0, 6100.0, 0.0), 180.0},
		{TEXT("SM_Hangar_ArmourRack"), FVector(9000.0, 6100.0, 0.0), 180.0},
		{TEXT("SM_Eng_DroneDock"), FVector(2620.0, 2400.0, 650.0), -90.0},
	};
	for (const FProp& Prop : Props)
	{
		// On the deck the hall leaves the rooms with stations to the deck's own furniture: a
		// container must not stand where the commander steps out of the lift.
		if (!InKeptClearRoom(Prop.At))
		{
			AddDressing(Prop.Mesh, FTransform(FRotator(0.0, Prop.Yaw, 0.0), Prop.At));
		}
	}
	// Gantry columns along the hull walls carry the roof trusses.
	for (double Y = 800.0; Y < 6000.0; Y += 1600.0)
	{
		AddDressing(TEXT("SM_Hangar_GantryColumn"), FTransform(FRotator(0.0, 0.0, 0.0), FVector(WestFaceX + 90.0, Y, 0.0)));
		AddDressing(TEXT("SM_Hangar_GantryColumn"), FTransform(FRotator(0.0, 180.0, 0.0), FVector(EastFaceX - 90.0, Y, 0.0)));
	}

	// Floor: the pad under the gunship, lane lines, chevrons at the well and the spawns, floor lights.
	const double Mark = 0.6;
	AddDressing(TEXT("SM_Hangar_Marking_Pad"), FTransform(FRotator::ZeroRotator, FVector(5000.0, 2400.0, Mark), FVector(0.62, 0.62, 1.0)), TEXT("Arena_Marking"), false);
	for (const double Y : {470.0, 4330.0})
	{
		for (double X = 2700.0; X < 7400.0; X += 1200.0)
		{
			AddDressing(TEXT("SM_Hangar_Marking_LaneSolid"), FTransform(FRotator::ZeroRotator, FVector(X + 600.0, Y, Mark), FVector(1.0, 1.4, 1.0)),
				TEXT("Arena_HazardYellow"), false);
		}
	}
	for (double Y = 1100.0; Y < 4200.0; Y += 1200.0)
	{
		AddDressing(TEXT("SM_Hangar_Marking_LaneDashed"), FTransform(FRotator(0.0, 90.0, 0.0), FVector(5850.0, Y + 600.0, Mark)), TEXT("Arena_Marking"), false);
		AddDressing(TEXT("SM_Hangar_Marking_LaneDashed"), FTransform(FRotator(0.0, 90.0, 0.0), FVector(4150.0, Y + 600.0, Mark)), TEXT("Arena_Marking"), false);
	}
	// Hazard edge around the launch well (x 2700..3700, y 900..1900).
	const int32 Blocks = 25;
	for (int32 I = 0; I < Blocks; ++I)
	{
		const double T = 2700.0 + 1000.0 * (I + 0.5) / Blocks;
		const TCHAR* Look = I % 2 ? TEXT("Arena_HazardBlack") : TEXT("Arena_HazardYellow");
		AddTrim(Look, FVector(T, 860.0, 0.4), FVector(40.0, 60.0, 1.0), FRotator::ZeroRotator, false);
		AddTrim(Look, FVector(T, 1940.0, 0.4), FVector(40.0, 60.0, 1.0), FRotator::ZeroRotator, false);
		const double U = 900.0 + 1000.0 * (I + 0.5) / Blocks;
		AddTrim(Look, FVector(2660.0, U, 0.4), FVector(60.0, 40.0, 1.0), FRotator::ZeroRotator, false);
		AddTrim(Look, FVector(3740.0, U, 0.4), FVector(60.0, 40.0, 1.0), FRotator::ZeroRotator, false);
	}
	// A red maintenance band down the well and amber lamps at its rim.
	AddTrim(TEXT("Light_Maint_Red"), FVector(3200.0, 952.0, -400.0), FVector(980.0, 2.0, 8.0), FRotator::ZeroRotator, false);
	AddTrim(TEXT("Light_Maint_Red"), FVector(3200.0, 1848.0, -400.0), FVector(980.0, 2.0, 8.0), FRotator::ZeroRotator, false);
	AddTrim(TEXT("Light_Maint_Red"), FVector(2752.0, 1400.0, -400.0), FVector(2.0, 980.0, 8.0), FRotator::ZeroRotator, false);
	AddTrim(TEXT("Light_Maint_Red"), FVector(3648.0, 1400.0, -400.0), FVector(2.0, 980.0, 8.0), FRotator::ZeroRotator, false);
	for (const FVector& Spawn : {FVector(2600.0, 500.0, 0.0), FVector(7080.0, 600.0, 0.0), FVector(7100.0, 4000.0, 0.0), FVector(4850.0, 4300.0, 0.0),
			 FVector(4800.0, 800.0, 0.0)})
	{
		AddDressing(TEXT("SM_Hangar_Marking_Chevrons"), FTransform(FRotator::ZeroRotator, Spawn + FVector(0.0, 0.0, Mark)), TEXT("Arena_HazardYellow"), false);
	}
	for (double X = 2800.0; X < 7400.0; X += 480.0)
	{
		AddDressing(TEXT("SM_Hangar_FloorLight"), FTransform(FRotator::ZeroRotator, FVector(X, 4250.0, 0.5)), nullptr, false);
	}
	for (double Y = 2100.0; Y < 4200.0; Y += 480.0)
	{
		AddDressing(TEXT("SM_Hangar_FloorLight"), FTransform(FRotator::ZeroRotator, FVector(2560.0, Y, 0.5)), nullptr, false);
	}
	// Bay numbers on the hero wall, backlit.
	AddDressing(TEXT("SM_Hangar_Marking_BayNumber"), FTransform(FRotator(0.0, 0.0, 90.0), FVector(3000.0, HeroFaceY + 40.0, 1450.0), FVector(4.0)),
		TEXT("Arena_Marking"), false);
	AddDressing(TEXT("SM_Hangar_Marking_BayNumber"), FTransform(FRotator(0.0, 0.0, 90.0), FVector(7000.0, HeroFaceY + 40.0, 1450.0), FVector(4.0)),
		TEXT("Arena_Marking"), false);
}

void AVerseArenaGraybox::DressDecals()
{
	using namespace VerseArenaDressingPrivate;
	// Seeded, so every duel shows the same floor: oil under the gunship and the vehicles' lanes,
	// boot and tyre scuffs everywhere else. The launch well (x 2700..3700, y 900..1900) stays clean.
	FRandomStream Rng(0x48414E47);
	auto Place = [&](const TCHAR* Look, const FVector& At, double Size)
	{
		UDecalComponent* Decal = NewObject<UDecalComponent>(this);
		Decal->SetDecalMaterial(MaterialFor(Look));
		Decal->DecalSize = FVector(30.0, Size, Size * Rng.FRandRange(0.6f, 1.0f));
		Decal->SetFadeScreenSize(0.002f);
		Decal->SetupAttachment(RootComponent);
		Decal->SetWorldLocationAndRotation(At, FRotator(-90.0, Rng.FRandRange(0.f, 360.f), 0.0));
		Decal->RegisterComponent();
		++DressingInstances;
	};
	for (int32 I = 0; I < 90; ++I)
	{
		const FVector At(Rng.FRandRange(2550.f, 7450.f), Rng.FRandRange(450.f, 4350.f), 0.0);
		if (At.X > 2650.0 && At.X < 3750.0 && At.Y > 850.0 && At.Y < 1950.0)
		{
			continue;
		}
		const bool bOil = I % 3 == 0;
		Place(bOil ? TEXT("Arena_OilStain") : TEXT("Arena_Scuff"), At, bOil ? Rng.FRandRange(60.f, 220.f) : Rng.FRandRange(120.f, 380.f));
	}
	// Stencilled markings (signage.py masks): text along the lanes, row numbers at the canyon,
	// the deck number on the hero wall. Sizes are the decal's width and height in cm. A floor
	// sign's yaw is the yaw its main reader faces plus 90, so the text reads upright to them.
	auto Sign = [&](const TCHAR* Look, const FVector& At, double Yaw, double Width, double Height, bool bWall = false)
	{
		UDecalComponent* Decal = NewObject<UDecalComponent>(this);
		Decal->SetDecalMaterial(MaterialFor(Look));
		Decal->DecalSize = FVector(bWall ? 40.0 : 20.0, Width * 0.5, Height * 0.5);
		Decal->SetFadeScreenSize(0.001f);
		Decal->SortOrder = 2;
		Decal->SetupAttachment(RootComponent);
		Decal->SetWorldLocationAndRotation(At, bWall ? FRotator(0.0, Yaw, 0.0) : FRotator(-90.0, Yaw, 90.0));
		Decal->RegisterComponent();
		++DressingInstances;
	};
	Sign(TEXT("Arena_Sign_KeepClear"), FVector(3200.0, 760.0, 0.0), 180.0, 520.0, 130.0);
	Sign(TEXT("Arena_Sign_KeepClear"), FVector(3200.0, 2040.0, 0.0), 0.0, 520.0, 130.0);
	Sign(TEXT("Arena_Sign_Lift"), FVector(2560.0, 1400.0, 0.0), 90.0, 420.0, 105.0);
	Sign(TEXT("Arena_Sign_Bay"), FVector(4850.0, 4120.0, 0.0), 0.0, 360.0, 90.0);
	Sign(TEXT("Arena_Sign_NoStep"), FVector(5000.0, 2000.0, 300.0), 180.0, 300.0, 75.0);
	for (double Y = 1300.0; Y < 4200.0; Y += 1200.0)
	{
		Sign(TEXT("Arena_Sign_Arrow"), FVector(5850.0, Y, 0.0), 90.0, 320.0, 80.0);
		Sign(TEXT("Arena_Sign_Arrow"), FVector(4150.0, Y + 600.0, 0.0), -90.0, 320.0, 80.0);
	}
	Sign(TEXT("Arena_Sign_Row1"), FVector(6180.0, 4150.0, 0.0), 0.0, 160.0, 160.0);
	Sign(TEXT("Arena_Sign_Row2"), FVector(6780.0, 4150.0, 0.0), 0.0, 160.0, 160.0);
	Sign(TEXT("Arena_Sign_Row3"), FVector(7380.0, 4150.0, 0.0), 0.0, 160.0, 160.0);
	Sign(TEXT("Arena_Sign_Deck"), FVector(3700.0, HeroFaceY + 10.0, 700.0), -90.0, 500.0, 500.0, true);
	Sign(TEXT("Arena_Sign_Deck"), FVector(6300.0, HeroFaceY + 10.0, 700.0), -90.0, 500.0, 500.0, true);

	for (int32 I = 0; I < 10; ++I)
	{
		Place(TEXT("Arena_OilStain"), FVector(5000.0 + Rng.FRandRange(-300.f, 300.f), 2400.0 + Rng.FRandRange(-800.f, 800.f), 0.0), Rng.FRandRange(80.f, 260.f));
	}
}

void AVerseArenaGraybox::Dress(UWorld& World, const TSharedPtr<FJsonObject>& Root)
{
	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("boxes")))
	{
		if (Includes(Value->AsObject()))
		{
			DressBox(Value->AsObject());
		}
	}
	DressHall();
	DressDecals();
	DressArt();
	UE_LOG(LogVerse, Log, TEXT("[VerseArena] dressing: %d instances on %d components"), DressingInstances, Dressing.Num());
}

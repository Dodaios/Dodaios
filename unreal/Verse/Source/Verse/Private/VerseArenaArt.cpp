#include "VerseArenaGraybox.h"

#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/RectLightComponent.h"
#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Engine/RectLight.h"
#include "Engine/SpotLight.h"
#include "Engine/PointLight.h"
#include "Components/PointLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "Materials/MaterialInterface.h"
#include "VerseLog.h"

// The art pass of the runtime hangar (arena.md 9.3). The boxes stay the gameplay truth; this file
// only adds what the eye sees, in the hall around the arena: scanned Poly Haven props
// (`SM_Hangar_<Name>`, art/verse/decks/hangar/unreal_arena/props.py), roof cranes, high-bay lamps,
// skylight shafts through the haze, duct and pipe runs on the hull walls, equipment in the work
// bays and wear decals. Nothing here collides or touches the nav mesh.

namespace VerseArenaArtPrivate
{
	/** Hall interior (world cm), as in VerseArenaDressing.cpp. */
	constexpr double HeroFaceY = 150.0;
	constexpr double NearFaceY = 6160.0;
	constexpr double WestFaceX = 250.0;
	constexpr double EastFaceX = 9750.0;
	constexpr double CeilingZ = 2100.0;
	constexpr double DoorMinX = 2960.0;
	constexpr double DoorMaxX = 7040.0;
	/** Roof girders run across the hall at x = 600 + 800 k (VerseArenaDressing.cpp DressHall). */
	constexpr double GirderX0 = 600.0;
	constexpr double GirderStep = 800.0;
	/** The arena's footprint and the launch well (arena.md 1), world cm. */
	const FBox2D Arena(FVector2D(2500.0, 400.0), FVector2D(7500.0, 4400.0));
	const FBox2D Armoury(FVector2D(7700.0, 4720.0), FVector2D(9750.0, 6160.0));
	/** Skylights: centres between girders over the arena, size along x and y (cm). */
	const FVector2D SkylightSize(560.0, 1400.0);
	const FVector2D Skylights[] = {FVector2D(3400.0, 1500.0), FVector2D(5000.0, 1500.0), FVector2D(6600.0, 1500.0), FVector2D(3400.0, 3400.0),
		FVector2D(5000.0, 3400.0), FVector2D(6600.0, 3400.0)};
	/** Skylights over the bays and the apron: their lights cast no shadows (the frame budget). */
	const FVector2D BaySkylights[] = {FVector2D(1000.0, 1800.0), FVector2D(1800.0, 4200.0), FVector2D(9000.0, 1800.0), FVector2D(8200.0, 3800.0),
		FVector2D(4200.0, 5400.0), FVector2D(5800.0, 5400.0)};
	/** Lumens of one skylight's rect light and its haze scattering (the shafts). */
	constexpr float SkylightLumens = 60000.f;
	constexpr float SkylightScattering = 2.0f;
	/** Lumens of one hall lamp's light on the deck view (hall part only). */
	constexpr float HallLampLumens = 60000.f;

	/** One wall of the hall: the face, the run along it and the way into the hall. */
	struct FWall
	{
		const TCHAR* Name;
		bool bAlongX;
		double Face;
		double From;
		double To;
		double Inward;  // +1 or -1 along the fixed axis
		double Yaw;     // a wall prop's yaw: its +Y side looks into the hall

		FVector At(double T, double Out, double Z) const
		{
			return bAlongX ? FVector(T, Face + Inward * Out, Z) : FVector(Face + Inward * Out, T, Z);
		}
		FVector Along() const { return bAlongX ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0); }
	};
	const FWall Walls[] = {
		{TEXT("hero"), true, HeroFaceY, 400.0, 9600.0, 1.0, 0.0},
		{TEXT("near"), true, NearFaceY, 400.0, 9600.0, -1.0, 180.0},
		{TEXT("west"), false, WestFaceX, 500.0, 5900.0, 1.0, -90.0},
		{TEXT("east"), false, EastFaceX, 500.0, 5900.0, -1.0, 90.0},
	};

	bool InDoor(const FWall& Wall, double T)
	{
		return Wall.bAlongX && Wall.Inward < 0.0 && T > DoorMinX - 150.0 && T < DoorMaxX + 150.0;
	}
}

UStaticMesh* AVerseArenaGraybox::ExternalSwap(const TCHAR* KitName, FTransform& InOutTransform)
{
	if (!bExternalSwapsRead)
	{
		bExternalSwapsRead = true;
		FString Text;
		TSharedPtr<FJsonObject> Root;
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/arena/external_swaps.json"));
		if (FFileHelper::LoadFileToString(Text, *Path) && FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root)
		{
			const TSharedPtr<FJsonObject>* Swaps = nullptr;
			if (Root->TryGetObjectField(TEXT("swaps"), Swaps))
			{
				for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Swaps)->Values)
				{
					ExternalSwaps.Add(Pair.Key, Pair.Value->AsObject());
				}
			}
		}
	}
	const TSharedPtr<FJsonObject>* Entry = ExternalSwaps.Find(KitName);
	if (!Entry || !Entry->IsValid())
	{
		return nullptr;
	}
	UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *(*Entry)->GetStringField(TEXT("mesh")), nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (!Mesh)
	{
		return nullptr;  // External/ is not on this machine: the CC0 kit mesh stays
	}
	double Scale = 1.0;
	double Yaw = 0.0;
	double Lift = 0.0;
	(*Entry)->TryGetNumberField(TEXT("scale"), Scale);
	(*Entry)->TryGetNumberField(TEXT("yaw"), Yaw);
	(*Entry)->TryGetNumberField(TEXT("lift_cm"), Lift);
	++ExternalSwapsUsed;
	InOutTransform = FTransform(FRotator(0.0, Yaw, 0.0)) * FTransform(FQuat::Identity, FVector(0.0, 0.0, Lift), FVector(Scale)) * InOutTransform;
	return Mesh;
}

void AVerseArenaGraybox::AddProp(const TCHAR* Name, const FVector& At, double Yaw, const FVector& Scale, bool bShadow)
{
	AddDressing(Name, FTransform(FRotator(0.0, Yaw, 0.0), At, Scale), nullptr, bShadow);
}

void AVerseArenaGraybox::AddWear(const TCHAR* Look, const FVector& At, double Yaw, double Width, double Height, bool bWall)
{
	UDecalComponent* Decal = NewObject<UDecalComponent>(this);
	Decal->SetDecalMaterial(MaterialFor(Look));
	Decal->DecalSize = FVector(bWall ? 30.0 : 25.0, Width * 0.5, Height * 0.5);
	Decal->SetFadeScreenSize(0.0015f);
	Decal->SortOrder = 1;
	Decal->SetupAttachment(RootComponent);
	Decal->SetWorldLocationAndRotation(At, bWall ? FRotator(0.0, Yaw, 0.0) : FRotator(-90.0, Yaw, 0.0));
	Decal->RegisterComponent();
	++DressingInstances;
}

void AVerseArenaGraybox::DressArtRoof()
{
	using namespace VerseArenaArtPrivate;

	// Two overhead cranes over the arena: a bridge girder spanning the arena's depth on runway beams,
	// a trolley with its hook block hanging into the haze above the fight.
	for (const double X : {3600.0, 6600.0})
	{
		const double Bottom = 1430.0;
		AddProp(TEXT("SM_Hangar_Crane_Bridge"), FVector(X, 2400.0, Bottom), 90.0, FVector(3.4, 1.5, 1.45));
		AddProp(TEXT("SM_Hangar_Crane_Winch"), FVector(X, X < 5000.0 ? 1900.0 : 3000.0, Bottom - 180.0), 90.0, FVector(1.45));
	}
	// Amber beacons on both ends of each bridge and on the arena's perimeter corners.
	UWorld* BeaconWorld = GetWorld();
	const FVector Beacons[] = {FVector(3600.0, 700.0, 1900.0), FVector(3600.0, 4100.0, 1900.0), FVector(6600.0, 700.0, 1900.0), FVector(6600.0, 4100.0, 1900.0),
		FVector(2470.0, 370.0, 470.0), FVector(7530.0, 370.0, 470.0), FVector(2470.0, 4430.0, 470.0), FVector(7530.0, 4430.0, 470.0)};
	for (const FVector& At : Beacons)
	{
		AddTrim(TEXT("Struct_Gunmetal"), At - FVector(0.0, 0.0, 12.0), FVector(26.0, 26.0, 10.0));
		AddTrim(TEXT("Indicator_Amber"), At + FVector(0.0, 0.0, 6.0), FVector(18.0, 18.0, 22.0), FRotator::ZeroRotator, false);
		if (BeaconWorld && BeaconWorld->GetNetMode() != NM_DedicatedServer)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			if (APointLight* Lamp = BeaconWorld->SpawnActor<APointLight>(At + FVector(0.0, 0.0, 6.0), FRotator::ZeroRotator, Params))
			{
				UPointLightComponent* C = CastChecked<UPointLightComponent>(Lamp->GetLightComponent());
				C->SetMobility(EComponentMobility::Movable);
				C->SetIntensityUnits(ELightUnits::Lumens);
				C->SetIntensity(900.f);
				C->SetAttenuationRadius(700.f);
				C->SetLightColor(FLinearColor(1.0f, 0.55f, 0.12f));
				C->SetCastShadows(false);
				C->SetVolumetricScatteringIntensity(2.0f);
				Spawned.Add(Lamp);
			}
		}
	}
	// The runway beams the bridges ride on, along the hall at both ends of the span.
	for (const double Y : {300.0, 4500.0})
	{
		AddTrim(TEXT("Struct_Gunmetal"), FVector(5000.0, Y, 1400.0), FVector(9500.0, 60.0, 90.0));
		AddTrim(TEXT("Struct_Gunmetal"), FVector(5000.0, Y, 1452.0), FVector(9500.0, 30.0, 14.0));
		AddTrim(TEXT("Arena_HazardYellow"), FVector(5000.0, Y + (Y < 1000.0 ? 31.0 : -31.0), 1380.0), FVector(9500.0, 2.0, 18.0), FRotator::ZeroRotator, false);
		for (double X = 600.0; X < 9500.0; X += 800.0)
		{
			// Hangers from the roof girders.
			AddTrim(TEXT("Struct_Gunmetal"), FVector(X, Y, (1445.0 + CeilingZ) * 0.5), FVector(18.0, 18.0, CeilingZ - 1445.0));
		}
	}

	// High-bay lamps hanging under every girder, in rows along the hall; each lens glows.
	for (double X = GirderX0; X < 9500.0; X += GirderStep)
	{
		for (double Y = 800.0; Y < 5900.0; Y += 900.0)
		{
			AddProp(TEXT("SM_Hangar_HangLamp"), FVector(X, Y, CeilingZ - 140.0 - 216.0), 0.0, FVector(1.6), false);
		}
	}
	// The deck view stands in the hall without the arena's work lights: every second lamp of
	// every second row casts a real light there, so the hall reads at the deck's exposure.
	UWorld* LampWorld = GetWorld();
	if (Part == EVerseGrayboxPart::Hall && LampWorld && LampWorld->GetNetMode() != NM_DedicatedServer)
	{
		FActorSpawnParameters LampParams;
		LampParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		int32 Count = 0;
		for (double X = GirderX0; X < 9500.0; X += GirderStep * 2.0)
		{
			for (double Y = 800.0; Y < 5900.0; Y += 1800.0)
			{
				if (ASpotLight* Spot = LampWorld->SpawnActor<ASpotLight>(FVector(X, Y, CeilingZ - 380.0), FRotator(-90.0, 0.0, 0.0), LampParams))
				{
					USpotLightComponent* C = Spot->SpotLightComponent;
					C->SetMobility(EComponentMobility::Movable);
					C->SetIntensityUnits(ELightUnits::Lumens);
					C->SetIntensity(HallLampLumens);
					C->SetOuterConeAngle(62.f);
					C->SetInnerConeAngle(30.f);
					C->SetAttenuationRadius(2600.f);
					C->SetUseTemperature(true);
					C->SetTemperature(3900.f);
					C->SetCastShadows(Count++ % 4 == 0);
					C->SetVolumetricScatteringIntensity(1.2f);
					Spawned.Add(Spot);
				}
			}
		}
	}

	// Skylights: bright panels set into the roof between girders. The rect light under each one
	// throws a slanted shaft through the haze onto the deck (shadowed, so girders cut the beams).
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	UWorld* World = GetWorld();
	TArray<TPair<FVector2D, bool>> AllSkylights;
	for (const FVector2D& Sky : Skylights)
	{
		AllSkylights.Add({Sky, true});
	}
	for (const FVector2D& Sky : BaySkylights)
	{
		AllSkylights.Add({Sky, false});
	}
	for (const TPair<FVector2D, bool>& Entry : AllSkylights)
	{
		const FVector2D& Sky = Entry.Key;
		const FVector Centre(Sky.X, Sky.Y, CeilingZ - 6.0);
		AddTrim(TEXT("Light_CeilingPanel"), Centre, FVector(SkylightSize.X, SkylightSize.Y, 4.0), FRotator::ZeroRotator, false);
		// The frame and the mullions of the glazing.
		AddTrim(TEXT("Struct_Gunmetal"), Centre - FVector(0.0, 0.0, 8.0), FVector(SkylightSize.X + 40.0, 30.0, 16.0));
		for (const double Dy : {-0.5, -0.25, 0.25, 0.5})
		{
			AddTrim(TEXT("Struct_Gunmetal"), Centre + FVector(0.0, SkylightSize.Y * Dy, -8.0), FVector(SkylightSize.X + 40.0, 18.0, 16.0));
		}
		for (const double Dx : {-0.5, 0.5})
		{
			AddTrim(TEXT("Struct_Gunmetal"), Centre + FVector(SkylightSize.X * Dx, 0.0, -8.0), FVector(18.0, SkylightSize.Y + 40.0, 16.0));
		}
		if (!World || World->GetNetMode() == NM_DedicatedServer)
		{
			continue;
		}
		if (ARectLight* Rect = World->SpawnActor<ARectLight>(Centre - FVector(0.0, 0.0, 30.0), FRotator(-72.0, 25.0, 0.0), Params))
		{
			URectLightComponent* C = Rect->RectLightComponent;
			C->SetMobility(EComponentMobility::Movable);
			C->SetSourceWidth(static_cast<float>(SkylightSize.X));
			C->SetSourceHeight(static_cast<float>(SkylightSize.Y));
			C->SetIntensityUnits(ELightUnits::Lumens);
			C->SetIntensity(SkylightLumens);
			C->SetAttenuationRadius(3200.f);
			C->SetBarnDoorAngle(20.f);
			C->SetBarnDoorLength(60.f);
			C->SetUseTemperature(true);
			C->SetTemperature(7200.f);  // cold daylight against the warm work lights
			C->SetCastShadows(Entry.Value);
			C->SetVolumetricScatteringIntensity(Entry.Value ? SkylightScattering : SkylightScattering * 0.5f);
			Spawned.Add(Rect);
		}
	}
}

void AVerseArenaGraybox::DressArtWalls()
{
	using namespace VerseArenaArtPrivate;

	for (const FWall& Wall : Walls)
	{
		const FVector Along = Wall.Along();
		// A supply duct high on every wall, on braces, with a vent every 6 m.
		constexpr double DuctStep = 66.3;
		int32 Index = 0;
		for (double T = Wall.From; T < Wall.To; T += DuctStep, ++Index)
		{
			if (InDoor(Wall, T))
			{
				continue;
			}
			const FVector At = Wall.At(T, 70.0, 1560.0);
			AddProp(TEXT("SM_Hangar_Duct_Single"), At, Wall.Yaw + 90.0);
			if (Index % 9 == 0)
			{
				AddProp(TEXT("SM_Hangar_Duct_Brace"), At - FVector(0.0, 0.0, 6.0), Wall.Yaw + 90.0);
				AddTrim(TEXT("Struct_Gunmetal"), Wall.At(T, 35.0, 1560.0), Wall.bAlongX ? FVector(6.0, 70.0, 6.0) : FVector(70.0, 6.0, 6.0));
			}
		}
		// Three service pipes at head height and a cable bundle under them.
		constexpr double PipeStep = 195.4;
		for (double T = Wall.From; T + PipeStep < Wall.To; T += PipeStep)
		{
			if (InDoor(Wall, T) || InDoor(Wall, T + PipeStep))
			{
				continue;
			}
			for (int32 Row = 0; Row < 3; ++Row)
			{
				const FVector At = Wall.At(T, 45.0 + Row * 4.0, 300.0 + Row * 28.0);
				// The pipe piece stands along Z: pitched flat along the wall.
				const FRotator Flat = FRotator::MakeFromEuler(Wall.bAlongX ? FVector(0.0, 90.0, 0.0) : FVector(90.0, 0.0, 0.0));
				AddDressing(TEXT("SM_Hangar_Pipes_P2"), FTransform(Flat, At + Along * 0.0, FVector(1.0)));
			}
			for (int32 Strand = 0; Strand < 4; ++Strand)
			{
				const FVector At = Wall.At(T, 18.0 + Strand * 3.0, 250.0 - Strand * 4.0);
				const FRotator Flat = FRotator::MakeFromEuler(Wall.bAlongX ? FVector(0.0, 90.0, 0.0) : FVector(90.0, 0.0, 0.0));
				for (int32 Seg = 0; Seg < 3; ++Seg)
				{
					AddDressing(TEXT("SM_Hangar_Cables_Double"), FTransform(Flat, At + Along * (Seg * 61.4), FVector(1.0)), nullptr, false);
				}
			}
		}
		// Equipment on the walls every 9.6 m: a lamp over a power board or a utility cabinet,
		// an extinguisher and an alarm, and a roller shutter into a side room on the long walls.
		Index = 0;
		for (double T = Wall.From + 300.0; T < Wall.To - 300.0; T += 960.0, ++Index)
		{
			if (InDoor(Wall, T))
			{
				continue;
			}
			AddProp(TEXT("SM_Hangar_WallLamp"), Wall.At(T, 32.0, 520.0), Wall.Yaw);
			AddTrim(TEXT("Arena_LampWarm"), Wall.At(T, 40.0, 528.0), FVector(18.0), FRotator::ZeroRotator, false);
			if (Index % 2 == 0)
			{
				AddProp(TEXT("SM_Hangar_PowerBox"), Wall.At(T + 120.0, 50.0, 140.0), Wall.Yaw);
				AddProp(TEXT("SM_Hangar_Extinguisher"), Wall.At(T - 140.0, 48.0, 0.0), Wall.Yaw);
				AddProp(TEXT("SM_Hangar_FireAlarm"), Wall.At(T - 140.0, 32.0, 150.0), Wall.Yaw);
			}
			else
			{
				AddProp(TEXT("SM_Hangar_UtilityBox"), Wall.At(T, 55.0, 0.0), Wall.Yaw);
				AddProp(TEXT("SM_Hangar_AirUnit"), Wall.At(T + 220.0, 55.0, 0.0), Wall.Yaw);
			}
			if (!Wall.bAlongX && Index % 3 == 1)
			{
				AddProp(TEXT("SM_Hangar_Shutter"), Wall.At(T + 380.0, 34.0, 0.0), Wall.Yaw, FVector(2.2, 1.0, 1.4));
				AddProp(TEXT("SM_Hangar_Ladder"), Wall.At(T - 320.0, 40.0, 0.0), Wall.Yaw, FVector(1.0, 1.0, 1.5));
			}
		}
	}
	// Cameras watching the floor from the hall's corners.
	AddProp(TEXT("SM_Hangar_Camera"), FVector(WestFaceX + 40.0, HeroFaceY + 40.0, 900.0), 45.0);
	AddProp(TEXT("SM_Hangar_Camera"), FVector(EastFaceX - 40.0, HeroFaceY + 40.0, 900.0), 135.0);
	AddProp(TEXT("SM_Hangar_Camera"), FVector(WestFaceX + 40.0, NearFaceY - 40.0, 900.0), -45.0);
	AddProp(TEXT("SM_Hangar_Camera"), FVector(EastFaceX - 40.0, NearFaceY - 40.0, 900.0), -135.0);
}

void AVerseArenaGraybox::DressArtBays()
{
	using namespace VerseArenaArtPrivate;

	// A work station: welding cart, tool trolley and chest, generator, gas bottles and drums.
	auto Station = [this](const FVector& At, double Yaw)
	{
		if (InKeptClearRoom(At))
		{
			return;  // a deck station's room keeps to the deck's own furniture
		}
		const FTransform Frame(FRotator(0.0, Yaw, 0.0), At);
		auto Put = [&](const TCHAR* Name, double X, double Y, double LocalYaw, double Scale = 1.0)
		{
			AddProp(Name, Frame.TransformPosition(FVector(X, Y, 0.0)), Yaw + LocalYaw, FVector(Scale));
		};
		Put(TEXT("SM_Hangar_WeldCart"), 0.0, 0.0, 10.0);
		Put(TEXT("SM_Hangar_ToolTrolley"), 150.0, 30.0, -8.0);
		Put(TEXT("SM_Hangar_ToolChest"), 290.0, -10.0, 0.0);
		Put(TEXT("SM_Hangar_Generator"), -150.0, 160.0, 35.0);
		Put(TEXT("SM_Hangar_GasBottle"), -60.0, -70.0, 0.0);
		Put(TEXT("SM_Hangar_GasBottle"), -25.0, -95.0, 40.0);
		AddProp(TEXT("SM_Hangar_Toolbox"), Frame.TransformPosition(FVector(150.0, 30.0, 96.0)), Yaw + 20.0);
		Put(TEXT("SM_Hangar_HandTruck"), 380.0, 120.0, -60.0);
		// A work light over the station: a warm pool the bay reads by.
		UWorld* World = GetWorld();
		if (World && World->GetNetMode() != NM_DedicatedServer)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			const FVector Lamp = Frame.TransformPosition(FVector(80.0, 40.0, 700.0));
			if (ASpotLight* Spot = World->SpawnActor<ASpotLight>(Lamp, FRotator(-90.0, 0.0, 0.0), Params))
			{
				USpotLightComponent* C = Spot->SpotLightComponent;
				C->SetMobility(EComponentMobility::Movable);
				C->SetIntensityUnits(ELightUnits::Lumens);
				C->SetIntensity(9000.f);
				C->SetOuterConeAngle(42.f);
				C->SetInnerConeAngle(18.f);
				C->SetAttenuationRadius(1400.f);
				C->SetUseTemperature(true);
				C->SetTemperature(4300.f);
				C->SetCastShadows(true);
				C->SetVolumetricScatteringIntensity(0.8f);
				Spawned.Add(Spot);
			}
			AddProp(TEXT("SM_Hangar_HangLamp"), Lamp + FVector(0.0, 0.0, 20.0), 0.0, FVector(1.3), false);
			AddTrim(TEXT("Struct_Gunmetal"), FVector(Lamp.X, Lamp.Y, (Lamp.Z + 150.0 + CeilingZ) * 0.5), FVector(6.0, 6.0, CeilingZ - Lamp.Z - 150.0));
		}
	};
	// Fuel and stores: drums on and around a pallet, crates, cartons on shelving.
	auto Stores = [this](const FVector& At, double Yaw, int32 Seed)
	{
		if (InKeptClearRoom(At))
		{
			return;
		}
		FRandomStream Rng(Seed);
		const FTransform Frame(FRotator(0.0, Yaw, 0.0), At);
		auto Put = [&](const TCHAR* Name, double X, double Y, double Z, double LocalYaw)
		{
			AddProp(Name, Frame.TransformPosition(FVector(X, Y, Z)), Yaw + LocalYaw);
		};
		static const TCHAR* Drums[] = {TEXT("SM_Hangar_Drum"), TEXT("SM_Hangar_DrumB"), TEXT("SM_Hangar_DrumC")};
		for (int32 I = 0; I < 7; ++I)
		{
			Put(Drums[Rng.RandHelper(3)], (I % 4) * 62.0 + Rng.FRandRange(-6.f, 6.f), (I / 4) * 64.0 + Rng.FRandRange(-6.f, 6.f), 0.0, Rng.FRandRange(0.f, 360.f));
		}
		Put(TEXT("SM_Hangar_Shelves"), 160.0, 260.0, 0.0, 0.0);
		Put(TEXT("SM_Hangar_Shelves"), 272.0, 260.0, 0.0, 0.0);
		for (int32 Level = 0; Level < 3; ++Level)
		{
			for (int32 Slot = 0; Slot < 4; ++Slot)
			{
				if (Rng.FRand() < 0.75f)
				{
					Put(Slot % 2 ? TEXT("SM_Hangar_Carton") : TEXT("SM_Hangar_PlasticCrate"), 130.0 + Slot * 56.0, 260.0, 8.0 + Level * 66.0,
						Rng.FRandRange(-8.f, 8.f));
				}
			}
		}
		Put(TEXT("SM_Hangar_MilCrate"), 360.0, 40.0, 0.0, 90.0);
		Put(TEXT("SM_Hangar_MilCrate"), 360.0, 40.0, 47.0, 84.0);
		Put(TEXT("SM_Hangar_MilCrateB"), 470.0, 10.0, 0.0, 5.0);
		Put(TEXT("SM_Hangar_AmmoCan"), 470.0, 10.0, 31.0, 20.0);
		Put(TEXT("SM_Hangar_AmmoCan"), 460.0, 40.0, 31.0, -15.0);
		Put(TEXT("SM_Hangar_Jerrycan"), 300.0, -60.0, 0.0, 30.0);
		Put(TEXT("SM_Hangar_Jerrycan"), 330.0, -70.0, 0.0, 5.0);
		Put(TEXT("SM_Hangar_StoreCart"), 620.0, 140.0, 0.0, 70.0);
		Put(TEXT("SM_Hangar_Bin"), -90.0, 220.0, 0.0, 90.0);
	};
	// A barrier line: jersey barriers in a row, tyres stacked behind them.
	auto Barriers = [this](const FVector& From, double Yaw, int32 Count)
	{
		if (InKeptClearRoom(From))
		{
			return;
		}
		const FVector Dir = FRotator(0.0, Yaw, 0.0).Vector();
		for (int32 I = 0; I < Count; ++I)
		{
			AddProp(TEXT("SM_Hangar_JerseyBarrier"), From + Dir * (I * 158.0), Yaw);
		}
		const FVector Back = From + FRotator(0.0, Yaw + 90.0, 0.0).Vector() * 90.0;
		for (int32 I = 0; I < 3; ++I)
		{
			AddDressing(TEXT("SM_Hangar_Tyre"), FTransform(FRotator(0.0, Yaw, 90.0), Back + FVector(0.0, 0.0, 8.0 + 17.0 * I)));
		}
	};

	// West bay (x 250..2500): stations between the container stacks and the racks.
	Station(FVector(800.0, 3000.0, 0.0), 90.0);
	Stores(FVector(450.0, 3900.0, 0.0), -90.0, 11);
	Station(FVector(2050.0, 4300.0, 0.0), 180.0);
	Barriers(FVector(1900.0, 600.0, 0.0), 90.0, 4);
	Stores(FVector(500.0, 5300.0, 0.0), 0.0, 12);
	// East bay (x 7500..9750), north of the armoury.
	Station(FVector(9200.0, 1500.0, 0.0), -90.0);
	Stores(FVector(9500.0, 2600.0, 0.0), 90.0, 21);
	Station(FVector(8100.0, 4200.0, 0.0), 0.0);
	Barriers(FVector(7900.0, 450.0, 0.0), 0.0, 3);
	// South apron (y 4400..6160) either side of the hall door, clear of the armoury.
	Stores(FVector(1400.0, 5850.0, 0.0), 0.0, 31);
	Station(FVector(6400.0, 5600.0, 0.0), 180.0);
	// The parked gunship on the apron in front of the hall door, seen through the arena fence.
	// On the deck view the apron is the arrivals room and stays clear for its station.
	if (!InKeptClearRoom(FVector(4950.0, 5330.0, 0.0)))
	{
		AddProp(TEXT("SM_Hangar_Shuttle"), FVector(4950.0, 5330.0, 0.0), 90.0);
		AddDressing(TEXT("SM_Hangar_LandingPad"), FTransform(FRotator::ZeroRotator, FVector(4950.0, 5330.0, 0.5), FVector(1.25, 1.0, 1.0)), nullptr, false);
	}
	Barriers(FVector(2700.0, 4720.0, 0.0), 0.0, 4);
	// Floodlights on stands of the bays, aimed at the work.
	AddProp(TEXT("SM_Hangar_Floodlight"), FVector(1000.0, 2700.0, 0.0), 30.0, FVector(1.6));
	AddProp(TEXT("SM_Hangar_Floodlight"), FVector(8900.0, 1900.0, 0.0), 210.0, FVector(1.6));
}

void AVerseArenaGraybox::DressArtWear()
{
	using namespace VerseArenaArtPrivate;
	FRandomStream Rng(0x57454152);
	// Standing water in the low spots of the deck: it mirrors the lamps and the skylight shafts.
	for (int32 I = 0; I < 26; ++I)
	{
		const FVector At(Rng.FRandRange(600.f, 9400.f), Rng.FRandRange(500.f, 5800.f), 0.0);
		if (At.X > 2650.0 && At.X < 3750.0 && At.Y > 850.0 && At.Y < 1950.0)
		{
			continue;  // the launch well
		}
		const double Size = Rng.FRandRange(180.f, 520.f);
		AddWear(TEXT("Arena_Puddle"), At, Rng.FRandRange(0.f, 360.f), Size, Size * Rng.FRandRange(0.5f, 0.9f), false);
	}
	// Tug tracks through the bays and across the apron.
	for (int32 I = 0; I < 18; ++I)
	{
		const bool bBay = I < 12;
		const FVector At = bBay ? FVector(I % 2 ? Rng.FRandRange(700.f, 2300.f) : Rng.FRandRange(7700.f, 9300.f), Rng.FRandRange(600.f, 5600.f), 0.0)
							   : FVector(Rng.FRandRange(2600.f, 7400.f), Rng.FRandRange(4500.f, 5900.f), 0.0);
		AddWear(TEXT("Arena_TyreMark"), At, Rng.FRandRange(0.f, 360.f), 260.0, Rng.FRandRange(500.f, 900.f), false);
	}
	// Dirt banked at the foot of every wall, and rust running down from the pipe brackets.
	for (const FWall& Wall : Walls)
	{
		for (double T = Wall.From; T < Wall.To; T += Rng.FRandRange(260.f, 520.f))
		{
			const double Facing = Wall.Yaw - 90.0;  // decal X points into the wall
			AddWear(TEXT("Arena_Grime"), Wall.At(T, 40.0, 0.0), Rng.FRandRange(0.f, 360.f), Rng.FRandRange(240.f, 480.f), Rng.FRandRange(120.f, 220.f), false);
			if (Rng.FRand() < 0.55f)
			{
				AddWear(TEXT("Arena_Leak"), Wall.At(T, 4.0, Rng.FRandRange(200.f, 900.f)), Facing, Rng.FRandRange(90.f, 220.f), Rng.FRandRange(220.f, 520.f), true);
			}
		}
	}
}

void AVerseArenaGraybox::DressArtBox(const TSharedPtr<FJsonObject>& Box)
{
	const FString Id = Box->GetStringField(TEXT("id"));
	const FString Piece = Box->HasField(TEXT("piece")) ? Box->GetStringField(TEXT("piece")) : FString();
	const bool bCover = Id.StartsWith(TEXT("barrier_")) || Id.StartsWith(TEXT("cover_wall_")) || Id.StartsWith(TEXT("lowwall_"))
		|| Id.StartsWith(TEXT("column_")) || Id.StartsWith(TEXT("cover_column_"));
	const bool bContainer = Id.EndsWith(TEXT("_roof")) && Box->GetStringField(TEXT("zone")) == TEXT("arena_canyon") && !Id.StartsWith(TEXT("hung"));
	const TArray<TSharedPtr<FJsonValue>>& C = Box->GetArrayField(TEXT("center"));
	const TArray<TSharedPtr<FJsonValue>>& S = Box->GetArrayField(TEXT("size"));
	const FVector Centre(C[0]->AsNumber(), C[1]->AsNumber(), C[2]->AsNumber());
	const FVector Size(S[0]->AsNumber(), S[1]->AsNumber(), S[2]->AsNumber());
	// Raised decks and roofs that never break (gallery, booth floors and roofs, the shuttle roof):
	// a steel frame underneath, edge channels along the long sides and joists across every 1.2 m.
	const double Underside = Centre.Z - Size.Z * 0.5;
	if (!Box->HasField(TEXT("piece")) && Underside > 250.0 && Size.Z <= 60.0 && Id != TEXT("ceiling") && FMath::Min(Size.X, Size.Y) >= 200.0)
	{
		const bool bAlongX = Size.X >= Size.Y;
		const double Long = bAlongX ? Size.X : Size.Y;
		const double Short = bAlongX ? Size.Y : Size.X;
		const FVector L = bAlongX ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
		const FVector W = bAlongX ? FVector(0.0, 1.0, 0.0) : FVector(1.0, 0.0, 0.0);
		for (const double Side : {-0.5, 0.5})
		{
			const FVector At = Centre + W * (Side * Short - Side * 8.0);
			AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, Underside - 13.0), bAlongX ? FVector(Long, 14.0, 26.0) : FVector(14.0, Long, 26.0));
		}
		for (double T = -Long * 0.5 + 60.0; T < Long * 0.5 - 30.0; T += 120.0)
		{
			const FVector At = Centre + L * T;
			AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, Underside - 9.0), bAlongX ? FVector(8.0, Short - 20.0, 18.0) : FVector(Short - 20.0, 8.0, 18.0));
		}
		return;
	}
	if (Id.StartsWith(TEXT("console_")))
	{
		// The booth's consoles: the kit console fitted to the box (the box only collides).
		const double Bottom = Centre.Z - Size.Z * 0.5;
		const bool bAlongX = Size.X >= Size.Y;
		const FVector Fit = bAlongX ? FVector(Size.X / 378.0, Size.Y / 109.0, Size.Z / 131.0) : FVector(Size.Y / 378.0, Size.X / 109.0, Size.Z / 131.0);
		AddProp(TEXT("SM_Console_BoothRear"), FVector(Centre.X, Centre.Y, Bottom), bAlongX ? 0.0 : 90.0, Fit);
		return;
	}
	if (Id.StartsWith(TEXT("crate_")) || Id.StartsWith(TEXT("cover_crate")))
	{
		// Cargo under webbing: two straps each way over the top, steel corner guards.
		const double Top = Centre.Z + Size.Z * 0.5;
		for (const double T : {-0.25, 0.25})
		{
			AddTrim(TEXT("Rubber_Black"), FVector(Centre.X + T * Size.X, Centre.Y, Top * 0.5), FVector(9.0, Size.Y + 3.0, Top + 2.0));
			AddTrim(TEXT("Rubber_Black"), FVector(Centre.X, Centre.Y + T * Size.Y, Top * 0.5), FVector(Size.X + 3.0, 9.0, Top + 2.0));
			AddTrim(TEXT("Arena_HazardYellow"), FVector(Centre.X + T * Size.X, Centre.Y, Top * 0.5), FVector(10.0, Size.Y + 3.4, 12.0), FRotator::ZeroRotator, false);
		}
		for (const double A : {-0.5, 0.5})
		{
			for (const double B : {-0.5, 0.5})
			{
				AddTrim(TEXT("Struct_Gunmetal"), FVector(Centre.X + A * Size.X, Centre.Y + B * Size.Y, Top * 0.5), FVector(10.0, 10.0, Top + 1.0));
			}
		}
		AddWear(TEXT("Arena_Grime"), FVector(Centre.X, Centre.Y, 0.0), 0.0, Size.X + 140.0, Size.Y + 140.0, false);
		return;
	}
	if (Id == TEXT("hung_container"))
	{
		// The hung container reads as one: corrugation ribs down both long faces, castings.
		const double Low = Centre.Z - Size.Z * 0.5;
		const double High = Centre.Z + Size.Z * 0.5;
		for (const double Side : {-1.0, 1.0})
		{
			for (double X = -Size.X * 0.5 + 15.0; X < Size.X * 0.5 - 10.0; X += 30.0)
			{
				AddTrim(TEXT("Arena_ContainerRust"), FVector(Centre.X + X, Centre.Y + Side * (Size.Y * 0.5 + 2.0), Centre.Z), FVector(14.0, 4.0, Size.Z - 24.0));
			}
		}
		for (const double A : {-0.5, 0.5})
		{
			for (const double B : {-0.5, 0.5})
			{
				for (const double Z : {Low + 9.0, High - 9.0})
				{
					AddTrim(TEXT("Struct_Gunmetal"), FVector(Centre.X + A * (Size.X - 16.0), Centre.Y + B * (Size.Y - 16.0), Z), FVector(22.0, 22.0, 20.0));
				}
			}
		}
		return;
	}
	if (Piece == TEXT("glass"))
	{
		// Glazing in a steel frame with a mullion: the frame stays when the pane breaks.
		const bool bLongX = Size.X >= Size.Y;
		const double Run = bLongX ? Size.X : Size.Y;
		const FVector RunDir = bLongX ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
		const FVector Edge = bLongX ? FVector(Run + 10.0, 12.0, 8.0) : FVector(12.0, Run + 10.0, 8.0);
		AddTrim(TEXT("Struct_Gunmetal"), Centre + FVector(0.0, 0.0, Size.Z * 0.5), Edge);
		AddTrim(TEXT("Struct_Gunmetal"), Centre - FVector(0.0, 0.0, Size.Z * 0.5), Edge);
		for (const double T : {-0.5, 0.0, 0.5})
		{
			const FVector At = Centre + RunDir * (T * Run);
			AddTrim(TEXT("Struct_Gunmetal"), At, bLongX ? FVector(8.0, 12.0, Size.Z + 8.0) : FVector(12.0, 8.0, Size.Z + 8.0));
		}
		return;
	}
	if (Id.StartsWith(TEXT("screen_")) || Id.StartsWith(TEXT("cover_screen_")))
	{
		// Armour plate on a frame: vertical stiffeners on both faces every 1.5 m, a stringer at mid
		// height and lifting lugs on top.
		const bool bLongX = Size.X >= Size.Y;
		const double Run = bLongX ? Size.X : Size.Y;
		const double Thick = bLongX ? Size.Y : Size.X;
		const FVector RunDir = bLongX ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
		const FVector Across = bLongX ? FVector(0.0, 1.0, 0.0) : FVector(1.0, 0.0, 0.0);
		const double Top = Centre.Z + Size.Z * 0.5;
		const double Low = Centre.Z - Size.Z * 0.5;
		for (const double Side : {-1.0, 1.0})
		{
			for (double T = -Run * 0.5 + 75.0; T < Run * 0.5; T += 150.0)
			{
				const FVector At = Centre + RunDir * T + Across * (Side * (Thick * 0.5 + 4.0));
				AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, (Top + Low + 30.0) * 0.5), bLongX ? FVector(10.0, 8.0, Size.Z - 34.0) : FVector(8.0, 10.0, Size.Z - 34.0));
			}
			const FVector Mid = Centre + Across * (Side * (Thick * 0.5 + 3.0));
			AddTrim(TEXT("Struct_Gunmetal"), FVector(Mid.X, Mid.Y, Centre.Z + 20.0), bLongX ? FVector(Run - 10.0, 6.0, 12.0) : FVector(6.0, Run - 10.0, 12.0));
		}
		for (const double T : {-0.35, 0.35})
		{
			const FVector At = Centre + RunDir * (T * Run);
			AddTrim(TEXT("Struct_Gunmetal"), FVector(At.X, At.Y, Top + 10.0), bLongX ? FVector(14.0, Thick + 6.0, 20.0) : FVector(Thick + 6.0, 14.0, 20.0));
		}
		return;
	}
	if (!bCover && !bContainer)
	{
		return;
	}
	if (Id.StartsWith(TEXT("column_")) || Id.StartsWith(TEXT("cover_column_")))
	{
		// Built-up steel column: angle guards down all four edges, a bolted base plate.
		for (const double A : {-0.5, 0.5})
		{
			for (const double B : {-0.5, 0.5})
			{
				const FVector Corner(Centre.X + A * Size.X, Centre.Y + B * Size.Y, 0.0);
				AddTrim(TEXT("Struct_Gunmetal"), FVector(Corner.X - A * 6.0, Corner.Y + B * 1.0, Size.Z * 0.5), FVector(16.0, 4.0, Size.Z));
				AddTrim(TEXT("Struct_Gunmetal"), FVector(Corner.X + A * 1.0, Corner.Y - B * 6.0, Size.Z * 0.5), FVector(4.0, 16.0, Size.Z));
			}
		}
		AddTrim(TEXT("Struct_Gunmetal"), FVector(Centre.X, Centre.Y, 3.0), FVector(Size.X + 40.0, Size.Y + 40.0, 6.0));
	}
	const double Top = Centre.Z + Size.Z * 0.5;
	const double Bottom = Centre.Z - Size.Z * 0.5;
	FRandomStream Rng(static_cast<int32>(GetTypeHash(Id)));
	const bool bLong = Size.X >= Size.Y;
	const double Run = bLong ? Size.X : Size.Y;
	const double Thick = bLong ? Size.Y : Size.X;
	const FVector RunDir = bLong ? FVector(1.0, 0.0, 0.0) : FVector(0.0, 1.0, 0.0);
	const FVector Across = bLong ? FVector(0.0, 1.0, 0.0) : FVector(1.0, 0.0, 0.0);
	auto Slab = [&](const TCHAR* Look, double AlongT, double Out, double Z, double Len, double Depth, double Height, bool bShadow = true)
	{
		const FVector At = Centre + RunDir * AlongT + Across * Out;
		const FVector Extent = bLong ? FVector(Len, Depth, Height) : FVector(Depth, Len, Height);
		AddTrim(Look, FVector(At.X, At.Y, Z), Extent, FRotator::ZeroRotator, bShadow);
	};
	const bool bWallLike = Id.StartsWith(TEXT("barrier_")) || Id.StartsWith(TEXT("cover_wall_")) || Id.StartsWith(TEXT("lowwall_"));
	if (Id.StartsWith(TEXT("barrier_")) && Box->GetStringField(TEXT("zone")) == TEXT("shell"))
	{
		// The perimeter's inner face: lamps every 8 m, a cable run under them, power boards.
		const FVector Inward = (FVector(5000.0, 2400.0, 0.0) - Centre) * Across;
		const double In = Inward.X + Inward.Y >= 0.0 ? 1.0 : -1.0;
		const double Face = Thick * 0.5;
		const double Yaw = bLong ? (In > 0.0 ? 0.0 : 180.0) : (In > 0.0 ? -90.0 : 90.0);
		const FRotator Flat = FRotator::MakeFromEuler(bLong ? FVector(0.0, 90.0, 0.0) : FVector(90.0, 0.0, 0.0));
		for (double T = -Run * 0.5 + 30.0; T + 61.4 < Run * 0.5; T += 61.4)
		{
			const FVector At = Centre + RunDir * T + Across * (In * (Face + 4.0));
			AddDressing(TEXT("SM_Hangar_Cables_Double"), FTransform(Flat, FVector(At.X, At.Y, 380.0)), nullptr, false);
		}
		// Deck number painted big on every perimeter segment, as hangar bays are marked.
		{
			const FVector Paint = Centre + Across * (In * Face);
			AddWear(TEXT("Arena_Sign_Deck"), FVector(Paint.X, Paint.Y, 230.0), Yaw - 90.0, 300.0, 300.0, true);
		}
		int32 Index = 0;
		for (double T = -Run * 0.5 + 200.0; T < Run * 0.5 - 100.0; T += 400.0, ++Index)
		{
			const FVector At = Centre + RunDir * T + Across * (In * (Face + 2.0));
			if (Index % 2 == 0)
			{
				AddProp(TEXT("SM_Hangar_WallLamp"), FVector(At.X, At.Y, 330.0), Yaw);
				AddTrim(TEXT("Arena_LampWarm"), FVector(At.X, At.Y, 338.0) + Across * (In * 10.0), FVector(16.0), FRotator::ZeroRotator, false);
			}
			else
			{
				AddProp(TEXT("SM_Hangar_PowerBox"), FVector(At.X, At.Y, 120.0) + Across * (In * 18.0), Yaw);
			}
		}
	}
	if (bWallLike && Bottom < 5.0)
	{
		// Cast concrete: a stepped foot on both faces and the joints between 2.4 m segments.
		for (const double Side : {-1.0, 1.0})
		{
			Slab(TEXT("Arena_Barrier"), 0.0, Side * (Thick * 0.5 + 6.0), 18.0, Run + 12.0, 12.0, 36.0);
			for (double T = -Run * 0.5 + 240.0; T < Run * 0.5 - 60.0; T += 240.0)
			{
				Slab(TEXT("Recess_Dark"), T, Side * (Thick * 0.5 + 0.6), (Top + 40.0) * 0.5, 4.0, 1.4, Top - 60.0, false);
			}
		}
	}
	if (bContainer)
	{
		// ISO corner castings and, on one end, the door's locking bars and hinge plates.
		for (const double A : {-0.5, 0.5})
		{
			for (const double B : {-0.5, 0.5})
			{
				for (const double Z : {9.0, Top - 9.0})
				{
					Slab(TEXT("Struct_Gunmetal"), A * Run - A * 8.0, B * Thick - B * 8.0, Z, 20.0, 20.0, 18.0);
				}
			}
		}
		const double End = (Rng.FRand() < 0.5f ? -0.5 : 0.5) * Run;
		const double Out = End > 0.0 ? 3.0 : -3.0;
		for (const double B : {-0.36, -0.14, 0.14, 0.36})
		{
			const double AtX = End + Out;
			Slab(TEXT("Struct_Gunmetal"), AtX, B * Thick, Top * 0.5, 4.0, 4.0, Top - 30.0);
			for (const double Z : {Top * 0.25, Top * 0.75})
			{
				Slab(TEXT("Struct_Gunmetal"), AtX + Out * 0.5, B * Thick + 6.0, Z, 3.0, 12.0, 8.0);
			}
		}
		for (const double Z : {40.0, Top * 0.5, Top - 40.0})
		{
			for (const double B : {-0.49, 0.49})
			{
				Slab(TEXT("Struct_Gunmetal"), End + Out * 0.6, B * Thick, Z, 3.0, 10.0, 26.0);
			}
		}
	}
	// Grime banked against the foot all round.
	AddWear(TEXT("Arena_Grime"), FVector(Centre.X, Centre.Y, 0.0), Rng.FRandRange(-6.f, 6.f), Size.X + 120.0, Size.Y + 120.0, false);
	// Rust and dirt running down the long faces from the top edge.
	const bool bAlongX = Size.X >= Size.Y;
	for (const double Side : {-1.0, 1.0})
	{
		const double Length = bAlongX ? Size.X : Size.Y;
		const int32 Streaks = FMath::Clamp(FMath::RoundToInt(Length / 260.0), 1, 6);
		for (int32 I = 0; I < Streaks; ++I)
		{
			if (Rng.FRand() > 0.6f)
			{
				continue;
			}
			const double T = (Rng.FRandRange(0.1f, 0.9f) - 0.5) * Length;
			const double H = FMath::Min((bContainer ? Top : Size.Z) * Rng.FRandRange(0.4f, 0.8f), 380.0);
			const FVector Face = bAlongX ? FVector(Centre.X + T, Centre.Y + Side * Size.Y * 0.5, Top - H * 0.5)
										 : FVector(Centre.X + Side * Size.X * 0.5, Centre.Y + T, Top - H * 0.5);
			// Decal X points into the face.
			const double Yaw = bAlongX ? (Side > 0.0 ? -90.0 : 90.0) : (Side > 0.0 ? 180.0 : 0.0);
			AddWear(TEXT("Arena_Leak"), Face, Yaw, Rng.FRandRange(70.f, 160.f), H, true);
		}
	}
}

void AVerseArenaGraybox::DressArt()
{
	const int32 Before = DressingInstances;
	// The hull wall modules' backlit slots draw hundreds of small light dashes across the hall; the
	// hangar is lit by its lamps instead, so those slots take the dark recess finish here.
	for (const TPair<FString, TObjectPtr<UInstancedStaticMeshComponent>>& Pair : Dressing)
	{
		UInstancedStaticMeshComponent* Component = Pair.Value;
		const UStaticMesh* Mesh = Component ? Component->GetStaticMesh() : nullptr;
		if (!Mesh || !Mesh->GetName().StartsWith(TEXT("SM_Wall_480")))
		{
			continue;
		}
		const TArray<FStaticMaterial>& Slots = Mesh->GetStaticMaterials();
		for (int32 Slot = 0; Slot < Slots.Num(); ++Slot)
		{
			if (Slots[Slot].MaterialInterface && Slots[Slot].MaterialInterface->GetName() == TEXT("MI_Light_Backlit"))
			{
				Component->SetMaterial(Slot, MaterialFor(TEXT("Recess_Dark")));
			}
		}
	}
	DressArtRoof();
	DressArtWalls();
	DressArtBays();
	DressArtWear();
	UE_LOG(LogVerse, Log, TEXT("[VerseArena] art pass: %d instances, %d from External/ (of %d swap entries)"), DressingInstances - Before,
		ExternalSwapsUsed, ExternalSwaps.Num());
}

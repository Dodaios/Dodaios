#include "VerseArenaGraybox.h"

#include "Components/DirectionalLightComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/DirectionalLight.h"
#include "Engine/RectLight.h"
#include "Engine/SpotLight.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "NavMesh/RecastNavMesh.h"
#include "NavigationSystem.h"
#include "Rules/VerseSpawnPoint.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseCollision.h"
#include "VerseLog.h"

namespace VerseArenaGrayboxPrivate
{
	const TCHAR* CubePath = TEXT("/Engine/BasicShapes/Cube.Cube");
	const TCHAR* MaterialPath = TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial");
	/** Lights that cast shadows (the rest light only); keeps the frame inside budget. */
	constexpr int32 MaxShadowedLights = 8;
	/** Capsule half height above a spawn's floor point, cm. */
	constexpr double SpawnLiftCm = 100.0;

	FLinearColor ColorFor(const FString& Material)
	{
		// Charcoal hall, warm steel, muted containers; linear values (art-pipeline 8.1 shares).
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

AVerseArenaGraybox::AVerseArenaGraybox()
{
	PrimaryActorTick.bCanEverTick = false;
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

UInstancedStaticMeshComponent* AVerseArenaGraybox::SurfaceFor(const FString& Material, bool bSolid, bool bGlass)
{
	using namespace VerseArenaGrayboxPrivate;
	const FString Key = FString::Printf(TEXT("%s_%d"), *Material, bSolid ? 1 : 0);
	if (TObjectPtr<UInstancedStaticMeshComponent>* Found = Surfaces.Find(Key))
	{
		return *Found;
	}
	UInstancedStaticMeshComponent* Surface = NewObject<UInstancedStaticMeshComponent>(this, FName(*(TEXT("Surface_") + Key)));
	Surface->SetMobility(EComponentMobility::Static);
	Surface->SetStaticMesh(LoadObject<UStaticMesh>(nullptr, CubePath));
	if (UMaterialInterface* Base = LoadObject<UMaterialInterface>(nullptr, MaterialPath))
	{
		UMaterialInstanceDynamic* Mid = UMaterialInstanceDynamic::Create(Base, Surface);
		Mid->SetVectorParameterValue(TEXT("Color"), ColorFor(Material));
		Surface->SetMaterial(0, Mid);
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

	for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("boxes")))
	{
		const TSharedPtr<FJsonObject> Box = Value->AsObject();
		const FString Material = Box->GetStringField(TEXT("material"));
		const bool bSolid = Box->GetBoolField(TEXT("solid"));
		const FVector Center = ReadVector(Box, TEXT("center"));
		const FVector Size = ReadVector(Box, TEXT("size"));
		AddSlab(SurfaceFor(Material, bSolid, Material == TEXT("glass")), FTransform(FQuat::Identity, Center, Size / 100.0));
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
		AddSlab(SurfaceFor(TEXT("concrete"), true, false), FTransform(Rotation, Center, FVector(Along.Size(), Width, Thick) / 100.0));
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
		}
	}

	if (World->GetNetMode() != NM_DedicatedServer)
	{
		// Graybox has no bounce-friendly albedo or light cards yet: two shadowless fills keep the
		// space between the work-light cones readable at the deck's manual exposure (EV100 6-7).
		const FRotator FillAims[] = {FRotator(-70.0, 35.0, 0.0), FRotator(-20.0, 215.0, 0.0)};
		const float FillLux[] = {9.f, 3.f};
		for (int32 Index = 0; Index < 2; ++Index)
		{
			if (ADirectionalLight* Fill = World->SpawnActor<ADirectionalLight>(FVector(5000.0, 2400.0, 1500.0), FillAims[Index], Params))
			{
				UDirectionalLightComponent* C = CastChecked<UDirectionalLightComponent>(Fill->GetLightComponent());
				C->SetMobility(EComponentMobility::Movable);
				C->SetIntensity(FillLux[Index]);
				C->SetUseTemperature(true);
				C->SetTemperature(5200.f);
				C->SetCastShadows(false);
				C->SetAtmosphereSunLight(false);
				// The deck's own directional light stays the one for forward shading and fog.
				C->SetForwardShadingPriority(-1 - Index);
				Spawned.Add(Fill);
			}
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
					C->SetInnerConeAngle(float(Light->GetNumberField(TEXT("coneDeg")) * 0.3));
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
			Component->SetTemperature(float(Light->GetNumberField(TEXT("kelvin"))));
			Component->SetAttenuationRadius(float(Light->GetNumberField(TEXT("attenuationCm"))));
			Component->SetCastShadows(bSpot && Shadowed++ < MaxShadowedLights);
		}
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
	UE_LOG(LogVerse, Log, TEXT("[VerseArena] graybox built: %d slabs on %d surfaces, %d actors"), Boxes, Surfaces.Num(), Spawned.Num());
	return Boxes > 0;
}

void AVerseArenaGraybox::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	for (const TObjectPtr<AActor>& Actor : Spawned)
	{
		if (IsValid(Actor))
		{
			Actor->Destroy();
		}
	}
	Spawned.Reset();
	Super::EndPlay(EndPlayReason);
}

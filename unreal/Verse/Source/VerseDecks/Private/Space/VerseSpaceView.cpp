#include "Space/VerseSpaceView.h"

#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Camera/PlayerCameraManager.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Engine/StaticMesh.h"
#include "Materials/MaterialInterface.h"
#include "UObject/UObjectGlobals.h"
#include "VerseLog.h"

namespace
{
	struct FSpaceField
	{
		const TCHAR* Name;
		double FVerseSpaceLook::* Member;
	};

	TConstArrayView<FSpaceField> SpaceFields()
	{
		static const FSpaceField Fields[] = {
			{ TEXT("altitudeKm"), &FVerseSpaceLook::AltitudeKm },
			{ TEXT("centreDownDeg"), &FVerseSpaceLook::CentreDownDeg },
			{ TEXT("rollDeg"), &FVerseSpaceLook::RollDeg },
			{ TEXT("latDeg"), &FVerseSpaceLook::LatDeg },
			{ TEXT("lonDeg"), &FVerseSpaceLook::LonDeg },
			{ TEXT("sunAzimuthDeg"), &FVerseSpaceLook::SunAzimuthDeg },
			{ TEXT("sunElevationDeg"), &FVerseSpaceLook::SunElevationDeg },
			{ TEXT("sunRadiance"), &FVerseSpaceLook::SunRadiance },
			{ TEXT("nightGain"), &FVerseSpaceLook::NightGain },
			{ TEXT("hazeGain"), &FVerseSpaceLook::HazeGain },
			{ TEXT("starGain"), &FVerseSpaceLook::StarGain },
			{ TEXT("orbitSpeed"), &FVerseSpaceLook::OrbitSpeed },
			{ TEXT("planet"), &FVerseSpaceLook::Planet },
		};
		return Fields;
	}
}

bool FVerseSpaceLook::Set(const FString& Field, double Value)
{
	if (!FMath::IsFinite(Value))
	{
		return false;
	}
	for (const FSpaceField& Entry : SpaceFields())
	{
		if (Field.Equals(Entry.Name, ESearchCase::IgnoreCase))
		{
			this->*Entry.Member = Value;
			return true;
		}
	}
	return false;
}

TConstArrayView<const TCHAR*> FVerseSpaceLook::FieldNames()
{
	static TArray<const TCHAR*> Names;
	if (Names.Num() == 0)
	{
		for (const FSpaceField& Entry : SpaceFields())
		{
			Names.Add(Entry.Name);
		}
	}
	return Names;
}

FString FVerseSpaceLook::ToJson(double ElapsedS) const
{
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	for (const FSpaceField& Entry : SpaceFields())
	{
		Root->SetNumberField(Entry.Name, this->*Entry.Member);
	}
	Root->SetNumberField(TEXT("orbit_rad_per_s"), OrbitRadPerS());
	Root->SetNumberField(TEXT("elapsed_s"), ElapsedS);
	Root->SetNumberField(TEXT("earth_turn_rad"), ElapsedS * OrbitRadPerS());
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}

const TCHAR* AVerseSpaceView::EarthMeshPath = TEXT("/Game/Verse/Kit/Props/SM_Space_Earth.SM_Space_Earth");
const TCHAR* AVerseSpaceView::StarDomeMeshPath = TEXT("/Game/Verse/Kit/Props/SM_Space_StarDome.SM_Space_StarDome");
const TCHAR* AVerseSpaceView::EarthMaterialPath = TEXT("/Game/Verse/Materials/Instances/Props/MI_Space_Earth.MI_Space_Earth");
const TCHAR* AVerseSpaceView::StarsMaterialPath = TEXT("/Game/Verse/Materials/Instances/Props/MI_Space_Stars.MI_Space_Stars");

namespace
{
	template <typename T>
	T* LoadQuiet(const TCHAR* Path)
	{
		return LoadObject<T>(nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
}

AVerseSpaceView::AVerseSpaceView()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Earth = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Earth"));
	Earth->SetupAttachment(Root);
	Earth->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Earth->CastShadow = false;
	Stars = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Stars"));
	Stars->SetupAttachment(Root);
	Stars->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Stars->CastShadow = false;
	for (UStaticMeshComponent* Part : { Earth.Get(), Stars.Get() })
	{
		Part->bAffectDistanceFieldLighting = false;
		Part->bReceivesDecals = false;
		Part->SetCanEverAffectNavigation(false);
		Part->bNeverDistanceCull = true;
	}
	Stars->SetRelativeScale3D(FVector(DomeRadiusCm / 100.0));
	Earth->SetRelativeScale3D(FVector(EarthRadiusCm / 100.0));
}

FVector AVerseSpaceView::EarthOffsetCm() const
{
	const double Distance = EarthRadiusCm * (FVerseSpaceLook::EarthKm + Look.AltitudeKm) / FVerseSpaceLook::EarthKm;
	const double Down = FMath::DegreesToRadians(Look.CentreDownDeg);
	return FVector(FMath::Cos(Down) * Distance, 0.0, -FMath::Sin(Down) * Distance);
}

int32 AVerseSpaceView::LoadBackdrop()
{
	int32 Found = 0;
	auto Assign = [&Found](UStaticMeshComponent* Part, const TCHAR* MeshPath, const TCHAR* MaterialPath)
	{
		if (UStaticMesh* Mesh = LoadQuiet<UStaticMesh>(MeshPath))
		{
			Part->SetStaticMesh(Mesh);
			++Found;
		}
		else
		{
			UE_LOG(LogVerseDecks, Warning, TEXT("space view: no mesh %s"), MeshPath);
		}
		if (UMaterialInterface* Material = LoadQuiet<UMaterialInterface>(MaterialPath))
		{
			Part->SetMaterial(0, Material);
			++Found;
		}
		else
		{
			UE_LOG(LogVerseDecks, Log, TEXT("space view: no instance %s yet (WP14 masters), default material"), MaterialPath);
		}
	};
	Assign(Earth, EarthMeshPath, EarthMaterialPath);
	Assign(Stars, StarDomeMeshPath, StarsMaterialPath);
	Earth->SetRelativeLocation(EarthOffsetCm());
	return Found;
}

void AVerseSpaceView::BeginPlay()
{
	Super::BeginPlay();
	LoadBackdrop();
}

void AVerseSpaceView::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	ElapsedS += DeltaSeconds;
	// At infinity: the backdrop rides with the camera, so windows show no parallax.
	if (const UWorld* World = GetWorld())
	{
		if (const APlayerController* Controller = World->GetFirstPlayerController())
		{
			if (Controller->PlayerCameraManager)
			{
				SetActorLocation(Controller->PlayerCameraManager->GetCameraLocation());
			}
		}
	}
	Earth->SetVisibility(Look.Planet > 0.5);
	Earth->SetRelativeLocation(EarthOffsetCm());
	Earth->SetRelativeRotation(FRotator(0.0, FMath::RadiansToDegrees(EarthTurnRad()), Look.RollDeg));
}

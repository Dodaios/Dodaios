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
#include "Materials/MaterialParameterCollection.h"
#include "Materials/MaterialParameterCollectionInstance.h"
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

const TCHAR* AVerseSpaceView::StarDomeMeshPath = TEXT("/Game/Verse/Kit/Props/SM_Space_StarDome.SM_Space_StarDome");
const TCHAR* AVerseSpaceView::EarthMaterialPath = TEXT("/Game/Verse/Materials/Instances/Props/MI_Space_Earth.MI_Space_Earth");
const TCHAR* AVerseSpaceView::StarsMaterialPath = TEXT("/Game/Verse/Materials/Instances/Props/MI_Space_Stars.MI_Space_Stars");
const TCHAR* AVerseSpaceView::CollectionPath = TEXT("/Game/Verse/Materials/Master/MPC_Verse_Space.MPC_Verse_Space");

namespace
{
	template <typename T>
	T* LoadQuiet(const TCHAR* Path)
	{
		return LoadObject<T>(nullptr, Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}

	/** Unreal axes <-> three.js axes: swap Y and Z (coordinates.md section 1; its own inverse). */
	FVector Swap(const FVector& V)
	{
		return FVector(V.X, V.Z, V.Y);
	}

	/** three.js `Vector3.applyAxisAngle`: right-handed rotation about a unit axis. */
	FVector Rotate(const FVector& V, const FVector& Axis, double Angle)
	{
		const double C = FMath::Cos(Angle);
		const double S = FMath::Sin(Angle);
		return V * C + FVector::CrossProduct(Axis, V) * S + Axis * FVector::DotProduct(Axis, V) * (1.0 - C);
	}

	FLinearColor Vec4(const FVector& V)
	{
		return FLinearColor(float(V.X), float(V.Y), float(V.Z), 0.f);
	}
}

FVerseSpaceFrame FVerseSpaceFrame::Compute(const FVerseSpaceLook& Look, const FVector& OutwardThree, double ElapsedS)
{
	// SpaceView.update in spaceView.ts, line by line; lengths in Earth radii, three.js axes.
	FVerseSpaceFrame F;
	const double Rad = UE_DOUBLE_PI / 180.0;
	FVector Out = FVector(OutwardThree.X, 0.0, OutwardThree.Z).GetSafeNormal();
	if (Out.IsNearlyZero())
	{
		Out = FVector(0.0, 0.0, 1.0);
	}
	FVector Up(0.0, 1.0, 0.0);
	FVector Side = FVector::CrossProduct(Out, Up).GetSafeNormal();
	// Horizon tilt: the whole frame turns about the outward axis.
	Up = Rotate(Up, Out, Look.RollDeg * Rad);
	Side = Rotate(Side, Out, Look.RollDeg * Rad);

	const double Distance = 1.0 + Look.AltitudeKm / FVerseSpaceLook::EarthKm;
	const double Down = Look.CentreDownDeg * Rad;
	const FVector Centre = (Out * FMath::Cos(Down) - Up * FMath::Sin(Down)) * Distance;
	// The ground point facing the windows: where the outward ray meets the sphere, else the limb.
	const double B = FVector::DotProduct(Centre, Out);
	const double H = B * B - (Centre.SizeSquared() - 1.0);
	const FVector NW = (Out * (H > 0.0 ? B - FMath::Sqrt(H) : B) - Centre).GetSafeNormal();
	const FVector EW = (Side - NW * FVector::DotProduct(Side, NW)).GetSafeNormal();
	const FVector North = FVector::CrossProduct(NW, EW);
	// The chosen place in the maps' frame: y north, longitude 0 at +x, east towards -z.
	const double Lat = Look.LatDeg * Rad;
	const double Lon = Look.LonDeg * Rad;
	const FVector PL(FMath::Cos(Lat) * FMath::Cos(Lon), FMath::Sin(Lat), -FMath::Cos(Lat) * FMath::Sin(Lon));
	const FVector EL(-FMath::Sin(Lon), 0.0, -FMath::Cos(Lon));
	const FVector NL = FVector::CrossProduct(PL, EL);
	// worldToEarth = L * W^T (L has the columns eL, nL, pL; W the columns eW, north, nW): row I.
	for (int32 I = 0; I < 3; ++I)
	{
		F.Rows[I] = EW * EL[I] + North * NL[I] + NW * PL[I];
	}
	F.EarthCentre = Centre;
	// Ground moving under the ship towards the right of the windows.
	const double Turn = ElapsedS * Look.OrbitRadPerS();
	F.Spin = -Turn;
	F.CloudSpin = -Turn * 1.04 + 0.35;
	const double Az = Look.SunAzimuthDeg * Rad;
	const double El = Look.SunElevationDeg * Rad;
	F.SunDir = (Out * (FMath::Cos(El) * FMath::Cos(Az)) + Side * (FMath::Cos(El) * FMath::Sin(Az)) + Up * FMath::Sin(El)).GetSafeNormal();
	return F;
}

AVerseSpaceView::AVerseSpaceView()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickGroup = TG_PostUpdateWork;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Stars = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("Stars"));
	Stars->SetupAttachment(Root);
	Stars->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Stars->CastShadow = false;
	Stars->bAffectDistanceFieldLighting = false;
	Stars->bAffectDynamicIndirectLighting = false;
	Stars->bReceivesDecals = false;
	Stars->SetCanEverAffectNavigation(false);
	Stars->bNeverDistanceCull = true;
	// Behind every other translucent surface: the viewport glass draws over it.
	Stars->TranslucencySortPriority = -1000;
	Stars->SetRelativeScale3D(FVector(DomeRadiusCm / 100.0));
	// Brighter stars than three.js (starGain 1): the bridge's side windows look across the orbit,
	// away from the Earth, and with the game's grade the sparse field read as black panes.
	Look.StarGain = 2.0;
}

void AVerseSpaceView::SetOutward(const FVector& Direction)
{
	const FVector Level(Direction.X, Direction.Y, 0.0);
	Outward = Level.IsNearlyZero() ? FVector(1.0, 0.0, 0.0) : Level.GetSafeNormal();
}

FVerseSpaceFrame AVerseSpaceView::Frame() const
{
	return FVerseSpaceFrame::Compute(Look, Swap(Outward), ElapsedS);
}

int32 AVerseSpaceView::LoadBackdrop()
{
	int32 Found = 0;
	if (UStaticMesh* Mesh = LoadQuiet<UStaticMesh>(StarDomeMeshPath))
	{
		Stars->SetStaticMesh(Mesh);
		++Found;
	}
	else
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("space view: no mesh %s"), StarDomeMeshPath);
	}
	EarthMaterial = LoadQuiet<UMaterialInterface>(EarthMaterialPath);
	StarsMaterial = LoadQuiet<UMaterialInterface>(StarsMaterialPath);
	Collection = LoadQuiet<UMaterialParameterCollection>(CollectionPath);
	Found += EarthMaterial ? 1 : 0;
	Found += StarsMaterial ? 1 : 0;
	Found += Collection ? 1 : 0;
	if (!EarthMaterial || !StarsMaterial || !Collection)
	{
		UE_LOG(LogVerseDecks, Warning, TEXT("space view: missing %s %s %s"), EarthMaterial ? TEXT("") : EarthMaterialPath,
			StarsMaterial ? TEXT("") : StarsMaterialPath, Collection ? TEXT("") : CollectionPath);
	}
	Stars->SetMaterial(0, EarthMaterial);
	PushFrame();
	return Found;
}

void AVerseSpaceView::PushFrame()
{
	UWorld* World = GetWorld();
	UMaterialParameterCollectionInstance* Instance = (World && Collection) ? World->GetParameterCollectionInstance(Collection) : nullptr;
	if (Instance == nullptr)
	{
		return;
	}
	const FVerseSpaceFrame F = Frame();
	Instance->SetVectorParameterValue(TEXT("EarthCentre"), Vec4(F.EarthCentre));
	Instance->SetVectorParameterValue(TEXT("EarthRow0"), Vec4(F.Rows[0]));
	Instance->SetVectorParameterValue(TEXT("EarthRow1"), Vec4(F.Rows[1]));
	Instance->SetVectorParameterValue(TEXT("EarthRow2"), Vec4(F.Rows[2]));
	Instance->SetVectorParameterValue(TEXT("SunDir"), Vec4(F.SunDir));
	Instance->SetVectorParameterValue(TEXT("Spin"), FLinearColor(float(F.Spin), float(F.CloudSpin), float(Look.SunRadiance), float(Look.NightGain)));
	Instance->SetVectorParameterValue(TEXT("Gains"), FLinearColor(float(Look.HazeGain), float(Look.StarGain), Look.Planet > 0.5 ? 1.f : 0.f, 1.f));
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
	// At infinity: the dome rides with the camera, so windows show no parallax.
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
	Stars->SetMaterial(0, DomeOverride ? DomeOverride.Get() : Look.Planet > 0.5 ? EarthMaterial.Get() : StarsMaterial.Get());
	PushFrame();
}

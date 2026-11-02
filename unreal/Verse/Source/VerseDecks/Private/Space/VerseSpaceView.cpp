#include "Space/VerseSpaceView.h"

#include "Components/StaticMeshComponent.h"
#include "Dom/JsonObject.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "Camera/PlayerCameraManager.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

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
	Earth->SetRelativeRotation(FRotator(0.0, FMath::RadiansToDegrees(EarthTurnRad()), Look.RollDeg));
}

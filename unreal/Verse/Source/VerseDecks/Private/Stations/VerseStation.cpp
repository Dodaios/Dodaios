#include "Stations/VerseStation.h"

#include "Components/SceneComponent.h"
#include "Events/VerseEventHub.h"
#include "Stations/VerseStationSubsystem.h"

AVerseStation::AVerseStation()
{
	PrimaryActorTick.bCanEverTick = false;
	RootComponent = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	UseSpot = CreateDefaultSubobject<USceneComponent>(TEXT("UseSpot"));
	UseSpot->SetupAttachment(RootComponent);
	UseSpot->SetRelativeLocation(FVector(-80.f, 0.f, 0.f));
}

FString AVerseStation::PromptName() const
{
	const UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this);
	const FString Fallback = VerseStations::FallbackName(Kind);
	return Stations ? Stations->Localize(VerseStations::NameKey(Kind), Fallback) : Fallback;
}

FString AVerseStation::PromptAction() const
{
	const UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this);
	const FString Fallback = VerseStations::FallbackAction(Kind);
	return Stations ? Stations->Localize(VerseStations::ActionKey(Kind), Fallback) : Fallback;
}

void AVerseStation::Use(int32 UserId)
{
	if (!bEnabled)
	{
		return;
	}
	if (UVerseEventHub* Hub = UVerseEventHub::Get(this))
	{
		FVerseStationUsedEvent Event;
		Event.StationId = StationId;
		Event.Kind = VerseStations::KindName(Kind);
		Event.UserId = UserId;
		Hub->OnStationUsed.Broadcast(Event);
	}
}

void AVerseStation::BeginPlay()
{
	Super::BeginPlay();
	if (UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this))
	{
		Stations->RegisterStation(this);
		TWeakObjectPtr<AVerseStation> Self(this);
		FVerseUseTarget Target;
		Target.Owner = this;
		Target.Location = [Self]() { return Self.IsValid() ? Self->GetActorLocation() : FVector::ZeroVector; };
		Target.CanUse = [Self]() { return Self.IsValid() && Self->bEnabled; };
		Target.Label = [Self]() { return Self.IsValid() ? Self->PromptName() : FString(); };
		Target.Action = [Self]() { return Self.IsValid() ? Self->PromptAction() : FString(); };
		Target.Use = [Self](int32 UserId)
		{
			if (Self.IsValid())
			{
				Self->Use(UserId);
			}
		};
		UseHandle = Stations->AddUseTarget(MoveTemp(Target));
	}
}

void AVerseStation::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this))
	{
		Stations->RemoveUseTarget(UseHandle);
		Stations->UnregisterStation(this);
	}
	UseHandle = INDEX_NONE;
	Super::EndPlay(Reason);
}

AVerseArmouryStation::AVerseArmouryStation()
{
	Kind = EVerseStationKind::Armoury;
}

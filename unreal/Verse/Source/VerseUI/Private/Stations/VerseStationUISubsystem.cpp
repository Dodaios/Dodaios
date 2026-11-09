#include "Stations/VerseStationUISubsystem.h"

#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "HAL/PlatformTime.h"
#include "Stations/SVerseStationPanel.h"
#include "Stations/VerseStation.h"

namespace
{
	constexpr double NoticeSeconds = 4.0;
}

UVerseStationUISubsystem* UVerseStationUISubsystem::Get(const UObject* WorldContext)
{
	if (!WorldContext || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContext, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseStationUISubsystem>() : nullptr;
}

void UVerseStationUISubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	UVerseEventHub* Hub = Collection.InitializeDependency<UVerseEventHub>();
	UVerseStationSubsystem* StationSystem = Collection.InitializeDependency<UVerseStationSubsystem>();
	Super::Initialize(Collection);
	Stations = StationSystem;

	TWeakObjectPtr<UVerseStationUISubsystem> Self(this);
	StationController.GetLink = [Self]() -> IVerseCommandLink*
	{
		return Self.IsValid() && Self->Stations.IsValid() ? Self->Stations->GetLink() : nullptr;
	};
	StationController.Notice = [Self](const FString& Text)
	{
		if (Self.IsValid())
		{
			Self->ShowNotice(Text);
		}
	};
	StationController.Localize = [Self](const FString& Key, const FString& Fallback)
	{
		return Self.IsValid() && Self->Stations.IsValid() ? Self->Stations->Localize(Key, Fallback) : Fallback;
	};
	StationController.ErrorText = [Self](const FString& Code)
	{
		return Self.IsValid() && Self->Stations.IsValid() ? Self->Stations->ErrorText(Code) : Code;
	};

	if (Hub)
	{
		UsedHandle = Hub->OnStationUsed.AddUObject(this, &UVerseStationUISubsystem::HandleStationUsed);
	}
	if (StationSystem)
	{
		StationSystem->OnNotice.AddUObject(this, &UVerseStationUISubsystem::ShowNotice);
		StationSystem->OnPromptChanged.AddWeakLambda(this, [this](const FVerseStationPrompt& Prompt) { CurrentPrompt = Prompt; });
	}
}

void UVerseStationUISubsystem::Deinitialize()
{
	if (Panel.IsValid() && GEngine && GEngine->GameViewport)
	{
		GEngine->GameViewport->RemoveViewportWidgetContent(Panel.ToSharedRef());
	}
	Panel.Reset();
	Super::Deinitialize();
}

void UVerseStationUISubsystem::OnWorldBeginPlay(UWorld& InWorld)
{
	Super::OnWorldBeginPlay(InWorld);
	UGameViewportClient* Viewport = InWorld.GetGameViewport();
	if (!Viewport || !InWorld.IsGameWorld())
	{
		return;
	}
	Panel = SNew(SVerseStationPanel).Owner(this);
	Viewport->AddViewportWidgetContent(Panel.ToSharedRef(), 20);
}

void UVerseStationUISubsystem::HandleStationUsed(const FVerseStationUsedEvent& Event)
{
	FString Room;
	if (Stations.IsValid())
	{
		if (const AVerseStation* Station = Stations->FindStation(Event.StationId))
		{
			Room = Station->Room;
		}
	}
	StationController.HandleStationUsed(Event.Kind, Event.StationId, Room);
}

void UVerseStationUISubsystem::ShowNotice(const FString& Text)
{
	NoticeText = Text;
	NoticeUntil = FPlatformTime::Seconds() + NoticeSeconds;
}

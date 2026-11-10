#include "QA/VerseDecksOverlay.h"

#include "Components/InputComponent.h"
#include "Containers/Ticker.h"
#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseDeckSubsystem.h"
#include "DrawDebugHelpers.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HAL/IConsoleManager.h"
#include "VerseLog.h"

namespace
{
	bool GOn = false;
	bool GInstalled = false;
	TWeakObjectPtr<UVerseDeckSubsystem> GOwner;
	FTSTicker::FDelegateHandle GTick;
	IConsoleObject* GCommand = nullptr;
	TWeakObjectPtr<UInputComponent> GBoundInput;

	const FColor RoomColor(40, 200, 220);
	const FColor WaypointColor(255, 150, 40);
	const FColor SocketColor(230, 220, 70);
	const FColor StationColor(230, 60, 200);

	FVector Plan(const FVector2D& P, double Z)
	{
		return FVector(P.X, P.Y, Z + 4.0);
	}

	void BindF9(UWorld* World)
	{
		APlayerController* Player = World ? World->GetFirstPlayerController() : nullptr;
		UInputComponent* Input = Player ? Player->InputComponent.Get() : nullptr;
		if (Input == nullptr || GBoundInput.Get() == Input)
		{
			return;
		}
		FInputKeyBinding Binding(FInputChord(FKey(TEXT("F9"))), IE_Pressed);
		Binding.KeyDelegate.GetDelegateForManualSet().BindLambda([]()
			{
				if (GInstalled)
				{
					VerseDecksOverlay::SetOn(!GOn);
				}
			});
		Input->KeyBindings.Emplace(MoveTemp(Binding));
		GBoundInput = Input;
	}
}

VerseDecksOverlay::FCounts VerseDecksOverlay::Count(const FVerseDeckManifest& Manifest)
{
	FCounts Counts;
	Counts.Rooms = Manifest.Rooms.Num();
	Counts.Stations = Manifest.Stations.Num();
	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		if (Socket.Kind == TEXT("waypoint"))
		{
			++Counts.Waypoints;
		}
		else
		{
			++Counts.Sockets;
		}
	}
	return Counts;
}

void VerseDecksOverlay::Draw(UWorld* World, const FVerseDeckManifest& Manifest)
{
	if (World == nullptr)
	{
		return;
	}
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		const int32 N = Room.PolygonCm.Num();
		FVector2D Sum = FVector2D::ZeroVector;
		for (int32 I = 0; I < N; ++I)
		{
			DrawDebugLine(World, Plan(Room.PolygonCm[I], Room.ZCm), Plan(Room.PolygonCm[(I + 1) % N], Room.ZCm), RoomColor, false, -1.f, 0, 3.f);
			Sum += Room.PolygonCm[I];
		}
		if (N > 0)
		{
			DrawDebugString(World, Plan(Sum / N, Room.ZCm) + FVector(0, 0, 20), Room.Id.ToString(), nullptr, RoomColor, 0.f, true, 1.f);
		}
	}
	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		const bool bWaypoint = Socket.Kind == TEXT("waypoint");
		const FVector At = Socket.Transform.GetLocation();
		DrawDebugSphere(World, At, bWaypoint ? 12.f : 8.f, 6, bWaypoint ? WaypointColor : SocketColor, false, -1.f, 0, 1.f);
		DrawDebugDirectionalArrow(World, At, At + Socket.Transform.GetRotation().GetForwardVector() * 40.0, 12.f, bWaypoint ? WaypointColor : SocketColor, false, -1.f, 0, 1.f);
		if (!bWaypoint)
		{
			DrawDebugString(World, At + FVector(0, 0, 25), Socket.Kind.ToString(), nullptr, SocketColor, 0.f, true, 0.8f);
		}
	}
	for (const FVerseDeckStation& Station : Manifest.Stations)
	{
		const FVector At = Station.Transform.GetLocation();
		DrawDebugBox(World, At + FVector(0, 0, 50), FVector(40.0, 40.0, 50.0), Station.Transform.GetRotation(), StationColor, false, -1.f, 0, 2.f);
		DrawDebugString(World, At + FVector(0, 0, 110), FString::Printf(TEXT("%s (%s)"), *Station.Id.ToString(), *Station.Kind.ToString()), nullptr, StationColor, 0.f, true, 1.f);
	}
}

FString VerseDecksOverlay::StateJson(UVerseDeckSubsystem& Decks)
{
	const FName Deck = Decks.GetCurrentDeck();
	FCounts Counts;
	if (const FVerseDeckManifest* Manifest = Deck.IsNone() ? nullptr : Decks.GetManifest(Deck))
	{
		Counts = Count(*Manifest);
	}
	return FString::Printf(TEXT("{\"on\":%s,\"deck\":\"%s\",\"rooms\":%d,\"waypoints\":%d,\"sockets\":%d,\"stations\":%d}"),
		GOn ? TEXT("true") : TEXT("false"), *Deck.ToString(), Counts.Rooms, Counts.Waypoints, Counts.Sockets, Counts.Stations);
}

bool VerseDecksOverlay::IsOn()
{
	return GOn;
}

void VerseDecksOverlay::SetOn(bool bOn)
{
	GOn = bOn;
	UE_LOG(LogVerseDecks, Log, TEXT("alignment overlay %s"), bOn ? TEXT("on") : TEXT("off"));
}

void VerseDecksOverlay::Install(UVerseDeckSubsystem& Decks)
{
#if !UE_BUILD_SHIPPING
	GOwner = &Decks;
	GInstalled = true;
	if (GCommand == nullptr)
	{
		GCommand = IConsoleManager::Get().RegisterConsoleCommand(
			TEXT("Verse.Debug.Overlay"),
			TEXT("Verse.Debug.Overlay [on|off]: alignment overlay (rooms, waypoints, sockets, stations); F9 toggles"),
			FConsoleCommandWithArgsDelegate::CreateLambda([](const TArray<FString>& Args)
				{
					if (!Args.IsEmpty() && Args[0].Equals(TEXT("on"), ESearchCase::IgnoreCase))
					{
						SetOn(true);
					}
					else if (!Args.IsEmpty() && Args[0].Equals(TEXT("off"), ESearchCase::IgnoreCase))
					{
						SetOn(false);
					}
					else
					{
						SetOn(!GOn);
					}
					if (UVerseDeckSubsystem* Owner = GOwner.Get())
					{
						UE_LOG(LogVerseDecks, Display, TEXT("%s"), *StateJson(*Owner));
					}
				}),
			ECVF_Default);
	}
	GTick = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateLambda([](float)
		{
			UVerseDeckSubsystem* Owner = GOwner.Get();
			UGameInstance* Instance = Owner ? Owner->GetGameInstance() : nullptr;
			UWorld* World = Instance ? Instance->GetWorld() : nullptr;
			if (World == nullptr)
			{
				return true;
			}
			BindF9(World);
			if (GOn && !Owner->GetCurrentDeck().IsNone())
			{
				if (const FVerseDeckManifest* Manifest = Owner->GetManifest(Owner->GetCurrentDeck()))
				{
					Draw(World, *Manifest);
				}
			}
			return true;
		}));
#endif
}

void VerseDecksOverlay::Remove(UVerseDeckSubsystem& Decks)
{
	if (GOwner.Get() != &Decks)
	{
		return;
	}
	GInstalled = false;
	GOn = false;
	GOwner.Reset();
	GBoundInput.Reset();
	FTSTicker::GetCoreTicker().RemoveTicker(GTick);
	GTick.Reset();
	if (GCommand != nullptr)
	{
		IConsoleManager::Get().UnregisterConsoleObject(GCommand, false);
		GCommand = nullptr;
	}
}

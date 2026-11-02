#include "Decks/VerseDeckManifest.h"

#include "Dom/JsonObject.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseLog.h"

namespace Verse::Decks
{
	TConstArrayView<FVerseDeckInfo> All()
	{
		static const TArray<FVerseDeckInfo> Decks = {
			{ FName(TEXT("bridge")), 1, TEXT("Bridge"), TEXT("/Game/Verse/Decks/Bridge/LV_Bridge") },
			{ FName(TEXT("ops")), 2, TEXT("Ops"), TEXT("/Game/Verse/Decks/Ops/LV_Ops") },
			{ FName(TEXT("engineering")), 3, TEXT("Engineering"), TEXT("/Game/Verse/Decks/Engineering/LV_Engineering") },
			{ FName(TEXT("hangar")), 4, TEXT("Hangar"), TEXT("/Game/Verse/Decks/Hangar/LV_Hangar") },
		};
		return Decks;
	}

	const FVerseDeckInfo* Find(FName Deck)
	{
		for (const FVerseDeckInfo& Info : All())
		{
			if (Info.Id == Deck)
			{
				return &Info;
			}
		}
		return nullptr;
	}

	FString PlacementsDir()
	{
		return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT("Art/Placements")));
	}
}

namespace VerseDeckManifestPrivate
{
	bool ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, int32 Count, TArray<double>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object->TryGetArrayField(Field, Values) || Values->Num() != Count)
		{
			return false;
		}
		Out.Reset(Count);
		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			double Number = 0.0;
			if (!Value.IsValid() || !Value->TryGetNumber(Number))
			{
				return false;
			}
			Out.Add(Number);
		}
		return true;
	}

	bool ReadTransform(const TSharedPtr<FJsonObject>& Object, FTransform& Out)
	{
		TArray<double> Location;
		TArray<double> Rotation;
		if (!ReadVector(Object, TEXT("location"), 3, Location) || !ReadVector(Object, TEXT("rotation"), 4, Rotation))
		{
			return false;
		}
		FQuat Quat(Rotation[0], Rotation[1], Rotation[2], Rotation[3]);
		Quat.Normalize();
		Out = FTransform(Quat, FVector(Location[0], Location[1], Location[2]));
		return true;
	}

	FName NameField(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		FString Value;
		return Object->TryGetStringField(Field, Value) ? FName(*Value) : NAME_None;
	}
}

bool FVerseDeckRoom::ContainsPlan(const FVector2D& Point) const
{
	bool bInside = false;
	const int32 Count = PolygonCm.Num();
	for (int32 I = 0, J = Count - 1; I < Count; J = I++)
	{
		const FVector2D& A = PolygonCm[I];
		const FVector2D& B = PolygonCm[J];
		if ((A.Y > Point.Y) != (B.Y > Point.Y) && Point.X < (B.X - A.X) * (Point.Y - A.Y) / (B.Y - A.Y) + A.X)
		{
			bInside = !bInside;
		}
	}
	return bInside;
}

bool FVerseDeckRoom::Contains(const FVector& FeetCm) const
{
	return FMath::Abs(FeetCm.Z - ZCm) < FloorBandCm && ContainsPlan(FVector2D(FeetCm.X, FeetCm.Y));
}

bool FVerseDeckManifest::AddPlacementJson(const FString& Json, FString& OutError)
{
	using namespace VerseDeckManifestPrivate;

	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = TEXT("not valid JSON");
		return false;
	}
	FString Schema;
	if (!Root->TryGetStringField(TEXT("schema"), Schema) || Schema != TEXT("verse.placement/1"))
	{
		OutError = FString::Printf(TEXT("schema is '%s', want verse.placement/1"), *Schema);
		return false;
	}
	const FName FileDeck = NameField(Root, TEXT("deck"));
	const FName Zone = NameField(Root, TEXT("zone"));
	if (Deck.IsNone())
	{
		Deck = FileDeck;
	}
	if (FileDeck != Deck || Zone.IsNone())
	{
		OutError = FString::Printf(TEXT("file of deck '%s' zone '%s' added to deck '%s'"), *FileDeck.ToString(), *Zone.ToString(), *Deck.ToString());
		return false;
	}
	Zones.AddUnique(Zone);

	const TArray<TSharedPtr<FJsonValue>>* RoomValues = nullptr;
	if (Root->TryGetArrayField(TEXT("rooms"), RoomValues))
	{
		for (const TSharedPtr<FJsonValue>& Value : *RoomValues)
		{
			const TSharedPtr<FJsonObject> Object = Value.IsValid() ? Value->AsObject() : nullptr;
			if (!Object.IsValid())
			{
				continue;
			}
			FVerseDeckRoom& Room = Rooms.AddDefaulted_GetRef();
			Room.Id = NameField(Object, TEXT("id"));
			Object->TryGetStringField(TEXT("name"), Room.Name);
			Room.Zone = Zone;
			Object->TryGetNumberField(TEXT("z_cm"), Room.ZCm);
			Object->TryGetBoolField(TEXT("main"), Room.bMain);
			const TArray<TSharedPtr<FJsonValue>>* Points = nullptr;
			if (Object->TryGetArrayField(TEXT("polygon_cm"), Points))
			{
				for (const TSharedPtr<FJsonValue>& Point : *Points)
				{
					const TArray<TSharedPtr<FJsonValue>>& XY = Point->AsArray();
					if (XY.Num() == 2)
					{
						Room.PolygonCm.Add(FVector2D(XY[0]->AsNumber(), XY[1]->AsNumber()));
					}
				}
			}
		}
	}

	const TArray<TSharedPtr<FJsonValue>>* SocketValues = nullptr;
	if (Root->TryGetArrayField(TEXT("sockets"), SocketValues))
	{
		for (const TSharedPtr<FJsonValue>& Value : *SocketValues)
		{
			const TSharedPtr<FJsonObject> Object = Value.IsValid() ? Value->AsObject() : nullptr;
			if (!Object.IsValid())
			{
				continue;
			}
			FVerseDeckSocket Socket;
			Socket.Id = NameField(Object, TEXT("id"));
			Socket.Kind = NameField(Object, TEXT("kind"));
			Socket.Zone = Zone;
			Socket.Room = NameField(Object, TEXT("room"));
			if (!ReadTransform(Object, Socket.Transform))
			{
				OutError = FString::Printf(TEXT("socket %s: bad location or rotation"), *Socket.Id.ToString());
				return false;
			}
			const TSharedPtr<FJsonObject>* Station = nullptr;
			if (Object->TryGetObjectField(TEXT("station"), Station))
			{
				Socket.StationId = NameField(*Station, TEXT("id"));
				Socket.StationKind = NameField(*Station, TEXT("kind"));
			}
			TArray<double> Size;
			if (ReadVector(Object, TEXT("size_cm"), 2, Size))
			{
				Socket.SizeCm = FVector2D(Size[0], Size[1]);
			}
			const TSharedPtr<FJsonObject>* Light = nullptr;
			if (Object->TryGetObjectField(TEXT("light"), Light))
			{
				Socket.LightType = NameField(*Light, TEXT("type"));
				(*Light)->TryGetNumberField(TEXT("kelvin"), Socket.LightKelvin);
				(*Light)->TryGetNumberField(TEXT("intensity_lm"), Socket.LightLumen);
				(*Light)->TryGetNumberField(TEXT("attenuation_cm"), Socket.LightAttenuationCm);
				(*Light)->TryGetNumberField(TEXT("source_size_cm"), Socket.LightSourceSizeCm);
			}
			const TSharedPtr<FJsonObject>* Props = nullptr;
			if (Object->TryGetObjectField(TEXT("props"), Props))
			{
				for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Props)->Values)
				{
					Socket.Props.Add(Pair.Key, Pair.Value.IsValid() ? Pair.Value->AsString() : FString());
				}
			}
			const FString* ManifestId = Socket.Props.Find(TEXT("manifest_id"));
			Socket.ManifestId = ManifestId ? FName(**ManifestId) : Socket.Id;

			if (Socket.Kind == FName(TEXT("station")) && !Socket.StationId.IsNone())
			{
				FVerseDeckStation& Entry = Stations.AddDefaulted_GetRef();
				Entry.Id = Socket.StationId;
				Entry.Kind = Socket.StationKind;
				Entry.Room = Socket.Room;
				Entry.Zone = Zone;
				Entry.Transform = Socket.Transform;
				for (const TPair<FString, FString>& Pair : Socket.Props)
				{
					FString Group;
					if (Pair.Key.Split(TEXT("sockets."), nullptr, &Group) && !Group.IsEmpty())
					{
						TArray<FString> Ids;
						Pair.Value.ParseIntoArray(Ids, TEXT(","));
						TArray<FName>& Names = Entry.Sockets.Add(FName(*Group));
						for (const FString& Id : Ids)
						{
							Names.Add(FName(*Id));
						}
					}
				}
			}
			Sockets.Add(MoveTemp(Socket));
		}
	}
	return true;
}

bool FVerseDeckManifest::Load(FName InDeck, const FString& PlacementsDir, FVerseDeckManifest& Out, FString& OutError)
{
	Out = FVerseDeckManifest();
	Out.Deck = InDeck;
	const FString Folder = FPaths::Combine(PlacementsDir, InDeck.ToString());
	TArray<FString> Files;
	IFileManager::Get().FindFiles(Files, *FPaths::Combine(Folder, TEXT("*.placement.json")), true, false);
	Files.Sort();
	int32 Loaded = 0;
	for (const FString& File : Files)
	{
		FString Text;
		const FString Path = FPaths::Combine(Folder, File);
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			UE_LOG(LogVerseDecks, Warning, TEXT("deck %s: cannot read %s"), *InDeck.ToString(), *Path);
			continue;
		}
		FString Error;
		if (!Out.AddPlacementJson(Text, Error))
		{
			UE_LOG(LogVerseDecks, Warning, TEXT("deck %s: %s: %s"), *InDeck.ToString(), *File, *Error);
			continue;
		}
		++Loaded;
	}
	if (Loaded == 0)
	{
		OutError = FString::Printf(TEXT("no placement file for deck '%s' in %s"), *InDeck.ToString(), *Folder);
		return false;
	}
	return true;
}

const FVerseDeckRoom* FVerseDeckManifest::FindRoom(FName Room) const
{
	return Rooms.FindByPredicate([Room](const FVerseDeckRoom& Entry) { return Entry.Id == Room; });
}

const FVerseDeckStation* FVerseDeckManifest::FindStation(FName Station) const
{
	return Stations.FindByPredicate([Station](const FVerseDeckStation& Entry) { return Entry.Id == Station; });
}

const FVerseDeckSocket* FVerseDeckManifest::FindSocket(FName Kind, FName ManifestId) const
{
	return Sockets.FindByPredicate([Kind, ManifestId](const FVerseDeckSocket& Entry)
		{
			return Entry.Kind == Kind && Entry.ManifestId == ManifestId;
		});
}

TArray<const FVerseDeckSocket*> FVerseDeckManifest::SocketsOfKind(FName Kind) const
{
	TArray<const FVerseDeckSocket*> Out;
	for (const FVerseDeckSocket& Socket : Sockets)
	{
		if (Socket.Kind == Kind)
		{
			Out.Add(&Socket);
		}
	}
	return Out;
}

TArray<FName> FVerseDeckManifest::RoomsAt(const FVector& FeetCm) const
{
	TArray<FName> Out;
	for (const FVerseDeckRoom& Room : Rooms)
	{
		if (Room.Contains(FeetCm))
		{
			Out.Add(Room.Id);
		}
	}
	return Out;
}

bool FVerseDeckManifest::ArrivalTransform(bool bByLift, FTransform& Out) const
{
	if (bByLift)
	{
		const FVerseDeckSocket* Lift = FindSocket(FName(TEXT("lift")), FName(TEXT("main")));
		if (Lift == nullptr)
		{
			const TArray<const FVerseDeckSocket*> Lifts = SocketsOfKind(FName(TEXT("lift")));
			Lift = Lifts.Num() > 0 ? Lifts[0] : nullptr;
		}
		if (Lift)
		{
			Out = Lift->Transform;
			return true;
		}
	}
	const FVerseDeckSocket* Spawn = FindSocket(FName(TEXT("spawn")), FName(TEXT("commander")));
	if (Spawn == nullptr)
	{
		const TArray<const FVerseDeckSocket*> Spawns = SocketsOfKind(FName(TEXT("spawn")));
		Spawn = Spawns.Num() > 0 ? Spawns[0] : nullptr;
	}
	if (Spawn)
	{
		Out = Spawn->Transform;
		return true;
	}
	return false;
}

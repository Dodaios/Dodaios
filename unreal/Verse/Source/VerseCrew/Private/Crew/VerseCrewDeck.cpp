#include "Crew/VerseCrewDeck.h"

#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

const FString& FVerseCrewSocket::Key() const
{
	// Built once: the planner asks for keys of every socket for every member.
	if (CachedKey.IsEmpty() || CachedKind != Kind || CachedId != Id)
	{
		CachedKey = FString::Printf(TEXT("%s:%s"), VerseCrew::SocketKindName(Kind), *Id);
		CachedKind = Kind;
		CachedId = Id;
	}
	return CachedKey;
}

const FVerseCrewSocket* FVerseCrewDeck::FindSocket(EVerseCrewSocketKind Kind, const FString& SocketId) const
{
	return Sockets.FindByPredicate([&](const FVerseCrewSocket& S) { return S.Kind == Kind && S.Id == SocketId; });
}

const FVerseCrewSocket* FVerseCrewDeck::FindByKey(const FString& Key) const
{
	FString KindText;
	FString SocketId;
	if (!Key.Split(TEXT(":"), &KindText, &SocketId))
	{
		return nullptr;
	}
	return FindSocket(VerseCrew::ParseSocketKind(KindText), SocketId);
}

const FVerseCrewSocket* FVerseCrewDeck::FirstOfKind(EVerseCrewSocketKind Kind) const
{
	return Sockets.FindByPredicate([&](const FVerseCrewSocket& S) { return S.Kind == Kind; });
}

const FVerseCrewSocket* FVerseCrewDeck::ArrivalSpawn() const
{
	const FVerseCrewSocket* Found = Sockets.FindByPredicate(
		[](const FVerseCrewSocket& S) { return S.Kind == EVerseCrewSocketKind::Spawn && S.Id.StartsWith(TEXT("arrival")); });
	return Found ? Found : FirstOfKind(EVerseCrewSocketKind::Spawn);
}

const FVerseCrewSocket* FVerseCrewDeck::Lift() const
{
	return FirstOfKind(EVerseCrewSocketKind::Lift);
}

namespace
{
	bool ReadVector(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field, FVector& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (!Object->TryGetArrayField(Field, Values) || Values->Num() != 3)
		{
			return false;
		}
		Out = FVector((*Values)[0]->AsNumber(), (*Values)[1]->AsNumber(), (*Values)[2]->AsNumber());
		return true;
	}
}

bool FVerseCrewDeck::AppendPlacementJson(const TSharedRef<FJsonObject>& Root, FString& OutError)
{
	if (Root->GetStringField(TEXT("schema")) != TEXT("verse.placement/1"))
	{
		OutError = TEXT("not a verse.placement/1 document");
		return false;
	}
	const FString DeckText = Root->GetStringField(TEXT("deck"));
	if (Id.IsNone())
	{
		Id = FName(*DeckText);
	}
	else if (Id != FName(*DeckText))
	{
		OutError = FString::Printf(TEXT("zone of deck %s appended to deck %s"), *DeckText, *Id.ToString());
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* SocketValues = nullptr;
	if (Root->TryGetArrayField(TEXT("sockets"), SocketValues))
	{
		for (const TSharedPtr<FJsonValue>& Value : *SocketValues)
		{
			const TSharedPtr<FJsonObject> Raw = Value->AsObject();
			if (!Raw.IsValid())
			{
				continue;
			}
			FVerseCrewSocket Socket;
			Socket.Id = Raw->GetStringField(TEXT("id"));
			Socket.Kind = VerseCrew::ParseSocketKind(Raw->GetStringField(TEXT("kind")));
			FVector Local;
			if (!ReadVector(Raw, TEXT("location"), Local))
			{
				OutError = FString::Printf(TEXT("socket %s has no location"), *Socket.Id);
				return false;
			}
			Socket.Location = Local + OriginCm;
			const TArray<TSharedPtr<FJsonValue>>* Quat = nullptr;
			if (Raw->TryGetArrayField(TEXT("rotation"), Quat) && Quat->Num() == 4)
			{
				const FQuat Q((*Quat)[0]->AsNumber(), (*Quat)[1]->AsNumber(), (*Quat)[2]->AsNumber(), (*Quat)[3]->AsNumber());
				Socket.HeadingDeg = static_cast<float>(Q.Rotator().Yaw);
			}
			Raw->TryGetStringField(TEXT("room"), Socket.Room);
			const TSharedPtr<FJsonObject>* Station = nullptr;
			if (Raw->TryGetObjectField(TEXT("station"), Station) && Station && Station->IsValid())
			{
				Socket.StationId = (*Station)->GetStringField(TEXT("id"));
				Socket.StationKind = (*Station)->GetStringField(TEXT("kind"));
			}
			VerseCrew::SocketGroup(Socket.Id, Socket.Group, Socket.Order);
			Sockets.Add(MoveTemp(Socket));
		}
	}
	const TArray<TSharedPtr<FJsonValue>>* RoomValues = nullptr;
	if (Root->TryGetArrayField(TEXT("rooms"), RoomValues))
	{
		for (const TSharedPtr<FJsonValue>& Value : *RoomValues)
		{
			const TSharedPtr<FJsonObject> Raw = Value->AsObject();
			if (!Raw.IsValid())
			{
				continue;
			}
			FVerseCrewRoom Room;
			Room.Id = Raw->GetStringField(TEXT("id"));
			Room.FloorZCm = static_cast<float>(Raw->GetNumberField(TEXT("z_cm")) + OriginCm.Z);
			Room.bMain = Raw->GetBoolField(TEXT("main"));
			const TArray<TSharedPtr<FJsonValue>>* Points = nullptr;
			if (Raw->TryGetArrayField(TEXT("polygon_cm"), Points))
			{
				for (const TSharedPtr<FJsonValue>& Point : *Points)
				{
					const TArray<TSharedPtr<FJsonValue>>& XY = Point->AsArray();
					if (XY.Num() == 2)
					{
						Room.PolygonCm.Add(FVector2D(XY[0]->AsNumber() + OriginCm.X, XY[1]->AsNumber() + OriginCm.Y));
					}
				}
			}
			Rooms.Add(MoveTemp(Room));
		}
	}
	return true;
}

bool FVerseCrewDeck::AppendPlacementFile(const FString& Path, FString& OutError)
{
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Path))
	{
		OutError = FString::Printf(TEXT("cannot read %s"), *Path);
		return false;
	}
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = FString::Printf(TEXT("%s is not JSON"), *Path);
		return false;
	}
	return AppendPlacementJson(Root.ToSharedRef(), OutError);
}

void FVerseCrewDeck::Finalize()
{
}

namespace VerseCrew
{
	void SocketGroup(const FString& SocketId, FString& OutGroup, int32& OutOrder)
	{
		const int32 Cut = SocketId.Find(TEXT("__"), ESearchCase::CaseSensitive, ESearchDir::FromEnd);
		if (Cut > 0)
		{
			const FString Tail = SocketId.Mid(Cut + 2);
			OutGroup = SocketId.Left(Cut);
			bool bDigits = !Tail.IsEmpty();
			for (const TCHAR C : Tail)
			{
				bDigits = bDigits && FChar::IsDigit(C);
			}
			OutOrder = bDigits ? FCString::Atoi(*Tail) : 0;
			return;
		}
		int32 Start = SocketId.Len();
		while (Start > 0 && FChar::IsDigit(SocketId[Start - 1]))
		{
			--Start;
		}
		if (Start == SocketId.Len())
		{
			OutGroup = SocketId;
			OutOrder = 0;
			return;
		}
		OutOrder = FCString::Atoi(*SocketId.Mid(Start));
		OutGroup = SocketId.Left(Start);
		if (OutGroup.EndsWith(TEXT("_")))
		{
			OutGroup.LeftChopInline(1);
		}
	}

	EVerseCrewSocketKind ParseSocketKind(const FString& Kind)
	{
		if (Kind == TEXT("screen")) return EVerseCrewSocketKind::Screen;
		if (Kind == TEXT("seat")) return EVerseCrewSocketKind::Seat;
		if (Kind == TEXT("stand")) return EVerseCrewSocketKind::Stand;
		if (Kind == TEXT("bunk")) return EVerseCrewSocketKind::Bunk;
		if (Kind == TEXT("waypoint")) return EVerseCrewSocketKind::Waypoint;
		if (Kind == TEXT("spawn")) return EVerseCrewSocketKind::Spawn;
		if (Kind == TEXT("lift")) return EVerseCrewSocketKind::Lift;
		if (Kind == TEXT("station")) return EVerseCrewSocketKind::Station;
		return EVerseCrewSocketKind::Other;
	}

	const TCHAR* SocketKindName(EVerseCrewSocketKind Kind)
	{
		switch (Kind)
		{
		case EVerseCrewSocketKind::Screen: return TEXT("screen");
		case EVerseCrewSocketKind::Seat: return TEXT("seat");
		case EVerseCrewSocketKind::Stand: return TEXT("stand");
		case EVerseCrewSocketKind::Bunk: return TEXT("bunk");
		case EVerseCrewSocketKind::Waypoint: return TEXT("waypoint");
		case EVerseCrewSocketKind::Spawn: return TEXT("spawn");
		case EVerseCrewSocketKind::Lift: return TEXT("lift");
		case EVerseCrewSocketKind::Station: return TEXT("station");
		default: return TEXT("other");
		}
	}

	FString FixtureDeckDir()
	{
		return FPaths::ConvertRelativePathToFull(FPaths::ProjectContentDir() / TEXT("Verse/Test/WP15/Decks"));
	}

	bool LoadFixtureDeck(FName DeckId, const FVector& OriginCm, FVerseCrewDeck& Out, FString& OutError)
	{
		Out = FVerseCrewDeck();
		Out.Id = DeckId;
		Out.OriginCm = OriginCm;
		const FString Path = FixtureDeckDir() / (DeckId.ToString() + TEXT(".placement.json"));
		if (!Out.AppendPlacementFile(Path, OutError))
		{
			return false;
		}
		Out.Finalize();
		return true;
	}
}

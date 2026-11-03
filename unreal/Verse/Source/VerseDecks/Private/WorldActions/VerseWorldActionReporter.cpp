#include "WorldActions/VerseWorldActionReporter.h"

#include "Decks/VerseDeckManifest.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

void FVerseWorldActionReporter::Emit(const FString& Action, const FString& Ref)
{
	if (Sink)
	{
		Sink(FVerseWorldAction{ Action, Ref });
	}
}

void FVerseWorldActionReporter::NotifyVisible()
{
	if (bVisitReported)
	{
		return;
	}
	bVisitReported = true;
	Emit(TEXT("daily_visit"), FString());
}

void FVerseWorldActionReporter::NotifyArrived(FName Deck)
{
	if (Deck.IsNone())
	{
		return;
	}
	// Each visit starts a new tour, as today's effect re-runs (and drops its visited set) on every
	// deck change: `inspection` needs every room within one visit (A12.5).
	Visited.Remove(Deck);
	if (Discovered.Contains(Deck))
	{
		return;
	}
	Discovered.Add(Deck);
	Emit(TEXT("deck_discovered"), Deck.ToString());
}

void FVerseWorldActionReporter::NotifyPosition(const FVerseDeckManifest& Deck, const FVector& FeetCm, const FString& Day)
{
	if (Deck.Rooms.Num() == 0)
	{
		return;
	}
	TSet<FName>& Seen = Visited.FindOrAdd(Deck.Deck);
	for (const FName Room : Deck.RoomsAt(FeetCm))
	{
		Seen.Add(Room);
	}
	const FString Key = Deck.Deck.ToString() + TEXT(":") + Day;
	if (Inspected.Contains(Key))
	{
		return;
	}
	for (const FVerseDeckRoom& Room : Deck.Rooms)
	{
		if (!Seen.Contains(Room.Id))
		{
			return;
		}
	}
	Inspected.Add(Key);
	Emit(TEXT("inspection"), Deck.Deck.ToString());
}

TArray<FName> FVerseWorldActionReporter::VisitedRooms(FName Deck) const
{
	TArray<FName> Out;
	if (const TSet<FName>* Seen = Visited.Find(Deck))
	{
		Out = Seen->Array();
	}
	Out.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });
	return Out;
}

FString FVerseWorldActionReporter::ToBridgeJson(const FVerseWorldAction& Action, const FString& Id, double Ts)
{
	const TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("action"), Action.Action);
	Data->SetStringField(TEXT("ref"), Action.Ref);
	const TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("type"), TEXT("progression.action"));
	Root->SetStringField(TEXT("id"), Id);
	Root->SetNumberField(TEXT("ts"), Ts);
	Root->SetObjectField(TEXT("data"), Data);
	FString Out;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
	FJsonSerializer::Serialize(Root, Writer);
	return Out;
}

#include "Balance/VerseHarnessScenario.h"

#include "Dom/JsonObject.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace VerseHarnessScenarioPrivate
{
	bool ParseSlot(const TSharedPtr<FJsonObject>& Obj, FVerseHarnessSlot& Out, FString& OutError)
	{
		if (!Obj.IsValid())
		{
			OutError = TEXT("slot is not an object");
			return false;
		}
		const FString Kind = Obj->GetStringField(TEXT("kind"));
		if (Kind == TEXT("bot"))
		{
			Out.Kind = EVerseHarnessSlotKind::Bot;
		}
		else if (Kind == TEXT("model"))
		{
			Out.Kind = EVerseHarnessSlotKind::Model;
		}
		else
		{
			OutError = FString::Printf(TEXT("unknown slot kind '%s'"), *Kind);
			return false;
		}
		FString Text;
		if (Obj->TryGetStringField(TEXT("tier"), Text))
		{
			Out.Tier = FName(*Text);
		}
		if (Obj->TryGetStringField(TEXT("model"), Text))
		{
			Out.Model = FName(*Text);
		}
		if (Obj->TryGetStringField(TEXT("trick"), Text))
		{
			Out.Trick = FName(*Text);
		}
		Obj->TryGetBoolField(TEXT("learning"), Out.bLearning);
		if (Out.IsBot() && Out.Tier.IsNone())
		{
			OutError = TEXT("a bot slot needs a tier");
			return false;
		}
		if (!Out.IsBot() && Out.Model.IsNone() && Out.Tier.IsNone())
		{
			OutError = TEXT("a model slot needs a model or a base tier");
			return false;
		}
		return true;
	}
}

FString FVerseHarnessSlot::Label() const
{
	if (IsBot())
	{
		return bLearning ? Tier.ToString() : Tier.ToString() + TEXT("-nolearn");
	}
	if (!Trick.IsNone())
	{
		return Model.IsNone() ? Trick.ToString() : Model.ToString() + TEXT("+") + Trick.ToString();
	}
	return Model.IsNone() ? Tier.ToString() : Model.ToString();
}

bool FVerseHarnessScenario::Parse(const FString& JsonText, FVerseHarnessScenario& Out, FString& OutError)
{
	using namespace VerseHarnessScenarioPrivate;

	TSharedPtr<FJsonObject> Root;
	if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JsonText), Root) || !Root.IsValid())
	{
		OutError = TEXT("not a JSON object");
		return false;
	}
	if (Root->GetStringField(TEXT("schema")) != TEXT("verse.scenario/1"))
	{
		OutError = TEXT("schema is not verse.scenario/1");
		return false;
	}
	Out = FVerseHarnessScenario();
	Out.Run = Root->GetStringField(TEXT("run"));
	Out.Map = Root->GetStringField(TEXT("map"));
	Out.OutputDir = Root->GetStringField(TEXT("output"));
	Root->TryGetNumberField(TEXT("job"), Out.Job);
	Root->TryGetNumberField(TEXT("maxWallS"), Out.MaxWallS);
	const TSharedPtr<FJsonObject>* Trace = nullptr;
	if (Root->TryGetObjectField(TEXT("trace"), Trace))
	{
		(*Trace)->TryGetBoolField(TEXT("bearing"), Out.bTraceBearing);
		(*Trace)->TryGetBoolField(TEXT("fireAudit"), Out.bTraceFireAudit);
	}
	if (Out.Run.IsEmpty() || Out.OutputDir.IsEmpty() || Out.Map.IsEmpty())
	{
		OutError = TEXT("run, map and output are required");
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* Units = nullptr;
	if (!Root->TryGetArrayField(TEXT("units"), Units) || Units->Num() == 0)
	{
		OutError = TEXT("units must be a non-empty array");
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Units)
	{
		const TSharedPtr<FJsonObject> U = Value->AsObject();
		if (!U.IsValid())
		{
			OutError = TEXT("a unit is not an object");
			return false;
		}
		FVerseHarnessUnit Unit;
		Unit.Pairing = U->GetStringField(TEXT("pairing"));
		U->TryGetStringField(TEXT("set"), Unit.Set);
		U->TryGetNumberField(TEXT("match"), Unit.Match);
		double Seed = 0.0;
		U->TryGetNumberField(TEXT("seed"), Seed);
		Unit.Seed = uint32(FMath::Clamp(Seed, 0.0, 4294967295.0));
		U->TryGetNumberField(TEXT("bouts"), Unit.Bouts);
		U->TryGetNumberField(TEXT("killsToWin"), Unit.KillsToWin);
		U->TryGetNumberField(TEXT("matchTimeLimitS"), Unit.MatchTimeLimitS);
		FString Scenario;
		if (U->TryGetStringField(TEXT("scenario"), Scenario))
		{
			Unit.Scenario = FName(*Scenario);
		}
		const TSharedPtr<FJsonObject>* Patch = nullptr;
		if (U->TryGetObjectField(TEXT("tierPatch"), Patch))
		{
			const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Unit.TierPatchJson);
			FJsonSerializer::Serialize(Patch->ToSharedRef(), Writer);
		}
		const TSharedPtr<FJsonObject>* SlotA = nullptr;
		const TSharedPtr<FJsonObject>* SlotB = nullptr;
		if (!U->TryGetObjectField(TEXT("a"), SlotA) || !U->TryGetObjectField(TEXT("b"), SlotB))
		{
			OutError = FString::Printf(TEXT("unit %s needs slots a and b"), *Unit.Pairing);
			return false;
		}
		if (!ParseSlot(*SlotA, Unit.A, OutError) || !ParseSlot(*SlotB, Unit.B, OutError))
		{
			OutError = FString::Printf(TEXT("unit %s: %s"), *Unit.Pairing, *OutError);
			return false;
		}
		if (Unit.Pairing.IsEmpty() || Unit.Bouts < 1 || Unit.KillsToWin < 1 || Unit.MatchTimeLimitS <= 0.0)
		{
			OutError = FString::Printf(TEXT("unit %s has an empty id, no bouts or no limits"), *Unit.Pairing);
			return false;
		}
		Out.Units.Add(MoveTemp(Unit));
	}
	return true;
}

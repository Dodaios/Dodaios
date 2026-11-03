#include "Balance/VerseHarnessScenario.h"

#include "VerseHarnessJson.h"

namespace VerseHarnessScenarioPrivate
{
	bool ParseSlot(const FVerseJson* Obj, FVerseHarnessSlot& Out, FString& OutError)
	{
		if (!Obj || !Obj->IsObject())
		{
			OutError = TEXT("slot is not an object");
			return false;
		}
		const FString Kind = Obj->StringOr(TEXT("kind"));
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
		if (Obj->TryString(TEXT("tier"), Text))
		{
			Out.Tier = FName(*Text);
		}
		if (Obj->TryString(TEXT("model"), Text))
		{
			Out.Model = FName(*Text);
		}
		if (Obj->TryString(TEXT("trick"), Text))
		{
			Out.Trick = FName(*Text);
		}
		Obj->TryBool(TEXT("learning"), Out.bLearning);
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

	const TSharedPtr<FVerseJson> Root = FVerseJson::Parse(JsonText, OutError);
	if (!Root.IsValid() || !Root->IsObject())
	{
		OutError = TEXT("not a JSON object: ") + OutError;
		return false;
	}
	if (Root->StringOr(TEXT("schema")) != TEXT("verse.scenario/1"))
	{
		OutError = TEXT("schema is not verse.scenario/1");
		return false;
	}
	Out = FVerseHarnessScenario();
	Out.Run = Root->StringOr(TEXT("run"));
	Out.Map = Root->StringOr(TEXT("map"));
	Out.OutputDir = Root->StringOr(TEXT("output"));
	Root->TryInt(TEXT("job"), Out.Job);
	Root->TryNumber(TEXT("maxWallS"), Out.MaxWallS);
	if (const FVerseJson* Trace = Root->ObjectField(TEXT("trace")))
	{
		Trace->TryBool(TEXT("bearing"), Out.bTraceBearing);
		Trace->TryBool(TEXT("fireAudit"), Out.bTraceFireAudit);
	}
	if (Out.Run.IsEmpty() || Out.OutputDir.IsEmpty() || Out.Map.IsEmpty())
	{
		OutError = TEXT("run, map and output are required");
		return false;
	}
	const TArray<TSharedPtr<FVerseJson>>* Units = Root->ArrayField(TEXT("units"));
	if (!Units || Units->Num() == 0)
	{
		OutError = TEXT("units must be a non-empty array");
		return false;
	}
	for (const TSharedPtr<FVerseJson>& U : *Units)
	{
		if (!U.IsValid() || !U->IsObject())
		{
			OutError = TEXT("a unit is not an object");
			return false;
		}
		FVerseHarnessUnit Unit;
		Unit.Pairing = U->StringOr(TEXT("pairing"));
		U->TryString(TEXT("set"), Unit.Set);
		U->TryInt(TEXT("match"), Unit.Match);
		double Seed = 0.0;
		U->TryNumber(TEXT("seed"), Seed);
		Unit.Seed = uint32(FMath::Clamp(Seed, 0.0, 4294967295.0));
		U->TryInt(TEXT("bouts"), Unit.Bouts);
		U->TryInt(TEXT("killsToWin"), Unit.KillsToWin);
		U->TryNumber(TEXT("matchTimeLimitS"), Unit.MatchTimeLimitS);
		FString Scenario;
		if (U->TryString(TEXT("scenario"), Scenario))
		{
			Unit.Scenario = FName(*Scenario);
		}
		if (const FVerseJson* Patch = U->ObjectField(TEXT("tierPatch")))
		{
			Unit.TierPatchJson = Patch->ToString();
		}
		if (!ParseSlot(U->Find(TEXT("a")), Unit.A, OutError) || !ParseSlot(U->Find(TEXT("b")), Unit.B, OutError))
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

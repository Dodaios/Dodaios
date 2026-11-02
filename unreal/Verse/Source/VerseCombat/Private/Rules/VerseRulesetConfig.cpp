#include "Rules/VerseRulesetConfig.h"

#include "Misc/Paths.h"
#include "Rules/VerseRuleset_Deathmatch.h"

namespace
{
	const TCHAR* RulesSchema = TEXT("verse.rules/1");

	/**
	 * The rules files are flat JSON: strings, numbers and one object of strings. VerseCombat
	 * has no Json module edge in the module DAG, so this small reader covers exactly that.
	 */
	struct FRulesValue
	{
		enum class EKind : uint8 { String, Number, Object, Other } Kind = EKind::Other;
		FString String;
		double Number = 0.0;
		TArray<TPair<FString, FString>> Object;  // string values only
	};

	struct FRulesReader
	{
		const FString& Text;
		int32 Pos = 0;
		FString Error;

		explicit FRulesReader(const FString& InText) : Text(InText) {}

		void Skip()
		{
			while (Pos < Text.Len() && FChar::IsWhitespace(Text[Pos]))
			{
				++Pos;
			}
		}

		bool Eat(TCHAR C)
		{
			Skip();
			if (Pos < Text.Len() && Text[Pos] == C)
			{
				++Pos;
				return true;
			}
			return false;
		}

		bool ReadString(FString& Out)
		{
			if (!Eat(TEXT('"')))
			{
				Error = TEXT("string expected");
				return false;
			}
			Out.Reset();
			while (Pos < Text.Len() && Text[Pos] != TEXT('"'))
			{
				if (Text[Pos] == TEXT('\\') && Pos + 1 < Text.Len())
				{
					++Pos;
				}
				Out.AppendChar(Text[Pos++]);
			}
			if (Pos >= Text.Len())
			{
				Error = TEXT("unterminated string");
				return false;
			}
			++Pos;
			return true;
		}

		bool ReadValue(FRulesValue& Out, bool bAllowObject)
		{
			Skip();
			if (Pos >= Text.Len())
			{
				Error = TEXT("value expected");
				return false;
			}
			const TCHAR C = Text[Pos];
			if (C == TEXT('"'))
			{
				Out.Kind = FRulesValue::EKind::String;
				return ReadString(Out.String);
			}
			if (C == TEXT('{') && bAllowObject)
			{
				++Pos;
				Out.Kind = FRulesValue::EKind::Object;
				if (Eat(TEXT('}')))
				{
					return true;
				}
				do
				{
					FString Key;
					FRulesValue Inner;
					if (!ReadString(Key) || !Eat(TEXT(':')) || !ReadValue(Inner, false))
					{
						Error = Error.IsEmpty() ? TEXT("bad object") : Error;
						return false;
					}
					if (Inner.Kind != FRulesValue::EKind::String)
					{
						Error = FString::Printf(TEXT("%s: a string"), *Key);
						return false;
					}
					Out.Object.Emplace(Key, Inner.String);
				} while (Eat(TEXT(',')));
				if (!Eat(TEXT('}')))
				{
					Error = TEXT("} expected");
					return false;
				}
				return true;
			}
			const int32 Start = Pos;
			while (Pos < Text.Len() && (FChar::IsDigit(Text[Pos]) || Text[Pos] == TEXT('-') || Text[Pos] == TEXT('+')
				|| Text[Pos] == TEXT('.') || Text[Pos] == TEXT('e') || Text[Pos] == TEXT('E')))
			{
				++Pos;
			}
			if (Pos == Start)
			{
				Error = TEXT("unsupported value (strings, numbers and one object of strings only)");
				return false;
			}
			Out.Kind = FRulesValue::EKind::Number;
			Out.Number = FCString::Atod(*Text.Mid(Start, Pos - Start));
			return true;
		}

		bool ReadRoot(TMap<FString, FRulesValue>& Out)
		{
			if (!Eat(TEXT('{')))
			{
				Error = TEXT("not valid JSON");
				return false;
			}
			if (!Eat(TEXT('}')))
			{
				do
				{
					FString Key;
					FRulesValue Value;
					if (!ReadString(Key) || !Eat(TEXT(':')) || !ReadValue(Value, true))
					{
						Error = Error.IsEmpty() ? TEXT("not valid JSON") : Error;
						return false;
					}
					Out.Add(Key, MoveTemp(Value));
				} while (Eat(TEXT(',')));
				if (!Eat(TEXT('}')))
				{
					Error = TEXT("not valid JSON");
					return false;
				}
			}
			Skip();
			if (Pos != Text.Len())
			{
				Error = TEXT("trailing text");
				return false;
			}
			return true;
		}
	};
}

FString UVerseRulesetConfig::RulesFilePath(const FString& Name)
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("rules"), Name + TEXT(".json"));
}

bool UVerseRulesetConfig::ApplyJson(const FString& Text, FString& OutError)
{
	TMap<FString, FRulesValue> Root;
	FRulesReader Reader(Text);
	if (!Reader.ReadRoot(Root))
	{
		OutError = Reader.Error;
		return false;
	}
	const FRulesValue* Schema = Root.Find(TEXT("schema"));
	if (!Schema || Schema->Kind != FRulesValue::EKind::String || Schema->String != RulesSchema)
	{
		OutError = FString::Printf(TEXT("schema must be %s"), RulesSchema);
		return false;
	}
	static const TSet<FString> Known = {
		TEXT("schema"), TEXT("ruleset"), TEXT("respawn_delay_s"), TEXT("spawn_protection_max_s"),
		TEXT("kills_per_set"), TEXT("health_regen_per_s"), TEXT("max_armor"), TEXT("loadout"), TEXT("notes")};
	for (const TPair<FString, FRulesValue>& Pair : Root)
	{
		if (!Known.Contains(Pair.Key))
		{
			OutError = FString::Printf(TEXT("unknown key %s"), *Pair.Key);
			return false;
		}
	}
	if (const FRulesValue* Ruleset = Root.Find(TEXT("ruleset")))
	{
		if (Ruleset->String != UVerseRuleset_Deathmatch::RulesetId.ToString())
		{
			OutError = FString::Printf(TEXT("unknown ruleset %s"), *Ruleset->String);
			return false;
		}
		RulesetClass = UVerseRuleset_Deathmatch::StaticClass();
	}
	auto Number = [&Root](const TCHAR* Key, double& Out) {
		const FRulesValue* V = Root.Find(Key);
		if (V && V->Kind == FRulesValue::EKind::Number)
		{
			Out = V->Number;
			return true;
		}
		return false;
	};
	double Value = 0.0;
	if (Number(TEXT("respawn_delay_s"), Value))
	{
		RespawnDelay = float(Value);
	}
	if (Number(TEXT("spawn_protection_max_s"), Value))
	{
		SpawnProtectionMax = float(Value);
	}
	if (Number(TEXT("kills_per_set"), Value))
	{
		KillsPerSet = FMath::RoundToInt(Value);
	}
	if (Number(TEXT("health_regen_per_s"), Value))
	{
		HealthRegenPerSec = float(Value);
	}
	if (Number(TEXT("max_armor"), Value))
	{
		MaxArmor = float(Value);
	}
	if (const FRulesValue* LoadoutValue = Root.Find(TEXT("loadout")))
	{
		if (LoadoutValue->Kind != FRulesValue::EKind::Object)
		{
			OutError = TEXT("loadout must be an object");
			return false;
		}
		const UEnum* SlotEnum = StaticEnum<EVerseLoadoutSlot>();
		Loadout.Reset();
		for (const TPair<FString, FString>& Pair : LoadoutValue->Object)
		{
			const int64 Slot = SlotEnum->GetValueByNameString(Pair.Key);
			if (Slot == INDEX_NONE)
			{
				OutError = FString::Printf(TEXT("loadout: unknown slot %s"), *Pair.Key);
				return false;
			}
			if (!Pair.Value.StartsWith(TEXT("/Game/Verse/")))
			{
				OutError = FString::Printf(TEXT("loadout.%s: an object path under /Game/Verse/"), *Pair.Key);
				return false;
			}
			Loadout.Add(EVerseLoadoutSlot(Slot), TSoftObjectPtr<UPrimaryDataAsset>(FSoftObjectPath(Pair.Value)));
		}
	}
	if (RespawnDelay <= 0.f || SpawnProtectionMax < 0.f || KillsPerSet < 1 || MaxArmor < 0.f)
	{
		OutError = TEXT("respawn_delay_s > 0, spawn_protection_max_s >= 0, kills_per_set >= 1, max_armor >= 0");
		return false;
	}
	return true;
}

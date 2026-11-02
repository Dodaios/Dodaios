#include "Rules/VerseRulesetConfig.h"

#include "Dom/JsonObject.h"
#include "Misc/Paths.h"
#include "Rules/VerseRuleset_Deathmatch.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	const TCHAR* RulesSchema = TEXT("verse.rules/1");
}

FString UVerseRulesetConfig::RulesFilePath(const FString& Name)
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("rules"), Name + TEXT(".json"));
}

bool UVerseRulesetConfig::ApplyJson(const FString& Text, FString& OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		OutError = TEXT("not valid JSON");
		return false;
	}
	FString Schema;
	if (!Root->TryGetStringField(TEXT("schema"), Schema) || Schema != RulesSchema)
	{
		OutError = FString::Printf(TEXT("schema must be %s"), RulesSchema);
		return false;
	}
	static const TSet<FString> Known = {
		TEXT("schema"), TEXT("ruleset"), TEXT("respawn_delay_s"), TEXT("spawn_protection_max_s"),
		TEXT("kills_per_set"), TEXT("health_regen_per_s"), TEXT("max_armor"), TEXT("loadout"), TEXT("notes")};
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : Root->Values)
	{
		if (!Known.Contains(Pair.Key))
		{
			OutError = FString::Printf(TEXT("unknown key %s"), *Pair.Key);
			return false;
		}
	}
	FString Ruleset;
	if (Root->TryGetStringField(TEXT("ruleset"), Ruleset))
	{
		if (Ruleset != UVerseRuleset_Deathmatch::RulesetId.ToString())
		{
			OutError = FString::Printf(TEXT("unknown ruleset %s"), *Ruleset);
			return false;
		}
		RulesetClass = UVerseRuleset_Deathmatch::StaticClass();
	}
	double Number = 0.0;
	if (Root->TryGetNumberField(TEXT("respawn_delay_s"), Number))
	{
		RespawnDelay = float(Number);
	}
	if (Root->TryGetNumberField(TEXT("spawn_protection_max_s"), Number))
	{
		SpawnProtectionMax = float(Number);
	}
	if (Root->TryGetNumberField(TEXT("kills_per_set"), Number))
	{
		KillsPerSet = FMath::RoundToInt(Number);
	}
	if (Root->TryGetNumberField(TEXT("health_regen_per_s"), Number))
	{
		HealthRegenPerSec = float(Number);
	}
	if (Root->TryGetNumberField(TEXT("max_armor"), Number))
	{
		MaxArmor = float(Number);
	}
	const TSharedPtr<FJsonObject>* LoadoutObject = nullptr;
	if (Root->TryGetObjectField(TEXT("loadout"), LoadoutObject))
	{
		const UEnum* SlotEnum = StaticEnum<EVerseLoadoutSlot>();
		Loadout.Reset();
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*LoadoutObject)->Values)
		{
			const int64 Value = SlotEnum->GetValueByNameString(Pair.Key);
			if (Value == INDEX_NONE)
			{
				OutError = FString::Printf(TEXT("loadout: unknown slot %s"), *Pair.Key);
				return false;
			}
			FString Path;
			if (!Pair.Value->TryGetString(Path) || !Path.StartsWith(TEXT("/Game/Verse/")))
			{
				OutError = FString::Printf(TEXT("loadout.%s: an object path under /Game/Verse/"), *Pair.Key);
				return false;
			}
			Loadout.Add(EVerseLoadoutSlot(Value), TSoftObjectPtr<UPrimaryDataAsset>(FSoftObjectPath(Path)));
		}
	}
	if (RespawnDelay <= 0.f || SpawnProtectionMax < 0.f || KillsPerSet < 1 || MaxArmor < 0.f)
	{
		OutError = TEXT("respawn_delay_s > 0, spawn_protection_max_s >= 0, kills_per_set >= 1, max_armor >= 0");
		return false;
	}
	return true;
}

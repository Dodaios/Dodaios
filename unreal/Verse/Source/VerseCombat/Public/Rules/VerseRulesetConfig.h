#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseRulesetConfig.generated.h"

class AController;
class APawn;
class UVerseRuleset;

/** What a player did; offensive actions end spawn protection (combat-state.md 9.3, 10). */
UENUM()
enum class EVersePlayerAction : uint8
{
	Fire,
	Melee,
	Gadget,
	Reload,
	Ads,
	SwitchSlot
};

/** The question "may this damage land" (combat-state.md 10, CanDamage / ModifyDamage). */
USTRUCT()
struct VERSECOMBAT_API FVerseDamageContext
{
	GENERATED_BODY()

	UPROPERTY()
	TObjectPtr<AController> Instigator = nullptr;

	UPROPERTY()
	TObjectPtr<APawn> Victim = nullptr;

	UPROPERTY()
	EVerseDamageSource Source = EVerseDamageSource::Bolt;

	UPROPERTY()
	EVerseHitZone Zone = EVerseHitZone::None;
};

/**
 * One game mode's rules as data (combat-state.md 10, 11.2). Deathmatch reads its start values
 * from unreal/Verse/Data/rules/deathmatch.json (ApplyJson); the balance harness owns them.
 */
UCLASS(BlueprintType)
class VERSECOMBAT_API UVerseRulesetConfig : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	TSubclassOf<UVerseRuleset> RulesetClass;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules", meta = (Units = "s"))
	float RespawnDelay = 3.f;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules", meta = (Units = "s"))
	float SpawnProtectionMax = 2.f;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	int32 KillsPerSet = 10;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	float HealthRegenPerSec = 0.f;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	float MaxArmor = 0.f;

	UPROPERTY(EditDefaultsOnly, Category = "Verse|Rules")
	TMap<EVerseLoadoutSlot, TSoftObjectPtr<UPrimaryDataAsset>> Loadout;

	/**
	 * Reads the `verse.rules/1` text surface (unreal/Verse/Data/rules/<mode>.json) into this
	 * config. Unknown keys are errors, so a renamed field never silently keeps its old value.
	 */
	bool ApplyJson(const FString& Text, FString& OutError);

	/** Project path of a rules file: <project>/Data/rules/<Name>.json. */
	static FString RulesFilePath(const FString& Name);
};

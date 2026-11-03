#pragma once

#include "CoreMinimal.h"

class FJsonObject;
class UVerseGadgetDefinition;
class UVerseWeaponDefinition;

/**
 * The text surface of the weapon and gadget definitions (WP02.1, combat-state.md 2.3, 3):
 * unreal/Verse/Data/weapons/<weapon_id>.json (one weapon) and gadgets.json (every gadget). Keys
 * are the UPROPERTY names of the definition classes, every field is required and unknown keys are
 * errors, so a JSON file and its DA_Weapon_* / DA_Gadget_* asset are always field-for-field equal.
 *
 * Value forms: numbers, booleans and names as JSON scalars; FText and FGameplayTag as strings; enums
 * by entry name ("Primary", "Auto"); FVector2f as [x, y]; FVector3f as [x, y, z]; FRuntimeFloatCurve
 * as [[x, y], ...] with linear keys; maps keyed by enum entry name.
 */
struct VERSECOMBAT_API FVerseDefinitionJson
{
	/** Schema tag every weapon file carries in "$schema". */
	static const TCHAR* WeaponSchema;
	/** Schema tag of gadgets.json. */
	static const TCHAR* GadgetsSchema;

	/** unreal/Verse/Data/weapons/ */
	static FString DataDir();

	/** Fills Out from a weapon object; false with Errors on any missing, unknown or malformed field. */
	static bool ApplyWeapon(const FJsonObject& Json, UVerseWeaponDefinition& Out, TArray<FString>& Errors);
	static bool ApplyWeaponText(const FString& Text, UVerseWeaponDefinition& Out, TArray<FString>& Errors);

	/** The canonical JSON object of a weapon (what the file holds). */
	static TSharedRef<FJsonObject> ExportWeapon(const UVerseWeaponDefinition& W);
	static FString ExportWeaponText(const UVerseWeaponDefinition& W);

	static bool ApplyGadget(const FJsonObject& Json, UVerseGadgetDefinition& Out, TArray<FString>& Errors);
	static TSharedRef<FJsonObject> ExportGadget(const UVerseGadgetDefinition& G);

	/** gadgets.json: { "$schema": ..., "gadgets": [ {...}, ... ] } */
	static bool LoadGadgetsText(const FString& Text, UObject* Outer, TArray<UVerseGadgetDefinition*>& Out, TArray<FString>& Errors);

	/** Names: ids lower_snake_case ASCII, display names letters, digits, spaces and hyphens only. */
	static bool CheckNames(const FName& Id, const FText& DisplayName, TArray<FString>& Errors);

	/** Every weapon file of DataDir() (all *.json except gadgets.json), each into a new transient definition. */
	static TArray<UVerseWeaponDefinition*> LoadAllWeapons(UObject* Outer, TArray<FString>& Errors);

	/** Field-for-field comparison of two JSON values (numbers within Tolerance); appends the differing paths. */
	static bool JsonEqual(const TSharedPtr<class FJsonValue>& A, const TSharedPtr<class FJsonValue>& B, const FString& Path,
		TArray<FString>& Diffs, double Tolerance = 1e-5);

	/** Asset name of a weapon or gadget id: graveline -> DA_Weapon_Graveline, breach_charge -> DA_Gadget_BreachCharge. */
	static FString WeaponAssetName(const FName& WeaponId);
	static FString GadgetAssetName(const FName& GadgetId);

	/** Content folder of the definition assets. */
	static const TCHAR* AssetFolder;
};

#pragma once

#include "CoreMinimal.h"

class UVerseGadgetDefinition;
class UVerseWeaponDefinition;

/**
 * Finds weapon and gadget definitions by id: the DA_Weapon_* / DA_Gadget_* asset under
 * FVerseDefinitionJson::AssetFolder when it exists, else the definition imported from the JSON in
 * Data/weapons (kept alive for the process). Game thread only.
 */
struct VERSECOMBAT_API FVerseWeaponRegistry
{
	static const UVerseWeaponDefinition* FindWeapon(FName WeaponId);
	static const UVerseGadgetDefinition* FindGadget(FName GadgetId);

	/** The definition saved as an asset, or nullptr. */
	static const UVerseWeaponDefinition* LoadWeaponAsset(FName WeaponId);
	static const UVerseGadgetDefinition* LoadGadgetAsset(FName GadgetId);

	/** Drops the JSON cache (tests). */
	static void ResetCache();
};

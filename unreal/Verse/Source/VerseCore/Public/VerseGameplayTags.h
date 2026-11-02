#pragma once

#include "CoreMinimal.h"
#include "NativeGameplayTags.h"

// Native gameplay tags frozen by the contracts. Noise.*: bot.md 3.2 (one tag per FVerseNoiseEvent,
// the DA_Audibility row key). Bot.State.*: one per decision state of bot.md 5.1.
// Verse.Material.<id>: the penetration table materials of destruction.md 2, in wire order.

namespace VerseTags
{
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Shot);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Footstep_Sprint);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Footstep_Run);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Footstep_Walk);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Move_Slide);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Move_Land);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Move_Mantle);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Reload);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Gadget_BulwarkDeploy);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Gadget_BulwarkHum);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Gadget_BreachPlant);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Gadget_BreachDetonate);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Fracture);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Drone);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Melee);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Finisher);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Noise_Impact);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Attack);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Hold);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Flank);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_StalkForFinisher);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Retreat);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Reload);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_DeployBulwark);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Breach);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Wallbang);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Bot_State_Search);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_SheetMetal);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_ContainerWall);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_Glass);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_CladdingPanel);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_CatwalkGrating);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_CeilingPanel);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_Concrete);
	VERSECORE_API UE_DECLARE_GAMEPLAY_TAG_EXTERN(Verse_Material_ArmorSteel);

	/** Every Noise.* tag of bot.md 3.2, in table order. */
	VERSECORE_API TConstArrayView<FGameplayTag> AllNoiseTags();

	/** Every Bot.State.* tag, in bot.md 5.1 order. */
	VERSECORE_API TConstArrayView<FGameplayTag> AllBotStateTags();

	/** Verse.Material.* tags indexed by wire id (EVersePenetrationMaterial). */
	VERSECORE_API TConstArrayView<FGameplayTag> AllMaterialTags();
}

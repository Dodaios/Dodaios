#include "VerseGameplayTags.h"

namespace VerseTags
{
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Shot, "Noise.Shot", "Weapon shot; audible in the whole arena (bot.md 3.2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Footstep_Sprint, "Noise.Footstep.Sprint", "Sprint footsteps, 20 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Footstep_Run, "Noise.Footstep.Run", "Run footsteps, 10 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Footstep_Walk, "Noise.Footstep.Walk", "Walk footsteps, 4 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Move_Slide, "Noise.Move.Slide", "Slide, 12 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Move_Land, "Noise.Move.Land", "Landing from a jump or drop, 12 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Move_Mantle, "Noise.Move.Mantle", "Mantle, 12 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Reload, "Noise.Reload", "Reload (tactical or empty), 7 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Gadget_BulwarkDeploy, "Noise.Gadget.BulwarkDeploy", "Bulwark deploy, 15 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Gadget_BulwarkHum, "Noise.Gadget.BulwarkHum", "Bulwark hum while active, 5 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Gadget_BreachPlant, "Noise.Gadget.BreachPlant", "Breach charge plant, 10 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Gadget_BreachDetonate, "Noise.Gadget.BreachDetonate", "Breach charge detonation; whole arena");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Fracture, "Noise.Fracture", "Piece fracture; range = loudness x 40 m (destruction.md 6.2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Drone, "Noise.Drone", "Repair drone flight and weld; loudness 0.15");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Melee, "Noise.Melee", "Knife strike or whiff, 8 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Finisher, "Noise.Finisher", "Finisher takedown, 8 m");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Noise_Impact, "Noise.Impact", "Bolt impact within 3 m of the listener; always heard");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Attack, "Bot.State.Attack", "Bot decision state Attack (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Hold, "Bot.State.Hold", "Bot decision state Hold (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Flank, "Bot.State.Flank", "Bot decision state Flank (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_StalkForFinisher, "Bot.State.StalkForFinisher", "Bot decision state StalkForFinisher (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Retreat, "Bot.State.Retreat", "Bot decision state Retreat (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Reload, "Bot.State.Reload", "Bot decision state Reload (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_DeployBulwark, "Bot.State.DeployBulwark", "Bot decision state DeployBulwark (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Breach, "Bot.State.Breach", "Bot decision state Breach (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Wallbang, "Bot.State.Wallbang", "Bot decision state Wallbang (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Bot_State_Search, "Bot.State.Search", "Bot decision state Search (bot.md 5.1)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_SheetMetal, "Verse.Material.sheet_metal", "Penetration table material sheet_metal (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_ContainerWall, "Verse.Material.container_wall", "Penetration table material container_wall (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_Glass, "Verse.Material.glass", "Penetration table material glass (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_CladdingPanel, "Verse.Material.cladding_panel", "Penetration table material cladding_panel (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_CatwalkGrating, "Verse.Material.catwalk_grating", "Penetration table material catwalk_grating (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_CeilingPanel, "Verse.Material.ceiling_panel", "Penetration table material ceiling_panel (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_Concrete, "Verse.Material.concrete", "Penetration table material concrete (destruction.md 2)");
	UE_DEFINE_GAMEPLAY_TAG_COMMENT(Verse_Material_ArmorSteel, "Verse.Material.armor_steel", "Penetration table material armor_steel (destruction.md 2)");

	TConstArrayView<FGameplayTag> AllNoiseTags()
	{
		static const TArray<FGameplayTag> Tags = {
			Noise_Shot,
			Noise_Footstep_Sprint,
			Noise_Footstep_Run,
			Noise_Footstep_Walk,
			Noise_Move_Slide,
			Noise_Move_Land,
			Noise_Move_Mantle,
			Noise_Reload,
			Noise_Gadget_BulwarkDeploy,
			Noise_Gadget_BulwarkHum,
			Noise_Gadget_BreachPlant,
			Noise_Gadget_BreachDetonate,
			Noise_Fracture,
			Noise_Drone,
			Noise_Melee,
			Noise_Finisher,
			Noise_Impact,
		};
		return Tags;
	}

	TConstArrayView<FGameplayTag> AllBotStateTags()
	{
		static const TArray<FGameplayTag> Tags = {
			Bot_State_Attack,
			Bot_State_Hold,
			Bot_State_Flank,
			Bot_State_StalkForFinisher,
			Bot_State_Retreat,
			Bot_State_Reload,
			Bot_State_DeployBulwark,
			Bot_State_Breach,
			Bot_State_Wallbang,
			Bot_State_Search,
		};
		return Tags;
	}

	TConstArrayView<FGameplayTag> AllMaterialTags()
	{
		static const TArray<FGameplayTag> Tags = {
			Verse_Material_SheetMetal,
			Verse_Material_ContainerWall,
			Verse_Material_Glass,
			Verse_Material_CladdingPanel,
			Verse_Material_CatwalkGrating,
			Verse_Material_CeilingPanel,
			Verse_Material_Concrete,
			Verse_Material_ArmorSteel,
		};
		return Tags;
	}
}

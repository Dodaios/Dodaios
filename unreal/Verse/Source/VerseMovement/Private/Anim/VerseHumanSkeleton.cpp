// Bone and clip tables of SKEL_Verse_Human. Kept in step with
// art/verse/characters/fps/skeleton.py, catalogue.py and grip_reference.json
// by tests/verse/test_unreal_characters.py (it parses the lists below).

#include "Anim/VerseHumanSkeleton.h"

namespace VerseHuman
{
TConstArrayView<TPair<FName, FName>> Bones()
{
	static const TArray<TPair<FName, FName>> Table = []()
	{
		TArray<TPair<FName, FName>> Out;
		auto B = [&Out](const TCHAR* Bone, const TCHAR* Parent)
		{ Out.Emplace(FName(Bone), Parent ? FName(Parent) : FName(NAME_None)); };
		// BONES-BEGIN
		B(TEXT("Root"), nullptr);
		B(TEXT("Hips"), TEXT("Root"));
		B(TEXT("Spine_01"), TEXT("Hips"));
		B(TEXT("Spine_02"), TEXT("Spine_01"));
		B(TEXT("Spine_03"), TEXT("Spine_02"));
		B(TEXT("Neck"), TEXT("Spine_03"));
		B(TEXT("Head"), TEXT("Neck"));
		B(TEXT("Camera"), TEXT("Head"));
		B(TEXT("Clavicle_L"), TEXT("Spine_03"));
		B(TEXT("UpperArm_L"), TEXT("Clavicle_L"));
		B(TEXT("UpperArm_Twist_L"), TEXT("UpperArm_L"));
		B(TEXT("LowerArm_L"), TEXT("UpperArm_L"));
		B(TEXT("LowerArm_Twist_L"), TEXT("LowerArm_L"));
		B(TEXT("Hand_L"), TEXT("LowerArm_L"));
		B(TEXT("Thumb_01_L"), TEXT("Hand_L"));
		B(TEXT("Thumb_02_L"), TEXT("Thumb_01_L"));
		B(TEXT("Thumb_03_L"), TEXT("Thumb_02_L"));
		B(TEXT("Index_01_L"), TEXT("Hand_L"));
		B(TEXT("Index_02_L"), TEXT("Index_01_L"));
		B(TEXT("Index_03_L"), TEXT("Index_02_L"));
		B(TEXT("Middle_01_L"), TEXT("Hand_L"));
		B(TEXT("Middle_02_L"), TEXT("Middle_01_L"));
		B(TEXT("Middle_03_L"), TEXT("Middle_02_L"));
		B(TEXT("Ring_01_L"), TEXT("Hand_L"));
		B(TEXT("Ring_02_L"), TEXT("Ring_01_L"));
		B(TEXT("Ring_03_L"), TEXT("Ring_02_L"));
		B(TEXT("Pinky_01_L"), TEXT("Hand_L"));
		B(TEXT("Pinky_02_L"), TEXT("Pinky_01_L"));
		B(TEXT("Pinky_03_L"), TEXT("Pinky_02_L"));
		B(TEXT("Weapon_L"), TEXT("Hand_L"));
		B(TEXT("Thigh_L"), TEXT("Hips"));
		B(TEXT("Thigh_Twist_L"), TEXT("Thigh_L"));
		B(TEXT("Calf_L"), TEXT("Thigh_L"));
		B(TEXT("Calf_Twist_L"), TEXT("Calf_L"));
		B(TEXT("Foot_L"), TEXT("Calf_L"));
		B(TEXT("Ball_L"), TEXT("Foot_L"));
		B(TEXT("Clavicle_R"), TEXT("Spine_03"));
		B(TEXT("UpperArm_R"), TEXT("Clavicle_R"));
		B(TEXT("UpperArm_Twist_R"), TEXT("UpperArm_R"));
		B(TEXT("LowerArm_R"), TEXT("UpperArm_R"));
		B(TEXT("LowerArm_Twist_R"), TEXT("LowerArm_R"));
		B(TEXT("Hand_R"), TEXT("LowerArm_R"));
		B(TEXT("Thumb_01_R"), TEXT("Hand_R"));
		B(TEXT("Thumb_02_R"), TEXT("Thumb_01_R"));
		B(TEXT("Thumb_03_R"), TEXT("Thumb_02_R"));
		B(TEXT("Index_01_R"), TEXT("Hand_R"));
		B(TEXT("Index_02_R"), TEXT("Index_01_R"));
		B(TEXT("Index_03_R"), TEXT("Index_02_R"));
		B(TEXT("Middle_01_R"), TEXT("Hand_R"));
		B(TEXT("Middle_02_R"), TEXT("Middle_01_R"));
		B(TEXT("Middle_03_R"), TEXT("Middle_02_R"));
		B(TEXT("Ring_01_R"), TEXT("Hand_R"));
		B(TEXT("Ring_02_R"), TEXT("Ring_01_R"));
		B(TEXT("Ring_03_R"), TEXT("Ring_02_R"));
		B(TEXT("Pinky_01_R"), TEXT("Hand_R"));
		B(TEXT("Pinky_02_R"), TEXT("Pinky_01_R"));
		B(TEXT("Pinky_03_R"), TEXT("Pinky_02_R"));
		B(TEXT("Weapon_R"), TEXT("Hand_R"));
		B(TEXT("Thigh_R"), TEXT("Hips"));
		B(TEXT("Thigh_Twist_R"), TEXT("Thigh_R"));
		B(TEXT("Calf_R"), TEXT("Thigh_R"));
		B(TEXT("Calf_Twist_R"), TEXT("Calf_R"));
		B(TEXT("Foot_R"), TEXT("Calf_R"));
		B(TEXT("Ball_R"), TEXT("Foot_R"));
		B(TEXT("IK_Foot_Root"), TEXT("Root"));
		B(TEXT("IK_Foot_L"), TEXT("IK_Foot_Root"));
		B(TEXT("IK_Foot_R"), TEXT("IK_Foot_Root"));
		B(TEXT("IK_Hand_Root"), TEXT("Root"));
		B(TEXT("IK_Hand_Gun"), TEXT("IK_Hand_Root"));
		B(TEXT("IK_Hand_L"), TEXT("IK_Hand_Gun"));
		B(TEXT("IK_Hand_R"), TEXT("IK_Hand_Gun"));
		// BONES-END
		return Out;
	}();
	return Table;
}

TConstArrayView<TPair<FName, FName>> OptionalBones()
{
	static const TArray<TPair<FName, FName>> Table = []()
	{
		TArray<TPair<FName, FName>> Out;
		auto B = [&Out](const TCHAR* Bone, const TCHAR* Parent) { Out.Emplace(FName(Bone), FName(Parent)); };
		// OPTIONAL-BONES-BEGIN
		B(TEXT("Cloak_R1"), TEXT("Spine_03"));
		B(TEXT("Cloak_R2"), TEXT("Cloak_R1"));
		B(TEXT("Cloak_C1"), TEXT("Spine_03"));
		B(TEXT("Cloak_C2"), TEXT("Cloak_C1"));
		B(TEXT("Cloak_L1"), TEXT("Spine_03"));
		B(TEXT("Cloak_L2"), TEXT("Cloak_L1"));
		// OPTIONAL-BONES-END
		return Out;
	}();
	return Table;
}

TConstArrayView<TPair<FName, float>> SpineShares()
{
	static const TArray<TPair<FName, float>> Table = []()
	{
		TArray<TPair<FName, float>> Out;
		auto S = [&Out](const TCHAR* Bone, float Share) { Out.Emplace(FName(Bone), Share); };
		S(TEXT("Spine_01"), 0.25f);
		S(TEXT("Spine_02"), 0.35f);
		S(TEXT("Spine_03"), 0.4f);
		return Out;
	}();
	return Table;
}

TConstArrayView<const TCHAR*> ClipNames()
{
	static const TCHAR* Table[] = {
		// CLIPS-BEGIN
		TEXT("A_Stand_Idle"),
		TEXT("A_Crouch_Idle"),
		TEXT("A_Prone_Idle"),
		TEXT("A_Stand_Move_F"),
		TEXT("A_Stand_Move_FL"),
		TEXT("A_Stand_Move_L"),
		TEXT("A_Stand_Move_BL"),
		TEXT("A_Stand_Move_B"),
		TEXT("A_Stand_Move_BR"),
		TEXT("A_Stand_Move_R"),
		TEXT("A_Stand_Move_FR"),
		TEXT("A_Crouch_Move_F"),
		TEXT("A_Crouch_Move_FL"),
		TEXT("A_Crouch_Move_L"),
		TEXT("A_Crouch_Move_BL"),
		TEXT("A_Crouch_Move_B"),
		TEXT("A_Crouch_Move_BR"),
		TEXT("A_Crouch_Move_R"),
		TEXT("A_Crouch_Move_FR"),
		TEXT("A_Prone_Move_F"),
		TEXT("A_Prone_Move_FL"),
		TEXT("A_Prone_Move_L"),
		TEXT("A_Prone_Move_BL"),
		TEXT("A_Prone_Move_B"),
		TEXT("A_Prone_Move_BR"),
		TEXT("A_Prone_Move_R"),
		TEXT("A_Prone_Move_FR"),
		TEXT("A_Sprint_F"),
		TEXT("A_Jump_Start"),
		TEXT("A_Fall_Loop"),
		TEXT("A_Land"),
		TEXT("A_Slide"),
		TEXT("A_Prone_Enter"),
		TEXT("A_Prone_Exit"),
		TEXT("A_Mantle_Low"),
		TEXT("A_Mantle_High"),
		TEXT("A_Stand_Lean_L"),
		TEXT("A_Stand_Lean_R"),
		TEXT("A_Crouch_Lean_L"),
		TEXT("A_Crouch_Lean_R"),
		TEXT("A_Rifle_Idle"),
		TEXT("A_Rifle_ADS"),
		TEXT("A_Rifle_Fire"),
		TEXT("A_Rifle_Reload_Tactical"),
		TEXT("A_Rifle_Reload_Empty"),
		TEXT("A_Rifle_Equip"),
		TEXT("A_Rifle_Holster"),
		TEXT("A_Pistol_Idle"),
		TEXT("A_Pistol_ADS"),
		TEXT("A_Pistol_Fire"),
		TEXT("A_Pistol_Reload_Tactical"),
		TEXT("A_Pistol_Reload_Empty"),
		TEXT("A_Pistol_Equip"),
		TEXT("A_Pistol_Holster"),
		TEXT("A_Knife_Idle"),
		TEXT("A_Knife_Strike"),
		TEXT("A_Knife_Equip"),
		TEXT("A_Knife_Holster"),
		TEXT("A_Finisher_Attacker"),
		TEXT("A_Finisher_Victim"),
		TEXT("A_Death_Front"),
		TEXT("A_Death_Back"),
		TEXT("A_Death_Left"),
		TEXT("A_Death_Right"),
		TEXT("A_Death_Head"),
		TEXT("A_Hit_Head"),
		TEXT("A_Hit_Torso_Front"),
		TEXT("A_Hit_Torso_Back"),
		TEXT("A_Hit_Arm_L"),
		TEXT("A_Hit_Arm_R"),
		TEXT("A_Hit_Leg_L"),
		TEXT("A_Hit_Leg_R"),
		TEXT("A_KillCam_Rifle_Fire"),
		TEXT("A_KillCam_Rifle_Run"),
		TEXT("A_KillCam_Pistol_Fire"),
		TEXT("A_Crew_Stand"),
		TEXT("A_Crew_Walk"),
		TEXT("A_Crew_Sit_Idle"),
		TEXT("A_Crew_Sit_Type"),
		TEXT("A_Crew_Stand_Type"),
		TEXT("A_Crew_Talk"),
		TEXT("A_Crew_Listen"),
		TEXT("A_Crew_Sit_Down"),
		TEXT("A_Crew_Stand_Up"),
		TEXT("A_Crew_Bunk"),
		// CLIPS-END
	};
	return MakeArrayView(Table);
}

FString ClipPath(const FString& Clip)
{
	FString Group = TEXT("Locomotion");
	if (Clip.StartsWith(TEXT("A_Rifle_")))
	{
		Group = TEXT("Weapons/Rifle");
	}
	else if (Clip.StartsWith(TEXT("A_Pistol_")))
	{
		Group = TEXT("Weapons/Pistol");
	}
	else if (Clip.StartsWith(TEXT("A_Knife_")))
	{
		Group = TEXT("Weapons/Knife");
	}
	else if (Clip.StartsWith(TEXT("A_Finisher_")))
	{
		Group = TEXT("Finisher");
	}
	else if (Clip.StartsWith(TEXT("A_Death_")) || Clip.StartsWith(TEXT("A_Hit_")) || Clip.StartsWith(TEXT("A_KillCam_")))
	{
		Group = TEXT("Reactions");
	}
	else if (Clip.StartsWith(TEXT("A_Crew_")))
	{
		Group = TEXT("Crew");
	}
	return FString::Printf(TEXT("/Game/Verse/Animations/%s/%s.%s"), *Group, *Clip, *Clip);
}

TConstArrayView<const TCHAR*> MeshPaths()
{
	static const TCHAR* Table[] = {
		// MESHES-BEGIN
		TEXT("/Game/Verse/Characters/Commander/SK_Commander_M.SK_Commander_M"),
		TEXT("/Game/Verse/Characters/Commander/SK_Commander_F.SK_Commander_F"),
		TEXT("/Game/Verse/Characters/Crew/SK_Crew_M.SK_Crew_M"),
		TEXT("/Game/Verse/Characters/Crew/SK_Crew_F.SK_Crew_F"),
		TEXT("/Game/Verse/Characters/Opponent/SK_Opponent_M.SK_Opponent_M"),
		TEXT("/Game/Verse/Characters/Opponent/SK_Opponent_F.SK_Opponent_F"),
		TEXT("/Game/Verse/Characters/Sovereign/SK_Sovereign.SK_Sovereign"),
		// MESHES-END
	};
	return MakeArrayView(Table);
}

TConstArrayView<TPair<FName, float>> FinisherMarkers()
{
	static const TArray<TPair<FName, float>> Table = []()
	{
		TArray<TPair<FName, float>> Out;
		auto M = [&Out](const TCHAR* Name, float Time) { Out.Emplace(FName(Name), Time); };
		M(TEXT("Takedown"), 0.25f);
		M(TEXT("Struggle"), 0.9f);
		M(TEXT("Kill"), 1.8f);
		M(TEXT("Recover"), 2.1f);
		M(TEXT("Release"), 2.5f);
		return Out;
	}();
	return Table;
}

FVector ReferenceSupport(bool bPistol)
{
	// GRIPS-BEGIN
	static const FVector Rifle(3.083f, 7.193f, 17.469f);
	static const FVector Pistol(4.624f, 0.0f, -4.932f);
	// GRIPS-END
	return bPistol ? Pistol : Rifle;
}
TConstArrayView<TPair<FName, EVerseHitZone>> HitBodies()
{
	static const TArray<TPair<FName, EVerseHitZone>> Table = []()
	{
		TArray<TPair<FName, EVerseHitZone>> Out;
		auto Z = [&Out](const TCHAR* Bone, EVerseHitZone Zone) { Out.Emplace(FName(Bone), Zone); };
		// HITZONES-BEGIN
		Z(TEXT("Hips"), EVerseHitZone::LowerTorso);
		Z(TEXT("Spine_01"), EVerseHitZone::LowerTorso);
		Z(TEXT("Spine_03"), EVerseHitZone::UpperTorso);
		Z(TEXT("Neck"), EVerseHitZone::Neck);
		Z(TEXT("Head"), EVerseHitZone::Head);
		Z(TEXT("UpperArm_L"), EVerseHitZone::Arm);
		Z(TEXT("UpperArm_R"), EVerseHitZone::Arm);
		Z(TEXT("LowerArm_L"), EVerseHitZone::Arm);
		Z(TEXT("LowerArm_R"), EVerseHitZone::Arm);
		Z(TEXT("Thigh_L"), EVerseHitZone::Leg);
		Z(TEXT("Thigh_R"), EVerseHitZone::Leg);
		Z(TEXT("Calf_L"), EVerseHitZone::Leg);
		Z(TEXT("Calf_R"), EVerseHitZone::Leg);
		// HITZONES-END
		return Out;
	}();
	return Table;
}

EVerseHitZone HitZoneForBone(FName Bone)
{
	static const TMap<FName, EVerseHitZone> Zones = []()
	{
		TMap<FName, EVerseHitZone> Out;
		for (const TPair<FName, EVerseHitZone>& Row : HitBodies())
		{
			Out.Add(Row.Key, Row.Value);
		}
		return Out;
	}();
	static const TMap<FName, FName> Parents = []()
	{
		TMap<FName, FName> Out;
		for (const TPair<FName, FName>& Row : Bones())
		{
			Out.Add(Row.Key, Row.Value);
		}
		return Out;
	}();
	for (FName Current = Bone; !Current.IsNone();)
	{
		if (const EVerseHitZone* Zone = Zones.Find(Current))
		{
			return *Zone;
		}
		const FName* Parent = Parents.Find(Current);
		Current = Parent ? *Parent : FName(NAME_None);
	}
	return EVerseHitZone::None;
}
} // namespace VerseHuman

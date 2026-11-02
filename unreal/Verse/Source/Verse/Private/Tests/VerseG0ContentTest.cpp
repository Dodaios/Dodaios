#include "Misc/AutomationTest.h"
#include "Misc/PackageName.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/WorldSettings.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "ReferenceSkeleton.h"
#include "WorldPartition/WorldPartition.h"
#include "WorldPartition/DataLayer/DataLayerAsset.h"

#if WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

// Verse.Content.Levels: the G0.8 deck maps exist as World Partition maps with One
// File Per Actor on, and every data layer asset of art-pipeline 3 is in place.
// scripts/unreal/g0_content.py regenerates them; its verify step also checks the
// data layer instances inside each world.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContentLevelsTest, "Verse.Content.Levels",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseContentLevelsTest::RunTest(const FString& Parameters)
{
	struct FDeck { const TCHAR* Name; TArray<const TCHAR*> Layers; };
	const FDeck Decks[] = {
		{ TEXT("Bridge"), { TEXT("DL_Bridge_Base") } },
		{ TEXT("Ops"), { TEXT("DL_Ops_Base") } },
		{ TEXT("Engineering"), { TEXT("DL_Engineering_Base") } },
		{ TEXT("Hangar"), { TEXT("DL_Hangar_Base"), TEXT("DL_Hangar_Day"), TEXT("DL_Hangar_Arena") } },
	};
	for (const FDeck& Deck : Decks)
	{
		const FString MapPath = FString::Printf(TEXT("/Game/Verse/Decks/%s/LV_%s"), Deck.Name, Deck.Name);
		if (!TestTrue(FString::Printf(TEXT("%s exists"), *MapPath), FPackageName::DoesPackageExist(MapPath)))
		{
			continue;
		}
		const UWorld* World = LoadObject<UWorld>(nullptr, *(MapPath + TEXT(".LV_") + Deck.Name));
		if (TestNotNull(FString::Printf(TEXT("%s loads"), *MapPath), World))
		{
			TestNotNull(FString::Printf(TEXT("%s is World Partition"), *MapPath),
				World->GetWorldSettings() ? World->GetWorldSettings()->GetWorldPartition() : nullptr);
			TestTrue(FString::Printf(TEXT("%s uses One File Per Actor"), *MapPath),
				World->PersistentLevel && World->PersistentLevel->IsUsingExternalActors());
		}
		for (const TCHAR* Layer : Deck.Layers)
		{
			const FString LayerPath = FString::Printf(TEXT("/Game/Verse/Decks/%s/DataLayers/%s.%s"), Deck.Name, Layer, Layer);
			const UDataLayerAsset* Asset = LoadObject<UDataLayerAsset>(nullptr, *LayerPath);
			if (TestNotNull(FString::Printf(TEXT("%s exists"), *LayerPath), Asset))
			{
				TestTrue(FString::Printf(TEXT("%s is a runtime layer"), Layer), Asset->IsRuntime());
			}
		}
	}
	return true;
}

// Verse.Content.TestHuman: SK_Test_Human carries every frozen bone of
// art-pipeline 12.1 with the frozen parent, plus hit bodies in its physics asset.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContentTestHumanTest, "Verse.Content.TestHuman",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseContentTestHumanTest::RunTest(const FString& Parameters)
{
	const USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, TEXT("/Game/Verse/Test/G0/SK_Test_Human.SK_Test_Human"));
	if (!TestNotNull(TEXT("SK_Test_Human loads"), Mesh))
	{
		return false;
	}
	const FReferenceSkeleton& Ref = Mesh->GetRefSkeleton();
	const TPair<const TCHAR*, const TCHAR*> Bones[] = {
		{ TEXT("Root"), TEXT("") },
		{ TEXT("Hips"), TEXT("Root") },
		{ TEXT("Spine_01"), TEXT("Hips") },
		{ TEXT("Spine_02"), TEXT("Spine_01") },
		{ TEXT("Spine_03"), TEXT("Spine_02") },
		{ TEXT("Neck"), TEXT("Spine_03") },
		{ TEXT("Head"), TEXT("Neck") },
		{ TEXT("Camera"), TEXT("Head") },
		{ TEXT("Clavicle_L"), TEXT("Spine_03") },
		{ TEXT("UpperArm_L"), TEXT("Clavicle_L") },
		{ TEXT("UpperArm_Twist_L"), TEXT("UpperArm_L") },
		{ TEXT("LowerArm_L"), TEXT("UpperArm_L") },
		{ TEXT("LowerArm_Twist_L"), TEXT("LowerArm_L") },
		{ TEXT("Hand_L"), TEXT("LowerArm_L") },
		{ TEXT("Index_01_L"), TEXT("Hand_L") },
		{ TEXT("Index_02_L"), TEXT("Index_01_L") },
		{ TEXT("Index_03_L"), TEXT("Index_02_L") },
		{ TEXT("Middle_01_L"), TEXT("Hand_L") },
		{ TEXT("Middle_02_L"), TEXT("Middle_01_L") },
		{ TEXT("Middle_03_L"), TEXT("Middle_02_L") },
		{ TEXT("Ring_01_L"), TEXT("Hand_L") },
		{ TEXT("Ring_02_L"), TEXT("Ring_01_L") },
		{ TEXT("Ring_03_L"), TEXT("Ring_02_L") },
		{ TEXT("Pinky_01_L"), TEXT("Hand_L") },
		{ TEXT("Pinky_02_L"), TEXT("Pinky_01_L") },
		{ TEXT("Pinky_03_L"), TEXT("Pinky_02_L") },
		{ TEXT("Thumb_01_L"), TEXT("Hand_L") },
		{ TEXT("Thumb_02_L"), TEXT("Thumb_01_L") },
		{ TEXT("Thumb_03_L"), TEXT("Thumb_02_L") },
		{ TEXT("Weapon_L"), TEXT("Hand_L") },
		{ TEXT("Thigh_L"), TEXT("Hips") },
		{ TEXT("Thigh_Twist_L"), TEXT("Thigh_L") },
		{ TEXT("Calf_L"), TEXT("Thigh_L") },
		{ TEXT("Calf_Twist_L"), TEXT("Calf_L") },
		{ TEXT("Foot_L"), TEXT("Calf_L") },
		{ TEXT("Ball_L"), TEXT("Foot_L") },
		{ TEXT("Clavicle_R"), TEXT("Spine_03") },
		{ TEXT("UpperArm_R"), TEXT("Clavicle_R") },
		{ TEXT("UpperArm_Twist_R"), TEXT("UpperArm_R") },
		{ TEXT("LowerArm_R"), TEXT("UpperArm_R") },
		{ TEXT("LowerArm_Twist_R"), TEXT("LowerArm_R") },
		{ TEXT("Hand_R"), TEXT("LowerArm_R") },
		{ TEXT("Index_01_R"), TEXT("Hand_R") },
		{ TEXT("Index_02_R"), TEXT("Index_01_R") },
		{ TEXT("Index_03_R"), TEXT("Index_02_R") },
		{ TEXT("Middle_01_R"), TEXT("Hand_R") },
		{ TEXT("Middle_02_R"), TEXT("Middle_01_R") },
		{ TEXT("Middle_03_R"), TEXT("Middle_02_R") },
		{ TEXT("Ring_01_R"), TEXT("Hand_R") },
		{ TEXT("Ring_02_R"), TEXT("Ring_01_R") },
		{ TEXT("Ring_03_R"), TEXT("Ring_02_R") },
		{ TEXT("Pinky_01_R"), TEXT("Hand_R") },
		{ TEXT("Pinky_02_R"), TEXT("Pinky_01_R") },
		{ TEXT("Pinky_03_R"), TEXT("Pinky_02_R") },
		{ TEXT("Thumb_01_R"), TEXT("Hand_R") },
		{ TEXT("Thumb_02_R"), TEXT("Thumb_01_R") },
		{ TEXT("Thumb_03_R"), TEXT("Thumb_02_R") },
		{ TEXT("Weapon_R"), TEXT("Hand_R") },
		{ TEXT("Thigh_R"), TEXT("Hips") },
		{ TEXT("Thigh_Twist_R"), TEXT("Thigh_R") },
		{ TEXT("Calf_R"), TEXT("Thigh_R") },
		{ TEXT("Calf_Twist_R"), TEXT("Calf_R") },
		{ TEXT("Foot_R"), TEXT("Calf_R") },
		{ TEXT("Ball_R"), TEXT("Foot_R") },
		{ TEXT("IK_Foot_Root"), TEXT("Root") },
		{ TEXT("IK_Hand_Root"), TEXT("Root") },
		{ TEXT("IK_Foot_L"), TEXT("IK_Foot_Root") },
		{ TEXT("IK_Foot_R"), TEXT("IK_Foot_Root") },
		{ TEXT("IK_Hand_Gun"), TEXT("IK_Hand_Root") },
		{ TEXT("IK_Hand_L"), TEXT("IK_Hand_Gun") },
		{ TEXT("IK_Hand_R"), TEXT("IK_Hand_Gun") },
	};
	TestEqual(TEXT("bone count"), Ref.GetRawBoneNum(), int32(UE_ARRAY_COUNT(Bones)));
	TestEqual(TEXT("first bone is Root"), Ref.GetBoneName(0), FName(TEXT("Root")));
	for (const TPair<const TCHAR*, const TCHAR*>& Bone : Bones)
	{
		const int32 Index = Ref.FindRawBoneIndex(FName(Bone.Key));
		if (!TestTrue(FString::Printf(TEXT("bone %s exists"), Bone.Key), Index != INDEX_NONE))
		{
			continue;
		}
		const int32 Parent = Ref.GetRawParentIndex(Index);
		const FName ParentName = Parent == INDEX_NONE ? NAME_None : Ref.GetBoneName(Parent);
		const FName Expected = *Bone.Value ? FName(Bone.Value) : NAME_None;
		TestEqual(FString::Printf(TEXT("parent of %s"), Bone.Key), ParentName, Expected);
	}

	const UPhysicsAsset* Physics = Mesh->GetPhysicsAsset();
	if (TestNotNull(TEXT("SK_Test_Human has a physics asset"), Physics))
	{
		const TCHAR* HitBones[] = {
			TEXT("Hips"), TEXT("Spine_01"), TEXT("Spine_03"), TEXT("Neck"), TEXT("Head"),
			TEXT("UpperArm_L"), TEXT("UpperArm_R"), TEXT("LowerArm_L"), TEXT("LowerArm_R"),
			TEXT("Thigh_L"), TEXT("Thigh_R"), TEXT("Calf_L"), TEXT("Calf_R"),
		};
		TArray<FString> Bodies;
		for (const USkeletalBodySetup* Body : Physics->SkeletalBodySetups)
		{
			Bodies.Add(Body ? Body->BoneName.ToString() : TEXT("<null>"));
		}
		AddInfo(FString::Printf(TEXT("PHYS_Test_Human bodies: %s"), *FString::Join(Bodies, TEXT(", "))));
		TestEqual(TEXT("hit body count"), Physics->SkeletalBodySetups.Num(), int32(UE_ARRAY_COUNT(HitBones)));
		for (const TCHAR* Bone : HitBones)
		{
			TestTrue(FString::Printf(TEXT("hit body on %s"), Bone), Physics->FindBodyIndex(FName(Bone)) != INDEX_NONE);
		}
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS && WITH_EDITOR

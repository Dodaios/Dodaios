#include "VerseHitZones.h"

#include "Components/BoxComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/HitResult.h"
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/BodySetup.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "VerseCharacter.h"

EVerseHitZone VerseHitZones::ZoneForBoneName(FName Bone)
{
	const FString Name = Bone.ToString();
	if (Name == TEXT("Head") || Name == TEXT("Camera"))
	{
		return EVerseHitZone::Head;
	}
	if (Name == TEXT("Neck"))
	{
		return EVerseHitZone::Neck;
	}
	if (Name == TEXT("Spine_02") || Name == TEXT("Spine_03") || Name.StartsWith(TEXT("Clavicle_")))
	{
		return EVerseHitZone::UpperTorso;
	}
	if (Name == TEXT("Spine_01") || Name == TEXT("Hips"))
	{
		return EVerseHitZone::LowerTorso;
	}
	if (Name.StartsWith(TEXT("UpperArm_")) || Name.StartsWith(TEXT("LowerArm_")) || Name.StartsWith(TEXT("Hand_")))
	{
		return EVerseHitZone::Arm;
	}
	if (Name.StartsWith(TEXT("Thigh_")) || Name.StartsWith(TEXT("Calf_")) || Name.StartsWith(TEXT("Foot_")) || Name.StartsWith(TEXT("Ball_")))
	{
		return EVerseHitZone::Leg;
	}
	return EVerseHitZone::None;
}

EVerseHitZone VerseHitZones::ZoneForBone(const USkeletalMesh* Mesh, FName Bone)
{
	if (!Mesh)
	{
		return ZoneForBoneName(Bone);
	}
	const FReferenceSkeleton& Skeleton = Mesh->GetRefSkeleton();
	int32 Index = Skeleton.FindBoneIndex(Bone);
	while (Index != INDEX_NONE)
	{
		const EVerseHitZone Zone = ZoneForBoneName(Skeleton.GetBoneName(Index));
		if (Zone != EVerseHitZone::None)
		{
			return Zone;
		}
		Index = Skeleton.GetParentIndex(Index);
	}
	return EVerseHitZone::None;
}

bool VerseHitZones::BuildTable(const UPhysicsAsset* Physics, const USkeletalMesh* Mesh, TMap<FName, EVerseHitZone>& OutTable, FString& OutError)
{
	OutTable.Reset();
	if (!Physics)
	{
		OutError = TEXT("no physics asset");
		return false;
	}
	for (const USkeletalBodySetup* Body : Physics->SkeletalBodySetups)
	{
		if (!Body)
		{
			continue;
		}
		const EVerseHitZone Zone = ZoneForBone(Mesh, Body->BoneName);
		if (Zone == EVerseHitZone::None)
		{
			OutError = FString::Printf(TEXT("body %s maps to no hit zone"), *Body->BoneName.ToString());
			return false;
		}
		OutTable.Add(Body->BoneName, Zone);
	}
	if (OutTable.IsEmpty())
	{
		OutError = TEXT("physics asset has no bodies");
		return false;
	}
	return true;
}

EVerseHitZone VerseHitZones::ZoneForHit(const FHitResult& Hit)
{
	const UPrimitiveComponent* Component = Hit.GetComponent();
	if (const AVerseCharacter* Character = Cast<AVerseCharacter>(Hit.GetActor()))
	{
		if (Component && Component == Character->GetProneBody())
		{
			return EVerseHitZone::Leg;
		}
	}
	if (const USkeletalMeshComponent* Mesh = Cast<USkeletalMeshComponent>(Component))
	{
		return ZoneForBone(Mesh->GetSkeletalMeshAsset(), Hit.BoneName);
	}
	return EVerseHitZone::None;
}

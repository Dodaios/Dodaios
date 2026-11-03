#include "VerseContentTools.h"

#if WITH_EDITOR
#include "Engine/SkeletalMesh.h"
#include "PhysicsEngine/PhysicsAsset.h"
#include "PhysicsEngine/SkeletalBodySetup.h"
#include "ReferenceSkeleton.h"

bool UVerseContentTools::RebuildHitBodies(UPhysicsAsset* PhysicsAsset, USkeletalMesh* Mesh,
	const TArray<FName>& Bones, const TArray<FName>& EndBones, const TArray<float>& Radii)
{
	if (!PhysicsAsset || !Mesh || Bones.Num() != EndBones.Num() || Bones.Num() != Radii.Num())
	{
		return false;
	}
	const FReferenceSkeleton& Ref = Mesh->GetRefSkeleton();
	const TArray<FTransform>& Local = Ref.GetRefBonePose();
	TArray<FTransform> Component;
	Component.SetNum(Local.Num());
	for (int32 Index = 0; Index < Local.Num(); ++Index)
	{
		const int32 Parent = Ref.GetParentIndex(Index);
		Component[Index] = Parent == INDEX_NONE ? Local[Index] : Local[Index] * Component[Parent];
	}

	PhysicsAsset->Modify();
	PhysicsAsset->SkeletalBodySetups.Empty();
	PhysicsAsset->ConstraintSetup.Empty();
	PhysicsAsset->CollisionDisableTable.Empty();

	for (int32 Entry = 0; Entry < Bones.Num(); ++Entry)
	{
		const int32 Bone = Ref.FindBoneIndex(Bones[Entry]);
		if (Bone == INDEX_NONE)
		{
			return false;
		}
		const float Radius = Radii[Entry];
		const FVector Start = Component[Bone].GetLocation();
		FVector End;
		const int32 EndBone = EndBones[Entry].IsNone() ? INDEX_NONE : Ref.FindBoneIndex(EndBones[Entry]);
		if (EndBone != INDEX_NONE)
		{
			End = Component[EndBone].GetLocation();
		}
		else
		{
			const int32 Parent = Ref.GetParentIndex(Bone);
			const FVector Dir = Parent == INDEX_NONE ? FVector::UpVector : (Start - Component[Parent].GetLocation()).GetSafeNormal();
			End = Start + Dir * (2.0f * Radius);
		}
		const FVector LocalDir = Component[Bone].InverseTransformVector(End - Start);

		FKSphylElem Capsule;
		Capsule.Radius = Radius;
		Capsule.Length = FMath::Max(1.0f, float(LocalDir.Size()) - Radius);
		Capsule.Center = Component[Bone].InverseTransformPosition((Start + End) * 0.5f);
		Capsule.Rotation = FRotationMatrix::MakeFromZ(LocalDir.GetSafeNormal()).Rotator();

		USkeletalBodySetup* Body = NewObject<USkeletalBodySetup>(PhysicsAsset, NAME_None, RF_Transactional);
		Body->BoneName = Bones[Entry];
		Body->PhysicsType = PhysType_Default;
		Body->AggGeom.SphylElems.Add(Capsule);
		PhysicsAsset->SkeletalBodySetups.Add(Body);
	}
	PhysicsAsset->UpdateBodySetupIndexMap();
	PhysicsAsset->UpdateBoundsBodiesArray();
	PhysicsAsset->MarkPackageDirty();
	return true;
}
#endif // WITH_EDITOR

#include "Anim/VerseFirstPerson.h"

#include "Anim/VerseAnimInstance.h"

#include "Camera/CameraComponent.h"
#include "Components/SkeletalMeshComponent.h"

const FName UVerseFirstPersonLibrary::HiddenBone(TEXT("Head"));
const FName UVerseFirstPersonLibrary::OwnerViewTag(TEXT("Verse.OwnerView"));

void UVerseFirstPersonLibrary::ConfigureOwnerView(USkeletalMeshComponent* FirstPersonBody, USkeletalMeshComponent* WorldBody,
	UCameraComponent* Camera, float FirstPersonFieldOfView, float FirstPersonScale)
{
	if (WorldBody)
	{
		// Seen by others and casting the owner's shadow; hidden from the owner.
		WorldBody->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::WorldSpaceRepresentation);
		WorldBody->SetCastShadow(true);
		WorldBody->bCastHiddenShadow = true;
	}
	if (FirstPersonBody)
	{
		FirstPersonBody->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::FirstPerson);
		FirstPersonBody->SetOnlyOwnerSee(true);
		FirstPersonBody->SetCastShadow(false);
		FirstPersonBody->ComponentTags.AddUnique(OwnerViewTag);
		// Hits resolve only against the world body: no second set of hit bodies on one pawn
		// (and none with a collapsed head). NoCollision also keeps the physics state from being created.
		FirstPersonBody->bAlwaysCreatePhysicsState = false;
		FirstPersonBody->SetGenerateOverlapEvents(false);
		FirstPersonBody->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		FirstPersonBody->SetCollisionResponseToAllChannels(ECR_Ignore);
		if (FirstPersonBody->IsPhysicsStateCreated())
		{
			// Already registered with hit bodies: drop them (no state is created again without collision).
			FirstPersonBody->RecreatePhysicsState();
		}
		// Covers bodies driven without UVerseAnimInstance (single-node clips); a no-op until registered.
		FirstPersonBody->HideBoneByName(HiddenBone, PBO_None);
		if (WorldBody && WorldBody != FirstPersonBody)
		{
			// Own anim instance, same inputs as the world body, so the head can be hidden on this body only.
			FirstPersonBody->SetLeaderPoseComponent(nullptr);
			UClass* WorldClass = WorldBody->AnimClass.Get();
			UClass* Wanted = WorldClass && WorldClass->IsChildOf(UVerseAnimInstance::StaticClass()) ? WorldClass : UVerseAnimInstance::StaticClass();
			UClass* Current = FirstPersonBody->AnimClass.Get();
			if (!Current || !Current->IsChildOf(UVerseAnimInstance::StaticClass()))
			{
				FirstPersonBody->SetAnimationMode(EAnimationMode::AnimationBlueprint);
				FirstPersonBody->SetAnimInstanceClass(Wanted);
			}
			// One source of weapon state and actions: the first-person body mirrors the world body.
			// An instance created later (registration) finds the world body itself (OwnerViewTag).
			if (UVerseAnimInstance* Instance = Cast<UVerseAnimInstance>(FirstPersonBody->GetAnimInstance()))
			{
				Instance->SetStateSource(WorldBody);
			}
			else
			{
				FirstPersonBody->PrimaryComponentTick.AddPrerequisite(WorldBody, WorldBody->PrimaryComponentTick);
			}
		}
	}
	if (Camera)
	{
		Camera->bEnableFirstPersonFieldOfView = true;
		Camera->bEnableFirstPersonScale = true;
		Camera->SetFirstPersonFieldOfView(FirstPersonFieldOfView);
		Camera->SetFirstPersonScale(FirstPersonScale);
	}
}

void UVerseFirstPersonLibrary::MarkFirstPerson(UPrimitiveComponent* Component)
{
	if (Component)
	{
		Component->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::FirstPerson);
		Component->SetCastShadow(false);
	}
}

void UVerseFirstPersonLibrary::ConfigureThirdPerson(USkeletalMeshComponent* FirstPersonBody, USkeletalMeshComponent* WorldBody)
{
	if (FirstPersonBody)
	{
		FirstPersonBody->SetVisibility(false);
	}
	if (WorldBody)
	{
		WorldBody->SetFirstPersonPrimitiveType(EFirstPersonPrimitiveType::None);
		WorldBody->SetOwnerNoSee(false);
		WorldBody->UnHideBoneByName(HiddenBone);
		WorldBody->ComponentTags.Remove(OwnerViewTag);
	}
}

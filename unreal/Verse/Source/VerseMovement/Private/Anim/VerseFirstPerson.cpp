#include "Anim/VerseFirstPerson.h"

#include "Camera/CameraComponent.h"
#include "Components/SkeletalMeshComponent.h"

const FName UVerseFirstPersonLibrary::HiddenBone(TEXT("Head"));

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
		FirstPersonBody->HideBoneByName(HiddenBone, PBO_None);
		if (WorldBody && WorldBody != FirstPersonBody)
		{
			FirstPersonBody->SetLeaderPoseComponent(WorldBody);
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
	}
}

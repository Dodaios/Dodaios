#include "Gore/VerseGoreActor.h"

#include "Components/DecalComponent.h"
#include "Components/InstancedStaticMeshComponent.h"
#include "Engine/CollisionProfile.h"
#include "Engine/StaticMesh.h"
#include "Gore/VerseGoreSubsystem.h"
#include "Materials/MaterialInterface.h"

AVerseGoreActor::AVerseGoreActor()
{
	PrimaryActorTick.bCanEverTick = false;
	bReplicates = false;
	SetReplicatingMovement(false);
	bNetLoadOnClient = false;
	SetCanBeDamaged(false);
	bFindCameraComponentWhenViewTarget = false;
	SetActorEnableCollision(false);

	USceneComponent* Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	RootComponent = Root;

	Droplets = NewInstanced(TEXT("Droplets"));
	// M_Gore_Droplet animates each instance from these floats (spawn time, velocity, life, drag, gravity).
	Droplets->NumCustomDataFloats = UVerseGoreSubsystem::DropletCustomFloats;
	Flashes = NewInstanced(TEXT("Flashes"));
}

UInstancedStaticMeshComponent* AVerseGoreActor::NewInstanced(FName Name)
{
	UInstancedStaticMeshComponent* Component = CreateDefaultSubobject<UInstancedStaticMeshComponent>(Name);
	Component->SetupAttachment(RootComponent);
	Component->SetMobility(EComponentMobility::Movable);
	MakeCosmetic(Component);
	Component->SetCanEverAffectNavigation(false);
	Component->bDisableCollision = true;
	Component->NumCustomDataFloats = 0;
	return Component;
}

void AVerseGoreActor::MakeCosmetic(UPrimitiveComponent* Component)
{
	if (!Component)
	{
		return;
	}
	Component->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Component->SetCollisionProfileName(UCollisionProfile::NoCollision_ProfileName);
	Component->SetCollisionResponseToAllChannels(ECR_Ignore);
	Component->SetGenerateOverlapEvents(false);
	Component->SetCanEverAffectNavigation(false);
	Component->CanCharacterStepUpOn = ECB_No;
	Component->SetCastShadow(false);
	Component->bReceivesDecals = false;
	Component->SetIsReplicated(false);
}

void AVerseGoreActor::SetLook(UStaticMesh* DropletMesh, UMaterialInterface* DropletMaterial, UMaterialInterface* FlashMaterial)
{
	if (DropletMesh)
	{
		Droplets->SetStaticMesh(DropletMesh);
		Flashes->SetStaticMesh(DropletMesh);
	}
	if (DropletMaterial)
	{
		Droplets->SetMaterial(0, DropletMaterial);
	}
	if (FlashMaterial)
	{
		Flashes->SetMaterial(0, FlashMaterial);
	}
	// Setting a mesh rebuilds body setup; keep both cosmetic afterwards.
	MakeCosmetic(Droplets);
	MakeCosmetic(Flashes);
}

UDecalComponent* AVerseGoreActor::NewDecal(UMaterialInterface* Material, const FVector& Size, const FLinearColor& Color,
	int32 SortOrder, const FTransform& Transform)
{
	UDecalComponent* Decal = NewObject<UDecalComponent>(this, NAME_None, RF_Transient);
	Decal->SetupAttachment(RootComponent);
	Decal->SetMobility(EComponentMobility::Movable);
	Decal->SetDecalMaterial(Material);
	Decal->DecalSize = Size;
	Decal->DecalColor = Color;
	Decal->SortOrder = SortOrder;
	Decal->SetWorldTransform(Transform);
	Decal->SetFadeScreenSize(0.002f);
	Decal->bDestroyOwnerAfterFade = false;
	Decal->SetIsReplicated(false);
	Decal->RegisterComponent();
	return Decal;
}

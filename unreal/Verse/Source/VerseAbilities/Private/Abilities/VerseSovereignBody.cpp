#include "Abilities/VerseSovereignBody.h"

#include "Anim/VerseAnimInstance.h"
#include "Anim/VerseAnimTypes.h"
#include "Components/CapsuleComponent.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/SkeletalMesh.h"
#include "GameFramework/Character.h"

const TCHAR* UVerseSovereignBody::MeshPath = TEXT("/Game/Verse/Characters/Sovereign/SK_Sovereign.SK_Sovereign");

namespace VerseSovereignBodyPrivate
{
	/** The mesh faces +Y in its own space (coordinates.md 3.3: mesh yaw = heading - 90). */
	const FRotator MeshBaseRotation(0.f, -90.f, 0.f);
	const FName IdleClip(TEXT("A_Crew_Stand"));
	const FName WalkClip(TEXT("A_Crew_Walk"));
}

UVerseSovereignBody::UVerseSovereignBody()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.TickGroup = TG_PostPhysics;
}

UVerseSovereignBody* UVerseSovereignBody::Dress(ACharacter* Character)
{
	using namespace VerseSovereignBodyPrivate;
	if (Character == nullptr || Character->GetMesh() == nullptr)
	{
		return nullptr;
	}
	if (UVerseSovereignBody* Existing = Character->FindComponentByClass<UVerseSovereignBody>())
	{
		return Existing;
	}
	USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, MeshPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	if (Mesh == nullptr)
	{
		return nullptr;
	}
	USkeletalMeshComponent* Body = Character->GetMesh();
	Body->SetSkeletalMeshAsset(Mesh);
	Body->SetAnimInstanceClass(UVerseAnimInstance::StaticClass());
	const float HalfHeight = Character->GetCapsuleComponent() ? Character->GetCapsuleComponent()->GetUnscaledCapsuleHalfHeight() : 90.f;
	Body->SetRelativeLocationAndRotation(FVector(0.f, 0.f, -HalfHeight), MeshBaseRotation);
	Body->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Body->SetCanEverAffectNavigation(false);
	Body->VisibilityBasedAnimTickOption = EVisibilityBasedAnimTickOption::AlwaysTickPoseAndRefreshBones;
	Body->SetVisibility(true);
	UVerseSovereignBody* Component = NewObject<UVerseSovereignBody>(Character, TEXT("SovereignBody"));
	Component->RegisterComponent();
	// The cloak swings after the body moved this frame.
	Component->AddTickPrerequisiteActor(Character);
	return Component;
}

FQuat UVerseSovereignBody::SegmentRotation(const VerseCloak::FAngles& Angles)
{
	// Lift: the hem rises backwards (toward -Y), a turn about the body's left axis (+X).
	// Swing: the hem moves toward the body's right (-X), a turn about the forward axis (+Y).
	// FQuat turns by the right-hand rule: +Lift is a negative angle about +X, +Swing positive about +Y.
	const FQuat Lift(FVector::XAxisVector, -Angles.Lift);
	const FQuat Swing(FVector::YAxisVector, Angles.Swing);
	return Lift * Swing;
}

void UVerseSovereignBody::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Animate(DeltaTime);
}

void UVerseSovereignBody::Animate(float DeltaTime)
{
	using namespace VerseSovereignBodyPrivate;
	const ACharacter* Character = Cast<ACharacter>(GetOwner());
	USkeletalMeshComponent* Body = Character ? Character->GetMesh() : nullptr;
	UVerseAnimInstance* Anim = Body ? Cast<UVerseAnimInstance>(Body->GetAnimInstance()) : nullptr;
	if (Anim == nullptr || DeltaTime <= 0.f)
	{
		return;
	}
	const FVector Velocity = Character->GetVelocity();
	const float Speed = static_cast<float>(Velocity.Size2D() / 100.0);
	const float Forward = static_cast<float>(FVector::DotProduct(Velocity, Character->GetActorForwardVector()) / 100.0);
	// Walk while moving; the three.js actor keeps walking down to a lower speed (hysteresis).
	bWalking = Speed > WalkAbove || (bWalking && Speed > 0.5f * WalkAbove);

	FVerseAnimInputs Inputs;
	Inputs.Weapon = EVerseAnimWeapon::None;
	Inputs.bOverrideLoop = true;
	if (bWalking)
	{
		// Backwards when the body walks against its facing (backpedal in a shooter view).
		const float Direction = Forward < -0.1f * Speed ? -1.f : 1.f;
		ClipTime += DeltaTime * Direction * FMath::Max(0.3f, Speed / ClipWalkSpeed);
		Inputs.OverrideClip = WalkClip;
	}
	else
	{
		ClipTime += DeltaTime;
		Inputs.OverrideClip = IdleClip;
	}
	// Positive and bounded: 3600 s is a whole number of loops of both clips (1 s and 6 s).
	ClipTime = FMath::Fmod(ClipTime + 3600.f, 3600.f);
	Inputs.OverrideTime = ClipTime;
	Anim->SetExternalInputs(Inputs);

	Cloak.Update(DeltaTime, Character->GetActorLocation(), static_cast<float>(Character->GetActorRotation().Yaw), !bWalking);
	TArray<FVerseBoneSwing> Swings;
	Swings.Reserve(VerseCloak::Columns * 2);
	for (int32 Column = 0; Column < VerseCloak::Columns; ++Column)
	{
		const VerseCloak::FColumn& C = Cloak.Column(Column);
		Swings.Add({VerseCloak::BoneName(Column, 0), SegmentRotation(C.Upper)});
		Swings.Add({VerseCloak::BoneName(Column, 1), SegmentRotation(C.Lower)});
	}
	Anim->SetBoneSwings(MoveTemp(Swings));
}

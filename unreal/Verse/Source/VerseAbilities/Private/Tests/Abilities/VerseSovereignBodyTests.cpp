#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Abilities/VerseSovereignBody.h"
#include "Anim/VerseAnimInstance.h"
#include "Components/SkeletalMeshComponent.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "GameFramework/Character.h"
#include "GameFramework/CharacterMovementComponent.h"
#include "GameFramework/WorldSettings.h"

#define VERSE_ABILITIES_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// The Sovereign as the person's body (Z-02): the skin goes on a character's mesh with the
// animation runtime, the walk clip runs while moving, and the cloak bones swing the way
// `actors/cloak.ts` swings them (the hem lifts backwards on a walk, toward the right on a swing).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAbilitiesSovereignBody, "Verse.Abilities.SovereignBody", VERSE_ABILITIES_TEST_FLAGS)
bool FVerseAbilitiesSovereignBody::RunTest(const FString&)
{
	// The segment rotation in mesh space: the mesh faces +Y, +X is the body's left.
	const FVector Hem(0.0, 0.0, -1.0);
	VerseCloak::FAngles Lift;
	Lift.Lift = 0.5f;
	TestTrue(TEXT("a positive lift raises the hem backwards (-Y)"), UVerseSovereignBody::SegmentRotation(Lift).RotateVector(Hem).Y < -0.3);
	VerseCloak::FAngles Swing;
	Swing.Swing = 0.5f;
	TestTrue(TEXT("a positive swing moves the hem to the body's right (-X)"), UVerseSovereignBody::SegmentRotation(Swing).RotateVector(Hem).X < -0.3);

	if (LoadObject<USkeletalMesh>(nullptr, UVerseSovereignBody::MeshPath, nullptr, LOAD_NoWarn | LOAD_Quiet) == nullptr)
	{
		AddError(TEXT("SK_Sovereign is not in the project"));
		return false;
	}
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseSovereignBodyTest")));
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	World->InitializeActorsForPlay(FURL());
	World->BeginPlay();
	if (!World->GetBegunPlay())
	{
		World->GetWorldSettings()->NotifyBeginPlay();
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ACharacter* Body = World->SpawnActor<ACharacter>(ACharacter::StaticClass(), FVector(0.0, 0.0, 90.0), FRotator::ZeroRotator, Params);
	UVerseSovereignBody* Skin = UVerseSovereignBody::Dress(Body);
	if (TestNotNull(TEXT("the Sovereign goes on"), Skin))
	{
		TestTrue(TEXT("dressing twice keeps one skin"), UVerseSovereignBody::Dress(Body) == Skin);
		USkeletalMeshComponent* Mesh = Body->GetMesh();
		TestTrue(TEXT("the mesh is SK_Sovereign"), Mesh->GetSkeletalMeshAsset() && Mesh->GetSkeletalMeshAsset()->GetPathName() == UVerseSovereignBody::MeshPath);
		TestTrue(TEXT("the cloak bones are on the mesh"), Mesh->GetBoneIndex(TEXT("Cloak_C2")) != INDEX_NONE);
		Mesh->InitAnim(true);
		UVerseAnimInstance* Anim = Cast<UVerseAnimInstance>(Mesh->GetAnimInstance());
		if (TestNotNull(TEXT("the animation runtime drives it"), Anim))
		{
			const float Dt = 1.f / 60.f;
			for (int32 I = 0; I < 30; ++I)
			{
				Skin->TickComponent(Dt, LEVELTICK_All, nullptr);
			}
			TestFalse(TEXT("standing: no walk"), Skin->IsWalking());
			TestEqual(TEXT("standing plays the idle clip"), Anim->GetInputs().OverrideClip, FName(TEXT("A_Crew_Stand")));
			// Walk forward at the clip's own speed for a second.
			Body->GetCharacterMovement()->Velocity = Body->GetActorForwardVector() * 140.0;
			for (int32 I = 0; I < 60; ++I)
			{
				Body->SetActorLocation(Body->GetActorLocation() + Body->GetActorForwardVector() * 140.0 * Dt);
				Skin->TickComponent(Dt, LEVELTICK_All, nullptr);
			}
			TestTrue(TEXT("walking"), Skin->IsWalking());
			TestEqual(TEXT("walking plays the walk clip"), Anim->GetInputs().OverrideClip, FName(TEXT("A_Crew_Walk")));
			const TArray<FVerseBoneSwing>& Swings = Anim->GetBoneSwings();
			TestEqual(TEXT("six cloak bones swing"), Swings.Num(), 6);
			if (Swings.Num() == 6)
			{
				TestTrue(TEXT("the centre hem trails behind a walk"), Swings[2].MeshRotation.RotateVector(Hem).Y < -0.1);
			}
		}
	}
	World->EndPlay(EEndPlayReason::Quit);
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/SkeletalMeshComponent.h"
#include "Crew/VerseCrewPawn.h"
#include "Engine/Engine.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/WorldSettings.h"
#include "Life/VerseDeckDrone.h"

// One companion only: the crew's companion wears the three.js drone (SK_Drone_Companion with its
// clips), tells the deck it is there, and a deck companion spawned before it steps aside.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCrewCompanionBodyTest, "Verse.Crew.Companion.Body", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseCrewCompanionBodyTest::RunTest(const FString&)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseCompanionBodyTest")));
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

	AVerseDeckDrone* DeckCompanion = World->SpawnActor<AVerseDeckDrone>(Params);
	TestTrue(TEXT("the deck companion is in the project"), DeckCompanion->Init(EVerseDroneKind::Companion, FVector::ZeroVector, 0.0));
	TestFalse(TEXT("no other companion yet"), AVerseDeckDrone::HasOtherCompanion(World));

	AVerseCompanionDrone* Crew = World->SpawnActor<AVerseCompanionDrone>(FVector(0.0, 0.0, 140.0), FRotator::ZeroRotator, Params);
	if (TestNotNull(TEXT("the crew companion flies"), Crew))
	{
		TestTrue(TEXT("it wears SK_Drone_Companion"), Crew->Body->GetSkeletalMeshAsset() && Crew->Body->GetSkeletalMeshAsset()->GetPathName() == AVerseDeckDrone::CompanionMeshPath);
		TestTrue(TEXT("hovering at heel"), Crew->Body->IsPlaying() && !Crew->IsMoving());
		Crew->SetMoving(true);
		TestTrue(TEXT("following on the move"), Crew->IsMoving());
		TestTrue(TEXT("the deck sees the crew companion"), AVerseDeckDrone::HasOtherCompanion(World));
		int32 DeckCompanions = 0;
		for (TActorIterator<AVerseDeckDrone> It(World); It; ++It)
		{
			DeckCompanions += IsValid(*It) && It->GetKind() == EVerseDroneKind::Companion ? 1 : 0;
		}
		TestEqual(TEXT("the deck companion stepped aside"), DeckCompanions, 0);
	}

	World->EndPlay(EEndPlayReason::Quit);
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

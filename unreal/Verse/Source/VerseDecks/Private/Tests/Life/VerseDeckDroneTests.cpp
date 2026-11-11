#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Commander/VerseDeckNavGrid.h"
#include "Decks/VerseDeckManifest.h"
#include "Engine/Engine.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "GameFramework/WorldSettings.h"
#include "Life/VerseDeckDrone.h"

#define VERSE_DECKS_DRONE_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// The deck drones (parity with three.js `life/cast.ts` and `actors/actor.ts`): which routes the
// utility drones drive, where the companion waits, and that both walk the nav grid with their clips.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksDroneRoutesTest, "Verse.Decks.Drones.Routes", VERSE_DECKS_DRONE_TEST_FLAGS)
bool FVerseDecksDroneRoutesTest::RunTest(const FString&)
{
	auto Group = [this](const TCHAR* What, const TCHAR* Id, const TCHAR* Want, int32 Order)
	{
		const TPair<FString, int32> Got = VerseDeckDrones::SocketGroup(Id);
		TestEqual(What, Got.Key, FString(Want));
		TestEqual(What, Got.Value, Order);
	};
	Group(TEXT("cargo_01"), TEXT("cargo_01"), TEXT("cargo"), 1);
	Group(TEXT("corridor10"), TEXT("corridor10"), TEXT("corridor"), 10);
	Group(TEXT("brief__02"), TEXT("brief__02"), TEXT("brief"), 2);
	Group(TEXT("step_p_1__top"), TEXT("step_p_1__top"), TEXT("step_p_1"), 0);
	Group(TEXT("ramp_top"), TEXT("ramp_top"), TEXT("ramp_top"), 0);

	FVerseDeckManifest Manifest;
	FString Error;
	const TCHAR* Json = TEXT(R"({"schema": "verse.placement/1", "deck": "test", "zone": "z", "rooms": [], "sockets": [
		{"id": "patrol_a_1", "kind": "waypoint", "location": [0, 0, 0], "rotation": [0, 0, 0, 1]},
		{"id": "patrol_a_2", "kind": "waypoint", "location": [100, 0, 0], "rotation": [0, 0, 0, 1]},
		{"id": "cargo_02", "kind": "waypoint", "location": [200, 0, 0], "rotation": [0, 0, 0, 1]},
		{"id": "cargo_01", "kind": "waypoint", "location": [100, 0, 0], "rotation": [0, 0, 0, 1]},
		{"id": "pad_1", "kind": "waypoint", "location": [0, 300, 0], "rotation": [0, 0, 0, 1]},
		{"id": "pad_2", "kind": "waypoint", "location": [0, 400, 0], "rotation": [0, 0, 0, 1]},
		{"id": "service_1", "kind": "waypoint", "location": [0, 500, 0], "rotation": [0, 0, 0, 1]},
		{"id": "service_2", "kind": "waypoint", "location": [0, 600, 0], "rotation": [0, 0, 0, 1]},
		{"id": "corridor_1", "kind": "waypoint", "location": [0, 700, 0], "rotation": [0, 0, 0, 1]}
	]})");
	if (!TestTrue(TEXT("placement parses"), Manifest.AddPlacementJson(Json, Error)))
	{
		AddError(Error);
		return false;
	}
	const TArray<FVerseDroneRoute> Routes = VerseDeckDrones::UtilityRoutes(Manifest);
	if (TestEqual(TEXT("two drones at most, patrols and one-point groups skipped"), Routes.Num(), 2))
	{
		TestEqual(TEXT("first seen first"), Routes[0].Group, FName(TEXT("cargo")));
		TestEqual(TEXT("then pad"), Routes[1].Group, FName(TEXT("pad")));
		TestEqual(TEXT("points by order"), Routes[0].Points[0].X, 100.0);
		TestEqual(TEXT("points by order"), Routes[0].Points[1].X, 200.0);
	}

	// Heel: 1.1 m behind and 0.45 m to the left of a leader facing +X.
	const FVector Heel = VerseDeckDrones::HeelPoint(FVector::ZeroVector, 0.0);
	TestTrue(TEXT("heel behind"), FMath::IsNearlyEqual(Heel.X, -110.0, 0.01));
	TestTrue(TEXT("heel to the left (-Y)"), FMath::IsNearlyEqual(Heel.Y, -45.0, 0.01));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksDroneWalkTest, "Verse.Decks.Drones.Walk", VERSE_DECKS_DRONE_TEST_FLAGS)
bool FVerseDecksDroneWalkTest::RunTest(const FString&)
{
	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseDroneTest")));
	FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
	Context.SetCurrentWorld(World);
	World->InitializeActorsForPlay(FURL());
	World->BeginPlay();
	if (!World->GetBegunPlay())
	{
		World->GetWorldSettings()->NotifyBeginPlay();
	}
	// A 20 x 20 m open floor.
	FVerseDeckNavGrid Grid;
	Grid.Init(FBox2D(FVector2D(-1000.0, -1000.0), FVector2D(1000.0, 1000.0)));
	for (int32 I = 0; I < Grid.NumCols() * Grid.NumRows(); ++I)
	{
		Grid.SetCell(I, true, 0.0);
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	const float Dt = 1.f / 30.f;

	AVerseDeckDrone* Companion = World->SpawnActor<AVerseDeckDrone>(Params);
	AStaticMeshActor* Lead = World->SpawnActor<AStaticMeshActor>(FVector::ZeroVector, FRotator::ZeroRotator, Params);
	Lead->SetMobility(EComponentMobility::Movable);
	if (!TestTrue(TEXT("the companion's mesh is in the project"), Companion->Init(EVerseDroneKind::Companion, VerseDeckDrones::HeelPoint(FVector::ZeroVector, 0.0), 0.0)))
	{
		GEngine->DestroyWorldContext(World);
		World->DestroyWorld(false);
		return false;
	}
	Companion->NavOverride = &Grid;
	Companion->Leader = Lead;
	for (int32 I = 0; I < 15; ++I)
	{
		Companion->Tick(Dt);
	}
	TestFalse(TEXT("at heel: no walk"), Companion->IsMoving());
	TestEqual(TEXT("at heel it hovers"), Companion->GetClip(), FName(TEXT("hover")));
	// The leader walks off 5 m: the companion follows to its heel.
	Lead->SetActorLocation(FVector(500.0, 0.0, 0.0));
	bool bFollowed = false;
	for (int32 I = 0; I < 30 * 6; ++I)
	{
		Companion->Tick(Dt);
		bFollowed |= Companion->GetClip() == FName(TEXT("walk"));
	}
	TestTrue(TEXT("it played the follow clip on the way"), bFollowed);
	const double ToLeader = FVector::Dist2D(Companion->GetFeet(), Lead->GetActorLocation());
	TestTrue(FString::Printf(TEXT("back within heel range (%.0f cm)"), ToLeader), ToLeader < VerseDeckDrones::HeelCm * 1.5);
	TestEqual(TEXT("settled: hover again"), Companion->GetClip(), FName(TEXT("hover")));

	AVerseDeckDrone* Utility = World->SpawnActor<AVerseDeckDrone>(Params);
	if (TestTrue(TEXT("the utility drone's mesh is in the project"), Utility->Init(EVerseDroneKind::Utility, FVector(0.0, 300.0, 0.0), 0.0)))
	{
		Utility->NavOverride = &Grid;
		FVerseDroneRoute Route;
		Route.Group = TEXT("cargo");
		Route.Points = { FVector(0.0, 300.0, 0.0), FVector(400.0, 300.0, 0.0) };
		Utility->SetRoute(Route);
		double Furthest = 0.0;
		bool bDrove = false;
		bool bBack = false;
		for (int32 I = 0; I < 30 * 10; ++I)
		{
			Utility->Tick(Dt);
			Furthest = FMath::Max(Furthest, Utility->GetFeet().X);
			bDrove |= Utility->GetClip() == FName(TEXT("walk"));
			bBack |= Furthest > 390.0 && Utility->GetFeet().X < Furthest - 50.0;
		}
		TestTrue(TEXT("it drove with the drive clip"), bDrove);
		TestTrue(FString::Printf(TEXT("it reached the far point (%.0f cm)"), Furthest), Furthest > 390.0);
		TestTrue(TEXT("and turned back on its round"), bBack);
	}

	World->EndPlay(EEndPlayReason::Quit);
	GEngine->DestroyWorldContext(World);
	World->DestroyWorld(false);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

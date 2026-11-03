#include "AI/NavigationSystemBase.h"
#include "AI/Navigation/NavigationDataInterface.h"
#include "AI/Navigation/NavigationTypes.h"
#include "Belief/VerseBeliefGrid.h"
#include "Belief/VerseBeliefMap.h"
#include "Belief/VerseBeliefNavSampler.h"
#include "CollisionQueryParams.h"
#include "Components/BrushComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/Brush.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "PhysicsEngine/BodySetup.h"
#include "Tests/Belief/VerseBeliefTestFixture.h"
#include "VerseCollision.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Belief.Recast and Verse.Perf.Bot.BeliefTraceCost: the WP07 fixture arena (the lane
// graybox of VerseBeliefTestFixture.h) built as real geometry in a transient editor world, with a
// Recast navmesh built from it. The belief grid is sampled from that navmesh (WP07.5) and the map
// step is timed with real VerseSight line traces (A7.6 with real TestSight cost).

#define VERSE_BELIEF_WORLD_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotBeliefWorldTests
{
	using namespace VerseBotBeliefTests;

	/** Pieces of the fixture: a catwalk-like floor slab (piece 3) and a solid 3 x 3 m block (piece 9). */
	constexpr int32 SlabPiece = 3;
	constexpr int32 BlockPiece = 9;
	/** The observer post of the lane fixture, (25, 5) m. */
	const FVector PostFeet = ColumnCentre(25, 5);
	const FBox SlabFootprint(FVector(4000.0, 3000.0, -50.0), FVector(4500.0, 3500.0, 50.0));
	const FBox BlockBox(FVector(3500.0, 1000.0, 0.0), FVector(3800.0, 1300.0, 400.0));

	/** TestSight as a plain line trace on VerseSight (the WP03 stand-in), counting its calls. */
	class FTraceSight : public IVersePenetrationQuery
	{
	public:
		explicit FTraceSight(UWorld* InWorld) : World(InWorld) {}

		UWorld* World = nullptr;
		mutable int32 Calls = 0;

		virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
			float Damage, uint8 RadiusMm, int32 MaxPieces) const override
		{
			return {};
		}

		virtual bool TestSight(const FVector& Eye, const FVector& Target) const override
		{
			++Calls;
			static const FName TraceTag(TEXT("VerseSight"));
			const FCollisionQueryParams Params(TraceTag, false);
			return !World->LineTraceTestByChannel(Eye, Target, VerseCollision::Sight, Params);
		}
	};

	/** The transient arena: floor, the fixture walls, the block; nav bounds; Recast built. */
	struct FArenaWorld
	{
		UWorld* World = nullptr;
		FString Error;

		FArenaWorld()
		{
			World = UWorld::CreateWorld(EWorldType::Editor, false, TEXT("VerseBeliefRecastFixture"));
			if (!World)
			{
				Error = TEXT("no world");
				return;
			}
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Editor);
			Context.SetCurrentWorld(World);
			FNavigationSystem::AddNavigationSystemToWorld(*World, FNavigationSystemRunMode::EditorMode);

			UStaticMesh* Cube = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
			if (!Cube)
			{
				Error = TEXT("no cube mesh");
				return;
			}
			// The cube is 100 cm with its pivot at the centre.
			auto AddBox = [this, Cube](const FBox& Box) {
				FActorSpawnParameters Params;
				Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
				AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(Box.GetCenter(), FRotator::ZeroRotator, Params);
				UStaticMeshComponent* Mesh = Actor->GetStaticMeshComponent();
				Mesh->SetMobility(EComponentMobility::Static);
				Mesh->SetStaticMesh(Cube);
				Mesh->SetWorldScale3D(Box.GetSize() / 100.0);
				Mesh->SetCollisionProfileName(VerseCollision::Profile::Architecture);
				Mesh->SetCanEverAffectNavigation(true);
			};
			AddBox(FBox(FVector(-100.0, -100.0, -20.0), FVector(5100.0, 4100.0, 0.0)));
			FLaneFixture Fixture;
			for (const FFakeWall& Wall : Fixture.World.Walls)
			{
				AddBox(Wall.Box);
			}
			AddBox(BlockBox);

			// Nav bounds: a NavMeshBoundsVolume (found by class name; VerseBot does not link the
			// NavigationSystem module) whose brush is a box body.
			UClass* BoundsClass = FindObject<UClass>(nullptr, TEXT("/Script/NavigationSystem.NavMeshBoundsVolume"));
			if (!BoundsClass)
			{
				Error = TEXT("no NavMeshBoundsVolume class");
				return;
			}
			const FTransform BoundsAt(FVector(2500.0, 2000.0, 200.0));
			ABrush* Bounds = World->SpawnActorDeferred<ABrush>(BoundsClass, BoundsAt);
			if (!Bounds || !Bounds->GetBrushComponent())
			{
				Error = TEXT("no bounds volume");
				return;
			}
			UBodySetup* Body = NewObject<UBodySetup>(Bounds->GetBrushComponent());
			Body->AggGeom.BoxElems.Add(FKBoxElem(5400.f, 4400.f, 1000.f));
			Bounds->GetBrushComponent()->BrushBodySetup = Body;
			Bounds->FinishSpawning(BoundsAt);
			// Components register at spawn, before the body was set: register again so the
			// navigation system sees the volume's real bounds.
			Bounds->UnregisterAllComponents();
			Bounds->RegisterAllComponents();

			UNavigationSystemBase* NavSys = World->GetNavigationSystem();
			if (!NavSys)
			{
				Error = TEXT("no navigation system");
				return;
			}
			for (int32 Tick = 0; Tick < 4; ++Tick)
			{
				NavSys->Tick(0.1f);
			}
			GEngine->Exec(World, TEXT("RebuildNavigation"));
			const double Deadline = FPlatformTime::Seconds() + 60.0;
			while (FPlatformTime::Seconds() < Deadline)
			{
				NavSys->Tick(0.05f);
				const INavigationDataInterface* Nav = NavSys->GetMainNavData();
				FNavLocation Hit;
				if (Nav && Nav->ProjectPoint(FVector(2500.0, 500.0, 0.0), Hit, FVector(50.0, 50.0, 150.0)) &&
					Nav->ProjectPoint(FVector(1000.0, 2300.0, 0.0), Hit, FVector(50.0, 50.0, 150.0)))
				{
					return;
				}
				FPlatformProcess::Sleep(0.01f);
			}
			Error = TEXT("navmesh not built within 60 s");
		}

		~FArenaWorld()
		{
			if (World)
			{
				GEngine->DestroyWorldContext(World);
				World->DestroyWorld(false);
			}
		}

		FVerseBeliefNavSettings Settings() const
		{
			FVerseBeliefNavSettings Out;
			Out.ArenaBox = FBox(FVector(0.0, 0.0, -100.0), FVector(5000.0, 4000.0, 1200.0));
			Out.CellSizeCm = 100.f;
			Out.PieceFootprints.Add({SlabPiece, SlabFootprint, EVerseBeliefGate::WhenStanding, EVerseArenaLevel::Floor});
			Out.PieceFootprints.Add({BlockPiece, BlockBox, EVerseBeliefGate::WhenOpen, EVerseArenaLevel::Floor});
			return Out;
		}
	};
}

using namespace VerseBotBeliefWorldTests;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefRecastTest, "Verse.Bot.Belief.Recast", VERSE_BELIEF_WORLD_TEST_FLAGS)

bool FVerseBeliefRecastTest::RunTest(const FString& Parameters)
{
	// WP07.5: the grid is sampled from a real Recast navmesh of the fixture arena: one cell per 1 m
	// column, none inside walls, the walls cut adjacency except at the door, and piece footprints
	// gate cells (a slab goes when destroyed, an opening appears when breached).
	FArenaWorld Arena;
	if (!Arena.Error.IsEmpty())
	{
		AddError(FString::Printf(TEXT("fixture arena: %s"), *Arena.Error));
		return false;
	}
	FVerseBeliefGridSource Source;
	const bool bBuilt = FVerseBeliefNavSampler::Build(*Arena.World, Arena.Settings(), Source);
	TestTrue(TEXT("sampled from Recast"), bBuilt);
	int32 Gated = 0;
	int32 Openings = 0;
	for (const FVerseBeliefCellDesc& Cell : Source.Cells)
	{
		Gated += Cell.Gate == EVerseBeliefGate::WhenStanding && Cell.GatePiece == SlabPiece ? 1 : 0;
		Openings += Cell.Gate == EVerseBeliefGate::WhenOpen && Cell.GatePiece == BlockPiece ? 1 : 0;
	}
	AddInfo(FString::Printf(TEXT("Recast sample: %d cells, %d slab-gated, %d opening cells"), Source.Cells.Num(), Gated, Openings));
	TestTrue(TEXT("about one cell per walkable column (1,500..2,100)"), Source.Cells.Num() >= 1500 && Source.Cells.Num() <= 2100);
	TestEqual(TEXT("slab footprint: 5 x 5 columns gated"), Gated, 25);
	TestEqual(TEXT("block footprint: 3 x 3 opening cells"), Openings, 9);

	FVerseBeliefGrid Grid;
	Grid.Build(Source);
	const int32 Post = Grid.FindCell(FIntPoint(25, 5), EVerseArenaLevel::Floor);
	const int32 Lane = Grid.FindCell(FIntPoint(10, 23), EVerseArenaLevel::Floor);
	const int32 SouthOfWall = Grid.FindCell(FIntPoint(10, 19), EVerseArenaLevel::Floor);
	const int32 NorthOfWall = Grid.FindCell(FIntPoint(10, 20), EVerseArenaLevel::Floor);
	TestTrue(TEXT("cells on both sides of wall A"), Post != INDEX_NONE && Lane != INDEX_NONE && SouthOfWall != INDEX_NONE &&
		NorthOfWall != INDEX_NONE);
	if (SouthOfWall != INDEX_NONE && NorthOfWall != INDEX_NONE)
	{
		TArray<int32> Neighbours;
		Grid.GetNeighbours(SouthOfWall, Neighbours);
		TestFalse(TEXT("wall A cuts adjacency"), Neighbours.Contains(NorthOfWall));
	}
	if (Post != INDEX_NONE && Lane != INDEX_NONE)
	{
		const TArray<int32> Path = Grid.FindPath(Post, Lane);
		TestTrue(TEXT("a path through the door"), Path.Num() > 0);
		bool bThroughDoor = false;
		for (const int32 Cell : Path)
		{
			const FIntPoint Column = Grid.GetCell(Cell).Column;
			bThroughDoor |= (Column.Y == 19 || Column.Y == 20) && Column.X >= 24 && Column.X <= 25;
		}
		TestTrue(TEXT("the path uses the door columns"), bThroughDoor);
	}

	// Gates: intact block, standing slab at match start.
	const int32 Slab = Grid.FindCellAnyState(FIntPoint(42, 32), EVerseArenaLevel::Floor);
	const int32 Opening = Grid.FindCellAnyState(FIntPoint(36, 11), EVerseArenaLevel::Floor);
	TestTrue(TEXT("slab standing: active"), Grid.IsActive(Slab));
	TestFalse(TEXT("block intact: no opening cell"), Grid.IsActive(Opening));
	Grid.ApplyGates([](int32 Piece) { return Piece == BlockPiece; }, [](int32 Piece) { return Piece != SlabPiece; });
	TestFalse(TEXT("slab destroyed: gone"), Grid.IsActive(Slab));
	TestTrue(TEXT("block breached: opening cell"), Grid.IsActive(Opening));
	TestTrue(TEXT("opening joins the floor around it"), Grid.NumNeighbours(Opening) >= 8);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBeliefTraceCostTest, "Verse.Perf.Bot.BeliefTraceCost", VERSE_BELIEF_WORLD_TEST_FLAGS)

bool FVerseBeliefTraceCostTest::RunTest(const FString& Parameters)
{
	// A7.6 with real sight: the map step on the Recast-sampled fixture arena with VerseSight line
	// traces, the default trace budget, the observer turning on the spot and then walking. Reports
	// the cost of a 10 Hz step (traces included) against the 0.05 ms belief budget, and the
	// amortised cost per 60 Hz tick against the 0.5 ms bot budget.
	FArenaWorld Arena;
	if (!Arena.Error.IsEmpty())
	{
		AddError(FString::Printf(TEXT("fixture arena: %s"), *Arena.Error));
		return false;
	}
	FVerseBeliefGridSource Source;
	if (!TestTrue(TEXT("sampled from Recast"), FVerseBeliefNavSampler::Build(*Arena.World, Arena.Settings(), Source)))
	{
		return false;
	}
	FTraceSight Sight(Arena.World);

	// One trace alone, for the report.
	{
		const FVector Eye(2500.0, 500.0, 165.0);
		const double Start = FPlatformTime::Seconds();
		for (int32 Index = 0; Index < 2000; ++Index)
		{
			Sight.TestSight(Eye, FVector(500.0 + (Index % 40) * 100.0, 2300.0, 160.0));
		}
		const double TraceUs = (FPlatformTime::Seconds() - Start) * 1e6 / 2000.0;
		AddInfo(FString::Printf(TEXT("one VerseSight trace: %.2f us"), TraceUs));
		Sight.Calls = 0;

		FVerseBeliefMapConfig Config;
		Config.SelfPlayerId = SelfId;
		Config.ArenaBox = FBox(FVector(0.0, 0.0, -100.0), FVector(5000.0, 4000.0, 1200.0));
		FVerseBeliefWorld World;
		World.Sight = &Sight;
		FVerseBeliefMap Map;
		Map.Initialize(Source, Config, World);

		uint32 NowMs = 1000;
		int32 Steps = 0;
		int32 MaxTraces = 0;
		double StepSeconds = 0.0;
		double WorstStep = 0.0;
		const int32 Ticks = 1800;
		const double TickStart = FPlatformTime::Seconds();
		for (int32 Tick = 0; Tick < Ticks; ++Tick)
		{
			NowMs += 17;
			// 15 s turning on the post, then 15 s walking along the hall at 4.5 m/s.
			FVector Feet = PostFeet;
			float Yaw = float(Tick % 720) * 0.5f;
			if (Tick >= 900)
			{
				Feet.X = 500.0 + FMath::Fmod((Tick - 900) * 7.5, 4000.0);
				Yaw = 0.f;
			}
			const int32 Before = Sight.Calls;
			const double T0 = FPlatformTime::Seconds();
			const bool bStep = Map.ApplyFrame(SelfFrame(NowMs, Feet, Yaw), World);
			const double Elapsed = FPlatformTime::Seconds() - T0;
			if (bStep)
			{
				++Steps;
				StepSeconds += Elapsed;
				WorstStep = FMath::Max(WorstStep, Elapsed);
				MaxTraces = FMath::Max(MaxTraces, Sight.Calls - Before);
			}
		}
		const double TickMs = (FPlatformTime::Seconds() - TickStart) * 1000.0 / Ticks;
		const double StepMs = StepSeconds * 1000.0 / FMath::Max(1, Steps);
		const double TracesPerStep = double(Sight.Calls) / FMath::Max(1, Steps);
		const int32 Budget = Config.MaxCellSightTestsPerStep + Config.MaxPieceSightTestsPerStep;
		TestTrue(FString::Printf(TEXT("traces per step %d <= budget %d"), MaxTraces, Budget), MaxTraces <= Budget);
		TestTrue(FString::Printf(TEXT("amortised %.4f ms per tick within the 0.5 ms bot budget"), TickMs), TickMs <= 0.5);
		AddInfo(FString::Printf(TEXT("map step with real traces: %.4f ms mean, %.4f ms worst, %.1f traces per step (%d cells); %.4f ms per tick"),
			StepMs, WorstStep * 1000.0, TracesPerStep, Map.GetGrid().NumCells(), TickMs));
		SaveProof(TEXT("7.6"), TEXT("belief_trace_cost.json"),
			FString::Printf(TEXT("{\n  \"test\": \"A7.6 belief step with real VerseSight traces (Recast fixture arena)\",\n")
							TEXT("  \"cells\": %d,\n  \"traceUs\": %.3f,\n  \"cellTraceBudgetPerStep\": %d,\n  \"pieceTraceBudgetPerStep\": %d,\n")
							TEXT("  \"steps\": %d,\n  \"tracesPerStepMean\": %.2f,\n  \"tracesPerStepMax\": %d,\n")
							TEXT("  \"msPerStepMean\": %.5f,\n  \"msPerStepWorst\": %.5f,\n  \"beliefBudgetMs\": 0.05,\n")
							TEXT("  \"stepWithinBeliefBudget\": %s,\n  \"msPerTickAmortised\": %.5f,\n  \"botBudgetMs\": 0.5,\n  \"pass\": %s\n}\n"),
				Map.GetGrid().NumCells(), TraceUs, Config.MaxCellSightTestsPerStep, Config.MaxPieceSightTestsPerStep, Steps, TracesPerStep,
				MaxTraces, StepMs, WorstStep * 1000.0, StepMs <= 0.05 ? TEXT("true") : TEXT("false"), TickMs,
				HasAnyErrors() ? TEXT("false") : TEXT("true")));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

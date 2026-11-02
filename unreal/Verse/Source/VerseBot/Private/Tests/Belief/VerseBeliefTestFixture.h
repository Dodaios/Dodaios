#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Belief/VerseBeliefGrid.h"
#include "Belief/VerseBeliefMap.h"
#include "CoreMinimal.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Tests/Belief/Fakes/FakeVerseBeliefWorld.h"

namespace VerseBotBeliefTests
{
	constexpr int32 SelfId = 1;
	constexpr int32 OpponentId = 2;

	inline FString ProofDir(const TCHAR* SubTask)
	{
		return FPaths::ProjectSavedDir() / TEXT("Harness/proof/WP07") / SubTask;
	}

	inline void SaveProof(const TCHAR* SubTask, const TCHAR* File, const FString& Json)
	{
		const FString Dir = ProofDir(SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		FFileHelper::SaveStringToFile(Json, *(Dir / File));
	}

	/** World cm of a cell column centre for a fixture whose column (0, 0) is at (50, 50) cm. */
	inline FVector ColumnCentre(int32 X, int32 Y, float Z = 0.f)
	{
		return FVector(50.0 + X * 100.0, 50.0 + Y * 100.0, Z);
	}

	/**
	 * The lane fixture (Content/Verse/Test/WP07 graybox in code): a 50 x 40 m hall, one level.
	 * Wall A along y = 20 m with a 2 m door at x 24-26 m; wall B along y = 26 m. Between them a
	 * 6 m lane, hidden from the observer post at (25, 5) m except through the door.
	 * Walls are 4 m tall, so sight at 1.0 and 1.6 m equals the 2D line of sight.
	 */
	struct FLaneFixture
	{
		FFakeVerseBeliefWorld World;
		FVerseBeliefGridSource Source;

		static constexpr int32 Columns = 50;
		static constexpr int32 Rows = 40;

		FLaneFixture()
		{
			World.AddWall(FVector(200.0, 1990.0, 0.0), FVector(2400.0, 2010.0, 400.0));
			World.AddWall(FVector(2600.0, 1990.0, 0.0), FVector(4800.0, 2010.0, 400.0));
			World.AddWall(FVector(200.0, 2590.0, 0.0), FVector(4800.0, 2610.0, 400.0));
			BuildSource();
		}

		void BuildSource()
		{
			Source = FVerseBeliefGridSource();
			Source.Origin = FVector2D(50.0, 50.0);
			Source.CellSizeCm = 100.f;
			for (int32 X = 0; X < Columns; ++X)
			{
				for (int32 Y = 0; Y < Rows; ++Y)
				{
					FVerseBeliefCellDesc& Cell = Source.Cells.AddDefaulted_GetRef();
					Cell.Column = FIntPoint(X, Y);
				}
			}
			const FFakeVerseBeliefWorld* Geometry = &World;
			const TArray<FVerseBeliefCellDesc>* Cells = &Source.Cells;
			Source.AreNeighboursConnected = [Geometry, Cells](int32 A, int32 B) {
				const FIntPoint Ca = (*Cells)[A].Column;
				const FIntPoint Cb = (*Cells)[B].Column;
				const FVector Pa = ColumnCentre(Ca.X, Ca.Y, 50.f);
				const FVector Pb = ColumnCentre(Cb.X, Cb.Y, 50.f);
				for (const FFakeWall& Wall : Geometry->Walls)
				{
					if (FFakeVerseBeliefWorld::SegmentHits(Wall.Box, Pa, Pb))
					{
						return false;
					}
				}
				return true;
			};
		}

		FVerseBeliefMapConfig Config() const
		{
			FVerseBeliefMapConfig Out;
			Out.SelfPlayerId = SelfId;
			Out.ArenaBox = FBox(FVector(0.0, 0.0, -100.0), FVector(5000.0, 4000.0, 1200.0));
			Out.MaxCellSightTestsPerStep = 100000;
			Out.MaxPieceSightTestsPerStep = 100000;
			Out.SpawnPoints = {ColumnCentre(5, 35), ColumnCentre(47, 37), ColumnCentre(5, 2), ColumnCentre(45, 2)};
			return Out;
		}

		FVerseBeliefWorld BeliefWorld() const
		{
			FVerseBeliefWorld Out;
			Out.Sight = &World;
			Out.Pieces = &World;
			return Out;
		}
	};

	/** A frame with the observer's own HUD state only. */
	inline FVersePerceptFrame SelfFrame(uint32 NowMs, const FVector& Feet, float YawDeg)
	{
		FVersePerceptFrame Frame;
		Frame.ServerTimeMs = NowMs;
		Frame.Self.Location = Feet;
		Frame.Self.EyeLocation = Feet + FVector(0.0, 0.0, 165.0);
		Frame.Self.ViewRotation = FRotator(0.f, YawDeg, 0.f);
		Frame.Self.Phase = EVerseCombatPhase::Alive;
		return Frame;
	}

	/** Three-level 50 x 40 m grid (6,000 cells) with stair links, no walls: the A7.6 cost case. */
	inline FVerseBeliefGridSource MakeThreeLevelSource()
	{
		FVerseBeliefGridSource Source;
		Source.Origin = FVector2D(50.0, 50.0);
		Source.CellSizeCm = 100.f;
		for (int32 Level = 0; Level < 3; ++Level)
		{
			for (int32 X = 0; X < 50; ++X)
			{
				for (int32 Y = 0; Y < 40; ++Y)
				{
					FVerseBeliefCellDesc& Cell = Source.Cells.AddDefaulted_GetRef();
					Cell.Column = FIntPoint(X, Y);
					Cell.Level = EVerseArenaLevel(Level);
					Cell.FloorZ = 400.f * Level;
					Cell.Zone = uint8((X / 10) + 5 * (Y / 20));
				}
			}
		}
		auto IndexOf = [](int32 X, int32 Y, int32 Level) { return (Level * 50 + X) * 40 + Y; };
		for (int32 Stair = 0; Stair < 8; ++Stair)
		{
			const int32 X = 3 + Stair * 6;
			for (int32 Level = 0; Level < 2; ++Level)
			{
				FVerseBeliefLinkDesc& Link = Source.Links.AddDefaulted_GetRef();
				Link.From = IndexOf(X, 10 + Level * 10, Level);
				Link.To = IndexOf(X + 1, 10 + Level * 10, Level + 1);
				Link.TraversalS = 1.5f;
				Link.Kind = EVerseBeliefLinkKind::Stair;
			}
		}
		return Source;
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

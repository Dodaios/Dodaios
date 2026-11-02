#pragma once

#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Misc/AutomationTest.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VerseDestructionManager.h"
#include "Pieces/VerseDestructionSim.h"
#include "Pieces/VersePieceTypes.h"
#include "VerseRng.h"

// Shared fixtures of the Verse.Destruction.* tests: one placeholder piece per class with the
// class's real dimensions and material thickness (the shapes art/verse/kit/destructible builds),
// a seeded test arena, and helpers that drive the simulation in fixed server ticks.

#define VERSE_DESTRUCTION_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseDestructionTest
{
	inline constexpr uint32 TickMs = 33; // 30 Hz server

	/** Piece-local Intact box of a class (centred on X, floor at Z = 0, thickness along +Y or +Z). */
	inline FBox ClassBox(EVersePieceClass Class)
	{
		switch (Class)
		{
		case EVersePieceClass::WallPanel:
			return FBox(FVector(-120, 0, 0), FVector(120, 0.3, 270));
		case EVersePieceClass::CladdingWall:
			return FBox(FVector(-120, 0, 0), FVector(120, 4.0, 270));
		case EVersePieceClass::ContainerWall:
			return FBox(FVector(-120, 0, 0), FVector(120, 4.0, 259)); // 0.4 cm sheet, 4 cm corrugation depth
		case EVersePieceClass::GlassPane:
			return FBox(FVector(-60, 0, 90), FVector(60, 2.4, 240));
		case EVersePieceClass::CatwalkSegment:
			return FBox(FVector(-120, -60, 0), FVector(120, 60, 3.0));
		case EVersePieceClass::CeilingPanel:
			return FBox(FVector(-60, -60, 0), FVector(60, 60, 2.5));
		}
		return FBox(FVector(-50), FVector(50));
	}

	inline FVersePieceDef MakePiece(EVersePieceClass Class, const FVector& Location, int32 Serial)
	{
		FVersePieceDef Def;
		Def.Guid = FGuid(0x0600u, uint32(Class), uint32(Serial), 0x1u);
		Def.Class = Class;
		Def.Material = VerseMaterialOfClass(Class);
		Def.Transform = FTransform(Location);
		Def.IntactBounds = ClassBox(Class);
		const bool bWall = Class == EVersePieceClass::WallPanel || Class == EVersePieceClass::CladdingWall || Class == EVersePieceClass::ContainerWall;
		if (bWall)
		{
			const FBox B = Def.IntactBounds;
			// Two holed variants (left, right) and two breached variants (standing, low).
			Def.HoledCentroids = {FVector(-60, 0, 140), FVector(60, 0, 140)};
			Def.HoledBounds = {B, B};
			Def.BreachedCentroids = {FVector(0, 0, 110), FVector(0, 0, 50)};
			Def.BreachedBounds = {FBox(B.Min, FVector(B.Max.X, B.Max.Y, B.Max.Z)), FBox(B.Min, B.Max)};
			Def.MantleLinks.Add({FVector(0, -60, 0), FVector(0, 60, 0)});
		}
		if (Class == EVersePieceClass::CatwalkSegment)
		{
			Def.DropLinks.Add({FVector(110, 0, 3), FVector(170, 0, -300)});
		}
		return Def;
	}

	/** A dense test arena: container rows plus walls, glass, catwalks and ceiling tiles (about 600 pieces). */
	inline TArray<FVersePieceDef> MakeArena(int32 ContainerRows = 30, int32 PerRow = 8)
	{
		TArray<FVersePieceDef> Defs;
		int32 Serial = 0;
		for (int32 Row = 0; Row < ContainerRows; ++Row)
		{
			for (int32 Col = 0; Col < PerRow; ++Col)
			{
				Defs.Add(MakePiece(EVersePieceClass::ContainerWall, FVector(Col * 245.0, Row * 600.0, 0), Serial++));
			}
			Defs.Add(MakePiece(EVersePieceClass::GlassPane, FVector(-200.0, Row * 600.0 + 60.0, 0), Serial++));
			Defs.Add(MakePiece(EVersePieceClass::CeilingPanel, FVector(100.0, Row * 600.0 + 60.0, 280.0), Serial++));
		}
		for (int32 Index = 0; Index < 150; ++Index)
		{
			Defs.Add(MakePiece(Index % 2 ? EVersePieceClass::WallPanel : EVersePieceClass::CladdingWall,
				FVector(3000.0 + (Index % 10) * 250.0, (Index / 10) * 600.0, 0), Serial++));
		}
		for (int32 Index = 0; Index < 90; ++Index)
		{
			Defs.Add(MakePiece(Index % 3 ? EVersePieceClass::CatwalkSegment : EVersePieceClass::CeilingPanel,
				FVector(-1500.0 + (Index % 9) * 250.0, (Index / 9) * 1200.0, 450.0), Serial++));
		}
		return Defs;
	}

	inline TArray<FVector> Docks(int32 Count)
	{
		TArray<FVector> Out;
		for (int32 Index = 0; Index < Count; ++Index)
		{
			Out.Add(FVector(-800.0, Index * 400.0, 600.0));
		}
		return Out;
	}

	inline FVersePieceDamage Bolt(const FVersePieceDef& Def, float Amount = 10.f, const FVector& Local = FVector(0, 0, 140))
	{
		FVersePieceDamage Damage;
		Damage.Cause = EVerseFractureCause::Bolt;
		Damage.Amount = Amount;
		Damage.Location = Def.Transform.TransformPosition(Local);
		Damage.Direction = FVector(0, 1, 0);
		Damage.InstigatorId = 0;
		return Damage;
	}

	inline FVersePieceDamage Breach(const FVersePieceDef& Def, const FVector& Local = FVector(0, -5, 110))
	{
		FVersePieceDamage Damage;
		Damage.Cause = EVerseFractureCause::Breach;
		Damage.Amount = 1000.f;
		Damage.Location = Def.Transform.TransformPosition(Local);
		Damage.Direction = FVector(0, 1, 0);
		Damage.BreachRadiusCm = 150.f;
		Damage.InstigatorId = 1;
		return Damage;
	}

	/** A knife strike; 5 piece damage, so intact glass cracks instead of shattering at once. */
	inline FVersePieceDamage Melee(const FVersePieceDef& Def, float Amount = 5.f)
	{
		FVersePieceDamage Damage = Bolt(Def, Amount);
		Damage.Cause = EVerseFractureCause::Melee;
		return Damage;
	}

	/** A bare game world (subsystems, no game mode); ticks only what the test ticks. */
	struct FTestWorld
	{
		UWorld* World = nullptr;

		explicit FTestWorld(const TCHAR* Name)
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, Name);
			FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
			Context.SetCurrentWorld(World);
			World->InitializeActorsForPlay(FURL());
		}

		~FTestWorld()
		{
			GEngine->DestroyWorldContext(World);
			World->DestroyWorld(false);
		}

		void Advance(float Seconds)
		{
			World->Tick(LEVELTICK_TimeOnly, Seconds);
		}

		AVerseDestructible* SpawnPiece(const FVersePieceDef& Def)
		{
			FActorSpawnParameters Params;
			Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
			AVerseDestructible* Piece = World->SpawnActor<AVerseDestructible>(AVerseDestructible::StaticClass(), Def.Transform, Params);
			Piece->PieceClass = Def.Class;
			Piece->Material = Def.Material;
			Piece->FallbackIntactBounds = Def.IntactBounds;
			Piece->SetPieceGuid(Def.Guid);
			for (int32 Index = 0; Index < Def.HoledCentroids.Num(); ++Index)
			{
				Piece->HoledVariants.AddDefaulted_GetRef().OpeningCentroid = Def.HoledCentroids[Index];
			}
			for (int32 Index = 0; Index < Def.BreachedCentroids.Num(); ++Index)
			{
				Piece->BreachedVariants.AddDefaulted_GetRef().OpeningCentroid = Def.BreachedCentroids[Index];
			}
			return Piece;
		}

		AVerseDestructionManager* SpawnManager(bool bClient, int32 NumDocks = 0)
		{
			FActorSpawnParameters Params;
			Params.bDeferConstruction = true;
			AVerseDestructionManager* Manager = World->SpawnActor<AVerseDestructionManager>(AVerseDestructionManager::StaticClass(), FTransform::Identity, Params);
			Manager->DroneDocks = VerseDestructionTest::Docks(NumDocks);
			if (bClient)
			{
				Manager->SetRole(ROLE_SimulatedProxy);
			}
			Manager->FinishSpawning(FTransform::Identity);
			Manager->RegisterPieces();
			return Manager;
		}
	};

	inline bool NeverEncroached(const FBox&) { return false; }

	/** Ticks the simulation from FromMs to ToMs (exclusive) and drains its outputs; returns the time reached. */
	inline uint32 Run(FVerseDestructionSim& Sim, uint32 FromMs, uint32 ToMs, TArray<FVersePendingFracture>* OutEvents = nullptr)
	{
		uint32 Now = FromMs;
		for (; Now < ToMs; Now += TickMs)
		{
			Sim.Tick(Now, [](const FBox&) { return false; });
			TArray<FVersePendingFracture> Events = Sim.DrainEvents();
			if (OutEvents)
			{
				OutEvents->Append(Events);
			}
			Sim.DrainNoise();
			Sim.DrainDirtyItems();
		}
		return Now;
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

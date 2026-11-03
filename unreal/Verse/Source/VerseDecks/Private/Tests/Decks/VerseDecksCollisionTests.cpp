#include "AssetCompilingManager.h"
#include "Components/StaticMeshComponent.h"
#include "Decks/VerseDeckManifest.h"
#include "Dom/JsonObject.h"
#include "Engine/Engine.h"
#include "Engine/StaticMesh.h"
#include "Engine/StaticMeshActor.h"
#include "PhysicsEngine/BodySetup.h"
#include "Engine/OverlapResult.h"
#include "Engine/World.h"
#include "HAL/FileManager.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UObject/Package.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Decks.Collision.*: the simple collision of the WP12 decks against a pawn capsule
// (art-pipeline 5). Each test builds a transient world, spawns every placement of a deck from
// its zone files (`unreal/Verse/Art/Placements/<deck>/`) with the placement's collision
// profile, and queries it with capsule sweeps on the Pawn channel. Only simple collision
// answers those queries, so they check the authored primitives, the auto boxes and the deck
// bounds, never the render triangles.

namespace VerseDecksCollision
{
	/** The default pawn capsule and step height of the character movement. */
	constexpr float CapsuleRadius = 34.f;
	constexpr float CapsuleHalfHeight = 88.f;
	constexpr double MaxStepCm = 45.0;
	constexpr double StrideCm = 10.0;

	struct FPlacement
	{
		FString Id;
		FString Piece;
		FString Asset;
		FString Profile;
		FTransform Transform;
	};

	struct FZoneDoc
	{
		FString Zone;
		TArray<FPlacement> Placements;
		TArray<TSharedPtr<FJsonObject>> Rooms;
		TArray<TSharedPtr<FJsonObject>> Sockets;
		FBox Bounds = FBox(ForceInit);
	};

	FVector Vec(const TArray<TSharedPtr<FJsonValue>>& A)
	{
		return A.Num() >= 3 ? FVector(A[0]->AsNumber(), A[1]->AsNumber(), A[2]->AsNumber()) : FVector::ZeroVector;
	}

	bool LoadDeck(FAutomationTestBase& Test, FName Deck, TArray<FZoneDoc>& Out)
	{
		const FString Dir = FPaths::Combine(Verse::Decks::PlacementsDir(), Deck.ToString());
		TArray<FString> Files;
		IFileManager::Get().FindFiles(Files, *FPaths::Combine(Dir, TEXT("*.placement.json")), true, false);
		Files.Sort();
		for (const FString& File : Files)
		{
			FString Text;
			TSharedPtr<FJsonObject> Root;
			if (!FFileHelper::LoadFileToString(Text, *FPaths::Combine(Dir, File)) || !FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) || !Root.IsValid())
			{
				Test.AddError(FString::Printf(TEXT("cannot read %s"), *File));
				return false;
			}
			FZoneDoc& Doc = Out.AddDefaulted_GetRef();
			Doc.Zone = Root->GetStringField(TEXT("zone"));
			const TSharedPtr<FJsonObject>* BoundsObject = nullptr;
			if (Root->TryGetObjectField(TEXT("bounds_cm"), BoundsObject))
			{
				Doc.Bounds = FBox(Vec((*BoundsObject)->GetArrayField(TEXT("min"))), Vec((*BoundsObject)->GetArrayField(TEXT("max"))));
			}
			for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("placements")))
			{
				const TSharedPtr<FJsonObject> Item = Value->AsObject();
				const TArray<TSharedPtr<FJsonValue>>& Q = Item->GetArrayField(TEXT("rotation"));
				const FQuat Rotation(Q[0]->AsNumber(), Q[1]->AsNumber(), Q[2]->AsNumber(), Q[3]->AsNumber());
				FPlacement& Placement = Doc.Placements.AddDefaulted_GetRef();
				Placement.Id = Item->GetStringField(TEXT("id"));
				Placement.Piece = Item->GetStringField(TEXT("piece"));
				Placement.Asset = Item->GetStringField(TEXT("asset"));
				Placement.Profile = Item->GetStringField(TEXT("collision"));
				Placement.Transform = FTransform(Rotation.GetNormalized(), Vec(Item->GetArrayField(TEXT("location"))), Vec(Item->GetArrayField(TEXT("scale"))));
			}
			for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("rooms")))
			{
				Doc.Rooms.Add(Value->AsObject());
			}
			for (const TSharedPtr<FJsonValue>& Value : Root->GetArrayField(TEXT("sockets")))
			{
				Doc.Sockets.Add(Value->AsObject());
			}
		}
		return Test.TestTrue(FString::Printf(TEXT("%s has zone files"), *Deck.ToString()), Out.Num() > 0);
	}

	/** A transient game world holding a deck's collision; destroyed with the object. */
	struct FDeckWorld
	{
		UWorld* World = nullptr;
		int32 Spawned = 0;
		TArray<FString> Missing;

		explicit FDeckWorld(const TArray<FZoneDoc>& Zones)
		{
			const FName Name = MakeUniqueObjectName(GetTransientPackage(), UWorld::StaticClass(), TEXT("VerseDecksCollision"));
			World = UWorld::CreateWorld(EWorldType::Game, false, Name, GetTransientPackage());
			TMap<FString, UStaticMesh*> Meshes;
			for (const FZoneDoc& Zone : Zones)
			{
				for (const FPlacement& Placement : Zone.Placements)
				{
					UStaticMesh*& Mesh = Meshes.FindOrAdd(Placement.Asset);
					if (Mesh == nullptr)
					{
						Mesh = LoadObject<UStaticMesh>(nullptr, *Placement.Asset, nullptr, LOAD_NoWarn | LOAD_Quiet);
					}
					if (Mesh == nullptr)
					{
						Missing.AddUnique(Placement.Asset);
						continue;
					}
					// Meshes build their bodies asynchronously in the editor; a mesh still compiling
					// has no collision yet.
					FAssetCompilingManager::Get().FinishAllCompilation();
					FActorSpawnParameters Params;
					Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
					Params.ObjectFlags |= RF_Transient;
					AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Placement.Transform, Params);
					if (Actor == nullptr)
					{
						continue;
					}
					UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
					Component->SetMobility(EComponentMobility::Movable);
					Component->SetStaticMesh(Mesh);
					Component->SetCollisionProfileName(FName(*Placement.Profile));
					Actor->SetActorTransform(Placement.Transform);
					++Spawned;
				}
			}
		}

		~FDeckWorld()
		{
			if (World)
			{
				World->DestroyWorld(false);
				World->RemoveFromRoot();
			}
		}

		bool Sweep(const FVector& From, const FVector& To, FHitResult& Hit) const
		{
			FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseDecksCollision), false);
			return World->SweepSingleByChannel(Hit, From, To, FQuat::Identity, ECC_Pawn, FCollisionShape::MakeCapsule(CapsuleRadius, CapsuleHalfHeight), Params);
		}

		/** Capsule centre standing on the floor under `At` (searched from `Up` above to `Down` below). */
		static FString NameOf(const FHitResult& Hit)
		{
			const AActor* Actor = Hit.GetActor();
			if (Actor == nullptr)
			{
				return TEXT("nothing");
			}
			const AStaticMeshActor* Mesh = Cast<AStaticMeshActor>(Actor);
			const UStaticMesh* Asset = Mesh ? Mesh->GetStaticMeshComponent()->GetStaticMesh() : nullptr;
			return Asset ? Asset->GetName() : Actor->GetName();
		}

		/** What is around `At`: overlaps of a 1 m box and a line trace down, for failure messages. */
		FString Around(const FVector& At) const
		{
			TArray<FOverlapResult> Overlaps;
			World->OverlapMultiByObjectType(Overlaps, At, FQuat::Identity, FCollisionObjectQueryParams(FCollisionObjectQueryParams::AllObjects), FCollisionShape::MakeBox(FVector(50.0, 50.0, 200.0)));
			TArray<FString> Names;
			for (const FOverlapResult& Overlap : Overlaps)
			{
				const AStaticMeshActor* Mesh = Cast<AStaticMeshActor>(Overlap.GetActor());
				const UStaticMesh* Asset = Mesh ? Mesh->GetStaticMeshComponent()->GetStaticMesh() : nullptr;
				const UPrimitiveComponent* Component = Overlap.GetComponent();
				Names.Add(FString::Printf(TEXT("%s/%s"), Asset ? *Asset->GetName() : TEXT("?"), Component ? *Component->GetCollisionProfileName().ToString() : TEXT("?")));
			}
			FHitResult Line;
			const bool bLine = World->LineTraceSingleByChannel(Line, At + FVector(0, 0, 200.0), At - FVector(0, 0, 400.0), ECC_Pawn);
			return FString::Printf(TEXT("overlaps [%s]; line down %s z %.1f"), *FString::Join(Names, TEXT(", ")), bLine ? *NameOf(Line) : TEXT("none"), bLine ? Line.ImpactPoint.Z : 0.0);
		}

		/** Capsule centre standing on the floor under `At`; `Why` says what went wrong. */
		bool Floor(const FVector& At, double Up, double Down, FVector& Centre, FString* Why = nullptr) const
		{
			FHitResult Hit;
			if (!Sweep(At + FVector(0, 0, Up), At - FVector(0, 0, Down), Hit))
			{
				if (Why)
				{
					*Why = FString::Printf(TEXT("no floor below (%s)"), *Around(At));
				}
				return false;
			}
			if (Hit.bStartPenetrating)
			{
				if (Why)
				{
					*Why = FString::Printf(TEXT("starts inside %s"), *NameOf(Hit));
				}
				return false;
			}
			if (Hit.ImpactNormal.Z < FMath::Cos(FMath::DegreesToRadians(46.0)))
			{
				if (Why)
				{
					*Why = FString::Printf(TEXT("too steep on %s (normal z %.2f)"), *NameOf(Hit), Hit.ImpactNormal.Z);
				}
				return false;
			}
			// Stand a hair above the contact, so the next sweep does not start touching the floor.
			Centre = Hit.Location + FVector(0, 0, 1.0);
			return true;
		}

		/**
		 * Walks a capsule from `From` to `To` (feet positions) the way character movement does:
		 * step up at most MaxStepCm, move a stride, drop onto the floor. Fails on a wall, on a
		 * step higher than MaxStepCm, or on a drop with no walkable floor within reach.
		 */
		bool Walk(const FVector& From, const FVector& To, FVector& End, FString& Why) const
		{
			FVector Centre;
			FString FloorWhy;
			if (!Floor(From + FVector(0, 0, CapsuleHalfHeight), 120.0, 200.0, Centre, &FloorWhy))
			{
				Why = FString::Printf(TEXT("start %s: %s"), *From.ToCompactString(), *FloorWhy);
				return false;
			}
			const FVector Flat(To.X - From.X, To.Y - From.Y, 0.0);
			const int32 Steps = FMath::CeilToInt(Flat.Size() / StrideCm);
			const FVector Stride = Flat / FMath::Max(1, Steps);
			FString Trail;
			for (int32 Step = 0; Step < Steps; ++Step)
			{
				if (Step % 3 == 0)
				{
					Trail += FString::Printf(TEXT(" %.0f/%.0f"), Centre.X, Centre.Z - CapsuleHalfHeight);
				}
				FHitResult Hit;
				const FVector Raised = Centre + FVector(0, 0, MaxStepCm);
				if (Sweep(Centre, Raised, Hit))
				{
					Why = FString::Printf(TEXT("no head room at %s under %s"), *Centre.ToCompactString(), *NameOf(Hit));
					return false;
				}
				if (Sweep(Raised, Raised + Stride, Hit))
				{
					Why = FString::Printf(TEXT("blocked at %s by %s at %s; feet x/z:%s"), *Raised.ToCompactString(), *NameOf(Hit), *Hit.ImpactPoint.ToCompactString(), *Trail);
					return false;
				}
				FVector Next;
				if (!Floor(Raised + Stride, 0.0, MaxStepCm * 2.0 + 30.0, Next, &FloorWhy))
				{
					Why = FString::Printf(TEXT("after %s: %s; feet x/z:%s"), *(Raised + Stride).ToCompactString(), *FloorWhy, *Trail);
					return false;
				}
				Centre = Next;
			}
			End = Centre - FVector(0, 0, CapsuleHalfHeight);
			return true;
		}
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksPitStairsTest, "Verse.Decks.Collision.PitStairs", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseDecksPitStairsTest::RunTest(const FString&)
{
	using namespace VerseDecksCollision;
	TArray<FZoneDoc> Zones;
	if (!LoadDeck(*this, TEXT("bridge"), Zones))
	{
		return true;
	}
	const FDeckWorld Deck(Zones);
	TestEqual(TEXT("every bridge asset loads"), Deck.Missing.Num(), 0);
	int32 Flights = 0;
	for (const FZoneDoc& Zone : Zones)
	{
		for (const FPlacement& Placement : Zone.Placements)
		{
			if (!Placement.Piece.StartsWith(TEXT("SM_Stairs_")))
			{
				continue;
			}
			// SM_Stairs_<w>_H<rise>: the flight descends along local +X from the top edge at 0
			// to the bottom floor at (rise / riser - 1) treads of 30 cm (kit/architecture/structure.py).
			FString Width, Rise;
			Placement.Piece.RightChop(10).Split(TEXT("_H"), &Width, &Rise);
			const double RiseCm = FCString::Atod(*Rise);
			const double RunCm = (FMath::RoundToDouble(RiseCm / 20.0) - 1.0) * 30.0;
			const FVector Top = Placement.Transform.TransformPosition(FVector(-70.0, 0.0, 0.0));
			const FVector Bottom = Placement.Transform.TransformPosition(FVector(RunCm + 70.0, 0.0, -RiseCm));
			FVector End;
			FString Why;
			if (Deck.Walk(Top, Bottom, End, Why))
			{
				TestEqual(FString::Printf(TEXT("%s: down at the pit floor"), *Placement.Id), End.Z, Bottom.Z, 12.0);
			}
			else
			{
				AddError(FString::Printf(TEXT("%s: cannot walk down: %s"), *Placement.Id, *Why));
			}
			if (Deck.Walk(Bottom, Top, End, Why))
			{
				TestEqual(FString::Printf(TEXT("%s: up on the walkway"), *Placement.Id), End.Z, Top.Z, 12.0);
			}
			else
			{
				AddError(FString::Printf(TEXT("%s: cannot walk up: %s"), *Placement.Id, *Why));
			}
			++Flights;
		}
	}
	TestEqual(TEXT("both crew pits have two flights each"), Flights, 4);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksPerimeterTest, "Verse.Decks.Collision.Perimeter", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseDecksPerimeterTest::RunTest(const FString&)
{
	using namespace VerseDecksCollision;
	static const TCHAR* Decks[] = { TEXT("bridge"), TEXT("ops"), TEXT("engineering") };
	static const TCHAR* Kinds[] = { TEXT("stand"), TEXT("spawn"), TEXT("waypoint"), TEXT("lift") };
	for (const TCHAR* DeckName : Decks)
	{
		TArray<FZoneDoc> Zones;
		if (!LoadDeck(*this, DeckName, Zones))
		{
			continue;
		}
		const FDeckWorld Deck(Zones);
		TestEqual(FString::Printf(TEXT("%s: every asset loads"), DeckName), Deck.Missing.Num(), 0);
		FBox All(ForceInit);
		for (const FZoneDoc& Zone : Zones)
		{
			All += Zone.Bounds;
		}
		All = All.ExpandBy(300.0);
		int32 Probes = 0;
		TArray<FString> Leaks;
		for (const FZoneDoc& Zone : Zones)
		{
			int32 PerZone = 0;
			for (const TSharedPtr<FJsonObject>& Socket : Zone.Sockets)
			{
				const FString Kind = Socket->GetStringField(TEXT("kind"));
				bool bKind = false;
				for (const TCHAR* Wanted : Kinds)
				{
					bKind |= Kind == Wanted;
				}
				if (PerZone >= 6 || !bKind)
				{
					continue;
				}
				const FVector Feet = Vec(Socket->GetArrayField(TEXT("location")));
				FVector Centre;
				FString Why;
				if (!Deck.Floor(Feet + FVector(0, 0, CapsuleHalfHeight), 60.0, 120.0, Centre, &Why))
				{
					// A stand socket can sit against a console; it is not a probe then.
					AddInfo(FString::Printf(TEXT("%s/%s at %s: %s"), *Zone.Zone, *Socket->GetStringField(TEXT("id")), *Feet.ToCompactString(), *Why));
					continue;
				}
				++PerZone;
				++Probes;
				for (int32 Dir = 0; Dir < 8; ++Dir)
				{
					const double Angle = Dir * UE_DOUBLE_PI / 4.0;
					const FVector Far = Centre + FVector(FMath::Cos(Angle), FMath::Sin(Angle), 0.0) * 12000.0;
					FHitResult Hit;
					const FVector Start = Centre + FVector(0, 0, 5.0);
					if (!Deck.Sweep(Start, Far + FVector(0, 0, 5.0), Hit) || !All.IsInside(Hit.Location))
					{
						Leaks.Add(FString::Printf(TEXT("%s/%s: open toward %.0f deg"), *Zone.Zone, *Socket->GetStringField(TEXT("id")), Dir * 45.0));
					}
				}
			}
		}
		TestTrue(FString::Printf(TEXT("%s: probes in most zones (%d probes, %d zones)"), DeckName, Probes, Zones.Num()), Probes >= Zones.Num());
		for (int32 Index = 0; Index < FMath::Min(Leaks.Num(), 12); ++Index)
		{
			AddError(FString::Printf(TEXT("%s: %s"), DeckName, *Leaks[Index]));
		}
		TestEqual(FString::Printf(TEXT("%s: the deck is closed for a pawn (%d probes)"), DeckName, Probes), Leaks.Num(), 0);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDecksBoundsBoxesTest, "Verse.Decks.Collision.BoundsKeepTheirTurn", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseDecksBoundsBoxesTest::RunTest(const FString&)
{
	// The bounds of the round reactor hall are turned boxes; the import must keep the turn.
	using namespace VerseDecksCollision;
	TArray<FZoneDoc> Zones;
	if (!LoadDeck(*this, TEXT("engineering"), Zones))
	{
		return true;
	}
	int32 Boxes = 0;
	int32 Turned = 0;
	for (const FZoneDoc& Zone : Zones)
	{
		for (const FPlacement& Placement : Zone.Placements)
		{
			if (!Placement.Id.Contains(TEXT("_bounds_")))
			{
				continue;
			}
			const UStaticMesh* Mesh = LoadObject<UStaticMesh>(nullptr, *Placement.Asset, nullptr, LOAD_NoWarn | LOAD_Quiet);
			const UBodySetup* Body = Mesh ? Mesh->GetBodySetup() : nullptr;
			if (!TestNotNull(*FString::Printf(TEXT("%s has a body"), *Placement.Asset), Body))
			{
				continue;
			}
			TestEqual(FString::Printf(TEXT("%s: boxes only"), *Placement.Asset), Body->AggGeom.ConvexElems.Num(), 0);
			for (const FKBoxElem& Box : Body->AggGeom.BoxElems)
			{
				++Boxes;
				const double Yaw = FMath::Fmod(FMath::Abs(Box.Rotation.Yaw), 90.0);
				Turned += Yaw > 1.0 && Yaw < 89.0;
			}
		}
	}
	TestTrue(TEXT("the engineering bounds have boxes"), Boxes > 100);
	TestTrue(FString::Printf(TEXT("turned boxes survive the import (%d of %d)"), Turned, Boxes), Turned > 10);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

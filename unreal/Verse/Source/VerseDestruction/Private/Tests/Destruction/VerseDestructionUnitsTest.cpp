#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Debris/VerseDebrisBudget.h"
#include "Pieces/VerseDestructible.h"
#include "Pieces/VersePieceManifest.h"
#include "Validation/VerseDestructibleValidator.h"

using namespace VerseDestructionTest;

// 6.9: full reset bumps the epoch, sets every item Intact with full HP, recalls drones, dirties
// nav and multicasts the reset event; the burst stays under 16 KB.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionReset, "Verse.Destruction.Reset", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionReset::RunTest(const FString&)
{
	FVerseDestructionSim Sim;
	Sim.Init(MakeArena(), FVerseDestructionSimTuning::Contract(), Docks(3), 5);
	TestTrue(TEXT("arena of about 600 pieces"), Sim.Num() >= 590 && Sim.Num() <= 2000);
	uint32 Now = 0;
	// Break every piece, then let three drones start repairing.
	for (int32 Index = 0; Index < Sim.Num(); ++Index)
	{
		FVersePieceDamage D = Breach(Sim.GetDef(uint16(Index)), FVector(0, 0, 1));
		D.PieceIndex = uint16(Index);
		D.BreachRadiusCm = 1.f; // only the target
		Sim.ApplyDamage(D, Now);
	}
	Now = Run(Sim, 0, 63000);
	TestEqual(TEXT("three drones busy"), Sim.NumActiveDrones(), 3);
	Sim.DrainEvents();
	Sim.FullReset(Now);
	TestEqual(TEXT("epoch bumped"), int32(Sim.GetEpoch()), 1);
	int32 NotIntact = 0;
	for (const FVersePieceItem& Item : Sim.GetItems())
	{
		NotIntact += (Item.State != EVersePieceState::Intact || Item.HealthQ != 255 || Item.Variant != 0) ? 1 : 0;
	}
	TestEqual(TEXT("every item Intact at full HP"), NotIntact, 0);
	TestEqual(TEXT("drones recalled"), Sim.NumActiveDrones(), 0);
	const TArray<FVersePendingFracture> Events = Sim.DrainEvents();
	if (TestEqual(TEXT("one reset event"), Events.Num(), 1))
	{
		TestEqual(TEXT("PieceIndex 0xFFFF"), int32(Events[0].Event.PieceIndex), 0xFFFF);
		TestEqual(TEXT("Cause Reset"), Events[0].Event.Cause, EVerseFractureCause::Reset);
		TestEqual(TEXT("new epoch on the event"), int32(Events[0].Event.Epoch), 1);
		TestTrue(TEXT("the reset is always multicast"), Events[0].bMulticast);
	}
	TestTrue(FString::Printf(TEXT("reset burst under 16 KB (%d bytes)"), Sim.GetLastResetBurstBytes()), Sim.GetLastResetBurstBytes() < 16 * 1024);
	TestEqual(TEXT("every broken item is written once"), Sim.DrainDirtyItems().Num(), Sim.Num());
	TestTrue(TEXT("nav tiles queued for the rebuild"), Sim.GetNav().NumQueued() > 0);
	// A second reset with nothing broken writes nothing.
	Sim.FullReset(Now + 100);
	TestEqual(TEXT("an intact arena costs no items"), Sim.DrainDirtyItems().Num(), 0);
	const int32 RepairsBefore = Sim.GetCounters().Repairs;
	Run(Sim, Now + 100, Now + 70000);
	TestEqual(TEXT("nothing to repair after a reset"), Sim.GetCounters().Repairs, RepairsBefore);
	return true;
}

// 6.7 / A6.4 (logic part): a change dirties old and new proxy bounds +50 cm, at most 4 tiles in
// flight, and a breach's tiles are handed to navigation within 100 ms. Mantle links live while
// Breached, drop links while Destroyed.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionNav, "Verse.Destruction.Nav", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionNav::RunTest(const FString&)
{
	{
		FVerseNavDirtyQueue Queue(4, 50.f);
		Queue.MarkDirty(FBox(FVector(10, 10, 0), FVector(20, 20, 100)));
		TestEqual(TEXT("a small box near the tile corner dirties 4 tiles with the margin"), Queue.NumQueued(), 4);
		Queue.MarkDirty(FBox(FVector(10, 10, 0), FVector(20, 20, 300)));
		TestEqual(TEXT("the same tiles merge"), Queue.NumQueued(), 4);
		Queue.MarkDirty(FBox(FVector(700, 700, 0), FVector(750, 750, 10)));
		TestEqual(TEXT("a far box adds its tile"), Queue.NumQueued(), 5);
		TArray<FVerseNavDirtyQueue::FTile> First = Queue.Release(0);
		TestEqual(TEXT("at most 4 in flight"), First.Num(), 4);
		TestEqual(TEXT("nothing more while 4 are in flight"), Queue.Release(0).Num(), 0);
		TestEqual(TEXT("a finished tile frees a slot"), Queue.Release(1).Num(), 1);
		TestEqual(TEXT("merged z range"), First[0].MaxZ, 350.f);
	}
	// 100 trials: a breach at a random place is released to navigation within 100 ms.
	FVerseRng Rng(0x6A4);
	int32 Within = 0;
	for (int32 Trial = 0; Trial < 100; ++Trial)
	{
		const FVector At(Rng.Range(-5000, 5000), Rng.Range(-3000, 3000), 0);
		FVersePieceDef Wall = MakePiece(EVersePieceClass::ContainerWall, At, Trial);
		Wall.Transform.SetRotation(FQuat(FVector::UpVector, Rng.Range(0, PI)));
		FVerseDestructionSim Sim;
		Sim.Init({Wall}, FVerseDestructionSimTuning::Contract(), {}, uint64(Trial));
		FVersePieceDamage Charge = Breach(Wall);
		Sim.ApplyDamage(Charge, 0);
		FBox Expected = Wall.GetWorldBounds(EVersePieceState::Intact, 0).ExpandBy(50.f);
		const int32 Dirty = Sim.GetNav().NumQueued();
		int32 Released = 0;
		bool bCovers = true;
		uint32 Now = 0;
		for (; Now <= 100 && Sim.GetNav().NumQueued() > 0; Now += TickMs)
		{
			for (const FVerseNavDirtyQueue::FTile& Tile : Sim.GetNav().Release(Sim.GetNav().NumInFlight()))
			{
				++Released;
				bCovers &= Tile.GetBox().Intersect(Expected) && Tile.PieceIndex == 0;
			}
			TestTrue(TEXT("never more than 4 tiles in flight"), Sim.GetNav().NumInFlight() <= 4);
		}
		if (Sim.GetNav().NumQueued() == 0 && Released == Dirty && bCovers && Dirty > 0)
		{
			++Within;
		}
	}
	TestEqual(TEXT("100 of 100 breaches handed to navigation within 100 ms"), Within, 100);

	// Nav links follow the state.
	FVersePieceDef Wall = MakePiece(EVersePieceClass::WallPanel, FVector(100, 0, 0), 1);
	FVersePieceDef Catwalk = MakePiece(EVersePieceClass::CatwalkSegment, FVector(0, 500, 300), 2);
	FVerseDestructionSim Sim;
	Sim.Init({Wall, Catwalk}, FVerseDestructionSimTuning::Contract(), {}, 1);
	EVersePieceNavLinkKind Kind = EVersePieceNavLinkKind::Mantle;
	TestEqual(TEXT("no links while Intact"), Sim.GetLiveNavLinks(0, Kind).Num(), 0);
	FVersePieceDamage D = Breach(Wall, FVector(0, -5, 40));
	D.BreachRadiusCm = 1.f;
	Sim.ApplyDamage(D, 0);
	const TArray<FVersePieceNavLink> Mantle = Sim.GetLiveNavLinks(0, Kind);
	TestEqual(TEXT("a low breach opens its mantle link"), Mantle.Num(), 1);
	TestEqual(TEXT("mantle kind"), Kind, EVersePieceNavLinkKind::Mantle);
	TestTrue(TEXT("links in world space"), Mantle.Num() == 1 && Mantle[0].Start.Equals(FVector(100, -60, 0)));
	D = Breach(Catwalk, FVector(0, 0, 5));
	D.PieceIndex = 1;
	D.BreachRadiusCm = 1.f;
	Sim.ApplyDamage(D, 0);
	TestEqual(TEXT("a destroyed catwalk adds its drop links"), Sim.GetLiveNavLinks(1, Kind).Num(), 1);
	TestEqual(TEXT("drop kind"), Kind, EVersePieceNavLinkKind::Drop);
	TestFalse(TEXT("a destroyed catwalk has no walkable proxy"), Sim.GetPieceBounds(1).IsValid != 0);
	return true;
}

// 6.4: DA_PieceManifest index rule (destruction.md 8).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionManifest, "Verse.Destruction.Manifest", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionManifest::RunTest(const FString&)
{
	UVersePieceManifest* Manifest = NewObject<UVersePieceManifest>();
	TArray<FGuid> Guids;
	FVerseRng Rng(8);
	for (int32 Index = 0; Index < 600; ++Index)
	{
		Guids.Add(FGuid(Rng.NextU32(), Rng.NextU32(), Rng.NextU32(), Rng.NextU32() | 1u));
	}
	TArray<FGuid> Shuffled = Guids;
	for (int32 Index = Shuffled.Num() - 1; Index > 0; --Index)
	{
		Shuffled.Swap(Index, Rng.RangeInt(0, Index));
	}
	FString Error;
	TestTrue(TEXT("builds"), Manifest->Build(Shuffled, &Error));
	TestTrue(TEXT("consistent"), Manifest->IsConsistent());
	UVersePieceManifest* Other = NewObject<UVersePieceManifest>();
	Other->Build(Guids);
	TestEqual(TEXT("order independent: same list"), Manifest->PieceGuids, Other->PieceGuids);
	TestEqual(TEXT("order independent: same hash (server welcome check)"), Manifest->Hash, Other->Hash);
	for (int32 Index = 0; Index < Manifest->PieceGuids.Num(); ++Index)
	{
		if (Manifest->IndexOf(Manifest->PieceGuids[Index]) != Index)
		{
			AddError(TEXT("IndexOf disagrees with the list"));
			break;
		}
	}
	TestEqual(TEXT("unknown GUID"), Manifest->IndexOf(FGuid(1, 2, 3, 4)), int32(INDEX_NONE));
	Other->Build(TArray<FGuid>(Guids.GetData(), 599));
	TestNotEqual(TEXT("a missing piece changes the hash"), Manifest->Hash, Other->Hash);
	TArray<FGuid> TooMany;
	for (int32 Index = 0; Index < 2001; ++Index)
	{
		TooMany.Add(FGuid(1, 2, 3, uint32(Index + 1)));
	}
	TestFalse(TEXT("more than 2,000 pieces per deck fail"), Other->Build(TooMany, &Error));
	TestFalse(TEXT("an invalid GUID fails"), Other->Build({FGuid()}, &Error));
	Manifest->Hash ^= 1u;
	TestFalse(TEXT("a wrong hash is inconsistent"), Manifest->IsConsistent());
	return true;
}

namespace
{
	FVerseMeshSoup Corrugated(float Sheet, float Depth, float Width, float Height, int32 Ribs)
	{
		// Trapezoid ribs as a closed solid: the sheet's two faces follow the same zigzag profile,
		// offset by the sheet thickness, extruded along Z.
		TArray<FVector2D> Outer;
		const float Pitch = Width / Ribs;
		for (int32 Rib = 0; Rib < Ribs; ++Rib)
		{
			const float X = -Width * 0.5f + Rib * Pitch;
			Outer.Add({X, 0});
			Outer.Add({X + Pitch * 0.25f, 0});
			Outer.Add({X + Pitch * 0.375f, Depth});
			Outer.Add({X + Pitch * 0.875f, Depth});
		}
		Outer.Add({Width * 0.5f, 0});
		FVerseMeshSoup Mesh;
		// Build the profile polygon: outer line then the inner line offset by Sheet along +Y (flat parts exact).
		TArray<FVector2D> Poly = Outer;
		for (int32 Index = Outer.Num() - 1; Index >= 0; --Index)
		{
			Poly.Add(Outer[Index] + FVector2D(0, Sheet));
		}
		// Extrude: side quads around the polygon, caps triangulated as quads between the two lines.
		const int32 N = Poly.Num();
		for (int32 Index = 0; Index < N; ++Index)
		{
			const FVector2D& A = Poly[Index];
			const FVector2D& B = Poly[(Index + 1) % N];
			Mesh.AddQuad(FVector(A.X, A.Y, 0), FVector(B.X, B.Y, 0), FVector(B.X, B.Y, Height), FVector(A.X, A.Y, Height));
		}
		const int32 M = Outer.Num();
		for (int32 Index = 0; Index + 1 < M; ++Index)
		{
			const FVector2D O0 = Outer[Index];
			const FVector2D O1 = Outer[Index + 1];
			const FVector2D I0 = O0 + FVector2D(0, Sheet);
			const FVector2D I1 = O1 + FVector2D(0, Sheet);
			Mesh.AddQuad(FVector(O0.X, O0.Y, 0), FVector(I0.X, I0.Y, 0), FVector(I1.X, I1.Y, 0), FVector(O1.X, O1.Y, 0));
			Mesh.AddQuad(FVector(O0.X, O0.Y, Height), FVector(O1.X, O1.Y, Height), FVector(I1.X, I1.Y, Height), FVector(I0.X, I0.Y, Height));
		}
		return Mesh;
	}

	FVerseMeshSoup Grating(float Length, float Width, float Height, float Bar, float Spacing)
	{
		FVerseMeshSoup Mesh;
		for (float Y = -Width * 0.5f; Y + Bar <= Width * 0.5f + 0.01f; Y += Spacing)
		{
			Mesh.AddBox(FVector(-Length * 0.5f, Y, 0), FVector(Length * 0.5f, Y + Bar, Height));
		}
		return Mesh;
	}
}

// A6.6: the validator fails a double-plane wall and a missing proxy and passes the shipped shapes.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionValidator, "Verse.Destruction.Validator", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionValidator::RunTest(const FString&)
{
	using V = UVerseDestructibleValidator;
	struct FShape
	{
		EVersePieceClass Class;
		FVerseMeshSoup Mesh;
	};
	TArray<FShape> Shapes;
	{
		FVerseMeshSoup M;
		M.AddBox(FVector(-120, 0, 0), FVector(120, 0.3, 270));
		Shapes.Add({EVersePieceClass::WallPanel, M});
	}
	{
		FVerseMeshSoup M;
		M.AddBox(FVector(-120, 0, 0), FVector(120, 4.0, 270));
		Shapes.Add({EVersePieceClass::CladdingWall, M});
	}
	Shapes.Add({EVersePieceClass::ContainerWall, Corrugated(0.4f, 4.f, 240.f, 259.f, 8)});
	{
		FVerseMeshSoup M;
		M.AddBox(FVector(-60, 0, 90), FVector(60, 2.4, 240));
		Shapes.Add({EVersePieceClass::GlassPane, M});
	}
	Shapes.Add({EVersePieceClass::CatwalkSegment, Grating(240.f, 120.f, 3.f, 0.5f, 3.f)});
	{
		FVerseMeshSoup M;
		M.AddBox(FVector(-60, -60, 0), FVector(60, 60, 2.5));
		Shapes.Add({EVersePieceClass::CeilingPanel, M});
	}
	for (const FShape& Shape : Shapes)
	{
		const FVerseValidationReport Report = V::CheckSolid(Shape.Mesh, V::ThicknessAxis(Shape.Class), V::RefThicknessCm(Shape.Class));
		TestTrue(FString::Printf(TEXT("%s passes (%.3f cm): %s"), *UEnum::GetValueAsString(Shape.Class), Report.MeasuredThicknessCm,
					 *FString::Join(Report.Errors, TEXT("; "))),
			Report.IsOk());
	}
	{
		// Two coincident-free planes 0.3 cm apart: the old thin double-plane wall.
		FVerseMeshSoup Double;
		Double.AddQuad(FVector(-120, 0, 0), FVector(120, 0, 0), FVector(120, 0, 270), FVector(-120, 0, 270));
		Double.AddQuad(FVector(-120, 0.3, 0), FVector(-120, 0.3, 270), FVector(120, 0.3, 270), FVector(120, 0.3, 0));
		const FVerseValidationReport Report = V::CheckSolid(Double, FVector::RightVector, 0.3f);
		TestFalse(TEXT("a double-plane wall fails"), Report.IsOk());
		TestTrue(TEXT("as not watertight"), Report.Errors.Num() > 0 && Report.Errors[0].Contains(TEXT("watertight")));
	}
	{
		FVerseMeshSoup Box;
		Box.AddBox(FVector(-120, 0, 0), FVector(120, 10.0, 270));
		TestFalse(TEXT("a 10 cm sheet-metal wall fails the thickness rule"), V::CheckSolid(Box, FVector::RightVector, 0.3f).IsOk());
		FVerseMeshSoup Open;
		Open.AddBox(FVector(-120, 0, 0), FVector(120, 0.3, 270));
		Open.Indices.SetNum(Open.Indices.Num() - 6); // drop one face
		TestFalse(TEXT("an open shell fails"), V::CheckClosed(Open).IsOk());
		FVerseMeshSoup Flipped;
		Flipped.AddBox(FVector(-120, 0, 0), FVector(120, 0.3, 270));
		Swap(Flipped.Indices[0], Flipped.Indices[1]); // one triangle wound the wrong way
		TestFalse(TEXT("an inconsistently wound face fails"), V::CheckClosed(Flipped).IsOk());
	}
	// Piece level: a wall actor without proxies or geometry collection fails with clear errors.
	FTestWorld World(TEXT("VerseDestructionValidator"));
	AVerseDestructible* Piece = World.World->SpawnActor<AVerseDestructible>();
	Piece->PieceClass = EVersePieceClass::WallPanel;
	Piece->Material = EVersePenetrationMaterial::SheetMetal;
	Piece->SetPieceGuid(FGuid(6, 6, 6, 6));
	UVersePieceManifest* Manifest = NewObject<UVersePieceManifest>();
	Manifest->Build({FGuid(1, 1, 1, 1)});
	const FVerseValidationReport Report = V::ValidatePiece(*Piece, Manifest);
	const FString All = FString::Join(Report.Errors, TEXT("; "));
	TestTrue(TEXT("missing Intact proxy reported: ") + All, All.Contains(TEXT("missing proxy: Intact")));
	TestTrue(TEXT("missing Holed proxy reported"), All.Contains(TEXT("missing proxy: Holed")));
	TestTrue(TEXT("missing Breached proxy reported"), All.Contains(TEXT("missing proxy: Breached")));
	TestTrue(TEXT("missing geometry collection reported"), All.Contains(TEXT("geometry collection")));
	TestTrue(TEXT("not in the manifest reported"), All.Contains(TEXT("manifest")));
	Piece->Material = EVersePenetrationMaterial::Glass;
	TestTrue(TEXT("a material that does not match the class fails"),
		FString::Join(V::ValidatePiece(*Piece, nullptr).Errors, TEXT(";")).Contains(TEXT("does not match")));
	return true;
}

// 6.5 (budget part): caps, oldest first, lifetimes, Niagara-only types.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionDebrisBudget, "Verse.Destruction.Debris.Budget", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionDebrisBudget::RunTest(const FString&)
{
	FVerseDebrisBudget Budget(FVerseDebrisBudget::FConfig::High());
	FVerseDebrisBudget::FRequest BreachReq;
	BreachReq.Type = EVerseDebrisType::PanelChunks;
	BreachReq.ToState = EVersePieceState::Breached;
	double Now = 0.0;
	int32 FirstId = 0;
	for (int32 Index = 0; Index < 20; ++Index)
	{
		BreachReq.PieceIndex = uint16(Index);
		const FVerseDebrisBudget::FGrant Grant = Budget.Request(BreachReq, Now);
		FirstId = FirstId ? FirstId : Grant.BurstId;
		TestTrue(TEXT("at most 40 per fracture"), Grant.Bodies <= 40);
		TestTrue(TEXT("never above 400 bodies"), Budget.ActiveBodies() <= 400);
		TestTrue(TEXT("never above 32 actors"), Budget.AliveActors() <= 32);
		if (Index == 10)
		{
			TestTrue(TEXT("the oldest is evicted first"), Grant.Evicted.Num() > 0 && Grant.Evicted[0] == FirstId);
		}
		Now += 0.01;
	}
	TestEqual(TEXT("the cap is held at 400"), Budget.ActiveBodies(), 400);
	FVerseDebrisBudget::FRequest GlassReq;
	GlassReq.Type = EVerseDebrisType::GlassShards;
	GlassReq.ToState = EVersePieceState::Destroyed;
	const FVerseDebrisBudget::FGrant GlassGrant = Budget.Request(GlassReq, Now);
	TestEqual(TEXT("glass: no rigid bodies"), GlassGrant.Bodies, 0);
	TestTrue(TEXT("glass: Niagara shards"), GlassGrant.bNiagara);
	FVerseDebrisBudget::FRequest ScorchReq;
	ScorchReq.Type = EVerseDebrisType::MetalShards;
	ScorchReq.ToState = EVersePieceState::Damaged;
	TestEqual(TEXT("Damaged: sparks only"), Budget.Request(ScorchReq, Now).Bodies, 0);
	FVerseDebrisBudget::FRequest TileReq;
	TileReq.Type = EVerseDebrisType::CeilingTile;
	TileReq.ToState = EVersePieceState::Destroyed;
	TestEqual(TEXT("a ceiling tile falls whole"), FVerseDebrisBudget::DesiredBodies(TileReq.Type, TileReq.ToState), 1);
	Budget.Tick(Now + 3.0);
	TestTrue(TEXT("asleep after 3 s"), Budget.GetBursts().Num() > 0 && Budget.GetBursts().Last().bAsleep);
	Budget.Tick(Now + 10.0);
	Budget.Tick(Now + 10.31);
	TestEqual(TEXT("despawned after 10 s plus the 0.3 s fade"), Budget.ActiveBodies(), 0);
	TestEqual(TEXT("and gone"), Budget.GetBursts().Num(), 0);

	FVerseDebrisBudget LowBudget(FVerseDebrisBudget::FConfig::Low());
	for (int32 Index = 0; Index < 10; ++Index)
	{
		LowBudget.Request(BreachReq, 0.0);
	}
	TestTrue(TEXT("Low holds 150"), LowBudget.ActiveBodies() <= 150);
	LowBudget.Tick(6.0);
	LowBudget.Tick(6.31);
	TestEqual(TEXT("Low despawns at 6 s"), LowBudget.GetBursts().Num(), 0);
	TestEqual(TEXT("purge on reset"), Budget.PurgeAll().Num(), 0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Misc/AutomationTest.h"
#include "Penetration/VersePenetrationMath.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	using FShape = TPair<FVector, FVector>;

	/** A slab across the X axis: X from MinX to MaxX, 100 x 100 cm face. */
	FShape Slab(double MinX, double MaxX)
	{
		return FShape(FVector((MinX + MaxX) * 0.5, 0.0, 0.0), FVector((MaxX - MinX) * 0.5, 50.0, 50.0));
	}
}

// WP03.3 on real proxy shapes (art-pipeline.md 5: up to 16 convex shapes; Holed and Breached
// proxies are concave): the shapes of one proxy are one piece, charged once for the solid along
// the ray, and the air between its shapes is free. The sight hole test checks every solid run.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationCompoundTest, "Verse.Destruction.Penetration.Compound", WP03Flags)

bool FVersePenetrationCompoundTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	const EVersePenetrationMaterial Cladding = EVersePenetrationMaterial::CladdingPanel;
	const double LaneY = 300.0;

	// Lane 0: three touching shapes, 3 cm of solid; lane 1: one 3 cm box for reference.
	const FShape Touching[] = {Slab(-0.5, 0.5), Slab(0.5, 1.5), Slab(1.5, 2.5)};
	if (!TestNotNull(TEXT("compound proxy"), W.SpawnCompoundPiece(1, Cladding, FVector(100, 0 * LaneY, 0), Touching)))
	{
		return false;
	}
	W.SpawnPiece(2, Cladding, FVector(101, 1 * LaneY, 0), 3.f);
	// Lane 2: overlapping shapes (a convex decomposition with overlap), 3 cm of solid.
	const FShape Overlapping[] = {Slab(-0.5, 1.2), Slab(0.8, 2.5)};
	W.SpawnCompoundPiece(3, Cladding, FVector(100, 2 * LaneY, 0), Overlapping);
	// Lane 3: concave, two 1 cm runs with 3 cm of air between; lane 4: a 2 cm box for reference.
	const FShape Gap[] = {Slab(-0.5, 0.5), Slab(3.5, 4.5)};
	W.SpawnCompoundPiece(4, Cladding, FVector(100, 3 * LaneY, 0), Gap);
	W.SpawnPiece(5, Cladding, FVector(100, 4 * LaneY, 0), 2.f);
	// Lane 5: a four-run compound, then three single pieces: the compound counts as one piece.
	const FShape Four[] = {Slab(-0.5, -0.3), Slab(1.0, 1.2), Slab(2.5, 2.7), Slab(4.0, 4.2)};
	W.SpawnCompoundPiece(6, EVersePenetrationMaterial::SheetMetal, FVector(100, 5 * LaneY, 0), Four);
	for (int32 I = 0; I < 3; ++I)
	{
		W.SpawnPiece(uint16(7 + I), EVersePenetrationMaterial::SheetMetal, FVector(150 + 30 * I, 5 * LaneY, 0), 0.2f);
	}
	W.Settle();

	auto Fire = [&W](int32 Lane, float Power = 150.f, double Z = 0.0) {
		return W.Penetration->TraceBolt(FVector(0, Lane * LaneY, Z), FVector::ForwardVector, 1000.f, Power, 30.f, 15, 3);
	};

	const TArray<FVersePenetrationHit> Ref3 = Fire(1);
	const TArray<FVersePenetrationHit> Touch = Fire(0);
	if (TestEqual(TEXT("touching shapes: one piece entry"), Touch.Num(), 1) && TestEqual(TEXT("reference: one entry"), Ref3.Num(), 1))
	{
		TestEqual(TEXT("touching shapes: the piece"), Touch[0].PieceIndex, uint16(1));
		TestTrue(FString::Printf(TEXT("touching shapes: 3 cm traced (%.4f)"), Touch[0].TracedThicknessCm),
			VerseWP03Test::Near(Touch[0].TracedThicknessCm, 3.0, 1e-3));
		TestTrue(TEXT("touching shapes: entry and exit on the outer faces"),
			VerseWP03Test::Near(Touch[0].Entry.X, 99.5, 1e-3) && VerseWP03Test::Near(Touch[0].Exit.X, 102.5, 1e-3));
		TestTrue(TEXT("touching shapes cost what one 3 cm box costs"), VerseWP03Test::Near(Touch[0].PowerLeft, Ref3[0].PowerLeft, 1e-3)
			&& VerseWP03Test::Near(Touch[0].DamageLeft, Ref3[0].DamageLeft, 1e-4));
	}
	const TArray<FVersePenetrationHit> Over = Fire(2);
	if (TestEqual(TEXT("overlapping shapes: one piece entry"), Over.Num(), 1))
	{
		TestTrue(FString::Printf(TEXT("overlapping shapes: 3 cm traced (%.4f)"), Over[0].TracedThicknessCm),
			VerseWP03Test::Near(Over[0].TracedThicknessCm, 3.0, 1e-3));
	}

	const TArray<FVersePenetrationHit> Ref2 = Fire(4);
	const TArray<FVersePenetrationHit> Concave = Fire(3);
	if (TestEqual(TEXT("concave proxy: one piece entry"), Concave.Num(), 1) && TestEqual(TEXT("2 cm reference: one entry"), Ref2.Num(), 1))
	{
		TestTrue(FString::Printf(TEXT("concave proxy: 2 cm of solid traced, the 3 cm of air left out (%.4f)"), Concave[0].TracedThicknessCm),
			VerseWP03Test::Near(Concave[0].TracedThicknessCm, 2.0, 1e-3));
		TestTrue(TEXT("concave proxy: exit on the far run"), VerseWP03Test::Near(Concave[0].Exit.X, 104.5, 1e-3));
		TestTrue(TEXT("concave proxy costs what 2 cm of solid costs"), VerseWP03Test::Near(Concave[0].PowerLeft, Ref2[0].PowerLeft, 1e-3));
	}

	const TArray<FVersePenetrationHit> Limit = Fire(5, 1000.f);
	if (TestEqual(TEXT("four-run proxy and three pieces: four entries"), Limit.Num(), 4))
	{
		TestEqual(TEXT("the four-run proxy is the first piece"), Limit[0].PieceIndex, uint16(6));
		TestTrue(TEXT("three pieces pass"), Limit[0].bPassed && Limit[1].bPassed && Limit[2].bPassed);
		TestFalse(TEXT("the 4th piece stops the bolt (the proxy counted once)"), Limit[3].bPassed);
		TestTrue(TEXT("four-run proxy: 0.8 cm of solid"), VerseWP03Test::Near(Limit[0].TracedThicknessCm, 0.8, 1e-3));
	}

	// Sight through a concave sheet proxy: thin runs 4 cm apart. A hole is a cylinder along its
	// axis; a ray at 30 deg off the axis passes the hole in the first run but meets solid in the
	// second, so it is blocked until the second run has a hole where the ray crosses it.
	W.Holes->ResetAll(1);
	const FShape Sheets[] = {Slab(-0.15, 0.15), Slab(3.85, 4.15)};
	W.SpawnCompoundPiece(20, EVersePenetrationMaterial::SheetMetal, FVector(100, 6 * LaneY, 0), Sheets);
	W.Settle();
	const FVector Eye(0, 6 * LaneY, 0);
	const FVector Slant = FRotator(0.0, 30.0, 0.0).RotateVector(FVector::ForwardVector);
	const FVector SlantEye = FVector(100, 6 * LaneY, 0) - Slant * 100.0;
	TestFalse(TEXT("no holes: the sheets block"), W.Penetration->TestSight(Eye, Eye + FVector(200, 0, 0)));
	W.Holes->AddHole(20, EVersePenetrationMaterial::SheetMetal, FVector::ZeroVector, FVector::ForwardVector, 15, 1000);
	TestTrue(TEXT("one hole on the axis: both runs lie inside its cylinder"), W.Penetration->TestSight(Eye, Eye + FVector(200, 0, 0)));
	TestFalse(TEXT("30 deg ray: passes the first run's hole, the second run blocks"),
		W.Penetration->TestSight(SlantEye, SlantEye + Slant * 200.0));
	const double Lateral = 4.0 * FMath::Tan(FMath::DegreesToRadians(30.0));
	W.Holes->AddHole(20, EVersePenetrationMaterial::SheetMetal, FVector(4.0, Lateral, 0.0), FVector::ForwardVector, 15, 1001);
	TestTrue(TEXT("30 deg ray with a hole in each run: see-through"), W.Penetration->TestSight(SlantEye, SlantEye + Slant * 200.0));
	const TArray<FVersePenetrationHit> Through =
		W.Penetration->TraceBolt(SlantEye, Slant, 200.f, 100.f, 30.f, 15, 3);
	TestEqual(TEXT("the bolt flies through both holes without cost"), Through.Num(), 0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

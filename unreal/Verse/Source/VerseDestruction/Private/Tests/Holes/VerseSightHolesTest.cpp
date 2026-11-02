#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Holes/VerseBoltHoleComponent.h"
#include "Misc/AutomationTest.h"
#include "Penetration/VersePenetrationMath.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"
#include "VerseRng.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	/** Distance of a piece-local point from a hole's (decoded) axis, cm. */
	double AxisDistance(const FVerseBoltHole& Hole, const FVector& Local)
	{
		const FVector Dir = Hole.GetAxisDirection();
		const FVector Rel = Local - Hole.GetAxisPointCm();
		return (Rel - Dir * FVector::DotProduct(Rel, Dir)).Size();
	}

	/** Where a ray crosses the plane x = PlaneX (piece-local, slab faces). */
	FVector CrossPlaneX(const FVector& Start, const FVector& Dir, double PlaneX)
	{
		return Start + Dir * ((PlaneX - Start.X) / Dir.X);
	}
}

// A3.3: a ray through a 15 mm hole in 0.3 cm sheet at 30 deg off the axis passes; the same ray
// through a 4 cm panel fails; 10,000 seeded rays agree with the analytic two-point test.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSightHolesTest, "Verse.Destruction.Sight.Holes", WP03Flags)

bool FVerseSightHolesTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	struct FPanel
	{
		const TCHAR* Name;
		EVersePenetrationMaterial Material;
		float Thickness;
		FVector Center;
		bool bThirtyDegPasses;
	};
	const FPanel Panels[] = {
		{TEXT("0.3 cm sheet metal"), EVersePenetrationMaterial::SheetMetal, 0.3f, FVector(0, 0, 0), true},
		{TEXT("4 cm cladding panel"), EVersePenetrationMaterial::CladdingPanel, 4.f, FVector(0, 1000.f, 0), false},
	};
	const double Rad30 = FMath::DegreesToRadians(30.0);
	const FVector Dir30(FMath::Cos(Rad30), FMath::Sin(Rad30), 0.0);
	uint16 Index = 0;
	for (const FPanel& Panel : Panels)
	{
		W.SpawnPiece(Index, Panel.Material, Panel.Center, Panel.Thickness);
		// A rifle bolt shot straight through the middle left the 15 mm hole.
		TestEqual(FString::Printf(TEXT("%s: hole recorded"), Panel.Name),
			W.Holes->AddHole(Index, Panel.Material, FVector::ZeroVector, FVector::ForwardVector, 15, 1000), EVerseHoleAddResult::Added);
		W.Settle();

		// The ray enters at the centre of the hole's entry face, 30 deg off the hole axis.
		const FVector Entry = Panel.Center - FVector(Panel.Thickness * 0.5f, 0, 0);
		const FVector Eye = Entry - Dir30 * 200.0;
		const FVector Target = Entry + Dir30 * 200.0;
		TestEqual(FString::Printf(TEXT("%s: 30 deg sight through the hole"), Panel.Name), W.Penetration->TestSight(Eye, Target), Panel.bThirtyDegPasses);
		TestEqual(FString::Printf(TEXT("%s: the reverse direction agrees"), Panel.Name), W.Penetration->TestSight(Target, Eye), Panel.bThirtyDegPasses);

		// Straight down the axis both pass; well beside the hole both are blocked.
		TestTrue(FString::Printf(TEXT("%s: on-axis sight"), Panel.Name),
			W.Penetration->TestSight(Panel.Center - FVector(100, 0, 0), Panel.Center + FVector(100, 0, 0)));
		TestFalse(FString::Printf(TEXT("%s: sight beside the hole"), Panel.Name),
			W.Penetration->TestSight(Panel.Center - FVector(100, 0, 10), Panel.Center + FVector(100, 0, 10)));

		// Bolts use the same test: through the hole is free, the panel itself is not.
		TestEqual(FString::Printf(TEXT("%s: bolt down the hole enters no piece"), Panel.Name),
			W.Penetration->TraceBolt(Panel.Center - FVector(100, 0, 0), FVector::ForwardVector, 200.f, 100.f, 1.f, 15, 3).Num(), 0);
		const TArray<FVersePenetrationHit> Beside =
			W.Penetration->TraceBolt(Panel.Center - FVector(100, 0, 10), FVector::ForwardVector, 200.f, 100.f, 1.f, 15, 3);
		TestEqual(FString::Printf(TEXT("%s: bolt beside the hole enters the piece"), Panel.Name), Beside.Num(), 1);
		++Index;
	}

	// 10,000 seeded rays near the holes, both panels: TestSight against the analytic two-point
	// test on the slab faces. Rays whose entry or exit lies within 0.02 cm of the rim are left
	// out (trace precision), and counted.
	FVerseRng Rng(0x5713E03ull);
	int32 Agree = 0;
	int32 Disagree = 0;
	int32 NearRim = 0;
	int32 Passing = 0;
	for (int32 Ray = 0; Ray < 10000; ++Ray)
	{
		const FPanel& Panel = Panels[Ray % 2];
		const uint16 Piece = uint16(Ray % 2);
		const TConstArrayView<FVerseBoltHole> Holes = W.Holes->GetPieceHoles(Piece);
		if (!TestEqual(TEXT("one hole per panel"), Holes.Num(), 1))
		{
			return false;
		}
		const FVerseBoltHole& Hole = Holes[0];
		const FVector2D Disk = Rng.UnitDisk() * 2.5;
		const FVector EntryLocal(-Panel.Thickness * 0.5, Disk.X, Disk.Y);
		const FVector Dir = Rng.ConeDirection(FVector::ForwardVector, 60.0);
		const FVector ExitLocal = CrossPlaneX(EntryLocal, Dir, Panel.Thickness * 0.5);
		const double Radius = Hole.RadiusMm / 10.0;
		const double EntryMargin = Radius - AxisDistance(Hole, EntryLocal);
		const double ExitMargin = Radius - AxisDistance(Hole, ExitLocal);
		if (FMath::Abs(EntryMargin) < 0.02 || FMath::Abs(ExitMargin) < 0.02)
		{
			++NearRim;
			continue;
		}
		const bool bAnalytic = EntryMargin > 0.0 && ExitMargin > 0.0;
		const FVector EntryWorld = Panel.Center + EntryLocal;
		const bool bTraced = W.Penetration->TestSight(EntryWorld - Dir * 150.0, EntryWorld + Dir * 150.0);
		if (bTraced == bAnalytic)
		{
			++Agree;
		}
		else
		{
			++Disagree;
			if (Disagree <= 5)
			{
				AddError(FString::Printf(TEXT("ray %d on %s: traced %d, analytic %d (margins %.4f, %.4f)"), Ray, Panel.Name, bTraced, bAnalytic,
					EntryMargin, ExitMargin));
			}
		}
		Passing += bAnalytic ? 1 : 0;
	}
	AddInfo(FString::Printf(TEXT("seeded rays: %d agree, %d disagree, %d near the rim left out, %d see through"), Agree, Disagree, NearRim, Passing));
	TestEqual(TEXT("no seeded ray disagrees"), Disagree, 0);
	TestTrue(TEXT("rim band stays small (< 2 %)"), NearRim < 200);
	TestTrue(TEXT("both outcomes are exercised"), Passing > 500 && Passing < Agree - 500);
	return true;
}

// destruction.md 5: intact glass and grating never block sight, damaged glass blocks except
// through its holes, other pieces and world geometry block.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseSightRulesTest, "Verse.Destruction.Sight.Rules", WP03Flags)

bool FVerseSightRulesTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	const FVector Eye(-200.f, 0, 0);
	const FVector Target(200.f, 0, 0);
	TestTrue(TEXT("empty world: clear"), W.Penetration->TestSight(Eye, Target));

	AActor* Glass = W.SpawnPiece(1, EVersePenetrationMaterial::Glass, FVector::ZeroVector, 2.4f);
	W.Settle();
	TestTrue(TEXT("intact glass is see-through"), W.Penetration->TestSight(Eye, Target));
	W.Query.States.Add(1, EVersePieceState::Damaged);
	TestFalse(TEXT("damaged glass blocks"), W.Penetration->TestSight(Eye, Target));
	W.Holes->AddHole(1, EVersePenetrationMaterial::Glass, FVector::ZeroVector, FVector::ForwardVector, 15, 10);
	TestTrue(TEXT("damaged glass: sight through its hole"), W.Penetration->TestSight(Eye, Target));
	TestFalse(TEXT("damaged glass: beside its hole"), W.Penetration->TestSight(Eye + FVector(0, 0, 20), Target + FVector(0, 0, 20)));
	TestEqual(TEXT("bolts still stop or pass by the table at intact glass"),
		W.Penetration->TraceBolt(Eye + FVector(0, 0, 20), FVector::ForwardVector, 400.f, 100.f, 1.f, 15, 3).Num(), 1);
	W.Query.States.Add(1, EVersePieceState::Destroyed);
	TestTrue(TEXT("destroyed glass never blocks"), W.Penetration->TestSight(Eye + FVector(0, 0, 20), Target + FVector(0, 0, 20)));
	W.DestroyActor(Glass);

	AActor* Grating = W.SpawnPiece(2, EVersePenetrationMaterial::CatwalkGrating, FVector::ZeroVector, 3.f);
	W.Settle();
	TestTrue(TEXT("grating is see-through"), W.Penetration->TestSight(Eye, Target));
	const TArray<FVersePenetrationHit> GratingHits = W.Penetration->TraceBolt(Eye, FVector::ForwardVector, 400.f, 100.f, 1.f, 15, 3);
	TestTrue(TEXT("a bolt is charged by the grating"), GratingHits.Num() == 1 && GratingHits[0].bPassed
		&& FMath::IsNearlyEqual(GratingHits[0].PowerLeft, 90.f, 1e-3f));

	AActor* Wall = W.SpawnPiece(3, EVersePenetrationMaterial::ContainerWall, FVector(50.f, 0, 0), 0.4f);
	W.Settle();
	TestFalse(TEXT("a container wall behind grating blocks"), W.Penetration->TestSight(Eye, Target));
	W.Query.States.Add(3, EVersePieceState::Damaged);
	TestFalse(TEXT("a damaged wall without holes blocks"), W.Penetration->TestSight(Eye, Target));
	W.DestroyActor(Wall);
	W.DestroyActor(Grating);

	const EVerseWorldSurface Surface = EVerseWorldSurface::StructuralWall;
	W.SpawnWorldBox(&Surface, FVector::ZeroVector, 30.f);
	W.Settle();
	TestFalse(TEXT("world geometry blocks"), W.Penetration->TestSight(Eye, Target));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Destruction/VerseDestructionTuning.h"
#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Holes/VerseHoleGlow.h"
#include "Holes/VerseHoleRenderComponent.h"
#include "Misc/AutomationTest.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FVector HolePoint(int32 I)
	{
		return FVector(0.0, -40.0 + 3.0 * (I % 25), -30.0 + 3.0 * (I / 25));
	}

	float HueOf(const FLinearColor& Linear)
	{
		return Linear.LinearRGBToHSV().R;
	}
}

// A3.4: hole 25 on a wall makes it Holed and clears its holes; the arena cap drops the oldest
// hole of the fullest piece; glass keeps its newest 24; resets bump the epoch.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleCapsTest, "Verse.Destruction.Holes.Caps", WP03Flags)

bool FVerseHoleCapsTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	UVerseBoltHoleComponent* Holes = W.Holes;
	const UVerseDestructionTuning* Tuning = GetDefault<UVerseDestructionTuning>();
	Holes->ApplyTuning(*Tuning);
	TestEqual(TEXT("24 holes per piece"), Holes->GetHolesPerPiece(), 24);
	TestEqual(TEXT("512 holes per arena"), Holes->GetHolesPerArena(), 512);

	uint16 CapPiece = 0xFFFF;
	FVector CapCentroid = FVector::ZeroVector;
	int32 CapCalls = 0;
	Holes->OnPieceHoleCap.AddLambda([&](uint16 Piece, const FVector& Centroid) {
		CapPiece = Piece;
		CapCentroid = Centroid;
		++CapCalls;
	});

	// Wall: 24 holes stay, hole 25 turns it Holed and clears them.
	FVector Sum = FVector::ZeroVector;
	for (int32 I = 0; I < 24; ++I)
	{
		TestEqual(FString::Printf(TEXT("wall hole %d"), I + 1),
			Holes->AddHole(7, EVersePenetrationMaterial::ContainerWall, HolePoint(I), FVector::ForwardVector, 15, 100 + I), EVerseHoleAddResult::Added);
		Sum += HolePoint(I);
	}
	TestEqual(TEXT("24 holes on the wall"), Holes->NumOnPiece(7), 24);
	TestEqual(TEXT("hole 25 turns the wall Holed"),
		Holes->AddHole(7, EVersePenetrationMaterial::ContainerWall, HolePoint(24), FVector::ForwardVector, 15, 200), EVerseHoleAddResult::PieceHoled);
	Sum += HolePoint(24);
	TestEqual(TEXT("wall holes cleared"), Holes->NumOnPiece(7), 0);
	TestEqual(TEXT("cap fired once"), CapCalls, 1);
	TestEqual(TEXT("cap names the piece"), CapPiece, uint16(7));
	TestTrue(TEXT("cap centroid is the mean of the 25 holes (1 mm records)"), CapCentroid.Equals(Sum / 25.0, 0.06));

	// Glass and ceiling are not walls: the 25th hole drops the piece's oldest.
	for (int32 I = 0; I < 25; ++I)
	{
		Holes->AddHole(8, EVersePenetrationMaterial::Glass, HolePoint(I), FVector::ForwardVector, 15, 300 + I);
	}
	TestEqual(TEXT("glass keeps 24"), Holes->NumOnPiece(8), 24);
	TestEqual(TEXT("glass dropped its oldest"), Holes->GetPieceHoles(8)[0].ServerTimeMs, uint32(301));
	TestEqual(TEXT("no cap event for glass"), CapCalls, 1);

	// Materials without holes.
	TestEqual(TEXT("grating keeps no holes"),
		Holes->AddHole(9, EVersePenetrationMaterial::CatwalkGrating, FVector::ZeroVector, FVector::ForwardVector, 15, 1), EVerseHoleAddResult::NotHoleMaterial);
	TestEqual(TEXT("concrete keeps no holes"),
		Holes->AddHole(9, EVersePenetrationMaterial::Concrete, FVector::ZeroVector, FVector::ForwardVector, 15, 1), EVerseHoleAddResult::NotHoleMaterial);
	TestEqual(TEXT("armor steel keeps no holes"),
		Holes->AddHole(9, EVersePenetrationMaterial::ArmorSteel, FVector::ZeroVector, FVector::ForwardVector, 15, 1), EVerseHoleAddResult::NotHoleMaterial);

	// Arena cap: fill to 512, the fullest piece (ties: the older one) loses its oldest hole.
	Holes->ResetAll(3);
	TestEqual(TEXT("reset clears"), Holes->Num(), 0);
	TestEqual(TEXT("reset sets the epoch"), Holes->GetEpoch(), uint16(3));
	uint32 Time = 1000;
	for (uint16 Piece = 0; Piece < 21; ++Piece)
	{
		for (int32 I = 0; I < 24; ++I)
		{
			Holes->AddHole(Piece, EVersePenetrationMaterial::SheetMetal, HolePoint(I), FVector::ForwardVector, 15, Time++);
		}
	}
	for (int32 I = 0; I < 8; ++I)
	{
		Holes->AddHole(21, EVersePenetrationMaterial::SheetMetal, HolePoint(I), FVector::ForwardVector, 15, Time++);
	}
	TestEqual(TEXT("arena at 512"), Holes->Num(), 512);
	const uint32 Piece0Second = Holes->GetPieceHoles(0)[1].ServerTimeMs;
	TestEqual(TEXT("hole 513 is added"),
		Holes->AddHole(30, EVersePenetrationMaterial::SheetMetal, FVector::ZeroVector, FVector::ForwardVector, 15, Time++), EVerseHoleAddResult::Added);
	TestEqual(TEXT("arena stays at 512"), Holes->Num(), 512);
	TestEqual(TEXT("the oldest of the fullest piece went"), Holes->NumOnPiece(0), 23);
	TestEqual(TEXT("piece 0 now starts with its second hole"), Holes->GetPieceHoles(0)[0].ServerTimeMs, Piece0Second);
	TestEqual(TEXT("other full pieces keep theirs"), Holes->NumOnPiece(1), 24);
	TestEqual(TEXT("the smallest piece keeps its holes"), Holes->NumOnPiece(21), 8);
	Holes->AddHole(31, EVersePenetrationMaterial::SheetMetal, FVector::ZeroVector, FVector::ForwardVector, 15, Time++);
	TestEqual(TEXT("next eviction: piece 1 (fullest, oldest)"), Holes->NumOnPiece(1), 23);
	TArray<FVerseBoltHole> All;
	Holes->GetAllHoles(All);
	TestTrue(TEXT("every record carries the epoch"), All.ContainsByPredicate([](const FVerseBoltHole& H) { return H.Epoch != 3; }) == false);

	// Clear on a state change.
	Holes->ClearPiece(2);
	TestEqual(TEXT("clear piece"), Holes->NumOnPiece(2), 0);

	// Holes from a traced bolt: one record per passed piece that keeps holes, none after a stop.
	Holes->ResetAll(4);
	W.SpawnPiece(100, EVersePenetrationMaterial::ContainerWall, FVector(100.f, 0, 0), 0.4f);
	W.SpawnPiece(101, EVersePenetrationMaterial::CatwalkGrating, FVector(150.f, 0, 0), 3.f);
	W.SpawnPiece(102, EVersePenetrationMaterial::ContainerWall, FVector(200.f, 0, 0), 0.4f);
	W.SpawnPiece(103, EVersePenetrationMaterial::CladdingPanel, FVector(250.f, 0, 0), 4.f);
	W.Settle();
	const FVector Dir = FVector(1.0, 0.1, 0.0).GetSafeNormal();
	const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(FVector(0, -10.f, 0), Dir, 1000.f, 100.f, 30.f, 15, 3);
	TestEqual(TEXT("bolt enters four pieces"), Hits.Num(), 4);
	TestEqual(TEXT("two holes recorded (grating keeps none, the cladding stopped it)"),
		W.Penetration->RecordBoltHoles(Hits, Dir, 15, 5000), 2);
	TestEqual(TEXT("first wall has its hole"), Holes->NumOnPiece(100), 1);
	TestEqual(TEXT("second wall has its hole"), Holes->NumOnPiece(102), 1);
	TestEqual(TEXT("stopping piece has none"), Holes->NumOnPiece(103), 0);
	if (Holes->NumOnPiece(100) == 1)
	{
		const FVerseBoltHole& Hole = Holes->GetPieceHoles(100)[0];
		TestTrue(TEXT("hole axis follows the bolt"), FVector::DotProduct(Hole.GetAxisDirection(), Dir) > 0.999);
		TestEqual(TEXT("hole radius from the weapon"), Hole.RadiusMm, uint8(15));
		TestEqual(TEXT("hole epoch"), Hole.Epoch, uint16(4));
		// The same bolt line now flies through the recorded hole of the first wall without cost.
		const TArray<FVersePenetrationHit> Again = W.Penetration->TraceBolt(FVector(0, -10.f, 0), Dir, 1000.f, 100.f, 30.f, 15, 3);
		TestTrue(TEXT("second bolt skips both holed walls"), Again.Num() == 2 && Again[0].PieceIndex == 101 && Again[1].PieceIndex == 103);
	}
	return true;
}

// WP03.6: the glow curve (tau 1.2 s, dull red at 2.5 s, off at 4 s) and its colours never
// fall under the rendered-pixel ban at any exposure.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleGlowTest, "Verse.Destruction.Holes.Glow", WP03Flags)

bool FVerseHoleGlowTest::RunTest(const FString& Parameters)
{
	const FVerseHoleGlowSample Fresh = VerseHoleGlow::Sample(0.f);
	TestTrue(TEXT("fresh hole glows at full"), Fresh.bGlowing && VerseWP03Test::Near(Fresh.Intensity, 1.f, 1e-6f));
	const float FreshHue = HueOf(Fresh.Color);
	TestTrue(FString::Printf(TEXT("fresh hue %.1f is white-amber (25..45 deg)"), FreshHue), FreshHue >= 25.f && FreshHue <= 45.f);
	TestTrue(TEXT("fresh colour is near white (low saturation)"), Fresh.Color.LinearRGBToHSV().G < 0.6f);
	TestTrue(TEXT("tau 1.2 s"), VerseWP03Test::Near(VerseHoleGlow::Sample(1.2f).Intensity, FMath::Exp(-1.f), 1e-4f));
	const FVerseHoleGlowSample Red = VerseHoleGlow::Sample(2.5f);
	TestTrue(TEXT("2.5 s intensity is exp(-2.5 / 1.2)"), VerseWP03Test::Near(Red.Intensity, FMath::Exp(-2.5f / 1.2f), 1e-4f));
	const float RedHue = HueOf(Red.Color);
	TestTrue(FString::Printf(TEXT("2.5 s hue %.1f is dull red (<= 12 deg)"), RedHue), RedHue <= 12.f || RedHue >= 355.f);
	const FVerseHoleGlowSample Off = VerseHoleGlow::Sample(4.f);
	TestTrue(TEXT("glow off at 4 s"), !Off.bGlowing && Off.Intensity == 0.f);
	TestTrue(TEXT("charred after the glow"), Off.Color.Equals(VerseHoleGlow::CharredColor()));

	float Last = 2.f;
	int32 Banned = 0;
	int32 Samples = 0;
	const float Exposures[] = {0.05f, 0.25f, 1.f, 4.f, 40.f};
	for (int32 Ms = 0; Ms <= 4000; Ms += 10)
	{
		const FVerseHoleGlowSample S = VerseHoleGlow::Sample(Ms / 1000.f);
		if (S.Intensity > Last + 1e-7f)
		{
			AddError(FString::Printf(TEXT("glow rises at %d ms"), Ms));
		}
		Last = S.Intensity;
		for (const float Exposure : Exposures)
		{
			// Emissive over the charred rim, clipped like a display would.
			const FLinearColor Pixel = VerseHoleGlow::CharredColor() + S.Color * (S.Intensity * Exposure);
			const FColor Srgb = FLinearColor(FMath::Min(Pixel.R, 1.f), FMath::Min(Pixel.G, 1.f), FMath::Min(Pixel.B, 1.f)).ToFColor(true);
			Banned += VerseHoleGlow::IsBannedPixel(Srgb) ? 1 : 0;
			++Samples;
		}
	}
	TestEqual(FString::Printf(TEXT("banned pixels over %d glow samples"), Samples), Banned, 0);

	// The ban itself.
	TestTrue(TEXT("cyan is banned"), VerseHoleGlow::IsBannedPixel(FColor(0, 200, 220)));
	TestTrue(TEXT("violet is banned"), VerseHoleGlow::IsBannedPixel(FColor(140, 40, 220)));
	TestTrue(TEXT("info blue is banned"), VerseHoleGlow::IsBannedPixel(FColor(40, 90, 230)));
	TestFalse(TEXT("amber passes"), VerseHoleGlow::IsBannedPixel(FColor(255, 160, 40)));
	TestFalse(TEXT("dark blue below the value floor passes"), VerseHoleGlow::IsBannedPixel(FColor(5, 10, 20)));

	// 128 glowing at most, the oldest cools first, nothing older than 4 s glows.
	TArray<uint32> Times;
	for (int32 I = 0; I < 200; ++I)
	{
		Times.Add(10000 + I * 10);
	}
	Times.Add(1000);
	const uint32 Now = 12000;
	const TArray<int32> Glowing = VerseHoleGlow::SelectGlowing(Times, Now, 128);
	TestEqual(TEXT("128 glowing"), Glowing.Num(), 128);
	TestEqual(TEXT("newest first"), Glowing[0], 199);
	TestFalse(TEXT("the oldest young holes cooled first"), Glowing.Contains(0));
	TestFalse(TEXT("a hole older than 4 s never glows"), Glowing.Contains(200));
	TestEqual(TEXT("nothing glows 4 s after the last hole"), VerseHoleGlow::SelectGlowing(Times, 10000 + 199 * 10 + 4000, 128).Num(), 0);
	return true;
}

// WP03.6: the renderer's bookkeeping, which runs on every client: a mask slot per piece on its
// first hole, a slot per hole, the 128 glowing cap. GPU objects are only made with a real RHI.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseHoleRenderTest, "Verse.Destruction.Holes.Render", WP03Flags)

bool FVerseHoleRenderTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	UVerseHoleRenderComponent* Render = NewObject<UVerseHoleRenderComponent>(W.Manager, TEXT("HoleRender"));
	Render->RegisterComponent();
	uint32 Now = 0;
	Render->SetServerTimeSource([&Now]() { return Now; });
	Render->SetHoleSource(W.Holes);
	const FBox Bounds(FVector(-0.2, -100, -50), FVector(0.2, 100, 50));
	Render->RegisterPieceVisual(4, nullptr, Bounds, W.Manager->GetRootComponent());
	Render->Sync();
	TestEqual(TEXT("no mask before the first hole"), Render->NumMaskSlots(), 0);

	TestTrue(TEXT("hole UV of the centre"), UVerseHoleRenderComponent::HoleUV(Bounds, FVector::ZeroVector).Equals(FVector2D(0.5, 0.5), 1e-6));
	TestTrue(TEXT("hole UV of a corner"), UVerseHoleRenderComponent::HoleUV(Bounds, FVector(0, -100, 50)).Equals(FVector2D(0, 0), 1e-6));
	TestTrue(TEXT("15 mm on a 2 m face is about 1.9 px"), VerseWP03Test::Near(UVerseHoleRenderComponent::HoleRadiusPx(Bounds, 1.5f, 256), 1.92f, 1e-3f));

	Now = 100000;
	for (int32 I = 0; I < 200; ++I)
	{
		const uint16 Piece = uint16(4 + I / 24);
		W.Holes->AddHole(Piece, EVersePenetrationMaterial::Glass, HolePoint(I % 24), FVector::ForwardVector, 15, Now - 199 + I);
	}
	Render->Sync();
	TestEqual(TEXT("a slot per hole"), Render->NumHoleSlots(), W.Holes->Num());
	TestEqual(TEXT("a mask per piece with holes"), Render->NumMaskSlots(), 9);
	TestTrue(TEXT("piece 4 has its mask"), Render->HasMask(4));
	TestFalse(TEXT("an untouched piece has none"), Render->HasMask(40));
	TestEqual(TEXT("128 glowing at most"), Render->NumGlowing(), 128);
	Now += 4000;
	Render->Sync();
	TestEqual(TEXT("all cooled after 4 s"), Render->NumGlowing(), 0);
	W.Holes->ClearPiece(4);
	Render->Sync();
	TestEqual(TEXT("a mask slot survives its holes (cleared, reused)"), Render->NumMaskSlots(), 9);
	if (!UVerseHoleRenderComponent::CanRender(W.World()))
	{
		TestNull(TEXT("no GPU mask without a renderer"), Render->GetMask(5));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

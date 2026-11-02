#include "Core/VerseUiLayout.h"
#include "Core/VerseUiStrings.h"
#include "Core/VerseUiTheme.h"
#include "Hud/VerseCrosshair.h"
#include "Hud/VerseHudModel.h"
#include "Hud/VerseHudPainter.h"
#include "Engine/Font.h"
#include "Misc/AutomationTest.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"

#if WITH_DEV_AUTOMATION_TESTS

namespace VerseUiHudTest
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FVerseUiStrings LoadStrings()
	{
		FVerseUiStrings Strings;
		Strings.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		return Strings;
	}

	/** Independent pinhole projection (horizontal FOV kept), to check the renderer path. */
	FVector2D Analytic(const FVerseHudView& View, const FVector2D& Viewport, const FVector& Dir)
	{
		const FRotationMatrix M(View.Rotation);
		const FVector F = M.GetUnitAxis(EAxis::X);
		const FVector R = M.GetUnitAxis(EAxis::Y);
		const FVector U = M.GetUnitAxis(EAxis::Z);
		const double Depth = FVector::DotProduct(Dir, F);
		const double Focal = (Viewport.X * 0.5) / FMath::Tan(FMath::DegreesToRadians(View.HorizontalFovDeg) * 0.5);
		return FVector2D(Viewport.X * 0.5 + FVector::DotProduct(Dir, R) / Depth * Focal,
			Viewport.Y * 0.5 - FVector::DotProduct(Dir, U) / Depth * Focal);
	}

	FVerseHitEvent Hit(int32 From, int32 To, float Damage = 20.f)
	{
		FVerseHitEvent E;
		E.InstigatorId = From;
		E.VictimId = To;
		E.Damage = Damage;
		E.WeaponId = TEXT("graveline");
		return E;
	}
}

using namespace VerseUiHudTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiLayoutTest, "Verse.UI.Layout.Scaling", Flags)
bool FVerseUiLayoutTest::RunTest(const FString&)
{
	const FVerseUiLayout L1080 = FVerseUiLayout::Compute(FVector2D(1920, 1080), 0.025f, FMargin(0), 1.f);
	const FVerseUiLayout L1440 = FVerseUiLayout::Compute(FVector2D(2560, 1440), 0.025f, FMargin(0), 1.f);
	const FVerseUiLayout L4K = FVerseUiLayout::Compute(FVector2D(3840, 2160), 0.025f, FMargin(0), 1.f);
	TestEqual(TEXT("1080p scale"), L1080.Scale, 1.f);
	TestTrue(TEXT("1440p scale"), FMath::IsNearlyEqual(L1440.Scale, 4.f / 3.f, 1e-4f));
	TestEqual(TEXT("4K scale"), L4K.Scale, 2.f);
	TestTrue(TEXT("safe area 2.5 % at 4K"), FMath::IsNearlyEqual(L4K.SafeMin.X, 96.0, 0.01));
	const FVerseUiLayout Padded = FVerseUiLayout::Compute(FVector2D(1920, 1080), 0.025f, FMargin(100, 10, 0, 0), 1.2f);
	TestTrue(TEXT("platform padding wins when larger"), FMath::IsNearlyEqual(Padded.SafeMin.X, 100.0, 0.01));
	TestTrue(TEXT("text scale follows the person's size"), FMath::IsNearlyEqual(Padded.TextScale, 1.2f, 1e-4f));
	// Every anchor lands inside the safe rectangle, even with an offset pushing out.
	for (int32 A = 0; A <= int32(EVerseUiAnchor::BottomRight); ++A)
	{
		const FVector2D Size(400, 120);
		const FVector2D P = L4K.Place(EVerseUiAnchor(A), Size * L4K.Scale, FVector2D(-5000, -5000));
		TestTrue(FString::Printf(TEXT("anchor %d inside safe area"), A),
			P.X >= L4K.SafeMin.X - 0.01 && P.Y >= L4K.SafeMin.Y - 0.01 && P.X + Size.X * L4K.Scale <= L4K.SafeMax.X + 0.01 && P.Y + Size.Y * L4K.Scale <= L4K.SafeMax.Y + 0.01);
	}
	return true;
}

// A18.1: centre of the crosshair and the predicted bolt direction differ by 0 px at 1440p over 1,000 shots.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiCrosshairTest, "Verse.UI.Hud.Crosshair", Flags)
bool FVerseUiCrosshairTest::RunTest(const FString&)
{
	const FVerseUiStrings Strings = LoadStrings();
	FFakeVerseHudSource Source;
	Source.Pawn.bValid = true;
	FVerseHudModel Model;
	Model.SetLocalPlayerId(Source.LocalId);
	FRandomStream Rng(1440);
	const FVector2D Viewport(2560, 1440);
	int32 Mismatch = 0;
	double WorstPx = 0.0;
	for (int32 Shot = 0; Shot < 1000; ++Shot)
	{
		Source.View.Location = FVector(Rng.FRandRange(-5000, 5000), Rng.FRandRange(-5000, 5000), Rng.FRandRange(0, 600));
		Source.View.Rotation = FRotator(Rng.FRandRange(-80, 80), Rng.FRandRange(-180, 180), Rng.FRandRange(-12, 12));
		Source.View.HorizontalFovDeg = Rng.FRandRange(80.f, 110.f);
		// Recoil, sway and lean push the bolt up to 6 degrees off the camera axis.
		const FRotator Off(Rng.FRandRange(-6, 6), Rng.FRandRange(-6, 6), 0);
		Source.BoltDirection = (Source.View.Rotation.Quaternion() * Off.Quaternion()).GetForwardVector();
		Source.SpreadDeg = Rng.FRandRange(0.f, 3.f);

		FVerseHudFrame Frame;
		Frame.Model = &Model;
		Frame.Strings = &Strings;
		Frame.Source = &Source;
		Frame.Layout = FVerseUiLayout::Compute(Viewport, 0.025f, FMargin(0), 1.f);
		Source.GetPawnState(Frame.Pawn);
		Frame.bHasView = Source.GetView(Frame.View);
		FVerseHudDrawList List;
		FVerseHudPainter::Paint(Frame, List, FVerseHudPainter::DefaultMeasure());

		const FVector2D Expected = Analytic(Source.View, Viewport, Source.BoltDirection);
		WorstPx = FMath::Max(WorstPx, FVector2D::Distance(Expected, List.CrosshairCentre));
		Mismatch += FVerseCrosshair::PixelCell(Expected) != FVerseCrosshair::PixelCell(List.CrosshairCentre) || !List.bCrosshairVisible;
	}
	AddInfo(FString::Printf(TEXT("worst sub-pixel distance %.6f px"), WorstPx));
	TestEqual(TEXT("shots whose crosshair pixel differs from the bolt pixel"), Mismatch, 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiMarkersTest, "Verse.UI.Hud.Markers", Flags)
bool FVerseUiMarkersTest::RunTest(const FString&)
{
	FVerseHudModel Model;
	Model.SetLocalPlayerId(1);
	FVerseHitEvent H = Hit(1, 2);
	Model.OnHit(H, 0.0);
	H.bHeadshot = 1;
	Model.OnHit(H, 0.0);
	H.bHeadshot = 0;
	H.bKillingBlow = 1;
	Model.OnHit(H, 0.0);
	H.bKillingBlow = 0;
	H.bBlockedBySpawnProtection = 1;
	Model.OnHit(H, 0.0);
	TestEqual(TEXT("four marker kinds"), Model.GetHitMarkers().Num(), 4);
	Model.OnHit(Hit(2, 3), 0.0);
	TestEqual(TEXT("no marker for someone else's hit"), Model.GetHitMarkers().Num(), 4);
	Model.Tick(0.35, 0.0);
	TestFalse(TEXT("hit marker gone after 0.3 s"), Model.GetHitMarkers().ContainsByPredicate([](const FVerseHitMarker& M) { return M.Kind == EVerseHitMarkerKind::Hit; }));
	TestTrue(TEXT("kill marker still up at 0.35 s"), Model.GetHitMarkers().ContainsByPredicate([](const FVerseHitMarker& M) { return M.Kind == EVerseHitMarkerKind::Kill; }));
	Model.Tick(1.0, 0.0);
	TestEqual(TEXT("all markers gone after 1 s"), Model.GetHitMarkers().Num(), 0);

	// WP18.10: every kind has its own shape, so none depends on colour.
	const EVerseHitMarkerKind Kinds[] = {EVerseHitMarkerKind::Hit, EVerseHitMarkerKind::Headshot, EVerseHitMarkerKind::Kill, EVerseHitMarkerKind::Blocked};
	TSet<FIntVector> Shapes;
	for (EVerseHitMarkerKind Kind : Kinds)
	{
		const FIntVector Shape = FVerseHudPainter::MarkerShape(Kind);
		TestTrue(TEXT("marker draws something"), Shape.X + Shape.Y + Shape.Z > 0);
		Shapes.Add(Shape);
	}
	TestEqual(TEXT("four distinct marker shapes"), Shapes.Num(), 4);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiDamageDirectionTest, "Verse.UI.Hud.DamageDirection", Flags)
bool FVerseUiDamageDirectionTest::RunTest(const FString&)
{
	FVerseHudModel Model;
	Model.SetLocalPlayerId(1);
	FVerseHitEvent H = Hit(2, 1);
	// Shooter on the person's left: the bolt travels toward +Y (right) when the person faces +X.
	H.Direction = FVector_NetQuantizeNormal(0.0, 1.0, 0.0);
	Model.OnHit(H, 0.0);
	TestEqual(TEXT("one indicator"), Model.GetDamageIndicators().Num(), 1);
	FVerseHudView View;
	View.Rotation = FRotator::ZeroRotator;
	const float Left = FVerseHudPainter::IndicatorAngleDeg(View, Model.GetDamageIndicators()[0].FromDirection);
	TestTrue(TEXT("points left (-90)"), FMath::IsNearlyEqual(Left, -90.f, 0.5f));
	View.Rotation = FRotator(0, -90, 0);
	const float Ahead = FVerseHudPainter::IndicatorAngleDeg(View, Model.GetDamageIndicators()[0].FromDirection);
	TestTrue(TEXT("turning toward the source puts it ahead"), FMath::IsNearlyEqual(Ahead, 0.f, 0.5f));
	FVerseHitEvent Blocked = Hit(2, 1);
	Blocked.bBlockedBySpawnProtection = 1;
	Model.OnHit(Blocked, 0.0);
	TestEqual(TEXT("a blocked hit shows no damage"), Model.GetDamageIndicators().Num(), 1);
	Model.Tick(2.0, 0.0);
	TestEqual(TEXT("indicator fades out"), Model.GetDamageIndicators().Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiKillFeedTest, "Verse.UI.Hud.KillFeed", Flags)
bool FVerseUiKillFeedTest::RunTest(const FString&)
{
	FVerseHudModel Model;
	Model.SetLocalPlayerId(1);
	FVerseHitEvent Wall = Hit(1, 2, 60.f);
	Wall.PenetrationCount = 1;
	Wall.bHeadshot = 1;
	Model.OnHit(Wall, 0.0);
	FVerseDeathEvent Death;
	Death.KillerId = 1;
	Death.VictimId = 2;
	Death.WeaponId = TEXT("graveline");
	Death.ServerTime = 10.0;
	Death.RespawnAt = 13.0;
	Model.OnDeath(Death, 0.0);
	TestEqual(TEXT("one feed line"), Model.GetKillFeed().Num(), 1);
	TestTrue(TEXT("wall shot flagged"), Model.GetKillFeed()[0].bWallShot);
	TestTrue(TEXT("headshot flagged"), Model.GetKillFeed()[0].bHeadshot);
	TestEqual(TEXT("own score"), Model.GetScoreSelf(), 1);

	Model.Tick(1.0, 13.0);
	TestEqual(TEXT("opponent respawn line"), Model.GetKillFeed().Last().Kind, EVerseFeedKind::Respawn);

	FVerseDeathEvent Mine;
	Mine.KillerId = 2;
	Mine.VictimId = 1;
	Mine.Cause = EVerseDamageSource::Finisher;
	Mine.ServerTime = 20.0;
	Mine.RespawnAt = 23.0;
	Model.OnDeath(Mine, 2.0);
	TestTrue(TEXT("person dead"), Model.IsLocalDead());
	TestEqual(TEXT("opponent score"), Model.GetScoreOpponent(), 1);
	TestTrue(TEXT("respawn countdown 3.0 s"), FMath::IsNearlyEqual(Model.GetRespawnRemaining(20.0), 3.f, 1e-3f));
	TestTrue(TEXT("respawn countdown 1.0 s"), FMath::IsNearlyEqual(Model.GetRespawnRemaining(22.0), 1.f, 1e-3f));
	Model.Tick(3.0, 23.0);
	TestFalse(TEXT("person alive after RespawnAt"), Model.IsLocalDead());

	FVerseDeathEvent World;
	World.KillerId = -1;
	World.VictimId = 1;
	World.RespawnAt = 40.0;
	Model.OnDeath(World, 4.0);
	TestEqual(TEXT("a world kill scores nobody"), Model.GetScoreOpponent(), 1);

	FVerseSetSummary Summary;
	Summary.SetIndex = 1;
	Summary.Outcome = EVerseSetOutcome::Won;
	Model.OnSetEnded(Summary, 5.0);
	TestEqual(TEXT("set score resets"), Model.GetScoreSelf() + Model.GetScoreOpponent(), 0);
	TestEqual(TEXT("next set index"), Model.GetSetIndex(), 2);
	for (int32 I = 0; I < 12; ++I)
	{
		Model.OnDeath(Death, 5.0);
	}
	TestEqual(TEXT("feed keeps at most 5 lines"), Model.GetKillFeed().Num(), 5);
	// The tick at 20 s expires the kill lines and posts the opponent's respawn (RespawnAt 13);
	// that line expires 6 s later like any other.
	Model.Tick(20.0, 50.0);
	TestEqual(TEXT("kill lines expired, respawn line posted"), Model.GetKillFeed().Num(), 1);
	Model.Tick(26.0, 50.0);
	TestEqual(TEXT("feed lines expire after 6 s"), Model.GetKillFeed().Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiPaletteTest, "Verse.UI.Theme.Palette", Flags)
bool FVerseUiPaletteTest::RunTest(const FString&)
{
	for (const FLinearColor& C : VerseUiTheme::AllColours())
	{
		TestFalse(FString::Printf(TEXT("%s is not cyan or violet"), *C.ToString()), VerseUiTheme::IsForbiddenAccent(C));
	}
	TestTrue(TEXT("the check catches cyan"), VerseUiTheme::IsForbiddenAccent(FLinearColor(0.f, 0.8f, 0.9f)));
	TestTrue(TEXT("the check catches violet"), VerseUiTheme::IsForbiddenAccent(FLinearColor(0.5f, 0.1f, 0.9f)));
	return true;
}

/** A busy fight frame: every block on screen. */
static void FillFightFrame(FFakeVerseHudSource& Source, FVerseHudModel& Model)
{
	Source.LocalId = 1;
	Source.Names.Add(2, TEXT("Opponent"));
	Source.Bots.Add(2);
	Source.Pawn.bValid = true;
	Source.Pawn.Health = 64.f;
	Source.Pawn.Stance = EVerseStance::Crouch;
	Source.Pawn.bSpawnProtected = true;
	Source.Pawn.SpawnProtectionRemaining = 1.4f;
	Source.Pawn.bHasWeapon = true;
	Source.Pawn.WeaponId = TEXT("graveline");
	Source.Pawn.Magazine = 7;
	Source.Pawn.MagazineSize = 30;
	Source.Pawn.bChambered = true;
	Source.Pawn.Reserve = 90;
	Source.Pawn.bReloading = true;
	Source.Pawn.ReloadProgress = 0.4f;
	Source.Pawn.Gadgets = {{TEXT("bulwark"), 1, 1, 0.f}, {TEXT("breach_charge"), 1, 2, 0.f}};
	Source.SpreadDeg = 1.2f;
	Model.SetLocalPlayerId(1);
	FVerseHitEvent H = Hit(1, 2);
	H.bHeadshot = 1;
	Model.OnHit(H, 0.0);
	FVerseHitEvent In = Hit(2, 1);
	In.Direction = FVector_NetQuantizeNormal(-0.7, 0.7, 0.0);
	Model.OnHit(In, 0.0);
	FVerseDeathEvent D;
	D.KillerId = 1;
	D.VictimId = 2;
	D.WeaponId = TEXT("graveline");
	D.RespawnAt = 1e9;
	Model.OnDeath(D, 0.0);
	D.KillerId = 2;
	D.VictimId = 1;
	D.Cause = EVerseDamageSource::Finisher;
	D.RespawnAt = 103.0;
	Model.OnDeath(D, 0.0);
}

// Regression: canvas text items need a runtime-cache UFont or the engine skips them, which left
// every HUD label blank in the first captures.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiHudLabelFontTest, "Verse.UI.Hud.LabelFont", Flags)
bool FVerseUiHudLabelFontTest::RunTest(const FString&)
{
	const UFont* Font = FVerseHudCanvasRenderer::LabelFont();
	TestNotNull(TEXT("label font"), Font);
	if (Font)
	{
		TestTrue(TEXT("runtime font cache"), Font->FontCacheType == EFontCacheType::Runtime);
	}
	return true;
}

// A18.3 (game-thread part): building the HUD draw list stays far under 0.3 ms.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiHudCostTest, "Verse.UI.Hud.Cost", Flags)
bool FVerseUiHudCostTest::RunTest(const FString&)
{
	const FVerseUiStrings Strings = LoadStrings();
	FFakeVerseHudSource Source;
	FVerseHudModel Model;
	FillFightFrame(Source, Model);
	const FVerseTextMeasure Measure = FVerseHudPainter::DefaultMeasure();
	FVerseHudDrawList List;
	const int32 Frames = 2000;
	const double Start = FPlatformTime::Seconds();
	for (int32 I = 0; I < Frames; ++I)
	{
		FVerseHudFrame Frame;
		Frame.Model = &Model;
		Frame.Strings = &Strings;
		Frame.Source = &Source;
		Frame.Layout = FVerseUiLayout::Compute(FVector2D(2560, 1440), 0.025f, FMargin(0), 1.f);
		Source.GetPawnState(Frame.Pawn);
		Frame.bHasView = Source.GetView(Frame.View);
		Frame.Now = 0.1;
		Frame.ServerTime = 101.0;
		Frame.bKillCam = true;
		Frame.KillCamKillerId = 2;
		FVerseHudPainter::Paint(Frame, List, Measure);
		Model.Tick(0.1, 101.0);
	}
	const double MeanMs = (FPlatformTime::Seconds() - Start) * 1000.0 / Frames;
	AddInfo(FString::Printf(TEXT("HUD model tick + draw list: %.4f ms per frame, %d primitives"), MeanMs, List.Num()));
	TestTrue(TEXT("HUD game-thread build under 0.3 ms"), MeanMs < 0.3);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

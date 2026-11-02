#include "CanvasItem.h"
#include "CanvasTypes.h"
#include "Core/VerseUiSubsystem.h"
#include "Core/VerseUiTheme.h"
#include "DynamicRHI.h"
#include "Events/VerseEventHub.h"
#include "Misc/App.h"
#include "Engine/Canvas.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/TextureRenderTarget2D.h"
#include "HAL/FileManager.h"
#include "Hud/VerseHudPainter.h"
#include "ImageUtils.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "KillCam/VerseKillCam.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Styling/CoreStyle.h"
#include "Tests/UI/Fakes/VerseUiFakes.h"
#include "UnrealClient.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.WP18.*: the evidence of work-packages WP18 (HUD in a fight at 1080p, 1440p and
// 4K, kill cam contact sheet, the armoury in every locale, the HUD cost). Runs on the GPU in
// -game through scripts/unreal/screenshot.py; files go to Saved/Harness/proof/WP18/.
// No arena exists yet (WP11), so the HUD is drawn over a plain backdrop in the captures and
// over the empty entry map in the viewport shots.

namespace VerseUiVisual
{
	constexpr EAutomationTestFlags Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	FString ProofDir(const TCHAR* SubTask)
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP18"), SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		return Dir;
	}

	/** Headless runs (-nullrhi) skip the captures; screenshot.py runs them on the GPU. */
	bool SkipHeadless(FAutomationTestBase& Test)
	{
		if (!FApp::CanEverRender())
		{
			Test.AddInfo(TEXT("skipped: no renderer (-nullrhi); scripts/unreal/screenshot.py runs this suite"));
			return true;
		}
		return false;
	}

	UWorld* GameWorld()
	{
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World() && Context.GameViewport)
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	/** A dark hangar-like backdrop: gradient, wall plates, a catwalk rail, work lights. */
	void Backdrop(UCanvas* Canvas, const FVector2D& Size, uint32 Seed)
	{
		FCanvas* C = Canvas->Canvas;
		const int32 Bands = 48;
		for (int32 I = 0; I < Bands; ++I)
		{
			const float T = float(I) / Bands;
			const FLinearColor Colour = FMath::Lerp(FLinearColor(0.030f, 0.028f, 0.026f), FLinearColor(0.004f, 0.004f, 0.005f), T);
			FCanvasTileItem Tile(FVector2D(0, Size.Y * T), FVector2D(Size.X, Size.Y / Bands + 1), Colour);
			C->DrawItem(Tile);
		}
		FRandomStream Rng(int32(Seed));
		for (int32 I = 0; I < 9; ++I)
		{
			const FVector2D P(Size.X * Rng.FRandRange(-0.05f, 0.95f), Size.Y * Rng.FRandRange(0.15f, 0.55f));
			const FVector2D S(Size.X * Rng.FRandRange(0.08f, 0.22f), Size.Y * Rng.FRandRange(0.2f, 0.5f));
			FCanvasTileItem Plate(P, S, FLinearColor(0.018f, 0.017f, 0.016f, 1.f));
			C->DrawItem(Plate);
		}
		FCanvasTileItem Rail(FVector2D(0, Size.Y * 0.36f), FVector2D(Size.X, Size.Y * 0.012f), FLinearColor(0.05f, 0.045f, 0.04f));
		C->DrawItem(Rail);
		FCanvasTileItem Floor(FVector2D(0, Size.Y * 0.72f), FVector2D(Size.X, Size.Y * 0.28f), FLinearColor(0.012f, 0.011f, 0.010f));
		C->DrawItem(Floor);
		for (int32 I = 0; I < 4; ++I)
		{
			FCanvasTileItem Light(FVector2D(Size.X * (0.12f + 0.25f * I), Size.Y * 0.05f), FVector2D(Size.X * 0.05f, Size.Y * 0.008f), FLinearColor(0.9f, 0.7f, 0.4f));
			C->DrawItem(Light);
		}
	}

	bool SavePng(UWorld* World, UTextureRenderTarget2D* Target, const FString& Path)
	{
		FImage Image;
		return FImageUtils::GetRenderTargetImage(Target, Image) && FImageUtils::SaveImageByExtension(*Path, Image);
	}

	/** The fight state every capture shows. */
	void FightSource(FFakeVerseHudSource& Source, FVerseHudModel& Model, double Now)
	{
		Source.LocalId = 1;
		Source.Bots.Add(2);
		Source.Names.Add(2, TEXT("Opponent"));
		Source.Pawn.bValid = true;
		Source.Pawn.Health = 64.f;
		Source.Pawn.Stance = EVerseStance::Crouch;
		Source.Pawn.bHasWeapon = true;
		Source.Pawn.WeaponId = TEXT("graveline");
		Source.Pawn.Magazine = 17;
		Source.Pawn.MagazineSize = 30;
		Source.Pawn.bChambered = true;
		Source.Pawn.Reserve = 90;
		Source.Pawn.Gadgets = {{TEXT("bulwark"), 1, 1, 0.f}, {TEXT("breach_charge"), 1, 2, 0.f}};
		Source.View.Rotation = FRotator(-2.f, 35.f, 0.f);
		Source.View.HorizontalFovDeg = 100.f;
		Source.BoltDirection = (Source.View.Rotation + FRotator(1.4f, 0.6f, 0.f)).Vector();
		Source.SpreadDeg = 1.1f;
		Model.SetLocalPlayerId(1);
		FVerseHitEvent Hit;
		Hit.InstigatorId = 1;
		Hit.VictimId = 2;
		Hit.bHeadshot = 1;
		Model.OnHit(Hit, Now);
		FVerseHitEvent Taken;
		Taken.InstigatorId = 2;
		Taken.VictimId = 1;
		Taken.Damage = 36.f;
		Taken.Direction = FVector_NetQuantizeNormal(FRotator(0.f, 35.f + 120.f, 0.f).Vector() * -1.f);
		Model.OnHit(Taken, Now);
		FVerseDeathEvent Earlier;
		Earlier.KillerId = 1;
		Earlier.VictimId = 2;
		Earlier.WeaponId = TEXT("graveline");
		Earlier.LastZone = EVerseHitZone::Head;
		Earlier.RespawnAt = 1e9;
		Model.OnDeath(Earlier, Now - 2.0);
		Earlier.KillerId = 2;
		Earlier.VictimId = 1;
		Earlier.WeaponId = TEXT("tallow");
		Earlier.LastZone = EVerseHitZone::UpperTorso;
		Earlier.RespawnAt = -1.0;
		Model.OnDeath(Earlier, Now - 1.0);
		Model.Tick(Now, 0.0);
	}

	void DrawFrame(UCanvas* Canvas, const FVerseHudFrame& Frame, const FVector2D& Offset)
	{
		FVerseHudDrawList List;
		FVerseHudPainter::Paint(Frame, List, FVerseHudPainter::DefaultMeasure());
		for (FVerseHudDrawList::FLine& L : List.Lines) { L.A += Offset; L.B += Offset; }
		for (FVerseHudDrawList::FRect& R : List.Rects) { R.Min += Offset; R.Max += Offset; }
		for (FVerseHudDrawList::FTri& T : List.Tris) { T.A += Offset; T.B += Offset; T.C += Offset; }
		for (FVerseHudDrawList::FLabel& T : List.Labels) { T.Position += Offset; }
		FVerseHudCanvasRenderer::Render(Canvas, List);
	}

	/** Runs one step per frame until every step reports done. */
	struct FSteps
	{
		TArray<TFunction<bool()>> Steps;
		int32 Index = 0;
		bool Update()
		{
			while (Index < Steps.Num())
			{
				if (!Steps[Index]())
				{
					return false;
				}
				++Index;
			}
			return true;
		}
	};
}

using namespace VerseUiVisual;

// Evidence: HUD screenshots in a fight at 1080p, 1440p, 4K (drawn by the real painter and canvas
// renderer into a render target of that size) and the kill cam contact sheet.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiVisualHudTest, "Verse.Visual.WP18.Hud", Flags)
bool FVerseUiVisualHudTest::RunTest(const FString&)
{
	if (SkipHeadless(*this))
	{
		return true;
	}
	UWorld* World = GameWorld();
	if (!World)
	{
		AddError(TEXT("needs a game world with a viewport (run through scripts/unreal/screenshot.py)"));
		return false;
	}
	UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(World);
	if (!TestNotNull(TEXT("UI subsystem"), Ui))
	{
		return false;
	}
	const FString Dir = ProofDir(TEXT("18.1-18.4"));
	const double Now = 100.0;
	FFakeVerseHudSource Source;
	FVerseHudModel Model;
	FightSource(Source, Model, Now);

	const FIntPoint Sizes[] = {FIntPoint(1920, 1080), FIntPoint(2560, 1440), FIntPoint(3840, 2160)};
	for (const FIntPoint& Size : Sizes)
	{
		UTextureRenderTarget2D* Target = UKismetRenderingLibrary::CreateRenderTarget2D(World, Size.X, Size.Y, RTF_RGBA8_SRGB, FLinearColor::Black);
		UCanvas* Canvas = nullptr;
		FVector2D CanvasSize;
		FDrawToRenderTargetContext Context;
		UKismetRenderingLibrary::BeginDrawCanvasToRenderTarget(World, Target, Canvas, CanvasSize, Context);
		Backdrop(Canvas, CanvasSize, 18);
		FVerseHudFrame Frame;
		Frame.Model = &Model;
		Frame.Strings = &Ui->GetStrings();
		Frame.Source = &Source;
		Frame.Layout = Ui->ComputeLayout(CanvasSize);
		Source.GetPawnState(Frame.Pawn);
		Frame.bHasView = Source.GetView(Frame.View);
		Frame.Now = Now + 0.05;
		DrawFrame(Canvas, Frame, FVector2D::ZeroVector);
		UKismetRenderingLibrary::EndDrawCanvasToRenderTarget(World, Context);
		const FString Path = FPaths::Combine(Dir, FString::Printf(TEXT("hud_fight_%dx%d.png"), Size.X, Size.Y));
		TestTrue(FString::Printf(TEXT("saved %s"), *Path), SavePng(World, Target, Path));
	}

	// Kill cam contact sheet: six moments of one replay. Each tile: the HUD in kill cam mode and a
	// top-down plot of the server log (grey), the replayed killer (amber) and the camera (red).
	FVerseKillCamBuffer Buffer;
	auto PathAt = [](double T) { return FVector(600.0 * FMath::Cos(T * 1.1), 600.0 * FMath::Sin(T * 1.1), 90.0); };
	for (int32 I = 0; I <= 300; ++I)
	{
		const double T = 50.0 + I / 60.0;
		Buffer.AddPose(2, T, PathAt(T), FRotator(0.f, FMath::RadiansToDegrees(T * 1.1) + 90.f, 0.f));
	}
	FVerseDeathEvent Death;
	Death.KillerId = 2;
	Death.VictimId = 1;
	Death.WeaponId = TEXT("graveline");
	Death.ServerTime = 55.0;
	Death.RespawnAt = 58.0;
	FVerseKillCamPlayer Player;
	TestTrue(TEXT("kill cam begins"), Player.Begin(Buffer, Death, 1, 0.0, 55.0, false));
	FVerseHudModel CamModel;
	CamModel.SetLocalPlayerId(1);
	CamModel.OnDeath(Death, 0.0);

	const FVector2D Tile(960, 540);
	UTextureRenderTarget2D* Sheet = UKismetRenderingLibrary::CreateRenderTarget2D(World, 2880, 1080, RTF_RGBA8_SRGB, FLinearColor::Black);
	UCanvas* Canvas = nullptr;
	FVector2D CanvasSize;
	FDrawToRenderTargetContext Context;
	UKismetRenderingLibrary::BeginDrawCanvasToRenderTarget(World, Sheet, Canvas, CanvasSize, Context);
	const double Length = Player.GetClipEnd() - Player.GetClipStart();
	for (int32 K = 0; K < 6; ++K)
	{
		const double LocalT = Length * K / 5.0;
		Player.Tick(LocalT);
		const FVector2D Origin((K % 3) * Tile.X, (K / 3) * Tile.Y);
		FCanvasTileItem Clear(Origin, Tile, FLinearColor(0.006f, 0.006f, 0.007f));
		Canvas->Canvas->DrawItem(Clear);
		FFakeVerseHudSource CamSource;
		CamSource.LocalId = 1;
		CamSource.Bots.Add(2);
		CamSource.ServerTime = 55.0 + LocalT;
		FVerseHudFrame Frame;
		Frame.Model = &CamModel;
		Frame.Strings = &Ui->GetStrings();
		Frame.Source = &CamSource;
		Frame.Layout = Ui->ComputeLayout(Tile);
		Frame.ServerTime = CamSource.ServerTime;
		Frame.bKillCam = Player.IsPlaying() || K == 5;
		Frame.KillCamKillerId = 2;
		Frame.SkipKeyName = Ui->GetKeyMap().GetKey(TEXT("skip_kill_cam")).GetDisplayName();
		DrawFrame(Canvas, Frame, Origin);

		// Top-down plot, 1 px = 4 cm, centred in the tile.
		const FVector2D Centre = Origin + FVector2D(Tile.X * 0.5, Tile.Y * 0.56);
		auto Map = [&Centre](const FVector& P) { return Centre + FVector2D(P.X, P.Y) / 4.0; };
		for (double T = 51.0; T < 55.0; T += 1.0 / 30.0)
		{
			FCanvasLineItem Line(Map(PathAt(T)), Map(PathAt(T + 1.0 / 30.0)));
			Line.SetColor(FLinearColor(0.35f, 0.33f, 0.30f));
			Canvas->Canvas->DrawItem(Line);
		}
		FVector Killer;
		FRotator Aim;
		FVector Cam;
		FRotator CamRot;
		if (Player.GetKillerPose(Killer, Aim) && Player.GetCamera(Cam, CamRot))
		{
			FCanvasTileItem KillerDot(Map(Killer) - FVector2D(5, 5), FVector2D(10, 10), VerseUiTheme::Amber);
			Canvas->Canvas->DrawItem(KillerDot);
			FCanvasTileItem CamDot(Map(Cam) - FVector2D(4, 4), FVector2D(8, 8), VerseUiTheme::Red);
			Canvas->Canvas->DrawItem(CamDot);
			FCanvasLineItem Sight(Map(Cam), Map(Cam + CamRot.Vector() * 400.0));
			Sight.SetColor(VerseUiTheme::Red);
			Canvas->Canvas->DrawItem(Sight);
			const double Err = FVector::Distance(Killer, PathAt(Player.GetReplayTime()));
			FCanvasTextItem Info(Origin + FVector2D(16, Tile.Y - 30),
				FText::AsCultureInvariant(FString::Printf(TEXT("t %.2f / %.2f s   path error %.2f cm"), LocalT, Length, Err)),
				FCoreStyle::GetDefaultFontStyle("Regular", 11), VerseUiTheme::TextDim);
			Canvas->Canvas->DrawItem(Info);
		}
		FCanvasLineItem EdgeA(Origin, Origin + FVector2D(Tile.X, 0));
		EdgeA.SetColor(VerseUiTheme::Edge);
		Canvas->Canvas->DrawItem(EdgeA);
		FCanvasLineItem EdgeB(Origin, Origin + FVector2D(0, Tile.Y));
		EdgeB.SetColor(VerseUiTheme::Edge);
		Canvas->Canvas->DrawItem(EdgeB);
	}
	UKismetRenderingLibrary::EndDrawCanvasToRenderTarget(World, Context);
	TestTrue(TEXT("kill cam contact sheet saved"), SavePng(World, Sheet, FPaths::Combine(ProofDir(TEXT("18.5")), TEXT("kill_cam_contact_sheet.png"))));
	return true;
}

// Evidence: one screenshot per locale of the armoury, the other screens, and the live HUD drawn
// through the real AHUD post-render path, captured from the game viewport.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiVisualMenusTest, "Verse.Visual.WP18.Menus", Flags)
bool FVerseUiVisualMenusTest::RunTest(const FString&)
{
	if (SkipHeadless(*this))
	{
		return true;
	}
	UWorld* World = GameWorld();
	UVerseUiSubsystem* Ui = World ? UVerseUiSubsystem::Get(World) : nullptr;
	if (!Ui)
	{
		AddError(TEXT("needs a game world with a viewport and the UI subsystem (screenshot.py)"));
		return false;
	}
	TSharedPtr<FFakeVerseHudSource> Source = MakeShared<FFakeVerseHudSource>();
	TSharedPtr<FFakeVerseUiGamePort> Game = MakeShared<FFakeVerseUiGamePort>();
	TSharedPtr<FFakeVerseUiBridgePort> Bridge = MakeShared<FFakeVerseUiBridgePort>();
	Ui->SetHudSource(Source);
	Ui->SetGamePort(Game);
	Ui->SetBridgePort(Bridge);

	TSharedRef<FSteps> Steps = MakeShared<FSteps>();
	auto Shot = [Steps](const FString& Path, TFunction<void()> Setup)
	{
		TSharedRef<double> Started = MakeShared<double>(0.0);
		Steps->Steps.Add([Setup, Path, Started]
			{
				Setup();
				IFileManager::Get().Delete(*Path);
				*Started = FPlatformTime::Seconds();
				return true;
			});
		// Let Slate lay the screen out for a few frames, then capture.
		Steps->Steps.Add([Started] { return FPlatformTime::Seconds() - *Started > 0.6; });
		Steps->Steps.Add([Path] { FScreenshotRequest::RequestScreenshot(Path, true, false); return true; });
		Steps->Steps.Add([Path, Started] { return IFileManager::Get().FileExists(*Path) || FPlatformTime::Seconds() - *Started > 10.0; });
	};

	const FString ArmouryDir = ProofDir(TEXT("18.6"));
	for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
	{
		Shot(FPaths::Combine(ArmouryDir, FString::Printf(TEXT("armoury_%s_1080p.png"), *Lang)), [Ui, Lang, Game]
			{
				Game->bDuel = false;
				Ui->GetMutableStrings().SetLanguage(Lang);
				Ui->GetArmoury().SelectTier(TEXT("adaptive"));
				Ui->ShowScreen(EVerseUiScreen::Armoury);
			});
	}
	Shot(FPaths::Combine(ProofDir(TEXT("18.7")), TEXT("verse_bar_en_1080p.png")), [Ui, Game]
		{
			Game->bDuel = false;
			Ui->GetMutableStrings().SetLanguage(TEXT("en"));
			Ui->ShowScreen(EVerseUiScreen::None);
		});
	Shot(FPaths::Combine(ProofDir(TEXT("18.8")), TEXT("esc_menu_en_1080p.png")), [Ui, Game]
		{
			Game->bDuel = true;
			Ui->ShowScreen(EVerseUiScreen::EscMenu);
		});
	Shot(FPaths::Combine(ProofDir(TEXT("18.8")), TEXT("settings_de_1080p.png")), [Ui]
		{
			Ui->GetMutableStrings().SetLanguage(TEXT("de"));
			Ui->ShowScreen(EVerseUiScreen::Settings);
		});
	Shot(FPaths::Combine(ProofDir(TEXT("18.9")), TEXT("end_of_set_en_1080p.png")), [Ui, Source]
		{
			Ui->GetMutableStrings().SetLanguage(TEXT("en"));
			Source->Bots.Add(2);
			Source->Skill = 0.62f;
			FVerseSetSummary Summary;
			Summary.SetIndex = 3;
			Summary.BotTier = TEXT("adaptive");
			Summary.Outcome = EVerseSetOutcome::Won;
			Summary.Person = {};
			Summary.Person.PlayerId = 1;
			Summary.Person.Kills = 10;
			Summary.Person.Deaths = 7;
			Summary.Person.Headshots = 4;
			Summary.Person.Finishers = 1;
			Summary.Person.ShotsFired = 214;
			Summary.Person.ShotsHit = 66;
			Summary.Person.DamageDealt = 1342;
			Summary.Person.WallsBreached = 3;
			Summary.Person.BestStreak = 4;
			Summary.Opponent.PlayerId = 2;
			Summary.Opponent.bIsBot = true;
			Summary.Opponent.Kills = 7;
			Summary.Opponent.Deaths = 10;
			Summary.Opponent.Headshots = 2;
			Summary.Opponent.ShotsFired = 251;
			Summary.Opponent.ShotsHit = 70;
			Summary.Opponent.DamageDealt = 1012;
			Summary.Opponent.WallsBreached = 2;
			Summary.Opponent.BestStreak = 3;
			UVerseEventHub::Get(Ui)->OnSetEnded.Broadcast(Summary);
		});
	Shot(FPaths::Combine(ProofDir(TEXT("18.1-18.4")), TEXT("hud_live_viewport_1080p.png")), [Ui, Source, Game]
		{
			Game->bDuel = true;
			Ui->ShowScreen(EVerseUiScreen::None);
			FightSource(*Source, Ui->GetMutableHudModel(), FPlatformTime::Seconds() + 0.5);
		});
	Steps->Steps.Add([this, Ui, ArmouryDir]
		{
			for (const FString& Lang : FVerseUiStrings::SupportedLanguages())
			{
				const FString Path = FPaths::Combine(ArmouryDir, FString::Printf(TEXT("armoury_%s_1080p.png"), *Lang));
				TestTrue(FString::Printf(TEXT("armoury screenshot %s"), *Lang), IFileManager::Get().FileExists(*Path));
			}
			Ui->ShowScreen(EVerseUiScreen::None);
			Ui->GetMutableStrings().SetLanguage(TEXT("en"));
			Ui->SetHudSource(nullptr);
			Ui->SetGamePort(nullptr);
			Ui->SetBridgePort(nullptr);
			return true;
		});
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([Steps] { return Steps->Update(); }));
	return true;
}

// A18.3: HUD at most 0.3 ms game thread plus GPU, measured in the running game at 1080p.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseUiVisualCostTest, "Verse.Visual.WP18.Cost", Flags)
bool FVerseUiVisualCostTest::RunTest(const FString&)
{
	if (SkipHeadless(*this))
	{
		return true;
	}
	UWorld* World = GameWorld();
	UVerseUiSubsystem* Ui = World ? UVerseUiSubsystem::Get(World) : nullptr;
	if (!Ui)
	{
		AddError(TEXT("needs a game world with a viewport and the UI subsystem (screenshot.py)"));
		return false;
	}
	TSharedPtr<FFakeVerseHudSource> Source = MakeShared<FFakeVerseHudSource>();
	TSharedPtr<FFakeVerseUiGamePort> Game = MakeShared<FFakeVerseUiGamePort>();
	Game->bDuel = true;
	Ui->SetHudSource(Source);
	Ui->SetGamePort(Game);
	Ui->ShowScreen(EVerseUiScreen::None);
	FightSource(*Source, Ui->GetMutableHudModel(), FPlatformTime::Seconds() + 1000.0);

	struct FState
	{
		int32 Frame = 0;
		TArray<double> GpuOn;
		TArray<double> GpuOff;
		double GameThread = 0.0;
	};
	TSharedRef<FState> State = MakeShared<FState>();
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, Ui, State]
		{
			// 8 alternating blocks of 60 frames, HUD on and off; the first 30 frames warm up.
			const int32 Block = 60;
			const int32 Warm = 30;
			const int32 F = State->Frame++;
			if (F < Warm)
			{
				return false;
			}
			const int32 Index = (F - Warm) / Block;
			const bool bOn = Index % 2 == 0;
			Ui->bDrawHudOnPostRender = bOn;
			if ((F - Warm) % Block > 5)
			{
				const double GpuMs = FPlatformTime::ToMilliseconds(RHIGetGPUFrameCycles());
				(bOn ? State->GpuOn : State->GpuOff).Add(GpuMs);
			}
			if (Index < 8)
			{
				return false;
			}
			Ui->bDrawHudOnPostRender = true;
			auto Median = [](TArray<double> V) { V.Sort(); return V.Num() ? V[V.Num() / 2] : 0.0; };
			const double On = Median(State->GpuOn);
			const double Off = Median(State->GpuOff);
			const double GameThread = Ui->GetHudCostMs();
			const double Gpu = FMath::Max(0.0, On - Off);
			const FString Json = FString::Printf(TEXT("{\"resolution\":\"1920x1080\",\"hud_game_thread_ms\":%.4f,\"gpu_frame_ms_hud_on\":%.4f,\"gpu_frame_ms_hud_off\":%.4f,\"hud_gpu_ms\":%.4f,\"total_ms\":%.4f,\"budget_ms\":0.3}"),
				GameThread, On, Off, Gpu, GameThread + Gpu);
			FFileHelper::SaveStringToFile(Json, *FPaths::Combine(ProofDir(TEXT("18.1-18.4")), TEXT("hud_cost.json")));
			AddInfo(Json);
			TestTrue(TEXT("HUD game thread measured"), GameThread > 0.0);
			TestTrue(TEXT("HUD at most 0.3 ms game thread plus GPU"), GameThread + Gpu <= 0.3);
			Ui->SetHudSource(nullptr);
			Ui->SetGamePort(nullptr);
			return true;
		}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

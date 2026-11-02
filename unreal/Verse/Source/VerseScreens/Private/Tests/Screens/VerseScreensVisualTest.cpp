#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Cells/VerseCells.h"
#include "Engine/CanvasRenderTarget2D.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "HAL/FileManager.h"
#include "ImageUtils.h"
#include "Misc/App.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Render/VerseTerminalTheme.h"
#include "RenderingThread.h"
#include "Screens/VerseScreenSurface.h"
#include "Screens/VerseTerminalMonitorComponent.h"
#include "TextureResource.h"

namespace VerseScreensVisualTest
{
	FVerseCellRun Cells(uint16 Col, const FString& Text, uint32 Fg, uint32 Bg = 0, uint16 Attrs = 0)
	{
		FVerseCellRun R;
		R.Col = Col;
		R.Text = Text;
		R.Fg = Fg;
		R.Bg = Bg;
		R.Attrs = Attrs;
		VerseCells::BuildClusters(R);
		R.Cells = uint16(R.ClusterEnds.Num());
		return R;
	}

	uint32 Pal(int32 I) { return (VerseCells::ModePalette << 24) | uint32(I); }

	/** The golden pane of parity E-03: ANSI colours, a box-drawing frame, a wide glyph, 16 bg swatches. */
	FVerseCellFrame GoldenPane()
	{
		FVerseCellFrame F;
		F.Kind = EVerseCellsKind::Snapshot;
		F.Ref = 1;
		F.Seq = 1;
		F.Cols = 80;
		F.Rows = 24;
		F.CursorRow = 21;
		F.CursorCol = 4;
		auto AddRow = [&F](int32 Row, TArray<FVerseCellRun> Runs)
		{
			FVerseCellRow& R = F.RowsChanged.AddDefaulted_GetRef();
			R.Row = uint16(Row);
			R.Runs = MoveTemp(Runs);
		};
		AddRow(0, {Cells(0, TEXT("┌") + FString::ChrN(78, TEXT('─')) + TEXT("┐"), Pal(8))});
		AddRow(1, {Cells(0, TEXT("│"), Pal(8)), Cells(2, TEXT("verse monitor test pane"), Pal(3), 0, VerseCells::Bold), Cells(79, TEXT("│"), Pal(8))});
		AddRow(3, {Cells(2, TEXT("$ pytest -q"), 0)});
		AddRow(4, {Cells(2, TEXT("42 passed"), (VerseCells::ModeRgb << 24) | 0x4fb86a, 0, VerseCells::Bold), Cells(12, TEXT("in 3.1 s"), Pal(8), 0, VerseCells::Dim)});
		AddRow(5, {Cells(2, TEXT("1 failed"), Pal(1), 0, VerseCells::Underline)});
		AddRow(6, {Cells(2, TEXT("wide:"), 0), Cells(8, TEXT("漢字"), Pal(6), 0, VerseCells::Wide), Cells(13, TEXT("inverse"), Pal(4), 0, VerseCells::Inverse)});
		TArray<FVerseCellRun> Swatches;
		for (int32 I = 0; I < 16; ++I)
		{
			Swatches.Add(Cells(uint16(2 + I * 4), TEXT("    "), 0, Pal(I)));
		}
		AddRow(8, MoveTemp(Swatches));
		AddRow(21, {Cells(2, TEXT("> "), Pal(2), 0, VerseCells::Bold)});
		AddRow(23, {Cells(0, TEXT("└") + FString::ChrN(78, TEXT('─')) + TEXT("┘"), Pal(8))});
		return F;
	}

	UWorld* GameWorld()
	{
		for (const FWorldContext& Ctx : GEngine->GetWorldContexts())
		{
			if ((Ctx.WorldType == EWorldType::Game || Ctx.WorldType == EWorldType::PIE) && Ctx.World())
			{
				return Ctx.World();
			}
		}
		return nullptr;
	}
}

using namespace VerseScreensVisualTest;

// WP16.2 / parity E-03 (rendered): the golden pane painted into a monitor's render target, read back
// and saved as proof; the background swatches measured against the theme palette (A16.3 on the GPU).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualScreensMonitor, "Verse.Visual.Screens.MonitorTarget",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseVisualScreensMonitor::RunTest(const FString&)
{
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no renderer (-nullrhi): the rendered monitor check runs in the visual lane"));
		return true;
	}
	UWorld* World = GameWorld();
	if (!TestNotNull(TEXT("a game world"), World))
	{
		return false;
	}
	AActor* Desk = World->SpawnActor<AActor>();
	UVerseTerminalMonitorComponent* Monitor = NewObject<UVerseTerminalMonitorComponent>(Desk);
	Monitor->Resolution = FIntPoint(1280, 768);
	Monitor->PaneIds.Add(TEXT("ws_91:T1"));
	Desk->SetRootComponent(Monitor);
	Monitor->RegisterComponent();
	if (!Desk->HasActorBegunPlay())
	{
		Desk->DispatchBeginPlay();
	}
	UVerseScreenSurface* Surface = Monitor->Surface();
	if (!TestTrue(TEXT("monitor has a render target"), Surface && Surface->CanPaint()))
	{
		return false;
	}
	Monitor->ApplyFrame(GoldenPane());
	FVerseTerminalDrawList Scratch;
	TestEqual(TEXT("all 24 rows painted"), Monitor->Redraw(0.0, Scratch), 24);
	FlushRenderingCommands();

	UTextureRenderTarget2D* Target = Cast<UTextureRenderTarget2D>(Surface->GetTexture());
	FTextureRenderTargetResource* Resource = Target ? Target->GameThread_GetRenderTargetResource() : nullptr;
	TArray<FColor> Pixels;
	if (!TestTrue(TEXT("pixels read back"), Resource && Resource->ReadPixels(Pixels) && Pixels.Num() == 1280 * 768))
	{
		return false;
	}
	// The 16 background swatches of row 8: sample each centre.
	const FVerseTerminalLayout L = Monitor->Layout();
	const FVerseTerminalPalette& P = Monitor->Palette();
	double WorstChannel = 0.0;
	for (int32 I = 0; I < 16; ++I)
	{
		const int32 X = FMath::RoundToInt((2 + I * 4 + 2) * L.CellW);
		const int32 Y = FMath::RoundToInt((8 - L.FirstRow + 0.5f) * L.CellH);
		const FColor Got = Pixels[Y * 1280 + X];
		const FColor Want = P.Index(I);
		WorstChannel = FMath::Max(WorstChannel, double(FMath::Max3(FMath::Abs(Got.R - Want.R), FMath::Abs(Got.G - Want.G), FMath::Abs(Got.B - Want.B))));
	}
	AddInfo(FString::Printf(TEXT("rendered swatches: worst channel error %.0f of 255"), WorstChannel));
	TestTrue(TEXT("rendered swatch colours within 3 of the theme palette"), WorstChannel <= 3.0);

	TArray64<uint8> Png;
	FImageUtils::PNGCompressImageArray(1280, 768, TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
	const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP16/16.2"));
	IFileManager::Get().MakeDirectory(*Dir, true);
	TestTrue(TEXT("proof image saved"), FFileHelper::SaveArrayToFile(Png, *FPaths::Combine(Dir, TEXT("monitor_golden_pane.png"))));
	Desk->Destroy();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

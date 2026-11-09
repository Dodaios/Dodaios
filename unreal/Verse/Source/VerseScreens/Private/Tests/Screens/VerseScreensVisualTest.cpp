#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Cells/VerseCells.h"
#include "Dom/JsonObject.h"
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
#include "Screens/VerseScreenSurface.h"
#include "Screens/VerseTerminalMonitorComponent.h"
#include "Serialization/JsonSerializer.h"
#include "Tests/Screens/VerseColourDifference.h"
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

namespace VerseScreensVisualTest
{
	FColor PixelAt(const TArray<FColor>& Pixels, int32 W, int32 H, float X, float Y)
	{
		const int32 PX = FMath::Clamp(FMath::RoundToInt(X), 0, W - 1);
		const int32 PY = FMath::Clamp(FMath::RoundToInt(Y), 0, H - 1);
		FColor C = Pixels[PY * W + PX];
		C.A = 255;
		return C;
	}

	/** The pixel of a cell's inner box farthest from the cell's ground: the core of the glyph (as web_reference.ts). */
	FColor GlyphCore(const TArray<FColor>& Pixels, int32 W, int32 H, float X, float Y, float CW, float CH, FColor Ground)
	{
		FColor Best = Ground;
		int32 BestD = -1;
		for (int32 PY = FMath::CeilToInt(Y + CH * 0.15f); PY < Y + CH * 0.85f; ++PY)
		{
			for (int32 PX = FMath::CeilToInt(X + CW * 0.15f); PX < X + CW * 0.85f; ++PX)
			{
				const FColor P = PixelAt(Pixels, W, H, float(PX), float(PY));
				const int32 D = FMath::Square(int32(P.R) - Ground.R) + FMath::Square(int32(P.G) - Ground.G) + FMath::Square(int32(P.B) - Ground.B);
				if (D > BestD)
				{
					BestD = D;
					Best = P;
				}
			}
		}
		return Best;
	}

	uint16 AttrsFromJson(const TArray<TSharedPtr<FJsonValue>>& Names)
	{
		uint16 Attrs = 0;
		for (const TSharedPtr<FJsonValue>& A : Names)
		{
			for (int32 B = 0; B < VerseCells::AttrCount; ++B)
			{
				Attrs |= A->AsString() == VerseCells::AttrName(B) ? uint16(1 << B) : 0;
			}
		}
		return Attrs;
	}
}

// A16.3 (rendered): the 256-colour and RGB test screen painted onto a monitor render target on the GPU,
// read back and sampled like the web reference (Content/Verse/Test/WP16/colour_reference.json, captured
// from the IDE's own painter by make_web_reference.py): the block cell, the core of an "M" glyph drawn
// as canvas text, and the blank background cell. Pass: mean CIEDE2000 at most 2.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualScreensColour, "Verse.Visual.Screens.Colour",
	EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)
bool FVerseVisualScreensColour::RunTest(const FString&)
{
	if (!FApp::CanEverRender())
	{
		AddInfo(TEXT("no renderer (-nullrhi): the rendered colour check runs in the visual lane"));
		return true;
	}
	FString Text;
	TSharedPtr<FJsonObject> Root;
	const FString Path = FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Verse/Test/WP16/colour_reference.json"));
	if (!TestTrue(TEXT("colour_reference.json loads"), FFileHelper::LoadFileToString(Text, *Path)
		&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root.IsValid()))
	{
		return false;
	}
	const int32 Cols = int32(Root->GetNumberField(TEXT("cols")));
	const int32 Rows = int32(Root->GetNumberField(TEXT("rows")));
	const FString Glyphs = Root->GetStringField(TEXT("glyphs"));
	const TArray<TSharedPtr<FJsonValue>> Samples = Root->GetArrayField(TEXT("samples"));

	FVerseCellFrame F;
	F.Kind = EVerseCellsKind::Snapshot;
	F.Ref = 1;
	F.Seq = 1;
	F.Cols = uint16(Cols);
	F.Rows = uint16(Rows);
	F.CursorRow = -1;
	F.CursorCol = -1;
	TMap<int32, TArray<FVerseCellRun>> RowRuns;
	for (const TSharedPtr<FJsonValue>& V : Samples)
	{
		const FJsonObject& S = *V->AsObject();
		uint32 Fg = 0, Bg = 0;
		VerseCells::ColourFromJson(S.TryGetField(TEXT("fg")), Fg);
		VerseCells::ColourFromJson(S.TryGetField(TEXT("bg")), Bg);
		RowRuns.FindOrAdd(int32(S.GetNumberField(TEXT("row"))))
			.Add(Cells(uint16(S.GetNumberField(TEXT("col"))), Glyphs, Fg, Bg, AttrsFromJson(S.GetArrayField(TEXT("attrs")))));
	}
	RowRuns.KeySort(TLess<int32>());
	for (TPair<int32, TArray<FVerseCellRun>>& R : RowRuns)
	{
		FVerseCellRow& Row = F.RowsChanged.AddDefaulted_GetRef();
		Row.Row = uint16(R.Key);
		Row.Runs = MoveTemp(R.Value);
	}

	UWorld* World = GameWorld();
	if (!TestNotNull(TEXT("a game world"), World))
	{
		return false;
	}
	constexpr int32 W = 1280;
	const int32 H = 40 * Rows;
	AActor* Desk = World->SpawnActor<AActor>();
	UVerseTerminalMonitorComponent* Monitor = NewObject<UVerseTerminalMonitorComponent>(Desk);
	Monitor->Resolution = FIntPoint(W, H);
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
		Desk->Destroy();
		return false;
	}
	Monitor->ApplyFrame(MoveTemp(F));
	FVerseTerminalDrawList Scratch;
	Monitor->Redraw(0.0, Scratch);
	const FVerseTerminalLayout L = Monitor->Layout();
	TestEqual(TEXT("every row of the test screen shown"), L.VisibleRows, Rows);

	UTextureRenderTarget2D* Target = Cast<UTextureRenderTarget2D>(Surface->GetTexture());
	FTextureRenderTargetResource* Resource = Target ? Target->GameThread_GetRenderTargetResource() : nullptr;
	TArray<FColor> Pixels;
	if (!TestTrue(TEXT("pixels read back"), Resource && Resource->ReadPixels(Pixels) && Pixels.Num() == W * H))
	{
		Desk->Destroy();
		return false;
	}

	double Sum[3] = {0.0, 0.0, 0.0};
	double Worst = 0.0;
	FString WorstAt;
	int32 N = 0;
	const TCHAR* Kinds[3] = {TEXT("block"), TEXT("text"), TEXT("bg")};
	for (const TSharedPtr<FJsonValue>& V : Samples)
	{
		const FJsonObject& S = *V->AsObject();
		const int32 Row = int32(S.GetNumberField(TEXT("row")));
		const int32 Col = int32(S.GetNumberField(TEXT("col")));
		const float Y = float(Row - L.FirstRow) * L.CellH;
		auto X = [&L](int32 C) { return float(C) * L.CellW; };
		const FColor Ground = PixelAt(Pixels, W, H, X(Col + 2) + L.CellW * 0.5f, Y + L.CellH * 0.5f);
		const FColor Got[3] = {
			PixelAt(Pixels, W, H, X(Col) + L.CellW * 0.25f, Y + L.CellH * 0.25f),
			GlyphCore(Pixels, W, H, X(Col + 1), Y, L.CellW, L.CellH, Ground),
			Ground,
		};
		const TSharedPtr<FJsonObject> Web = S.GetObjectField(TEXT("web"));
		for (int32 K = 0; K < 3; ++K)
		{
			const FColor Want = FColor::FromHex(Web->GetStringField(Kinds[K]));
			const double D = VerseColourDifference::DeltaE2000(Got[K], Want);
			Sum[K] += D;
			if (D > Worst)
			{
				Worst = D;
				WorstAt = FString::Printf(TEXT("%s at row %d col %d: drawn %s, web %s"), Kinds[K], Row, Col, *Got[K].ToHex(), *Want.ToHex());
			}
		}
		++N;
	}
	const double Mean = N > 0 ? (Sum[0] + Sum[1] + Sum[2]) / (3.0 * N) : 999.0;
	AddInfo(FString::Printf(TEXT("A16.3 rendered vs web: %d cells x 3 samples, mean dE2000 %.3f (block %.3f, text %.3f, bg %.3f), worst %.3f (%s)"),
		N, Mean, Sum[0] / FMath::Max(1, N), Sum[1] / FMath::Max(1, N), Sum[2] / FMath::Max(1, N), Worst, *WorstAt));
	TestTrue(TEXT("every sample of the reference"), N >= 500);
	TestTrue(TEXT("mean CIEDE2000 at most 2"), Mean <= 2.0);

	const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP16/16.2"));
	IFileManager::Get().MakeDirectory(*Dir, true);
	TArray64<uint8> Png;
	FImageUtils::PNGCompressImageArray(W, H, TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
	FFileHelper::SaveArrayToFile(Png, *FPaths::Combine(Dir, TEXT("monitor_colour_screen.png")));
	TSharedRef<FJsonObject> Proof = MakeShared<FJsonObject>();
	Proof->SetStringField(TEXT("test"), TEXT("Verse.Visual.Screens.Colour"));
	Proof->SetStringField(TEXT("reference"), Root->GetStringField(TEXT("source")));
	Proof->SetNumberField(TEXT("cells"), N);
	Proof->SetNumberField(TEXT("mean_ciede2000"), Mean);
	Proof->SetNumberField(TEXT("mean_block"), Sum[0] / FMath::Max(1, N));
	Proof->SetNumberField(TEXT("mean_text"), Sum[1] / FMath::Max(1, N));
	Proof->SetNumberField(TEXT("mean_bg"), Sum[2] / FMath::Max(1, N));
	Proof->SetNumberField(TEXT("worst_ciede2000"), Worst);
	Proof->SetStringField(TEXT("worst_sample"), WorstAt);
	Proof->SetNumberField(TEXT("budget_mean"), 2.0);
	FString Json;
	FJsonSerializer::Serialize(Proof, TJsonWriterFactory<>::Create(&Json));
	FFileHelper::SaveStringToFile(Json, *FPaths::Combine(Dir, TEXT("colour.json")));
	Desk->Destroy();
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

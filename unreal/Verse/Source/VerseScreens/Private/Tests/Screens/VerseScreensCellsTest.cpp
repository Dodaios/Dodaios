#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Cells/VerseCells.h"
#include "Cells/VerseTerminalGrid.h"
#include "Dom/JsonObject.h"
#include "Render/VerseTerminalPainter.h"
#include "Render/VerseTerminalTheme.h"
#include "Tests/Screens/Fakes/FakeVerseCommandLink.h"
#include "Tests/Screens/VerseColourDifference.h"

#define VERSE_SCREENS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseScreensCellsTest
{
	bool FrameFromVector(FAutomationTestBase& Test, const FJsonObject& Vector, FVerseCellFrame& Out)
	{
		const TSharedPtr<FJsonObject>* Frame = nullptr;
		const TSharedPtr<FJsonObject>* Data = nullptr;
		if (!Vector.TryGetObjectField(TEXT("frame"), Frame) || !(*Frame)->TryGetObjectField(TEXT("data"), Data))
		{
			Test.AddError(TEXT("vector without frame.data"));
			return false;
		}
		double Seq = 0;
		double Base = 0;
		double Ref = 0;
		(*Frame)->TryGetNumberField(TEXT("seq"), Seq);
		(*Frame)->TryGetNumberField(TEXT("base"), Base);
		Vector.TryGetNumberField(TEXT("ref"), Ref);
		FString Error;
		if (!VerseCells::DecodeJson(**Data, uint32(Seq), uint32(Base), Out, Error))
		{
			Test.AddError(FString::Printf(TEXT("cells.json/1 decode failed: %s"), *Error));
			return false;
		}
		Out.Ref = uint16(Ref);
		return true;
	}

	/** A pane frame of the given geometry with one run per listed row. */
	FVerseCellFrame MakeFrame(EVerseCellsKind Kind, uint32 Seq, uint32 Base, int32 Cols, int32 Rows, TArray<TPair<int32, FString>> RowsText)
	{
		FVerseCellFrame F;
		F.Kind = Kind;
		F.Seq = Seq;
		F.Base = Base;
		F.Cols = uint16(Cols);
		F.Rows = uint16(Rows);
		F.CursorRow = 0;
		F.CursorCol = 0;
		for (const TPair<int32, FString>& R : RowsText)
		{
			FVerseCellRow& Row = F.RowsChanged.AddDefaulted_GetRef();
			Row.Row = uint16(R.Key);
			FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
			Run.Text = R.Value;
			VerseCells::BuildClusters(Run);
			Run.Cells = uint16(Run.ClusterEnds.Num());
		}
		return F;
	}

	FColor ParseHex(const FString& S)
	{
		return FColor::FromHex(S);
	}

}

using namespace VerseScreensCellsTest;
using namespace VerseColourDifference;

// A16.1: every golden cells.bin/1 vector decodes to its cells.json/1 frame, and encodes back byte-exact.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensCellsGolden, "Verse.Screens.Cells.GoldenVectors", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensCellsGolden::RunTest(const FString&)
{
	const TSharedPtr<FJsonValue> Root = VerseBridgeGolden::Load(TEXT("cells/vectors.json"));
	const TSharedPtr<FJsonObject>* RootObj = nullptr;
	if (!TestTrue(TEXT("vectors.json loads"), Root.IsValid() && Root->TryGetObject(RootObj)))
	{
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* Valid = nullptr;
	if (!TestTrue(TEXT("valid vectors"), (*RootObj)->TryGetArrayField(TEXT("valid"), Valid) && Valid->Num() >= 10))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& V : *Valid)
	{
		const FJsonObject& Vector = *V->AsObject();
		const FString Name = Vector.GetStringField(TEXT("name"));
		const TArray<uint8> Bytes = VerseBridgeGolden::Hex(Vector.GetStringField(TEXT("bin_hex")));
		FVerseCellFrame FromBin;
		FString Error;
		if (!TestTrue(FString::Printf(TEXT("%s: binary decodes (%s)"), *Name, *Error), VerseCells::DecodeBinary(Bytes, FromBin, Error)))
		{
			AddError(Error);
			continue;
		}
		FVerseCellFrame FromJson;
		if (!FrameFromVector(*this, Vector, FromJson))
		{
			continue;
		}
		TestTrue(FString::Printf(TEXT("%s: binary and JSON forms hold the same cells"), *Name), FromBin.SameCells(FromJson));
		TArray<uint8> Encoded;
		TestTrue(FString::Printf(TEXT("%s: encodes"), *Name), VerseCells::EncodeBinary(FromJson, Encoded, Error));
		TestTrue(FString::Printf(TEXT("%s: JSON form encodes to the golden bytes"), *Name), Encoded == Bytes);
		TArray<uint8> Again;
		VerseCells::EncodeBinary(FromBin, Again, Error);
		TestTrue(FString::Printf(TEXT("%s: decode then encode is byte-exact"), *Name), Again == Bytes);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensCellsMalformed, "Verse.Screens.Cells.RejectsMalformed", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensCellsMalformed::RunTest(const FString&)
{
	const TSharedPtr<FJsonValue> Root = VerseBridgeGolden::Load(TEXT("cells/vectors.json"));
	const TArray<TSharedPtr<FJsonValue>>* Invalid = nullptr;
	if (!TestTrue(TEXT("invalid vectors"), Root.IsValid() && Root->AsObject()->TryGetArrayField(TEXT("invalid"), Invalid) && Invalid->Num() >= 9))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& V : *Invalid)
	{
		const FJsonObject& Vector = *V->AsObject();
		FVerseCellFrame Frame;
		FString Error;
		TestFalse(FString::Printf(TEXT("%s is rejected (%s)"), *Vector.GetStringField(TEXT("name")), *Vector.GetStringField(TEXT("reason"))),
			VerseCells::DecodeBinary(VerseBridgeGolden::Hex(Vector.GetStringField(TEXT("bin_hex"))), Frame, Error));
	}
	// Strict UTF-8: an overlong slash inside an otherwise valid one-run frame.
	FVerseCellFrame F = MakeFrame(EVerseCellsKind::Snapshot, 1, 0, 10, 2, {{0, TEXT("/")}});
	TArray<uint8> Bytes;
	FString Error;
	VerseCells::EncodeBinary(F, Bytes, Error);
	const int32 TextAt = Bytes.Num() - 1;
	Bytes[TextAt] = 0xC0;
	Bytes.Insert(0xAF, TextAt + 1);
	// text_bytes (low byte) sits at header 24 + row record 4 + 14.
	Bytes[24 + 4 + 14] = 2;
	TestFalse(TEXT("overlong UTF-8 is rejected"), VerseCells::DecodeBinary(Bytes, F, Error));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensCellsJsonMessages, "Verse.Screens.Cells.JsonMessages", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensCellsJsonMessages::RunTest(const FString&)
{
	const TSharedPtr<FJsonValue> Root = VerseBridgeGolden::Load(TEXT("messages/screens.frame.json"));
	if (!TestTrue(TEXT("screens.frame fixtures load"), Root.IsValid()))
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& V : Root->AsArray())
	{
		const FJsonObject& Env = *V->AsObject();
		FVerseCellFrame Frame;
		FString Error;
		double Seq = 0, Base = 0;
		Env.TryGetNumberField(TEXT("seq"), Seq);
		Env.TryGetNumberField(TEXT("base"), Base);
		TestTrue(FString::Printf(TEXT("frame seq %d decodes (%s)"), int32(Seq), *Error),
			VerseCells::DecodeJson(*Env.GetObjectField(TEXT("data")), uint32(Seq), uint32(Base), Frame, Error));
		TestFalse(TEXT("pane id read"), Frame.PaneId.IsEmpty());
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensGridApply, "Verse.Screens.Grid.ApplyAndResync", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensGridApply::RunTest(const FString&)
{
	FVerseTerminalGrid Grid;
	TestEqual(TEXT("a delta before any snapshot asks for a resync"),
		Grid.Apply(MakeFrame(EVerseCellsKind::Delta, 5, 4, 20, 4, {{0, TEXT("x")}})), FVerseTerminalGrid::EApply::NeedsResync);
	TestEqual(TEXT("snapshot applies"), Grid.Apply(MakeFrame(EVerseCellsKind::Snapshot, 10, 0, 20, 4, {{0, TEXT("$ ls")}, {2, TEXT("done")}})),
		FVerseTerminalGrid::EApply::Applied);
	TestTrue(TEXT("a snapshot dirties every row"), Grid.DirtyRows().CountSetBits() == 4);
	TestEqual(TEXT("row 0 text"), Grid.RowText(0), FString(TEXT("$ ls")));
	TestEqual(TEXT("row 1 blank"), Grid.RowText(1), FString());
	Grid.ClearDirty();
	TestEqual(TEXT("a delta on the last seq applies"), Grid.Apply(MakeFrame(EVerseCellsKind::Delta, 12, 10, 20, 4, {{2, TEXT("ok")}})),
		FVerseTerminalGrid::EApply::Applied);
	TestTrue(TEXT("the delta's row replaced completely"), Grid.RowText(2) == TEXT("ok"));
	TestTrue(TEXT("only the changed row (and the cursor row) is dirty"), Grid.DirtyRows()[2] && !Grid.DirtyRows()[1] && !Grid.DirtyRows()[3]);
	TestEqual(TEXT("a gap (base is not the last seq) asks for a resync"),
		Grid.Apply(MakeFrame(EVerseCellsKind::Delta, 20, 15, 20, 4, {{1, TEXT("lost")}})), FVerseTerminalGrid::EApply::NeedsResync);
	TestEqual(TEXT("nothing of the refused delta is kept"), Grid.RowText(1), FString());
	TestEqual(TEXT("a delta with a new geometry asks for a resync"),
		Grid.Apply(MakeFrame(EVerseCellsKind::Delta, 13, 12, 30, 4, {{1, TEXT("x")}})), FVerseTerminalGrid::EApply::NeedsResync);

	// Wide glyphs: the second column reads as the continuation of the first.
	FVerseCellFrame Wide = MakeFrame(EVerseCellsKind::Snapshot, 30, 0, 10, 1, {});
	FVerseCellRow& Row = Wide.RowsChanged.AddDefaulted_GetRef();
	FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
	Run.Col = 2;
	Run.Text = TEXT("漢字");
	Run.Attrs = VerseCells::Wide;
	VerseCells::BuildClusters(Run);
	Run.Cells = uint16(Run.ClusterEnds.Num());
	Grid.Apply(MoveTemp(Wide));
	FVerseCellView Cell;
	Grid.CellAt(0, 4, Cell);
	TestTrue(TEXT("col 4 holds the second wide glyph"), !Cell.bContinuation && Cell.Grapheme == FStringView(TEXT("字")));
	Grid.CellAt(0, 5, Cell);
	TestTrue(TEXT("col 5 is its continuation"), Cell.bContinuation);
	Grid.CellAt(0, 6, Cell);
	TestTrue(TEXT("col 6 is blank"), Cell.bBlank);
	return true;
}

// Parity E-04: a 60-row pane on a 24-row monitor shows rows 37-60 (1-based).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensGridBottomBlock, "Verse.Screens.Grid.BottomBlock", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensGridBottomBlock::RunTest(const FString&)
{
	FVerseTerminalGrid Grid;
	Grid.Apply(MakeFrame(EVerseCellsKind::Snapshot, 1, 0, 80, 60, {{59, TEXT("bottom")}}));
	int32 First = 0, Count = 0;
	Grid.VisibleRange(24, First, Count);
	TestEqual(TEXT("first shown row is row 37 (index 36)"), First, 36);
	TestEqual(TEXT("24 rows shown"), Count, 24);
	const FVerseTerminalLayout L = FVerseTerminalLayout::Fit(960, 480, 80, 60, 2.f);
	TestEqual(TEXT("width fills the tile: 80 cols over 960 px"), L.CellW, 12.f);
	TestEqual(TEXT("rows that fit at that cell size"), L.VisibleRows, 20);
	TestEqual(TEXT("the bottom block of the pane"), L.FirstRow, 40);
	return true;
}

// Parity E-03 (AT): every drawn glyph lands on its bridge cell with its colour.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensPaintCells, "Verse.Screens.Paint.CellToGlyph", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensPaintCells::RunTest(const FString&)
{
	const TSharedPtr<FJsonValue> Root = VerseBridgeGolden::Load(TEXT("cells/vectors.json"));
	if (!TestTrue(TEXT("vectors load"), Root.IsValid()))
	{
		return false;
	}
	FVerseTerminalPalette Palette;
	Palette.Build(UVerseTerminalTheme::Default());
	for (const TSharedPtr<FJsonValue>& V : Root->AsObject()->GetArrayField(TEXT("valid")))
	{
		FVerseCellFrame Frame;
		if (!FrameFromVector(*this, *V->AsObject(), Frame) || Frame.Kind != EVerseCellsKind::Snapshot)
		{
			continue;
		}
		const FString Name = V->AsObject()->GetStringField(TEXT("name"));
		FVerseTerminalGrid Grid;
		Grid.Apply(MoveTemp(Frame));
		const FVerseTerminalLayout L = FVerseTerminalLayout::Fit(Grid.Cols() * 8, Grid.Rows() * 16, Grid.Cols(), Grid.Rows(), 2.f);
		FVerseTerminalDrawList List;
		VerseTerminalPainter::Build(Grid, Palette, L, true, false, List);
		TestEqual(FString::Printf(TEXT("%s: every row drawn"), *Name), List.RowsDrawn, Grid.Rows());
		int32 Checked = 0;
		for (const FVerseTerminalText& T : List.Texts)
		{
			const int32 Col = FMath::RoundToInt(T.Pos.X / L.CellW);
			TestEqual(TEXT("text sits on its column"), Col, T.Col);
			// Walk the text's clusters across its columns and compare with the grid.
			int32 C = T.Col;
			FVerseCellView First;
			Grid.CellAt(T.Row, C, First);
			FColor Fg, Bg;
			bool bHasBg = false;
			Palette.Resolve(First.Fg, First.Bg, First.Attrs, Fg, Bg, bHasBg);
			TestEqual(TEXT("text colour is the cell's resolved fg"), T.Colour, Fg);
			FString Joined;
			for (int32 K = 0; K < T.Cells; ++K)
			{
				FVerseCellView Cell;
				Grid.CellAt(T.Row, C + K, Cell);
				if (!Cell.bContinuation)
				{
					Joined.Append(Cell.Grapheme.GetData(), Cell.Grapheme.Len());
				}
			}
			TestEqual(FString::Printf(TEXT("%s: glyphs at row %d col %d"), *Name, T.Row, T.Col), Joined, FString(T.Text));
			++Checked;
		}
		TestTrue(FString::Printf(TEXT("%s: texts checked"), *Name), Checked > 0 || Name.Contains(TEXT("empty")));
	}
	return true;
}

// WP16.2 colour rules: Unreal's palette resolves every cell of the A16.3 test screen to the run colours
// the web painter itself resolved (snapshotXterm over a real xterm buffer, captured by
// Content/Verse/Test/WP16/make_web_reference.py). The rendered comparison is Verse.Visual.Screens.Colour.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensColourResolve, "Verse.Screens.Colour.ResolveMatchesWeb", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensColourResolve::RunTest(const FString&)
{
	FString Text;
	const FString Path = FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Verse/Test/WP16/colour_reference.json"));
	TSharedPtr<FJsonObject> Root;
	if (!TestTrue(TEXT("colour_reference.json loads"), FFileHelper::LoadFileToString(Text, *Path)
		&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root.IsValid()))
	{
		return false;
	}
	TestEqual(TEXT("reference format"), Root->GetStringField(TEXT("format")), FString(TEXT("wp16-web-colour-reference/1")));
	FVerseTerminalPalette Palette;
	Palette.Build(UVerseTerminalTheme::Default());
	double Sum = 0.0;
	double Worst = 0.0;
	int32 N = 0;
	const TArray<TSharedPtr<FJsonValue>> Samples = Root->GetArrayField(TEXT("samples"));
	for (const TSharedPtr<FJsonValue>& V : Samples)
	{
		const FJsonObject& Cell = *V->AsObject();
		uint32 Fg = 0, Bg = 0;
		uint16 Attrs = 0;
		VerseCells::ColourFromJson(Cell.TryGetField(TEXT("fg")), Fg);
		VerseCells::ColourFromJson(Cell.TryGetField(TEXT("bg")), Bg);
		for (const TSharedPtr<FJsonValue>& A : Cell.GetArrayField(TEXT("attrs")))
		{
			for (int32 B = 0; B < VerseCells::AttrCount; ++B)
			{
				Attrs |= A->AsString() == VerseCells::AttrName(B) ? uint16(1 << B) : 0;
			}
		}
		FColor DrawnFg, DrawnBg;
		bool bHasBg = false;
		Palette.Resolve(Fg, Bg, Attrs, DrawnFg, DrawnBg, bHasBg);
		const TSharedPtr<FJsonObject> Web = Cell.GetObjectField(TEXT("web_run"));
		FString WebBg;
		const bool bWebHasBg = Web->TryGetStringField(TEXT("bg"), WebBg);
		TestEqual(FString::Printf(TEXT("cell %d,%d: background shown"), int32(Cell.GetNumberField(TEXT("row"))), int32(Cell.GetNumberField(TEXT("col")))), bHasBg, bWebHasBg);
		const double DFg = DeltaE2000(DrawnFg, ParseHex(Web->GetStringField(TEXT("fg"))));
		const double DBg = DeltaE2000(bHasBg ? DrawnBg : Palette.Ground, bWebHasBg ? ParseHex(WebBg) : ParseHex(Root->GetStringField(TEXT("ground"))));
		Sum += DFg + DBg;
		Worst = FMath::Max(Worst, FMath::Max(DFg, DBg));
		N += 2;
	}
	const double Mean = N > 0 ? Sum / N : 999.0;
	AddInfo(FString::Printf(TEXT("resolve vs web runs: %d samples, mean dE2000 %.4f, worst %.4f"), N, Mean, Worst));
	TestTrue(TEXT("every cell of the test screen"), Samples.Num() >= 500);
	TestTrue(TEXT("resolved colours equal the web runs (worst dE2000 under 0.5)"), Worst < 0.5);
	TestTrue(TEXT("CIEDE2000 of identical colours is 0"), DeltaE2000(FColor(10, 200, 30), FColor(10, 200, 30)) < 1e-9);
	TestTrue(TEXT("CIEDE2000 separates black from white"), DeltaE2000(FColor::Black, FColor::White) > 99.0);
	return true;
}

// cells.json/1 colours: "#rrggbb" in either case (the contract does not ask for lower case).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensCellsHexCase, "Verse.Screens.Cells.HexColourCase", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensCellsHexCase::RunTest(const FString&)
{
	uint32 Upper = 0, Lower = 0, Bad = 0;
	TestTrue(TEXT("upper case reads"), VerseCells::ColourFromJson(MakeShared<FJsonValueString>(TEXT("#E3242B")), Upper));
	TestTrue(TEXT("lower case reads"), VerseCells::ColourFromJson(MakeShared<FJsonValueString>(TEXT("#e3242b")), Lower));
	TestEqual(TEXT("same colour"), Upper, Lower);
	TestEqual(TEXT("rgb mode and value"), Upper, (uint32(VerseCells::ModeRgb) << 24) | 0xe3242bu);
	TestFalse(TEXT("not a hex digit"), VerseCells::ColourFromJson(MakeShared<FJsonValueString>(TEXT("#E3242G")), Bad));
	TestFalse(TEXT("short"), VerseCells::ColourFromJson(MakeShared<FJsonValueString>(TEXT("#E3242")), Bad));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

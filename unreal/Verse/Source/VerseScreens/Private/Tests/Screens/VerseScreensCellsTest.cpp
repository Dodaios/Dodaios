#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Cells/VerseCells.h"
#include "Cells/VerseTerminalGrid.h"
#include "Dom/JsonObject.h"
#include "Render/VerseTerminalPainter.h"
#include "Render/VerseTerminalTheme.h"
#include "Tests/Screens/Fakes/FakeVerseCommandLink.h"

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

	/** sRGB 8-bit to CIELAB (D65). */
	FVector3d ToLab(const FColor& C)
	{
		auto Lin = [](double V)
		{
			V /= 255.0;
			return V <= 0.04045 ? V / 12.92 : FMath::Pow((V + 0.055) / 1.055, 2.4);
		};
		const double R = Lin(C.R), G = Lin(C.G), B = Lin(C.B);
		const double X = (0.4124564 * R + 0.3575761 * G + 0.1804375 * B) / 0.95047;
		const double Y = (0.2126729 * R + 0.7151522 * G + 0.0721750 * B) / 1.0;
		const double Z = (0.0193339 * R + 0.1191920 * G + 0.9503041 * B) / 1.08883;
		auto F = [](double T) { return T > 216.0 / 24389.0 ? FMath::Pow(T, 1.0 / 3.0) : (24389.0 / 27.0 * T + 16.0) / 116.0; };
		const double Fx = F(X), Fy = F(Y), Fz = F(Z);
		return FVector3d(116.0 * Fy - 16.0, 500.0 * (Fx - Fy), 200.0 * (Fy - Fz));
	}

	/** CIEDE2000 colour difference (Sharma, Wu, Dalal 2005). */
	double DeltaE2000(const FColor& A, const FColor& B)
	{
		const FVector3d L1 = ToLab(A), L2 = ToLab(B);
		const double C1 = FMath::Sqrt(L1.Y * L1.Y + L1.Z * L1.Z), C2 = FMath::Sqrt(L2.Y * L2.Y + L2.Z * L2.Z);
		const double Cm = 0.5 * (C1 + C2);
		const double G = 0.5 * (1.0 - FMath::Sqrt(FMath::Pow(Cm, 7.0) / (FMath::Pow(Cm, 7.0) + FMath::Pow(25.0, 7.0))));
		const double A1 = (1.0 + G) * L1.Y, A2 = (1.0 + G) * L2.Y;
		const double Cp1 = FMath::Sqrt(A1 * A1 + L1.Z * L1.Z), Cp2 = FMath::Sqrt(A2 * A2 + L2.Z * L2.Z);
		auto Hue = [](double Bv, double Av) { if (Av == 0.0 && Bv == 0.0) { return 0.0; } double H = FMath::RadiansToDegrees(FMath::Atan2(Bv, Av)); return H < 0.0 ? H + 360.0 : H; };
		const double H1 = Hue(L1.Z, A1), H2 = Hue(L2.Z, A2);
		const double DL = L2.X - L1.X, DC = Cp2 - Cp1;
		double Dh = 0.0;
		if (Cp1 * Cp2 != 0.0)
		{
			Dh = H2 - H1;
			if (Dh > 180.0) { Dh -= 360.0; }
			else if (Dh < -180.0) { Dh += 360.0; }
		}
		const double DH = 2.0 * FMath::Sqrt(Cp1 * Cp2) * FMath::Sin(FMath::DegreesToRadians(Dh / 2.0));
		const double Lm = 0.5 * (L1.X + L2.X), Cpm = 0.5 * (Cp1 + Cp2);
		double Hm = H1 + H2;
		if (Cp1 * Cp2 != 0.0)
		{
			if (FMath::Abs(H1 - H2) <= 180.0) { Hm = 0.5 * (H1 + H2); }
			else { Hm = (H1 + H2 < 360.0) ? 0.5 * (H1 + H2 + 360.0) : 0.5 * (H1 + H2 - 360.0); }
		}
		const double T = 1.0 - 0.17 * FMath::Cos(FMath::DegreesToRadians(Hm - 30.0)) + 0.24 * FMath::Cos(FMath::DegreesToRadians(2.0 * Hm))
			+ 0.32 * FMath::Cos(FMath::DegreesToRadians(3.0 * Hm + 6.0)) - 0.20 * FMath::Cos(FMath::DegreesToRadians(4.0 * Hm - 63.0));
		const double DTheta = 30.0 * FMath::Exp(-FMath::Square((Hm - 275.0) / 25.0));
		const double Rc = 2.0 * FMath::Sqrt(FMath::Pow(Cpm, 7.0) / (FMath::Pow(Cpm, 7.0) + FMath::Pow(25.0, 7.0)));
		const double Sl = 1.0 + (0.015 * FMath::Square(Lm - 50.0)) / FMath::Sqrt(20.0 + FMath::Square(Lm - 50.0));
		const double Sc = 1.0 + 0.045 * Cpm, Sh = 1.0 + 0.015 * Cpm * T;
		const double Rt = -FMath::Sin(FMath::DegreesToRadians(2.0 * DTheta)) * Rc;
		return FMath::Sqrt(FMath::Square(DL / Sl) + FMath::Square(DC / Sc) + FMath::Square(DH / Sh) + Rt * (DC / Sc) * (DH / Sh));
	}
}

using namespace VerseScreensCellsTest;

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

// A16.3: the 256-colour and RGB test screen against the web painter's reference: mean CIEDE2000 <= 2.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseScreensColourReference, "Verse.Screens.Colour.ReferenceScreen", VERSE_SCREENS_TEST_FLAGS)
bool FVerseScreensColourReference::RunTest(const FString&)
{
	FString Text;
	const FString Path = FPaths::Combine(FPaths::ProjectContentDir(), TEXT("Verse/Test/WP16/colour_reference.json"));
	TSharedPtr<FJsonObject> Root;
	if (!TestTrue(TEXT("colour_reference.json loads"), FFileHelper::LoadFileToString(Text, *Path)
		&& FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root) && Root.IsValid()))
	{
		return false;
	}
	FVerseTerminalPalette Palette;
	Palette.Build(UVerseTerminalTheme::Default());
	double Sum = 0.0;
	double Worst = 0.0;
	int32 N = 0;
	for (const TSharedPtr<FJsonValue>& V : Root->GetArrayField(TEXT("cells")))
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
		const double DFg = DeltaE2000(DrawnFg, ParseHex(Cell.GetStringField(TEXT("drawn_fg"))));
		const double DBg = DeltaE2000(bHasBg ? DrawnBg : Palette.Ground, ParseHex(Cell.GetStringField(TEXT("drawn_bg"))));
		Sum += DFg + DBg;
		Worst = FMath::Max(Worst, FMath::Max(DFg, DBg));
		N += 2;
	}
	const double Mean = N > 0 ? Sum / N : 999.0;
	AddInfo(FString::Printf(TEXT("colour reference: %d samples, mean dE2000 %.4f, worst %.4f"), N, Mean, Worst));
	TestTrue(TEXT("samples"), N >= 1000);
	TestTrue(TEXT("mean CIEDE2000 at most 2"), Mean <= 2.0);
	TestTrue(TEXT("CIEDE2000 of identical colours is 0"), DeltaE2000(FColor(10, 200, 30), FColor(10, 200, 30)) < 1e-9);
	TestTrue(TEXT("CIEDE2000 separates black from white"), DeltaE2000(FColor::Black, FColor::White) > 99.0);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Render/VerseTerminalPainter.h"

#include "CanvasItem.h"
#include "Cells/VerseTerminalGrid.h"
#include "Engine/Canvas.h"
#include "Engine/Font.h"

FVerseTerminalLayout FVerseTerminalLayout::Fit(int32 Width, int32 Height, int32 Cols, int32 Rows, float CellAspect)
{
	FVerseTerminalLayout L;
	L.Width = FMath::Max(1, Width);
	L.Height = FMath::Max(1, Height);
	const int32 SafeCols = FMath::Max(1, Cols);
	L.CellW = float(L.Width) / float(SafeCols);
	L.CellH = FMath::Max(1.f, L.CellW * CellAspect);
	const int32 Fits = FMath::Max(1, FMath::FloorToInt(float(L.Height) / L.CellH));
	L.VisibleRows = FMath::Clamp(Fits, 0, FMath::Max(0, Rows));
	L.FirstRow = FMath::Max(0, Rows - L.VisibleRows);
	// Stretch the rows that fit over the whole height, so the tile is filled top to bottom.
	if (L.VisibleRows > 0)
	{
		L.CellH = float(L.Height) / float(L.VisibleRows);
	}
	return L;
}

namespace VerseTerminalPainter
{
	namespace
	{
		bool IsBlankText(FStringView Text)
		{
			for (const TCHAR C : Text)
			{
				if (C != TEXT(' '))
				{
					return false;
				}
			}
			return true;
		}

		void AddText(FVerseTerminalDrawList& Out, const FVerseTerminalLayout& L, float Y, int32 Row, int32 Col, int32 Cells,
			FStringView Text, FColor Colour, uint16 Attrs)
		{
			if (Text.IsEmpty() || IsBlankText(Text))
			{
				return;
			}
			FVerseTerminalText& T = Out.Texts.AddDefaulted_GetRef();
			T.Pos = FVector2f(float(Col) * L.CellW, Y);
			T.Cells = Cells;
			T.Col = Col;
			T.Row = Row;
			T.Colour = Colour;
			T.bBold = (Attrs & VerseCells::Bold) != 0;
			T.bItalic = (Attrs & VerseCells::Italic) != 0;
			T.Text = Text;
		}

		struct FFontMetrics
		{
			float Advance = 0.f;
			float Height = 0.f;
		};

		FFontMetrics MeasureFont(UCanvas* Canvas, UFont* Font)
		{
			static TMap<TWeakObjectPtr<UFont>, FFontMetrics> Cache;
			if (const FFontMetrics* Found = Cache.Find(Font))
			{
				return *Found;
			}
			float W = 0.f;
			float H = 0.f;
			Canvas->TextSize(Font, TEXT("MMMMMMMMMM"), W, H);
			FFontMetrics M;
			M.Advance = W > 0.f ? W / 10.f : 8.f;
			M.Height = H > 0.f ? H : 16.f;
			Cache.Add(Font, M);
			return M;
		}
	}

	void Build(const FVerseTerminalGrid& Grid, const FVerseTerminalPalette& Palette, const FVerseTerminalLayout& L,
		bool bAllRows, bool bCursorOn, FVerseTerminalDrawList& Out)
	{
		Out.Reset();
		const TBitArray<>& Dirty = Grid.DirtyRows();
		const float LineH = FMath::Max(1.f, L.CellH * 0.07f);
		for (int32 V = 0; V < L.VisibleRows; ++V)
		{
			const int32 Row = L.FirstRow + V;
			if (Row >= Grid.Rows() || (!bAllRows && !(Dirty.IsValidIndex(Row) && Dirty[Row])))
			{
				continue;
			}
			++Out.RowsDrawn;
			const float Y = float(V) * L.CellH;
			Out.Rects.Add({FVector2f(0.f, Y), FVector2f(float(L.Width), L.CellH), Palette.Ground});
			for (const FVerseCellRun& Run : Grid.RowRuns(Row))
			{
				FColor Fg;
				FColor Bg;
				bool bHasBg = false;
				Palette.Resolve(Run.Fg, Run.Bg, Run.Attrs, Fg, Bg, bHasBg);
				const float X = float(Run.Col) * L.CellW;
				const float W = float(Run.Span()) * L.CellW;
				if (bHasBg)
				{
					Out.Rects.Add({FVector2f(X, Y), FVector2f(W, L.CellH), Bg});
				}
				if (Run.Attrs & VerseCells::Invisible)
				{
					continue;
				}
				const bool bWide = (Run.Attrs & VerseCells::Wide) != 0;
				const bool bSimple = !bWide && Run.Text.Len() == int32(Run.Cells);
				if (bSimple)
				{
					AddText(Out, L, Y, Row, Run.Col, Run.Cells, FStringView(Run.Text), Fg, Run.Attrs);
				}
				else
				{
					const int32 Width = bWide ? 2 : 1;
					for (int32 I = 0; I < Run.ClusterEnds.Num(); ++I)
					{
						AddText(Out, L, Y, Row, Run.Col + I * Width, Width, Run.Cluster(I), Fg, Run.Attrs);
					}
				}
				if (Run.Attrs & VerseCells::Underline)
				{
					Out.Rects.Add({FVector2f(X, Y + L.CellH - 2.f * LineH), FVector2f(W, LineH), Fg});
				}
				if (Run.Attrs & VerseCells::Strikethrough)
				{
					Out.Rects.Add({FVector2f(X, Y + 0.5f * L.CellH), FVector2f(W, LineH), Fg});
				}
			}
			if (bCursorOn && Row == Grid.CursorRow() && Grid.CursorCol() >= 0)
			{
				const int32 Col = Grid.CursorCol();
				Out.Rects.Add({FVector2f(float(Col) * L.CellW, Y), FVector2f(L.CellW, L.CellH), Palette.CursorColour});
				FVerseCellView Cell;
				if (Grid.CellAt(Row, Col, Cell) && !Cell.bBlank && !Cell.bContinuation)
				{
					AddText(Out, L, Y, Row, Col, (Cell.Attrs & VerseCells::Wide) ? 2 : 1, Cell.Grapheme, Palette.Ground, Cell.Attrs);
				}
			}
		}
	}

	void BuildPage(const FVerseTerminalPalette& Palette, int32 Width, int32 Height, FStringView Line, FColor LineColour,
		FVerseTerminalDrawList& Out)
	{
		Out.Reset();
		Out.RowsDrawn = 1;
		Out.Rects.Add({FVector2f(0.f, 0.f), FVector2f(float(Width), float(Height)), Palette.Ground});
		FVerseTerminalText& T = Out.Texts.AddDefaulted_GetRef();
		const float CellH = FMath::Max(8.f, float(Height) / 8.f);
		const float CellW = CellH * 0.5f;
		T.Cells = Line.Len();
		T.Pos = FVector2f(FMath::Max(0.f, 0.5f * (float(Width) - CellW * float(T.Cells))), 0.5f * (float(Height) - CellH));
		T.Colour = LineColour;
		T.Text = Line;
	}

	void Submit(UCanvas* Canvas, UFont* Font, const FVerseTerminalLayout& L, const FVerseTerminalDrawList& List)
	{
		if (!Canvas || !Font)
		{
			return;
		}
		for (const FVerseTerminalRect& R : List.Rects)
		{
			FCanvasTileItem Tile(FVector2D(R.Pos), GWhiteTexture, FVector2D(R.Size), FLinearColor(R.Colour));
			Tile.BlendMode = SE_BLEND_Opaque;
			Canvas->DrawItem(Tile);
		}
		const FFontMetrics M = MeasureFont(Canvas, Font);
		const float CellH = L.CellH > 0.f ? L.CellH : FMath::Max(8.f, float(L.Height) / 8.f);
		const float CellW = L.CellW > 0.f ? L.CellW : CellH * 0.5f;
		const FVector2D Scale(CellW / M.Advance, CellH / M.Height);
		const float BoldShift = FMath::Max(1.f, CellW * 0.06f);
		for (const FVerseTerminalText& T : List.Texts)
		{
			FCanvasTextItem Item(FVector2D(T.Pos), FText::AsCultureInvariant(FString(T.Text)), Font, FLinearColor(T.Colour));
			Item.Scale = Scale;
			Item.BlendMode = SE_BLEND_Translucent;
			Canvas->DrawItem(Item);
			if (T.bBold)
			{
				Item.Position.X += BoldShift;
				Canvas->DrawItem(Item);
			}
		}
	}
}

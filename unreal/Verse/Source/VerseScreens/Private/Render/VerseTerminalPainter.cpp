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

		// Box drawing and blocks as geometry, a port of terminalCanvas.ts drawGlyph: frames join
		// without gaps and blocks are solid at any font, the way the IDE's web painter draws them.

		/** Arms of a box-drawing glyph: left, right, up, down; 1 light, 2 heavy, 3 double. */
		struct FBoxGlyph
		{
			TCHAR Ch;
			uint8 L, R, U, D;
		};
		constexpr FBoxGlyph BoxGlyphs[] = {
			{0x2500, 1, 1, 0, 0}, {0x2501, 2, 2, 0, 0}, {0x2502, 0, 0, 1, 1}, {0x2503, 0, 0, 2, 2},
			{0x250C, 0, 1, 0, 1}, {0x2510, 1, 0, 0, 1}, {0x2514, 0, 1, 1, 0}, {0x2518, 1, 0, 1, 0},
			// Rounded corners: the web strokes an arc; here the two arms meet square.
			{0x256D, 0, 1, 0, 1}, {0x256E, 1, 0, 0, 1}, {0x2570, 0, 1, 1, 0}, {0x256F, 1, 0, 1, 0},
			{0x250F, 0, 2, 0, 2}, {0x2513, 2, 0, 0, 2}, {0x2517, 0, 2, 2, 0}, {0x251B, 2, 0, 2, 0},
			{0x251C, 0, 1, 1, 1}, {0x2524, 1, 0, 1, 1}, {0x252C, 1, 1, 0, 1}, {0x2534, 1, 1, 1, 0}, {0x253C, 1, 1, 1, 1},
			{0x2550, 3, 3, 0, 0}, {0x2551, 0, 0, 3, 3}, {0x2554, 0, 3, 0, 3}, {0x2557, 3, 0, 0, 3}, {0x255A, 0, 3, 3, 0},
			{0x255D, 3, 0, 3, 0},
			{0x2574, 1, 0, 0, 0}, {0x2576, 0, 1, 0, 0}, {0x2575, 0, 0, 1, 0}, {0x2577, 0, 0, 0, 1},
		};

		/** Quadrants lit: top-left, top-right, bottom-left, bottom-right. */
		struct FQuadGlyph
		{
			TCHAR Ch;
			uint8 TL, TR, BL, BR;
		};
		constexpr FQuadGlyph QuadGlyphs[] = {
			{0x2598, 1, 0, 0, 0}, {0x259D, 0, 1, 0, 0}, {0x2596, 0, 0, 1, 0}, {0x2597, 0, 0, 0, 1},
			{0x2580, 1, 1, 0, 0}, {0x2584, 0, 0, 1, 1}, {0x258C, 1, 0, 1, 0}, {0x2590, 0, 1, 0, 1},
			{0x259A, 1, 0, 0, 1}, {0x259E, 0, 1, 1, 0}, {0x2599, 1, 0, 1, 1}, {0x259B, 1, 1, 1, 0},
			{0x259C, 1, 1, 0, 1}, {0x259F, 0, 1, 1, 1}, {0x2588, 1, 1, 1, 1},
		};

		float ShadeOf(TCHAR C)
		{
			return C == 0x2591 ? 0.25f : C == 0x2592 ? 0.5f : C == 0x2593 ? 0.75f : 0.f;
		}

		bool IsGeometryGlyph(TCHAR C)
		{
			if (C < 0x2500 || C > 0x259F)
			{
				return false;
			}
			for (const FBoxGlyph& B : BoxGlyphs) { if (B.Ch == C) { return true; } }
			for (const FQuadGlyph& Q : QuadGlyphs) { if (Q.Ch == C) { return true; } }
			return ShadeOf(C) > 0.f;
		}

		bool HasGeometryGlyph(const FString& Text)
		{
			for (const TCHAR C : Text)
			{
				if (IsGeometryGlyph(C))
				{
					return true;
				}
			}
			return false;
		}

		/** Draws C as rects in a W x H cell at X, Y; false when C is not a box or block glyph. */
		bool AddGlyphRects(FVerseTerminalDrawList& Out, TCHAR C, float X, float Y, float W, float H, FColor Fg, FColor Under)
		{
			auto Rect = [&Out](float RX, float RY, float RW, float RH, FColor Colour)
			{
				Out.Rects.Add({FVector2f(RX, RY), FVector2f(RW, RH), Colour});
			};
			for (const FQuadGlyph& Q : QuadGlyphs)
			{
				if (Q.Ch == C)
				{
					const float HW = W * 0.5f, HH = H * 0.5f;
					if (Q.TL && Q.TR && Q.BL && Q.BR) { Rect(X, Y, W, H, Fg); return true; }
					if (Q.TL) { Rect(X, Y, HW, HH, Fg); }
					if (Q.TR) { Rect(X + HW, Y, W - HW, HH, Fg); }
					if (Q.BL) { Rect(X, Y + HH, HW, H - HH, Fg); }
					if (Q.BR) { Rect(X + HW, Y + HH, W - HW, H - HH, Fg); }
					return true;
				}
			}
			if (const float Shade = ShadeOf(C); Shade > 0.f)
			{
				// The web fills at alpha Shade over the cell; the rect here is opaque, so mix it.
				auto Mix = [Shade](uint8 A, uint8 B) { return uint8(FMath::RoundToInt(float(A) * (1.f - Shade) + float(B) * Shade)); };
				Rect(X, Y, W, H, FColor(Mix(Under.R, Fg.R), Mix(Under.G, Fg.G), Mix(Under.B, Fg.B)));
				return true;
			}
			const FBoxGlyph* Box = nullptr;
			for (const FBoxGlyph& B : BoxGlyphs) { if (B.Ch == C) { Box = &B; break; } }
			if (!Box)
			{
				return false;
			}
			const float Light = FMath::Max(1.f, float(FMath::RoundToInt(W / 8.f)));
			const float CX = X + W * 0.5f, CY = Y + H * 0.5f;
			auto Thick = [Light](uint8 K) { return K == 2 ? Light * 2.f : Light; };
			auto HLine = [&](float X0, float X1, uint8 K)
			{
				if (K == 3) { Rect(X0, CY - Light * 1.5f, X1 - X0, Light, Fg); Rect(X0, CY + Light * 0.5f, X1 - X0, Light, Fg); }
				else { Rect(X0, CY - Thick(K) * 0.5f, X1 - X0, Thick(K), Fg); }
			};
			auto VLine = [&](float Y0, float Y1, uint8 K)
			{
				if (K == 3) { Rect(CX - Light * 1.5f, Y0, Light, Y1 - Y0, Fg); Rect(CX + Light * 0.5f, Y0, Light, Y1 - Y0, Fg); }
				else { Rect(CX - Thick(K) * 0.5f, Y0, Thick(K), Y1 - Y0, Fg); }
			};
			const float Ov = Light; // overlap at the centre so the arms meet
			if (Box->L) { HLine(X, CX + (Box->R ? 0.f : Ov), Box->L); }
			if (Box->R) { HLine(CX - (Box->L ? 0.f : Ov), X + W, Box->R); }
			if (Box->U) { VLine(Y, CY + (Box->D ? 0.f : Ov), Box->U); }
			if (Box->D) { VLine(CY - (Box->U ? 0.f : Ov), Y + H, Box->D); }
			return true;
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
				const bool bGeometry = HasGeometryGlyph(Run.Text);
				const bool bSimple = !bWide && !bGeometry && Run.Text.Len() == int32(Run.Cells);
				if (bSimple)
				{
					AddText(Out, L, Y, Row, Run.Col, Run.Cells, FStringView(Run.Text), Fg, Run.Attrs);
				}
				else
				{
					const int32 Width = bWide ? 2 : 1;
					const FColor Under = bHasBg ? Bg : Palette.Ground;
					for (int32 I = 0; I < Run.ClusterEnds.Num(); ++I)
					{
						const FStringView Cluster = Run.Cluster(I);
						const int32 Col = Run.Col + I * Width;
						if (bGeometry && Cluster.Len() == 1
							&& AddGlyphRects(Out, Cluster[0], float(Col) * L.CellW, Y, float(Width) * L.CellW, L.CellH, Fg, Under))
						{
							continue;
						}
						AddText(Out, L, Y, Row, Col, Width, Cluster, Fg, Run.Attrs);
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
			// The size-and-colour form draws the engine white texture (no RenderCore link needed).
			FCanvasTileItem Tile(FVector2D(R.Pos), FVector2D(R.Size), FLinearColor(R.Colour));
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

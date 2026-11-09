#pragma once

#include "CoreMinimal.h"
#include "Render/VerseTerminalTheme.h"

class FVerseTerminalGrid;
class UCanvas;
class UFont;

/** Where a pane's cells land on a monitor's render target (WP16.2). */
struct VERSESCREENS_API FVerseTerminalLayout
{
	int32 Width = 0;
	int32 Height = 0;
	float CellW = 0.f;
	float CellH = 0.f;
	/** First pane row shown and how many: the bottom block that fits (parity E-04). */
	int32 FirstRow = 0;
	int32 VisibleRows = 0;

	/**
	 * Width fills the target: CellW = Width / Cols; the cell keeps the reference font's aspect
	 * (CellAspect = height / width), so the rows that fit follow from the height.
	 */
	static FVerseTerminalLayout Fit(int32 Width, int32 Height, int32 Cols, int32 Rows, float CellAspect = 2.f);
};

/** A solid rectangle: a cleared row, a run's background, the cursor, an underline. */
struct FVerseTerminalRect
{
	FVector2f Pos;
	FVector2f Size;
	FColor Colour;
};

/** Glyphs drawn as one string at one place: a run of narrow cells, or one cluster. */
struct FVerseTerminalText
{
	FVector2f Pos;
	/** Columns the text covers (it is stretched to exactly that width). */
	int32 Cells = 1;
	int32 Col = 0;
	int32 Row = 0;
	FColor Colour;
	bool bBold = false;
	bool bItalic = false;
	/** Points into the grid; valid until the grid applies its next frame. */
	FStringView Text;
};

/** Everything one repaint draws, in order: rects, then texts. Built without a GPU, so testable. */
struct VERSESCREENS_API FVerseTerminalDrawList
{
	TArray<FVerseTerminalRect> Rects;
	TArray<FVerseTerminalText> Texts;
	int32 RowsDrawn = 0;

	void Reset()
	{
		Rects.Reset();
		Texts.Reset();
		RowsDrawn = 0;
	}
	bool IsEmpty() const { return RowsDrawn == 0; }
};

/**
 * Turns a grid into draw lists (WP16.2). Only dirty visible rows are drawn; the render target
 * keeps everything else (no clear between repaints). The glyph atlas is the engine font cache of
 * the terminal font: each text is shaped and cached once per font size, then drawn from that atlas.
 */
namespace VerseTerminalPainter
{
	/** Draw list for the grid's dirty rows (all visible rows when bAllRows). */
	VERSESCREENS_API void Build(const FVerseTerminalGrid& Grid, const FVerseTerminalPalette& Palette,
		const FVerseTerminalLayout& Layout, bool bAllRows, bool bCursorOn, FVerseTerminalDrawList& Out);

	/** A full-target page with one centred line (standby, vacant, fault: parity E-07). */
	VERSESCREENS_API void BuildPage(const FVerseTerminalPalette& Palette, int32 Width, int32 Height,
		FStringView Line, FColor LineColour, FVerseTerminalDrawList& Out);

	/** Submits a draw list on a canvas (render target update). Needs a font; no-op without a canvas. */
	VERSESCREENS_API void Submit(UCanvas* Canvas, UFont* Font, const FVerseTerminalLayout& Layout, const FVerseTerminalDrawList& List);
}

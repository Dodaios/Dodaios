#include "Cells/VerseTerminalGrid.h"

void FVerseTerminalGrid::Reset()
{
	NumCols = 0;
	NumRows = 0;
	CurRow = -1;
	CurCol = -1;
	Seq = 0;
	bHasSnapshot = false;
	bAnyDirty = false;
	Lines.Reset();
	Dirty.Reset();
}

FVerseTerminalGrid::EApply FVerseTerminalGrid::Apply(FVerseCellFrame&& Frame)
{
	if (Frame.Kind == EVerseCellsKind::Snapshot)
	{
		NumCols = Frame.Cols;
		NumRows = Frame.Rows;
		Lines.Reset();
		Lines.SetNum(NumRows);
		Dirty.Init(true, NumRows);
		bAnyDirty = true;
		bHasSnapshot = true;
	}
	else
	{
		if (!bHasSnapshot || Frame.Base != Seq || Frame.Cols != NumCols || Frame.Rows != NumRows)
		{
			return EApply::NeedsResync;
		}
		// The cursor moved: both its old and its new row need a redraw.
		if (CurRow >= 0 && (CurRow != Frame.CursorRow || CurCol != Frame.CursorCol))
		{
			MarkDirty(CurRow);
		}
	}
	for (FVerseCellRow& Record : Frame.RowsChanged)
	{
		Lines[Record.Row] = MoveTemp(Record.Runs);
		MarkDirty(Record.Row);
	}
	CurRow = Frame.CursorRow;
	CurCol = Frame.CursorCol;
	if (CurRow >= 0 && CurRow < NumRows)
	{
		MarkDirty(CurRow);
	}
	Seq = Frame.Seq;
	return EApply::Applied;
}

void FVerseTerminalGrid::MarkDirty(int32 Row)
{
	if (Row >= 0 && Row < NumRows)
	{
		Dirty[Row] = true;
		bAnyDirty = true;
	}
}

void FVerseTerminalGrid::MarkAllDirty()
{
	if (NumRows > 0)
	{
		Dirty.Init(true, NumRows);
		bAnyDirty = true;
	}
}

void FVerseTerminalGrid::ClearDirty()
{
	if (bAnyDirty)
	{
		Dirty.Init(false, NumRows);
		bAnyDirty = false;
	}
}

bool FVerseTerminalGrid::CellAt(int32 Row, int32 Col, FVerseCellView& Out) const
{
	Out = FVerseCellView();
	if (Row < 0 || Row >= NumRows || Col < 0 || Col >= NumCols)
	{
		return false;
	}
	for (const FVerseCellRun& Run : Lines[Row])
	{
		if (Col < Run.Col)
		{
			break;
		}
		if (Col >= Run.Col + Run.Span())
		{
			continue;
		}
		const int32 Width = (Run.Attrs & VerseCells::Wide) ? 2 : 1;
		const int32 Index = (Col - Run.Col) / Width;
		Out.Grapheme = Run.Cluster(Index);
		Out.Glyph = Run.Glyphs[Index];
		Out.Fg = Run.Fg;
		Out.Bg = Run.Bg;
		Out.Attrs = Run.Attrs;
		Out.bContinuation = Width == 2 && ((Col - Run.Col) % 2) == 1;
		Out.bBlank = false;
		return true;
	}
	return true;
}

FString FVerseTerminalGrid::RowText(int32 Row) const
{
	FString Text;
	if (Row < 0 || Row >= NumRows)
	{
		return Text;
	}
	int32 Col = 0;
	for (const FVerseCellRun& Run : Lines[Row])
	{
		while (Col < Run.Col)
		{
			Text.AppendChar(TEXT(' '));
			++Col;
		}
		Text.Append(Run.Text);
		Col = Run.Col + Run.Span();
	}
	return Text;
}

void FVerseTerminalGrid::VisibleRange(int32 VisibleRows, int32& OutFirst, int32& OutCount) const
{
	OutCount = FMath::Clamp(VisibleRows, 0, NumRows);
	OutFirst = NumRows - OutCount;
}

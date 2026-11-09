#pragma once

#include "Cells/VerseCells.h"
#include "CoreMinimal.h"

/** One cell as a reader sees it (the second column of a wide glyph reads as its continuation). */
struct VERSESCREENS_API FVerseCellView
{
	FStringView Grapheme;
	uint64 Glyph = 0;
	uint32 Fg = 0;
	uint32 Bg = 0;
	uint16 Attrs = 0;
	bool bContinuation = false;
	bool bBlank = true;
};

/**
 * The screen of one watched pane: rows of runs, cursor, dirty rows (WP16.1). Fed with decoded
 * frames; a delta must apply on top of the last frame it saw (base == last seq), otherwise the
 * caller asks for a resync (contracts/bridge-protocol.md 2, "Ordering").
 */
class VERSESCREENS_API FVerseTerminalGrid
{
public:
	enum class EApply : uint8
	{
		Applied,
		/** A delta before any snapshot, with a base that is not the last seq, or with a new geometry. */
		NeedsResync,
	};

	EApply Apply(FVerseCellFrame&& Frame);
	void Reset();

	int32 Cols() const { return NumCols; }
	int32 Rows() const { return NumRows; }
	bool HasSnapshot() const { return bHasSnapshot; }
	uint32 LastSeq() const { return Seq; }
	int32 CursorRow() const { return CurRow; }
	int32 CursorCol() const { return CurCol; }

	const TArray<FVerseCellRun>& RowRuns(int32 Row) const { return Lines[Row]; }
	bool CellAt(int32 Row, int32 Col, FVerseCellView& Out) const;
	/** The row's text with blank cells as spaces, trailing blanks dropped (tests, logs). */
	FString RowText(int32 Row) const;

	/** Rows changed since the last ClearDirty(); all of them after a snapshot or a resize. */
	const TBitArray<>& DirtyRows() const { return Dirty; }
	bool IsDirty() const { return bAnyDirty; }
	void MarkAllDirty();
	void ClearDirty();

	/** The bottom block of rows a monitor of VisibleRows rows shows (parity E-04): [First, First + Count). */
	void VisibleRange(int32 VisibleRows, int32& OutFirst, int32& OutCount) const;

private:
	void MarkDirty(int32 Row);

	int32 NumCols = 0;
	int32 NumRows = 0;
	int32 CurRow = -1;
	int32 CurCol = -1;
	uint32 Seq = 0;
	bool bHasSnapshot = false;
	bool bAnyDirty = false;
	TArray<TArray<FVerseCellRun>> Lines;
	TBitArray<> Dirty;
};

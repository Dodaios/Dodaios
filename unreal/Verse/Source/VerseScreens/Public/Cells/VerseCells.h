#pragma once

#include "Containers/ArrayView.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// Terminal screen cells of verse.bridge/1 (contracts/bridge-protocol.md 5.4): the cell model,
// the cells.bin/1 binary decoder and encoder, and the cells.json/1 reader. The Python reference
// codec is scripts/unreal/bridge_cells.py; both read the golden vectors in
// unreal/Verse/Tests/Data/bridge/cells/vectors.json (Verse.Screens.Cells.*).

namespace VerseCells
{
	/** Colour modes, the high byte of a u32 colour. */
	constexpr uint32 ModeDefault = 0;
	constexpr uint32 ModePalette = 1;
	constexpr uint32 ModeRgb = 2;

	/** Attribute bits (u16), in contract order. */
	enum EAttr : uint16
	{
		Bold = 1 << 0,
		Dim = 1 << 1,
		Italic = 1 << 2,
		Underline = 1 << 3,
		Inverse = 1 << 4,
		Strikethrough = 1 << 5,
		Invisible = 1 << 6,
		Blink = 1 << 7,
		Wide = 1 << 8,
	};
	constexpr uint16 AttrMask = 0x01FF;
	constexpr int32 AttrCount = 9;

	constexpr int32 MaxCols = 240;
	constexpr int32 MaxRows = 60;
	constexpr int32 HeaderSize = 24;

	/** Attribute names in bit order ("bold", ... "wide"). */
	VERSESCREENS_API const TCHAR* AttrName(int32 Bit);
}

/** One run: cells with the same fg, bg and attrs on one row. */
struct VERSESCREENS_API FVerseCellRun
{
	uint16 Col = 0;
	/** Grapheme clusters held (a wide cluster counts one and covers two columns). */
	uint16 Cells = 0;
	uint32 Fg = 0;
	uint32 Bg = 0;
	uint16 Attrs = 0;
	FString Text;
	/** End offset (in TCHARs of Text) of each grapheme cluster; Num() == Cells. */
	TArray<uint16, TInlineAllocator<32>> ClusterEnds;
	/** Glyph key per cluster: the code point for a one-code-point cluster, else a hash with bit 63 set. */
	TArray<uint64, TInlineAllocator<32>> Glyphs;

	int32 Span() const { return int32(Cells) * ((Attrs & VerseCells::Wide) ? 2 : 1); }
	FStringView Cluster(int32 Index) const;

	bool operator==(const FVerseCellRun& Other) const
	{
		return Col == Other.Col && Cells == Other.Cells && Fg == Other.Fg && Bg == Other.Bg && Attrs == Other.Attrs
			&& Text.Equals(Other.Text, ESearchCase::CaseSensitive);
	}
};

/** One row record: replaces that row completely (no runs = a blank row). */
struct VERSESCREENS_API FVerseCellRow
{
	uint16 Row = 0;
	TArray<FVerseCellRun> Runs;

	bool operator==(const FVerseCellRow& Other) const { return Row == Other.Row && Runs == Other.Runs; }
};

enum class EVerseCellsKind : uint8
{
	Snapshot = 1,
	Delta = 2
};

/** A decoded screens frame, from either encoding. */
struct VERSESCREENS_API FVerseCellFrame
{
	EVerseCellsKind Kind = EVerseCellsKind::Snapshot;
	uint16 Ref = 0;
	uint32 Seq = 0;
	/** Seq the delta applies on top of; 0 on a snapshot. */
	uint32 Base = 0;
	uint16 Cols = 0;
	uint16 Rows = 0;
	int16 CursorRow = -1;
	int16 CursorCol = -1;
	TArray<FVerseCellRow> RowsChanged;

	// cells.json/1 and screens.meta extras (not in the binary frame).
	FString PaneId;
	/** "styled" or "plain". */
	FString Style;
	bool bCut = false;
	double At = 0.0;

	bool HasCursor() const { return CursorRow >= 0 && CursorCol >= 0; }

	/** Equality of everything the binary frame carries. */
	bool SameCells(const FVerseCellFrame& Other) const
	{
		return Kind == Other.Kind && Ref == Other.Ref && Seq == Other.Seq && Base == Other.Base && Cols == Other.Cols
			&& Rows == Other.Rows && CursorRow == Other.CursorRow && CursorCol == Other.CursorCol
			&& RowsChanged == Other.RowsChanged;
	}
};

namespace VerseCells
{
	/** Decodes one cells.bin/1 frame. False, with a reason, on anything malformed (nothing partial). */
	VERSESCREENS_API bool DecodeBinary(TConstArrayView<uint8> Bytes, FVerseCellFrame& Out, FString& OutError);

	/**
	 * Reads the data object of a cells.json/1 "screens.frame" (pane_id, kind, cols, rows, cursor,
	 * style, rows_changed, plus ref/cut/at on a snapshot). Seq and Base come from the envelope.
	 */
	VERSESCREENS_API bool DecodeJson(const FJsonObject& Data, uint32 Seq, uint32 Base, FVerseCellFrame& Out, FString& OutError);

	/** Encodes a frame as cells.bin/1 (the inverse of DecodeBinary); validates first. */
	VERSESCREENS_API bool EncodeBinary(const FVerseCellFrame& Frame, TArray<uint8>& Out, FString& OutError);

	/** JSON colour (null, {"i": n}, "#rrggbb") to its u32 form. */
	VERSESCREENS_API bool ColourFromJson(const TSharedPtr<FJsonValue>& Value, uint32& Out);

	/** Splits a run's text into grapheme clusters and glyph keys (same rule set as bridge_cells.py). */
	VERSESCREENS_API void BuildClusters(FVerseCellRun& Run);

	/** Grid, row and run structure checks shared by both decoders. */
	VERSESCREENS_API bool CheckRows(int32 Cols, int32 Rows, TConstArrayView<FVerseCellRow> RowsChanged, FString& OutError);

	/** Does this code point extend the previous grapheme cluster? */
	VERSESCREENS_API bool ExtendsCluster(uint32 CodePoint);
}

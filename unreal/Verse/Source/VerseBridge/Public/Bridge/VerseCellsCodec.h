#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/**
 * Terminal screen cells: cells.bin/1 and cells.json/1 (bridge-protocol.md 5.4).
 *
 * Little endian: "VC", version 1, kind (1 snapshot, 2 delta), u16 ref, u32 seq, u32 base,
 * u16 cols, u16 rows, i16 cursor row, i16 cursor col, u16 row count, then row records
 * (u16 row, u16 run count, runs: u16 col, u16 cells, u32 fg, u32 bg, u16 attrs, u16 bytes, UTF-8).
 * Colour u32: high byte mode (0 default, 1 palette index, 2 RGB). Attribute bits: bold, dim,
 * italic, underline, inverse, strikethrough, invisible, blink, wide.
 */
namespace VerseCells
{
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
		AllAttrs = (1 << 9) - 1,
	};

	static constexpr uint32 DefaultColour = 0;
	static constexpr int32 MaxCols = 240;
	static constexpr int32 MaxRows = 60;
	static constexpr int32 HeaderSize = 24;

	inline uint32 Mode(uint32 Colour) { return Colour >> 24; }

	/** Grapheme clusters in UTF-8 bytes with the contract's simplified rules (combining marks,
	 *  ZWJ sequences, variation selectors, skin-tone modifiers and tag characters extend). */
	VERSEBRIDGE_API int32 CountGraphemes(const uint8* Utf8, int32 Bytes, bool* bValidUtf8 = nullptr);
}

struct FVerseCellRun
{
	uint16 Col = 0;
	uint16 Cells = 0;
	uint32 Fg = VerseCells::DefaultColour;
	uint32 Bg = VerseCells::DefaultColour;
	uint16 Attrs = 0;
	/** The run's UTF-8 bytes as sent, and as text. */
	TArray<uint8> Utf8;
	FString Text;

	/** Columns the run covers (a wide glyph covers two). */
	int32 Span() const { return Cells * ((Attrs & VerseCells::Wide) ? 2 : 1); }
};

struct FVerseCellRow
{
	uint16 Row = 0;
	TArray<FVerseCellRun> Runs;
};

struct VERSEBRIDGE_API FVerseCellsFrame
{
	bool bSnapshot = true;
	uint16 Ref = 0;
	uint32 Seq = 0;
	uint32 Base = 0;
	uint16 Cols = 0;
	uint16 Rows = 0;
	int16 CursorRow = -1;
	int16 CursorCol = -1;
	TArray<FVerseCellRow> RowsChanged;

	/** Decodes a binary frame; false (with a reason) on anything malformed. */
	static bool Decode(const TArray<uint8>& Blob, FVerseCellsFrame& Out, FString* OutError = nullptr);

	/** Encodes this frame as cells.bin/1. */
	TArray<uint8> Encode() const;

	/** Reads the data object of a cells.json/1 screens.frame (ref and seq come from outside). */
	static bool FromJson(const TSharedPtr<FJsonObject>& Data, FVerseCellsFrame& Out, FString* OutError = nullptr);

	/** Rows inside the grid, each once, runs sorted, inside the row, not overlapping. */
	bool CheckRows(FString* OutError = nullptr) const;

	static uint32 ColourFromJson(const TSharedPtr<FJsonValue>& Value, bool& bOk);
	static uint16 AttrsFromJson(const TArray<TSharedPtr<FJsonValue>>* Names, bool& bOk);
};

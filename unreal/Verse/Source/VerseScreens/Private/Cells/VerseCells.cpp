#include "Cells/VerseCells.h"

#include "Hash/CityHash.h"

namespace VerseCells
{
	namespace
	{
		const TCHAR* const AttrNames[AttrCount] = {
			TEXT("bold"), TEXT("dim"), TEXT("italic"), TEXT("underline"), TEXT("inverse"),
			TEXT("strikethrough"), TEXT("invisible"), TEXT("blink"), TEXT("wide"),
		};

		/**
		 * Combining marks (Unicode categories Mn, Me, Mc) of the scripts a terminal shows. A simplified
		 * table, as the reference codec's rule set is a simplified one; it covers every golden vector.
		 */
		const uint32 CombiningRanges[][2] = {
			{0x0300, 0x036F}, {0x0483, 0x0489}, {0x0591, 0x05BD}, {0x05BF, 0x05BF}, {0x05C1, 0x05C2},
			{0x05C4, 0x05C5}, {0x05C7, 0x05C7}, {0x0610, 0x061A}, {0x064B, 0x065F}, {0x0670, 0x0670},
			{0x06D6, 0x06DC}, {0x06DF, 0x06E4}, {0x06E7, 0x06E8}, {0x06EA, 0x06ED}, {0x0711, 0x0711},
			{0x0730, 0x074A}, {0x0900, 0x0903}, {0x093A, 0x093C}, {0x093E, 0x094F}, {0x0951, 0x0957},
			{0x0962, 0x0963}, {0x0981, 0x0983}, {0x09BC, 0x09BC}, {0x09BE, 0x09CD}, {0x0A01, 0x0A03},
			{0x0A3C, 0x0A51}, {0x0E31, 0x0E31}, {0x0E34, 0x0E3A}, {0x0E47, 0x0E4E}, {0x0EB1, 0x0EB1},
			{0x0EB4, 0x0EBC}, {0x0EC8, 0x0ECE}, {0x1AB0, 0x1AFF}, {0x1DC0, 0x1DFF}, {0x20D0, 0x20FF},
			{0x302A, 0x302F}, {0x3099, 0x309A}, {0xA66F, 0xA672}, {0xA674, 0xA67D}, {0xFE20, 0xFE2F},
		};

		uint16 ReadU16(const uint8* P) { return uint16(P[0]) | uint16(uint16(P[1]) << 8); }
		uint32 ReadU32(const uint8* P) { return uint32(P[0]) | (uint32(P[1]) << 8) | (uint32(P[2]) << 16) | (uint32(P[3]) << 24); }
		int16 ReadI16(const uint8* P) { return int16(ReadU16(P)); }

		void PutU16(TArray<uint8>& Out, uint16 V) { Out.Add(uint8(V & 0xFF)); Out.Add(uint8(V >> 8)); }
		void PutU32(TArray<uint8>& Out, uint32 V)
		{
			Out.Add(uint8(V & 0xFF));
			Out.Add(uint8((V >> 8) & 0xFF));
			Out.Add(uint8((V >> 16) & 0xFF));
			Out.Add(uint8(V >> 24));
		}

		/** Strict UTF-8 check: no overlong forms, no surrogates, nothing above U+10FFFF. */
		bool IsValidUtf8(const uint8* P, int32 Len)
		{
			int32 I = 0;
			while (I < Len)
			{
				const uint8 C = P[I];
				int32 Extra = 0;
				uint32 Cp = 0;
				if (C < 0x80) { ++I; continue; }
				if ((C & 0xE0) == 0xC0) { Extra = 1; Cp = C & 0x1F; }
				else if ((C & 0xF0) == 0xE0) { Extra = 2; Cp = C & 0x0F; }
				else if ((C & 0xF8) == 0xF0) { Extra = 3; Cp = C & 0x07; }
				else { return false; }
				for (int32 K = 1; K <= Extra; ++K)
				{
					if (I + K >= Len || (P[I + K] & 0xC0) != 0x80) { return false; }
					Cp = (Cp << 6) | (P[I + K] & 0x3F);
				}
				const uint32 Min = Extra == 1 ? 0x80 : Extra == 2 ? 0x800 : 0x10000;
				if (Cp < Min || Cp > 0x10FFFF || (Cp >= 0xD800 && Cp <= 0xDFFF)) { return false; }
				I += Extra + 1;
			}
			return true;
		}

		/** Next code point of a TCHAR string (UTF-16 surrogate pairs joined when TCHAR is 16 bit). */
		uint32 NextCodePoint(const TCHAR* S, int32 Len, int32& I)
		{
			uint32 Cp = uint32(S[I++]);
			if constexpr (sizeof(TCHAR) == 2)
			{
				if (Cp >= 0xD800 && Cp <= 0xDBFF && I < Len)
				{
					const uint32 Lo = uint32(S[I]);
					if (Lo >= 0xDC00 && Lo <= 0xDFFF)
					{
						++I;
						Cp = 0x10000 + ((Cp - 0xD800) << 10) + (Lo - 0xDC00);
					}
				}
			}
			return Cp;
		}

		bool ColourValid(uint32 Value)
		{
			const uint32 Mode = Value >> 24;
			const uint32 Low = Value & 0xFFFFFF;
			if (Mode == ModeDefault) { return Low == 0; }
			if (Mode == ModePalette) { return Low <= 0xFF; }
			return Mode == ModeRgb;
		}

		bool ParseHexColour(const FString& S, uint32& Out)
		{
			if (S.Len() != 7 || S[0] != TEXT('#')) { return false; }
			uint32 V = 0;
			for (int32 I = 1; I < 7; ++I)
			{
				const TCHAR C = S[I];
				uint32 D;
				if (C >= TEXT('0') && C <= TEXT('9')) { D = C - TEXT('0'); }
				else if (C >= TEXT('a') && C <= TEXT('f')) { D = 10 + C - TEXT('a'); }
				// The contract does not ask for lower case: one "#E3242B" must not cost a resync.
				else if (C >= TEXT('A') && C <= TEXT('F')) { D = 10 + C - TEXT('A'); }
				else { return false; }
				V = (V << 4) | D;
			}
			Out = (ModeRgb << 24) | V;
			return true;
		}

		bool ReadInt(const FJsonObject& O, const TCHAR* Field, int64 Min, int64 Max, int64& Out)
		{
			double D = 0.0;
			if (!O.TryGetNumberField(Field, D) || D != FMath::FloorToDouble(D) || D < double(Min) || D > double(Max))
			{
				return false;
			}
			Out = int64(D);
			return true;
		}
	}

	const TCHAR* AttrName(int32 Bit) { return Bit >= 0 && Bit < AttrCount ? AttrNames[Bit] : TEXT(""); }

	bool ExtendsCluster(uint32 Cp)
	{
		if (Cp == 0x200D || (Cp >= 0xFE00 && Cp <= 0xFE0F) || (Cp >= 0x1F3FB && Cp <= 0x1F3FF) || (Cp >= 0xE0020 && Cp <= 0xE007F))
		{
			return true;
		}
		for (const uint32* Range : CombiningRanges)
		{
			if (Cp >= Range[0] && Cp <= Range[1]) { return true; }
		}
		return false;
	}

	void BuildClusters(FVerseCellRun& Run)
	{
		Run.ClusterEnds.Reset();
		Run.Glyphs.Reset();
		const TCHAR* S = *Run.Text;
		const int32 Len = Run.Text.Len();
		int32 I = 0;
		bool bJoinNext = false;
		int32 ClusterStart = 0;
		int32 CodePoints = 0;
		uint32 FirstCp = 0;
		auto Close = [&](int32 End)
		{
			uint64 Key = FirstCp;
			if (CodePoints > 1)
			{
				Key = (1ull << 63) | (CityHash64(reinterpret_cast<const char*>(S + ClusterStart), uint32((End - ClusterStart) * sizeof(TCHAR))) >> 1);
			}
			Run.ClusterEnds.Add(uint16(End));
			Run.Glyphs.Add(Key);
		};
		while (I < Len)
		{
			const int32 At = I;
			const uint32 Cp = NextCodePoint(S, Len, I);
			if (At > 0 && (bJoinNext || ExtendsCluster(Cp)))
			{
				++CodePoints;
			}
			else
			{
				if (At > 0) { Close(At); }
				ClusterStart = At;
				CodePoints = 1;
				FirstCp = Cp;
			}
			bJoinNext = Cp == 0x200D;
		}
		if (Len > 0) { Close(Len); }
	}

	bool CheckRows(int32 Cols, int32 Rows, TConstArrayView<FVerseCellRow> RowsChanged, FString& OutError)
	{
		if (Cols < 1 || Cols > MaxCols || Rows < 1 || Rows > MaxRows)
		{
			OutError = FString::Printf(TEXT("grid %dx%d outside 1..%d x 1..%d"), Cols, Rows, MaxCols, MaxRows);
			return false;
		}
		TBitArray<> Seen(false, Rows);
		for (const FVerseCellRow& Record : RowsChanged)
		{
			if (Record.Row >= Rows)
			{
				OutError = FString::Printf(TEXT("row %d outside 0..%d"), Record.Row, Rows - 1);
				return false;
			}
			if (Seen[Record.Row])
			{
				OutError = FString::Printf(TEXT("row %d sent twice"), Record.Row);
				return false;
			}
			Seen[Record.Row] = true;
			int32 End = 0;
			for (const FVerseCellRun& Run : Record.Runs)
			{
				if (Run.Text.IsEmpty())
				{
					OutError = FString::Printf(TEXT("row %d: empty run at col %d"), Record.Row, Run.Col);
					return false;
				}
				if (Run.Col < End)
				{
					OutError = FString::Printf(TEXT("row %d: run at col %d overlaps or is out of order"), Record.Row, Run.Col);
					return false;
				}
				End = Run.Col + Run.Span();
				if (End > Cols)
				{
					OutError = FString::Printf(TEXT("row %d: run at col %d ends at %d, past %d cols"), Record.Row, Run.Col, End, Cols);
					return false;
				}
			}
		}
		return true;
	}

	bool DecodeBinary(TConstArrayView<uint8> Bytes, FVerseCellFrame& Out, FString& OutError)
	{
		const int32 Len = Bytes.Num();
		const uint8* P = Bytes.GetData();
		if (Len < HeaderSize)
		{
			OutError = FString::Printf(TEXT("frame of %d bytes is shorter than the %d-byte header"), Len, HeaderSize);
			return false;
		}
		if (P[0] != 'V' || P[1] != 'C') { OutError = TEXT("bad magic"); return false; }
		if (P[2] != 1) { OutError = FString::Printf(TEXT("unsupported version %d"), P[2]); return false; }
		if (P[3] != 1 && P[3] != 2) { OutError = FString::Printf(TEXT("bad kind %d"), P[3]); return false; }

		FVerseCellFrame F;
		F.Kind = EVerseCellsKind(P[3]);
		F.Ref = ReadU16(P + 4);
		F.Seq = ReadU32(P + 6);
		F.Base = ReadU32(P + 10);
		F.Cols = ReadU16(P + 14);
		F.Rows = ReadU16(P + 16);
		F.CursorRow = ReadI16(P + 18);
		F.CursorCol = ReadI16(P + 20);
		const int32 Count = ReadU16(P + 22);
		if (F.Kind == EVerseCellsKind::Snapshot && F.Base != 0) { OutError = TEXT("a snapshot carries base 0"); return false; }
		const bool bHidden = F.CursorRow == -1 && F.CursorCol == -1;
		if (!bHidden && !(F.CursorRow >= 0 && F.CursorRow < F.Rows && F.CursorCol >= 0 && F.CursorCol < F.Cols))
		{
			OutError = FString::Printf(TEXT("cursor %d,%d outside the grid"), F.CursorRow, F.CursorCol);
			return false;
		}

		int32 Offset = HeaderSize;
		F.RowsChanged.Reserve(Count);
		for (int32 R = 0; R < Count; ++R)
		{
			if (Offset + 4 > Len) { OutError = TEXT("truncated row record"); return false; }
			FVerseCellRow& Row = F.RowsChanged.AddDefaulted_GetRef();
			Row.Row = ReadU16(P + Offset);
			const int32 RunCount = ReadU16(P + Offset + 2);
			Offset += 4;
			Row.Runs.Reserve(RunCount);
			for (int32 U = 0; U < RunCount; ++U)
			{
				if (Offset + 16 > Len) { OutError = TEXT("truncated run"); return false; }
				FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
				Run.Col = ReadU16(P + Offset);
				Run.Cells = ReadU16(P + Offset + 2);
				Run.Fg = ReadU32(P + Offset + 4);
				Run.Bg = ReadU32(P + Offset + 8);
				Run.Attrs = ReadU16(P + Offset + 12);
				const int32 TextBytes = ReadU16(P + Offset + 14);
				Offset += 16;
				if (Offset + TextBytes > Len) { OutError = TEXT("run text runs past the end of the frame"); return false; }
				if (!ColourValid(Run.Fg) || !ColourValid(Run.Bg))
				{
					OutError = FString::Printf(TEXT("bad colour %08x / %08x"), Run.Fg, Run.Bg);
					return false;
				}
				if (Run.Attrs & ~AttrMask) { OutError = FString::Printf(TEXT("unknown attribute bits %04x"), Run.Attrs); return false; }
				if (!IsValidUtf8(P + Offset, TextBytes)) { OutError = TEXT("run text is not UTF-8"); return false; }
				const auto Conv = StringCast<TCHAR>(reinterpret_cast<const UTF8CHAR*>(P + Offset), TextBytes);
				Run.Text = FString::ConstructFromPtrSize(Conv.Get(), Conv.Length());
				Offset += TextBytes;
				const uint16 Said = Run.Cells;
				BuildClusters(Run);
				if (Run.ClusterEnds.Num() != Said)
				{
					OutError = FString::Printf(TEXT("run at row %d col %d says %d cells but holds %d"), Row.Row, Run.Col, Said, Run.ClusterEnds.Num());
					return false;
				}
			}
		}
		if (Offset != Len) { OutError = FString::Printf(TEXT("%d trailing bytes"), Len - Offset); return false; }
		if (!CheckRows(F.Cols, F.Rows, F.RowsChanged, OutError)) { return false; }
		Out = MoveTemp(F);
		return true;
	}

	bool ColourFromJson(const TSharedPtr<FJsonValue>& Value, uint32& Out)
	{
		if (!Value.IsValid() || Value->IsNull()) { Out = 0; return true; }
		FString S;
		if (Value->TryGetString(S)) { return ParseHexColour(S, Out); }
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (Value->TryGetObject(Obj) && Obj && (*Obj)->Values.Num() == 1)
		{
			int64 Index = 0;
			if (ReadInt(**Obj, TEXT("i"), 0, 255, Index))
			{
				Out = (ModePalette << 24) | uint32(Index);
				return true;
			}
		}
		return false;
	}

	bool DecodeJson(const FJsonObject& Data, uint32 Seq, uint32 Base, FVerseCellFrame& Out, FString& OutError)
	{
		FVerseCellFrame F;
		FString Kind;
		if (!Data.TryGetStringField(TEXT("kind"), Kind) || (Kind != TEXT("snapshot") && Kind != TEXT("delta")))
		{
			OutError = TEXT("bad kind");
			return false;
		}
		F.Kind = Kind == TEXT("snapshot") ? EVerseCellsKind::Snapshot : EVerseCellsKind::Delta;
		F.Seq = Seq;
		F.Base = F.Kind == EVerseCellsKind::Snapshot ? 0 : Base;
		Data.TryGetStringField(TEXT("pane_id"), F.PaneId);
		Data.TryGetStringField(TEXT("style"), F.Style);
		Data.TryGetBoolField(TEXT("cut"), F.bCut);
		Data.TryGetNumberField(TEXT("at"), F.At);
		int64 V = 0;
		if (Data.HasField(TEXT("ref")))
		{
			if (!ReadInt(Data, TEXT("ref"), 0, 0xFFFF, V)) { OutError = TEXT("bad ref"); return false; }
			F.Ref = uint16(V);
		}
		if (!ReadInt(Data, TEXT("cols"), 1, MaxCols, V)) { OutError = TEXT("bad cols"); return false; }
		F.Cols = uint16(V);
		if (!ReadInt(Data, TEXT("rows"), 1, MaxRows, V)) { OutError = TEXT("bad rows"); return false; }
		F.Rows = uint16(V);
		const TArray<TSharedPtr<FJsonValue>>* Cursor = nullptr;
		if (!Data.TryGetArrayField(TEXT("cursor"), Cursor) || Cursor->Num() != 2) { OutError = TEXT("bad cursor"); return false; }
		F.CursorRow = int16((*Cursor)[0]->AsNumber());
		F.CursorCol = int16((*Cursor)[1]->AsNumber());
		const bool bHidden = F.CursorRow == -1 && F.CursorCol == -1;
		if (!bHidden && !(F.CursorRow >= 0 && F.CursorRow < F.Rows && F.CursorCol >= 0 && F.CursorCol < F.Cols))
		{
			OutError = TEXT("cursor outside the grid");
			return false;
		}
		const TArray<TSharedPtr<FJsonValue>>* RowsChanged = nullptr;
		if (!Data.TryGetArrayField(TEXT("rows_changed"), RowsChanged)) { OutError = TEXT("no rows_changed"); return false; }
		for (const TSharedPtr<FJsonValue>& RowValue : *RowsChanged)
		{
			const TSharedPtr<FJsonObject>* RowObj = nullptr;
			if (!RowValue.IsValid() || !RowValue->TryGetObject(RowObj)) { OutError = TEXT("bad row record"); return false; }
			FVerseCellRow& Row = F.RowsChanged.AddDefaulted_GetRef();
			if (!ReadInt(**RowObj, TEXT("row"), 0, 0xFFFF, V)) { OutError = TEXT("bad row index"); return false; }
			Row.Row = uint16(V);
			const TArray<TSharedPtr<FJsonValue>>* Runs = nullptr;
			if (!(*RowObj)->TryGetArrayField(TEXT("runs"), Runs)) { OutError = TEXT("row without runs"); return false; }
			for (const TSharedPtr<FJsonValue>& RunValue : *Runs)
			{
				const TSharedPtr<FJsonObject>* RunObj = nullptr;
				if (!RunValue.IsValid() || !RunValue->TryGetObject(RunObj)) { OutError = TEXT("bad run"); return false; }
				FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
				if (!ReadInt(**RunObj, TEXT("col"), 0, 0xFFFF, V)) { OutError = TEXT("bad run col"); return false; }
				Run.Col = uint16(V);
				if (!(*RunObj)->TryGetStringField(TEXT("text"), Run.Text)) { OutError = TEXT("run without text"); return false; }
				if (!ColourFromJson((*RunObj)->TryGetField(TEXT("fg")), Run.Fg) || !ColourFromJson((*RunObj)->TryGetField(TEXT("bg")), Run.Bg))
				{
					OutError = TEXT("bad run colour");
					return false;
				}
				const TArray<TSharedPtr<FJsonValue>>* Attrs = nullptr;
				if ((*RunObj)->TryGetArrayField(TEXT("attrs"), Attrs))
				{
					for (const TSharedPtr<FJsonValue>& A : *Attrs)
					{
						const FString Name = A.IsValid() ? A->AsString() : FString();
						int32 Bit = INDEX_NONE;
						for (int32 B = 0; B < AttrCount; ++B)
						{
							if (Name == AttrNames[B]) { Bit = B; break; }
						}
						if (Bit == INDEX_NONE) { OutError = FString::Printf(TEXT("unknown attribute %s"), *Name); return false; }
						Run.Attrs |= uint16(1 << Bit);
					}
				}
				BuildClusters(Run);
				Run.Cells = uint16(Run.ClusterEnds.Num());
			}
		}
		if (!CheckRows(F.Cols, F.Rows, F.RowsChanged, OutError)) { return false; }
		Out = MoveTemp(F);
		return true;
	}

	bool EncodeBinary(const FVerseCellFrame& F, TArray<uint8>& Out, FString& OutError)
	{
		if (!CheckRows(F.Cols, F.Rows, F.RowsChanged, OutError)) { return false; }
		Out.Reset();
		Out.Reserve(HeaderSize + F.RowsChanged.Num() * 64);
		Out.Add('V');
		Out.Add('C');
		Out.Add(1);
		Out.Add(uint8(F.Kind));
		PutU16(Out, F.Ref);
		PutU32(Out, F.Seq);
		PutU32(Out, F.Kind == EVerseCellsKind::Snapshot ? 0u : F.Base);
		PutU16(Out, F.Cols);
		PutU16(Out, F.Rows);
		PutU16(Out, uint16(F.CursorRow));
		PutU16(Out, uint16(F.CursorCol));
		PutU16(Out, uint16(F.RowsChanged.Num()));
		for (const FVerseCellRow& Row : F.RowsChanged)
		{
			PutU16(Out, Row.Row);
			PutU16(Out, uint16(Row.Runs.Num()));
			for (const FVerseCellRun& Run : Row.Runs)
			{
				const auto Utf8 = StringCast<UTF8CHAR>(*Run.Text, Run.Text.Len());
				if (Utf8.Length() > 0xFFFF) { OutError = TEXT("run text over 65535 bytes"); return false; }
				PutU16(Out, Run.Col);
				PutU16(Out, uint16(Run.ClusterEnds.Num()));
				PutU32(Out, Run.Fg);
				PutU32(Out, Run.Bg);
				PutU16(Out, Run.Attrs);
				PutU16(Out, uint16(Utf8.Length()));
				Out.Append(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
			}
		}
		return true;
	}
}

FStringView FVerseCellRun::Cluster(int32 Index) const
{
	const int32 Start = Index > 0 ? ClusterEnds[Index - 1] : 0;
	return FStringView(*Text + Start, ClusterEnds[Index] - Start);
}

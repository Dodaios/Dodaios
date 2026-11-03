#include "Bridge/VerseCellsCodec.h"

#include "Bridge/VerseBridgeCodec.h"

namespace
{
	/** Decodes one UTF-8 code point; returns its byte length, or 0 when malformed. */
	int32 DecodeOne(const uint8* P, int32 Left, uint32& Cp)
	{
		const uint8 B0 = P[0];
		if (B0 < 0x80)
		{
			Cp = B0;
			return 1;
		}
		int32 Len = 0;
		if ((B0 & 0xE0) == 0xC0)
		{
			Len = 2;
			Cp = B0 & 0x1F;
		}
		else if ((B0 & 0xF0) == 0xE0)
		{
			Len = 3;
			Cp = B0 & 0x0F;
		}
		else if ((B0 & 0xF8) == 0xF0)
		{
			Len = 4;
			Cp = B0 & 0x07;
		}
		else
		{
			return 0;
		}
		if (Left < Len)
		{
			return 0;
		}
		for (int32 I = 1; I < Len; ++I)
		{
			if ((P[I] & 0xC0) != 0x80)
			{
				return 0;
			}
			Cp = (Cp << 6) | (P[I] & 0x3F);
		}
		static const uint32 Min[5] = {0, 0, 0x80, 0x800, 0x10000};
		if (Cp < Min[Len] || Cp > 0x10FFFF || (Cp >= 0xD800 && Cp <= 0xDFFF))
		{
			return 0;
		}
		return Len;
	}

	/** Unicode categories Mn, Me, Mc in the blocks terminal text uses, plus the joiners. */
	bool Extends(uint32 Cp)
	{
		return (Cp >= 0x0300 && Cp <= 0x036F) || (Cp >= 0x0483 && Cp <= 0x0489) || (Cp >= 0x0591 && Cp <= 0x05BD)
			|| (Cp >= 0x0610 && Cp <= 0x061A) || (Cp >= 0x064B && Cp <= 0x065F) || (Cp >= 0x0900 && Cp <= 0x0903)
			|| (Cp >= 0x093A && Cp <= 0x094F) || (Cp >= 0x0E31 && Cp <= 0x0E3A && Cp != 0x0E32 && Cp != 0x0E33)
			|| (Cp >= 0x1AB0 && Cp <= 0x1AFF) || (Cp >= 0x1DC0 && Cp <= 0x1DFF) || (Cp >= 0x20D0 && Cp <= 0x20FF)
			|| (Cp >= 0x302A && Cp <= 0x302F) || (Cp >= 0x3099 && Cp <= 0x309A) || (Cp >= 0xFE20 && Cp <= 0xFE2F)
			|| Cp == 0x200D || (Cp >= 0xFE00 && Cp <= 0xFE0F) || (Cp >= 0x1F3FB && Cp <= 0x1F3FF)
			|| (Cp >= 0xE0020 && Cp <= 0xE007F) || (Cp >= 0xE0100 && Cp <= 0xE01EF);
	}

	struct FReader
	{
		const TArray<uint8>& B;
		int32 Off = 0;
		bool bOk = true;

		bool Has(int32 N) const { return Off + N <= B.Num(); }
		uint8 U8() { return bOk && Has(1) ? B[Off++] : (bOk = false, 0); }
		uint16 U16()
		{
			if (!bOk || !Has(2))
			{
				bOk = false;
				return 0;
			}
			const uint16 V = uint16(B[Off]) | (uint16(B[Off + 1]) << 8);
			Off += 2;
			return V;
		}
		uint32 U32()
		{
			const uint32 Lo = U16();
			const uint32 Hi = U16();
			return Lo | (Hi << 16);
		}
	};

	void W16(TArray<uint8>& O, uint16 V)
	{
		O.Add(uint8(V & 0xFF));
		O.Add(uint8(V >> 8));
	}

	void W32(TArray<uint8>& O, uint32 V)
	{
		W16(O, uint16(V & 0xFFFF));
		W16(O, uint16(V >> 16));
	}

	bool ColourValid(uint32 C)
	{
		const uint32 M = C >> 24;
		const uint32 Low = C & 0xFFFFFF;
		return (M == 0 && Low == 0) || (M == 1 && Low <= 0xFF) || M == 2;
	}

	static const TCHAR* AttrNames[] = {TEXT("bold"), TEXT("dim"), TEXT("italic"), TEXT("underline"), TEXT("inverse"),
		TEXT("strikethrough"), TEXT("invisible"), TEXT("blink"), TEXT("wide")};
}

int32 VerseCells::CountGraphemes(const uint8* Utf8, int32 Bytes, bool* bValidUtf8)
{
	int32 Count = 0;
	bool bJoinNext = false;
	int32 I = 0;
	while (I < Bytes)
	{
		uint32 Cp = 0;
		const int32 Len = DecodeOne(Utf8 + I, Bytes - I, Cp);
		if (Len == 0)
		{
			if (bValidUtf8)
			{
				*bValidUtf8 = false;
			}
			return -1;
		}
		I += Len;
		if (Count > 0 && (bJoinNext || Extends(Cp)))
		{
			// Extends the previous cluster.
		}
		else
		{
			++Count;
		}
		bJoinNext = Cp == 0x200D;
	}
	if (bValidUtf8)
	{
		*bValidUtf8 = true;
	}
	return Count;
}

bool FVerseCellsFrame::CheckRows(FString* OutError) const
{
	auto Fail = [OutError](const FString& Why)
	{
		if (OutError)
		{
			*OutError = Why;
		}
		return false;
	};
	if (Cols < 1 || Cols > VerseCells::MaxCols || Rows < 1 || Rows > VerseCells::MaxRows)
	{
		return Fail(FString::Printf(TEXT("grid %dx%d outside the limits"), Cols, Rows));
	}
	TSet<uint16> Seen;
	for (const FVerseCellRow& R : RowsChanged)
	{
		if (R.Row >= Rows)
		{
			return Fail(FString::Printf(TEXT("row %d outside the grid"), R.Row));
		}
		if (Seen.Contains(R.Row))
		{
			return Fail(FString::Printf(TEXT("row %d sent twice"), R.Row));
		}
		Seen.Add(R.Row);
		int32 End = 0;
		for (const FVerseCellRun& Run : R.Runs)
		{
			if (Run.Utf8.Num() == 0 || Run.Cells == 0)
			{
				return Fail(FString::Printf(TEXT("row %d: empty run"), R.Row));
			}
			if (Run.Col < End)
			{
				return Fail(FString::Printf(TEXT("row %d: run at col %d overlaps"), R.Row, Run.Col));
			}
			End = Run.Col + Run.Span();
			if (End > Cols)
			{
				return Fail(FString::Printf(TEXT("row %d: run past the last column"), R.Row));
			}
		}
	}
	return true;
}

bool FVerseCellsFrame::Decode(const TArray<uint8>& Blob, FVerseCellsFrame& Out, FString* OutError)
{
	auto Fail = [OutError](const FString& Why)
	{
		if (OutError)
		{
			*OutError = Why;
		}
		return false;
	};
	if (Blob.Num() < VerseCells::HeaderSize)
	{
		return Fail(TEXT("shorter than the header"));
	}
	FReader R{Blob};
	const uint8 M0 = R.U8();
	const uint8 M1 = R.U8();
	if (M0 != 'V' || M1 != 'C')
	{
		return Fail(TEXT("bad magic"));
	}
	if (R.U8() != 1)
	{
		return Fail(TEXT("unsupported version"));
	}
	const uint8 Kind = R.U8();
	if (Kind != 1 && Kind != 2)
	{
		return Fail(TEXT("bad kind"));
	}
	Out = FVerseCellsFrame();
	Out.bSnapshot = Kind == 1;
	Out.Ref = R.U16();
	Out.Seq = R.U32();
	Out.Base = R.U32();
	Out.Cols = R.U16();
	Out.Rows = R.U16();
	Out.CursorRow = int16(R.U16());
	Out.CursorCol = int16(R.U16());
	const uint16 Count = R.U16();
	if (Out.bSnapshot && Out.Base != 0)
	{
		return Fail(TEXT("a snapshot carries base 0"));
	}
	const bool bHidden = Out.CursorRow == -1 && Out.CursorCol == -1;
	if (!bHidden && (Out.CursorRow < 0 || Out.CursorRow >= Out.Rows || Out.CursorCol < 0 || Out.CursorCol >= Out.Cols))
	{
		return Fail(TEXT("cursor outside the grid"));
	}
	for (int32 I = 0; I < Count; ++I)
	{
		if (!R.Has(4))
		{
			return Fail(TEXT("truncated row record"));
		}
		FVerseCellRow& Row = Out.RowsChanged.AddDefaulted_GetRef();
		Row.Row = R.U16();
		const uint16 RunCount = R.U16();
		for (int32 J = 0; J < RunCount; ++J)
		{
			if (!R.Has(16))
			{
				return Fail(TEXT("truncated run"));
			}
			FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
			Run.Col = R.U16();
			Run.Cells = R.U16();
			Run.Fg = R.U32();
			Run.Bg = R.U32();
			Run.Attrs = R.U16();
			const uint16 Bytes = R.U16();
			if (!R.Has(Bytes))
			{
				return Fail(TEXT("run text runs past the end of the frame"));
			}
			if (!ColourValid(Run.Fg) || !ColourValid(Run.Bg))
			{
				return Fail(TEXT("bad colour"));
			}
			if (Run.Attrs & ~VerseCells::AllAttrs)
			{
				return Fail(TEXT("unknown attribute bits"));
			}
			Run.Utf8.Append(Blob.GetData() + R.Off, Bytes);
			R.Off += Bytes;
			bool bValid = true;
			const int32 Held = VerseCells::CountGraphemes(Run.Utf8.GetData(), Run.Utf8.Num(), &bValid);
			if (!bValid)
			{
				return Fail(TEXT("run text is not UTF-8"));
			}
			if (Held != Run.Cells)
			{
				return Fail(FString::Printf(TEXT("run says %d cells but holds %d"), Run.Cells, Held));
			}
			const FUTF8ToTCHAR Conv(reinterpret_cast<const ANSICHAR*>(Run.Utf8.GetData()), Run.Utf8.Num());
			Run.Text = FString(Conv.Length(), Conv.Get());
		}
	}
	if (!R.bOk)
	{
		return Fail(TEXT("truncated frame"));
	}
	if (R.Off != Blob.Num())
	{
		return Fail(TEXT("trailing bytes"));
	}
	return Out.CheckRows(OutError);
}

TArray<uint8> FVerseCellsFrame::Encode() const
{
	TArray<uint8> O;
	O.Add('V');
	O.Add('C');
	O.Add(1);
	O.Add(bSnapshot ? 1 : 2);
	W16(O, Ref);
	W32(O, Seq);
	W32(O, bSnapshot ? 0 : Base);
	W16(O, Cols);
	W16(O, Rows);
	W16(O, uint16(CursorRow));
	W16(O, uint16(CursorCol));
	W16(O, uint16(RowsChanged.Num()));
	for (const FVerseCellRow& Row : RowsChanged)
	{
		W16(O, Row.Row);
		W16(O, uint16(Row.Runs.Num()));
		for (const FVerseCellRun& Run : Row.Runs)
		{
			W16(O, Run.Col);
			W16(O, uint16(VerseCells::CountGraphemes(Run.Utf8.GetData(), Run.Utf8.Num())));
			W32(O, Run.Fg);
			W32(O, Run.Bg);
			W16(O, Run.Attrs);
			W16(O, uint16(Run.Utf8.Num()));
			O.Append(Run.Utf8);
		}
	}
	return O;
}

uint32 FVerseCellsFrame::ColourFromJson(const TSharedPtr<FJsonValue>& Value, bool& bOk)
{
	if (!Value.IsValid() || Value->Type == EJson::Null)
	{
		return VerseCells::DefaultColour;
	}
	if (Value->Type == EJson::Object)
	{
		const TSharedPtr<FJsonObject> O = Value->AsObject();
		double I = -1;
		if (O->Values.Num() != 1 || !O->TryGetNumberField(TEXT("i"), I) || I < 0 || I > 255)
		{
			bOk = false;
			return 0;
		}
		return (1u << 24) | uint32(I);
	}
	if (Value->Type == EJson::String)
	{
		const FString S = Value->AsString();
		if (S.Len() == 7 && S[0] == '#')
		{
			uint32 V = 0;
			for (int32 K = 1; K < 7; ++K)
			{
				const TCHAR C = S[K];
				const int32 D = (C >= '0' && C <= '9') ? C - '0' : (C >= 'a' && C <= 'f') ? C - 'a' + 10 : -1;
				if (D < 0)
				{
					bOk = false;
					return 0;
				}
				V = (V << 4) | uint32(D);
			}
			return (2u << 24) | V;
		}
	}
	bOk = false;
	return 0;
}

uint16 FVerseCellsFrame::AttrsFromJson(const TArray<TSharedPtr<FJsonValue>>* Names, bool& bOk)
{
	uint16 Bits = 0;
	if (!Names)
	{
		return 0;
	}
	for (const TSharedPtr<FJsonValue>& V : *Names)
	{
		const FString Name = V.IsValid() ? V->AsString() : FString();
		bool bFound = false;
		for (int32 I = 0; I < UE_ARRAY_COUNT(AttrNames); ++I)
		{
			if (Name == AttrNames[I])
			{
				Bits |= uint16(1u << I);
				bFound = true;
			}
		}
		bOk &= bFound;
	}
	return Bits;
}

bool FVerseCellsFrame::FromJson(const TSharedPtr<FJsonObject>& Data, FVerseCellsFrame& Out, FString* OutError)
{
	if (!Data.IsValid())
	{
		return false;
	}
	Out = FVerseCellsFrame();
	FString Kind;
	Data->TryGetStringField(TEXT("kind"), Kind);
	Out.bSnapshot = Kind != TEXT("delta");
	Out.Cols = uint16(VerseBridgeJson::Num(Data, TEXT("cols")));
	Out.Rows = uint16(VerseBridgeJson::Num(Data, TEXT("rows")));
	Out.Ref = uint16(VerseBridgeJson::Num(Data, TEXT("ref")));
	const TArray<TSharedPtr<FJsonValue>>* Cursor = nullptr;
	if (Data->TryGetArrayField(TEXT("cursor"), Cursor) && Cursor->Num() == 2)
	{
		Out.CursorRow = int16((*Cursor)[0]->AsNumber());
		Out.CursorCol = int16((*Cursor)[1]->AsNumber());
	}
	bool bOk = true;
	const TArray<TSharedPtr<FJsonValue>>* RowList = nullptr;
	if (Data->TryGetArrayField(TEXT("rows_changed"), RowList))
	{
		for (const TSharedPtr<FJsonValue>& RowValue : *RowList)
		{
			const TSharedPtr<FJsonObject> RowObj = RowValue->AsObject();
			FVerseCellRow& Row = Out.RowsChanged.AddDefaulted_GetRef();
			Row.Row = uint16(RowObj->GetNumberField(TEXT("row")));
			const TArray<TSharedPtr<FJsonValue>>* Runs = nullptr;
			if (!RowObj->TryGetArrayField(TEXT("runs"), Runs))
			{
				continue;
			}
			for (const TSharedPtr<FJsonValue>& RunValue : *Runs)
			{
				const TSharedPtr<FJsonObject> RunObj = RunValue->AsObject();
				FVerseCellRun& Run = Row.Runs.AddDefaulted_GetRef();
				Run.Col = uint16(RunObj->GetNumberField(TEXT("col")));
				Run.Text = RunObj->GetStringField(TEXT("text"));
				const FTCHARToUTF8 Utf8(*Run.Text);
				Run.Utf8.Append(reinterpret_cast<const uint8*>(Utf8.Get()), Utf8.Length());
				Run.Cells = uint16(VerseCells::CountGraphemes(Run.Utf8.GetData(), Run.Utf8.Num()));
				Run.Fg = ColourFromJson(RunObj->TryGetField(TEXT("fg")), bOk);
				Run.Bg = ColourFromJson(RunObj->TryGetField(TEXT("bg")), bOk);
				const TArray<TSharedPtr<FJsonValue>>* Attrs = nullptr;
				RunObj->TryGetArrayField(TEXT("attrs"), Attrs);
				Run.Attrs = AttrsFromJson(Attrs, bOk);
			}
		}
	}
	if (!bOk)
	{
		if (OutError)
		{
			*OutError = TEXT("bad colour or attribute");
		}
		return false;
	}
	return Out.CheckRows(OutError);
}

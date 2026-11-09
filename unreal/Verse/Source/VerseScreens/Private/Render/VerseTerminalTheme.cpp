#include "Render/VerseTerminalTheme.h"

#include "Cells/VerseCells.h"
#include "Engine/Font.h"

UVerseTerminalTheme::UVerseTerminalTheme()
{
	Ansi = {
		FColor(0x2b, 0x2b, 0x2b), FColor(0xfc, 0x6b, 0x83), FColor(0x3f, 0xa2, 0x66), FColor(0xd2, 0x94, 0x3e),
		FColor(0x81, 0xa1, 0xc1), FColor(0xb4, 0x8e, 0xad), FColor(0x88, 0xc0, 0xd0), FColor(0xdc, 0xdc, 0xdc),
		FColor(0x8a, 0x8a, 0x8a), FColor(0xff, 0x8f, 0xa3), FColor(0x70, 0xb4, 0x89), FColor(0xf1, 0xb4, 0x67),
		FColor(0xa5, 0xbd, 0xd6), FColor(0xd4, 0xb3, 0xcc), FColor(0xa8, 0xd6, 0xe1), FColor(0xff, 0xff, 0xff),
	};
	Foreground = FColor(0xf4, 0xf4, 0xf6);
	Background = FColor(0x12, 0x14, 0x1a);
	Cursor = FColor(0xff, 0xff, 0xff);
	Font = TSoftObjectPtr<UFont>(FSoftObjectPath(TEXT("/Engine/EngineFonts/DroidSansMono.DroidSansMono")));
}

const UVerseTerminalTheme& UVerseTerminalTheme::Default()
{
	return *GetDefault<UVerseTerminalTheme>();
}

void FVerseTerminalPalette::Build(const UVerseTerminalTheme& Theme)
{
	// xterm's defaults for a slot the theme leaves out (terminalCanvas.ts ANSI_DEFAULT).
	static const FColor XtermDefault[16] = {
		FColor(0x2e, 0x34, 0x36), FColor(0xcc, 0x00, 0x00), FColor(0x4e, 0x9a, 0x06), FColor(0xc4, 0xa0, 0x00),
		FColor(0x34, 0x65, 0xa4), FColor(0x75, 0x50, 0x7b), FColor(0x06, 0x98, 0x9a), FColor(0xd3, 0xd7, 0xcf),
		FColor(0x55, 0x57, 0x53), FColor(0xef, 0x29, 0x29), FColor(0x8a, 0xe2, 0x34), FColor(0xfc, 0xe9, 0x4f),
		FColor(0x72, 0x9f, 0xcf), FColor(0xad, 0x7f, 0xa8), FColor(0x34, 0xe2, 0xe2), FColor(0xee, 0xee, 0xec),
	};
	for (int32 I = 0; I < 16; ++I)
	{
		Table[I] = Theme.Ansi.IsValidIndex(I) ? Theme.Ansi[I] : XtermDefault[I];
	}
	static const uint8 Steps[6] = {0, 95, 135, 175, 215, 255};
	int32 N = 16;
	for (int32 R = 0; R < 6; ++R)
	{
		for (int32 G = 0; G < 6; ++G)
		{
			for (int32 B = 0; B < 6; ++B)
			{
				Table[N++] = FColor(Steps[R], Steps[G], Steps[B]);
			}
		}
	}
	for (int32 I = 0; I < 24; ++I)
	{
		const uint8 V = uint8(8 + I * 10);
		Table[N++] = FColor(V, V, V);
	}
	Ink = Theme.Foreground;
	Ground = Theme.Background;
	CursorColour = Theme.Cursor;
	DimMix = Theme.DimMix;
}

void FVerseTerminalPalette::Resolve(uint32 Fg, uint32 Bg, uint16 Attrs, FColor& OutFg, FColor& OutBg, bool& bOutHasBg) const
{
	auto Rgb = [](uint32 V) { return FColor(uint8((V >> 16) & 0xFF), uint8((V >> 8) & 0xFF), uint8(V & 0xFF)); };
	const uint32 FgMode = Fg >> 24;
	if (FgMode == VerseCells::ModeRgb)
	{
		OutFg = Rgb(Fg);
	}
	else if (FgMode == VerseCells::ModePalette)
	{
		int32 Idx = int32(Fg & 0xFF);
		// xterm's drawBoldTextInBrightColors default.
		if ((Attrs & VerseCells::Bold) && Idx < 8)
		{
			Idx += 8;
		}
		OutFg = Table[Idx];
	}
	else
	{
		OutFg = Ink;
	}
	const uint32 BgMode = Bg >> 24;
	bOutHasBg = BgMode == VerseCells::ModeRgb || BgMode == VerseCells::ModePalette;
	OutBg = BgMode == VerseCells::ModeRgb ? Rgb(Bg) : BgMode == VerseCells::ModePalette ? Table[Bg & 0xFF] : Ground;
	if (Attrs & VerseCells::Inverse)
	{
		const FColor F = OutFg;
		OutFg = bOutHasBg ? OutBg : Ground;
		OutBg = F;
		bOutHasBg = true;
	}
	if (Attrs & VerseCells::Dim)
	{
		const FColor Toward = bOutHasBg ? OutBg : Ground;
		auto Mix = [this](uint8 A, uint8 B) { return uint8(FMath::RoundToInt(float(A) * (1.f - DimMix) + float(B) * DimMix)); };
		OutFg = FColor(Mix(OutFg.R, Toward.R), Mix(OutFg.G, Toward.G), Mix(OutFg.B, Toward.B));
	}
}

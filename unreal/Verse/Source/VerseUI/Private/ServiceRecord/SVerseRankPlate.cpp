#include "ServiceRecord/VerseRankPlate.h"

#include "DeckHud/VerseSlateKit.h"
#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Rendering/DrawElements.h"

namespace
{
	// Plate steel, edge and empty socket (style bible 7.2).
	const FLinearColor PlateSteel(0.396f, 0.412f, 0.431f, 1.f);
	const FLinearColor PlateEdge(0.114f, 0.122f, 0.130f, 1.f);
	const FLinearColor PlateRecess(0.023f, 0.026f, 0.030f, 1.f);

	FLinearColor Hex(uint8 R, uint8 G, uint8 B)
	{
		return FLinearColor::FromSRGBColor(FColor(R, G, B));
	}

	const FVerseRankRow* FindRow(FName RankId)
	{
		for (const FVerseRankRow& Row : FVerseServiceRecordModel::Ladder())
		{
			if (Row.Id == RankId)
			{
				return &Row;
			}
		}
		return nullptr;
	}
}

int32 FVerseRankPlate::NumLit() const
{
	int32 Count = 0;
	for (const bool bLit : Lit)
	{
		Count += bLit ? 1 : 0;
	}
	return Count;
}

bool FVerseRankPlate::IsSymmetric() const
{
	return Lit[0] == Lit[2] && Lit[3] == Lit[5];
}

FString FVerseRankPlate::Pattern() const
{
	FString Out;
	for (int32 Slot = 0; Slot < 6; ++Slot)
	{
		if (Slot == 3)
		{
			Out.AppendChar(TEXT('|'));
		}
		Out.AppendChar(Lit[Slot] ? TEXT('1') : TEXT('0'));
	}
	return Out;
}

FLinearColor FVerseRankPlate::TierColour(FName Tier)
{
	if (Tier == FName(TEXT("line"))) return Hex(0x4d, 0x86, 0xd9);
	if (Tier == FName(TEXT("command"))) return Hex(0xc2, 0x7a, 0x3a);
	if (Tier == FName(TEXT("flag"))) return Hex(0xc8, 0xa2, 0x4a);
	return Hex(0xa9, 0xad, 0xb2);
}

FLinearColor FVerseRankPlate::UniformColour(FName Tier)
{
	if (Tier == FName(TEXT("line"))) return Hex(0x34, 0x40, 0x4f);
	if (Tier == FName(TEXT("command"))) return Hex(0x24, 0x26, 0x2b);
	if (Tier == FName(TEXT("flag"))) return Hex(0x4a, 0x1d, 0x24);
	return Hex(0x3b, 0x3f, 0x47);
}

FVerseRankPlate FVerseRankPlate::For(FName RankId)
{
	const FVerseRankRow* Row = FindRow(RankId);
	if (!Row)
	{
		Row = &FVerseServiceRecordModel::Ladder()[0];
	}
	FVerseRankPlate Plate;
	Plate.Tier = Row->Tier;
	Plate.TileColour = TierColour(Row->Tier);
	int32 Slot = 0;
	for (const TCHAR Digit : Row->Plate)
	{
		if (Digit == TEXT('0') || Digit == TEXT('1'))
		{
			Plate.Lit[Slot++] = Digit == TEXT('1');
		}
	}
	return Plate;
}

FVerseRankPlate FVerseRankPlate::ForLevel(int32 Level)
{
	return For(FVerseServiceRecordModel::RankFor(Level).Id);
}

void SVerseRankPlate::Construct(const FArguments& InArgs)
{
	Rank = InArgs._Rank;
	Revealed = InArgs._Revealed;
	Width = InArgs._Width;
}

FVector2D SVerseRankPlate::ComputeDesiredSize(float) const
{
	return FVector2D(Width, Width * 0.62f);
}

int32 SVerseRankPlate::OnPaint(const FPaintArgs&, const FGeometry& Geometry, const FSlateRect&, FSlateWindowElementList& Out, int32 LayerId, const FWidgetStyle&, bool) const
{
	const FVerseRankPlate Plate = FVerseRankPlate::For(Rank.Get());
	const FVector2D Size = Geometry.GetLocalSize();
	const FSlateBrush* White = VerseSlateKit::Colour(FLinearColor::White);
	auto Box = [&](const FVector2D& Position, const FVector2D& Extent, const FLinearColor& Tint)
	{
		FSlateDrawElement::MakeBox(Out, LayerId, Geometry.ToPaintGeometry(FVector2f(Extent), FSlateLayoutTransform(FVector2f(Position))), White, ESlateDrawEffect::None, Tint);
	};
	// The plate: edge, then steel one pixel inside, with chamfered ends cut by two corner pieces.
	const float Chamfer = Size.Y * 0.22f;
	Box(FVector2D(0, 0), Size, PlateEdge);
	Box(FVector2D(1, 1), Size - FVector2D(2, 2), PlateSteel);
	for (const float X : {0.f, float(Size.X - Chamfer)})
	{
		Box(FVector2D(X, 0), FVector2D(Chamfer, Chamfer * 0.5f), FLinearColor(0, 0, 0, 0.55f));
		Box(FVector2D(X, Size.Y - Chamfer * 0.5f), FVector2D(Chamfer, Chamfer * 0.5f), FLinearColor(0, 0, 0, 0.55f));
	}
	++LayerId;
	// Six elongated hexagons, each drawn as horizontal slices of a hexagon whose points face left and right.
	const int32 Shown = Revealed.Get();
	const float TileW = Size.X * 0.24f;
	const float TileH = Size.Y * 0.32f;
	const float GapX = (Size.X - 3.f * TileW) / 4.f;
	const float GapY = (Size.Y - 2.f * TileH) / 3.f;
	int32 LitSeen = 0;
	for (int32 Slot = 0; Slot < 6; ++Slot)
	{
		const int32 Row = Slot / 3;
		const int32 Col = Slot % 3;
		const FVector2D Origin(GapX + Col * (TileW + GapX), GapY + Row * (TileH + GapY));
		bool bOn = Plate.Lit[Slot];
		if (bOn)
		{
			bOn = LitSeen < Shown;
			++LitSeen;
		}
		const FLinearColor Fill = bOn ? Plate.TileColour : PlateRecess;
		constexpr int32 Slices = 7;
		for (int32 Slice = 0; Slice < Slices; ++Slice)
		{
			// Width falls from the middle row to the top and bottom rows: a hexagon.
			const float Mid = (Slices - 1) * 0.5f;
			const float Taper = 1.f - 0.55f * FMath::Abs(Slice - Mid) / Mid;
			const float SliceW = TileW * Taper;
			Box(FVector2D(Origin.X + (TileW - SliceW) * 0.5f, Origin.Y + Slice * TileH / Slices), FVector2D(SliceW, TileH / Slices + 0.5f), Fill);
		}
	}
	return LayerId + 1;
}

#include "Belief/VerseBeliefDebugDraw.h"

#include "DrawDebugHelpers.h"
#include "Engine/World.h"
#include "ImageUtils.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "HAL/FileManager.h"

namespace
{
	float MaxMass(const FVerseBeliefGrid& Grid)
	{
		float Max = 0.f;
		for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
		{
			Max = FMath::Max(Max, Grid.GetMass(Cell));
		}
		return Max;
	}

	void Put(TArray<FColor>& Pixels, int32 Width, int32 Height, int32 X, int32 Y, const FColor& Color)
	{
		if (X >= 0 && Y >= 0 && X < Width && Y < Height)
		{
			Pixels[Y * Width + X] = Color;
		}
	}
}

FColor FVerseBeliefDebugDraw::HeatColor(float Relative)
{
	const float T = FMath::Clamp(Relative, 0.f, 1.f);
	// Steel (40, 42, 46) -> amber (232, 150, 40) -> red (210, 40, 30).
	const FLinearColor Steel(40.f / 255.f, 42.f / 255.f, 46.f / 255.f);
	const FLinearColor Amber(232.f / 255.f, 150.f / 255.f, 40.f / 255.f);
	const FLinearColor Red(210.f / 255.f, 40.f / 255.f, 30.f / 255.f);
	const FLinearColor Color = T < 0.5f ? FMath::Lerp(Steel, Amber, T * 2.f) : FMath::Lerp(Amber, Red, (T - 0.5f) * 2.f);
	return Color.ToFColor(false);
}

void FVerseBeliefDebugDraw::DrawWorld(const UWorld* World, const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived,
	float LifetimeS, float MinRelative)
{
#if ENABLE_DRAW_DEBUG
	if (!World)
	{
		return;
	}
	const float Max = MaxMass(Grid);
	if (Max <= 0.f)
	{
		return;
	}
	const float Half = 0.45f * Grid.GetCellSizeCm();
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		if (!Grid.IsActive(Cell))
		{
			continue;
		}
		const float Relative = Grid.GetMass(Cell) / Max;
		if (Relative < MinRelative)
		{
			continue;
		}
		const FVector Centre = Grid.GetCellCentre(Cell) + FVector(0.0, 0.0, 5.0);
		DrawDebugSolidBox(World, Centre, FVector(Half, Half, 2.0 + 30.0 * Relative), HeatColor(Relative).WithAlpha(160), false, LifetimeS);
	}
	if (Derived.TopCluster.CentreCell != INDEX_NONE)
	{
		DrawDebugCircle(World, Derived.TopCluster.Centre + FVector(0.0, 0.0, 10.0), Grid.GetTuning().ClusterRadiusCm, 48,
			FColor(212, 175, 55), false, LifetimeS, 0, 4.f, FVector(1, 0, 0), FVector(0, 1, 0), false);
	}
#endif
}

void FVerseBeliefDebugDraw::RenderTopDown(const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived, EVerseArenaLevel Level,
	int32 PixelsPerCell, TArray<FColor>& OutPixels, int32& OutWidth, int32& OutHeight, TConstArrayView<FVector> Marks)
{
	const int32 Scale = FMath::Max(1, PixelsPerCell);
	FIntPoint Min(TNumericLimits<int32>::Max(), TNumericLimits<int32>::Max());
	FIntPoint Max(TNumericLimits<int32>::Lowest(), TNumericLimits<int32>::Lowest());
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		const FIntPoint Column = Grid.GetCell(Cell).Column;
		Min.X = FMath::Min(Min.X, Column.X);
		Min.Y = FMath::Min(Min.Y, Column.Y);
		Max.X = FMath::Max(Max.X, Column.X);
		Max.Y = FMath::Max(Max.Y, Column.Y);
	}
	if (Grid.NumCells() == 0)
	{
		OutWidth = OutHeight = 0;
		OutPixels.Reset();
		return;
	}
	const int32 Columns = Max.X - Min.X + 1;
	const int32 Rows = Max.Y - Min.Y + 1;
	OutWidth = Columns * Scale;
	OutHeight = Rows * Scale;
	OutPixels.Init(FColor(8, 8, 9), OutWidth * OutHeight);
	const float MaxP = FMath::Max(MaxMass(Grid), 1e-12f);
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Grid.GetCell(Cell);
		if (Desc.Level != Level)
		{
			continue;
		}
		const FColor Color = Grid.IsActive(Cell) ? HeatColor(FMath::Sqrt(Grid.GetMass(Cell) / MaxP)) : FColor(20, 20, 22);
		const int32 Px = (Desc.Column.X - Min.X) * Scale;
		const int32 Py = (Max.Y - Desc.Column.Y) * Scale;
		for (int32 Dy = 0; Dy < Scale - (Scale > 3 ? 1 : 0); ++Dy)
		{
			for (int32 Dx = 0; Dx < Scale - (Scale > 3 ? 1 : 0); ++Dx)
			{
				Put(OutPixels, OutWidth, OutHeight, Px + Dx, Py + Dy, Color);
			}
		}
	}
	auto ToPixel = [&](const FVector& World) {
		const double Fx = (World.X - Grid.GetCellCentre(0).X) / Grid.GetCellSizeCm() + Grid.GetCell(0).Column.X;
		const double Fy = (World.Y - Grid.GetCellCentre(0).Y) / Grid.GetCellSizeCm() + Grid.GetCell(0).Column.Y;
		return FVector2D((Fx - Min.X + 0.5) * Scale, (Max.Y - Fy + 0.5) * Scale);
	};
	if (Derived.TopCluster.CentreCell != INDEX_NONE && Derived.TopCluster.Level == Level)
	{
		const FVector2D Centre = ToPixel(Derived.TopCluster.Centre);
		const double Radius = Grid.GetTuning().ClusterRadiusCm / Grid.GetCellSizeCm() * Scale;
		for (int32 Step = 0; Step < 720; ++Step)
		{
			const double A = Step * UE_DOUBLE_PI / 360.0;
			Put(OutPixels, OutWidth, OutHeight, FMath::RoundToInt(Centre.X + Radius * FMath::Cos(A)),
				FMath::RoundToInt(Centre.Y + Radius * FMath::Sin(A)), FColor(212, 175, 55));
		}
	}
	for (const FVector& Mark : Marks)
	{
		const FVector2D Pixel = ToPixel(Mark);
		const int32 Cx = FMath::RoundToInt(Pixel.X);
		const int32 Cy = FMath::RoundToInt(Pixel.Y);
		for (int32 D = -Scale; D <= Scale; ++D)
		{
			Put(OutPixels, OutWidth, OutHeight, Cx + D, Cy + D, FColor::White);
			Put(OutPixels, OutWidth, OutHeight, Cx + D, Cy - D, FColor::White);
		}
	}
}

bool FVerseBeliefDebugDraw::SavePng(const FString& Path, const FVerseBeliefGrid& Grid, const FVerseBeliefDerived& Derived,
	EVerseArenaLevel Level, int32 PixelsPerCell, TConstArrayView<FVector> Marks)
{
	TArray<FColor> Pixels;
	int32 Width = 0;
	int32 Height = 0;
	RenderTopDown(Grid, Derived, Level, PixelsPerCell, Pixels, Width, Height, Marks);
	if (Width == 0 || Height == 0)
	{
		return false;
	}
	TArray64<uint8> Png;
	FImageUtils::PNGCompressImageArray(Width, Height, TArrayView64<const FColor>(Pixels.GetData(), Pixels.Num()), Png);
	IFileManager::Get().MakeDirectory(*FPaths::GetPath(Path), true);
	return FFileHelper::SaveArrayToFile(TArrayView64<const uint8>(Png.GetData(), Png.Num()), *Path);
}

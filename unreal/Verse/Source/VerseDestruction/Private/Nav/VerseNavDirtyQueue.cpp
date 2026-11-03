#include "Nav/VerseNavDirtyQueue.h"

FBox FVerseNavDirtyQueue::FTile::GetBox() const
{
	const FVector Min(Key.X * TileSizeCm, Key.Y * TileSizeCm, MinZ);
	const FVector Max((Key.X + 1) * TileSizeCm, (Key.Y + 1) * TileSizeCm, MaxZ);
	return FBox(Min, Max);
}

FVerseNavDirtyQueue::FVerseNavDirtyQueue(int32 InMaxInFlight, float InMarginCm)
	: MaxInFlight(FMath::Max(1, InMaxInFlight))
	, MarginCm(FMath::Max(0.f, InMarginCm))
{
}

FIntPoint FVerseNavDirtyQueue::TileOf(const FVector& Point)
{
	return FIntPoint(FMath::FloorToInt32(Point.X / TileSizeCm), FMath::FloorToInt32(Point.Y / TileSizeCm));
}

void FVerseNavDirtyQueue::MarkDirty(const FBox& Box, int32 PieceIndex)
{
	if (!Box.IsValid)
	{
		return;
	}
	const FBox Grown = Box.ExpandBy(MarginCm);
	const FIntPoint Lo = TileOf(Grown.Min);
	const FIntPoint Hi = TileOf(Grown.Max);
	for (int32 X = Lo.X; X <= Hi.X; ++X)
	{
		for (int32 Y = Lo.Y; Y <= Hi.Y; ++Y)
		{
			const FIntPoint Key(X, Y);
			FTile* Existing = Queue.FindByPredicate([&Key](const FTile& Tile) { return Tile.Key == Key; });
			if (Existing)
			{
				Existing->MinZ = FMath::Min(Existing->MinZ, float(Grown.Min.Z));
				Existing->MaxZ = FMath::Max(Existing->MaxZ, float(Grown.Max.Z));
				continue;
			}
			FTile Tile;
			Tile.Key = Key;
			Tile.PieceIndex = PieceIndex;
			Tile.MinZ = float(Grown.Min.Z);
			Tile.MaxZ = float(Grown.Max.Z);
			Queue.Add(Tile);
		}
	}
}

TArray<FVerseNavDirtyQueue::FTile> FVerseNavDirtyQueue::Release(int32 CompletedSinceLastRelease)
{
	InFlight = FMath::Max(0, InFlight - FMath::Max(0, CompletedSinceLastRelease));
	const int32 Count = FMath::Min(Queue.Num(), MaxInFlight - InFlight);
	TArray<FTile> Out;
	if (Count <= 0)
	{
		return Out;
	}
	Out.Append(Queue.GetData(), Count);
	Queue.RemoveAt(0, Count, EAllowShrinking::No);
	InFlight += Count;
	PeakInFlight = FMath::Max(PeakInFlight, InFlight);
	return Out;
}

TArray<FVerseNavDirtyQueue::FTile> FVerseNavDirtyQueue::ReleaseAll()
{
	TArray<FTile> Out = MoveTemp(Queue);
	Queue.Reset();
	InFlight = 0;
	return Out;
}

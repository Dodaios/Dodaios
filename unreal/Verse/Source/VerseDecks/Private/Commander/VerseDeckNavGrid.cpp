#include "Commander/VerseDeckNavGrid.h"

#include "Algo/Reverse.h"
#include "Decks/VerseDeckManifest.h"

namespace VerseDeckNavGridPrivate
{
	/** Searches give up past this many expanded cells (a 60 x 200 m deck has 300k). */
	constexpr int32 MaxExpanded = 400000;
	constexpr int32 DC[8] = { 1, -1, 0, 0, 1, 1, -1, -1 };
	constexpr int32 DR[8] = { 0, 0, 1, -1, 1, -1, 1, -1 };

	struct FOpen
	{
		int32 Cell;
		double F;
	};

	struct FOpenLess
	{
		bool operator()(const FOpen& A, const FOpen& B) const { return A.F < B.F; }
	};
}

void FVerseDeckNavGrid::Init(const FBox2D& BoundsCm, double CellCm)
{
	Cell = FMath::Max(1.0, CellCm);
	Origin = BoundsCm.Min;
	const FVector2D Size = BoundsCm.GetSize();
	Cols = FMath::Max(1, FMath::CeilToInt32(Size.X / Cell));
	Rows = FMath::Max(1, FMath::CeilToInt32(Size.Y / Cell));
	const int32 N = Cols * Rows;
	Walkable.Init(0, N);
	Heights.Init(0.f, N);
	RoomZ.Init(TNumericLimits<float>::Lowest(), N);
	NextRow = 0;
}

void FVerseDeckNavGrid::InitFromManifest(const FVerseDeckManifest& Manifest, double CellCm)
{
	FBox2D Bounds(ForceInit);
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		for (const FVector2D& Point : Room.PolygonCm)
		{
			Bounds += Point;
		}
	}
	if (!Bounds.bIsValid)
	{
		Init(FBox2D(FVector2D::ZeroVector, FVector2D(CellCm, CellCm)), CellCm);
		NextRow = Rows;
		return;
	}
	Init(Bounds, CellCm);
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		FBox2D RoomBox(ForceInit);
		for (const FVector2D& Point : Room.PolygonCm)
		{
			RoomBox += Point;
		}
		const int32 C0 = FMath::Clamp(FMath::FloorToInt32((RoomBox.Min.X - Origin.X) / Cell), 0, Cols - 1);
		const int32 C1 = FMath::Clamp(FMath::FloorToInt32((RoomBox.Max.X - Origin.X) / Cell), 0, Cols - 1);
		const int32 R0 = FMath::Clamp(FMath::FloorToInt32((RoomBox.Min.Y - Origin.Y) / Cell), 0, Rows - 1);
		const int32 R1 = FMath::Clamp(FMath::FloorToInt32((RoomBox.Max.Y - Origin.Y) / Cell), 0, Rows - 1);
		for (int32 R = R0; R <= R1; ++R)
		{
			for (int32 C = C0; C <= C1; ++C)
			{
				const int32 Index = R * Cols + C;
				if (Room.ContainsPlan(CellCentre(Index)))
				{
					// Overlapping rooms (a walkway over a pit): probe from the highest floor down.
					RoomZ[Index] = FMath::Max(RoomZ[Index], static_cast<float>(Room.ZCm));
				}
			}
		}
	}
}

int32 FVerseDeckNavGrid::ProbeRows(int32 NumRows, FFloorProbe Probe)
{
	const int32 End = FMath::Min(Rows, NextRow + FMath::Max(0, NumRows));
	for (int32 R = NextRow; R < End; ++R)
	{
		for (int32 C = 0; C < Cols; ++C)
		{
			const int32 Index = R * Cols + C;
			if (RoomZ[Index] == TNumericLimits<float>::Lowest())
			{
				continue;
			}
			const TOptional<double> Floor = Probe(CellCentre(Index), RoomZ[Index]);
			SetCell(Index, Floor.IsSet(), Floor.Get(0.0));
		}
	}
	NextRow = End;
	return Rows - NextRow;
}

void FVerseDeckNavGrid::SetCell(int32 Index, bool bWalkable, double HeightCm)
{
	if (Walkable.IsValidIndex(Index))
	{
		Walkable[Index] = bWalkable ? 1 : 0;
		Heights[Index] = static_cast<float>(HeightCm);
	}
}

int32 FVerseDeckNavGrid::CellIndex(const FVector2D& PlanCm) const
{
	const int32 C = FMath::FloorToInt32((PlanCm.X - Origin.X) / Cell);
	const int32 R = FMath::FloorToInt32((PlanCm.Y - Origin.Y) / Cell);
	if (C < 0 || R < 0 || C >= Cols || R >= Rows)
	{
		return INDEX_NONE;
	}
	return R * Cols + C;
}

FVector2D FVerseDeckNavGrid::CellCentre(int32 Index) const
{
	const int32 C = Index % FMath::Max(1, Cols);
	const int32 R = Index / FMath::Max(1, Cols);
	return FVector2D(Origin.X + (C + 0.5) * Cell, Origin.Y + (R + 0.5) * Cell);
}

bool FVerseDeckNavGrid::IsWalkable(const FVector2D& PlanCm) const
{
	const int32 Index = CellIndex(PlanCm);
	return Index != INDEX_NONE && Walkable[Index] == 1;
}

TOptional<double> FVerseDeckNavGrid::FloorHeight(const FVector2D& PlanCm) const
{
	const int32 Index = CellIndex(PlanCm);
	if (Index == INDEX_NONE || Walkable[Index] != 1)
	{
		return {};
	}
	return static_cast<double>(Heights[Index]);
}

int32 FVerseDeckNavGrid::NumWalkable() const
{
	int32 Count = 0;
	for (const uint8 Flag : Walkable)
	{
		Count += Flag;
	}
	return Count;
}

bool FVerseDeckNavGrid::IsOpen(int32 Col, int32 Row) const
{
	return Col >= 0 && Row >= 0 && Col < Cols && Row < Rows && Walkable[Row * Cols + Col] == 1;
}

int32 FVerseDeckNavGrid::NearestWalkableCell(const FVector2D& PlanCm, double MaxCm) const
{
	const int32 C0 = FMath::FloorToInt32((PlanCm.X - Origin.X) / Cell);
	const int32 R0 = FMath::FloorToInt32((PlanCm.Y - Origin.Y) / Cell);
	if (IsOpen(C0, R0))
	{
		return R0 * Cols + C0;
	}
	const int32 MaxRing = FMath::CeilToInt32(MaxCm / Cell);
	int32 Best = INDEX_NONE;
	double BestD = TNumericLimits<double>::Max();
	for (int32 Ring = 1; Ring <= MaxRing; ++Ring)
	{
		for (int32 DR = -Ring; DR <= Ring; ++DR)
		{
			const bool bEdge = FMath::Abs(DR) == Ring;
			for (int32 DC = -Ring; DC <= Ring; DC += bEdge ? 1 : 2 * Ring)
			{
				if (!IsOpen(C0 + DC, R0 + DR))
				{
					continue;
				}
				// Distance from the point itself, so the nearest floor wins, not the nearest cell index.
				const int32 Index = (R0 + DR) * Cols + (C0 + DC);
				const double D = FVector2D::DistSquared(CellCentre(Index), PlanCm);
				if (D < BestD)
				{
					BestD = D;
					Best = Index;
				}
			}
		}
		if (Best != INDEX_NONE)
		{
			break;
		}
	}
	if (Best != INDEX_NONE && FMath::Sqrt(BestD) > MaxCm + Cell * 0.5)
	{
		return INDEX_NONE;
	}
	return Best;
}

TOptional<FVector> FVerseDeckNavGrid::NearestWalkable(const FVector2D& PlanCm, double MaxCm) const
{
	if (const TOptional<double> Floor = FloorHeight(PlanCm))
	{
		return FVector(PlanCm.X, PlanCm.Y, Floor.GetValue());
	}
	const int32 Index = NearestWalkableCell(PlanCm, MaxCm);
	if (Index == INDEX_NONE)
	{
		return {};
	}
	const FVector2D At = CellCentre(Index);
	return FVector(At.X, At.Y, Heights[Index]);
}

bool FVerseDeckNavGrid::AStar(int32 Start, int32 Goal, TArray<int32>& OutCells) const
{
	using namespace VerseDeckNavGridPrivate;
	OutCells.Reset();
	if (!Walkable.IsValidIndex(Start) || !Walkable.IsValidIndex(Goal) || Walkable[Start] != 1 || Walkable[Goal] != 1)
	{
		return false;
	}
	if (Start == Goal)
	{
		OutCells.Add(Start);
		return true;
	}
	const int32 N = Cols * Rows;
	TArray<double> G;
	G.Init(TNumericLimits<double>::Max(), N);
	TArray<int32> From;
	From.Init(INDEX_NONE, N);
	TBitArray<> Closed(false, N);
	const int32 GC = Goal % Cols;
	const int32 GR = Goal / Cols;
	auto Heuristic = [GC, GR, this](int32 Index)
	{
		const int32 DX = FMath::Abs(Index % Cols - GC);
		const int32 DZ = FMath::Abs(Index / Cols - GR);
		return DX + DZ + (UE_DOUBLE_SQRT_2 - 2.0) * FMath::Min(DX, DZ);
	};
	TArray<FOpen> Open;
	G[Start] = 0.0;
	Open.HeapPush({ Start, Heuristic(Start) }, FOpenLess());
	int32 Expanded = 0;
	bool bFound = false;
	while (Open.Num() > 0)
	{
		FOpen Top;
		Open.HeapPop(Top, FOpenLess(), EAllowShrinking::No);
		const int32 Cur = Top.Cell;
		if (Closed[Cur])
		{
			continue;
		}
		if (Cur == Goal)
		{
			bFound = true;
			break;
		}
		Closed[Cur] = true;
		if (++Expanded > MaxExpanded)
		{
			return false;
		}
		const int32 CC = Cur % Cols;
		const int32 CR = Cur / Cols;
		for (int32 K = 0; K < 8; ++K)
		{
			const int32 NC = CC + DC[K];
			const int32 NR = CR + DR[K];
			if (!IsOpen(NC, NR))
			{
				continue;
			}
			const int32 Next = NR * Cols + NC;
			if (Closed[Next] || FMath::Abs(Heights[Next] - Heights[Cur]) > MaxStepCm)
			{
				continue;
			}
			// A diagonal step needs both cells it squeezes between.
			if (K >= 4 && (!IsOpen(NC, CR) || !IsOpen(CC, NR)))
			{
				continue;
			}
			const double NG = G[Cur] + (K >= 4 ? UE_DOUBLE_SQRT_2 : 1.0);
			if (NG >= G[Next])
			{
				continue;
			}
			G[Next] = NG;
			From[Next] = Cur;
			Open.HeapPush({ Next, NG + Heuristic(Next) }, FOpenLess());
		}
	}
	if (!bFound)
	{
		return false;
	}
	for (int32 Index = Goal; Index != INDEX_NONE; Index = From[Index])
	{
		OutCells.Add(Index);
	}
	Algo::Reverse(OutCells);
	return true;
}

bool FVerseDeckNavGrid::LineOfWalk(const FVector2D& A, const FVector2D& B) const
{
	int32 C = FMath::FloorToInt32((A.X - Origin.X) / Cell);
	int32 R = FMath::FloorToInt32((A.Y - Origin.Y) / Cell);
	const int32 CE = FMath::FloorToInt32((B.X - Origin.X) / Cell);
	const int32 RE = FMath::FloorToInt32((B.Y - Origin.Y) / Cell);
	if (!IsOpen(C, R) || !IsOpen(CE, RE))
	{
		return false;
	}
	const double DX = B.X - A.X;
	const double DZ = B.Y - A.Y;
	const int32 StepC = DX > 0 ? 1 : -1;
	const int32 StepR = DZ > 0 ? 1 : -1;
	const double Inf = TNumericLimits<double>::Max();
	const double TDX = DX != 0 ? Cell / FMath::Abs(DX) : Inf;
	const double TDZ = DZ != 0 ? Cell / FMath::Abs(DZ) : Inf;
	double TX = DX != 0 ? (Origin.X + (C + (DX > 0 ? 1 : 0)) * Cell - A.X) / DX : Inf;
	double TZ = DZ != 0 ? (Origin.Y + (R + (DZ > 0 ? 1 : 0)) * Cell - A.Y) / DZ : Inf;
	float LastH = Heights[R * Cols + C];
	for (;;)
	{
		if (FMath::Min(TX, TZ) >= 1.0 - 1e-9)
		{
			break;
		}
		if (FMath::Abs(TX - TZ) < 1e-9)
		{
			// Through a corner: both neighbours must be open.
			if (!IsOpen(C + StepC, R) || !IsOpen(C, R + StepR))
			{
				return false;
			}
			C += StepC;
			R += StepR;
			TX += TDX;
			TZ += TDZ;
		}
		else if (TX < TZ)
		{
			C += StepC;
			TX += TDX;
		}
		else
		{
			R += StepR;
			TZ += TDZ;
		}
		if (!IsOpen(C, R))
		{
			return false;
		}
		const float H = Heights[R * Cols + C];
		if (FMath::Abs(H - LastH) > MaxStepCm)
		{
			return false;
		}
		LastH = H;
	}
	return true;
}

void FVerseDeckNavGrid::StringPull(TArray<FVector2D>& Points) const
{
	if (Points.Num() <= 2)
	{
		return;
	}
	TArray<FVector2D> Out;
	Out.Add(Points[0]);
	int32 Anchor = 0;
	while (Anchor < Points.Num() - 1)
	{
		int32 Next = Anchor + 1;
		// The farthest point still in sight; a binary search would miss a wall between two visible points.
		for (int32 J = Points.Num() - 1; J > Anchor + 1; --J)
		{
			if (LineOfWalk(Points[Anchor], Points[J]))
			{
				Next = J;
				break;
			}
		}
		Out.Add(Points[Next]);
		Anchor = Next;
	}
	Points = MoveTemp(Out);
}

bool FVerseDeckNavGrid::FindPath(const FVector& From, const FVector& To, TArray<FVector>& OutPoints) const
{
	OutPoints.Reset();
	const FVector2D From2(From.X, From.Y);
	const int32 StartCell = NearestWalkableCell(From2, 200.0);
	const TOptional<FVector> Goal = NearestWalkable(FVector2D(To.X, To.Y), 1200.0);
	if (StartCell == INDEX_NONE || !Goal.IsSet())
	{
		return false;
	}
	const FVector2D Goal2(Goal->X, Goal->Y);
	TArray<int32> Cells;
	if (!AStar(StartCell, CellIndex(Goal2), Cells))
	{
		return false;
	}
	TArray<FVector2D> Points;
	Points.Add(IsWalkable(From2) ? From2 : CellCentre(StartCell));
	for (int32 I = 1; I + 1 < Cells.Num(); ++I)
	{
		Points.Add(CellCentre(Cells[I]));
	}
	Points.Add(Goal2);
	StringPull(Points);
	for (const FVector2D& Point : Points)
	{
		OutPoints.Add(FVector(Point.X, Point.Y, FloorHeight(Point).Get(From.Z)));
	}
	return true;
}

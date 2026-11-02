#include "Belief/VerseBeliefGrid.h"

#include "Algo/Reverse.h"
#include "Misc/Crc.h"

namespace
{
	constexpr int32 LevelCount = 3;

	const FIntPoint EightOffsets[8] = {
		{1, 0}, {-1, 0}, {0, 1}, {0, -1}, {1, 1}, {1, -1}, {-1, 1}, {-1, -1}};

	bool GateOpen(EVerseBeliefGate Gate, int32 Piece, TFunctionRef<bool(int32)> IsOpen, TFunctionRef<bool(int32)> IsStanding)
	{
		switch (Gate)
		{
		case EVerseBeliefGate::WhenOpen:
			return Piece != INDEX_NONE && IsOpen(Piece);
		case EVerseBeliefGate::WhenStanding:
			return Piece == INDEX_NONE || IsStanding(Piece);
		default:
			return true;
		}
	}

	float FastPowCos(float Cos, float Exponent)
	{
		if (Cos <= 0.f)
		{
			return 0.f;
		}
		if (Exponent == 4.f)
		{
			const float Sq = Cos * Cos;
			return Sq * Sq;
		}
		return FMath::Pow(Cos, Exponent);
	}
}

void FVerseBeliefGrid::Build(const FVerseBeliefGridSource& Source, const FVerseBeliefTuning& InTuning)
{
	Tuning = InTuning;
	Origin = Source.Origin;
	CellSizeCm = FMath::Max(1.f, Source.CellSizeCm);

	Cells.Reset();
	TArray<int32> SourceToCell;
	SourceToCell.Init(INDEX_NONE, Source.Cells.Num());
	TArray<int32> CellToSource;

	FIntPoint Min(TNumericLimits<int32>::Max(), TNumericLimits<int32>::Max());
	FIntPoint Max(TNumericLimits<int32>::Lowest(), TNumericLimits<int32>::Lowest());
	for (const FVerseBeliefCellDesc& Desc : Source.Cells)
	{
		Min.X = FMath::Min(Min.X, Desc.Column.X);
		Min.Y = FMath::Min(Min.Y, Desc.Column.Y);
		Max.X = FMath::Max(Max.X, Desc.Column.X);
		Max.Y = FMath::Max(Max.Y, Desc.Column.Y);
	}
	if (Source.Cells.Num() == 0)
	{
		Min = Max = FIntPoint::ZeroValue;
	}
	MinColumn = Min;
	ColumnSpan = FIntPoint(Max.X - Min.X + 1, Max.Y - Min.Y + 1);
	ColumnLookup.Init(INDEX_NONE, ColumnSpan.X * ColumnSpan.Y * LevelCount);

	for (int32 SourceIndex = 0; SourceIndex < Source.Cells.Num(); ++SourceIndex)
	{
		const FVerseBeliefCellDesc& Desc = Source.Cells[SourceIndex];
		const int32 Key = Level3(Desc.Column, Desc.Level);
		if (Key == INDEX_NONE || ColumnLookup[Key] != INDEX_NONE)
		{
			continue;
		}
		ColumnLookup[Key] = Cells.Num();
		SourceToCell[SourceIndex] = Cells.Num();
		CellToSource.Add(SourceIndex);
		Cells.Add(Desc);
	}

	const int32 Num = Cells.Num();
	Centres.SetNumUninitialized(Num);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		Centres[Cell] = FVector(Origin.X + double(Desc.Column.X) * CellSizeCm, Origin.Y + double(Desc.Column.Y) * CellSizeCm, Desc.FloorZ);
	}
	CellPrefix.SetNumUninitialized(Num);
	CentreX.SetNumUninitialized(Num);
	CentreY.SetNumUninitialized(Num);
	CentreZ.SetNumUninitialized(Num);
	CentreSq.SetNumUninitialized(Num);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		CellPrefix[Cell] = (int32(Desc.Level) * ColumnSpan.Y + (Desc.Column.Y - MinColumn.Y)) * (ColumnSpan.X + 1) +
			(Desc.Column.X - MinColumn.X) + 1;
		const FVector& C = Centres[Cell];
		CentreX[Cell] = C.X;
		CentreY[Cell] = C.Y;
		CentreZ[Cell] = C.Z;
		CentreSq[Cell] = C.X * C.X + C.Y * C.Y + C.Z * C.Z;
	}
	TArray<TArray<FNeighbour>> PerCell;
	PerCell.SetNum(Num);
	for (int32 SourceIndex = 0; SourceIndex < Source.Cells.Num(); ++SourceIndex)
	{
		const int32 Cell = SourceToCell[SourceIndex];
		if (Cell == INDEX_NONE)
		{
			continue;
		}
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
		{
			const FIntPoint& Offset = EightOffsets[DirIndex];
			const int32 Key = Level3(Desc.Column + Offset, Desc.Level);
			const int32 Other = Key == INDEX_NONE ? INDEX_NONE : ColumnLookup[Key];
			if (Other == INDEX_NONE)
			{
				continue;
			}
			if (Source.AreNeighboursConnected)
			{
				if (!Source.AreNeighboursConnected(SourceIndex, CellToSource[Other]))
				{
					continue;
				}
			}
			const float DistCm = CellSizeCm * FMath::Sqrt(float(Offset.X * Offset.X + Offset.Y * Offset.Y));
			FNeighbour& Edge = PerCell[Cell].AddDefaulted_GetRef();
			Edge.Cell = Other;
			Edge.Rate = Tuning.TypicalSpeedCmS / DistCm;
			Edge.Dir = FVector2f(float(Offset.X), float(Offset.Y)).GetSafeNormal();
			Edge.DirIndex = uint8(DirIndex);
		}
	}
	for (const FVerseBeliefLinkDesc& Link : Source.Links)
	{
		const int32 A = Source.Cells.IsValidIndex(Link.From) ? SourceToCell[Link.From] : INDEX_NONE;
		const int32 B = Source.Cells.IsValidIndex(Link.To) ? SourceToCell[Link.To] : INDEX_NONE;
		if (A == INDEX_NONE || B == INDEX_NONE || A == B)
		{
			continue;
		}
		const FVector Delta = GetCellCentre(B) - GetCellCentre(A);
		const FVector2f Horizontal = FVector2f(float(Delta.X), float(Delta.Y));
		const float Rate = 1.f / FMath::Max(0.05f, Link.TraversalS);
		auto Add = [&](int32 From, int32 To, const FVector2f& Dir) {
			FNeighbour& Edge = PerCell[From].AddDefaulted_GetRef();
			Edge.Cell = To;
			Edge.Rate = Rate;
			Edge.Dir = Horizontal.SizeSquared() > 1.f ? Dir : FVector2f::ZeroVector;
			Edge.Gate = Link.Gate;
			Edge.GatePiece = Link.GatePiece;
		};
		Add(A, B, Horizontal.GetSafeNormal());
		if (Link.bBidirectional)
		{
			Add(B, A, -Horizontal.GetSafeNormal());
		}
	}

	NeighbourStart.SetNumUninitialized(Num + 1);
	Neighbours.Reset();
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		NeighbourStart[Cell] = Neighbours.Num();
		Neighbours.Append(PerCell[Cell]);
	}
	NeighbourStart[Num] = Neighbours.Num();

	DiscOffsets.Reset();
	const int32 Reach = FMath::CeilToInt(Tuning.ClusterRadiusCm / CellSizeCm);
	DiscHalfWidth.Init(-1, 2 * Reach + 1);
	for (int32 Dx = -Reach; Dx <= Reach; ++Dx)
	{
		for (int32 Dy = -Reach; Dy <= Reach; ++Dy)
		{
			if (FMath::Square(float(Dx) * CellSizeCm) + FMath::Square(float(Dy) * CellSizeCm) <=
				FMath::Square(Tuning.ClusterRadiusCm) + 1.f)
			{
				DiscOffsets.Add(FIntPoint(Dx, Dy));
				DiscHalfWidth[Dy + Reach] = FMath::Max(DiscHalfWidth[Dy + Reach], FMath::Abs(Dx));
			}
		}
	}

	bCellActive.Init(1, Num);
	RateSum.Init(0.f, Num);
	BucketScratch.Init(0, Num);
	P.Init(0.f, Num);
	Scratch.Init(0.f, Num);
	Prior.Reset();
	LastClearedS.Init(-1.f, Num);
	LastSupportS.Init(-1.f, Num);
	LastSupportKind.Init(EVerseBeliefSupport::None, Num);
	bMomentum = false;
	bOpponentDead = false;

	// The match starts with every piece intact (destruction full reset).
	ApplyGates([](int32) { return false; }, [](int32) { return true; });
	ResetUniform();
}

int32 FVerseBeliefGrid::Level3(const FIntPoint& Column, EVerseArenaLevel Level) const
{
	const FIntPoint Local = Column - MinColumn;
	if (Local.X < 0 || Local.Y < 0 || Local.X >= ColumnSpan.X || Local.Y >= ColumnSpan.Y)
	{
		return INDEX_NONE;
	}
	return (int32(Level) * ColumnSpan.Y + Local.Y) * ColumnSpan.X + Local.X;
}

FIntPoint FVerseBeliefGrid::ColumnOf(const FVector& WorldLocation) const
{
	return FIntPoint(FMath::RoundToInt((WorldLocation.X - Origin.X) / CellSizeCm),
		FMath::RoundToInt((WorldLocation.Y - Origin.Y) / CellSizeCm));
}

int32 FVerseBeliefGrid::FindCell(const FIntPoint& Column, EVerseArenaLevel Level) const
{
	const int32 Key = Level3(Column, Level);
	const int32 Cell = Key == INDEX_NONE ? INDEX_NONE : ColumnLookup[Key];
	return Cell != INDEX_NONE && bCellActive[Cell] ? Cell : INDEX_NONE;
}

int32 FVerseBeliefGrid::FindCellAnyState(const FIntPoint& Column, EVerseArenaLevel Level) const
{
	const int32 Key = Level3(Column, Level);
	return Key == INDEX_NONE ? INDEX_NONE : ColumnLookup[Key];
}

void FVerseBeliefGrid::RecomputeRateSums()
{
	// Dense, padded per-level layout for the predict stencil: one weight array per adjacency
	// direction (0 where the edge does not exist or is inactive), plus a short list of links.
	const int32 Num = Cells.Num();
	const int32 PadX = ColumnSpan.X + 2;
	const int32 PadY = ColumnSpan.Y + 2;
	DenseSize = 3 * PadX * PadY;
	CellDense.SetNumUninitialized(Num);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		CellDense[Cell] = (int32(Desc.Level) * PadY + (Desc.Column.Y - MinColumn.Y + 1)) * PadX + (Desc.Column.X - MinColumn.X + 1);
	}
	for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
	{
		DirOffset[DirIndex] = EightOffsets[DirIndex].Y * PadX + EightOffsets[DirIndex].X;
		DenseRateBias[DirIndex].Init(0.f, DenseSize);
		DenseRate[DirIndex].Init(0.f, DenseSize);
	}
	LinkFrom.Reset();
	LinkTo.Reset();
	LinkRateBias.Reset();
	LinkRate.Reset();
	LinkDirs.Reset();
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		float Sum = 0.f;
		for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
		{
			const FNeighbour& Neighbour = Neighbours[Edge];
			if (!Neighbour.bActive)
			{
				continue;
			}
			Sum += Neighbour.Rate * Neighbour.Bias;
			if (Neighbour.DirIndex < 8)
			{
				DenseRateBias[Neighbour.DirIndex][CellDense[Cell]] = Neighbour.Rate * Neighbour.Bias;
				DenseRate[Neighbour.DirIndex][CellDense[Cell]] = Neighbour.Rate;
			}
			else
			{
				LinkFrom.Add(Cell);
				LinkTo.Add(Neighbour.Cell);
				LinkRateBias.Add(Neighbour.Rate * Neighbour.Bias);
				LinkRate.Add(Neighbour.Rate);
				LinkDirs.Add(Neighbour.Dir);
			}
		}
		RateSum[Cell] = Sum;
	}
	DenseOut.Init(0.f, DenseSize);
	DenseDiffuse.Init(0.f, DenseSize);
	DenseAdvect.Init(0.f, DenseSize);
	DenseSumA.Init(0.f, DenseSize);
}

int32 FVerseBeliefGrid::FindCell(const FVector& WorldLocation) const
{
	// The floor under the point: the highest cell of the column at most 60 cm above it.
	const FIntPoint Column = ColumnOf(WorldLocation);
	int32 Best = INDEX_NONE;
	float BestZ = TNumericLimits<float>::Lowest();
	for (int32 Level = 0; Level < LevelCount; ++Level)
	{
		const int32 Cell = FindCell(Column, EVerseArenaLevel(Level));
		if (Cell != INDEX_NONE && Cells[Cell].FloorZ <= WorldLocation.Z + 60.f && Cells[Cell].FloorZ > BestZ)
		{
			Best = Cell;
			BestZ = Cells[Cell].FloorZ;
		}
	}
	if (Best != INDEX_NONE)
	{
		return Best;
	}
	double BestDist = TNumericLimits<double>::Max();
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		if (!bCellActive[Cell])
		{
			continue;
		}
		const double Dist = FVector::DistSquared(GetCellCentre(Cell), WorldLocation);
		if (Dist < BestDist)
		{
			BestDist = Dist;
			Best = Cell;
		}
	}
	return Best;
}

int32 FVerseBeliefGrid::NumNeighbours(int32 Cell) const
{
	int32 Count = 0;
	for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
	{
		Count += Neighbours[Edge].bActive ? 1 : 0;
	}
	return Count;
}

void FVerseBeliefGrid::GetNeighbours(int32 Cell, TArray<int32>& Out) const
{
	Out.Reset();
	for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
	{
		if (Neighbours[Edge].bActive)
		{
			Out.Add(Neighbours[Edge].Cell);
		}
	}
}

bool FVerseBeliefGrid::ApplyGates(TFunctionRef<bool(int32 Piece)> IsOpen, TFunctionRef<bool(int32 Piece)> IsStanding)
{
	bool bChanged = false;
	bool bDropped = false;
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		if (Desc.Gate == EVerseBeliefGate::Always)
		{
			continue;
		}
		const uint8 Active = GateOpen(Desc.Gate, Desc.GatePiece, IsOpen, IsStanding) ? 1 : 0;
		if (Active != bCellActive[Cell])
		{
			bCellActive[Cell] = Active;
			bChanged = true;
			if (!Active && P.IsValidIndex(Cell) && P[Cell] > 0.f)
			{
				P[Cell] = 0.f;
				bDropped = true;
			}
		}
	}
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
		{
			FNeighbour& Neighbour = Neighbours[Edge];
			const bool bActive = bCellActive[Cell] && bCellActive[Neighbour.Cell] &&
				GateOpen(Neighbour.Gate, Neighbour.GatePiece, IsOpen, IsStanding);
			bChanged |= bActive != Neighbour.bActive;
			Neighbour.bActive = bActive;
		}
	}
	RecomputeRateSums();
	if (bDropped)
	{
		Normalise();
	}
	return bChanged;
}

void FVerseBeliefGrid::ResetUniform()
{
	bOpponentDead = false;
	int32 Active = 0;
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		Active += bCellActive[Cell];
	}
	const float Mass = Active > 0 ? float(1.0 / double(Active)) : 0.f;
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		P[Cell] = bCellActive[Cell] ? Mass : 0.f;
	}
}

void FVerseBeliefGrid::SetPositionPrior(TConstArrayView<float> PerCell)
{
	Prior.Reset();
	if (PerCell.Num() == Cells.Num())
	{
		Prior.Append(PerCell.GetData(), PerCell.Num());
	}
}

void FVerseBeliefGrid::SetZoneTransitionPrior(int32 Zones, TConstArrayView<float> Matrix)
{
	const bool bValid = Zones > 0 && Matrix.Num() == Zones * Zones;
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
		{
			FNeighbour& Neighbour = Neighbours[Edge];
			const int32 From = Cells[Cell].Zone;
			const int32 To = Cells[Neighbour.Cell].Zone;
			Neighbour.Bias = 1.f;
			if (bValid && From < Zones && To < Zones)
			{
				Neighbour.Bias = 1.f + Tuning.ZoneBiasGain * FMath::Clamp(Matrix[From * Zones + To], 0.f, 1.f);
			}
		}
	}
	RecomputeRateSums();
}

void FVerseBeliefGrid::SetMomentum(const FVector& Velocity, float AtS)
{
	MomentumVelocity = FVector2f(float(Velocity.X), float(Velocity.Y));
	MomentumAtS = AtS;
	bMomentum = MomentumVelocity.SizeSquared() > 1.f;
}

void FVerseBeliefGrid::ClearMomentum()
{
	bMomentum = false;
}

void FVerseBeliefGrid::Predict(float DeltaS, float NowS)
{
	if (bOpponentDead || DeltaS <= 0.f)
	{
		return;
	}
	float MomentumCellFraction = 0.f;
	FVector2f MomentumDir = FVector2f::ZeroVector;
	const float MomentumAge = FMath::Max(0.f, NowS - MomentumAtS);
	if (bMomentum && MomentumAge <= Tuning.MomentumMaxAgeS)
	{
		const float Speed = MomentumVelocity.Size() * FMath::Exp(-MomentumAge / FMath::Max(0.01f, Tuning.MomentumDecayS));
		MomentumCellFraction = FMath::Min(Tuning.MomentumMaxFraction, Speed * DeltaS / CellSizeCm);
		MomentumDir = MomentumVelocity.GetSafeNormal();
	}
	const bool bAdvect = MomentumCellFraction > 0.f;
	float Cos[8];
	for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
	{
		const FVector2f Dir = FVector2f(float(EightOffsets[DirIndex].X), float(EightOffsets[DirIndex].Y)).GetSafeNormal();
		Cos[DirIndex] = bAdvect ? FastPowCos(FVector2f::DotProduct(Dir, MomentumDir), Tuning.MomentumExponent) : 0.f;
	}
	const int32 Links = LinkFrom.Num();
	LinkCos.SetNumUninitialized(Links);
	for (int32 Link = 0; Link < Links; ++Link)
	{
		LinkCos[Link] = bAdvect ? FastPowCos(FVector2f::DotProduct(LinkDirs[Link], MomentumDir), Tuning.MomentumExponent) : 0.f;
	}

	const int32 Num = Cells.Num();
	const int32 Size = DenseSize;
	float* Out = DenseOut.GetData();
	float* Diffuse = DenseDiffuse.GetData();
	float* Advect = DenseAdvect.GetData();
	float* SumA = DenseSumA.GetData();
	FMemory::Memzero(Out, sizeof(float) * Size);
	FMemory::Memzero(Diffuse, sizeof(float) * Size);
	FMemory::Memzero(Advect, sizeof(float) * Size);

	// Momentum weight sum per cell: dense passes over the 8 directions, then the links.
	if (bAdvect)
	{
		FMemory::Memzero(SumA, sizeof(float) * Size);
		for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
		{
			const float C = Cos[DirIndex];
			if (C <= 0.f)
			{
				continue;
			}
			const float* Rate = DenseRate[DirIndex].GetData();
			for (int32 Index = 0; Index < Size; ++Index)
			{
				SumA[Index] += C * Rate[Index];
			}
		}
		for (int32 Link = 0; Link < Links; ++Link)
		{
			SumA[CellDense[LinkFrom[Link]]] += LinkCos[Link] * LinkRate[Link];
		}
	}

	// Per cell: what stays, the diffusion scale and the advection scale.
	const float MaxDiffusion = Tuning.MaxDiffusionFraction;
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const float M = P[Cell];
		if (M <= 0.f)
		{
			continue;
		}
		const int32 Dense = CellDense[Cell];
		const float SumW = RateSum[Cell] * DeltaS;
		if (SumW <= 0.f)
		{
			Out[Dense] += M;
			continue;
		}
		const float DiffusionScale = FMath::Min(1.f, MaxDiffusion / SumW);
		float Kept = M * (1.f - SumW * DiffusionScale);
		Diffuse[Dense] = M * DeltaS * DiffusionScale;
		if (bAdvect && SumA[Dense] > 0.f)
		{
			Kept -= M * MomentumCellFraction;
			Advect[Dense] = M * MomentumCellFraction / SumA[Dense];
		}
		Out[Dense] += Kept;
	}

	// The stencil: each direction is one contiguous pass (padding keeps every target in range).
	for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
	{
		const int32 Offset = DirOffset[DirIndex];
		const float* RateBias = DenseRateBias[DirIndex].GetData();
		const int32 Begin = FMath::Max(0, -Offset);
		const int32 End = FMath::Min(Size, Size - Offset);
		float* Target = Out + Offset;
		if (bAdvect && Cos[DirIndex] > 0.f)
		{
			const float C = Cos[DirIndex];
			const float* Rate = DenseRate[DirIndex].GetData();
			for (int32 Index = Begin; Index < End; ++Index)
			{
				Target[Index] += Diffuse[Index] * RateBias[Index] + Advect[Index] * C * Rate[Index];
			}
		}
		else
		{
			for (int32 Index = Begin; Index < End; ++Index)
			{
				Target[Index] += Diffuse[Index] * RateBias[Index];
			}
		}
	}
	for (int32 Link = 0; Link < Links; ++Link)
	{
		const int32 From = CellDense[LinkFrom[Link]];
		Out[CellDense[LinkTo[Link]]] += Diffuse[From] * LinkRateBias[Link] + Advect[From] * LinkCos[Link] * LinkRate[Link];
	}

	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		P[Cell] = Out[CellDense[Cell]];
	}
}

void FVerseBeliefGrid::Clear(const FVector& Eye, TFunctionRef<bool(int32 Cell)> IsVisible, float NowS)
{
	if (bOpponentDead)
	{
		return;
	}
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		if (!bCellActive[Cell] || !IsVisible(Cell))
		{
			continue;
		}
		const float DistM = float(FVector::Dist(Eye, GetCellCentre(Cell)) / 100.0);
		float Pd = Tuning.ClearNearPd;
		if (DistM > Tuning.ClearNearM)
		{
			const float Alpha = FMath::Clamp((DistM - Tuning.ClearNearM) / FMath::Max(1.f, Tuning.ClearFarM - Tuning.ClearNearM), 0.f, 1.f);
			Pd = FMath::Lerp(Tuning.ClearNearPd, Tuning.ClearFarPd, Alpha);
		}
		Pd *= FMath::Clamp(Cells[Cell].Visibility, 0.f, 1.f);
		P[Cell] *= 1.f - Pd;
		LastClearedS[Cell] = NowS;
	}
}

void FVerseBeliefGrid::ApplySighting(const FVector& PelvisLocation, float NowS)
{
	bOpponentDead = false;
	const int32 Centre = FindCell(PelvisLocation - FVector(0.0, 0.0, 95.0));
	if (Centre == INDEX_NONE)
	{
		return;
	}
	const EVerseArenaLevel Level = Cells[Centre].Level;
	const FIntPoint Column = Cells[Centre].Column;
	const float Sd = FMath::Max(1.f, Tuning.SightingSdCm);
	FMemory::Memzero(P.GetData(), sizeof(float) * P.Num());
	const int32 Reach = FMath::Max(1, FMath::CeilToInt(3.f * Sd / CellSizeCm));
	for (int32 Dx = -Reach; Dx <= Reach; ++Dx)
	{
		for (int32 Dy = -Reach; Dy <= Reach; ++Dy)
		{
			const int32 Cell = FindCell(Column + FIntPoint(Dx, Dy), Level);
			if (Cell == INDEX_NONE)
			{
				continue;
			}
			const FVector C = GetCellCentre(Cell);
			const double D2 = FMath::Square(C.X - PelvisLocation.X) + FMath::Square(C.Y - PelvisLocation.Y);
			P[Cell] = float(FMath::Exp(-D2 / (2.0 * Sd * Sd)));
			if (D2 <= FMath::Square(double(CellSizeCm)))
			{
				LastSupportS[Cell] = NowS;
				LastSupportKind[Cell] = EVerseBeliefSupport::Seen;
			}
		}
	}
	if (P[Centre] <= 0.f)
	{
		P[Centre] = 1.f;
	}
	LastSupportS[Centre] = NowS;
	LastSupportKind[Centre] = EVerseBeliefSupport::Seen;
}

void FVerseBeliefGrid::ApplyHeard(const FVerseHeardPercept& Heard, float NowS)
{
	if (bOpponentDead)
	{
		return;
	}
	const double Sd = FMath::Max(25.0, double(Heard.ErrorSdM) * 100.0);
	const double Inv2Var = 1.0 / (2.0 * Sd * Sd);
	const double Support2 = FMath::Square(2.0 * Sd);
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		if (!bCellActive[Cell])
		{
			continue;
		}
		const FVector C = GetCellCentre(Cell);
		const double D2 = FMath::Square(C.X - Heard.Location.X) + FMath::Square(C.Y - Heard.Location.Y);
		const double LevelWeight =
			Cells[Cell].Level == Heard.LevelGuess ? Tuning.HeardLevelWeight : 1.0 - Tuning.HeardLevelWeight;
		P[Cell] *= float(Tuning.HeardEps + LevelWeight * FMath::Exp(-D2 * Inv2Var));
		if (D2 <= Support2 && Cells[Cell].Level == Heard.LevelGuess)
		{
			LastSupportS[Cell] = NowS;
			LastSupportKind[Cell] = EVerseBeliefSupport::Heard;
		}
	}
}

void FVerseBeliefGrid::ApplyWedge(const FVector& Point, const FVector& BackDirection, float MaxDistCm, float NowS)
{
	if (bOpponentDead)
	{
		return;
	}
	const FVector2D Back = FVector2D(BackDirection.X, BackDirection.Y).GetSafeNormal();
	if (Back.IsNearlyZero())
	{
		return;
	}
	const double Half = FMath::DegreesToRadians(double(Tuning.WedgeHalfAngleDeg));
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		if (!bCellActive[Cell])
		{
			continue;
		}
		const FVector C = GetCellCentre(Cell);
		const FVector2D V(C.X - Point.X, C.Y - Point.Y);
		const double Dist = V.Size();
		double Like = 0.0;
		if (Dist <= MaxDistCm)
		{
			if (Dist < CellSizeCm)
			{
				Like = 1.0;
			}
			else
			{
				const double Angle = FMath::Acos(FMath::Clamp(FVector2D::DotProduct(V / Dist, Back), -1.0, 1.0));
				Like = Angle <= Half ? 1.0 : (Angle <= 2.0 * Half ? 1.0 - (Angle - Half) / Half : 0.0);
			}
		}
		P[Cell] *= float(Tuning.WedgeEps + (1.0 - Tuning.WedgeEps) * Like);
		if (Like >= 0.5)
		{
			LastSupportS[Cell] = NowS;
			LastSupportKind[Cell] = EVerseBeliefSupport::Inferred;
		}
	}
}

void FVerseBeliefGrid::ApplyOpponentDead()
{
	bOpponentDead = true;
	bMomentum = false;
	FMemory::Memzero(P.GetData(), sizeof(float) * P.Num());
}

void FVerseBeliefGrid::ApplySpawnPrior(TConstArrayView<FVector> RankedSpawnPoints, float NowS)
{
	bOpponentDead = false;
	bMomentum = false;
	const int32 Count = FMath::Min(3, RankedSpawnPoints.Num());
	if (Count == 0)
	{
		ResetUniform();
		return;
	}
	double WeightSum = 0.0;
	for (int32 Index = 0; Index < Count; ++Index)
	{
		WeightSum += Tuning.SpawnWeights[Index];
	}
	FMemory::Memzero(P.GetData(), sizeof(float) * P.Num());
	const double Sd = FMath::Max(1.0, double(Tuning.SpawnSdCm));
	const int32 Reach = FMath::Max(1, FMath::CeilToInt(3.0 * Sd / CellSizeCm));
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const FVector& Spawn = RankedSpawnPoints[Index];
		const int32 Centre = FindCell(Spawn);
		if (Centre == INDEX_NONE)
		{
			continue;
		}
		const EVerseArenaLevel Level = Cells[Centre].Level;
		TArray<TPair<int32, double>, TInlineAllocator<64>> Disc;
		double DiscSum = 0.0;
		for (int32 Dx = -Reach; Dx <= Reach; ++Dx)
		{
			for (int32 Dy = -Reach; Dy <= Reach; ++Dy)
			{
				const int32 Cell = FindCell(Cells[Centre].Column + FIntPoint(Dx, Dy), Level);
				if (Cell == INDEX_NONE)
				{
					continue;
				}
				const FVector C = GetCellCentre(Cell);
				const double D2 = FMath::Square(C.X - Spawn.X) + FMath::Square(C.Y - Spawn.Y);
				const double W = FMath::Exp(-D2 / (2.0 * Sd * Sd));
				Disc.Add({Cell, W});
				DiscSum += W;
			}
		}
		const double Share = Tuning.SpawnWeights[Index] / WeightSum;
		for (const TPair<int32, double>& Item : Disc)
		{
			P[Item.Key] += float(Share * Item.Value / FMath::Max(DiscSum, 1e-12));
			LastSupportS[Item.Key] = NowS;
			LastSupportKind[Item.Key] = EVerseBeliefSupport::Inferred;
		}
	}
}

void FVerseBeliefGrid::Normalise()
{
	if (bOpponentDead)
	{
		return;
	}
	const int32 Num = Cells.Num();
	double Sum = 0.0;
	int32 Active = 0;
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		if (bCellActive[Cell])
		{
			Sum += P[Cell];
			++Active;
		}
		else
		{
			P[Cell] = 0.f;
		}
	}
	if (Active == 0)
	{
		return;
	}
	if (!(Sum > 0.0) || !FMath::IsFinite(Sum))
	{
		ResetUniform();
		return;
	}
	// Prior: 90 % learned heatmap (when there is one) plus 10 % uniform, so it is never 0.
	double PriorSum = 0.0;
	if (Prior.Num() == Num)
	{
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			PriorSum += bCellActive[Cell] ? FMath::Max(0.f, Prior[Cell]) : 0.f;
		}
	}
	const bool bHeat = PriorSum > 0.0;
	const double Mix = FMath::Clamp(double(Tuning.PriorMix), 1e-6, 1.0);
	const float Keep = float((1.0 - Mix) / Sum);
	const float Uniform = float(Mix * (bHeat ? 0.1 : 1.0) / double(Active));
	if (bHeat)
	{
		const double HeatScale = Mix * 0.9 / PriorSum;
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			if (bCellActive[Cell])
			{
				P[Cell] = P[Cell] * Keep + Uniform + float(HeatScale * FMath::Max(0.f, Prior[Cell]));
			}
		}
	}
	else
	{
		float* Mass = P.GetData();
		const uint8* ActiveMask = bCellActive.GetData();
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			Mass[Cell] = ActiveMask[Cell] ? Mass[Cell] * Keep + Uniform : 0.f;
		}
	}
}

double FVerseBeliefGrid::TotalMass() const
{
	double Sum = 0.0;
	for (int32 Cell = 0; Cell < Cells.Num(); ++Cell)
	{
		Sum += bCellActive[Cell] ? P[Cell] : 0.f;
	}
	return Sum;
}

FVerseBeliefDerived FVerseBeliefGrid::ComputeDerived(float NowS, bool bKnown) const
{
	FVerseBeliefDerived Out;
	if (bOpponentDead)
	{
		Out.State = EVerseBeliefState::Dead;
		return Out;
	}
	const int32 Num = Cells.Num();
	if (Num == 0)
	{
		return Out;
	}

	// Pass 1: mass histogram by absolute float exponent (one bucket per factor of 2), the
	// highest exponent, and the row prefix inputs. Inactive and empty cells hold 0.
	const int32 SpanX = ColumnSpan.X;
	const int32 SpanY = ColumnSpan.Y;
	const int32 RowLen = SpanX + 1;
	PrefixScratch.SetNumUninitialized(3 * SpanY * RowLen);
	FMemory::Memzero(PrefixScratch.GetData(), sizeof(float) * PrefixScratch.Num());
	double ExpMass[256] = {};
	int32 ExpCount[256] = {};
	int32 MaxExp = 0;
	double Total = 0.0;
	{
		const float* Mass = P.GetData();
		uint8* Exps = BucketScratch.GetData();
		float* Prefix = PrefixScratch.GetData();
		const int32* PrefixIndex = CellPrefix.GetData();
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			const float Value = Mass[Cell];
			uint32 Bits;
			FMemory::Memcpy(&Bits, &Value, sizeof(Bits));
			const int32 Exp = Value > 0.f ? int32((Bits >> 23) & 0xFFu) : 0;
			Exps[Cell] = uint8(Exp);
			ExpMass[Exp] += Value;
			++ExpCount[Exp];
			MaxExp = FMath::Max(MaxExp, Exp);
			Total += Value;
			Prefix[PrefixIndex[Cell]] = Value;
		}
	}
	if (MaxExp == 0 || !(Total > 0.0))
	{
		return Out;
	}
	// Spread: the exponents (from the top) holding 90 % of the mass. Candidates: the exponents
	// within a factor of 8 of the peak, at most MaxCandidates cells, heaviest first.
	int32 SpreadMinExp = 1;
	double Accumulated = 0.0;
	for (int32 Exp = MaxExp; Exp >= 1; --Exp)
	{
		Accumulated += ExpMass[Exp];
		if (Accumulated >= 0.9 * Total)
		{
			SpreadMinExp = Exp;
			break;
		}
	}
	constexpr int32 MaxCandidates = 384;
	int32 CandidateMinExp = MaxExp;
	for (int32 Exp = MaxExp - 1, Count = ExpCount[MaxExp]; Exp >= FMath::Max(1, MaxExp - 3); --Exp)
	{
		Count += ExpCount[Exp];
		if (Count > MaxCandidates)
		{
			break;
		}
		CandidateMinExp = Exp;
	}

	// Pass 2: spread moments and candidates.
	CandidateScratch.Reset();
	double W = 0.0;
	double Sx = 0.0;
	double Sy = 0.0;
	double Sz = 0.0;
	double Sq = 0.0;
	{
		const float* Mass = P.GetData();
		const uint8* Exps = BucketScratch.GetData();
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			const int32 Exp = Exps[Cell];
			if (Exp >= SpreadMinExp)
			{
				const double Value = Mass[Cell];
				W += Value;
				Sx += Value * CentreX[Cell];
				Sy += Value * CentreY[Cell];
				Sz += Value * CentreZ[Cell];
				Sq += Value * CentreSq[Cell];
			}
			if (Exp >= CandidateMinExp && CandidateScratch.Num() < MaxCandidates)
			{
				CandidateScratch.Add(Cell);
			}
		}
	}
	for (int32 Row = 0; Row < 3 * SpanY; ++Row)
	{
		float* Line = PrefixScratch.GetData() + Row * RowLen;
		for (int32 X = 1; X < RowLen; ++X)
		{
			Line[X] += Line[X - 1];
		}
	}
	if (W > 0.0)
	{
		const double Mx = Sx / W;
		const double My = Sy / W;
		const double Mz = Sz / W;
		const double Var = FMath::Max(0.0, Sq / W - (Mx * Mx + My * My + Mz * Mz));
		Out.SpreadM = float(FMath::Sqrt(Var) / 100.0);
	}

	// TopCluster: the candidate whose disc holds the most mass (ties: lower cell index).
	const int32 Reach = DiscHalfWidth.Num() / 2;
	double BestMass = -1.0;
	int32 BestCell = INDEX_NONE;
	for (const int32 Candidate : CandidateScratch)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Candidate];
		const int32 Lx = Desc.Column.X - MinColumn.X;
		const int32 Ly = Desc.Column.Y - MinColumn.Y;
		const int32 LevelBase = int32(Desc.Level) * SpanY;
		double Mass = 0.0;
		for (int32 Dy = -Reach; Dy <= Reach; ++Dy)
		{
			const int32 Y = Ly + Dy;
			if (Y < 0 || Y >= SpanY)
			{
				continue;
			}
			const int32 Half = DiscHalfWidth[Dy + Reach];
			if (Half < 0)
			{
				continue;
			}
			const int32 X0 = FMath::Max(0, Lx - Half);
			const int32 X1 = FMath::Min(SpanX - 1, Lx + Half);
			const float* Line = PrefixScratch.GetData() + (LevelBase + Y) * RowLen;
			Mass += double(Line[X1 + 1]) - double(Line[X0]);
		}
		if (Mass > BestMass)
		{
			BestMass = Mass;
			BestCell = Candidate;
		}
	}
	if (BestCell == INDEX_NONE)
	{
		return Out;
	}

	FVector Weighted = FVector::ZeroVector;
	double DiscMass = 0.0;
	float NewestSupport = -1.f;
	EVerseBeliefSupport NewestKind = EVerseBeliefSupport::None;
	for (const FIntPoint& Offset : DiscOffsets)
	{
		const int32 Cell = FindCell(Cells[BestCell].Column + Offset, Cells[BestCell].Level);
		if (Cell == INDEX_NONE)
		{
			continue;
		}
		Weighted += Centres[Cell] * double(P[Cell]);
		DiscMass += P[Cell];
		const EVerseBeliefSupport Kind = LastSupportKind[Cell];
		if ((Kind == EVerseBeliefSupport::Seen || Kind == EVerseBeliefSupport::Heard) && LastSupportS[Cell] > NewestSupport)
		{
			NewestSupport = LastSupportS[Cell];
			NewestKind = Kind;
		}
	}
	Out.TopCluster.CentreCell = BestCell;
	Out.TopCluster.Level = Cells[BestCell].Level;
	Out.TopCluster.Mass = float(DiscMass);
	Out.TopCluster.Centre = DiscMass > 0.0 ? Weighted / DiscMass : Centres[BestCell];
	Out.Confidence = float(FMath::Clamp(DiscMass, 0.0, 1.0));
	if (NewestSupport >= 0.f)
	{
		Out.SupportAgeS = FMath::Max(0.f, NowS - NewestSupport);
		Out.SupportKind = NewestKind;
	}

	if (bKnown)
	{
		Out.State = EVerseBeliefState::Known;
	}
	else if (Out.Confidence >= Tuning.TrackedConfidence)
	{
		Out.State = EVerseBeliefState::Tracked;
	}
	else if (Out.Confidence >= Tuning.RoughConfidence)
	{
		Out.State = EVerseBeliefState::Rough;
	}
	else
	{
		Out.State = EVerseBeliefState::Lost;
	}
	return Out;
}

TArray<int32> FVerseBeliefGrid::FindPath(int32 From, int32 To) const
{
	TArray<int32> Path;
	if (!Cells.IsValidIndex(From) || !Cells.IsValidIndex(To) || !bCellActive[From] || !bCellActive[To])
	{
		return Path;
	}
	TArray<int32> Parent;
	Parent.Init(INDEX_NONE, Cells.Num());
	TArray<int32> Queue;
	Queue.Add(From);
	Parent[From] = From;
	for (int32 Head = 0; Head < Queue.Num(); ++Head)
	{
		const int32 Cell = Queue[Head];
		if (Cell == To)
		{
			break;
		}
		for (int32 Edge = NeighbourStart[Cell]; Edge < NeighbourStart[Cell + 1]; ++Edge)
		{
			const FNeighbour& Neighbour = Neighbours[Edge];
			if (Neighbour.bActive && Parent[Neighbour.Cell] == INDEX_NONE)
			{
				Parent[Neighbour.Cell] = Cell;
				Queue.Add(Neighbour.Cell);
			}
		}
	}
	if (Parent[To] == INDEX_NONE)
	{
		return Path;
	}
	for (int32 Cell = To; Cell != From; Cell = Parent[Cell])
	{
		Path.Add(Cell);
	}
	Path.Add(From);
	Algo::Reverse(Path);
	return Path;
}

uint32 FVerseBeliefGrid::HashMass() const
{
	return FCrc::MemCrc32(P.GetData(), P.Num() * sizeof(float));
}

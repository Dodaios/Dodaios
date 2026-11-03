#include "Belief/VerseBeliefGrid.h"

#include "Algo/Reverse.h"
#include "Math/VectorRegister.h"
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
	FBox CentreBox(ForceInit);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		CentreBox += Centres[Cell];
	}
	MomentOrigin = Num > 0 ? CentreBox.GetCenter() : FVector::ZeroVector;
	CellMoment.SetNumUninitialized(4 * Num);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const FVector C = (Centres[Cell] - MomentOrigin) / 100.0;
		CellMoment[4 * Cell + 0] = float(C.X);
		CellMoment[4 * Cell + 1] = float(C.Y);
		CellMoment[4 * Cell + 2] = float(C.Z);
		CellMoment[4 * Cell + 3] = float(C.X * C.X + C.Y * C.Y + C.Z * C.Z);
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
	// Padded disc layout: Reach zero columns and rows around every level, so no disc reaches past it.
	DiscPadWidth = ColumnSpan.X + 2 * Reach;
	const int32 DiscPadHeight = ColumnSpan.Y + 2 * Reach;
	DiscPadSize = Num > 0 ? LevelCount * DiscPadWidth * DiscPadHeight : 0;
	CellDiscPad.SetNumUninitialized(Num);
	DiscPadCell.Init(INDEX_NONE, DiscPadSize);
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		const FVerseBeliefCellDesc& Desc = Cells[Cell];
		const int32 Index = (int32(Desc.Level) * DiscPadHeight + (Desc.Column.Y - MinColumn.Y + Reach)) * DiscPadWidth +
			(Desc.Column.X - MinColumn.X + Reach);
		CellDiscPad[Cell] = Index;
		DiscPadCell[Index] = Cell;
	}
	DiscPadMass.Init(0.f, DiscPadSize);
	DiscPadSum.Init(0.f, DiscPadSize);
	DiscPadMask.Init(0.f, DiscPadSize);
	for (TArray<float>& Rows : DiscPadRows)
	{
		Rows.Init(0.f, DiscPadSize);
	}

	bCellActive.Init(1, Num);
	RateSum.Init(0.f, Num);
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
	bMomentumWeightsValid = false;
	ActiveMaskF.SetNumUninitialized(Num);
	ActiveCount = 0;
	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		DiscPadMask[CellDiscPad[Cell]] = bCellActive[Cell] ? 1.f : 0.f;
		ActiveMaskF[Cell] = bCellActive[Cell] ? 1.f : 0.f;
		ActiveCount += bCellActive[Cell] ? 1 : 0;
	}
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

void FVerseBeliefGrid::RefreshMomentumWeights(const FVector2f& Dir)
{
	// The momentum split depends only on the direction and the edges: computed once per sighting
	// direction, not per step. Weight per edge: cos^Exponent x rate, normalised per source cell.
	bMomentumWeightsValid = true;
	MomentumWeightsDir = Dir;
	const int32 Size = DenseSize;
	TArray<float> Sum;
	Sum.Init(0.f, Size);
	for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
	{
		const FVector2f Axis = FVector2f(float(EightOffsets[DirIndex].X), float(EightOffsets[DirIndex].Y)).GetSafeNormal();
		const float C = FastPowCos(FVector2f::DotProduct(Axis, Dir), Tuning.MomentumExponent);
		MomentumCos[DirIndex] = C;
		if (C <= 0.f)
		{
			continue;
		}
		const float* Rate = DenseRate[DirIndex].GetData();
		for (int32 Index = 0; Index < Size; ++Index)
		{
			Sum[Index] += C * Rate[Index];
		}
	}
	const int32 Links = LinkFrom.Num();
	TArray<float> LinkCos;
	LinkCos.SetNumUninitialized(Links);
	for (int32 Link = 0; Link < Links; ++Link)
	{
		LinkCos[Link] = FastPowCos(FVector2f::DotProduct(LinkDirs[Link], Dir), Tuning.MomentumExponent);
		Sum[CellDense[LinkFrom[Link]]] += LinkCos[Link] * LinkRate[Link];
	}
	DenseHasAdvect.SetNumUninitialized(Size);
	for (int32 Index = 0; Index < Size; ++Index)
	{
		DenseHasAdvect[Index] = Sum[Index] > 0.f ? 1 : 0;
		Sum[Index] = Sum[Index] > 0.f ? 1.f / Sum[Index] : 0.f;
	}
	for (int32 DirIndex = 0; DirIndex < 8; ++DirIndex)
	{
		const float C = MomentumCos[DirIndex];
		if (C <= 0.f)
		{
			DenseAdvectWeight[DirIndex].Reset();
			continue;
		}
		DenseAdvectWeight[DirIndex].SetNumUninitialized(Size);
		const float* Rate = DenseRate[DirIndex].GetData();
		float* Weight = DenseAdvectWeight[DirIndex].GetData();
		for (int32 Index = 0; Index < Size; ++Index)
		{
			Weight[Index] = C * Rate[Index] * Sum[Index];
		}
	}
	LinkAdvectWeight.SetNumUninitialized(Links);
	for (int32 Link = 0; Link < Links; ++Link)
	{
		LinkAdvectWeight[Link] = LinkCos[Link] * LinkRate[Link] * Sum[CellDense[LinkFrom[Link]]];
	}
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
	if (bAdvect && (!bMomentumWeightsValid || MomentumDir != MomentumWeightsDir))
	{
		RefreshMomentumWeights(MomentumDir);
	}

	const int32 Num = Cells.Num();
	const int32 Size = DenseSize;
	float* Out = DenseOut.GetData();
	float* Diffuse = DenseDiffuse.GetData();
	float* Advect = DenseAdvect.GetData();
	FMemory::Memzero(Out, sizeof(float) * Size);
	FMemory::Memzero(Diffuse, sizeof(float) * Size);
	if (bAdvect)
	{
		FMemory::Memzero(Advect, sizeof(float) * Size);
	}

	// Per cell: what stays, the diffusion scale and the advected mass.
	const float MaxDiffusion = Tuning.MaxDiffusionFraction;
	const uint8* HasAdvect = bAdvect ? DenseHasAdvect.GetData() : nullptr;
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
		if (HasAdvect && HasAdvect[Dense])
		{
			const float Moved = M * MomentumCellFraction;
			Kept -= Moved;
			Advect[Dense] = Moved;
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
		int32 Index = Begin;
		if (bAdvect && MomentumCos[DirIndex] > 0.f)
		{
			const float* Weight = DenseAdvectWeight[DirIndex].GetData();
			for (; Index + 4 <= End; Index += 4)
			{
				const VectorRegister4Float Flow = VectorAdd(VectorMultiply(VectorLoad(Diffuse + Index), VectorLoad(RateBias + Index)),
					VectorMultiply(VectorLoad(Advect + Index), VectorLoad(Weight + Index)));
				VectorStore(VectorAdd(VectorLoad(Target + Index), Flow), Target + Index);
			}
			for (; Index < End; ++Index)
			{
				Target[Index] += Diffuse[Index] * RateBias[Index] + Advect[Index] * Weight[Index];
			}
		}
		else
		{
			for (; Index + 4 <= End; Index += 4)
			{
				const VectorRegister4Float Flow = VectorMultiply(VectorLoad(Diffuse + Index), VectorLoad(RateBias + Index));
				VectorStore(VectorAdd(VectorLoad(Target + Index), Flow), Target + Index);
			}
			for (; Index < End; ++Index)
			{
				Target[Index] += Diffuse[Index] * RateBias[Index];
			}
		}
	}
	const int32 Links = LinkFrom.Num();
	for (int32 Link = 0; Link < Links; ++Link)
	{
		const int32 From = CellDense[LinkFrom[Link]];
		float Flow = Diffuse[From] * LinkRateBias[Link];
		if (bAdvect)
		{
			Flow += Advect[From] * LinkAdvectWeight[Link];
		}
		Out[CellDense[LinkTo[Link]]] += Flow;
	}

	for (int32 Cell = 0; Cell < Num; ++Cell)
	{
		P[Cell] = Out[CellDense[Cell]];
	}
}

float FVerseBeliefGrid::ClearPd(int32 Cell, const FVector& Eye) const
{
	const float DistM = float(FVector::Dist(Eye, GetCellCentre(Cell)) / 100.0);
	float Pd = Tuning.ClearNearPd;
	if (DistM > Tuning.ClearNearM)
	{
		const float Alpha = FMath::Clamp((DistM - Tuning.ClearNearM) / FMath::Max(1.f, Tuning.ClearFarM - Tuning.ClearNearM), 0.f, 1.f);
		Pd = FMath::Lerp(Tuning.ClearNearPd, Tuning.ClearFarPd, Alpha);
	}
	return Pd * FMath::Clamp(Cells[Cell].Visibility, 0.f, 1.f);
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
		P[Cell] *= 1.f - ClearPd(Cell, Eye);
		LastClearedS[Cell] = NowS;
	}
}

void FVerseBeliefGrid::Clear(const FVector& Eye, TConstArrayView<int32> VisibleCells, float NowS)
{
	if (bOpponentDead)
	{
		return;
	}
	for (const int32 Cell : VisibleCells)
	{
		if (!bCellActive.IsValidIndex(Cell) || !bCellActive[Cell])
		{
			continue;
		}
		P[Cell] *= 1.f - ClearPd(Cell, Eye);
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
	const int32 Active = ActiveCount;
	if (Active == 0)
	{
		return;
	}
	// Sum of active mass: four double accumulators, branch-free on the active mask.
	float* Mass = P.GetData();
	const float* MaskF = ActiveMaskF.GetData();
	double Sums[4] = {0.0, 0.0, 0.0, 0.0};
	int32 Cell = 0;
	for (; Cell + 4 <= Num; Cell += 4)
	{
		Sums[0] += double(Mass[Cell] * MaskF[Cell]);
		Sums[1] += double(Mass[Cell + 1] * MaskF[Cell + 1]);
		Sums[2] += double(Mass[Cell + 2] * MaskF[Cell + 2]);
		Sums[3] += double(Mass[Cell + 3] * MaskF[Cell + 3]);
	}
	for (; Cell < Num; ++Cell)
	{
		Sums[0] += double(Mass[Cell] * MaskF[Cell]);
	}
	const double Sum = (Sums[0] + Sums[1]) + (Sums[2] + Sums[3]);
	if (!(Sum > 0.0) || !FMath::IsFinite(Sum))
	{
		ResetUniform();
		return;
	}
	// Prior: 90 % learned heatmap (when there is one) plus 10 % uniform, so it is never 0.
	double PriorSum = 0.0;
	if (Prior.Num() == Num)
	{
		for (int32 Index = 0; Index < Num; ++Index)
		{
			PriorSum += bCellActive[Index] ? FMath::Max(0.f, Prior[Index]) : 0.f;
		}
	}
	const bool bHeat = PriorSum > 0.0;
	const double Mix = FMath::Clamp(double(Tuning.PriorMix), 1e-6, 1.0);
	const float Keep = float((1.0 - Mix) / Sum);
	const float Uniform = float(Mix * (bHeat ? 0.1 : 1.0) / double(Active));
	if (bHeat)
	{
		const double HeatScale = Mix * 0.9 / PriorSum;
		for (int32 Index = 0; Index < Num; ++Index)
		{
			P[Index] = bCellActive[Index] ? P[Index] * Keep + Uniform + float(HeatScale * FMath::Max(0.f, Prior[Index])) : 0.f;
		}
		return;
	}
	// (m x Keep + Uniform) x mask: exact for the 0 / 1 mask, inactive cells stay 0.
	const VectorRegister4Float KeepV = VectorSetFloat1(Keep);
	const VectorRegister4Float UniformV = VectorSetFloat1(Uniform);
	Cell = 0;
	for (; Cell + 4 <= Num; Cell += 4)
	{
		const VectorRegister4Float Value = VectorAdd(VectorMultiply(VectorLoad(Mass + Cell), KeepV), UniformV);
		VectorStore(VectorMultiply(Value, VectorLoad(MaskF + Cell)), Mass + Cell);
	}
	for (; Cell < Num; ++Cell)
	{
		Mass[Cell] = (Mass[Cell] * Keep + Uniform) * MaskF[Cell];
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
	if (Num == 0 || DiscPadSize == 0)
	{
		return Out;
	}

	// Pass 1 over the cells: scatter the mass into the padded disc layout, and a histogram by float
	// exponent (one bucket per factor of 2) holding the mass and the moment sums (x, y, z, x^2+y^2+z^2
	// in metres from the grid middle, one vector) of each bucket. Four interleaved banks keep
	// consecutive cells (usually the same bucket) off one dependency chain.
	constexpr int32 Banks = 4;
	constexpr int32 Buckets = 64;
	constexpr int32 ExpBase = 127 - Buckets + 1;
	alignas(16) float HistMoments[Banks * Buckets * 4];
	float HistMass[Banks * Buckets];
	FMemory::Memzero(HistMoments, sizeof(HistMoments));
	FMemory::Memzero(HistMass, sizeof(HistMass));
	{
		const float* Mass = P.GetData();
		const float* Moment = CellMoment.GetData();
		float* PadOut = DiscPadMass.GetData();
		const int32* PadIndex = CellDiscPad.GetData();
		for (int32 Cell = 0; Cell < Num; ++Cell)
		{
			const float Value = Mass[Cell];
			PadOut[PadIndex[Cell]] = Value;
			if (!(Value > 0.f))
			{
				continue;
			}
			uint32 Bits;
			FMemory::Memcpy(&Bits, &Value, sizeof(Bits));
			const int32 Bucket = FMath::Clamp(int32((Bits >> 23) & 0xFFu) - ExpBase, 0, Buckets - 1);
			const int32 Slot = (Cell & (Banks - 1)) * Buckets + Bucket;
			HistMass[Slot] += Value;
			float* Acc = HistMoments + 4 * Slot;
			VectorStoreAligned(VectorAdd(VectorLoadAligned(Acc), VectorMultiply(VectorSetFloat1(Value), VectorLoad(Moment + 4 * Cell))), Acc);
		}
	}
	double BucketMass[Buckets] = {};
	double Total = 0.0;
	for (int32 Bucket = 0; Bucket < Buckets; ++Bucket)
	{
		for (int32 Bank = 0; Bank < Banks; ++Bank)
		{
			BucketMass[Bucket] += HistMass[Bank * Buckets + Bucket];
		}
		Total += BucketMass[Bucket];
	}
	if (!(Total > 0.0))
	{
		return Out;
	}

	// Spread: the buckets (from the top) that hold 90 % of the mass.
	{
		double W = 0.0;
		double Sx = 0.0;
		double Sy = 0.0;
		double Sz = 0.0;
		double Sq = 0.0;
		for (int32 Bucket = Buckets - 1; Bucket >= 0 && W < 0.9 * Total; --Bucket)
		{
			for (int32 Bank = 0; Bank < Banks; ++Bank)
			{
				const int32 Slot = Bank * Buckets + Bucket;
				W += HistMass[Slot];
				Sx += HistMoments[4 * Slot + 0];
				Sy += HistMoments[4 * Slot + 1];
				Sz += HistMoments[4 * Slot + 2];
				Sq += HistMoments[4 * Slot + 3];
			}
		}
		if (W > 0.0)
		{
			const double Mx = Sx / W;
			const double My = Sy / W;
			const double Mz = Sz / W;
			const double Var = FMath::Max(0.0, Sq / W - (Mx * Mx + My * My + Mz * Mz));
			Out.SpreadM = float(FMath::Sqrt(Var));
		}
	}

	// TopCluster (bot.md 4.3): the disc sum of every cell, from horizontal box sums of the disc's row
	// half-widths, then the active cell with the largest sum (ties: the lowest padded index).
	const int32 Reach = DiscHalfWidth.Num() / 2;
	const int32 Width = DiscPadWidth;
	const int32 Size = DiscPadSize;
	const float* Pad = DiscPadMass.GetData();
	int32 MaxHalf = 0;
	for (const int32 Half : DiscHalfWidth)
	{
		MaxHalf = FMath::Max(MaxHalf, Half);
	}
	MaxHalf = FMath::Min(MaxHalf, 7);
	const float* Rows[8] = {Pad, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr, nullptr};
	for (int32 Half = 1; Half <= MaxHalf; ++Half)
	{
		const float* Prev = Rows[Half - 1];
		float* Cur = DiscPadRows[Half].GetData();
		const int32 End = Size - Reach;
		int32 Index = Reach;
		for (; Index + 4 <= End; Index += 4)
		{
			const VectorRegister4Float Sides = VectorAdd(VectorLoad(Pad + Index - Half), VectorLoad(Pad + Index + Half));
			VectorStore(VectorAdd(VectorLoad(Prev + Index), Sides), Cur + Index);
		}
		for (; Index < End; ++Index)
		{
			Cur[Index] = Prev[Index] + (Pad[Index - Half] + Pad[Index + Half]);
		}
		Rows[Half] = Cur;
	}
	const float* TermRows[17];
	int32 TermOffsets[17];
	int32 NumTerms = 0;
	for (int32 Dy = -Reach; Dy <= Reach && NumTerms < 17; ++Dy)
	{
		const int32 Half = DiscHalfWidth[Dy + Reach];
		if (Half >= 0 && Half <= MaxHalf)
		{
			TermRows[NumTerms] = Rows[Half];
			TermOffsets[NumTerms] = Dy * Width;
			++NumTerms;
		}
	}
	if (NumTerms == 0)
	{
		return Out;
	}
	float* Score = DiscPadSum.GetData();
	const float* Mask = DiscPadMask.GetData();
	const int32 Begin = Reach * Width;
	const int32 End = Size - Reach * Width;
	const VectorRegister4Float One = VectorSetFloat1(1.f);
	VectorRegister4Float BestLanes = VectorSetFloat1(-2.f);
	int32 Index = Begin;
	for (; Index + 4 <= End; Index += 4)
	{
		VectorRegister4Float Acc = VectorLoad(TermRows[0] + Index + TermOffsets[0]);
		for (int32 Term = 1; Term < NumTerms; ++Term)
		{
			Acc = VectorAdd(Acc, VectorLoad(TermRows[Term] + Index + TermOffsets[Term]));
		}
		const VectorRegister4Float M = VectorLoad(Mask + Index);
		// Inactive or no cell: -1, below every real disc sum.
		const VectorRegister4Float Value = VectorAdd(VectorMultiply(Acc, M), VectorSubtract(M, One));
		VectorStore(Value, Score + Index);
		BestLanes = VectorMax(BestLanes, Value);
	}
	float Best = -2.f;
	for (; Index < End; ++Index)
	{
		float Acc = TermRows[0][Index + TermOffsets[0]];
		for (int32 Term = 1; Term < NumTerms; ++Term)
		{
			Acc += TermRows[Term][Index + TermOffsets[Term]];
		}
		const float Value = Acc * Mask[Index] + (Mask[Index] - 1.f);
		Score[Index] = Value;
		Best = FMath::Max(Best, Value);
	}
	float Lanes[4];
	VectorStore(BestLanes, Lanes);
	Best = FMath::Max(FMath::Max(Best, FMath::Max(Lanes[0], Lanes[1])), FMath::Max(Lanes[2], Lanes[3]));
	if (Best < 0.f)
	{
		return Out;
	}
	int32 BestCell = INDEX_NONE;
	for (Index = Begin; Index < End; ++Index)
	{
		if (Score[Index] == Best)
		{
			BestCell = DiscPadCell[Index];
			break;
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

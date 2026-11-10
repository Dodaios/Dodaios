#include "Brain/VerseBotGridBelief.h"

#include "Brain/VerseBotWorldQueries.h"

namespace VerseBotGridBeliefPrivate
{
	/** A cell counts toward a query point when its pelvis is within this height of it, cm. */
	constexpr float LevelReachCm = 250.f;
	/** Seen or heard support older than this no longer authorises a shot without sight, s. */
	constexpr float SupportedMaxAgeS = 8.f;
	/** Top cells are at least this far apart, so they name different places, cm. */
	constexpr float TopSpacingCm = 300.f;
	/** Candidate pool for the top cells. */
	constexpr int32 TopPool = 96;
	/** A sighting's velocity stays the belief's velocity this long, s. */
	constexpr float VelocityHoldS = 2.f;
}

bool FVerseBotBeliefSight::TestSight(const FVector& Eye, const FVector& Target) const
{
	return Queries && Queries->TestSight(Eye, Target);
}

FVerseBotGridBelief::FVerseBotGridBelief(const FVerseBeliefGridSource& InSource, const FVerseBeliefMapConfig& InConfig, IVerseBotWorldQueries& Queries)
	: Source(InSource)
	, Config(InConfig)
	, Sight(Queries)
{
	Reset();
}

void FVerseBotGridBelief::Reset()
{
	FVerseBeliefWorld World;
	World.Sight = &Sight;
	Map.Initialize(Source, Config, World);
	bWasDead = false;
	Summarise();
}

void FVerseBotGridBelief::OnOwnDeath(float InNowS)
{
	NowS = InNowS;
	Map.OnOwnDeath(InNowS);
	Summarise();
}

void FVerseBotGridBelief::Step(const FVersePerceptFrame& Frame, float DtS, const FVerseBotMatchMemory* Memory, TConstArrayView<FVector> Spawns)
{
	NowS = float(Frame.ServerTimeMs) / 1000.f;
	FVerseBeliefWorld World;
	World.Sight = &Sight;
	Map.ApplyFrame(Frame, World);
	Summarise();
}

void FVerseBotGridBelief::NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState)
{
	Map.OnOwnPieceAction(PieceIndex, NewState, NowS);
}

EVersePieceState FVerseBotGridBelief::GetPieceBelief(uint16 PieceIndex) const
{
	return Map.GetPieces().GetBelievedState(PieceIndex);
}

float FVerseBotGridBelief::SumWithin(const FVector& Location, float RadiusCm, bool bSupportedOnly) const
{
	using namespace VerseBotGridBeliefPrivate;
	const FVerseBeliefGrid& Grid = Map.GetGrid();
	if (Grid.NumCells() == 0 || Grid.IsOpponentDead())
	{
		return 0.f;
	}
	const float CellCm = Grid.GetCellSizeCm();
	const int32 Reach = FMath::CeilToInt32(RadiusCm / CellCm);
	const FIntPoint Centre = Grid.ColumnOf(Location);
	const double R2 = double(RadiusCm) * double(RadiusCm);
	double Sum = 0.0;
	for (int32 Dx = -Reach; Dx <= Reach; ++Dx)
	{
		for (int32 Dy = -Reach; Dy <= Reach; ++Dy)
		{
			for (int32 Level = 0; Level < 3; ++Level)
			{
				const int32 Cell = Grid.FindCell(Centre + FIntPoint(Dx, Dy), EVerseArenaLevel(Level));
				if (Cell == INDEX_NONE)
				{
					continue;
				}
				const FVector C = Grid.GetCellCentre(Cell);
				if (FVector::DistSquared2D(C, Location) > R2 || FMath::Abs(float(C.Z) + PelvisAboveFloorCm - float(Location.Z)) > LevelReachCm)
				{
					continue;
				}
				if (bSupportedOnly)
				{
					const EVerseBeliefSupport Kind = Grid.GetLastSupportKind(Cell);
					if ((Kind != EVerseBeliefSupport::Seen && Kind != EVerseBeliefSupport::Heard) || NowS - Grid.GetLastSupportS(Cell) > SupportedMaxAgeS)
					{
						continue;
					}
				}
				Sum += Grid.GetMass(Cell);
			}
		}
	}
	return float(Sum);
}

float FVerseBotGridBelief::MassWithin(const FVector& Location, float RadiusCm) const
{
	return SumWithin(Location, RadiusCm, false);
}

float FVerseBotGridBelief::SupportedMassWithin(const FVector& Location, float RadiusCm) const
{
	return SumWithin(Location, RadiusCm, true);
}

void FVerseBotGridBelief::TopCells(int32 N, TArray<FVector>& Out) const
{
	using namespace VerseBotGridBeliefPrivate;
	Out.Reset();
	const FVerseBeliefGrid& Grid = Map.GetGrid();
	if (N <= 0 || Grid.NumCells() == 0 || Grid.IsOpponentDead())
	{
		return;
	}
	// The heaviest cells, then greedy spacing so every returned point is a different place.
	TArray<int32> Pool;
	Pool.Reserve(Grid.NumCells());
	for (int32 Cell = 0; Cell < Grid.NumCells(); ++Cell)
	{
		if (Grid.IsActive(Cell) && Grid.GetMass(Cell) > 0.f)
		{
			Pool.Add(Cell);
		}
	}
	const int32 Keep = FMath::Min(TopPool, Pool.Num());
	// Stable on equal mass: the lower cell index first (B5, deterministic).
	Pool.Sort([&Grid](int32 A, int32 B)
	{
		const float MA = Grid.GetMass(A);
		const float MB = Grid.GetMass(B);
		return MA != MB ? MA > MB : A < B;
	});
	const double Spacing2 = double(TopSpacingCm) * double(TopSpacingCm);
	for (int32 I = 0; I < Keep && Out.Num() < N; ++I)
	{
		const FVector C = Grid.GetCellCentre(Pool[I]) + FVector(0, 0, PelvisAboveFloorCm);
		if (Out.ContainsByPredicate([&C, Spacing2](const FVector& P) { return FVector::DistSquared(P, C) < Spacing2; }))
		{
			continue;
		}
		Out.Add(C);
	}
}

void FVerseBotGridBelief::Summarise()
{
	using namespace VerseBotGridBeliefPrivate;
	const FVerseBeliefDerived& D = Map.GetDerived();
	const FVerseOpponentEstimate& O = Map.GetOpponent();
	FVerseBotBeliefSummary S;
	const bool bDead = Map.GetGrid().IsOpponentDead();
	S.State = bDead ? EVerseBeliefState::Dead : D.State;
	S.TopCenter = D.TopCluster.Centre + FVector(0, 0, PelvisAboveFloorCm);
	S.TopLevel = D.TopCluster.Level;
	S.Confidence = bDead ? 0.f : D.Confidence;
	S.SupportAgeS = D.SupportAgeS;
	S.bPriorOnly = D.SupportKind != EVerseBeliefSupport::Seen && D.SupportKind != EVerseBeliefSupport::Heard;
	S.SpreadCm = D.SpreadM * 100.f;
	S.FacingYawDeg = O.LastSeenYawDeg;
	S.FacingAgeS = O.FacingAgeS(NowS);
	S.bReloadNoticed = O.bHeardReload;
	S.SinceSightingS = O.LastSeenYawAtS >= 0.f ? FMath::Max(NowS - O.LastSeenYawAtS, 0.f) : 1.0e6f;
	S.Velocity = S.SinceSightingS <= VelocityHoldS ? O.LastSeenVelocity : FVector::ZeroVector;
	S.LastSeenLocation = O.LastSeenLocation;
	S.OpponentHealthFrac = O.MaxHealth > 0.f ? FMath::Clamp(O.EstimatedHealth(NowS) / O.MaxHealth, 0.f, 1.f) : 1.f;
	S.OpponentShotsSinceReload = O.ShotsSinceReload;
	Cached = S;
	bWasDead = bDead;
}

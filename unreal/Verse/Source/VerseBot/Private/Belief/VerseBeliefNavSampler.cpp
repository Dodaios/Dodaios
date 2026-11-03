#include "Belief/VerseBeliefNavSampler.h"

#include "AI/Navigation/NavigationDataInterface.h"
#include "AI/Navigation/NavigationTypes.h"
#include "AI/NavigationSystemBase.h"
#include "Engine/World.h"

bool FVerseBeliefNavSampler::Build(const UWorld& World, const FVerseBeliefNavSettings& Settings, FVerseBeliefGridSource& OutSource)
{
	OutSource = FVerseBeliefGridSource();
	const UNavigationSystemBase* NavSys = World.GetNavigationSystem();
	const INavigationDataInterface* Nav = NavSys ? NavSys->GetMainNavData() : nullptr;
	return Nav ? Build(*Nav, Settings, OutSource) : false;
}

bool FVerseBeliefNavSampler::Build(const INavigationDataInterface& Nav, const FVerseBeliefNavSettings& Settings, FVerseBeliefGridSource& OutSource)
{
	OutSource = FVerseBeliefGridSource();
	if (!Settings.ArenaBox.IsValid)
	{
		return false;
	}
	const float Cell = FMath::Max(10.f, Settings.CellSizeCm);
	OutSource.CellSizeCm = Cell;
	OutSource.Origin = FVector2D(Settings.ArenaBox.Min.X + 0.5 * Cell, Settings.ArenaBox.Min.Y + 0.5 * Cell);
	const int32 Nx = FMath::Max(1, FMath::FloorToInt((Settings.ArenaBox.Max.X - Settings.ArenaBox.Min.X) / Cell));
	const int32 Ny = FMath::Max(1, FMath::FloorToInt((Settings.ArenaBox.Max.Y - Settings.ArenaBox.Min.Y) / Cell));
	const FVector Extent(Settings.ProjectHalfXYCm, Settings.ProjectHalfXYCm, Settings.ProjectHalfZCm);

	TArray<FNavLocation> Locations;
	TMap<FIntVector, int32> Lookup;
	for (int32 X = 0; X < Nx; ++X)
	{
		for (int32 Y = 0; Y < Ny; ++Y)
		{
			TArray<float, TInlineAllocator<3>> Floors;
			for (int32 Level = 0; Level < 3; ++Level)
			{
				const FVector Probe(OutSource.Origin.X + X * Cell, OutSource.Origin.Y + Y * Cell, Settings.LevelProbeZCm[Level]);
				FNavLocation Hit;
				if (!Nav.ProjectPoint(Probe, Hit, Extent))
				{
					continue;
				}
				if (Floors.ContainsByPredicate([&](float Z) { return FMath::Abs(Z - Hit.Location.Z) < Settings.SameFloorCm; }))
				{
					continue;
				}
				Floors.Add(float(Hit.Location.Z));
				FVerseBeliefCellDesc& Desc = OutSource.Cells.AddDefaulted_GetRef();
				Desc.Column = FIntPoint(X, Y);
				Desc.FloorZ = float(Hit.Location.Z);
				Desc.Level = EVerseArenaLevel(Level);
				Desc.Visibility = Settings.VisibilityAt ? Settings.VisibilityAt(Hit.Location) : 1.f;
				Desc.Zone = Settings.ZoneAt ? Settings.ZoneAt(Hit.Location) : 255;
				Lookup.Add(FIntVector(X, Y, Level), OutSource.Cells.Num() - 1);
				Locations.Add(Hit);
			}
		}
	}

	// Piece gates: catwalk cells go with their piece, breach openings appear when it opens.
	TArray<uint8> Unsampled;
	Unsampled.Init(0, OutSource.Cells.Num());
	for (const FVerseBeliefNavSettings::FPieceFootprint& Footprint : Settings.PieceFootprints)
	{
		if (!Footprint.Bounds.IsValid || Footprint.Piece == INDEX_NONE || Footprint.Gate == EVerseBeliefGate::Always)
		{
			continue;
		}
		const int32 X0 = FMath::Max(0, FMath::CeilToInt((Footprint.Bounds.Min.X - OutSource.Origin.X) / Cell));
		const int32 X1 = FMath::Min(Nx - 1, FMath::FloorToInt((Footprint.Bounds.Max.X - OutSource.Origin.X) / Cell));
		const int32 Y0 = FMath::Max(0, FMath::CeilToInt((Footprint.Bounds.Min.Y - OutSource.Origin.Y) / Cell));
		const int32 Y1 = FMath::Min(Ny - 1, FMath::FloorToInt((Footprint.Bounds.Max.Y - OutSource.Origin.Y) / Cell));
		for (int32 X = X0; X <= X1; ++X)
		{
			for (int32 Y = Y0; Y <= Y1; ++Y)
			{
				if (Footprint.Gate == EVerseBeliefGate::WhenStanding)
				{
					for (int32 Level = 0; Level < 3; ++Level)
					{
						const int32* Found = Lookup.Find(FIntVector(X, Y, Level));
						if (!Found)
						{
							continue;
						}
						FVerseBeliefCellDesc& Desc = OutSource.Cells[*Found];
						if (Desc.FloorZ >= Footprint.Bounds.Min.Z - Settings.SameFloorCm &&
							Desc.FloorZ <= Footprint.Bounds.Max.Z + Settings.SameFloorCm)
						{
							Desc.Gate = EVerseBeliefGate::WhenStanding;
							Desc.GatePiece = Footprint.Piece;
						}
					}
					continue;
				}
				const FIntVector Key(X, Y, int32(Footprint.Level));
				if (const int32* Found = Lookup.Find(Key))
				{
					OutSource.Cells[*Found].Gate = EVerseBeliefGate::WhenOpen;
					OutSource.Cells[*Found].GatePiece = Footprint.Piece;
					continue;
				}
				const FVector Floor(OutSource.Origin.X + X * Cell, OutSource.Origin.Y + Y * Cell, Footprint.Bounds.Min.Z);
				FVerseBeliefCellDesc& Desc = OutSource.Cells.AddDefaulted_GetRef();
				Desc.Column = FIntPoint(X, Y);
				Desc.FloorZ = float(Floor.Z);
				Desc.Level = Footprint.Level;
				Desc.Visibility = Settings.VisibilityAt ? Settings.VisibilityAt(Floor) : 1.f;
				Desc.Zone = Settings.ZoneAt ? Settings.ZoneAt(Floor) : 255;
				Desc.Gate = EVerseBeliefGate::WhenOpen;
				Desc.GatePiece = Footprint.Piece;
				Lookup.Add(Key, OutSource.Cells.Num() - 1);
				Locations.Add(FNavLocation(Floor));
				Unsampled.Add(1);
			}
		}
	}

	for (const FVerseBeliefNavSettings::FLink& Link : Settings.Links)
	{
		const int32* From = Lookup.Find(FIntVector(Link.FromColumn.X, Link.FromColumn.Y, int32(Link.FromLevel)));
		const int32* To = Lookup.Find(FIntVector(Link.ToColumn.X, Link.ToColumn.Y, int32(Link.ToLevel)));
		if (!From || !To)
		{
			continue;
		}
		FVerseBeliefLinkDesc& Desc = OutSource.Links.AddDefaulted_GetRef();
		Desc.From = *From;
		Desc.To = *To;
		Desc.TraversalS = Link.TraversalS;
		Desc.bBidirectional = Link.bBidirectional;
		Desc.Kind = Link.Kind;
		Desc.Gate = Link.Gate;
		Desc.GatePiece = Link.GatePiece;
	}

	// Connectivity of same-level neighbours: a move along the surface must arrive.
	const INavigationDataInterface* NavPtr = &Nav;
	TArray<FNavLocation> Captured = Locations;
	OutSource.AreNeighboursConnected = [NavPtr, Captured, Unsampled, Cell](int32 A, int32 B) {
		if (!Captured.IsValidIndex(A) || !Captured.IsValidIndex(B))
		{
			return false;
		}
		if (Unsampled[A] || Unsampled[B])
		{
			// An opening has no navmesh while the piece stands: a step of at most 60 cm joins it.
			return FMath::Abs(Captured[A].Location.Z - Captured[B].Location.Z) <= 60.f;
		}
		FNavLocation Reached;
		if (!NavPtr->FindMoveAlongSurface(Captured[A], Captured[B].Location, Reached))
		{
			return false;
		}
		return FVector::Dist2D(Reached.Location, Captured[B].Location) <= 0.25f * Cell &&
			FMath::Abs(Reached.Location.Z - Captured[B].Location.Z) <= 60.f;
	};
	return OutSource.Cells.Num() > 0;
}

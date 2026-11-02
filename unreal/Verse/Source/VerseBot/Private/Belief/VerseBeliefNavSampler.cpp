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
	OutSource.AreNeighboursConnected = [NavPtr, Captured, Cell](int32 A, int32 B) {
		if (!Captured.IsValidIndex(A) || !Captured.IsValidIndex(B))
		{
			return false;
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

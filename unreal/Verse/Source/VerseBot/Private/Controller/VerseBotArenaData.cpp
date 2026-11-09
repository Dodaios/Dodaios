#include "Controller/VerseBotArenaData.h"

#include "AI/Navigation/NavigationDataInterface.h"
#include "AI/NavigationSystemBase.h"
#include "Belief/VerseBeliefNavSampler.h"
#include "Brain/VerseBotBrainCore.h"
#include "Brain/VerseBotGridBelief.h"
#include "Controller/VerseBotEngineQueries.h"
#include "CollisionQueryParams.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerStart.h"
#include "NavigationSystem.h"
#include "Rules/VerseSpawnPoint.h"
#include "VerseCollision.h"
#include "VerseLog.h"

namespace VerseBotArenaDataPrivate
{
	/** Margin around the spawn points that still belongs to the arena, cm. */
	constexpr double ArenaMarginXYCm = 900.0;
	/** Height of the upper two levels above the floor (hangar: booth and shuttle roof, catwalks), cm. */
	constexpr float MidLevelCm = 300.f;
	constexpr float UpperLevelCm = 600.f;
	/** Fewer cells than this is a nav mesh still building (the hangar floor alone has thousands). */
	constexpr int32 MinCells = 400;
	constexpr double RetryS = 1.0;
	/** Cover probes: crouched and standing eye heights above the floor, reach of a wall, cm. */
	constexpr float LowProbeCm = 100.f;
	constexpr float HighProbeCm = 165.f;
	constexpr float CoverReachCm = 120.f;
	/** Sideways step that tests whether a cover run ends here (a peek edge), cm. */
	constexpr float EdgeStepCm = 150.f;
	/** The only channel arena data traces on: pawns ignore it (bot.md F1). */
	constexpr ECollisionChannel VerseSightChannel = VerseCollision::Sight;
	/** Cross-level joins: two ramp cells at most this far apart in height. */
	constexpr float StepUpCm = 60.f;

	struct FCacheEntry
	{
		TWeakObjectPtr<const UWorld> World;
		TSharedPtr<const FVerseBotArenaData> Data;
		double NextTryS = 0.0;
		int32 Attempts = 0;
	};

	TArray<FCacheEntry>& Cache()
	{
		static TArray<FCacheEntry> Entries;
		return Entries;
	}

	FCacheEntry& EntryFor(const UWorld& World)
	{
		TArray<FCacheEntry>& Entries = Cache();
		Entries.RemoveAll([](const FCacheEntry& E) { return !E.World.IsValid(); });
		for (FCacheEntry& E : Entries)
		{
			if (E.World.Get() == &World)
			{
				return E;
			}
		}
		FCacheEntry& E = Entries.AddDefaulted_GetRef();
		E.World = &World;
		return E;
	}

	void SpawnLocations(const UWorld& World, TArray<FVector>& Out)
	{
		Out.Reset();
		for (TActorIterator<AVerseSpawnPoint> It(&World); It; ++It)
		{
			Out.Add(It->GetActorLocation());
		}
		if (Out.Num() == 0)
		{
			for (TActorIterator<APlayerStart> It(&World); It; ++It)
			{
				Out.Add(It->GetActorLocation());
			}
		}
	}

	bool Blocked(const UWorld& World, const FVector& From, const FVector& To)
	{
		// VerseSight only: pawns ignore the channel, so this reads static geometry and nothing else.
		FCollisionQueryParams Params(SCENE_QUERY_STAT(VerseBotArenaData), false);
		FHitResult Hit;
		return World.LineTraceSingleByChannel(Hit, From, To, VerseSightChannel, Params);
	}

	/** The cover a floor point has: the direction it protects against and its height. */
	bool CoverAt(const UWorld& World, const FVector& Floor, FVector& OutFacing, bool& bOutHigh)
	{
		bool bFound = false;
		bOutHigh = false;
		for (int32 Dir = 0; Dir < 8; ++Dir)
		{
			const FVector D = FRotator(0.f, 45.f * float(Dir), 0.f).Vector();
			const FVector Low = Floor + FVector(0, 0, LowProbeCm);
			if (!Blocked(World, Low, Low + D * CoverReachCm))
			{
				continue;
			}
			const FVector High = Floor + FVector(0, 0, HighProbeCm);
			const bool bHigh = Blocked(World, High, High + D * CoverReachCm);
			// Axis directions first (walls are axis aligned), high cover over low.
			if (!bFound || (bHigh && !bOutHigh))
			{
				OutFacing = D;
				bOutHigh = bHigh;
				bFound = true;
			}
		}
		return bFound;
	}

	/** A cover run ends next to this point: one side along the wall has no wall any more. */
	bool IsEdge(const UWorld& World, const FVector& Floor, const FVector& Facing)
	{
		const FVector Side = FVector::CrossProduct(FVector::UpVector, Facing).GetSafeNormal();
		for (const float Sign : {1.f, -1.f})
		{
			const FVector Probe = Floor + Side * (Sign * EdgeStepCm) + FVector(0, 0, LowProbeCm);
			// The side step itself must be open floor (no wall in the way), and there no wall ahead.
			if (!Blocked(World, Floor + FVector(0, 0, LowProbeCm), Probe) && !Blocked(World, Probe, Probe + Facing * CoverReachCm))
			{
				return true;
			}
		}
		return false;
	}

	FVector CellWorld(const FVerseBeliefGridSource& Source, const FVerseBeliefCellDesc& Cell)
	{
		return FVector(Source.Origin.X + Cell.Column.X * Source.CellSizeCm, Source.Origin.Y + Cell.Column.Y * Source.CellSizeCm, Cell.FloorZ);
	}

	/**
	 * The sampler joins same-level neighbours only; ramps cross level bands, so join every pair of
	 * neighbouring cells on different levels that a move along the nav surface connects.
	 */
	void AddCrossLevelLinks(const INavigationDataInterface& Nav, FVerseBeliefGridSource& Source)
	{
		TMap<FIntVector, int32> Lookup;
		for (int32 I = 0; I < Source.Cells.Num(); ++I)
		{
			const FVerseBeliefCellDesc& C = Source.Cells[I];
			Lookup.Add(FIntVector(C.Column.X, C.Column.Y, int32(C.Level)), I);
		}
		const FVector Extent(30.f, 30.f, 80.f);
		const float Cell = Source.CellSizeCm;
		for (int32 I = 0; I < Source.Cells.Num(); ++I)
		{
			const FVerseBeliefCellDesc& A = Source.Cells[I];
			for (int32 Dx = -1; Dx <= 1; ++Dx)
			{
				for (int32 Dy = -1; Dy <= 1; ++Dy)
				{
					if (Dx == 0 && Dy == 0)
					{
						continue;
					}
					for (int32 Level = int32(A.Level) + 1; Level < 3; ++Level)
					{
						const int32* Other = Lookup.Find(FIntVector(A.Column.X + Dx, A.Column.Y + Dy, Level));
						if (!Other)
						{
							continue;
						}
						const FVerseBeliefCellDesc& B = Source.Cells[*Other];
						if (FMath::Abs(A.FloorZ - B.FloorZ) > StepUpCm)
						{
							continue;
						}
						FNavLocation From;
						if (!Nav.ProjectPoint(CellWorld(Source, A), From, Extent))
						{
							continue;
						}
						const FVector ToPoint = CellWorld(Source, B);
						FNavLocation Reached;
						if (!Nav.FindMoveAlongSurface(From, ToPoint, Reached) || FVector::Dist2D(Reached.Location, ToPoint) > 0.25f * Cell
							|| FMath::Abs(Reached.Location.Z - ToPoint.Z) > StepUpCm)
						{
							continue;
						}
						FVerseBeliefLinkDesc& Link = Source.Links.AddDefaulted_GetRef();
						Link.From = I;
						Link.To = *Other;
						Link.TraversalS = Cell / 450.f;
						Link.bBidirectional = true;
						Link.Kind = EVerseBeliefLinkKind::Stair;
					}
				}
			}
		}
	}

	/** Memoise the sampler's connectivity: every grid built from the source asks the same pairs. */
	void MemoiseConnectivity(FVerseBeliefGridSource& Source)
	{
		if (!Source.AreNeighboursConnected)
		{
			return;
		}
		TSharedRef<TFunction<bool(int32, int32)>> Inner = MakeShared<TFunction<bool(int32, int32)>>(MoveTemp(Source.AreNeighboursConnected));
		TSharedRef<TMap<uint64, bool>> Memo = MakeShared<TMap<uint64, bool>>();
		Source.AreNeighboursConnected = [Inner, Memo](int32 A, int32 B)
		{
			const uint64 Key = (uint64(uint32(A)) << 32) | uint64(uint32(B));
			if (const bool* Known = Memo->Find(Key))
			{
				return *Known;
			}
			const bool bConnected = (*Inner)(A, B);
			Memo->Add(Key, bConnected);
			return bConnected;
		};
	}

	/**
	 * Keep the cells a player can walk to: the components (8-neighbours on a level plus links) that
	 * hold a spawn point. The runtime nav mesh also covers box tops and closed rooms nobody can
	 * reach; belief mass there would never be cleared and the search would walk at it forever.
	 */
	int32 KeepReachableCells(FVerseBeliefGridSource& Source, TConstArrayView<FVector> Spawns)
	{
		const int32 Num = Source.Cells.Num();
		TMap<FIntVector, int32> Lookup;
		for (int32 I = 0; I < Num; ++I)
		{
			const FVerseBeliefCellDesc& C = Source.Cells[I];
			Lookup.Add(FIntVector(C.Column.X, C.Column.Y, int32(C.Level)), I);
		}
		TArray<TArray<int32>> LinksOf;
		LinksOf.SetNum(Num);
		for (const FVerseBeliefLinkDesc& Link : Source.Links)
		{
			if (Source.Cells.IsValidIndex(Link.From) && Source.Cells.IsValidIndex(Link.To))
			{
				LinksOf[Link.From].Add(Link.To);
				LinksOf[Link.To].Add(Link.From);
			}
		}
		// Seeds: the cell nearest each spawn (floor point).
		TArray<int32> Queue;
		TArray<uint8> Keep;
		Keep.Init(0, Num);
		for (const FVector& Spawn : Spawns)
		{
			int32 Best = INDEX_NONE;
			double BestD = 1.0e12;
			for (int32 I = 0; I < Num; ++I)
			{
				const double D = FVector::DistSquared(CellWorld(Source, Source.Cells[I]), Spawn);
				if (D < BestD)
				{
					BestD = D;
					Best = I;
				}
			}
			if (Best != INDEX_NONE && !Keep[Best])
			{
				Keep[Best] = 1;
				Queue.Add(Best);
			}
		}
		for (int32 Head = 0; Head < Queue.Num(); ++Head)
		{
			const int32 A = Queue[Head];
			const FVerseBeliefCellDesc& C = Source.Cells[A];
			auto Visit = [&](int32 B)
			{
				if (!Keep[B])
				{
					Keep[B] = 1;
					Queue.Add(B);
				}
			};
			for (int32 Dx = -1; Dx <= 1; ++Dx)
			{
				for (int32 Dy = -1; Dy <= 1; ++Dy)
				{
					const int32* B = (Dx || Dy) ? Lookup.Find(FIntVector(C.Column.X + Dx, C.Column.Y + Dy, int32(C.Level))) : nullptr;
					if (B && !Keep[*B] && (!Source.AreNeighboursConnected || Source.AreNeighboursConnected(A, *B)))
					{
						Visit(*B);
					}
				}
			}
			for (const int32 B : LinksOf[A])
			{
				Visit(B);
			}
		}
		// Remap: kept cells in their order; links between kept cells; the connectivity asks the old indices.
		TArray<int32> NewOf;
		NewOf.Init(INDEX_NONE, Num);
		TArray<int32> OldOf;
		TArray<FVerseBeliefCellDesc> Cells;
		for (int32 I = 0; I < Num; ++I)
		{
			if (Keep[I])
			{
				NewOf[I] = Cells.Num();
				OldOf.Add(I);
				Cells.Add(Source.Cells[I]);
			}
		}
		const int32 Dropped = Num - Cells.Num();
		TArray<FVerseBeliefLinkDesc> Links;
		for (const FVerseBeliefLinkDesc& Link : Source.Links)
		{
			if (Source.Cells.IsValidIndex(Link.From) && Source.Cells.IsValidIndex(Link.To) && Keep[Link.From] && Keep[Link.To])
			{
				FVerseBeliefLinkDesc& L = Links.Add_GetRef(Link);
				L.From = NewOf[Link.From];
				L.To = NewOf[Link.To];
			}
		}
		Source.Cells = MoveTemp(Cells);
		Source.Links = MoveTemp(Links);
		if (Source.AreNeighboursConnected)
		{
			TSharedRef<TFunction<bool(int32, int32)>> Inner = MakeShared<TFunction<bool(int32, int32)>>(MoveTemp(Source.AreNeighboursConnected));
			TSharedRef<TArray<int32>> Old = MakeShared<TArray<int32>>(MoveTemp(OldOf));
			Source.AreNeighboursConnected = [Inner, Old](int32 A, int32 B) { return (*Inner)((*Old)[A], (*Old)[B]); };
		}
		return Dropped;
	}

	TSharedPtr<FVerseBotArenaData> Build(const UWorld& World, FString& OutWhyNot)
	{
		UNavigationSystemV1* NavSys = FNavigationSystem::GetCurrent<UNavigationSystemV1>(const_cast<UWorld*>(&World));
		if (!NavSys)
		{
			OutWhyNot = TEXT("no navigation system");
			return nullptr;
		}
		if (NavSys->IsNavigationBuildInProgress())
		{
			OutWhyNot = TEXT("nav mesh still building");
			return nullptr;
		}
		const INavigationDataInterface* Nav = NavSys->GetMainNavData();
		if (!Nav)
		{
			OutWhyNot = TEXT("no nav data");
			return nullptr;
		}
		TArray<FVector> Spawns;
		SpawnLocations(World, Spawns);
		if (Spawns.Num() == 0)
		{
			OutWhyNot = TEXT("no spawn points");
			return nullptr;
		}
		// The floor: the lowest spawn projected onto the nav mesh.
		const FVector* Lowest = &Spawns[0];
		for (const FVector& S : Spawns)
		{
			Lowest = S.Z < Lowest->Z ? &S : Lowest;
		}
		FNavLocation FloorHit;
		if (!Nav->ProjectPoint(*Lowest, FloorHit, FVector(100.f, 100.f, 400.f)))
		{
			OutWhyNot = TEXT("spawn not on the nav mesh yet");
			return nullptr;
		}
		const float FloorZ = float(FloorHit.Location.Z);

		TSharedPtr<FVerseBotArenaData> Data = MakeShared<FVerseBotArenaData>();
		Data->ArenaBox = FVerseBotArenaData::ArenaBoxFromSpawns(Spawns);
		FVerseBeliefNavSettings Settings;
		Settings.ArenaBox = Data->ArenaBox;
		Settings.CellSizeCm = FVerseBotArenaData::GridCellCm;
		Settings.LevelProbeZCm[0] = FloorZ;
		Settings.LevelProbeZCm[1] = FloorZ + MidLevelCm;
		Settings.LevelProbeZCm[2] = FloorZ + UpperLevelCm;
		if (!FVerseBeliefNavSampler::Build(*Nav, Settings, Data->GridSource) || Data->GridSource.Cells.Num() < MinCells)
		{
			OutWhyNot = FString::Printf(TEXT("nav sample has %d cells"), Data->GridSource.Cells.Num());
			return nullptr;
		}
		MemoiseConnectivity(Data->GridSource);
		AddCrossLevelLinks(*Nav, Data->GridSource);
		const int32 Unreachable = KeepReachableCells(Data->GridSource, Spawns);

		// Cover points on the 2 m lattice.
		const int32 Step = FMath::Max(1, FMath::RoundToInt32(FVerseBotArenaData::PointStepCm / FVerseBotArenaData::GridCellCm));
		int32 NextEdge = 0;
		for (const FVerseBeliefCellDesc& Cell : Data->GridSource.Cells)
		{
			if (Cell.Column.X % Step != 0 || Cell.Column.Y % Step != 0)
			{
				continue;
			}
			const FVector Floor = CellWorld(Data->GridSource, Cell);
			FVector Facing;
			bool bHigh = false;
			if (!CoverAt(World, Floor, Facing, bHigh))
			{
				continue;
			}
			FVerseBotCoverPoint& P = Data->Points.AddDefaulted_GetRef();
			P.Id = Data->Points.Num() - 1;
			P.Location = Floor;
			P.bHigh = bHigh;
			P.Facing = Facing;
			P.MaterialProtection = 1.f;
			P.EdgeId = IsEdge(World, Floor, Facing) ? NextEdge++ : INDEX_NONE;
		}
		UE_LOG(LogVerseBot, Log, TEXT("[VerseBot] arena data: %d belief cells (%d unreachable dropped), %d stair links, %d cover points (%d edges), box %s"),
			Data->GridSource.Cells.Num(), Unreachable, Data->GridSource.Links.Num(), Data->Points.Num(), NextEdge, *Data->ArenaBox.ToString());
		return Data;
	}
}

FBox FVerseBotArenaData::ArenaBoxFromSpawns(TConstArrayView<FVector> Spawns)
{
	using namespace VerseBotArenaDataPrivate;
	FBox Box(ForceInit);
	for (const FVector& S : Spawns)
	{
		Box += S;
	}
	if (!Box.IsValid)
	{
		return Box;
	}
	return FBox(FVector(Box.Min.X - ArenaMarginXYCm, Box.Min.Y - ArenaMarginXYCm, Box.Min.Z - 300.0),
		FVector(Box.Max.X + ArenaMarginXYCm, Box.Max.Y + ArenaMarginXYCm, Box.Max.Z + 1000.0));
}

void FVerseBotArenaData::PointsWithin(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) const
{
	Out.Reset();
	const double R2 = double(RadiusCm) * double(RadiusCm);
	for (const FVerseBotCoverPoint& P : Points)
	{
		if (FVector::DistSquared(P.Location, Center) <= R2)
		{
			Out.Add(P);
		}
	}
}

TSharedPtr<const FVerseBotArenaData> FVerseBotArenaData::Get(UWorld& World)
{
	using namespace VerseBotArenaDataPrivate;
	FCacheEntry& Entry = EntryFor(World);
	if (Entry.Data.IsValid())
	{
		return Entry.Data;
	}
	const double Now = World.GetTimeSeconds();
	if (Now < Entry.NextTryS)
	{
		return nullptr;
	}
	Entry.NextTryS = Now + RetryS;
	++Entry.Attempts;
	FString WhyNot;
	Entry.Data = Build(World, WhyNot);
	if (!Entry.Data.IsValid() && (Entry.Attempts == 1 || Entry.Attempts % 30 == 0))
	{
		UE_LOG(LogVerseBot, Log, TEXT("[VerseBot] arena data not ready (attempt %d): %s"), Entry.Attempts, *WhyNot);
	}
	return Entry.Data;
}

const FVerseBotGridBelief* FVerseBotArenaData::AttachTo(UWorld& World, FVerseBotBrainCore& Brain, FVerseBotEngineQueries& Engine,
	IVerseBotWorldQueries& Active, int32 SelfPlayerId)
{
	const TSharedPtr<const FVerseBotArenaData> Arena = Get(World);
	if (!Arena.IsValid())
	{
		return nullptr;
	}
	Engine.SetArena(Arena);
	FVerseBeliefMapConfig Config;
	Config.SelfPlayerId = SelfPlayerId;
	Config.ArenaBox = Arena->ArenaBox;
	// Clear tests enough cells per step that looking around empties what the bot sees faster than
	// the belief diffuses back (bot.md 4.2).
	Config.MaxCellSightTestsPerStep = ClearTestsPerStep;
	Active.GetSpawnPoints(Config.SpawnPoints);
	TUniquePtr<FVerseBotGridBelief> Grid = MakeUnique<FVerseBotGridBelief>(Arena->GridSource, Config, Active);
	const FVerseBotGridBelief* Raw = Grid.Get();
	Brain.SetBelief(MoveTemp(Grid));
	return Raw;
}

void FVerseBotArenaData::Forget(const UWorld& World)
{
	using namespace VerseBotArenaDataPrivate;
	Cache().RemoveAll([&World](const FCacheEntry& E) { return !E.World.IsValid() || E.World.Get() == &World; });
}

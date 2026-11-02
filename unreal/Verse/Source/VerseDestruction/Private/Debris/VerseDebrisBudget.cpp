#include "Debris/VerseDebrisBudget.h"

FVerseDebrisBudget::FConfig FVerseDebrisBudget::FConfig::High()
{
	return FConfig();
}

FVerseDebrisBudget::FConfig FVerseDebrisBudget::FConfig::Low()
{
	FConfig Config;
	Config.MaxBodies = 150;
	Config.DespawnS = 6.f;
	return Config;
}

FVerseDebrisBudget::FVerseDebrisBudget(const FConfig& InConfig)
	: Config(InConfig)
{
}

int32 FVerseDebrisBudget::DesiredBodies(EVerseDebrisType Type, EVersePieceState ToState)
{
	// WP06 start values (unreal/Verse/Data/destruction/tuning.json "debris_bodies"). Damaged is
	// scorch and sparks only; Niagara-only types never ask for rigid bodies.
	if (ToState == EVersePieceState::Damaged || ToState == EVersePieceState::Repairing || ToState == EVersePieceState::Intact)
	{
		return 0;
	}
	switch (Type)
	{
	case EVerseDebrisType::MetalShards:
		return ToState == EVersePieceState::Holed ? 12 : 32;
	case EVerseDebrisType::CorrugatedChunks:
		return ToState == EVersePieceState::Holed ? 14 : 36;
	case EVerseDebrisType::PanelChunks:
		return ToState == EVersePieceState::Holed ? 16 : 40;
	case EVerseDebrisType::GratingTwisted:
		return 6;
	case EVerseDebrisType::CeilingTile:
		return 1;
	case EVerseDebrisType::GlassShards:
	case EVerseDebrisType::DustChips:
	case EVerseDebrisType::SparksOnly:
		return 0;
	}
	return 0;
}

bool FVerseDebrisBudget::HasNiagara(EVerseDebrisType Type)
{
	return Type != EVerseDebrisType::GratingTwisted;
}

int32 FVerseDebrisBudget::ActiveBodies() const
{
	int32 Sum = 0;
	for (const FBurst& Burst : Bursts)
	{
		if (!Burst.bFading)
		{
			Sum += Burst.Bodies;
		}
	}
	return Sum;
}

int32 FVerseDebrisBudget::AliveActors() const
{
	int32 Count = 0;
	for (const FBurst& Burst : Bursts)
	{
		Count += Burst.Bodies > 0 ? 1 : 0;
	}
	return Count;
}

void FVerseDebrisBudget::EvictOldest(double NowS, TArray<int32>& OutEvicted)
{
	for (FBurst& Burst : Bursts) // Bursts are kept in spawn order: the first live one is the oldest.
	{
		if (!Burst.bFading && Burst.Bodies > 0)
		{
			Burst.bFading = true;
			Burst.FadeStartS = NowS;
			OutEvicted.Add(Burst.Id);
			return;
		}
	}
}

FVerseDebrisBudget::FGrant FVerseDebrisBudget::Request(const FRequest& Request, double NowS)
{
	FGrant Grant;
	Grant.bNiagara = HasNiagara(Request.Type) && Request.ToState != EVersePieceState::Intact;
	const int32 Desired = DesiredBodies(Request.Type, Request.ToState);
	const int32 Bodies = FMath::Clamp(Desired, 0, FMath::Min(Config.MaxBodiesPerFracture, Config.MaxBodies));
	if (Bodies <= 0)
	{
		return Grant;
	}
	// Oldest bursts fade until the new one fits the body cap (fading bodies no longer count).
	while (ActiveBodies() + Bodies > Config.MaxBodies)
	{
		const int32 Before = Grant.Evicted.Num();
		EvictOldest(NowS, Grant.Evicted);
		if (Grant.Evicted.Num() == Before)
		{
			break;
		}
	}
	// A fading actor still holds a pool slot: when the pool is full, the oldest actor goes at once.
	while (AliveActors() + 1 > Config.MaxGeometryCollectionActors)
	{
		const int32 Oldest = Bursts.IndexOfByPredicate([](const FBurst& Burst) { return Burst.Bodies > 0; });
		if (Oldest == INDEX_NONE)
		{
			break;
		}
		Grant.Removed.Add(Bursts[Oldest].Id);
		Bursts.RemoveAt(Oldest);
	}
	FBurst Burst;
	Burst.Id = NextId++;
	Burst.PieceIndex = Request.PieceIndex;
	Burst.Bodies = Bodies;
	Burst.SpawnS = NowS;
	Bursts.Add(Burst);
	Grant.BurstId = Burst.Id;
	Grant.Bodies = Bodies;
	PeakBodies = FMath::Max(PeakBodies, ActiveBodies());
	PeakActors = FMath::Max(PeakActors, AliveActors());
	PeakPerFracture = FMath::Max(PeakPerFracture, Bodies);
	return Grant;
}

void FVerseDebrisBudget::Commit(int32 BurstId, int32 RealBodies)
{
	const int32 Index = Bursts.IndexOfByPredicate([BurstId](const FBurst& Burst) { return Burst.Id == BurstId; });
	if (Index == INDEX_NONE)
	{
		return;
	}
	FBurst& Burst = Bursts[Index];
	ensureMsgf(RealBodies <= Burst.Bodies, TEXT("debris burst %d simulates %d bodies, granted %d"), BurstId, RealBodies, Burst.Bodies);
	Burst.Bodies = FMath::Clamp(RealBodies, 0, Burst.Bodies);
	if (Burst.Bodies == 0)
	{
		Bursts.RemoveAt(Index);
		return;
	}
	PeakRealBodies = FMath::Max(PeakRealBodies, ActiveBodies());
	PeakRealActors = FMath::Max(PeakRealActors, AliveActors());
	PeakRealPerFracture = FMath::Max(PeakRealPerFracture, Burst.Bodies);
}

TArray<int32> FVerseDebrisBudget::Tick(double NowS)
{
	TArray<int32> Removed;
	for (int32 Index = Bursts.Num() - 1; Index >= 0; --Index)
	{
		FBurst& Burst = Bursts[Index];
		if (!Burst.bAsleep && NowS - Burst.SpawnS >= Config.SleepS)
		{
			Burst.bAsleep = true;
		}
		if (!Burst.bFading && NowS - Burst.SpawnS >= Config.DespawnS)
		{
			Burst.bFading = true;
			Burst.FadeStartS = NowS;
		}
		if (Burst.bFading && NowS - Burst.FadeStartS >= Config.FadeS)
		{
			Removed.Add(Burst.Id);
			Bursts.RemoveAt(Index);
		}
	}
	return Removed;
}

TArray<int32> FVerseDebrisBudget::PurgeAll()
{
	TArray<int32> Removed;
	for (const FBurst& Burst : Bursts)
	{
		Removed.Add(Burst.Id);
	}
	Bursts.Reset();
	return Removed;
}

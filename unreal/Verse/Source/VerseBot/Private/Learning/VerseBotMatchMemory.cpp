#include "Learning/VerseBotMatchMemory.h"

#include "Bot/VerseBotTier.h"

namespace
{
	constexpr float CellCm = 100.f;
	/** Weights of 7.1: sighted 1, heard 0.3, first contact 2. */
	constexpr float SightWeight = 1.f;
	constexpr float HeardWeight = 0.3f;
	constexpr float FirstContactWeight = 2.f;
	/** Fast re-peek threshold (7.1). */
	constexpr float FastRepeekS = 3.f;
	/** Height of one arena level, cm (3 levels). */
	constexpr float MemoryLevelCm = 400.f;

	int64 RouteKey(int32 From, int32 To)
	{
		return (int64(uint32(From)) << 32) | int64(uint32(To));
	}
}

int32 FVerseBotMatchMemory::RangeBin(float RangeCm)
{
	const float M = RangeCm / VerseBot::CmPerM;
	if (M < 5.f) return 0;
	if (M < 10.f) return 1;
	if (M < 20.f) return 2;
	if (M < 35.f) return 3;
	return 4;
}

float FVerseBotMatchMemory::RangeBinCentreCm(int32 Bin)
{
	static constexpr float Centres[NumRangeBins] = {3.f, 7.5f, 15.f, 27.5f, 40.f};
	return Centres[FMath::Clamp(Bin, 0, NumRangeBins - 1)] * VerseBot::CmPerM;
}

void FVerseBotMatchMemory::Configure(const UVerseBotTier& Tier)
{
	LearnWeightMax = FMath::Min(Tier.LearnWeightMax, float(UVerseBotTier::LearnWeightMaxCap));
	LearnSamplesHalf = FMath::Max(Tier.LearnSamplesHalf, 0.001f);
	HabitHalfLifeS = FMath::Max(Tier.HabitHalfLifeS, 1.f);
}

void FVerseBotMatchMemory::Reset()
{
	for (int32 i = 0; i < 2; ++i)
	{
		Layers[i].Reset();
		LayerTotal[i] = FCell();
	}
	Peeks.Reset();
	PeekTotal = 0.f;
	for (FRangeBin& Bin : Ranges)
	{
		Bin = FRangeBin();
	}
	Routes.Reset();
	RouteOut.Reset();
	LastZone = INDEX_NONE;
	Habits.Reset();
}

bool FVerseBotMatchMemory::IsEmpty() const
{
	bool bRanges = true;
	for (const FRangeBin& Bin : Ranges)
	{
		bRanges &= Bin.Engagements == 0;
	}
	return Layers[0].Num() == 0 && Layers[1].Num() == 0 && Peeks.Num() == 0 && Routes.Num() == 0 && Habits.Num() == 0
		&& bRanges && LastZone == INDEX_NONE && LayerTotal[0].Value == 0.f && LayerTotal[1].Value == 0.f;
}

FIntVector FVerseBotMatchMemory::CellOf(const FVector& Location)
{
	return FIntVector(FMath::FloorToInt32(Location.X / CellCm), FMath::FloorToInt32(Location.Y / CellCm),
		FMath::FloorToInt32(Location.Z / MemoryLevelCm));
}

float FVerseBotMatchMemory::Decay(float DtS) const
{
	return DtS <= 0.f ? 1.f : FMath::Pow(0.5f, DtS / HabitHalfLifeS);
}

float FVerseBotMatchMemory::Decayed(const FCell& Cell, float NowS) const
{
	return Cell.Value * Decay(NowS - Cell.TimeS);
}

void FVerseBotMatchMemory::AddHeat(ELayer Layer, const FVector& Location, float Amount, float NowS)
{
	if (!bEnabled)
	{
		return;
	}
	FCell& C = Layers[int32(Layer)].FindOrAdd(CellOf(Location));
	C.Value = Decayed(C, NowS) + Amount;
	C.TimeS = NowS;
	FCell& T = LayerTotal[int32(Layer)];
	T.Value = Decayed(T, NowS) + Amount;
	T.TimeS = NowS;
}

void FVerseBotMatchMemory::RecordSighting(const FVector& Location, float NowS, bool bFirstContact)
{
	AddHeat(ELayer::Position, Location, bFirstContact ? FirstContactWeight : SightWeight, NowS);
}

void FVerseBotMatchMemory::RecordHeard(const FVector& Location, float NowS)
{
	AddHeat(ELayer::Position, Location, HeardWeight, NowS);
}

void FVerseBotMatchMemory::RecordShotFrom(const FVector& Location, float NowS, bool bSeen)
{
	AddHeat(ELayer::Shooting, Location, bSeen ? SightWeight : HeardWeight, NowS);
}

void FVerseBotMatchMemory::RecordPeek(int32 EdgeId, EVerseBotPeekType Type, float NowS)
{
	if (!bEnabled || EdgeId == INDEX_NONE)
	{
		return;
	}
	FPeekHabit& H = Peeks.FindOrAdd(EdgeId);
	H.Appearances += 1.f;
	H.FastRepeeks += (NowS - H.LastS) < FastRepeekS ? 1.f : 0.f;
	H.JumpPeeks += Type == EVerseBotPeekType::JumpPeek ? 1.f : 0.f;
	H.LeanPeeks += (Type == EVerseBotPeekType::LeanLeft || Type == EVerseBotPeekType::LeanRight) ? 1.f : 0.f;
	H.LastS = NowS;
	PeekTotal += 1.f;
}

void FVerseBotMatchMemory::RecordEngagementEnd(float RangeCm, bool bPersonWon)
{
	if (!bEnabled)
	{
		return;
	}
	FRangeBin& Bin = Ranges[RangeBin(RangeCm)];
	++Bin.Engagements;
	Bin.PersonWins += bPersonWon ? 1 : 0;
}

void FVerseBotMatchMemory::RecordZone(int32 ZoneId, float NowS)
{
	if (!bEnabled || ZoneId == INDEX_NONE || ZoneId == LastZone)
	{
		return;
	}
	if (LastZone != INDEX_NONE)
	{
		Routes.FindOrAdd(RouteKey(LastZone, ZoneId)) += 1.f;
		RouteOut.FindOrAdd(LastZone) += 1.f;
	}
	LastZone = ZoneId;
}

void FVerseBotMatchMemory::RecordHabit(FName Habit)
{
	if (bEnabled)
	{
		++Habits.FindOrAdd(Habit);
	}
}

float FVerseBotMatchMemory::Heat(ELayer Layer, const FVector& Location, float NowS) const
{
	const FCell* C = Layers[int32(Layer)].Find(CellOf(Location));
	return C ? Decayed(*C, NowS) : 0.f;
}

float FVerseBotMatchMemory::SamplesNear(ELayer Layer, const FVector& Location, float RadiusCm, float NowS) const
{
	const int32 R = FMath::CeilToInt32(RadiusCm / CellCm);
	const FIntVector Centre = CellOf(Location);
	const TMap<FIntVector, FCell>& Map = Layers[int32(Layer)];
	float Sum = 0.f;
	for (int32 dx = -R; dx <= R; ++dx)
	{
		for (int32 dy = -R; dy <= R; ++dy)
		{
			if (dx * dx + dy * dy > R * R)
			{
				continue;
			}
			if (const FCell* C = Map.Find(Centre + FIntVector(dx, dy, 0)))
			{
				Sum += Decayed(*C, NowS);
			}
		}
	}
	return Sum;
}

float FVerseBotMatchMemory::HeatShare(ELayer Layer, const FVector& Location, float RadiusCm, float NowS) const
{
	const float Total = Decayed(LayerTotal[int32(Layer)], NowS);
	return Total > KINDA_SMALL_NUMBER ? FMath::Clamp(SamplesNear(Layer, Location, RadiusCm, NowS) / Total, 0.f, 1.f) : 0.f;
}

float FVerseBotMatchMemory::Weight(float Samples) const
{
	if (!bEnabled || Samples <= 0.f)
	{
		return 0.f;
	}
	const float Max = FMath::Min(LearnWeightMax, float(UVerseBotTier::LearnWeightMaxCap));
	return Max * Samples / (Samples + LearnSamplesHalf);
}

float FVerseBotMatchMemory::ZoneTransitionProb(int32 FromZone, int32 ToZone) const
{
	const float* Out = RouteOut.Find(FromZone);
	const float* N = Routes.Find(RouteKey(FromZone, ToZone));
	return (Out && N && *Out > 0.f) ? *N / *Out : 0.f;
}

int32 FVerseBotMatchMemory::MostLikelyNextZone(int32 FromZone) const
{
	int32 Best = INDEX_NONE;
	float BestN = 0.f;
	for (const TPair<int64, float>& R : Routes)
	{
		const int32 From = int32(uint32(R.Key >> 32));
		const int32 To = int32(uint32(R.Key & 0xffffffff));
		if (From == FromZone && (R.Value > BestN || (R.Value == BestN && To < Best)))
		{
			Best = To;
			BestN = R.Value;
		}
	}
	return Best;
}

TPair<int32, int32> FVerseBotMatchMemory::MostUsedRoute() const
{
	TPair<int32, int32> Best(INDEX_NONE, INDEX_NONE);
	float BestN = 0.f;
	for (const TPair<int64, float>& R : Routes)
	{
		if (R.Value > BestN)
		{
			BestN = R.Value;
			Best = TPair<int32, int32>(int32(uint32(R.Key >> 32)), int32(uint32(R.Key & 0xffffffff)));
		}
	}
	return Best;
}

float FVerseBotMatchMemory::PeekShare(int32 EdgeId, float& OutSamples) const
{
	const FPeekHabit* H = Peeks.Find(EdgeId);
	OutSamples = H ? H->Appearances : 0.f;
	return (H && PeekTotal > 0.f) ? H->Appearances / PeekTotal : 0.f;
}

float FVerseBotMatchMemory::RepeekShare(int32 EdgeId) const
{
	const FPeekHabit* H = Peeks.Find(EdgeId);
	return (H && H->Appearances > 0.f) ? H->FastRepeeks / H->Appearances : 0.f;
}

void FVerseBotMatchMemory::TopPeekEdges(int32 N, TArray<int32>& Out) const
{
	Out.Reset();
	TArray<TPair<int32, float>> All;
	for (const TPair<int32, FPeekHabit>& P : Peeks)
	{
		All.Emplace(P.Key, P.Value.Appearances);
	}
	All.Sort([](const TPair<int32, float>& A, const TPair<int32, float>& B)
		{ return A.Value != B.Value ? A.Value > B.Value : A.Key < B.Key; });
	for (int32 i = 0; i < FMath::Min(N, All.Num()); ++i)
	{
		Out.Add(All[i].Key);
	}
}

int32 FVerseBotMatchMemory::RangeBinShift(float PreferredRangeCm) const
{
	if (!bEnabled)
	{
		return 0;
	}
	const int32 Home = RangeBin(PreferredRangeCm);
	int32 Best = Home;
	float BestShare = 2.f;
	for (int32 Bin = FMath::Max(0, Home - 1); Bin <= FMath::Min(NumRangeBins - 1, Home + 1); ++Bin)
	{
		const FRangeBin& R = Ranges[Bin];
		if (R.Engagements < 3)
		{
			continue;
		}
		const float Share = float(R.PersonWins) / float(R.Engagements);
		if (Share < BestShare - 1e-6f || (FMath::IsNearlyEqual(Share, BestShare, 1e-6f) && Bin == Home))
		{
			BestShare = Share;
			Best = Bin;
		}
	}
	return FMath::Clamp(Best - Home, -1, 1);
}

int32 FVerseBotMatchMemory::HabitCount(FName Habit) const
{
	const int32* N = Habits.Find(Habit);
	return N ? *N : 0;
}

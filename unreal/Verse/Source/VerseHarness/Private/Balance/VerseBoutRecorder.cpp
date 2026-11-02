#include "Balance/VerseBoutRecorder.h"

#include "VerseHarnessJson.h"

namespace VerseBoutPrivate
{
	const TCHAR* CauseName(EVerseDamageSource Cause)
	{
		switch (Cause)
		{
		case EVerseDamageSource::Melee:
			return TEXT("melee");
		case EVerseDamageSource::Finisher:
			return TEXT("finisher");
		case EVerseDamageSource::Gadget:
			return TEXT("gadget");
		case EVerseDamageSource::World:
			return TEXT("world");
		default:
			return TEXT("bolt");
		}
	}

	int32 Index(EVerseSide Side) { return Side == EVerseSide::A ? 0 : 1; }

	FString SideJson(const FVerseBoutSide& S)
	{
		FVerseJsonWriter O;
		O.Num(TEXT("kills"), S.Kills)
			.Num(TEXT("deaths"), S.Deaths)
			.Num(TEXT("shots"), S.Shots)
			.Num(TEXT("hits"), S.Hits)
			.Num(TEXT("headshotHits"), S.HeadshotHits)
			.Numbers(TEXT("timeToContactS"), S.TimeToContactS)
			.Num(TEXT("bulwarkUses"), S.BulwarkUses)
			.Num(TEXT("breachUses"), S.BreachUses)
			.Num(TEXT("reloadsInFight"), S.ReloadsInFight)
			.Num(TEXT("stuckEvents"), S.StuckEvents)
			.Raw(TEXT("fireAudit"), TEXT("{}"))
			// Bot timing and nav health come from VerseBot once it lands (WP08); unknown until then.
			.Null(TEXT("botMsP99"))
			.Null(TEXT("navFailures"));
		return O.Close();
	}
}

FVerseBoutRecorder::FVerseBoutRecorder(int32 InPlayerIdA, int32 InPlayerIdB, int32 InKillsToWin, double InTimeLimitS)
	: PlayerIdA(InPlayerIdA)
	, PlayerIdB(InPlayerIdB)
	, KillsToWin(InKillsToWin)
	, TimeLimitS(InTimeLimitS)
{
}

EVerseSide FVerseBoutRecorder::SideOf(int32 PlayerId) const
{
	if (PlayerId == PlayerIdA)
	{
		return EVerseSide::A;
	}
	if (PlayerId == PlayerIdB)
	{
		return EVerseSide::B;
	}
	return EVerseSide::None;
}

void FVerseBoutRecorder::Contact(EVerseSide S, double T)
{
	FVerseBoutSide& Side = Mutable(S);
	if (!Side.bContactThisLife)
	{
		Side.bContactThisLife = true;
		Side.TimeToContactS.Add(float(FMath::Max(0.0, T - Side.LifeStartS)));
	}
	Side.LastFightS = T;
}

void FVerseBoutRecorder::OnFire(const FVerseFireEvent& Event, double T)
{
	const EVerseSide S = SideOf(Event.ShooterId);
	if (S != EVerseSide::None)
	{
		Mutable(S).Shots++;
	}
}

void FVerseBoutRecorder::OnHit(const FVerseHitEvent& Event, double T)
{
	const EVerseSide Shooter = SideOf(Event.InstigatorId);
	const EVerseSide Victim = SideOf(Event.VictimId);
	if (Shooter == EVerseSide::None || Victim == EVerseSide::None || Shooter == Victim)
	{
		return;
	}
	FVerseBoutSide& S = Mutable(Shooter);
	S.Hits++;
	S.HeadshotHits += Event.bHeadshot ? 1 : 0;
	FVerseBoutSide& V = Mutable(Victim);
	if (V.FirstHitTakenS < 0.0)
	{
		V.FirstHitTakenS = T;
	}
	Contact(Shooter, T);
	Contact(Victim, T);
	const int32 VI = VerseBoutPrivate::Index(Victim);
	LastHitOn[VI] = Event;
	bHasLastHit[VI] = true;
}

void FVerseBoutRecorder::OnDeath(const FVerseDeathEvent& Event, double T)
{
	const EVerseSide Victim = SideOf(Event.VictimId);
	if (Victim == EVerseSide::None)
	{
		return;
	}
	const EVerseSide Killer = SideOf(Event.KillerId);
	FVerseBoutSide& V = Mutable(Victim);
	V.Deaths++;
	if (Killer != EVerseSide::None && Killer != Victim)
	{
		Mutable(Killer).Kills++;
		FVerseBoutKill Kill;
		Kill.T = T;
		Kill.Killer = Killer;
		Kill.Cause = Event.Cause;
		const int32 VI = VerseBoutPrivate::Index(Victim);
		if (bHasLastHit[VI])
		{
			const FVerseHitEvent& Hit = LastHitOn[VI];
			Kill.bHeadshot = Hit.bHeadshot != 0 || Event.LastZone == EVerseHitZone::Head;
			Kill.bWall = Hit.PenetrationCount > 0;
			Kill.RangeM = Hit.DistanceM;
		}
		else
		{
			Kill.bHeadshot = Event.LastZone == EVerseHitZone::Head;
		}
		if (V.FirstHitTakenS >= 0.0)
		{
			Kill.TtkS = float(T - V.FirstHitTakenS);
		}
		Kill.bSpawnKill = T - V.LifeStartS <= SpawnKillWindowS;
		KillList.Add(Kill);
	}
	const int32 VI = VerseBoutPrivate::Index(Victim);
	bHasLastHit[VI] = false;
	V.FirstHitTakenS = -1.0;
	V.bHasPosition = false;
}

void FVerseBoutRecorder::OnRespawn(int32 PlayerId, double T)
{
	const EVerseSide S = SideOf(PlayerId);
	if (S == EVerseSide::None)
	{
		return;
	}
	FVerseBoutSide& Side = Mutable(S);
	Side.LifeStartS = T;
	Side.bContactThisLife = false;
	Side.FirstHitTakenS = -1.0;
	Side.bHasPosition = false;
}

void FVerseBoutRecorder::OnReload(const FVerseReloadEvent& Event, double T)
{
	const EVerseSide S = SideOf(Event.PlayerId);
	if (S != EVerseSide::None && !Event.bCancelled && T - Side(S).LastFightS <= FightWindowS)
	{
		Mutable(S).ReloadsInFight++;
	}
}

void FVerseBoutRecorder::OnGadget(const FVerseGadgetEvent& Event, double T)
{
	const EVerseSide S = SideOf(Event.OwnerId);
	if (S == EVerseSide::None)
	{
		return;
	}
	const FString Id = Event.GadgetId.ToString();
	if (Event.Kind == EVerseGadgetEventKind::Deploy && Id.Contains(TEXT("Bulwark")))
	{
		Mutable(S).BulwarkUses++;
	}
	else if (Event.Kind == EVerseGadgetEventKind::Plant && Id.Contains(TEXT("Breach")))
	{
		Mutable(S).BreachUses++;
	}
}

void FVerseBoutRecorder::SamplePosition(EVerseSide S, const FVector& Location, bool bAlive, double T)
{
	if (S == EVerseSide::None)
	{
		return;
	}
	FVerseBoutSide& Side = Mutable(S);
	if (!bAlive || !Side.bHasPosition)
	{
		Side.bHasPosition = bAlive;
		Side.LastMovedFrom = Location;
		Side.LastMovedS = T;
		return;
	}
	if (FVector::Dist(Location, Side.LastMovedFrom) > StuckDistanceCm)
	{
		Side.LastMovedFrom = Location;
		Side.LastMovedS = T;
	}
	else if (T - Side.LastMovedS >= StuckAfterS)
	{
		Side.StuckEvents++;
		Side.LastMovedS = T;
	}
}

bool FVerseBoutRecorder::IsOver(double T) const
{
	return SideA.Kills >= KillsToWin || SideB.Kills >= KillsToWin || T >= TimeLimitS;
}

EVerseSide FVerseBoutRecorder::Winner() const
{
	if (SideA.Kills > SideB.Kills)
	{
		return EVerseSide::A;
	}
	if (SideB.Kills > SideA.Kills)
	{
		return EVerseSide::B;
	}
	return EVerseSide::None;
}

FString FVerseBoutRecorder::ToJsonLine(const FString& Pairing, int32 Match, int32 Bout, uint32 Seed,
	int32 SpawnSideA, double DurationS, double MatchTimeStartS, const TArray<float>& AdaptiveTrace) const
{
	using namespace VerseBoutPrivate;

	const auto Ms = [](double V) { return FMath::RoundToDouble(V * 1000.0) / 1000.0; };
	TArray<FString> KillValues;
	for (const FVerseBoutKill& K : KillList)
	{
		FVerseJsonWriter O;
		O.Num(TEXT("t"), Ms(K.T))
			.Str(TEXT("killer"), K.Killer == EVerseSide::A ? TEXT("A") : TEXT("B"))
			.Str(TEXT("cause"), CauseName(K.Cause))
			.Bool(TEXT("headshot"), K.bHeadshot)
			.Bool(TEXT("wall"), K.bWall);
		if (K.RangeM >= 0.f)
		{
			O.Num(TEXT("rangeM"), K.RangeM);
		}
		if (K.TtkS >= 0.f)
		{
			O.Num(TEXT("ttkS"), K.TtkS);
		}
		O.Bool(TEXT("spawnKill"), K.bSpawnKill);
		KillValues.Add(O.Close());
	}
	const EVerseSide W = Winner();
	FVerseJsonWriter Root;
	Root.Str(TEXT("schema"), TEXT("verse.bout/1"))
		.Str(TEXT("pairing"), Pairing)
		.Num(TEXT("match"), Match)
		.Num(TEXT("bout"), Bout)
		.Num(TEXT("seed"), Seed)
		.Num(TEXT("spawnSideA"), SpawnSideA)
		.Str(TEXT("winner"), W == EVerseSide::A ? TEXT("A") : (W == EVerseSide::B ? TEXT("B") : TEXT("none")))
		.Num(TEXT("durationS"), Ms(DurationS))
		.Num(TEXT("matchTimeStartS"), Ms(MatchTimeStartS))
		.Raw(TEXT("kills"), TEXT("[") + FString::Join(KillValues, TEXT(",")) + TEXT("]"))
		.Raw(TEXT("a"), SideJson(SideA))
		.Raw(TEXT("b"), SideJson(SideB))
		.Numbers(TEXT("adaptiveTrace"), AdaptiveTrace);
	return Root.Close();
}

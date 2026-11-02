#include "Balance/VerseBoutRecorder.h"

#include "Dom/JsonObject.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

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

	TSharedRef<FJsonObject> SideJson(const FVerseBoutSide& S)
	{
		TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetNumberField(TEXT("kills"), S.Kills);
		O->SetNumberField(TEXT("deaths"), S.Deaths);
		O->SetNumberField(TEXT("shots"), S.Shots);
		O->SetNumberField(TEXT("hits"), S.Hits);
		O->SetNumberField(TEXT("headshotHits"), S.HeadshotHits);
		TArray<TSharedPtr<FJsonValue>> Contact;
		for (float T : S.TimeToContactS)
		{
			Contact.Add(MakeShared<FJsonValueNumber>(T));
		}
		O->SetArrayField(TEXT("timeToContactS"), Contact);
		O->SetNumberField(TEXT("bulwarkUses"), S.BulwarkUses);
		O->SetNumberField(TEXT("breachUses"), S.BreachUses);
		O->SetNumberField(TEXT("reloadsInFight"), S.ReloadsInFight);
		O->SetNumberField(TEXT("stuckEvents"), S.StuckEvents);
		O->SetObjectField(TEXT("fireAudit"), MakeShared<FJsonObject>());
		// Bot timing and nav health come from VerseBot once it lands (WP08); unknown until then.
		O->SetField(TEXT("botMsP99"), MakeShared<FJsonValueNull>());
		O->SetField(TEXT("navFailures"), MakeShared<FJsonValueNull>());
		return O;
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

	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("schema"), TEXT("verse.bout/1"));
	Root->SetStringField(TEXT("pairing"), Pairing);
	Root->SetNumberField(TEXT("match"), Match);
	Root->SetNumberField(TEXT("bout"), Bout);
	Root->SetNumberField(TEXT("seed"), Seed);
	Root->SetNumberField(TEXT("spawnSideA"), SpawnSideA);
	const EVerseSide W = Winner();
	Root->SetStringField(TEXT("winner"), W == EVerseSide::A ? TEXT("A") : (W == EVerseSide::B ? TEXT("B") : TEXT("none")));
	Root->SetNumberField(TEXT("durationS"), FMath::RoundToDouble(DurationS * 1000.0) / 1000.0);
	Root->SetNumberField(TEXT("matchTimeStartS"), FMath::RoundToDouble(MatchTimeStartS * 1000.0) / 1000.0);
	TArray<TSharedPtr<FJsonValue>> KillValues;
	for (const FVerseBoutKill& K : KillList)
	{
		TSharedRef<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetNumberField(TEXT("t"), FMath::RoundToDouble(K.T * 1000.0) / 1000.0);
		O->SetStringField(TEXT("killer"), K.Killer == EVerseSide::A ? TEXT("A") : TEXT("B"));
		O->SetStringField(TEXT("cause"), CauseName(K.Cause));
		O->SetBoolField(TEXT("headshot"), K.bHeadshot);
		O->SetBoolField(TEXT("wall"), K.bWall);
		if (K.RangeM >= 0.f)
		{
			O->SetNumberField(TEXT("rangeM"), K.RangeM);
		}
		if (K.TtkS >= 0.f)
		{
			O->SetNumberField(TEXT("ttkS"), K.TtkS);
		}
		O->SetBoolField(TEXT("spawnKill"), K.bSpawnKill);
		KillValues.Add(MakeShared<FJsonValueObject>(O));
	}
	Root->SetArrayField(TEXT("kills"), KillValues);
	Root->SetObjectField(TEXT("a"), SideJson(SideA));
	Root->SetObjectField(TEXT("b"), SideJson(SideB));
	TArray<TSharedPtr<FJsonValue>> Trace;
	for (float S : AdaptiveTrace)
	{
		Trace.Add(MakeShared<FJsonValueNumber>(S));
	}
	Root->SetArrayField(TEXT("adaptiveTrace"), Trace);

	FString Line;
	const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
		TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Line);
	FJsonSerializer::Serialize(Root, Writer);
	return Line;
}

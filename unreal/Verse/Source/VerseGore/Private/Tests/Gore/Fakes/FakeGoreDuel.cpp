#include "Tests/Gore/Fakes/FakeGoreDuel.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Components/PrimitiveComponent.h"
#include "EngineUtils.h"
#include "Gore/VerseGoreSynthetic.h"
#include "UObject/UnrealType.h"

namespace FakeGoreDuelPrivate
{
	uint32 HashString(const FString& Text)
	{
		return FCrc::StrCrc32(*Text);
	}

	uint32 HashVector(const FVector& V)
	{
		return HashCombine(HashCombine(GetTypeHash(FMath::RoundToInt64(V.X * 100.0)), GetTypeHash(FMath::RoundToInt64(V.Y * 100.0))),
			GetTypeHash(FMath::RoundToInt64(V.Z * 100.0)));
	}

	/** Net properties of one actor; object references hash as set or unset (paths name the world). */
	uint32 HashNetProperties(const AActor* Actor)
	{
		uint32 Hash = HashString(Actor->GetClass()->GetName());
		for (TFieldIterator<FProperty> It(Actor->GetClass()); It; ++It)
		{
			const FProperty* Property = *It;
			if (!Property->HasAnyPropertyFlags(CPF_Net))
			{
				continue;
			}
			Hash = HashCombine(Hash, HashString(Property->GetName()));
			if (const FObjectPropertyBase* Object = CastField<FObjectPropertyBase>(Property))
			{
				Hash = HashCombine(Hash, Object->GetObjectPropertyValue_InContainer(Actor) ? 1u : 0u);
				continue;
			}
			FString Value;
			Property->ExportText_InContainer(0, Value, Actor, Actor, nullptr, PPF_None);
			Hash = HashCombine(Hash, HashString(Value));
		}
		return HashCombine(Hash, HashVector(Actor->GetActorLocation()));
	}
}

FFakeGoreDuel::FFakeGoreDuel(VerseGoreTest::FWorld& InWorld, uint32 InSeed)
	: W(InWorld)
	, Seed(InSeed)
{
	for (int32 Index = 0; Index < 2; ++Index)
	{
		FDuellist& D = Duellists[Index];
		D.Id = Index + 1;
		D.Home = FVector(Index == 0 ? -500.0 : 500.0, 0.0, 0.0);
		D.Mesh = W.AddBody(D.Id, D.Home);
		D.Pawn = Cast<APawn>(D.Mesh->GetOwner());
		D.Pawn->SetReplicates(true);
	}
}

void FFakeGoreDuel::Step(double Dt)
{
	Time += Dt;
	++Tick;
	FVerseRng Rng(Seed, uint64(Tick), EVerseRngSalt::Harness);

	for (FDuellist& D : Duellists)
	{
		if (D.Health <= 0.f && Time >= D.RespawnAt)
		{
			D.Health = 100.f;
			D.RespawnAt = -1.f;
		}
		if (D.Health > 0.f)
		{
			const double Phase = Time * (0.6 + 0.1 * D.Id) + D.Id;
			D.Pawn->SetActorLocation(D.Home + FVector(FMath::Sin(Phase) * 250.0, FMath::Cos(Phase * 0.8) * 300.0, 0.0));
		}
	}

	FDuellist& A = Duellists[Tick % 2];
	FDuellist& B = Duellists[(Tick + 1) % 2];
	if (Tick % 3 != 0 || A.Health <= 0.f || B.Health <= 0.f)
	{
		return;
	}

	// Rarely a finisher, else a shot.
	if (Rng.Chance(0.01))
	{
		const double Offsets[] = {0.0, VerseGoreFinisherTimes::Takedown, VerseGoreFinisherTimes::Struggle,
			VerseGoreFinisherTimes::Kill, VerseGoreFinisherTimes::Recover};
		const EVerseFinisherPhase Phases[] = {EVerseFinisherPhase::Locked, EVerseFinisherPhase::Takedown,
			EVerseFinisherPhase::Struggle, EVerseFinisherPhase::Kill, EVerseFinisherPhase::Recover};
		for (int32 I = 0; I < 5; ++I)
		{
			FVerseFinisherEvent Event;
			Event.AttackerId = A.Id;
			Event.VictimId = B.Id;
			Event.Phase = Phases[I];
			Event.SequenceStartServerTime = float(Time);
			Event.WarpTarget = FTransform(B.Pawn->GetActorLocation() - FVector(80.0, 0.0, 0.0));
			W.Hub->OnFinisher.Broadcast(Event);   // phases are cosmetic; the fake applies the kill at once
			(void)Offsets[I];
		}
		B.Health = 0.f;
	}
	else if (Rng.Chance(0.45))
	{
		float Damage = 0.f;
		const double Roll = Rng.NextUnit();
		const EVerseHitZone Zone = Roll < 0.12 ? EVerseHitZone::Head : Roll < 0.5 ? EVerseHitZone::UpperTorso
			: Roll < 0.7 ? EVerseHitZone::LowerTorso : Roll < 0.85 ? EVerseHitZone::Arm : EVerseHitZone::Leg;
		Damage = Zone == EVerseHitZone::Head ? 60.f : Zone == EVerseHitZone::UpperTorso ? 30.f : 24.f;
		const bool bKill = B.Health - Damage <= 0.f;
		const FVerseHitEvent Hit = FVerseGoreSyntheticStream::MakeHit(Zone, B.Pawn->GetActorLocation(),
			A.Pawn->GetActorLocation() + FVector(0.0, 0.0, 160.0), A.Id, B.Id, Damage, ++Shot, float(Time), bKill);
		W.Hub->OnHit.Broadcast(Hit);
		B.Health -= Damage;
	}
	else
	{
		return;
	}

	if (B.Health <= 0.f)
	{
		B.Health = 0.f;
		++B.Deaths;
		++A.Kills;
		B.RespawnAt = float(Time + 3.0);
		FVerseDeathEvent Death;
		Death.VictimId = B.Id;
		Death.KillerId = A.Id;
		Death.ServerTime = float(Time);
		Death.RespawnAt = B.RespawnAt;
		W.Hub->OnDeath.Broadcast(Death);
	}
}

uint32 FFakeGoreDuel::StateHash() const
{
	using namespace FakeGoreDuelPrivate;
	TArray<uint32> ActorHashes;
	int32 Colliding = 0;
	for (TActorIterator<AActor> It(W.World); It; ++It)
	{
		const AActor* Actor = *It;
		if (Actor->GetIsReplicated())
		{
			ActorHashes.Add(HashNetProperties(Actor));
		}
		TInlineComponentArray<UPrimitiveComponent*> Primitives(Actor);
		for (const UPrimitiveComponent* Primitive : Primitives)
		{
			if (Primitive->IsRegistered() && Primitive->IsCollisionEnabled())
			{
				++Colliding;
			}
		}
	}
	ActorHashes.Sort();
	uint32 Hash = GetTypeHash(Colliding);
	for (const uint32 H : ActorHashes)
	{
		Hash = HashCombine(Hash, H);
	}
	for (const FDuellist& D : Duellists)
	{
		Hash = HashCombine(Hash, HashCombine(GetTypeHash(D.Health), HashCombine(GetTypeHash(D.Kills), GetTypeHash(D.Deaths))));
		Hash = HashCombine(Hash, HashVector(D.Pawn->GetActorLocation()));
	}
	return Hash;
}

#endif // WITH_DEV_AUTOMATION_TESTS

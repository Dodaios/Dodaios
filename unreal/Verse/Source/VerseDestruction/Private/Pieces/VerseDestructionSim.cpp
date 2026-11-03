#include "Pieces/VerseDestructionSim.h"

#include "Pieces/VersePieceRules.h"
#include "VerseGameplayTags.h"
#include "VerseLog.h"
#include "VerseRng.h"

using namespace Verse::Destruction;

namespace
{
	int16 QuantizeI16(double Value)
	{
		return int16(FMath::Clamp(FMath::RoundToInt64(Value), int64(-32768), int64(32767)));
	}

	uint8 InstigatorSlot(int32 InstigatorId)
	{
		return (InstigatorId < 0 || InstigatorId >= int32(WorldInstigator)) ? WorldInstigator : uint8(InstigatorId);
	}

	uint32 SecondsToMs(float Seconds)
	{
		return uint32(FMath::Max(0.f, Seconds) * 1000.f + 0.5f);
	}
}

void FVerseDestructionSim::Init(TArray<FVersePieceDef> InDefs, const FVerseDestructionSimTuning& InTuning,
	TConstArrayView<FVector> DroneDocks, uint64 InSeed)
{
	check(InDefs.Num() <= 2000); // destruction.md 8: at most 2,000 pieces per deck
	Defs = MoveTemp(InDefs);
	Tuning = InTuning;
	Seed = InSeed;
	SeedCounter = 0;
	Epoch = 0;
	Nav = FVerseNavDirtyQueue(Tuning.NavMaxTilesInFlight, Tuning.NavDirtyMarginCm);
	Items.SetNum(Defs.Num());
	Server.SetNum(Defs.Num());
	for (int32 Index = 0; Index < Defs.Num(); ++Index)
	{
		FVersePieceItem& Item = Items[Index];
		Item = FVersePieceItem();
		Item.PieceIndex = uint16(Index);
		Item.HealthQ = 255;
		Server[Index] = FServerPiece();
		Server[Index].Hp = Tuning.ClassRow(Defs[Index].Class).MaxHp;
	}
	Drones.Reset();
	for (int32 Index = 0; Index < DroneDocks.Num(); ++Index)
	{
		FVerseDroneState& Drone = Drones.AddDefaulted_GetRef();
		Drone.Index = Index;
		Drone.Dock = DroneDocks[Index];
		Drone.Location = DroneDocks[Index];
		Drone.Hp = Tuning.DroneMaxHp;
	}
	Events.Reset();
	EventOfPiece.Reset();
	Deferred.Reset();
	EventTickMs = 0;
	LastTickMs = 0;
	MulticastTimesMs.Reset();
	Noise.Reset();
	Dirty.Reset();
	Counters = FVerseDestructionCounters();
}

uint32 FVerseDestructionSim::NextSeed()
{
	return FVerseRng(Seed, SeedCounter++, EVerseRngSalt::Fracture).NextU32();
}

void FVerseDestructionSim::SetDef(uint16 PieceIndex, FVersePieceDef Def)
{
	if (!IsValidPiece(PieceIndex))
	{
		return;
	}
	const bool bWasInert = VerseMaterialNeverBreaks(Defs[PieceIndex].Material) && Items[PieceIndex].State == EVersePieceState::Intact;
	Defs[PieceIndex] = MoveTemp(Def);
	if (bWasInert)
	{
		// A piece that streamed in late takes its slot with full HP (destruction.md 8).
		Server[PieceIndex].Hp = Tuning.ClassRow(Defs[PieceIndex].Class).MaxHp;
	}
}

bool FVerseDestructionSim::CanBreak(uint16 PieceIndex) const
{
	return !VerseMaterialNeverBreaks(Defs[PieceIndex].Material);
}

void FVerseDestructionSim::ApplyDamage(const FVersePieceDamage& Damage, uint32 NowMs)
{
	if (!IsValidPiece(Damage.PieceIndex))
	{
		UE_LOG(LogVerseDestruction, Warning, TEXT("ApplyPieceDamage: unknown piece %u"), Damage.PieceIndex);
		return;
	}
	if (Damage.Cause == EVerseFractureCause::Repair || Damage.Cause == EVerseFractureCause::Reset)
	{
		return; // not damage causes
	}
	if (Damage.Cause != EVerseFractureCause::Breach)
	{
		ApplyOne(Damage.PieceIndex, Damage, Rules::EHitRole::Direct, NowMs);
		return;
	}
	ApplyOne(Damage.PieceIndex, Damage, Rules::EHitRole::BreachTarget, NowMs);
	const float Radius = Damage.BreachRadiusCm > 0.f ? Damage.BreachRadiusCm : Tuning.BreachSideRadiusCm;
	for (int32 Index = 0; Index < Defs.Num(); ++Index)
	{
		if (Index != Damage.PieceIndex && Defs[Index].IsWithinRadius(Damage.Location, Radius))
		{
			ApplyOne(uint16(Index), Damage, Rules::EHitRole::BreachSide, NowMs);
		}
	}
}

void FVerseDestructionSim::ApplyOne(uint16 PieceIndex, const FVersePieceDamage& Damage, Rules::EHitRole Role, uint32 NowMs)
{
	if (!CanBreak(PieceIndex))
	{
		return; // DR4
	}
	const FVersePieceDef& Def = Defs[PieceIndex];
	const FVersePieceClassTuning& Row = Tuning.ClassRow(Def.Class);
	FServerPiece& Piece = Server[PieceIndex];
	const uint8 Instigator = InstigatorSlot(Damage.InstigatorId);

	// Any damage while Repairing cancels the repair (destruction.md 7); the damage then applies
	// to the state it was repairing from. Damage while a drone is on its way recalls it.
	if (Items[PieceIndex].State == EVersePieceState::Repairing)
	{
		CancelRepair(PieceIndex, Damage.Cause, Instigator, NowMs);
	}
	else if (Piece.AssignedDrone != INDEX_NONE)
	{
		Recall(Drones[Piece.AssignedDrone], NowMs);
		Piece.AssignedDrone = INDEX_NONE;
	}

	const EVersePieceState Before = Items[PieceIndex].State;
	const float HpBefore = Piece.Hp;
	const Rules::FOutcome Out = Rules::Apply(Row, Before, Piece.Hp, Damage.Cause, Role, Damage.Amount);
	Piece.Hp = Out.Hp;

	const FVector Local = Def.Transform.InverseTransformPosition(Damage.Location);
	if (Damage.Cause == EVerseFractureCause::Bolt)
	{
		Piece.HitSumLocal += Local;
		Piece.HitCount += 1;
	}

	const bool bStateChanged = Out.State != Before;
	const bool bHpChanged = !FMath::IsNearlyEqual(HpBefore, Piece.Hp);
	// Any further damage restarts the 60 s (destruction.md 7), also on a piece already at 0 HP
	// that keeps taking hole-making bolts, so nothing is repaired while it is still under fire
	// and a recalled drone is not sent straight back.
	Piece.LastDamageMs = NowMs;
	if (bStateChanged || bHpChanged)
	{
		Piece.bDamagedSinceRepair = true;
	}
	if (bStateChanged)
	{
		uint8 Variant = Items[PieceIndex].Variant;
		if (Out.State == EVersePieceState::Holed && Before != EVersePieceState::Holed)
		{
			const FVector Centroid = (Damage.Cause == EVerseFractureCause::Bolt && Piece.HitCount > 0)
				? Piece.HitSumLocal / double(Piece.HitCount)
				: Local;
			Variant = FVersePieceDef::NearestVariant(Def.HoledCentroids, Centroid);
		}
		else if (Out.State == EVersePieceState::Breached)
		{
			Variant = FVersePieceDef::NearestVariant(Def.BreachedCentroids, Local);
		}
		else if (Out.State == EVersePieceState::Destroyed || Out.State == EVersePieceState::Damaged)
		{
			Variant = 0;
		}
		float ImpulseNs = Tuning.Start.BoltImpulseNs;
		uint8 Radius = Tuning.Start.BoltStrainRadiusCm;
		if (Damage.Cause == EVerseFractureCause::Melee)
		{
			ImpulseNs = Tuning.Start.MeleeImpulseNs;
			Radius = Tuning.Start.MeleeStrainRadiusCm;
		}
		else if (Damage.Cause == EVerseFractureCause::Breach)
		{
			const float BreachRadius = Damage.BreachRadiusCm > 0.f ? Damage.BreachRadiusCm : Tuning.BreachSideRadiusCm;
			ImpulseNs = Tuning.Start.BreachImpulseNs;
			Radius = uint8(FMath::Clamp(FMath::RoundToInt(BreachRadius), 0, 255));
		}
		const FVector Direction = Damage.Cause == EVerseFractureCause::Breach && Role == Rules::EHitRole::BreachSide
			? (Def.GetWorldBounds(Before, Items[PieceIndex].Variant).GetCenter() - Damage.Location).GetSafeNormal()
			: Damage.Direction.GetSafeNormal();
		SetState(PieceIndex, Out.State, Variant, Damage.Cause, Damage.Location, Direction, ImpulseNs, Radius, Instigator, NowMs);
		if (Out.State != EVersePieceState::Damaged && Out.State != EVersePieceState::Intact)
		{
			Piece.HitSumLocal = FVector::ZeroVector;
			Piece.HitCount = 0;
		}
	}
	else if (bHpChanged)
	{
		WriteHealth(PieceIndex);
	}
}

void FVerseDestructionSim::ApplyHoleCap(uint16 PieceIndex, const FVector& LocalCentroidCm, uint32 NowMs)
{
	if (!IsValidPiece(PieceIndex) || !CanBreak(PieceIndex))
	{
		return;
	}
	const FVersePieceDef& Def = Defs[PieceIndex];
	const FVersePieceClassTuning& Row = Tuning.ClassRow(Def.Class);
	if (Row.HoledAtOrBelowHp < 0.f)
	{
		return; // only wall pieces turn Holed from holes
	}
	if (Items[PieceIndex].State == EVersePieceState::Repairing)
	{
		CancelRepair(PieceIndex, EVerseFractureCause::Bolt, WorldInstigator, NowMs);
	}
	const EVersePieceState Before = Items[PieceIndex].State;
	if (!Rules::IsForward(Before, EVersePieceState::Holed) || Before == EVersePieceState::Holed)
	{
		return;
	}
	FServerPiece& Piece = Server[PieceIndex];
	Piece.Hp = FMath::Min(Piece.Hp, Row.HoledAtOrBelowHp);
	Piece.LastDamageMs = NowMs;
	const uint8 Variant = FVersePieceDef::NearestVariant(Def.HoledCentroids, LocalCentroidCm);
	SetState(PieceIndex, EVersePieceState::Holed, Variant, EVerseFractureCause::Bolt, Def.Transform.TransformPosition(LocalCentroidCm),
		FVector::ZeroVector, Tuning.Start.BoltImpulseNs, Tuning.Start.BoltStrainRadiusCm, WorldInstigator, NowMs);
}

void FVerseDestructionSim::SetState(uint16 PieceIndex, EVersePieceState NewState, uint8 Variant, EVerseFractureCause Cause,
	const FVector& WorldLocation, const FVector& Direction, float ImpulseNs, uint8 RadiusCm, uint8 Instigator, uint32 NowMs)
{
	FVersePieceItem& Item = Items[PieceIndex];
	const FVersePieceDef& Def = Defs[PieceIndex];
	FServerPiece& Piece = Server[PieceIndex];
	const EVersePieceState From = Item.State;
	const EVersePieceState OldProxy = Item.GetProxyState();
	const uint8 OldVariant = Item.Variant;

	Item.State = NewState;
	Item.Variant = Variant;
	Item.RepairFrom = NewState == EVersePieceState::Repairing ? From : EVersePieceState::Intact;
	Item.HealthQ = QuantizeHealth(Piece.Hp, Tuning.ClassRow(Def.Class).MaxHp);
	if (Tuning.ClassRow(Def.Class).MaxHp <= 0.f)
	{
		Item.HealthQ = NewState == EVersePieceState::Destroyed ? 0 : 255;
	}
	Item.LastSeed = NextSeed();
	const FVector Impulse = Direction * (ImpulseNs / ImpulseUnitNs);
	const FVector LocalMm = Def.Transform.InverseTransformPosition(WorldLocation) * 10.0;
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		Item.LastImpulse[Axis] = QuantizeI16(Impulse[Axis]);
		Item.LastLocation[Axis] = QuantizeI16(LocalMm[Axis]);
	}
	Item.StateTimeMs = NowMs;
	Item.Epoch = Epoch;
	if (From == EVersePieceState::Intact && NewState != EVersePieceState::Intact)
	{
		Piece.BrokenSinceMs = NowMs;
	}
	MarkDirty(PieceIndex);
	if (Item.GetProxyState() != OldProxy || Item.Variant != OldVariant)
	{
		MarkNav(PieceIndex, OldProxy, OldVariant);
	}
	Counters.StateChanges += 1;

	FVerseFractureEvent Event;
	Event.PieceIndex = PieceIndex;
	Event.FromState = From;
	Event.ToState = NewState;
	Event.Cause = Cause;
	Event.Variant = Variant;
	Event.Seed = Item.LastSeed;
	for (int32 Axis = 0; Axis < 3; ++Axis)
	{
		Event.Impulse[Axis] = Item.LastImpulse[Axis];
		Event.Location[Axis] = Item.LastLocation[Axis];
	}
	Event.Radius = RadiusCm;
	Event.Instigator = Instigator;
	Event.ServerTimeMs = NowMs;
	Event.Epoch = Epoch;
	PushEvent(Event, NowMs);

	if (Cause != EVerseFractureCause::Repair && Cause != EVerseFractureCause::Reset && From != EVersePieceState::Repairing
		&& NewState != EVersePieceState::Repairing)
	{
		const EVerseFractureNoise Kind = Rules::NoiseKind(Def.Class, Cause, NewState);
		PushNoise(VerseTags::Noise_Fracture, WorldLocation, FractureLoudness(Kind), NowMs);
	}
}

void FVerseDestructionSim::WriteHealth(uint16 PieceIndex)
{
	FVersePieceItem& Item = Items[PieceIndex];
	const float MaxHp = Tuning.ClassRow(Defs[PieceIndex].Class).MaxHp;
	const uint8 Q = QuantizeHealth(Server[PieceIndex].Hp, MaxHp);
	if (MaxHp > 0.f && Q != Item.HealthQ)
	{
		// Only an HP change of at least one quantum costs bandwidth (destruction.md 3.3).
		Item.HealthQ = Q;
		Item.Epoch = Epoch;
		MarkDirty(PieceIndex);
	}
}

void FVerseDestructionSim::CancelRepair(uint16 PieceIndex, EVerseFractureCause Cause, uint8 Instigator, uint32 NowMs)
{
	FServerPiece& Piece = Server[PieceIndex];
	const EVersePieceState Back = Items[PieceIndex].RepairFrom;
	if (Piece.AssignedDrone != INDEX_NONE)
	{
		Recall(Drones[Piece.AssignedDrone], NowMs);
		Piece.AssignedDrone = INDEX_NONE;
	}
	Piece.LastDamageMs = NowMs; // the 60 s restarts
	Counters.RepairsInterrupted += 1;
	SetState(PieceIndex, Back, Items[PieceIndex].Variant, Cause, Defs[PieceIndex].Transform.GetLocation(), FVector::ZeroVector, 0.f, 0,
		Instigator, NowMs);
}

void FVerseDestructionSim::Recall(FVerseDroneState& Drone, uint32 NowMs)
{
	UpdateDroneLocation(Drone, NowMs);
	Drone.TargetPiece = INDEX_NONE;
	StartFlight(Drone, Drone.Dock, NowMs);
	Drone.Task = EVerseDroneTask::Returning;
}

bool FVerseDestructionSim::ApplyDroneDamage(int32 DroneIndex, float Amount, uint32 NowMs)
{
	if (!Drones.IsValidIndex(DroneIndex) || Amount <= 0.f)
	{
		return false;
	}
	FVerseDroneState& Drone = Drones[DroneIndex];
	if (Drone.Task == EVerseDroneTask::Down)
	{
		return false;
	}
	Drone.Hp -= Amount;
	if (Drone.Hp > 0.f)
	{
		return false;
	}
	UpdateDroneLocation(Drone, NowMs);
	const int32 Target = Drone.TargetPiece;
	Drone.TargetPiece = INDEX_NONE;
	Drone.Task = EVerseDroneTask::Down;
	Drone.Generation += 1;
	if (Target != INDEX_NONE)
	{
		Server[Target].AssignedDrone = INDEX_NONE;
		if (Items[Target].State == EVersePieceState::Repairing)
		{
			CancelRepair(uint16(Target), EVerseFractureCause::Bolt, WorldInstigator, NowMs);
		}
		else
		{
			Server[Target].LastDamageMs = NowMs;
		}
	}
	return true;
}

void FVerseDestructionSim::StartFlight(FVerseDroneState& Drone, const FVector& To, uint32 NowMs)
{
	Drone.FlightFrom = Drone.Location;
	Drone.FlightTo = To;
	Drone.FlightStartMs = NowMs;
	const double Speed = FMath::Max(1.f, Tuning.Start.DroneSpeedCmS);
	Drone.FlightEndMs = NowMs + uint32(FMath::CeilToInt64(FVector::Dist(Drone.FlightFrom, To) / Speed * 1000.0));
}

void FVerseDestructionSim::UpdateDroneLocation(FVerseDroneState& Drone, uint32 NowMs) const
{
	if (Drone.Task != EVerseDroneTask::Outbound && Drone.Task != EVerseDroneTask::Returning)
	{
		return;
	}
	const uint32 Span = Drone.FlightEndMs - Drone.FlightStartMs;
	const double Alpha = Span == 0 ? 1.0 : FMath::Clamp(double(NowMs - Drone.FlightStartMs) / double(Span), 0.0, 1.0);
	Drone.Location = FMath::Lerp(Drone.FlightFrom, Drone.FlightTo, Alpha);
}

int32 FVerseDestructionSim::NumActiveDrones() const
{
	int32 Count = 0;
	for (const FVerseDroneState& Drone : Drones)
	{
		Count += Drone.IsActive() ? 1 : 0;
	}
	return Count;
}

void FVerseDestructionSim::Tick(uint32 NowMs, FEncroachFn IsEncroached)
{
	LastTickMs = NowMs;
	const uint32 RecheckMs = SecondsToMs(Tuning.RepairEncroachRecheckS);
	for (FVerseDroneState& Drone : Drones)
	{
		UpdateDroneLocation(Drone, NowMs);
		switch (Drone.Task)
		{
		case EVerseDroneTask::Down:
			// The dock replaces a downed drone; it flies again when a timer fires.
			Drone.Task = EVerseDroneTask::Docked;
			Drone.Location = Drone.Dock;
			Drone.Hp = Tuning.DroneMaxHp;
			break;
		case EVerseDroneTask::Outbound:
			if (NowMs >= Drone.FlightEndMs && Drone.TargetPiece != INDEX_NONE)
			{
				const uint16 PieceIndex = uint16(Drone.TargetPiece);
				FVersePieceItem& Item = Items[PieceIndex];
				const EVersePieceState From = Item.State;
				Drone.Task = EVerseDroneTask::Repairing;
				Drone.RepairEndMs = NowMs + SecondsToMs(Tuning.ClassRow(Defs[PieceIndex].Class).RepairTimeS);
				Drone.NextEncroachCheckMs = Drone.RepairEndMs;
				const uint8 Variant = Item.Variant;
				ensure(From != EVersePieceState::Intact && From != EVersePieceState::Repairing);
				SetState(PieceIndex, EVersePieceState::Repairing, Variant, EVerseFractureCause::Repair, Drone.Location, FVector::ZeroVector, 0.f, 0,
					WorldInstigator, NowMs);
			}
			break;
		case EVerseDroneTask::Repairing:
			if (Drone.TargetPiece != INDEX_NONE && NowMs >= Drone.RepairEndMs && NowMs >= Drone.NextEncroachCheckMs)
			{
				const uint16 PieceIndex = uint16(Drone.TargetPiece);
				const FBox IntactWorld = Defs[PieceIndex].GetWorldBounds(EVersePieceState::Intact, 0).ExpandBy(Tuning.RepairEncroachMarginCm);
				if (IsEncroached(IntactWorld))
				{
					Drone.NextEncroachCheckMs = NowMs + RecheckMs;
					break;
				}
				FServerPiece& Piece = Server[PieceIndex];
				Piece.Hp = Tuning.ClassRow(Defs[PieceIndex].Class).MaxHp;
				Piece.AssignedDrone = INDEX_NONE;
				Piece.bDamagedSinceRepair = false;
				Piece.HitSumLocal = FVector::ZeroVector;
				Piece.HitCount = 0;
				SetState(PieceIndex, EVersePieceState::Intact, 0, EVerseFractureCause::Repair, Drone.Location, FVector::ZeroVector, 0.f, 0,
					WorldInstigator, NowMs);
				Items[PieceIndex].HealthQ = 255;
				Counters.Repairs += 1;
				Drone.TargetPiece = INDEX_NONE;
				StartFlight(Drone, Drone.Dock, NowMs);
				Drone.Task = EVerseDroneTask::Returning;
			}
			break;
		case EVerseDroneTask::Returning:
			if (NowMs >= Drone.FlightEndMs)
			{
				Drone.Task = EVerseDroneTask::Docked;
				Drone.Location = Drone.Dock;
			}
			break;
		case EVerseDroneTask::Docked:
			break;
		}
		if (Drone.Task != EVerseDroneTask::Docked && NowMs >= Drone.NextNoiseMs)
		{
			// Flight and welding are audible to the bot (destruction.md 7 "Noise").
			PushNoise(VerseTags::Noise_Drone, Drone.Location, DroneLoudness, NowMs);
			Drone.NextNoiseMs = NowMs + Tuning.Start.DroneNoiseIntervalMs;
		}
	}
	Dispatch(NowMs);
	Counters.PeakActiveDrones = FMath::Max(Counters.PeakActiveDrones, NumActiveDrones());
}

void FVerseDestructionSim::Dispatch(uint32 NowMs)
{
	const uint32 DelayMs = SecondsToMs(Tuning.RepairDelayS);
	TArray<uint16> Queue;
	for (int32 Index = 0; Index < Items.Num(); ++Index)
	{
		const EVersePieceState State = Items[Index].State;
		const FServerPiece& Piece = Server[Index];
		const bool bBroken = State != EVersePieceState::Intact && State != EVersePieceState::Repairing;
		const bool bHpOnly = State == EVersePieceState::Intact && Piece.bDamagedSinceRepair;
		if ((bBroken || bHpOnly) && Piece.AssignedDrone == INDEX_NONE && NowMs - Piece.LastDamageMs >= DelayMs)
		{
			Queue.Add(uint16(Index));
		}
	}
	if (Queue.Num() == 0)
	{
		return;
	}
	// Catwalks, then walls, then glass, then ceiling panels; longest-broken first within a class.
	Queue.Sort([this](uint16 A, uint16 B)
	{
		const int32 PA = VerseRepairClassPriority(Defs[A].Class);
		const int32 PB = VerseRepairClassPriority(Defs[B].Class);
		if (PA != PB)
		{
			return PA < PB;
		}
		if (Server[A].BrokenSinceMs != Server[B].BrokenSinceMs)
		{
			return Server[A].BrokenSinceMs < Server[B].BrokenSinceMs;
		}
		return A < B;
	});
	for (const uint16 PieceIndex : Queue)
	{
		if (NumActiveDrones() >= Tuning.MaxActiveDrones)
		{
			return;
		}
		const FVector Target = Defs[PieceIndex].GetWorldBounds(EVersePieceState::Intact, 0).GetCenter();
		int32 Best = INDEX_NONE;
		double BestDistSq = TNumericLimits<double>::Max();
		for (FVerseDroneState& Drone : Drones)
		{
			if (!Drone.IsFree())
			{
				continue;
			}
			const double DistSq = FVector::DistSquared(Drone.Location, Target);
			if (DistSq < BestDistSq)
			{
				BestDistSq = DistSq;
				Best = Drone.Index;
			}
		}
		if (Best == INDEX_NONE)
		{
			return;
		}
		FVerseDroneState& Drone = Drones[Best];
		Drone.TargetPiece = PieceIndex;
		StartFlight(Drone, Target, NowMs);
		Drone.Task = EVerseDroneTask::Outbound;
		Server[PieceIndex].AssignedDrone = Best;
	}
}

void FVerseDestructionSim::FullReset(uint32 NowMs)
{
	Epoch = uint16(Epoch + 1);
	int32 Written = 0;
	for (int32 Index = 0; Index < Items.Num(); ++Index)
	{
		FVersePieceItem& Item = Items[Index];
		FServerPiece& Piece = Server[Index];
		const float MaxHp = Tuning.ClassRow(Defs[Index].Class).MaxHp;
		const bool bChanged = Item.State != EVersePieceState::Intact || Item.HealthQ != 255 || Item.Variant != 0;
		const EVersePieceState OldProxy = Item.GetProxyState();
		const uint8 OldVariant = Item.Variant;
		Piece = FServerPiece();
		Piece.Hp = MaxHp;
		if (!bChanged)
		{
			continue; // untouched items cost nothing in the reset burst
		}
		Item.State = EVersePieceState::Intact;
		Item.HealthQ = 255;
		Item.Variant = 0;
		Item.RepairFrom = EVersePieceState::Intact;
		// An Intact piece carries no fracture record, so the reset item packs small.
		Item.LastSeed = 0;
		FMemory::Memzero(Item.LastImpulse, sizeof(Item.LastImpulse));
		FMemory::Memzero(Item.LastLocation, sizeof(Item.LastLocation));
		Item.StateTimeMs = NowMs;
		Item.Epoch = Epoch;
		MarkDirty(uint16(Index));
		MarkNav(uint16(Index), OldProxy, OldVariant);
		++Written;
	}
	for (FVerseDroneState& Drone : Drones)
	{
		if (Drone.Task == EVerseDroneTask::Outbound || Drone.Task == EVerseDroneTask::Repairing)
		{
			Recall(Drone, NowMs);
		}
	}
	// Every changed piece marked its tiles dirty above; the queue rebuilds them (destruction.md 11).
	// The burst is what the fast array sends: its header, then element id and packed item per write.
	LastResetBurstBytes = Written > 0 ? FVersePieceItem::FastArrayHeaderBytes : 0;
	for (const uint16 Index : Dirty)
	{
		LastResetBurstBytes += FVersePieceItem::FastArrayItemIdBytes + FVersePieceItem::MeasureWireBytes(Items[Index]);
	}
	Deferred.Reset();

	FVerseFractureEvent Event;
	Event.PieceIndex = AllPieces;
	Event.FromState = EVersePieceState::Intact;
	Event.ToState = EVersePieceState::Intact;
	Event.Cause = EVerseFractureCause::Reset;
	Event.Instigator = WorldInstigator;
	Event.ServerTimeMs = NowMs;
	Event.Epoch = Epoch;
	// A reset clears whatever this tick held: no stale piece event may follow it.
	Events.Reset();
	EventOfPiece.Reset();
	PushEvent(Event, NowMs);
}

void FVerseDestructionSim::PushEvent(const FVerseFractureEvent& Event, uint32 NowMs)
{
	if (EventTickMs != NowMs)
	{
		EventTickMs = NowMs;
		EventOfPiece.Reset();
	}
	if (Tuning.Start.bCoalescePerTick && Event.PieceIndex != AllPieces)
	{
		if (const int32* Existing = EventOfPiece.Find(Event.PieceIndex))
		{
			// One event per piece per tick: keep the first FromState, take everything else from the latest.
			FVersePendingFracture& Pending = Events[*Existing];
			const EVersePieceState From = Pending.Event.FromState;
			Pending.Event = Event;
			Pending.Event.FromState = From;
			Counters.EventsCoalesced += 1;
			return;
		}
	}
	FVersePendingFracture& Pending = Events.AddDefaulted_GetRef();
	Pending.Event = Event;
	// Multicast rate cap: at most N per sliding second; the fast array stays the truth.
	while (MulticastTimesMs.Num() > 0 && NowMs - MulticastTimesMs[0] >= 1000)
	{
		MulticastTimesMs.RemoveAt(0, 1, EAllowShrinking::No);
	}
	Pending.bMulticast = Event.PieceIndex == AllPieces || MulticastTimesMs.Num() < Tuning.MaxFractureEventsPerSecond;
	if (Pending.bMulticast)
	{
		Deferred.Remove(Event.PieceIndex); // a newer event of the piece supersedes a waiting one
		MulticastTimesMs.Add(NowMs);
		Counters.PeakEventsPerSecond = FMath::Max(Counters.PeakEventsPerSecond, MulticastTimesMs.Num());
	}
	else
	{
		// Over the cap: published locally now, multicast later once the window has room,
		// coalesced per piece (destruction.md 4). The fast array stays the truth meanwhile.
		Counters.EventsOverRate += 1;
		if (FVerseFractureEvent* Waiting = Deferred.Find(Event.PieceIndex))
		{
			const EVersePieceState From = Waiting->FromState;
			*Waiting = Event;
			Waiting->FromState = From;
		}
		else
		{
			Deferred.Add(Event.PieceIndex, Event);
		}
	}
	if (Event.PieceIndex != AllPieces)
	{
		EventOfPiece.Add(Event.PieceIndex, Events.Num() - 1);
	}
}

void FVerseDestructionSim::PushNoise(const FGameplayTag& Tag, const FVector& Location, float Loudness, uint32 NowMs)
{
	FVerseNoiseEvent& Event = Noise.AddDefaulted_GetRef();
	Event.Noise = Tag;
	Event.SourceId = -1;
	Event.Location = Location;
	Event.Loudness = Loudness;
	Event.ServerTime = float(NowMs) / 1000.f;
}

void FVerseDestructionSim::MarkDirty(uint16 PieceIndex)
{
	Dirty.Add(PieceIndex);
}

void FVerseDestructionSim::MarkNav(uint16 PieceIndex, EVersePieceState OldState, uint8 OldVariant)
{
	const FVersePieceDef& Def = Defs[PieceIndex];
	const FVersePieceItem& Item = Items[PieceIndex];
	const FBox Old = Def.GetWorldBounds(OldState, OldVariant);
	const FBox New = Def.GetWorldBounds(Item.GetProxyState(), Item.Variant);
	Nav.MarkDirty(Old, PieceIndex);
	Nav.MarkDirty(New, PieceIndex);
	if (!Old.IsValid && !New.IsValid)
	{
		Nav.MarkDirty(Def.GetWorldBounds(EVersePieceState::Intact, 0), PieceIndex);
	}
}

TArray<FVersePendingFracture> FVerseDestructionSim::DrainEvents()
{
	// Deferred over-rate events go out as soon as the sliding second has room; one older than
	// a second is dropped (the item has long arrived), and so is one of an old epoch.
	if (Deferred.Num() > 0)
	{
		const uint32 NowMs = FMath::Max(EventTickMs, LastTickMs);
		while (MulticastTimesMs.Num() > 0 && NowMs - MulticastTimesMs[0] >= 1000)
		{
			MulticastTimesMs.RemoveAt(0, 1, EAllowShrinking::No);
		}
		for (auto It = Deferred.CreateIterator(); It; ++It)
		{
			const FVerseFractureEvent& Waiting = It.Value();
			if (Waiting.Epoch != Epoch || NowMs - Waiting.ServerTimeMs >= 1000)
			{
				Counters.EventsDeferredDropped += 1;
				It.RemoveCurrent();
				continue;
			}
			if (MulticastTimesMs.Num() >= Tuning.MaxFractureEventsPerSecond)
			{
				break;
			}
			FVersePendingFracture& Late = Events.AddDefaulted_GetRef();
			Late.Event = Waiting;
			Late.bMulticast = true;
			Late.bPublishLocal = false; // published on the server when it happened
			MulticastTimesMs.Add(NowMs);
			Counters.PeakEventsPerSecond = FMath::Max(Counters.PeakEventsPerSecond, MulticastTimesMs.Num());
			Counters.EventsDeferredSent += 1;
			It.RemoveCurrent();
		}
	}
	for (const FVersePendingFracture& Pending : Events)
	{
		Counters.EventsPublished += Pending.bPublishLocal ? 1 : 0;
		Counters.EventsMulticast += Pending.bMulticast ? 1 : 0;
	}
	EventOfPiece.Reset();
	return MoveTemp(Events);
}

TArray<FVerseNoiseEvent> FVerseDestructionSim::DrainNoise()
{
	return MoveTemp(Noise);
}

TArray<uint16> FVerseDestructionSim::DrainDirtyItems()
{
	TArray<uint16> Out = Dirty.Array();
	Out.Sort();
	Counters.ItemWrites += Out.Num();
	Dirty.Reset();
	return Out;
}

FBox FVerseDestructionSim::GetPieceBounds(uint16 PieceIndex) const
{
	if (!IsValidPiece(PieceIndex))
	{
		return FBox(ForceInit);
	}
	const FVersePieceItem& Item = Items[PieceIndex];
	return Defs[PieceIndex].GetWorldBounds(Item.GetProxyState(), Item.Variant);
}

TArray<uint16> FVerseDestructionSim::GetPiecesInBox(const FBox& WorldBox) const
{
	TArray<uint16> Out;
	for (int32 Index = 0; Index < Defs.Num(); ++Index)
	{
		// Pieces are found by their Intact footprint, so a destroyed piece is still listed.
		if (Defs[Index].GetWorldBounds(EVersePieceState::Intact, 0).Intersect(WorldBox))
		{
			Out.Add(uint16(Index));
		}
	}
	return Out;
}

TArray<FVersePieceNavLink> FVerseDestructionSim::GetLiveNavLinks(uint16 PieceIndex, EVersePieceNavLinkKind& OutKind) const
{
	TArray<FVersePieceNavLink> Out;
	if (!IsValidPiece(PieceIndex))
	{
		return Out;
	}
	const FVersePieceDef& Def = Defs[PieceIndex];
	const EVersePieceState State = Items[PieceIndex].GetProxyState();
	const TArray<FVersePieceNavLink>* Source = nullptr;
	if (State == EVersePieceState::Breached)
	{
		OutKind = EVersePieceNavLinkKind::Mantle;
		Source = &Def.MantleLinks;
	}
	else if (State == EVersePieceState::Destroyed)
	{
		OutKind = EVersePieceNavLinkKind::Drop;
		Source = &Def.DropLinks;
	}
	if (Source)
	{
		for (const FVersePieceNavLink& Link : *Source)
		{
			FVersePieceNavLink World;
			World.Start = Def.Transform.TransformPosition(Link.Start);
			World.End = Def.Transform.TransformPosition(Link.End);
			Out.Add(World);
		}
	}
	return Out;
}

uint32 FVerseDestructionSim::ProxyHash(TConstArrayView<FVersePieceItem> InItems)
{
	uint32 Hash = 0x9E3779B9u;
	for (const FVersePieceItem& Item : InItems)
	{
		const uint8 Bytes[4] = {uint8(Item.PieceIndex & 0xFF), uint8(Item.PieceIndex >> 8), uint8(Item.GetProxyState()), Item.Variant};
		Hash = FCrc::MemCrc32(Bytes, sizeof(Bytes), Hash);
	}
	return Hash;
}

#include "Perception/VersePerceptionModel.h"

#include "Bot/VerseBotTier.h"
#include "Noise/VerseAudibilityTable.h"

namespace
{
	/** Standing sample point heights above the pelvis, cm, in EVerseSightSample order, and lateral offsets. */
	struct FSampleOffset
	{
		float Forward;
		float Right;
		float Up;
	};

	// A 180 cm person with the pelvis at about 95 cm: head 170, neck 155, upper torso 135,
	// pelvis 95, shoulders 145 at +-20, knees 50 at +-12.
	constexpr FSampleOffset StandOffsets[8] = {
		{0.f, 0.f, 75.f},
		{0.f, 0.f, 60.f},
		{0.f, 0.f, 40.f},
		{0.f, 0.f, 0.f},
		{0.f, -20.f, 50.f},
		{0.f, 20.f, 50.f},
		{0.f, -12.f, -45.f},
		{0.f, 12.f, -45.f},
	};

	float StanceHeightScale(EVerseStance Stance)
	{
		switch (Stance)
		{
		case EVerseStance::Crouch:
			return 0.6f;
		case EVerseStance::Prone:
		case EVerseStance::Slide:
			return 0.25f;
		default:
			return 1.f;
		}
	}

	EVerseArenaLevel NeighbourLevel(EVerseArenaLevel Level, FVerseRng& Rng)
	{
		switch (Level)
		{
		case EVerseArenaLevel::Floor:
			return EVerseArenaLevel::Mid;
		case EVerseArenaLevel::Upper:
			return EVerseArenaLevel::Mid;
		default:
			return Rng.NextUnit() < 0.5 ? EVerseArenaLevel::Floor : EVerseArenaLevel::Upper;
		}
	}

	uint32 SecondsToMs(float Seconds)
	{
		return Seconds <= 0.f ? 0u : uint32(FMath::RoundToInt64(double(Seconds) * 1000.0));
	}
}

FVersePerceptionBody::FVersePerceptionBody()
{
	for (FVector& Point : SamplePoints)
	{
		Point = FVector::ZeroVector;
	}
}

void FVersePerceptionBody::SetSamplePointsFromStance()
{
	const float Scale = StanceHeightScale(Stance);
	const FRotator Yaw(0.f, FacingYawDeg, 0.f);
	for (int32 Index = 0; Index < 8; ++Index)
	{
		const FSampleOffset& Offset = StandOffsets[Index];
		const FVector Local(Offset.Forward, Offset.Right, Offset.Up * Scale);
		SamplePoints[Index] = Pelvis + Yaw.RotateVector(Local);
	}
}

EVerseArenaLevel FVersePerceptionWorld::ResolveLevel(const FVector& Location) const
{
	if (LevelOf)
	{
		return LevelOf(Location);
	}
	if (Location.Z >= UpperMinZCm)
	{
		return EVerseArenaLevel::Upper;
	}
	return Location.Z >= MidMinZCm ? EVerseArenaLevel::Mid : EVerseArenaLevel::Floor;
}

float FVersePerceptionWorld::ResolveLevelHeight(EVerseArenaLevel Level) const
{
	if (LevelHeightCm)
	{
		return LevelHeightCm(Level);
	}
	switch (Level)
	{
	case EVerseArenaLevel::Mid:
		return MidMinZCm;
	case EVerseArenaLevel::Upper:
		return UpperMinZCm;
	default:
		return 0.f;
	}
}

float FVersePerceptionWorld::ResolveVisibility(const FVector& Location) const
{
	return VisibilityFactor ? FMath::Clamp(VisibilityFactor(Location), 0.f, 1.f) : 1.f;
}

bool FVersePerceptionWorld::Sight(const FVector& Eye, const FVector& Target) const
{
	return TestSight ? TestSight(Eye, Target) : true;
}

FVersePerceptionProfile FVersePerceptionModel::MakeProfile(const UVerseBotTier& Tier, uint32 Seed)
{
	FVersePerceptionProfile Profile;
	Profile.HearingErrorBaseM = Tier.HearingErrorBaseM;
	Profile.HearingErrorPerM = Tier.HearingErrorPerM;
	Profile.ReactionMs = Tier.ReactionMs;
	Profile.PeripheralReactionMul = Tier.PeripheralReactionMul;
	Profile.PartialExposureAcquireMul = Tier.PartialExposureAcquireMul;
	Profile.TrackLatencyMs = Tier.TrackLatencyMs;
	Profile.Seed = Seed;
	return Profile;
}

void FVersePerceptionModel::AddObserver(int32 PlayerId, const FVersePerceptionProfile& Profile)
{
	RemoveObserver(PlayerId);
	FObserver& Observer = Observers.AddDefaulted_GetRef();
	Observer.PlayerId = PlayerId;
	Observer.Profile = Profile;
	Observer.Rng = FVerseRng(Profile.Seed, 0, EVerseRngSalt::Perception);
}

void FVersePerceptionModel::RemoveObserver(int32 PlayerId)
{
	Observers.RemoveAll([PlayerId](const FObserver& Observer) { return Observer.PlayerId == PlayerId; });
}

bool FVersePerceptionModel::HasObserver(int32 PlayerId) const
{
	return Observers.ContainsByPredicate([PlayerId](const FObserver& Observer) { return Observer.PlayerId == PlayerId; });
}

const FVersePerceptionProfile* FVersePerceptionModel::FindProfile(int32 PlayerId) const
{
	const FObserver* Found =
		Observers.FindByPredicate([PlayerId](const FObserver& Observer) { return Observer.PlayerId == PlayerId; });
	return Found ? &Found->Profile : nullptr;
}

TArray<int32> FVersePerceptionModel::GetObserverIds() const
{
	TArray<int32> Ids;
	for (const FObserver& Observer : Observers)
	{
		Ids.Add(Observer.PlayerId);
	}
	return Ids;
}

FVersePerceptionModel::FObserver* FVersePerceptionModel::Find(int32 PlayerId)
{
	return Observers.FindByPredicate([PlayerId](const FObserver& Observer) { return Observer.PlayerId == PlayerId; });
}

void FVersePerceptionModel::OnNoise(const FVerseNoiseEvent& Event)
{
	for (FObserver& Observer : Observers)
	{
		if (Event.SourceId != Observer.PlayerId)
		{
			Observer.PendingNoise.Add(Event);
		}
	}
}

void FVersePerceptionModel::OnFire(const FVerseFireEvent& Event)
{
	FLiveBolt& Bolt = Bolts.AddDefaulted_GetRef();
	Bolt.ShooterId = Event.ShooterId;
	Bolt.ShotCounter = Event.ShotCounter;
	Bolt.Origin = Event.Origin;
	Bolt.Direction = FVector(Event.Direction).GetSafeNormal();
	Bolt.StartS = Event.ServerTime;
	FBodyCues& Cue = Cues.FindOrAdd(Event.ShooterId);
	Cue.LastFireS = Event.ServerTime;
	if (!Event.WeaponId.IsNone())
	{
		Cue.Weapon = Event.WeaponId;
	}
}

void FVersePerceptionModel::OnReload(const FVerseReloadEvent& Event)
{
	FBodyCues& Cue = Cues.FindOrAdd(Event.PlayerId);
	if (!Event.WeaponId.IsNone())
	{
		Cue.Weapon = Event.WeaponId;
	}
	if (Event.bCancelled)
	{
		Cue.ReloadEndS = -1.f;
		return;
	}
	Cue.ReloadStartS = Event.StartServerTime;
	Cue.ReloadEndS = Event.EndServerTime;
}

FVersePerceptionBody FVersePerceptionModel::WithCues(const FVersePerceptionBody& Body, float NowS) const
{
	FVersePerceptionBody Out = Body;
	if (const FBodyCues* Cue = Cues.Find(Body.PlayerId))
	{
		Out.bFiring |= Cue->LastFireS >= 0.f && NowS >= Cue->LastFireS && NowS - Cue->LastFireS <= VersePerception::FiringVisibleS;
		if (Out.HeldWeaponId.IsNone())
		{
			Out.HeldWeaponId = Cue->Weapon;
		}
		Out.bReloading |= NowS >= Cue->ReloadStartS && NowS < Cue->ReloadEndS;
	}
	return Out;
}

void FVersePerceptionModel::OnHit(const FVerseHitEvent& Event)
{
	if (Event.Source == EVerseDamageSource::Bolt)
	{
		for (FLiveBolt& Bolt : Bolts)
		{
			if (Bolt.ShooterId == Event.InstigatorId && Bolt.ShotCounter == Event.ShotCounter)
			{
				Bolt.EndFlightS = float(FVector::Dist(Bolt.Origin, FVector(Event.ImpactWorld)) / VersePerception::BoltSpeedCmS);
			}
		}
	}
	if (Event.bBlockedBySpawnProtection)
	{
		return;
	}
	if (FObserver* Victim = Find(Event.VictimId))
	{
		Victim->PendingHurt.Add(Event);
	}
	if (Event.InstigatorId != Event.VictimId)
	{
		if (FObserver* Instigator = Find(Event.InstigatorId))
		{
			FVerseHudEvent& Hud = Instigator->PendingHud.AddDefaulted_GetRef();
			Hud.Kind = Event.bKillingBlow ? EVerseHudEventKind::KillMarker
				: Event.bHeadshot ? EVerseHudEventKind::HeadshotMarker
								  : EVerseHudEventKind::HitMarker;
			Hud.KillerId = Event.InstigatorId;
			Hud.VictimId = Event.VictimId;
			Hud.Cause = Event.Source;
			Hud.WeaponId = Event.WeaponId;
			Hud.bWallShot = Event.PenetrationCount > 0;
			Hud.ServerTimeMs = SecondsToMs(Event.ServerTime);
		}
	}
}

void FVersePerceptionModel::OnDeath(const FVerseDeathEvent& Event, const FVersePerceptionBody* KillerBody)
{
	for (FObserver& Observer : Observers)
	{
		FVerseHudEvent& Hud = Observer.PendingHud.AddDefaulted_GetRef();
		Hud.Kind = EVerseHudEventKind::Kill;
		Hud.KillerId = Event.KillerId;
		Hud.VictimId = Event.VictimId;
		Hud.Cause = Event.Cause;
		Hud.WeaponId = Event.WeaponId;
		Hud.ServerTimeMs = SecondsToMs(Event.ServerTime);
		// The kill cam shows the victim where the killer stood (bot.md 3.3).
		if (Observer.PlayerId == Event.VictimId && KillerBody && Event.KillerId != Event.VictimId)
		{
			Hud.bKillerPositionShown = true;
			Hud.KillerPosition = KillerBody->Pelvis;
		}
	}
	if (Event.RespawnAt > 0.f)
	{
		Respawns.Add({Event.VictimId, SecondsToMs(Event.RespawnAt)});
	}
}

void FVersePerceptionModel::ResetEvents()
{
	Bolts.Reset();
	Respawns.Reset();
	Cues.Reset();
	for (FObserver& Observer : Observers)
	{
		Observer.PendingNoise.Reset();
		Observer.PendingHurt.Reset();
		Observer.PendingHud.Reset();
		Observer.Contacts.Reset();
	}
}

FVersePerceptionModel::FCone FVersePerceptionModel::ConeFor(bool bAds, float AdsFovDeg)
{
	FCone Cone;
	if (bAds)
	{
		Cone.HalfAngleDeg = 0.5f * AdsFovDeg + VersePerception::AdsMarginDeg;
		Cone.VerticalHalfAngleDeg = VersePerception::AdsVerticalHalfAngleDeg;
	}
	return Cone;
}

FVersePerceptionModel::EConeZone FVersePerceptionModel::Classify(
	const FVector& Eye, const FRotator& View, const FCone& Cone, const FVector& Point)
{
	const FVector Local = View.UnrotateVector(Point - Eye);
	const double Horizontal = FMath::Sqrt(Local.X * Local.X + Local.Y * Local.Y);
	if (Horizontal < KINDA_SMALL_NUMBER && FMath::Abs(Local.Z) < KINDA_SMALL_NUMBER)
	{
		return EConeZone::Inside;
	}
	const double HorizontalDeg = FMath::RadiansToDegrees(FMath::Atan2(FMath::Abs(Local.Y), Local.X));
	const double VerticalDeg = FMath::RadiansToDegrees(FMath::Atan2(FMath::Abs(Local.Z), Horizontal));
	if (VerticalDeg > Cone.VerticalHalfAngleDeg)
	{
		return EConeZone::Outside;
	}
	if (HorizontalDeg <= Cone.HalfAngleDeg)
	{
		return EConeZone::Inside;
	}
	return HorizontalDeg <= Cone.PeripheralHalfAngleDeg ? EConeZone::Peripheral : EConeZone::Outside;
}

FVersePerceptFrame FVersePerceptionModel::BuildFrame(int32 ObserverId, const FVersePerceptionObserverInput& Input,
	TConstArrayView<FVersePerceptionBody> Bodies, const FVersePerceptionWorld& World, uint32 NowMs, float DeltaS)
{
	FVersePerceptFrame Frame;
	Frame.ServerTimeMs = NowMs;
	Frame.Self = Input.Self;

	ClockS = float(double(NowMs) / 1000.0);
	// Respawns that are due reach every other observer's kill feed.
	for (int32 Index = Respawns.Num() - 1; Index >= 0; --Index)
	{
		if (Respawns[Index].AtMs <= NowMs)
		{
			for (FObserver& Other : Observers)
			{
				if (Other.PlayerId != Respawns[Index].PlayerId)
				{
					FVerseHudEvent& Hud = Other.PendingHud.AddDefaulted_GetRef();
					Hud.Kind = EVerseHudEventKind::OpponentRespawned;
					Hud.KillerId = INDEX_NONE;
					Hud.VictimId = Respawns[Index].PlayerId;
					Hud.ServerTimeMs = Respawns[Index].AtMs;
				}
			}
			Respawns.RemoveAt(Index);
		}
	}
	Bolts.RemoveAll([this](const FLiveBolt& Bolt) {
		return ClockS - Bolt.StartS > FMath::Min(Bolt.EndFlightS, VersePerception::BoltMaxLifeS) + 0.25f;
	});

	FObserver* Observer = Find(ObserverId);
	if (!Observer)
	{
		return Frame;
	}

	// Order is fixed (B5): sight, bolts, hearing, hurt, HUD. Only hearing and hurt draw from the RNG.
	BuildSightings(*Observer, Input, Bodies, World, NowMs, Frame);
	BuildBolts(*Observer, Input, World, NowMs, DeltaS, Frame);
	BuildHeard(*Observer, Input, World, NowMs, Frame);
	BuildHurt(*Observer, NowMs, Frame);
	BuildHud(*Observer, NowMs, Frame);
	Observer->LastFrameMs = NowMs;
	Observer->bHasFrame = true;
	return Frame;
}

void FVersePerceptionModel::BuildSightings(FObserver& Observer, const FVersePerceptionObserverInput& Input,
	TConstArrayView<FVersePerceptionBody> Bodies, const FVersePerceptionWorld& World, uint32 NowMs, FVersePerceptFrame& Out)
{
	const FVector Eye = Input.Self.EyeLocation;
	const FRotator View = Input.Self.ViewRotation;
	const FCone Cone = ConeFor(Input.bAds, Input.AdsFovDeg);

	const float NowS = float(double(NowMs) / 1000.0);
	for (const FVersePerceptionBody& Truth : Bodies)
	{
		if (Truth.PlayerId == Observer.PlayerId || !Truth.bAlive)
		{
			continue;
		}
		const FVersePerceptionBody Body = WithCues(Truth, NowS);
		uint8 Mask = 0;
		bool bAnyInside = false;
		bool bAnyPeripheral = false;
		for (int32 Index = 0; Index < 8; ++Index)
		{
			const EConeZone Zone = Classify(Eye, View, Cone, Body.SamplePoints[Index]);
			if (Zone == EConeZone::Outside)
			{
				continue;
			}
			if (World.Sight(Eye, Body.SamplePoints[Index]))
			{
				Mask |= uint8(1u << Index);
				bAnyInside |= Zone == EConeZone::Inside;
				bAnyPeripheral |= Zone == EConeZone::Peripheral;
			}
		}
		const bool bAware = FVector::DistSquared(Eye, Body.Pelvis) <= FMath::Square(VersePerception::AwarenessRadiusCm);
		const bool bPeripheralNotice =
			bAnyPeripheral && (Body.Velocity.Size() > VersePerception::PeripheralSpeedCmS || Body.bFiring);
		// Awareness alone (bot.md 3.1 "felt, heard"): only with a clear line to the body. Behind a
		// wall it is not noticed at all; its noises still reach the hearing path (F2, B2).
		const bool bFeltOnly = bAware && !bAnyInside && !bPeripheralNotice;
		bool bCandidate = bAnyInside || bPeripheralNotice || bAware;
		if (bFeltOnly)
		{
			bool bClearLine = false;
			for (int32 Index = 0; Index < 8 && !bClearLine; ++Index)
			{
				bClearLine = World.Sight(Eye, Body.SamplePoints[Index]);
			}
			bCandidate = bClearLine;
		}

		if (!bCandidate)
		{
			if (FContact* Contact = Observer.Contacts.Find(Body.PlayerId))
			{
				Contact->bVisibleLastTick = false;
			}
			continue;
		}

		FContact& Contact = Observer.Contacts.FindOrAdd(Body.PlayerId);
		if (!Contact.bVisibleLastTick)
		{
			Contact.VisibleSinceMs = NowMs;
			Contact.bVisibleLastTick = true;
		}
		// Dark zones lengthen the time to notice a target by 1 / VisibilityFactor (bot.md 3.1).
		// The base reaction, the peripheral and the partial-exposure multipliers are the aim
		// layer's (bot.md 8.1), so the service adds only the dark-zone part.
		if (!bAware)
		{
			const float Factor = World.ResolveVisibility(Body.Pelvis);
			if (Factor <= 0.f)
			{
				continue;
			}
			const double ExtraMs = double(Observer.Profile.ReactionMs.X) * (1.0 / double(Factor) - 1.0);
			if (double(NowMs - Contact.VisibleSinceMs) < ExtraMs)
			{
				continue;
			}
		}

		FVerseSightPercept& Sight = Out.Sightings.AddDefaulted_GetRef();
		Sight.PerceptId = Observer.NextPerceptId++;
		Sight.PelvisLocation = Body.Pelvis;
		if (bFeltOnly)
		{
			// Felt, not seen: where it is, nothing a look would show (no mask, no visual fields).
			Sight.VisibleMask = 0;
			Sight.bPeripheral = true;
			continue;
		}
		Sight.Velocity = Body.Velocity;
		Sight.FacingYawDeg = Body.FacingYawDeg;
		Sight.FacingPitchDeg = Body.FacingPitchDeg;
		Sight.Stance = Body.Stance;
		Sight.LeanQuantized = Body.LeanQuantized;
		Sight.bAds = Body.bAds;
		Sight.HeldWeaponId = Body.HeldWeaponId;
		Sight.bReloading = Body.bReloading;
		Sight.bSpawnProtected = Body.bSpawnProtected;
		Sight.VisibleMask = Mask;
		Sight.bPeripheral = !bAnyInside;
	}
}

void FVersePerceptionModel::BuildBolts(FObserver& Observer, const FVersePerceptionObserverInput& Input,
	const FVersePerceptionWorld& World, uint32 NowMs, float DeltaS, FVersePerceptFrame& Out)
{
	const FVector Eye = Input.Self.EyeLocation;
	const FRotator View = Input.Self.ViewRotation;
	const FCone Cone = ConeFor(Input.bAds, Input.AdsFovDeg);
	const float NowS = float(double(NowMs) / 1000.0);

	for (const FLiveBolt& Bolt : Bolts)
	{
		if (Bolt.ShooterId == Observer.PlayerId)
		{
			continue;
		}
		const float End = FMath::Min(Bolt.EndFlightS, VersePerception::BoltMaxLifeS);
		const float T1 = FMath::Min(NowS - Bolt.StartS, End);
		const float T0 = FMath::Max(0.f, NowS - FMath::Max(DeltaS, 0.f) - Bolt.StartS);
		if (T1 <= T0)
		{
			continue;
		}
		const float Times[3] = {T1, 0.5f * (T0 + T1), T0};
		for (const float T : Times)
		{
			const FVector Point = Bolt.Origin + Bolt.Direction * (VersePerception::BoltSpeedCmS * T);
			if (Classify(Eye, View, Cone, Point) == EConeZone::Inside && World.Sight(Eye, Point))
			{
				FVerseBoltPercept& Percept = Out.Bolts.AddDefaulted_GetRef();
				Percept.PerceptId = Observer.NextPerceptId++;
				Percept.Position = Point;
				Percept.Direction = Bolt.Direction;
				Percept.ServerTimeMs = NowMs;
				break;
			}
		}
	}
}

void FVersePerceptionModel::BuildHeard(FObserver& Observer, const FVersePerceptionObserverInput& Input,
	const FVersePerceptionWorld& World, uint32 NowMs, FVersePerceptFrame& Out)
{
	if (!World.Audibility)
	{
		Observer.PendingNoise.Reset();
		return;
	}
	const FVector Eye = Input.Self.EyeLocation;
	const EVerseArenaLevel ObserverLevel = World.ResolveLevel(Input.Self.Location);

	for (const FVerseNoiseEvent& Event : Observer.PendingNoise)
	{
		// Every audible range comes from the audibility table (DA_Audibility), never from code.
		const UVerseAudibilityTable& AudibilityTable = *World.Audibility;
		const FVerseAudibilityRow* Row = AudibilityTable.FindRow(Event.Noise);
		if (!Row)
		{
			// Crouch walk, prone crawl and standing still raise no event; an unknown tag is never heard.
			continue;
		}
		const float RangeM = AudibilityTable.GetAudibleRangeM(Event.Noise, Event.Loudness);
		const float DistanceM = float(FVector::Dist(Eye, Event.Location) / 100.0);
		if (DistanceM > RangeM)
		{
			continue;
		}
		const bool bLineOfSight = World.Sight(Eye, Event.Location);
		const float SdM = (Observer.Profile.HearingErrorBaseM + Observer.Profile.HearingErrorPerM * DistanceM) *
			Row->ErrorMultiplier * (bLineOfSight ? 1.f : VersePerception::NoLineOfSightErrorMul);

		const double Dx = Observer.Rng.Gaussian(0.0, double(SdM) * 100.0);
		const double Dy = Observer.Rng.Gaussian(0.0, double(SdM) * 100.0);

		const EVerseArenaLevel TrueLevel = World.ResolveLevel(Event.Location);
		const bool bNear = FMath::Abs(int32(TrueLevel) - int32(ObserverLevel)) <= 1;
		const double Correct = bNear ? VersePerception::LevelGuessNear : VersePerception::LevelGuessFar;
		const EVerseArenaLevel Guess = Observer.Rng.NextUnit() < Correct ? TrueLevel : NeighbourLevel(TrueLevel, Observer.Rng);

		FVerseHeardPercept& Heard = Out.Heard.AddDefaulted_GetRef();
		Heard.PerceptId = Observer.NextPerceptId++;
		Heard.Noise = Event.Noise;
		Heard.ErrorSdM = SdM;
		Heard.LevelGuess = Guess;
		Heard.ServerTimeMs = SecondsToMs(Event.ServerTime);
		if (SdM > 0.f)
		{
			// The height comes from the level guess only, never from the true source.
			Heard.Location = FVector(Event.Location.X + Dx, Event.Location.Y + Dy, World.ResolveLevelHeight(Guess));
		}
		else
		{
			// Noise.Impact: the impact point itself (bot.md 3.2), which is not the opponent's position.
			Heard.Location = Event.Location;
		}
	}
	Observer.PendingNoise.Reset();
}

void FVersePerceptionModel::BuildHurt(FObserver& Observer, uint32 NowMs, FVersePerceptFrame& Out)
{
	if (Observer.PendingHurt.Num() == 0)
	{
		return;
	}
	float Damage = 0.f;
	const FVerseHitEvent& Last = Observer.PendingHurt.Last();
	for (const FVerseHitEvent& Hit : Observer.PendingHurt)
	{
		Damage += Hit.Damage;
	}
	// Direction toward the shooter, uniformly within the +-8 deg cone (bot.md 3.2).
	const FVector From = -FVector(Last.Direction).GetSafeNormal();
	const FVector Noisy = Observer.Rng.ConeDirection(From, VersePerception::HurtDirectionErrorDeg);

	Out.bHasHurt = true;
	Out.Hurt.PerceptId = Observer.NextPerceptId++;
	Out.Hurt.IncomingDirection = Noisy.GetSafeNormal();
	Out.Hurt.Damage = Damage;
	Out.Hurt.Source = Last.Source;
	Out.Hurt.ServerTimeMs = NowMs;
	Observer.PendingHurt.Reset();
}

void FVersePerceptionModel::BuildHud(FObserver& Observer, uint32 NowMs, FVersePerceptFrame& Out)
{
	Out.Hud.Append(Observer.PendingHud);
	Observer.PendingHud.Reset();
}

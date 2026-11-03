#include "Brain/VerseBotBelief.h"

#include "Learning/VerseBotMatchMemory.h"
#include "VerseGameplayTags.h"

namespace
{
	/** Typical opponent speed for predict (4.2), cm/s. */
	constexpr float TypicalSpeedCmS = 450.f;
	/** TopCluster disc radius (4.3), cm. */
	constexpr float TopRadiusCm = 300.f;
	/** Sighting replaces the belief with sd 0.5 m (4.2). */
	constexpr float SightSdCm = 50.f;
	/** Heard likelihood floor (4.2). */
	constexpr float HeardEps = 0.02f;
	/** Spawn prior sd 1.5 m and weights 0.5 / 0.3 / 0.2 (4.2 kill feed). */
	constexpr float SpawnSdCm = 150.f;
	constexpr float SpawnWeights[3] = {0.5f, 0.3f, 0.2f};
	/** The wedge of a hurt or bolt percept, placed along the line at a typical range. */
	constexpr float WedgeRangeCm = 1500.f;
	constexpr float WedgeSdCm = 600.f;
	/** Clear (4.2): Pd 0.95 within 30 m; the coarse belief has no sight test, so it clears softly. */
	constexpr float ClearHalfAngleDeg = 55.f;
	constexpr float ClearRangeCm = 1500.f;
	constexpr float ClearPerStep = 0.12f;
	constexpr float MinWeight = 0.002f;
	constexpr float BeliefLevelCm = 400.f;
	/** Learned priors (7.2): zone-transition weight 0.5 and a 1 % heatmap mix. */
	constexpr float ZoneTransitionGain = 0.5f;
	constexpr float HeatPriorMix = 0.01f;
	constexpr float HeatPriorSdCm = 150.f;

	EVerseArenaLevel LevelOf(const FVector& L)
	{
		const int32 Level = FMath::Clamp(FMath::FloorToInt32(L.Z / BeliefLevelCm), 0, 2);
		return EVerseArenaLevel(Level);
	}
}

void FVerseBotCoarseBelief::Reset()
{
	Hyps.Reset();
	Pieces.Reset();
	Cached = FVerseBotBeliefSummary();
	bDead = false;
	bReload = false;
	NowS = 0.f;
	LastSeenS = -1.0e6f;
	LastSeen = FVector::ZeroVector;
	FacingYaw = 0.f;
	FacingTimeS = -1.0e6f;
	OpponentHealth = 1.f;
	ShotsSinceReload = 0;
}

void FVerseBotCoarseBelief::NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState)
{
	Pieces.Add(PieceIndex, NewState);
}

EVersePieceState FVerseBotCoarseBelief::GetPieceBelief(uint16 PieceIndex) const
{
	const EVersePieceState* S = Pieces.Find(PieceIndex);
	return S ? *S : EVersePieceState::Intact;
}

float FVerseBotCoarseBelief::DiscMass(const FHypothesis& H, const FVector& Location, float RadiusCm)
{
	const float Sd2 = FMath::Max(H.SdCm * H.SdCm, 1.f);
	const float R2 = RadiusCm * RadiusCm;
	const float D2 = float(FVector::DistSquared2D(H.Center, Location));
	const float Inside = 1.f - FMath::Exp(-R2 / (2.f * Sd2));
	const float Off = FMath::Exp(-D2 / (2.f * (Sd2 + 0.5f * R2)));
	return H.Weight * Inside * Off;
}

void FVerseBotCoarseBelief::AddHypothesis(const FHypothesis& H)
{
	if (Hyps.Num() >= MaxHypotheses)
	{
		int32 Low = 0;
		for (int32 i = 1; i < Hyps.Num(); ++i)
		{
			if (Hyps[i].Weight < Hyps[Low].Weight)
			{
				Low = i;
			}
		}
		Hyps.RemoveAt(Low);
	}
	Hyps.Add(H);
}

void FVerseBotCoarseBelief::Normalise()
{
	float Sum = 0.f;
	for (const FHypothesis& H : Hyps)
	{
		Sum += H.Weight;
	}
	if (Sum <= 0.f)
	{
		Hyps.Reset();
		return;
	}
	// Mass below 1 is "somewhere else" (the unexplored rest of the arena); only an excess is scaled.
	if (Sum > 1.f)
	{
		for (FHypothesis& H : Hyps)
		{
			H.Weight /= Sum;
		}
	}
	Hyps.RemoveAll([](const FHypothesis& H) { return H.Weight < MinWeight; });
}

void FVerseBotCoarseBelief::Step(const FVersePerceptFrame& Frame, float DtS, const FVerseBotMatchMemory* Memory, TConstArrayView<FVector> Spawns)
{
	NowS = float(Frame.ServerTimeMs) / 1000.f;
	const FVerseSelfPercept& Self = Frame.Self;

	// Kill feed and hit markers (3.3, 4.2).
	for (const FVerseHudEvent& E : Frame.Hud)
	{
		switch (E.Kind)
		{
		case EVerseHudEventKind::Kill:
			if (E.VictimId != SelfId)
			{
				bDead = true;
				Hyps.Reset();
			}
			break;
		case EVerseHudEventKind::KillMarker:
			bDead = true;
			Hyps.Reset();
			break;
		case EVerseHudEventKind::OpponentRespawned:
		{
			bDead = false;
			Hyps.Reset();
			OpponentHealth = 1.f;
			ShotsSinceReload = 0;
			bReload = false;
			// Public rule: the spawn farthest from the bot; top 3 weighted 0.5 / 0.3 / 0.2.
			TArray<FVector> Ranked(Spawns.GetData(), Spawns.Num());
			Ranked.Sort([&Self](const FVector& A, const FVector& B)
				{ return FVector::DistSquared(A, Self.Location) > FVector::DistSquared(B, Self.Location); });
			for (int32 i = 0; i < FMath::Min(3, Ranked.Num()); ++i)
			{
				FHypothesis H;
				H.Center = Ranked[i];
				H.SdCm = SpawnSdCm;
				H.Weight = SpawnWeights[i];
				H.Level = LevelOf(Ranked[i]);
				H.Support = ESupport::Inferred;
				H.SupportTimeS = NowS;
				Hyps.Add(H);
			}
			break;
		}
		case EVerseHudEventKind::HitMarker:
			OpponentHealth = FMath::Max(0.f, OpponentHealth - 0.25f);
			break;
		case EVerseHudEventKind::HeadshotMarker:
			OpponentHealth = FMath::Max(0.f, OpponentHealth - 0.5f);
			break;
		}
	}

	// Predict: diffuse at the typical speed, drift with the believed velocity.
	for (FHypothesis& H : Hyps)
	{
		H.Center += H.Velocity * DtS;
		H.Velocity *= FMath::Exp(-DtS);
		H.SdCm = FMath::Sqrt(H.SdCm * H.SdCm + FMath::Square(TypicalSpeedCmS * DtS) * 4.f);
		// Learned zone-transition prior (7.2): the mass leans toward the zone the person most
		// often moves on to from here, by 0.5 x the transition probability of the typical speed.
		FVector NextZone;
		float Prob = 0.f;
		if (Memory && Memory->PredictNextZone(H.Center, NextZone, Prob))
		{
			H.Center += (NextZone - H.Center).GetSafeNormal2D() * (ZoneTransitionGain * Prob * TypicalSpeedCmS * DtS);
		}
	}

	const FVerseSightPercept* Sight = nullptr;
	for (const FVerseSightPercept& S : Frame.Sightings)
	{
		if (S.VisibleMask != 0)
		{
			Sight = &S;
			break;
		}
	}

	if (Sight && !bDead)
	{
		// Sighting replaces the grid (4.2).
		Hyps.Reset();
		FHypothesis H;
		H.Center = Sight->PelvisLocation;
		H.SdCm = SightSdCm;
		H.Weight = 1.f;
		H.Level = LevelOf(Sight->PelvisLocation);
		H.Support = ESupport::Seen;
		H.SupportTimeS = NowS;
		H.Velocity = Sight->Velocity;
		Hyps.Add(H);
		LastSeen = Sight->PelvisLocation;
		LastSeenS = NowS;
		FacingYaw = Sight->FacingYawDeg;
		FacingTimeS = NowS;
		if (Sight->bReloading)
		{
			bReload = true;
			ShotsSinceReload = 0;
		}
	}
	else if (!bDead)
	{
		// Clear: mass in the view cone loses weight (no sighting there).
		const FVector Axis = Self.ViewRotation.Vector();
		const float CosHalf = FMath::Cos(FMath::DegreesToRadians(ClearHalfAngleDeg));
		for (FHypothesis& H : Hyps)
		{
			const FVector To = H.Center - Self.EyeLocation;
			const float Dist = float(To.Size());
			if (Dist < ClearRangeCm && Dist > 1.f && float(FVector::DotProduct(To / Dist, Axis)) > CosHalf)
			{
				H.Weight *= 1.f - ClearPerStep;
			}
		}
	}

	if (!bDead)
	{
		for (const FVerseHeardPercept& Heard : Frame.Heard)
		{
			const float SdCm = FMath::Max(Heard.ErrorSdM * VerseBot::CmPerM, 30.f);
			float Best = 0.f;
			int32 BestIndex = INDEX_NONE;
			for (int32 i = 0; i < Hyps.Num(); ++i)
			{
				FHypothesis& H = Hyps[i];
				const float S2 = SdCm * SdCm + H.SdCm * H.SdCm;
				const float L = FMath::Exp(-float(FVector::DistSquared2D(H.Center, Heard.Location)) / (2.f * S2));
				const float LevelW = H.Level == Heard.LevelGuess ? 0.9f : 0.1f;
				H.Weight *= HeardEps + L * LevelW;
				if (L > Best)
				{
					Best = L;
					BestIndex = i;
				}
			}
			if (BestIndex != INDEX_NONE && Best > 0.1f)
			{
				// Fuse (product of Gaussians).
				FHypothesis& H = Hyps[BestIndex];
				const float A = H.SdCm * H.SdCm;
				const float B = SdCm * SdCm;
				H.Center = (H.Center * B + Heard.Location * A) / (A + B);
				H.SdCm = FMath::Sqrt(A * B / (A + B));
				H.Support = ESupport::Heard;
				H.SupportTimeS = NowS;
			}
			else
			{
				FHypothesis H;
				H.Center = Heard.Location;
				H.SdCm = SdCm;
				H.Weight = 0.6f;
				H.Level = Heard.LevelGuess;
				H.Support = ESupport::Heard;
				H.SupportTimeS = NowS;
				AddHypothesis(H);
			}
			if (Heard.Noise == VerseTags::Noise_Shot)
			{
				++ShotsSinceReload;
				bReload = false;
			}
			else if (Heard.Noise == VerseTags::Noise_Reload)
			{
				bReload = true;
				ShotsSinceReload = 0;
			}
			Normalise();
		}

		auto AddWedge = [this](const FVector& From, const FVector& Toward)
		{
			FHypothesis H;
			H.Center = From + Toward.GetSafeNormal() * WedgeRangeCm;
			H.SdCm = WedgeSdCm;
			H.Weight = 0.5f;
			H.Level = LevelOf(H.Center);
			H.Support = ESupport::Inferred;
			H.SupportTimeS = NowS;
			AddHypothesis(H);
		};
		if (Frame.bHasHurt && !Sight)
		{
			AddWedge(Self.EyeLocation, Frame.Hurt.IncomingDirection);
		}
		if (!Sight)
		{
			for (const FVerseBoltPercept& Bolt : Frame.Bolts)
			{
				AddWedge(Bolt.Position, -Bolt.Direction);
			}
		}
	}

	Normalise();
	if (Memory && !bDead && !Sight)
	{
		// Normalise (4.2): 1 % of the learned position heatmap is mixed in, as prior-only mass
		// (it never supports a wall shot or a prefire, 7.3).
		FVector Hot;
		float Share = 0.f;
		if (Memory->HottestCell(FVerseBotMatchMemory::ELayer::Position, NowS, Hot, Share))
		{
			FHypothesis* Existing = Hyps.FindByPredicate([&Hot](const FHypothesis& H)
				{ return H.Support == ESupport::Prior && FVector::DistSquared2D(H.Center, Hot) < 100.f * 100.f; });
			if (Existing)
			{
				Existing->Weight = FMath::Max(Existing->Weight, HeatPriorMix);
			}
			else
			{
				FHypothesis H;
				H.Center = Hot;
				H.SdCm = HeatPriorSdCm;
				H.Weight = HeatPriorMix;
				H.Level = LevelOf(Hot);
				H.Support = ESupport::Prior;
				AddHypothesis(H);
			}
		}
	}
	Refresh(NowS);
	if (Sight)
	{
		Cached.State = EVerseBeliefState::Known;
	}
}

void FVerseBotCoarseBelief::Refresh(float InNowS)
{
	FVerseBotBeliefSummary S;
	S.FacingYawDeg = FacingYaw;
	S.FacingAgeS = InNowS - FacingTimeS;
	S.bReloadNoticed = bReload;
	S.SinceSightingS = InNowS - LastSeenS;
	S.LastSeenLocation = LastSeen;
	S.OpponentHealthFrac = OpponentHealth;
	S.OpponentShotsSinceReload = ShotsSinceReload;
	if (bDead || Hyps.Num() == 0)
	{
		S.State = bDead ? EVerseBeliefState::Dead : EVerseBeliefState::Lost;
		Cached = S;
		return;
	}
	int32 Top = 0;
	float TopMass = -1.f;
	for (int32 i = 0; i < Hyps.Num(); ++i)
	{
		const float M = MassWithin(Hyps[i].Center, TopRadiusCm);
		if (M > TopMass)
		{
			TopMass = M;
			Top = i;
		}
	}
	S.TopCenter = Hyps[Top].Center;
	S.TopLevel = Hyps[Top].Level;
	S.Confidence = FMath::Clamp(TopMass, 0.f, 1.f);
	S.Velocity = Hyps[Top].Velocity;
	float NewestSupport = -1.0e6f;
	bool bSupported = false;
	for (const FHypothesis& H : Hyps)
	{
		if (DiscMass(H, S.TopCenter, TopRadiusCm) > 0.05f * FMath::Max(TopMass, 0.01f)
			&& (H.Support == ESupport::Seen || H.Support == ESupport::Heard))
		{
			bSupported = true;
			NewestSupport = FMath::Max(NewestSupport, H.SupportTimeS);
		}
	}
	S.bPriorOnly = !bSupported;
	S.SupportAgeS = bSupported ? InNowS - NewestSupport : 1.0e6f;
	FVector Mean = FVector::ZeroVector;
	for (const FHypothesis& H : Hyps)
	{
		Mean += H.Center * H.Weight;
	}
	float Var = 0.f;
	for (const FHypothesis& H : Hyps)
	{
		Var += H.Weight * (H.SdCm * H.SdCm + float(FVector::DistSquared2D(H.Center, Mean)));
	}
	S.SpreadCm = FMath::Sqrt(Var);
	S.State = S.Confidence >= 0.5f ? EVerseBeliefState::Tracked
		: S.Confidence >= 0.2f   ? EVerseBeliefState::Rough
								 : EVerseBeliefState::Lost;
	Cached = S;
}

float FVerseBotCoarseBelief::MassWithin(const FVector& Location, float RadiusCm) const
{
	float M = 0.f;
	for (const FHypothesis& H : Hyps)
	{
		M += DiscMass(H, Location, RadiusCm);
	}
	return M;
}

float FVerseBotCoarseBelief::SupportedMassWithin(const FVector& Location, float RadiusCm) const
{
	float M = 0.f;
	for (const FHypothesis& H : Hyps)
	{
		if (H.Support == ESupport::Seen || H.Support == ESupport::Heard)
		{
			M += DiscMass(H, Location, RadiusCm);
		}
	}
	return M;
}

void FVerseBotCoarseBelief::TopCells(int32 N, TArray<FVector>& Out) const
{
	Out.Reset();
	TArray<int32, TInlineAllocator<MaxHypotheses>> Order;
	for (int32 i = 0; i < Hyps.Num(); ++i)
	{
		Order.Add(i);
	}
	Order.Sort([this](int32 A, int32 B) { return Hyps[A].Weight != Hyps[B].Weight ? Hyps[A].Weight > Hyps[B].Weight : A < B; });
	for (int32 i : Order)
	{
		if (Out.Num() >= N)
		{
			return;
		}
		Out.Add(Hyps[i].Center);
	}
	// Fill with points one sd around the strongest hypotheses.
	static const FVector Ring[4] = {FVector(1, 0, 0), FVector(0, 1, 0), FVector(-1, 0, 0), FVector(0, -1, 0)};
	for (int32 i : Order)
	{
		for (const FVector& R : Ring)
		{
			if (Out.Num() >= N)
			{
				return;
			}
			Out.Add(Hyps[i].Center + R * FMath::Min(Hyps[i].SdCm, 300.f));
		}
	}
}

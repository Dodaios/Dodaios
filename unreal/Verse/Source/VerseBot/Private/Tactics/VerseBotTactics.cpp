#include "Tactics/VerseBotTactics.h"

#include "Bot/VerseBotTier.h"

namespace
{
	constexpr float TacticsChestCm = 120.f;
	constexpr float ArriveCm = 70.f;
	/** Sound discipline applies when TopCluster is within 15 m (8.3). */
	constexpr float QuietRangeCm = 1500.f;
	/** DeployBulwark: no cover within 6 m (5.1). */
	constexpr float BulwarkNoCoverCm = 600.f;
	/** Flank window without sight (5.1). */
	constexpr float FlankMinS = 1.5f, FlankMaxS = 8.f;
	/** Stalk: Spread below 2 m, facing seen less than 2 s ago (5.1). */
	constexpr float StalkSpreadCm = 200.f, StalkFacingAgeS = 2.f;
	constexpr float BreachFuseS = 2.5f;
	/** Search (5.1): cells below this mass are not worth a walk; arena points within 4 m count as searched. */
	constexpr float SearchMinMass = 0.05f;
	constexpr float SearchVisitCm = 400.f;
	constexpr float SearchRadiusCm = 6000.f;
	constexpr float SearchRetargetS = 8.f;
	constexpr int32 SearchPathChecks = 5;

	using EState = EVerseBotState;

	bool BeliefUsable(const FVerseBotBeliefSummary& B)
	{
		return B.State == EVerseBeliefState::Known || B.State == EVerseBeliefState::Tracked || B.State == EVerseBeliefState::Rough;
	}

	FVector Chest(const FVector& Pelvis) { return Pelvis + FVector(0, 0, TacticsChestCm - 70.f); }

	/** The believed opponent faces away from the bot: the bot is more than 100 deg off its facing. */
	bool FacingAway(const FVerseBotTacticsContext& Ctx)
	{
		return VerseBotEqs::OffFacingDeg(Ctx.Query, Ctx.Query.Self->Location) > VerseBotEqs::FinisherArcDeg;
	}

	bool Quiet(const FVerseBotTacticsContext& Ctx)
	{
		const float D = float(FVector::Dist2D(Ctx.Query.Self->Location, Ctx.Query.Belief->TopCenter));
		return D < QuietRangeCm && Ctx.Query.Tier->SoundDiscipline >= 0.5f;
	}

	float RollRange(FVerseRng& Rng, float Min, float Max) { return float(Rng.Range(Min, Max)); }
}

namespace VerseBotTactics
{
	void Utilities(const FVerseBotTacticsContext& Ctx, float (&Out)[VerseBot::NumStates])
	{
		for (float& U : Out)
		{
			U = -1.f;
		}
		const UVerseBotTier& T = *Ctx.Query.Tier;
		const FVerseBotBeliefSummary& B = *Ctx.Query.Belief;
		const FVerseBotQueryCache& C = *Ctx.Cache;
		const bool bSight = Ctx.Sighting != nullptr;
		const bool bRecentSight = Ctx.SinceSightS < 0.5f;
		const bool bUsable = BeliefUsable(B);
		const float DistTop = float(FVector::Dist2D(Ctx.Query.Self->Location, B.TopCenter));
		const float Lead = Ctx.HealthFrac - B.OpponentHealthFrac;
		const bool bLow = Ctx.HealthFrac < 0.35f && Ctx.HealthFrac <= B.OpponentHealthFrac;
		const bool bAmmoLow = Ctx.MagazineFrac < 0.1f && Ctx.bPistolLow;
		const FVerseBotCoverResult& Near = C.GetCover(EVerseBotCoverMode::Near);
		const bool bNearCoverClose = Near.bFound && float(FVector::Dist(Near.Point.Location, Ctx.Query.Self->Location)) <= BulwarkNoCoverCm;

		// Attack: known or seen < 0.5 s ago; + health lead; + Aggression.
		if (bSight || bRecentSight)
		{
			Out[int32(EState::Attack)] = 0.6f + 0.3f * T.Aggression + 0.3f * Lead - (Ctx.MagazineFrac <= 0.f ? 0.4f : 0.f);
		}

		// Hold: tracked belief moving toward the bot, good cover with a sightline; + CoverUse.
		if (Near.bFound && (bUsable || bSight) && B.State != EVerseBeliefState::Dead)
		{
			const FVector ToBot = (Ctx.Query.Self->Location - B.TopCenter).GetSafeNormal2D();
			const bool bApproach = FVector::DotProduct(B.Velocity.GetSafeNormal2D(), ToBot) > 0.3f;
			Out[int32(EState::Hold)] = 0.3f + 0.5f * T.CoverUse + (bApproach ? 0.15f : 0.f)
				+ (B.State == EVerseBeliefState::Tracked ? 0.1f : 0.f) - (bSight ? 0.1f : 0.f);
		}

		// Flank: tracked or rough, no sight 1.5-8 s; opponent holding still; + FlankUse.
		if ((B.State == EVerseBeliefState::Tracked || B.State == EVerseBeliefState::Rough) && !bSight
			&& Ctx.SinceSightS >= FlankMinS && Ctx.SinceSightS <= FlankMaxS)
		{
			const bool bStill = B.Velocity.Size2D() < 100.f;
			Out[int32(EState::Flank)] = 0.3f + 0.6f * T.FlankUse + (bStill ? 0.15f : 0.f)
				+ (C.GetCover(EVerseBotCoverMode::Flank).bFound ? 0.05f : 0.f);
		}

		// StalkForFinisher: tracked, Spread < 2 m, static or facing away; hidden approach exists; + StalkUse.
		if (B.State == EVerseBeliefState::Tracked && !bSight && B.SpreadCm < StalkSpreadCm && C.Finisher.bFound)
		{
			const bool bStill = B.Velocity.Size2D() < 100.f;
			const bool bAway = (B.FacingAgeS < StalkFacingAgeS && FacingAway(Ctx)) || B.bReloadNoticed;
			if (bStill || bAway)
			{
				Out[int32(EState::StalkForFinisher)] = 0.4f + 0.8f * T.StalkUse + (bAway ? 0.1f : 0.f);
			}
		}

		// Retreat: own health low vs the estimate, or magazine and pistol both low; + CoverUse.
		if (bLow || bAmmoLow)
		{
			Out[int32(EState::Retreat)] = 0.5f + 0.5f * T.CoverUse + 0.3f * (1.f - Ctx.HealthFrac);
		}

		// Reload: magazine at or below the tactical fraction, no sight, threat low or in cover.
		if (Ctx.MagazineFrac <= T.TacticalReloadAtFrac && !bSight && Ctx.Query.Self->Reserve > 0)
		{
			const bool bSafe = B.Confidence < 0.5f || DistTop > QuietRangeCm || Ctx.bInCover || !bUsable;
			const bool bEmpty = Ctx.MagazineFrac <= 0.f;
			if (bSafe || bEmpty || T.ReloadOnlyWhenSafe < 0.5f)
			{
				Out[int32(EState::Reload)] = (bEmpty ? 0.9f : 0.5f) + 0.4f * (1.f - Ctx.MagazineFrac) + (Ctx.bInCover ? 0.1f * T.ReloadOnlyWhenSafe : 0.f);
			}
		}

		// DeployBulwark: wants to hold or retreat but no cover within 6 m; charge available; + BulwarkUse.
		if (Ctx.bBulwarkReady && !bNearCoverClose && (bUsable || bSight || bLow))
		{
			Out[int32(EState::DeployBulwark)] = 0.35f + 0.6f * T.BulwarkUse;
		}

		// Breach: a believed-intact breachable piece shortens the path or opens an angle; + BreachUse.
		if (Ctx.bBreachReady && C.Breach.bFound && bUsable && !bSight)
		{
			Out[int32(EState::Breach)] = 0.25f + 0.6f * T.BreachUse + 0.2f * FMath::Clamp(C.Breach.Score, 0.f, 1.f);
		}

		// Wallbang: authority holds, bot unseen; + WallbangUse.
		if (Ctx.bWallbangAuthorised && !bSight && Ctx.SinceHurtS > 1.f)
		{
			Out[int32(EState::Wallbang)] = 0.45f + 0.6f * T.WallbangUse;
		}

		// Search: belief rough or lost (or the opponent is respawning).
		{
			const float Base = B.State == EVerseBeliefState::Lost ? 0.7f
				: B.State == EVerseBeliefState::Dead           ? 0.6f
				: B.State == EVerseBeliefState::Rough          ? 0.45f
															   : 0.15f;
			Out[int32(EState::Search)] = bSight ? 0.05f : Base;
		}
	}

	void Enter(EVerseBotState State, const FVerseBotTacticsContext& Ctx, FVerseBotTacticsMemory& Mem, FVerseRng& Rng)
	{
		const FVerseBotQueryCache& C = *Ctx.Cache;
		switch (State)
		{
		case EState::Hold:
			Mem.HoldPhase = EVerseBotHoldPhase::Go;
			Mem.bHasCover = C.GetCover(EVerseBotCoverMode::Near).bFound;
			Mem.Cover = C.GetCover(EVerseBotCoverMode::Near).Point;
			Mem.bHasPeek = false;
			break;
		case EState::Retreat:
			Mem.bHasCover = C.GetCover(EVerseBotCoverMode::Far).bFound || C.GetCover(EVerseBotCoverMode::Near).bFound;
			Mem.Cover = C.GetCover(EVerseBotCoverMode::Far).bFound ? C.GetCover(EVerseBotCoverMode::Far).Point : C.GetCover(EVerseBotCoverMode::Near).Point;
			break;
		case EState::Reload:
			Mem.bHasCover = C.GetCover(EVerseBotCoverMode::Near).bFound;
			Mem.Cover = C.GetCover(EVerseBotCoverMode::Near).Point;
			break;
		case EState::DeployBulwark:
			Mem.bHasCover = C.GetCover(EVerseBotCoverMode::Bulwark).bFound;
			Mem.Cover = C.GetCover(EVerseBotCoverMode::Bulwark).Point;
			break;
		case EState::Flank:
		{
			const FVerseBotCoverResult& F = C.GetCover(EVerseBotCoverMode::Flank);
			if (F.bFound)
			{
				Mem.FlankPoint = F.Point.Location;
			}
			else
			{
				// A point 90-130 deg off the believed facing at the preferred range.
				const FVector Facing = VerseBotEqs::BeliefFacing(Ctx.Query);
				const float Side = Rng.Chance(0.5) ? 1.f : -1.f;
				const FVector Dir = Facing.RotateAngleAxis(Side * RollRange(Rng, 90.f, 130.f), FVector::UpVector);
				Mem.FlankPoint = Ctx.Query.Belief->TopCenter + Dir * Ctx.Query.PreferredRangeCm;
			}
			Mem.bHasFlankPoint = true;
			break;
		}
		case EState::StalkForFinisher:
			Mem.StalkStartS = Ctx.Query.NowS;
			break;
		case EState::Breach:
			Mem.bBreachPlanted = false;
			Mem.BreachPiece = C.Breach.PieceIndex;
			break;
		case EState::Wallbang:
			Mem.BurstShots = 0;
			Mem.BurstPauseUntilS = 0.f;
			break;
		case EState::Search:
			Mem.bHasSearchTarget = false;
			break;
		case EState::Attack:
			Mem.StrafeSign = Rng.Chance(0.5) ? 1 : -1;
			Mem.StrafeUntilS = Ctx.Query.NowS + RollRange(Rng, Ctx.Query.Tier->StrafeMs.X, Ctx.Query.Tier->StrafeMs.Y) / 1000.f;
			break;
		default:
			break;
		}
	}

	FVerseBotIntent Tick(EVerseBotState State, const FVerseBotTacticsContext& Ctx, FVerseBotTacticsMemory& Mem, FVerseRng& Rng)
	{
		FVerseBotIntent I;
		const UVerseBotTier& T = *Ctx.Query.Tier;
		const FVerseBotBeliefSummary& B = *Ctx.Query.Belief;
		const FVerseSelfPercept& Self = *Ctx.Query.Self;
		const float Now = Ctx.Query.NowS;
		const FVector TopChest = B.TopCenter + FVector(0, 0, TacticsChestCm);

		auto LookAtBelief = [&]()
		{
			I.bHasLookTarget = B.State != EVerseBeliefState::Lost && B.State != EVerseBeliefState::Dead;
			I.LookTarget = TopChest;
		};
		auto MoveTo = [&](const FVector& Target)
		{
			I.bHasMoveTarget = float(FVector::Dist2D(Target, Self.Location)) > ArriveCm;
			I.MoveTarget = Target;
			return !I.bHasMoveTarget;
		};

		switch (State)
		{
		case EState::Attack:
		{
			const FVector Target = Ctx.Sighting ? Chest(Ctx.Sighting->PelvisLocation) : Chest(B.LastSeenLocation);
			I.bHasLookTarget = true;
			I.LookTarget = Target;
			I.bWantFire = true;
			const float Dist = float(FVector::Dist2D(Target, Self.Location));
			I.bAds = Dist > T.AdsRangeM * VerseBot::CmPerM;
			if (Now >= Mem.StrafeUntilS)
			{
				Mem.StrafeSign = -Mem.StrafeSign;
				Mem.StrafeUntilS = Now + RollRange(Rng, T.StrafeMs.X, T.StrafeMs.Y) / 1000.f;
			}
			I.Strafe = Mem.StrafeSign;
			// Hold the preferred band; close in only with a reason (reloading, low, out of range).
			const bool bReason = (Ctx.Sighting && Ctx.Sighting->bReloading) || B.OpponentHealthFrac < 0.35f
				|| Dist > 1.4f * Ctx.Query.PreferredRangeCm;
			const FVector Away = (Self.Location - Target).GetSafeNormal2D();
			if (bReason)
			{
				MoveTo(Target + Away * 0.6f * Ctx.Query.PreferredRangeCm);
			}
			else if (Dist < 0.6f * Ctx.Query.PreferredRangeCm)
			{
				MoveTo(Self.Location + Away * 300.f);
			}
			break;
		}
		case EState::Hold:
		{
			LookAtBelief();
			if (!Mem.bHasCover)
			{
				I.bWantFire = Ctx.Sighting != nullptr;
				break;
			}
			switch (Mem.HoldPhase)
			{
			case EVerseBotHoldPhase::Go:
				if (MoveTo(Mem.Cover.Location))
				{
					Mem.HoldPhase = EVerseBotHoldPhase::Hide;
					Mem.PhaseUntilS = Now + RollRange(Rng, HideMinS, HideMaxS);
				}
				I.bSprint = !Quiet(Ctx) && FVector::Dist2D(Mem.Cover.Location, Self.Location) > 600.f;
				I.bWalk = Quiet(Ctx);
				break;
			case EVerseBotHoldPhase::Hide:
				MoveTo(Mem.Cover.Location);
				I.Stance = Mem.Cover.bHigh ? EVerseStance::Stand : EVerseStance::Crouch;
				I.bWantFire = false;
				if (Now >= Mem.PhaseUntilS && Ctx.MagazineFrac > T.TacticalReloadAtFrac && Ctx.HealthFrac > 0.3f
					&& Ctx.Cache->Peek.bFound)
				{
					Mem.HoldPhase = EVerseBotHoldPhase::Peek;
					Mem.PhaseUntilS = Now + RollRange(Rng, PeekMinS, PeekMaxS);
					Mem.bHasPeek = true;
					Mem.Peek = Ctx.Cache->Peek;
					if (Mem.RecentPeekEdges.Num() >= 3)
					{
						Mem.RecentPeekEdges.RemoveAt(0);
					}
					Mem.RecentPeekEdges.Add(Mem.Cover.EdgeId);
				}
				else if (Now >= Mem.PhaseUntilS)
				{
					Mem.PhaseUntilS = Now + RollRange(Rng, HideMinS, HideMaxS);
				}
				break;
			case EVerseBotHoldPhase::Peek:
				MoveTo(Mem.Peek.StandPoint);
				I.bAds = true;
				I.bWantFire = Ctx.Sighting != nullptr;
				switch (Mem.Peek.Type)
				{
				case EVerseBotPeekType::LeanLeft: I.Lean = -1; break;
				case EVerseBotPeekType::LeanRight: I.Lean = 1; break;
				case EVerseBotPeekType::JumpPeek: I.bJump = true; break;
				default: break;
				}
				if (Now >= Mem.PhaseUntilS)
				{
					Mem.HoldPhase = EVerseBotHoldPhase::Hide;
					Mem.PhaseUntilS = Now + RollRange(Rng, HideMinS, HideMaxS);
				}
				break;
			}
			break;
		}
		case EState::Flank:
		{
			LookAtBelief();
			if (Mem.bHasFlankPoint)
			{
				MoveTo(Mem.FlankPoint);
			}
			I.bWalk = Quiet(Ctx);
			I.bSprint = !I.bWalk;
			I.bWantFire = Ctx.Sighting != nullptr;
			break;
		}
		case EState::StalkForFinisher:
		{
			LookAtBelief();
			const FVerseBotFinisherResult& F = Ctx.Cache->Finisher;
			I.Stance = EVerseStance::Crouch;
			I.bWalk = true;
			if (F.bFound)
			{
				MoveTo(F.Approach);
			}
			// The melee press becomes the finisher when the rules allow it (combat-state 7.2).
			if (float(FVector::Dist2D(B.TopCenter, Self.Location)) <= VerseBotEqs::FinisherRangeCm && Ctx.Query.World->CanActivateFinisher())
			{
				I.bMelee = true;
			}
			break;
		}
		case EState::Retreat:
		{
			LookAtBelief();
			if (Mem.bHasCover)
			{
				MoveTo(Mem.Cover.Location);
			}
			I.bSprint = true;
			I.bReload = Ctx.Sighting == nullptr && Ctx.MagazineFrac < 1.f;
			I.bWantFire = Ctx.Sighting != nullptr && Ctx.MagazineFrac > 0.f;
			break;
		}
		case EState::Reload:
		{
			LookAtBelief();
			const bool bCoverClose = Mem.bHasCover && float(FVector::Dist2D(Mem.Cover.Location, Self.Location)) < 600.f;
			if (bCoverClose && !Ctx.bInCover)
			{
				MoveTo(Mem.Cover.Location);
			}
			I.Stance = (Mem.bHasCover && !Mem.Cover.bHigh && Ctx.bInCover) ? EVerseStance::Crouch : EVerseStance::Stand;
			I.bReload = true;
			break;
		}
		case EState::DeployBulwark:
		{
			LookAtBelief();
			const bool bThere = !Mem.bHasCover || MoveTo(Mem.Cover.Location);
			if (bThere && !Mem.bBulwarkDeployed && Ctx.bBulwarkReady)
			{
				I.bGadgetA = true;
				Mem.bBulwarkDeployed = true;
				Mem.BulwarkDeployedS = Now;
			}
			if (Mem.bBulwarkDeployed)
			{
				I.Stance = EVerseStance::Crouch;
				I.bWantFire = Ctx.Sighting != nullptr;
			}
			break;
		}
		case EState::Breach:
		{
			const FVerseBotBreachResult& Br = Ctx.Cache->Breach;
			if (!Mem.bBreachPlanted)
			{
				if (Br.bFound && MoveTo(Br.PlantPoint))
				{
					I.bHasLookTarget = true;
					I.LookTarget = Br.PlantPoint;
					I.bGadgetB = true;
					Mem.bBreachPlanted = true;
					Mem.BreachPlantedS = Now;
					Mem.BreachPiece = Br.PieceIndex;
				}
				I.bWalk = Quiet(Ctx);
			}
			else if (Now - Mem.BreachPlantedS < BreachFuseS + 0.3f)
			{
				// Step back out of the self-damage radius and wait for the detonation.
				MoveTo(Br.bFound ? Br.WaitPoint : Self.Location);
				LookAtBelief();
			}
			else
			{
				// Through the opening toward the belief.
				LookAtBelief();
				MoveTo(B.TopCenter);
				I.bWantFire = Ctx.Sighting != nullptr;
			}
			break;
		}
		case EState::Wallbang:
		{
			const FVerseBotWallbangResult& W = Ctx.Cache->Wallbang;
			I.bHasLookTarget = true;
			I.LookTarget = W.bFound ? W.AimPoint : TopChest;
			if (W.bFound)
			{
				MoveTo(W.FireFrom);
			}
			// Bursts; authority is re-checked by the fire gate on every shot.
			if (Now >= Mem.BurstPauseUntilS)
			{
				I.bWantFire = true;
				if (++Mem.BurstShots >= FMath::Max(1, T.MaxBurstShots) * 6)
				{
					Mem.BurstShots = 0;
					Mem.BurstPauseUntilS = Now + 0.4f;
				}
			}
			break;
		}
		case EState::Search:
		{
			const bool bArrived = Mem.bHasSearchTarget && float(FVector::Dist2D(Mem.SearchTarget, Self.Location)) < ArriveCm * 3.f;
			if (!Mem.bHasSearchTarget || bArrived || Now >= Mem.SearchUntilS)
			{
				if (bArrived || Now >= Mem.SearchUntilS)
				{
					// Mark the arena points around the reached (or abandoned) target as searched.
					TArray<FVerseBotCoverPoint> Near;
					Ctx.Query.World->GetCoverPoints(Mem.SearchTarget, SearchVisitCm, Near);
					for (const FVerseBotCoverPoint& P : Near)
					{
						Mem.Visited.Add(P.Id, Now);
					}
				}
				// Highest belief mass per path metre among the top cells.
				TArray<FVector> Cells;
				Ctx.Query.BeliefMap->TopCells(8, Cells);
				float Best = -1.f;
				for (const FVector& Cell : Cells)
				{
					const float Mass = Ctx.Query.BeliefMap->MassWithin(Cell, 300.f);
					if (Mass < SearchMinMass || float(FVector::Dist2D(Cell, Self.Location)) < ArriveCm * 3.f)
					{
						continue;
					}
					const float Len = FMath::Max(float(FVector::Dist(Cell, Self.Location)), 100.f) / VerseBot::CmPerM;
					const float V = Mass / Len;
					if (V > Best)
					{
						Best = V;
						Mem.SearchTarget = Cell;
					}
				}
				if (Best < 0.f)
				{
					// The rest of the mass is unexplored arena: the least recently searched point
					// per metre of distance (static arena data, 3.3).
					TArray<FVerseBotCoverPoint> Points;
					Ctx.Query.World->GetCoverPoints(Self.Location, SearchRadiusCm, Points);
					TArray<TPair<float, FVector>, TInlineAllocator<64>> Ranked;
					for (const FVerseBotCoverPoint& P : Points)
					{
						const float* Last = Mem.Visited.Find(P.Id);
						const float Age = Last ? Now - *Last : 120.f;
						const float Dist = float(FVector::Dist2D(P.Location, Self.Location)) / VerseBot::CmPerM;
						if (Dist < 3.f)
						{
							continue;
						}
						Ranked.Emplace(FMath::Min(Age, 120.f) / (Dist + 8.f) + float(Rng.Range(0.0, 0.01)), P.Location);
					}
					Ranked.StableSort([](const TPair<float, FVector>& A, const TPair<float, FVector>& B) { return A.Key > B.Key; });
					// The best few by gain that a path actually reaches.
					float BestGain = -1.f;
					for (int32 i = 0; i < FMath::Min(Ranked.Num(), SearchPathChecks); ++i)
					{
						if (Ctx.Query.World->FindPath(Self.Location, Ranked[i].Value, false).bValid)
						{
							BestGain = Ranked[i].Key;
							Mem.SearchTarget = Ranked[i].Value;
							break;
						}
					}
					if (BestGain < 0.f)
					{
						Mem.SearchTarget = Self.Location + Self.ViewRotation.Vector().GetSafeNormal2D() * 1200.f;
					}
				}
				Mem.bHasSearchTarget = true;
				Mem.SearchUntilS = Now + SearchRetargetS;
			}
			MoveTo(Mem.SearchTarget);
			// Sweep the view to clear cells.
			Mem.SearchSweepPhase += 0.05f;
			const FVector Ahead = (Mem.SearchTarget - Self.Location).GetSafeNormal2D();
			const FVector Sweep = Ahead.RotateAngleAxis(40.f * FMath::Sin(Mem.SearchSweepPhase), FVector::UpVector);
			I.bHasLookTarget = true;
			I.LookTarget = Self.EyeLocation + Sweep * 1000.f;
			I.bWalk = Quiet(Ctx);
			I.Stance = (I.bWalk && T.SoundDiscipline >= 0.8f) ? EVerseStance::Crouch : EVerseStance::Stand;
			I.bWantFire = Ctx.Sighting != nullptr;
			break;
		}
		}
		return I;
	}

	void WantedQueries(EVerseBotState Current, const FVerseBotTacticsContext& Ctx, TArray<EVerseBotQuery, TInlineAllocator<8>>& Out)
	{
		Out.Reset();
		const FVerseBotBeliefSummary& B = *Ctx.Query.Belief;
		const UVerseBotTier& T = *Ctx.Query.Tier;
		auto Add = [&Out](EVerseBotQuery Q) { Out.AddUnique(Q); };
		switch (Current)
		{
		case EState::Hold: Add(EVerseBotQuery::PeekCorner); Add(EVerseBotQuery::CoverNear); break;
		case EState::Retreat: Add(EVerseBotQuery::CoverFar); break;
		case EState::Flank: Add(EVerseBotQuery::CoverFlank); break;
		case EState::StalkForFinisher: Add(EVerseBotQuery::FinisherApproach); break;
		case EState::Breach: Add(EVerseBotQuery::BreachSpot); break;
		case EState::Wallbang: Add(EVerseBotQuery::WallbangSpot); break;
		case EState::DeployBulwark: Add(EVerseBotQuery::CoverBulwark); break;
		default: break;
		}
		if (B.State == EVerseBeliefState::Dead)
		{
			return;
		}
		Add(EVerseBotQuery::CoverNear);
		const bool bUsable = BeliefUsable(B);
		if (bUsable && Ctx.Sighting == nullptr)
		{
			if (T.WallbangUse > 0.f && !B.bPriorOnly)
			{
				Add(EVerseBotQuery::WallbangSpot);
			}
			if (B.SpreadCm < StalkSpreadCm * 1.5f && B.Confidence >= T.FinisherCommitConfidence)
			{
				Add(EVerseBotQuery::FinisherApproach);
			}
			Add(EVerseBotQuery::CoverFlank);
			if (Ctx.bBreachReady && T.BreachUse > 0.f)
			{
				Add(EVerseBotQuery::BreachSpot);
			}
		}
		if (Ctx.HealthFrac < 0.5f || Ctx.MagazineFrac < 0.2f)
		{
			Add(EVerseBotQuery::CoverFar);
		}
		if (Ctx.bBulwarkReady && T.BulwarkUse > 0.f)
		{
			Add(EVerseBotQuery::CoverBulwark);
		}
	}
}

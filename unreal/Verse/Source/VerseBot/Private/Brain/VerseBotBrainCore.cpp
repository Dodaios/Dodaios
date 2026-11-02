#include "Brain/VerseBotBrainCore.h"

#include "Bot/VerseBotTier.h"
#include "VerseGameplayTags.h"

namespace
{
	/** Belief step rate (bot.md 2): 10 Hz plus at once on a positive percept. */
	constexpr float BeliefStepS = 0.1f;
	/** Attack bonus on an acquired sighting (5.2). */
	constexpr float AcquireBonus = 0.4f;
	/** Contact lost after 3 s ends an engagement (7.1). */
	constexpr float EngagementLostS = 3.f;
	/** Stuck: wants to move, moved less than 0.5 m in 3 s (BG12). */
	constexpr float StuckWindowS = 3.f;
	constexpr float StuckMinMoveCm = 50.f;
	constexpr float StuckReplanS = 1.f;
	/** Knife reflex inside 2 m frontal, finisher reflex inside 1.5 m rear or flank (5.2). */
	constexpr float KnifeRangeCm = 200.f;
	constexpr float FinisherRangeCm = 150.f;
	constexpr float WaypointReachCm = 60.f;
	constexpr float BrainChestCm = 120.f;
	/** A sighting starting within 1.5 m of a cover edge counts as a peek there (7.1). */
	constexpr float PeekEdgeRadiusCm = 150.f;
	constexpr float InCoverCm = 90.f;

	const FVerseSightPercept* FirstVisible(const FVersePerceptFrame& F)
	{
		for (const FVerseSightPercept& S : F.Sightings)
		{
			if (S.VisibleMask != 0)
			{
				return &S;
			}
		}
		return nullptr;
	}

	uint32 MaskBits(EVerseInputButton B) { return uint32(B); }
}

FVerseBotBrainCore::FVerseBotBrainCore()
	: Belief(MakeUnique<FVerseBotCoarseBelief>())
	, Aim(MakeUnique<FVerseBotFollowAim>())
{
}

FVerseBotBrainCore::~FVerseBotBrainCore() = default;

void FVerseBotBrainCore::Init(const UVerseBotTier& InTier, const FConfig& InConfig)
{
	Config = InConfig;
	Tier = &InTier;
	DecisionRng = FVerseRng(Config.Seed, 1, EVerseRngSalt::Brain);
	TacticsRng = FVerseRng(Config.Seed, 2, EVerseRngSalt::Brain);
	ReflexRng = FVerseRng(Config.Seed, 3, EVerseRngSalt::Brain);
	Memory->Reset();
	Memory->Configure(InTier);
	Memory->SetEnabled(Config.bLearning);
	Audit.Reset();
	Belief->Reset();
	if (bCoarseBelief)
	{
		static_cast<FVerseBotCoarseBelief*>(Belief.Get())->SetSelfId(Config.SelfId);
	}
	Aim->Reset(FVerseRng::Mix(Config.Seed ^ 0xA1u), InTier);
	TacticsMem.Reset();
	Cache.Reset();
	Selector.Reset(EVerseBotState::Search, 0.f);
	Pending.Reset();
	Path = FVerseBotPath();
	PathTarget = FVector(1.0e9);
	PathIndex = 0;
	NowS = 0.f;
	LastThinkS = -1.f;
	NextDecisionS = 0.f;
	NextBeliefStepS = 0.f;
	LastBeliefStepS = 0.f;
	DecisionIndex = 0;
	FMemory::Memzero(StateCounts);
	bHadSighting = false;
	LastSightingS = -1.0e6f;
	bWasAlive = false;
	LastMagazine = -1;
	LastHurtS = -1.0e6f;
	AttackBonusUntilS = -1.f;
	bInEngagement = false;
	bFirstContactDone = false;
	StuckEvents = 0;
	bStuckCounted = false;
	PrevButtons = 0;
	LastHeardS = -1.0e6f;
	LastSightRecordS = -1.0e6f;
	LastOpponentKillS = -1.0e6f;
	bPistolRolled = bPistolChosen = bKnifeRolled = bKnifeChosen = false;
	QueryCursor = 0;
	PathDecision = -1;
	LastSeenLocation = FVector::ZeroVector;
	LastSightPerceptId = 0;
	LastHeard = FVerseHeardPercept();
	SightingThisTick = FVerseSightPercept();
	bSightingThisTick = false;
	EngagementRangeCm = 0.f;
	EngagementLastS = -1.0e6f;
	LastPersonZone = INDEX_NONE;
	StuckRef = FVector::ZeroVector;
	StuckSinceS = 0.f;
	bStuckReplanned = false;
	VisibleBurst = 0;
	BurstRestUntilS = 0.f;
	BeliefSummary = FVerseBotBeliefSummary();
	Spawns.Reset();
	bSpawnsFetched = false;
}

void FVerseBotBrainCore::SetTier(const UVerseBotTier& InTier)
{
	Tier = &InTier;
	Memory->Configure(InTier);
	Aim->Reset(FVerseRng::Mix(Config.Seed ^ uint64(DecisionIndex)), InTier);
}

void FVerseBotBrainCore::SetBelief(TUniquePtr<IVerseBotBelief> InBelief)
{
	if (InBelief)
	{
		Belief = MoveTemp(InBelief);
		bCoarseBelief = false;
	}
}

void FVerseBotBrainCore::SetAimDriver(TUniquePtr<IVerseBotAimDriver> InAim)
{
	if (InAim)
	{
		Aim = MoveTemp(InAim);
		if (Tier)
		{
			Aim->Reset(FVerseRng::Mix(Config.Seed ^ 0xA1u), *Tier);
		}
	}
}

void FVerseBotBrainCore::UseMemory(FVerseBotMatchMemory& InMemory)
{
	Memory = &InMemory;
	if (Tier)
	{
		Memory->Configure(*Tier);
	}
	Memory->SetEnabled(Config.bLearning);
}

void FVerseBotBrainCore::ResetMatch()
{
	Memory->Reset();
	Belief->Reset();
	Audit.Reset();
	TacticsMem.Reset();
	Cache.Reset();
	Pending.Reset();
	Path = FVerseBotPath();
	Selector.Reset(EVerseBotState::Search, NowS);
	bInEngagement = false;
	bFirstContactDone = false;
}

FVerseBotPresentation FVerseBotBrainCore::GetPresentation() const
{
	FVerseBotPresentation P;
	P.State = Selector.Current();
	P.StateTag = VerseBot::StateTag(P.State);
	P.HoldPhase = TacticsMem.HoldPhase;
	P.bHasCoverSpot = TacticsMem.bHasCover;
	P.CoverSpot = TacticsMem.Cover.Location;
	P.bHasPeekPoint = TacticsMem.bHasPeek;
	P.PeekPoint = TacticsMem.Peek.Eye;
	const FVerseBotBeliefSummary S = Belief->Summary();
	P.BeliefTop = S.TopCenter;
	P.Confidence = S.Confidence;
	return P;
}

void FVerseBotBrainCore::OnOwnDeath()
{
	// Tree stops; belief and plan cleared; match memory kept (5.2).
	Belief->Reset();
	TacticsMem.Reset();
	Cache.Reset();
	Pending.Reset();
	Path = FVerseBotPath();
	PathTarget = FVector(1.0e9);
	if (bInEngagement)
	{
		Memory->RecordEngagementEnd(EngagementRangeCm, true);
		bInEngagement = false;
	}
}

void FVerseBotBrainCore::OnOwnRespawn()
{
	Selector.Force(EVerseBotState::Search, NowS);
	TacticsVisibleReset();
	bFirstContactDone = false;
	NextDecisionS = NowS;
}

void FVerseBotBrainCore::TacticsVisibleReset()
{
	bHadSighting = false;
	LastSightingS = -1.0e6f;
	AttackBonusUntilS = -1.f;
	VisibleBurst = 0;
}

void FVerseBotBrainCore::BuildContext(const FVersePerceptFrame& Frame, IVerseBotWorldQueries& World)
{
	const UVerseBotTier& T = *Tier;
	FVerseBotQueryContext& Q = Ctx.Query;
	Q.Self = &Frame.Self;
	Q.Belief = &BeliefSummary;
	Q.BeliefMap = Belief.Get();
	Q.World = &World;
	Q.Memory = Memory->IsEnabled() ? Memory : nullptr;
	Q.Tier = Tier;
	Q.NowS = NowS;
	Q.Weapon = World.GetOwnWeapon();
	Q.RecentPeekEdges = TacticsMem.RecentPeekEdges;
	const float BaseRange = T.PreferredRangeM * VerseBot::CmPerM;
	const int32 Shift = Q.Memory ? Q.Memory->RangeBinShift(BaseRange) : 0;
	Q.PreferredRangeCm = Shift == 0 ? BaseRange
		: FVerseBotMatchMemory::RangeBinCentreCm(FVerseBotMatchMemory::RangeBin(BaseRange) + Shift);

	Ctx.Frame = &Frame;
	Ctx.Cache = &Cache;
	Ctx.Sighting = bSightingThisTick ? &SightingThisTick : nullptr;
	Ctx.RecentHeardAgeS = NowS - LastHeardS;
	Ctx.RecentHeard = Ctx.RecentHeardAgeS <= 2.f ? &LastHeard : nullptr;
	const FVerseSelfPercept& S = Frame.Self;
	Ctx.HealthFrac = S.MaxHealth > 0.f ? FMath::Clamp(S.Health / S.MaxHealth, 0.f, 1.f) : 1.f;
	const int32 MagSize = FMath::Max(Q.Weapon.MagazineSize, 1);
	Ctx.MagazineFrac = FMath::Clamp(float(S.Magazine) / float(MagSize), 0.f, 1.f);
	Ctx.bPistolLow = S.ActiveSlot == EVerseLoadoutSlot::Secondary ? Ctx.MagazineFrac < 0.2f : S.Reserve <= 0;
	Ctx.SinceSightS = NowS - LastSightingS;
	Ctx.SinceHurtS = NowS - LastHurtS;
	Ctx.bBulwarkReady = S.GadgetCharges[0] > 0 && S.GadgetCooldownS[0] <= 0.f;
	Ctx.bBreachReady = S.GadgetCharges[1] > 0 && S.GadgetCooldownS[1] <= 0.f;
	Ctx.bInCover = TacticsMem.bHasCover && float(FVector::Dist2D(TacticsMem.Cover.Location, S.Location)) < InCoverCm;

	// Wall-shot authority on the cached spot (4.5), rechecked against the current belief.
	Ctx.bWallbangAuthorised = false;
	if (Cache.Wallbang.bFound && Ctx.Sighting == nullptr)
	{
		FVerseBotFireEvidence& E = Ctx.WallbangEvidence;
		E = FVerseBotFireEvidence();
		E.AimPoint = BeliefSummary.TopCenter + FVector(0, 0, BrainChestCm);
		E.bAimInTopCluster = true;
		E.TraceDamageFrac = Cache.Wallbang.DamageFrac;
		E.TracePieces = Cache.Wallbang.Pieces;
		E.MassAtAim = Belief->MassWithin(E.AimPoint, FVerseBotFireClassifier::MassRadiusCm);
		E.SupportedMassAtAim = Belief->SupportedMassWithin(E.AimPoint, FVerseBotFireClassifier::MassRadiusCm);
		E.SupportAgeS = BeliefSummary.SupportAgeS;
		E.bPriorOnly = BeliefSummary.bPriorOnly;
		Ctx.bWallbangAuthorised = FVector::Dist(Cache.Wallbang.AimPoint, E.AimPoint) < FVerseBotFireClassifier::MassRadiusCm
			&& FVerseBotFireClassifier::HasWallShotAuthority(E, T);
	}
}

void FVerseBotBrainCore::UpdateLearning(const FVersePerceptFrame& Frame)
{
	if (!Memory->IsEnabled())
	{
		return;
	}
	// Learned from percepts only (7).
	if (bSightingThisTick)
	{
		const FVector P = SightingThisTick.PelvisLocation;
		const bool bStart = !bHadSighting;
		if (bStart || NowS - LastSightRecordS >= 0.1f)
		{
			LastSightRecordS = NowS;
			Memory->RecordSighting(P, NowS, !bFirstContactDone);
			bFirstContactDone = true;
			const int32 Zone = WorldThisTick->GetZoneId(P);
			Memory->RecordZone(Zone, NowS);
		}
		if (bStart && Ctx.SinceSightS > 1.f)
		{
			TArray<FVerseBotCoverPoint> Edges;
			WorldThisTick->GetCoverPoints(P, PeekEdgeRadiusCm, Edges);
			for (const FVerseBotCoverPoint& E : Edges)
			{
				if (E.EdgeId != INDEX_NONE)
				{
					const EVerseBotPeekType Type = SightingThisTick.LeanQuantized < -20 ? EVerseBotPeekType::LeanLeft
						: SightingThisTick.LeanQuantized > 20                          ? EVerseBotPeekType::LeanRight
						: SightingThisTick.Velocity.Z > 150.f                          ? EVerseBotPeekType::JumpPeek
						: SightingThisTick.Stance == EVerseStance::Crouch              ? EVerseBotPeekType::CrouchRise
																					  : EVerseBotPeekType::StepOut;
					Memory->RecordPeek(E.EdgeId, Type, NowS);
					break;
				}
			}
		}
		if (Frame.bHasHurt || Frame.Bolts.Num() > 0)
		{
			Memory->RecordShotFrom(P, NowS, true);
		}
		if (SightingThisTick.Stance == EVerseStance::Slide)
		{
			Memory->RecordHabit(TEXT("slide"));
		}
		if (SightingThisTick.Stance == EVerseStance::Prone)
		{
			Memory->RecordHabit(TEXT("prone"));
		}
		bInEngagement = true;
		EngagementRangeCm = float(FVector::Dist(P, Frame.Self.Location));
		EngagementLastS = NowS;
	}
	else if (bInEngagement && NowS - EngagementLastS > EngagementLostS)
	{
		Memory->RecordEngagementEnd(EngagementRangeCm, false);
		bInEngagement = false;
	}
	for (const FVerseHeardPercept& H : Frame.Heard)
	{
		Memory->RecordHeard(H.Location, NowS);
		if (H.Noise == VerseTags::Noise_Shot)
		{
			Memory->RecordShotFrom(H.Location, NowS, false);
		}
		else if (H.Noise == VerseTags::Noise_Gadget_BulwarkDeploy)
		{
			Memory->RecordHabit(TEXT("bulwark"));
		}
		else if (H.Noise == VerseTags::Noise_Finisher)
		{
			Memory->RecordHabit(TEXT("finisher"));
		}
		else if (H.Noise == VerseTags::Noise_Reload && NowS - LastOpponentKillS < 3.f)
		{
			Memory->RecordHabit(TEXT("after_kill_reload"));
		}
	}
	for (const FVerseHudEvent& E : Frame.Hud)
	{
		if (E.Kind == EVerseHudEventKind::Kill && E.VictimId != Config.SelfId)
		{
			LastOpponentKillS = NowS;
			if (bInEngagement)
			{
				Memory->RecordEngagementEnd(EngagementRangeCm, false);
				bInEngagement = false;
			}
		}
	}
}

bool FVerseBotBrainCore::ForcedTriggers(const FVersePerceptFrame& Frame, float (&Bonus)[VerseBot::NumStates])
{
	bool bForce = false;
	// Sighting acquired (after reaction): force, Attack +0.4.
	if (bSightingThisTick && !bHadSighting)
	{
		bForce = true;
		AttackBonusUntilS = NowS + 0.05f;
	}
	if (NowS <= AttackBonusUntilS)
	{
		Bonus[int32(EVerseBotState::Attack)] += AcquireBonus;
	}
	// Sight lost: 0.35 s suppression, then a decision.
	if (!bSightingThisTick && bHadSighting)
	{
		NextDecisionS = FMath::Min(NextDecisionS, NowS + FVerseBotFireClassifier::SuppressionS);
	}
	// Hit taken: force, Retreat and Hold + damage / max health.
	if (Frame.bHasHurt)
	{
		bForce = true;
		const float Frac = Frame.Self.MaxHealth > 0.f ? Frame.Hurt.Damage / Frame.Self.MaxHealth : 0.f;
		Bonus[int32(EVerseBotState::Retreat)] += Frac;
		Bonus[int32(EVerseBotState::Hold)] += Frac;
		LastHurtS = NowS;
	}
	// Magazine empty.
	if (LastMagazine > 0 && Frame.Self.Magazine == 0)
	{
		bForce = true;
	}
	LastMagazine = Frame.Self.Magazine;
	return bForce;
}

void FVerseBotBrainCore::Decide(bool bInterrupt, const float (&Bonus)[VerseBot::NumStates])
{
	const UVerseBotTier& T = *Tier;
	Ctx.Query.bIgnoreLearned = DecisionRng.Chance(T.ExplorationRate);
	float Util[VerseBot::NumStates];
	VerseBotTactics::Utilities(Ctx, Util);
	const FVerseBotUtilitySelector::FDecision D = Selector.Decide(Util, Bonus, T.UtilityNoise, bInterrupt, NowS, DecisionRng);
	if (D.bChanged)
	{
		VerseBotTactics::Enter(D.State, Ctx, TacticsMem, TacticsRng);
	}
	++StateCounts[int32(D.State)];
	++DecisionIndex;
	NextDecisionS = NowS + T.DecisionMs / 1000.f * float(DecisionRng.Range(0.8, 1.2));

	// Schedule EQS: at most 2 in flight; round-robin over the wanted list so every query refreshes.
	TArray<EVerseBotQuery, TInlineAllocator<8>> Wanted;
	VerseBotTactics::WantedQueries(D.State, Ctx, Wanted);
	if (Wanted.Num() > 0 && Pending.Num() < 2)
	{
		// The current state's own query (first) always goes in; the rest rotate.
		if (!Pending.Contains(Wanted[0]))
		{
			Pending.Add(Wanted[0]);
		}
		for (int32 i = 0; i < Wanted.Num() && Pending.Num() < 2; ++i)
		{
			const EVerseBotQuery Q = Wanted[(QueryCursor + i) % Wanted.Num()];
			if (!Pending.Contains(Q))
			{
				Pending.Add(Q);
				QueryCursor = (QueryCursor + i + 1) % FMath::Max(1, Wanted.Num());
				break;
			}
		}
	}
}

void FVerseBotBrainCore::RunScheduledQuery()
{
	if (Pending.Num() == 0)
	{
		return;
	}
	const EVerseBotQuery Q = Pending[0];
	Pending.RemoveAt(0);
	const FVerseBotQueryContext& C = Ctx.Query;
	switch (Q)
	{
	case EVerseBotQuery::CoverNear: Cache.Cover[int32(EVerseBotCoverMode::Near)] = VerseBotEqs::Cover(C, EVerseBotCoverMode::Near); break;
	case EVerseBotQuery::CoverFar: Cache.Cover[int32(EVerseBotCoverMode::Far)] = VerseBotEqs::Cover(C, EVerseBotCoverMode::Far); break;
	case EVerseBotQuery::CoverFlank: Cache.Cover[int32(EVerseBotCoverMode::Flank)] = VerseBotEqs::Cover(C, EVerseBotCoverMode::Flank); break;
	case EVerseBotQuery::CoverBulwark: Cache.Cover[int32(EVerseBotCoverMode::Bulwark)] = VerseBotEqs::Cover(C, EVerseBotCoverMode::Bulwark); break;
	case EVerseBotQuery::PeekCorner:
	{
		const FVerseBotCoverPoint& From = TacticsMem.bHasCover ? TacticsMem.Cover : Cache.GetCover(EVerseBotCoverMode::Near).Point;
		Cache.Peek = VerseBotEqs::PeekCorner(C, From);
		break;
	}
	case EVerseBotQuery::WallbangSpot: Cache.Wallbang = VerseBotEqs::WallbangSpot(C); break;
	case EVerseBotQuery::BreachSpot: Cache.Breach = VerseBotEqs::BreachSpot(C); break;
	case EVerseBotQuery::FinisherApproach: Cache.Finisher = VerseBotEqs::FinisherApproach(C); break;
	default: break;
	}
	Cache.ProducedAt[int32(Q)] = DecisionIndex;
}

void FVerseBotBrainCore::Reflexes(FVerseBotIntent& Intent)
{
	const UVerseBotTier& T = *Tier;
	const FVerseSelfPercept& S = *Ctx.Query.Self;
	if (!bSightingThisTick)
	{
		bPistolRolled = false;
		bKnifeRolled = false;
		return;
	}
	const FVector Opp = SightingThisTick.PelvisLocation;
	const float Dist = float(FVector::Dist2D(Opp, S.Location));
	// Spawn protection (opponent, visible): hold fire, pre-aim.
	if (SightingThisTick.bSpawnProtected)
	{
		Intent.bWantFire = false;
		Intent.bHasLookTarget = true;
		Intent.LookTarget = Opp + FVector(0, 0, BrainChestCm - 70.f);
		return;
	}
	// Finisher: within 1.5 m in the opponent's rear or flank arc, in every state.
	const FVector OppFacing = FRotator(0.f, SightingThisTick.FacingYawDeg, 0.f).Vector();
	const FVector OppToBot = (S.Location - Opp).GetSafeNormal2D();
	const float OffDeg = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(OppFacing, OppToBot)), -1.f, 1.f)));
	if (Dist <= FinisherRangeCm && OffDeg > 60.f && WorldThisTick->CanActivateFinisher())
	{
		Intent.bMelee = true;
		Intent.bWantFire = false;
		return;
	}
	// Knife: within 2 m frontal, magazine empty or the KnifeChoice roll.
	if (Dist <= KnifeRangeCm)
	{
		if (!bKnifeRolled)
		{
			bKnifeRolled = true;
			bKnifeChosen = ReflexRng.Chance(T.KnifeChoice);
		}
		if (S.Magazine == 0 || bKnifeChosen)
		{
			Intent.bMelee = true;
			Intent.bWantFire = false;
			return;
		}
	}
	else
	{
		bKnifeRolled = false;
	}
	// Magazine empty with a target in sight: pistol with PistolSwitchChance, else Retreat.
	if (S.Magazine == 0 && S.ActiveSlot == EVerseLoadoutSlot::Primary)
	{
		if (!bPistolRolled)
		{
			bPistolRolled = true;
			bPistolChosen = ReflexRng.Chance(T.PistolSwitchChance);
			if (!bPistolChosen)
			{
				Selector.Force(EVerseBotState::Retreat, NowS);
				VerseBotTactics::Enter(EVerseBotState::Retreat, Ctx, TacticsMem, TacticsRng);
			}
		}
		if (bPistolChosen)
		{
			Intent.bSwitchSecondary = true;
		}
	}
}

void FVerseBotBrainCore::ApplyFireGate(FVerseBotIntent& Intent, const FVerseBotAimResult& AimResult)
{
	if (!Intent.bWantFire || !Intent.bHasLookTarget)
	{
		Intent.bWantFire = false;
		return;
	}
	const UVerseBotTier& T = *Tier;
	FVerseBotFireEvidence E;
	E.ServerTimeMs = FrameThisTick->ServerTimeMs;
	E.AimPoint = Intent.LookTarget;
	E.bTargetVisible = bSightingThisTick && !SightingThisTick.bSpawnProtected
		&& float(FVector::Dist(Intent.LookTarget, SightingThisTick.PelvisLocation)) < 200.f;
	E.SightPerceptId = bSightingThisTick ? SightingThisTick.PerceptId : LastSightPerceptId;
	E.bTargetSpawnProtected = bSightingThisTick && SightingThisTick.bSpawnProtected;
	E.SinceSightLostS = bSightingThisTick ? 0.f : NowS - LastSightingS;
	E.LastSeenLocation = LastSeenLocation + FVector(0, 0, BrainChestCm - 70.f);
	E.HeardAgeS = NowS - LastHeardS;
	E.HeardLocation = LastHeard.Location;
	E.HeardSdCm = LastHeard.ErrorSdM * VerseBot::CmPerM;
	E.HeardPerceptId = LastHeard.PerceptId;
	E.MassAtAim = Belief->MassWithin(E.AimPoint, FVerseBotFireClassifier::MassRadiusCm);
	E.SupportedMassAtAim = Belief->SupportedMassWithin(E.AimPoint, FVerseBotFireClassifier::MassRadiusCm);
	E.SupportAgeS = BeliefSummary.SupportAgeS;
	E.bPriorOnly = BeliefSummary.bPriorOnly;
	E.bAimInTopCluster = float(FVector::Dist2D(E.AimPoint, BeliefSummary.TopCenter)) <= 300.f;
	E.bPrefireRolled = false;
	if (!E.bTargetVisible && E.SinceSightLostS > FVerseBotFireClassifier::SuppressionS)
	{
		const FVerseBotBoltTrace Trace = WorldThisTick->TraceBolt(FrameThisTick->Self.EyeLocation, E.AimPoint, Ctx.Query.Weapon);
		E.TraceDamageFrac = Trace.DamageFrac;
		E.TracePieces = Trace.Pieces;
	}
	const EVerseBotFireMode Mode = FVerseBotFireClassifier::Classify(E, T);
	const bool bAimed = AimResult.bOnTarget || (Mode != EVerseBotFireMode::Visible && AimResult.ErrorDeg < 2.f);
	if (Mode == EVerseBotFireMode::Unclassified || !bAimed)
	{
		Intent.bWantFire = false;
		return;
	}
	Audit.Add(FVerseBotFireClassifier::MakeAudit(E, Mode));
}

FVector FVerseBotBrainCore::NextWaypoint(const FVector& Target, bool bCrouch)
{
	const FVector Self = FrameThisTick->Self.Location;
	// Re-plan on a new target (> 1 m away from the old one) or on a new decision.
	if (FVector::DistSquared(Target, PathTarget) > 100.f * 100.f || PathDecision != DecisionIndex)
	{
		Path = WorldThisTick->FindPath(Self, Target, bCrouch);
		PathTarget = Target;
		PathIndex = 0;
		PathDecision = DecisionIndex;
	}
	if (!Path.bValid || Path.Waypoints.Num() == 0)
	{
		return Target;
	}
	while (PathIndex < Path.Waypoints.Num() - 1 && FVector::Dist2D(Path.Waypoints[PathIndex], Self) < WaypointReachCm)
	{
		++PathIndex;
	}
	return Path.Waypoints[PathIndex];
}

FVerseInputFrame FVerseBotBrainCore::ToInput(const FVerseBotIntent& Intent, const FVerseBotAimResult& AimResult, uint32 ServerTimeMs)
{
	FVerseInputFrame F;
	F.ServerTimeMs = ServerTimeMs;
	const FVerseSelfPercept& S = FrameThisTick->Self;
	FVector2f Move = FVector2f::ZeroVector;
	if (Intent.bHasMoveTarget)
	{
		const FVector Way = NextWaypoint(Intent.MoveTarget, Intent.Stance == EVerseStance::Crouch);
		const FVector Dir = (Way - S.Location).GetSafeNormal2D();
		const FVector Local = FRotator(0.f, S.ViewRotation.Yaw, 0.f).UnrotateVector(Dir);
		Move = FVector2f(float(Local.X), float(Local.Y));
	}
	if (Intent.Strafe != 0)
	{
		Move.Y = FMath::Clamp(Move.Y + 0.8f * float(Intent.Strafe), -1.f, 1.f);
	}
	const float Len = Move.Size();
	if (Len > 1.f)
	{
		Move /= Len;
	}
	if (Intent.bWalk)
	{
		Move *= 0.45f;
	}
	F.Move = Move;
	F.LookDeltaDeg = AimResult.LookDeltaDeg;

	uint32 B = 0;
	if (Intent.bWantFire) B |= MaskBits(EVerseInputButton::Fire);
	if (Intent.bAds && !Intent.bSprint && !Intent.bSlide) B |= MaskBits(EVerseInputButton::Ads);
	if (Intent.bReload) B |= MaskBits(EVerseInputButton::Reload);
	if (Intent.bMelee) B |= MaskBits(EVerseInputButton::Melee);
	if (Intent.bJump) B |= MaskBits(EVerseInputButton::Jump);
	if (Intent.Stance == EVerseStance::Crouch || Intent.bSlide) B |= MaskBits(EVerseInputButton::Crouch);
	if (Intent.Stance == EVerseStance::Prone) B |= MaskBits(EVerseInputButton::Prone);
	if ((Intent.bSprint || Intent.bSlide) && !Intent.bWantFire && Move.X > 0.5f) B |= MaskBits(EVerseInputButton::Sprint);
	if (Intent.Lean < 0) B |= MaskBits(EVerseInputButton::LeanLeft);
	if (Intent.Lean > 0) B |= MaskBits(EVerseInputButton::LeanRight);
	if (Intent.bGadgetA) B |= MaskBits(EVerseInputButton::GadgetA);
	if (Intent.bGadgetB) B |= MaskBits(EVerseInputButton::GadgetB);
	if (Intent.bSwitchSecondary) B |= MaskBits(EVerseInputButton::SlotSecondary);
	if (Intent.bSwitchPrimary) B |= MaskBits(EVerseInputButton::SlotPrimary);
	F.Buttons = B;
	F.Pressed = B & ~PrevButtons;
	PrevButtons = B;
	return F;
}

FVerseInputFrame FVerseBotBrainCore::Think(const FVersePerceptFrame& Frame, IVerseBotWorldQueries& World)
{
	check(Tier);
	NowS = float(Frame.ServerTimeMs) / 1000.f;
	const float Dt = LastThinkS < 0.f ? 1.f / 60.f : FMath::Max(NowS - LastThinkS, 0.f);
	LastThinkS = NowS;
	WorldThisTick = &World;
	FrameThisTick = &Frame;
	if (!bSpawnsFetched)
	{
		World.GetSpawnPoints(Spawns);
		bSpawnsFetched = true;
	}

	const bool bAlive = Frame.Self.Phase == EVerseCombatPhase::Alive || Frame.Self.Phase == EVerseCombatPhase::FinisherAttacker;
	if (!bAlive)
	{
		if (bWasAlive)
		{
			OnOwnDeath();
		}
		bWasAlive = false;
		PrevButtons = 0;
		FVerseInputFrame Idle;
		Idle.ServerTimeMs = Frame.ServerTimeMs;
		return Idle;
	}
	if (!bWasAlive)
	{
		if (DecisionIndex > 0)
		{
			OnOwnRespawn();
		}
		bWasAlive = true;
	}

	// Percepts of this frame.
	const FVerseSightPercept* Sight = FirstVisible(Frame);
	bSightingThisTick = Sight != nullptr;
	if (Sight)
	{
		SightingThisTick = *Sight;
	}
	if (Frame.Heard.Num() > 0)
	{
		LastHeard = Frame.Heard.Last();
		LastHeardS = NowS;
	}

	// Belief: 10 Hz, at once on a positive percept.
	const bool bPositive = Sight || Frame.Heard.Num() > 0 || Frame.bHasHurt || Frame.Bolts.Num() > 0 || Frame.Hud.Num() > 0;
	if (bPositive || NowS >= NextBeliefStepS)
	{
		Belief->Step(Frame, NowS - LastBeliefStepS, Memory->IsEnabled() ? Memory : nullptr, Spawns);
		LastBeliefStepS = NowS;
		NextBeliefStepS = NowS + BeliefStepS;
	}
	BeliefSummary = Belief->Summary();

	BuildContext(Frame, World);
	UpdateLearning(Frame);

	float Bonus[VerseBot::NumStates] = {};
	const bool bForce = ForcedTriggers(Frame, Bonus);
	if (bForce || NowS >= NextDecisionS)
	{
		Decide(bForce, Bonus);
	}
	else
	{
		RunScheduledQuery();
	}

	FVerseBotIntent Intent = VerseBotTactics::Tick(Selector.Current(), Ctx, TacticsMem, TacticsRng);
	if (TacticsMem.bBreachPlanted && NowS - TacticsMem.BreachPlantedS >= 2.5f && Belief->GetPieceBelief(TacticsMem.BreachPiece) == EVersePieceState::Intact)
	{
		// Own action (destruction 6.2): the bot knows its own charge went off.
		Belief->NoteOwnPieceChange(TacticsMem.BreachPiece, EVersePieceState::Breached);
	}
	Reflexes(Intent);

	// Aim.
	FVerseBotAimRequest AimReq;
	AimReq.bHasTarget = Intent.bHasLookTarget;
	AimReq.TargetPoint = Intent.LookTarget;
	AimReq.bNewTarget = bSightingThisTick && !bHadSighting;
	const float TargetDist = FMath::Max(float(FVector::Dist(Intent.LookTarget, Frame.Self.EyeLocation)), 100.f);
	AimReq.TargetHalfWidthDeg = FMath::RadiansToDegrees(FMath::Atan(25.f / TargetDist));
	const FVerseBotAimResult AimResult = Aim->Step(Frame.Self, AimReq, Dt);
	ApplyFireGate(Intent, AimResult);

	// Health: stuck events.
	if (Intent.bHasMoveTarget)
	{
		if (FVector::Dist2D(Frame.Self.Location, StuckRef) > StuckMinMoveCm)
		{
			StuckRef = Frame.Self.Location;
			StuckSinceS = NowS;
			bStuckCounted = false;
			bStuckReplanned = false;
		}
		else
		{
			if (NowS - StuckSinceS > StuckReplanS && !bStuckReplanned)
			{
				// No progress: drop the move targets and re-plan on the next tick (6.1 path invalidation).
				bStuckReplanned = true;
				TacticsMem.bHasSearchTarget = false;
				TacticsMem.bHasFlankPoint = false;
				PathTarget = FVector(1.0e9);
				NextDecisionS = NowS;
			}
			if (NowS - StuckSinceS > StuckWindowS && !bStuckCounted)
			{
				++StuckEvents;
				bStuckCounted = true;
			}
		}
	}
	else
	{
		StuckRef = Frame.Self.Location;
		StuckSinceS = NowS;
		bStuckReplanned = false;
	}

	if (Sight)
	{
		LastSightingS = NowS;
		LastSeenLocation = Sight->PelvisLocation;
		LastSightPerceptId = Sight->PerceptId;
	}
	bHadSighting = bSightingThisTick;
	return ToInput(Intent, AimResult, Frame.ServerTimeMs);
}

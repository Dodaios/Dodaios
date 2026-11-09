#include "Reflexes/VerseBotReflexes.h"

#include "Bot/VerseBotTier.h"

FVerseBotReflexParams FVerseBotReflexParams::FromTier(const UVerseBotTier& Tier)
{
	FVerseBotReflexParams Out;
	Out.LeanUse = Tier.LeanUse;
	Out.CrouchPeekUse = Tier.CrouchPeekUse;
	Out.ProneUse = Tier.ProneUse;
	Out.SlideUse = Tier.SlideUse;
	Out.SoundDiscipline = Tier.SoundDiscipline;
	Out.KnifeChoice = Tier.KnifeChoice;
	Out.PistolSwitchChance = Tier.PistolSwitchChance;
	Out.Reaction = FVerseBotReactionParams::FromTier(Tier);
	return Out;
}

void FVerseBotReflexes::Reset(const FVerseBotReflexParams& InParams, uint64 Seed)
{
	*this = FVerseBotReflexes();
	Params = InParams;
	Rng = FVerseRng(Seed, 4, EVerseRngSalt::Aim);
}

double FVerseBotReflexes::ArcAngleDeg(const FVector& VictimLocation, float VictimYawDeg, const FVector& AttackerLocation)
{
	FVector D = AttackerLocation - VictimLocation;
	D.Z = 0.0;
	if (!D.Normalize())
	{
		return 0.0;
	}
	const FVector Facing = FRotator(0.0, VictimYawDeg, 0.0).Vector();
	return FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FVector::DotProduct(Facing, D), -1.0, 1.0)));
}

void FVerseBotReflexes::Schedule(EVerseBotReflex Reflex, double NowS, EVerseBotStimulus Stimulus)
{
	if (Pending.Reflex != EVerseBotReflex::None)
	{
		return; // one stimulus answer at a time; the first one keeps its reaction time
	}
	Pending.Reflex = Reflex;
	Pending.FireAtS = NowS + FVerseBotReaction::SampleMs(Rng, Params.Reaction, Stimulus) / 1000.0;
}

bool FVerseBotReflexes::RollOnce(uint32 Id, uint32& RolledId, bool& bRolled, bool& bChosen, double Chance)
{
	if (!bRolled || RolledId != Id)
	{
		bRolled = true;
		RolledId = Id;
		bChosen = Rng.Chance(Chance);
	}
	return bChosen;
}

FVerseBotReflexOutput FVerseBotReflexes::Tick(const FVerseBotReflexContext& Ctx)
{
	FVerseBotReflexOutput Out;
	const bool bEmpty = Ctx.Magazine <= 0 && !Ctx.bChambered;

	// ---- Stimulus reflexes (wait a reaction time).
	double RangeCm = TNumericLimits<double>::Max();
	double Theta = 0.0;
	if (Ctx.bTargetVisible)
	{
		FVector D = Ctx.TargetLocation - Ctx.SelfLocation;
		D.Z = 0.0;
		RangeCm = D.Size();
		Theta = ArcAngleDeg(Ctx.TargetLocation, Ctx.TargetFacingYawDeg, Ctx.SelfLocation);
	}
	const bool bClose = Ctx.bTargetVisible && RangeCm <= KnifeRangeCm && !Ctx.bTargetSpawnProtected;
	if (!bClose)
	{
		bCloseContact = false;
		bKnifeRolled = false;
		if (Pending.Reflex == EVerseBotReflex::Finisher || Pending.Reflex == EVerseBotReflex::Knife)
		{
			Pending = FPending(); // the stimulus went away before the reaction finished
		}
	}
	else
	{
		bCloseContact = true;
	}

	if (bClose && RangeCm <= FinisherRangeCm && Theta > FrontArcDeg && Ctx.bFinisherAvailable)
	{
		// Rear or flank arc: the finisher beats every other reflex (bot.md 5.2). It pre-empts
		// whatever is pending and keeps that reflex's reaction clock, because the bot is
		// already reacting to this opponent; with nothing pending it samples a fresh one.
		if (Pending.Reflex == EVerseBotReflex::None)
		{
			Schedule(EVerseBotReflex::Finisher, Ctx.NowS, EVerseBotStimulus::Sight);
		}
		else
		{
			Pending.Reflex = EVerseBotReflex::Finisher;
		}
	}
	else if (bClose && Theta <= FrontArcDeg)
	{
		if (!bKnifeRolled)
		{
			bKnifeRolled = true;
			bKnifeChosen = Rng.Chance(Params.KnifeChoice);
		}
		if (bEmpty || bKnifeChosen)
		{
			Schedule(EVerseBotReflex::Knife, Ctx.NowS, EVerseBotStimulus::Sight);
		}
	}

	if (bEmpty && Ctx.bTargetVisible && Ctx.ActiveSlot == EVerseLoadoutSlot::Primary)
	{
		// Skip the switch-or-retreat answer only when a melee reflex actually answers this
		// contact; a close opponent the bot cannot knife or finish still gets one (bot.md 5.2).
		const bool bMeleeScheduled = Pending.Reflex == EVerseBotReflex::Knife || Pending.Reflex == EVerseBotReflex::Finisher;
		if (!bEmptyHandled && !bMeleeScheduled)
		{
			bEmptyHandled = true;
			if (Rng.Chance(Params.PistolSwitchChance))
			{
				Schedule(EVerseBotReflex::PistolSwitch, Ctx.NowS, EVerseBotStimulus::Sight);
			}
			else
			{
				Out.bWantRetreat = true;
				Out.Fired = EVerseBotReflex::RetreatOnEmpty;
			}
		}
	}
	else if (!bEmpty)
	{
		bEmptyHandled = false;
	}

	if (Ctx.bHitThisTick && Ctx.bBehindLowCover && !bDucking && Ctx.Stance != EVerseStance::Prone)
	{
		if (Rng.Chance(Params.CrouchPeekUse))
		{
			Schedule(EVerseBotReflex::DuckOnHit, Ctx.NowS, EVerseBotStimulus::Sight);
		}
	}

	if (Pending.Reflex != EVerseBotReflex::None && Ctx.NowS + 1.0e-9 >= Pending.FireAtS)
	{
		Out.Fired = Pending.Reflex;
		switch (Pending.Reflex)
		{
		case EVerseBotReflex::Finisher:
		case EVerseBotReflex::Knife:
			Out.Pressed |= uint32(EVerseInputButton::Melee);
			Out.Buttons |= uint32(EVerseInputButton::Melee);
			break;
		case EVerseBotReflex::PistolSwitch:
			Out.Pressed |= uint32(EVerseInputButton::SlotSecondary);
			Out.Buttons |= uint32(EVerseInputButton::SlotSecondary);
			break;
		case EVerseBotReflex::DuckOnHit:
			bDucking = true;
			break;
		default:
			break;
		}
		Pending = FPending();
	}

	// ---- Planned stance and movement (decided with the tactic, no reaction wait).
	if (Ctx.bPeeking)
	{
		bDucking = false;
		if (Ctx.PeekSide != 0 && RollOnce(Ctx.PeekId, LeanPeekId, bLeanRolled, bLeanChosen, Params.LeanUse))
		{
			Out.Buttons |= uint32(Ctx.PeekSide < 0 ? EVerseInputButton::LeanLeft : EVerseInputButton::LeanRight);
		}
	}
	if (bDucking && Ctx.bBehindLowCover)
	{
		Out.Buttons |= uint32(EVerseInputButton::Crouch);
	}
	else
	{
		bDucking = false;
	}

	if (Ctx.bHoldingLongRange && RollOnce(Ctx.HoldId, ProneHoldId, bProneRolled, bProneChosen, Params.ProneUse))
	{
		Out.Buttons |= uint32(EVerseInputButton::Prone);
	}

	bool bSprint = Ctx.bWantsSprint && Ctx.bWantsMove;
	const bool bNearBelief = Ctx.TopClusterDistanceM >= 0.0 && Ctx.TopClusterDistanceM <= SoundDisciplineRangeM;
	if (Ctx.bWantsMove && bNearBelief && RollOnce(Ctx.ApproachId, QuietApproachId, bQuietRolled, bQuietChosen, Params.SoundDiscipline))
	{
		bSprint = false;
		if (Ctx.TopClusterDistanceM <= CrouchWalkRangeM)
		{
			Out.Buttons |= uint32(EVerseInputButton::Crouch);
		}
		else
		{
			Out.MoveScale = WalkMoveScale;
		}
	}

	if (Ctx.bCrossingOpenGround && bSprint)
	{
		const bool bNewCrossing = !bSlideRolled || SlideCrossingId != Ctx.CrossingId;
		if (RollOnce(Ctx.CrossingId, SlideCrossingId, bSlideRolled, bSlideChosen, Params.SlideUse))
		{
			if (bNewCrossing)
			{
				bSlideDone = false;
			}
			if (!bSlideDone && Ctx.Stance != EVerseStance::Slide)
			{
				// Crouch while sprinting starts the slide (VerseMovement); one slide per crossing.
				Out.Pressed |= uint32(EVerseInputButton::Crouch);
				Out.Buttons |= uint32(EVerseInputButton::Crouch);
				bSlideDone = true;
			}
		}
	}
	if (bSprint)
	{
		Out.Buttons |= uint32(EVerseInputButton::Sprint);
	}
	return Out;
}

#include "Balance/VerseTrickOverrides.h"

namespace VerseTrickPrivate
{
	constexpr uint32 Bit(EVerseInputButton Button) { return uint32(Button); }

	void Hold(FVerseInputFrame& Frame, EVerseInputButton Button, bool bOn)
	{
		Frame.Buttons = bOn ? (Frame.Buttons | Bit(Button)) : (Frame.Buttons & ~Bit(Button));
	}

	bool Held(const FVerseInputFrame& Frame, EVerseInputButton Button) { return (Frame.Buttons & Bit(Button)) != 0; }
}

bool FVerseTrickOverrides::AnySighting(const FVersePerceptFrame& Percepts)
{
	for (const FVerseSightPercept& Sight : Percepts.Sightings)
	{
		if (Sight.VisibleMask != 0)
		{
			return true;
		}
	}
	return false;
}

float FVerseTrickOverrides::NearestSightingM(const FVersePerceptFrame& Percepts)
{
	float Best = TNumericLimits<float>::Max();
	for (const FVerseSightPercept& Sight : Percepts.Sightings)
	{
		if (Sight.VisibleMask != 0)
		{
			Best = FMath::Min(Best, float(FVector::Dist(Percepts.Self.EyeLocation, Sight.PelvisLocation) / 100.0));
		}
	}
	return Best;
}

FVerseInputFrame FVerseTrickOverrides::Apply(const FVerseTrickConfig& Config, const FVersePerceptFrame& Percepts,
	const FVerseInputFrame& Brain, FVerseTrickState& State, FVerseRng& Rng, double NowS)
{
	using namespace VerseTrickPrivate;
	using B = EVerseInputButton;

	FVerseInputFrame Out = Brain;
	const bool bSight = AnySighting(Percepts);
	const float Nearest = NearestSightingM(Percepts);
	const FVerseSelfPercept& Self = Percepts.Self;

	switch (Config.Trick)
	{
	case EVerseTrick::Spray:
	{
		// Holds the trigger on sight, never bursts, reloads only on empty.
		if (bSight)
		{
			Hold(Out, B::Fire, true);
		}
		const bool bEmpty = Self.Magazine <= 0 && !Self.bChambered;
		Hold(Out, B::Reload, bEmpty && Self.Reserve > 0);
		break;
	}
	case EVerseTrick::Rusher:
		if (!bSight)
		{
			Out.Move = FVector2f(1.f, 0.f);
			Hold(Out, B::Sprint, true);
		}
		break;
	case EVerseTrick::Slider:
		if (Held(Out, B::Sprint) && Out.Move.X > 0.5f && NowS - State.LastSlideS >= Config.SlideCooldownS)
		{
			Hold(Out, B::Crouch, true);
			State.LastSlideS = NowS;
		}
		break;
	case EVerseTrick::JumpPeek:
		if (Held(Out, B::LeanLeft) || Held(Out, B::LeanRight))
		{
			Hold(Out, B::LeanLeft, false);
			Hold(Out, B::LeanRight, false);
			Hold(Out, B::Jump, true);
		}
		break;
	case EVerseTrick::LeanSpam:
		if (bSight || Percepts.bHasHurt)
		{
			if (NowS >= State.NextLeanFlipS)
			{
				State.bLeanRight = !State.bLeanRight;
				State.NextLeanFlipS = NowS + Rng.Range(Config.LeanFlipMinMs, Config.LeanFlipMaxMs) / 1000.0;
			}
			Hold(Out, B::LeanRight, State.bLeanRight);
			Hold(Out, B::LeanLeft, !State.bLeanRight);
		}
		break;
	case EVerseTrick::Prone:
		if (bSight && Nearest > Config.ProneBeyondM)
		{
			Hold(Out, B::Prone, true);
			Hold(Out, B::Sprint, false);
			Hold(Out, B::Crouch, false);
		}
		break;
	case EVerseTrick::Turtle:
		// GadgetA is the Bulwark (combat-state.md 2.2): redeploy whenever it is ready.
		Hold(Out, B::GadgetA, Self.GadgetCharges[0] > 0 && Self.GadgetCooldownS[0] <= 0.f);
		break;
	case EVerseTrick::Knife:
		Hold(Out, B::Fire, false);
		Hold(Out, B::Ads, false);
		if (Self.ActiveSlot != EVerseLoadoutSlot::Melee)
		{
			Hold(Out, B::SlotMelee, true);
		}
		Hold(Out, B::Melee, bSight && Nearest <= Config.MeleeRangeM);
		break;
	case EVerseTrick::Finisher:
		Hold(Out, B::Fire, false);
		break;
	case EVerseTrick::Kiter:
		if (bSight && Nearest < Config.BackOffInsideM)
		{
			Out.Move.X = -1.f;
		}
		break;
	case EVerseTrick::Silent:
		Hold(Out, B::Crouch, true);
		Hold(Out, B::Sprint, false);
		Hold(Out, B::Jump, false);
		break;
	case EVerseTrick::Hider:
		if (!Percepts.bHasHurt)
		{
			Hold(Out, B::Fire, false);
		}
		if (bSight)
		{
			Out.Move.X = -1.f;
			Hold(Out, B::Sprint, true);
		}
		break;
	default:
		// Camper, WallSpam, Breacher, Watcher, Repeek: decision-level only (FVerseTrickIntent).
		break;
	}

	Out.Pressed = Out.Buttons & ~State.PrevButtons;
	State.PrevButtons = Out.Buttons;
	return Out;
}

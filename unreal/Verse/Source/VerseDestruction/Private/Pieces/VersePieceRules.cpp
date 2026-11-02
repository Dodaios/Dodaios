#include "Pieces/VersePieceRules.h"

namespace Verse::Destruction::Rules
{
	namespace
	{
		EVersePieceState Max(EVersePieceState A, EVersePieceState B)
		{
			return uint8(A) >= uint8(B) ? A : B;
		}
	}

	bool IsForward(EVersePieceState From, EVersePieceState To)
	{
		if (From == EVersePieceState::Repairing || To == EVersePieceState::Repairing)
		{
			return false;
		}
		return uint8(To) >= uint8(From);
	}

	FOutcome Apply(const FVersePieceClassTuning& Row, EVersePieceState State, float Hp, EVerseFractureCause Cause,
		EHitRole Role, float Amount)
	{
		FOutcome Out{State, Hp};
		if (State == EVersePieceState::Destroyed || State == EVersePieceState::Repairing)
		{
			return Out;
		}
		if (Row.Material == EVersePenetrationMaterial::Concrete || Row.Material == EVersePenetrationMaterial::ArmorSteel)
		{
			return Out; // DR4
		}
		const bool bWall = Row.bBreachedByCharge;

		switch (Cause)
		{
		case EVerseFractureCause::Bolt:
		{
			if (Row.MaxHp <= 0.f)
			{
				return Out; // catwalk: bolts pass or scorch, never change state
			}
			Out.Hp = FMath::Max(0.f, Hp - FMath::Max(0.f, Amount));
			EVersePieceState Next = State;
			if (Next == EVersePieceState::Intact && Row.bDamagedOnFirstHit)
			{
				Next = EVersePieceState::Damaged;
			}
			if (Row.HoledAtOrBelowHp >= 0.f && Out.Hp <= Row.HoledAtOrBelowHp)
			{
				Next = Max(Next, EVersePieceState::Holed); // bullets never take a wall past Holed
			}
			if (Row.bDestroyedAtZeroHp && Out.Hp <= 0.f)
			{
				Next = EVersePieceState::Destroyed;
			}
			Out.State = Max(State, Next);
			return Out;
		}
		case EVerseFractureCause::Melee:
		{
			if (!Row.bDestroyedByMeleeWhenDamaged)
			{
				return Out; // melee changes only glass
			}
			if (State == EVersePieceState::Damaged)
			{
				Out.State = EVersePieceState::Destroyed;
				Out.Hp = 0.f;
				return Out;
			}
			Out.Hp = FMath::Max(0.f, Hp - FMath::Max(0.f, Amount));
			Out.State = (Row.bDestroyedAtZeroHp && Out.Hp <= 0.f) ? EVersePieceState::Destroyed : EVersePieceState::Damaged;
			return Out;
		}
		case EVerseFractureCause::Breach:
		{
			if (Role == EHitRole::BreachSide)
			{
				if (bWall)
				{
					Out.State = Max(State, EVersePieceState::Holed);
					Out.Hp = Row.HoledAtOrBelowHp >= 0.f ? FMath::Min(Hp, Row.HoledAtOrBelowHp) : Hp;
				}
				else if (Row.bDestroyedAtZeroHp)
				{
					Out.State = EVersePieceState::Destroyed; // glass, ceiling
					Out.Hp = 0.f;
				}
				return Out; // catwalks only break as the target
			}
			if (Row.bBreachedByCharge)
			{
				Out.State = Max(State, EVersePieceState::Breached);
				Out.Hp = Row.HoledAtOrBelowHp >= 0.f ? FMath::Min(Hp, Row.HoledAtOrBelowHp) : Hp;
			}
			else if (Row.bDestroyedByCharge)
			{
				Out.State = EVersePieceState::Destroyed;
				Out.Hp = 0.f;
			}
			return Out;
		}
		case EVerseFractureCause::Repair:
		case EVerseFractureCause::Reset:
			return Out; // never damage causes
		}
		return Out;
	}

	EVerseFractureNoise NoiseKind(EVersePieceClass Class, EVerseFractureCause Cause, EVersePieceState To)
	{
		if (Cause == EVerseFractureCause::Breach)
		{
			return EVerseFractureNoise::Breach;
		}
		switch (Class)
		{
		case EVersePieceClass::GlassPane:
			return EVerseFractureNoise::Glass;
		case EVersePieceClass::CeilingPanel:
			return To == EVersePieceState::Destroyed ? EVerseFractureNoise::Tile : EVerseFractureNoise::BoltHole;
		case EVersePieceClass::CatwalkSegment:
			return EVerseFractureNoise::Breach;
		default:
			return To == EVersePieceState::Damaged ? EVerseFractureNoise::BoltHole : EVerseFractureNoise::WallBreak;
		}
	}
}

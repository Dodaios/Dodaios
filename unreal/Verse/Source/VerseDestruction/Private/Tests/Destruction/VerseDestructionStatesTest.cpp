#include "Tests/Destruction/VerseDestructionTestUtil.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Pieces/VersePieceRules.h"

using namespace VerseDestructionTest;

namespace
{
	struct FOne
	{
		FVerseDestructionSim Sim;
		FVersePieceDef Def;
		uint32 Now = 1000;

		explicit FOne(EVersePieceClass Class, EVersePenetrationMaterial Material = EVersePenetrationMaterial(0xFF))
		{
			Def = MakePiece(Class, FVector::ZeroVector, 1);
			if (uint8(Material) != 0xFF)
			{
				Def.Material = Material;
			}
			Sim.Init({Def}, FVerseDestructionSimTuning::Contract(), {}, 7);
		}
		EVersePieceState State() const { return Sim.GetItem(0).State; }
		void Hit(const FVersePieceDamage& Damage)
		{
			FVersePieceDamage D = Damage;
			D.PieceIndex = 0;
			Sim.ApplyDamage(D, Now);
			Now += TickMs;
		}
	};
}

// A6.1: every class follows table 3.2; bullets never take a wall past Holed; floor, concrete and
// armor steel never change.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesWalls, "Verse.Destruction.States.Walls", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesWalls::RunTest(const FString&)
{
	struct FCase
	{
		EVersePieceClass Class;
		float MaxHp;
		float HoledAt;
	};
	for (const FCase& Case : {FCase{EVersePieceClass::WallPanel, 200.f, 100.f}, FCase{EVersePieceClass::CladdingWall, 250.f, 125.f},
			 FCase{EVersePieceClass::ContainerWall, 300.f, 150.f}})
	{
		const FString Name = UEnum::GetValueAsString(Case.Class);
		FOne P(Case.Class);
		TestEqual(Name + TEXT(" starts Intact"), P.State(), EVersePieceState::Intact);
		TestEqual(Name + TEXT(" starts at full HealthQ"), int32(P.Sim.GetItem(0).HealthQ), 255);
		P.Hit(Bolt(P.Def));
		TestEqual(Name + TEXT(" first hit -> Damaged"), P.State(), EVersePieceState::Damaged);
		const int32 HitsToHoled = FMath::CeilToInt((Case.MaxHp - Case.HoledAt) / 10.f);
		for (int32 Hit = 1; Hit < HitsToHoled - 1; ++Hit)
		{
			P.Hit(Bolt(P.Def));
		}
		TestEqual(Name + TEXT(" above the threshold stays Damaged"), P.State(), EVersePieceState::Damaged);
		P.Hit(Bolt(P.Def));
		TestEqual(Name + TEXT(" at or below the threshold -> Holed"), P.State(), EVersePieceState::Holed);
		TestTrue(Name + TEXT(" HP at or below the threshold"), P.Sim.GetHp(0) <= Case.HoledAt);
		for (int32 Hit = 0; Hit < 60; ++Hit)
		{
			P.Hit(Bolt(P.Def));
		}
		TestEqual(Name + TEXT(" bullets never take a wall past Holed"), P.State(), EVersePieceState::Holed);
		TestEqual(Name + TEXT(" HP floors at 0"), P.Sim.GetHp(0), 0.f);
		P.Hit(Melee(P.Def));
		TestEqual(Name + TEXT(" melee changes only glass"), P.State(), EVersePieceState::Holed);
		P.Hit(Breach(P.Def));
		TestEqual(Name + TEXT(" breach charge -> Breached"), P.State(), EVersePieceState::Breached);
		P.Hit(Breach(P.Def));
		TestEqual(Name + TEXT(" a wall is never Destroyed"), P.State(), EVersePieceState::Breached);

		FOne Fresh(Case.Class);
		Fresh.Hit(Melee(Fresh.Def));
		TestEqual(Name + TEXT(" melee leaves an intact wall intact"), Fresh.State(), EVersePieceState::Intact);
		TestEqual(Name + TEXT(" melee costs a wall no HP"), Fresh.Sim.GetHp(0), Case.MaxHp);
		Fresh.Hit(Breach(Fresh.Def));
		TestEqual(Name + TEXT(" breach on an intact wall -> Breached"), Fresh.State(), EVersePieceState::Breached);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesOthers, "Verse.Destruction.States.GlassCatwalkCeiling", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesOthers::RunTest(const FString&)
{
	{
		FOne Glass(EVersePieceClass::GlassPane);
		Glass.Hit(Bolt(Glass.Def, 10.f, FVector(0, 0, 150)));
		TestEqual(TEXT("glass first hit -> Damaged (crack web)"), Glass.State(), EVersePieceState::Damaged);
		Glass.Hit(Bolt(Glass.Def, 10.f, FVector(0, 0, 150)));
		TestEqual(TEXT("glass HP 0 -> Destroyed"), Glass.State(), EVersePieceState::Destroyed);
		TestEqual(TEXT("destroyed glass HealthQ 0"), int32(Glass.Sim.GetItem(0).HealthQ), 0);
		Glass.Hit(Breach(Glass.Def));
		TestEqual(TEXT("Destroyed is final"), Glass.State(), EVersePieceState::Destroyed);
	}
	{
		FOne Glass(EVersePieceClass::GlassPane);
		Glass.Hit(Melee(Glass.Def));
		TestEqual(TEXT("melee on intact glass -> Damaged"), Glass.State(), EVersePieceState::Damaged);
		Glass.Hit(Melee(Glass.Def));
		TestEqual(TEXT("melee on damaged glass -> Destroyed"), Glass.State(), EVersePieceState::Destroyed);
	}
	{
		FOne Glass(EVersePieceClass::GlassPane);
		Glass.Hit(Breach(Glass.Def));
		TestEqual(TEXT("breach charge on glass -> Destroyed"), Glass.State(), EVersePieceState::Destroyed);
	}
	{
		FOne Catwalk(EVersePieceClass::CatwalkSegment);
		for (int32 Hit = 0; Hit < 100; ++Hit)
		{
			Catwalk.Hit(Bolt(Catwalk.Def, 50.f, FVector(0, 0, 1)));
		}
		Catwalk.Hit(Melee(Catwalk.Def));
		TestEqual(TEXT("bolts and melee never change a catwalk"), Catwalk.State(), EVersePieceState::Intact);
		Catwalk.Hit(Breach(Catwalk.Def, FVector(0, 0, 5)));
		TestEqual(TEXT("breach charge on a catwalk -> Destroyed"), Catwalk.State(), EVersePieceState::Destroyed);
	}
	{
		FOne Ceiling(EVersePieceClass::CeilingPanel);
		Ceiling.Hit(Bolt(Ceiling.Def, 10.f, FVector(0, 0, 1)));
		TestEqual(TEXT("ceiling first hit -> Damaged"), Ceiling.State(), EVersePieceState::Damaged);
		for (int32 Hit = 0; Hit < 4; ++Hit)
		{
			Ceiling.Hit(Bolt(Ceiling.Def, 10.f, FVector(0, 0, 1)));
		}
		TestEqual(TEXT("ceiling at 10 HP still Damaged"), Ceiling.State(), EVersePieceState::Damaged);
		Ceiling.Hit(Bolt(Ceiling.Def, 10.f, FVector(0, 0, 1)));
		TestEqual(TEXT("ceiling HP 0 -> Destroyed (whole tile falls)"), Ceiling.State(), EVersePieceState::Destroyed);
	}
	{
		FOne Ceiling(EVersePieceClass::CeilingPanel);
		Ceiling.Hit(Melee(Ceiling.Def));
		TestEqual(TEXT("melee never changes a ceiling panel"), Ceiling.State(), EVersePieceState::Intact);
		Ceiling.Hit(Breach(Ceiling.Def, FVector(0, 0, -5)));
		TestEqual(TEXT("breach charge on a ceiling panel -> Destroyed"), Ceiling.State(), EVersePieceState::Destroyed);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesNeverBreak, "Verse.Destruction.States.NeverBreaks", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesNeverBreak::RunTest(const FString&)
{
	for (const EVersePenetrationMaterial Material : {EVersePenetrationMaterial::Concrete, EVersePenetrationMaterial::ArmorSteel})
	{
		FOne P(EVersePieceClass::WallPanel, Material);
		for (int32 Hit = 0; Hit < 50; ++Hit)
		{
			P.Hit(Bolt(P.Def, 50.f));
		}
		P.Hit(Melee(P.Def));
		P.Hit(Breach(P.Def));
		TestEqual(FString::Printf(TEXT("%s never changes state (DR4)"), *UEnum::GetValueAsString(Material)), P.State(), EVersePieceState::Intact);
		TestEqual(TEXT("and keeps full HealthQ"), int32(P.Sim.GetItem(0).HealthQ), 255);
		TestEqual(TEXT("and raises no fracture event"), P.Sim.DrainEvents().Num(), 0);
	}
	// Non-damage causes are ignored.
	FOne Wall(EVersePieceClass::WallPanel);
	FVersePieceDamage Repair = Bolt(Wall.Def);
	Repair.Cause = EVerseFractureCause::Repair;
	Wall.Hit(Repair);
	Repair.Cause = EVerseFractureCause::Reset;
	Wall.Hit(Repair);
	TestEqual(TEXT("Repair and Reset are not damage"), Wall.State(), EVersePieceState::Intact);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesBreachRadius, "Verse.Destruction.States.BreachRadius", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesBreachRadius::RunTest(const FString&)
{
	// Target wall at the origin; neighbours with a proxy vertex inside 150 cm of the charge go
	// Holed (walls) or Destroyed (glass, ceiling); catwalks and far pieces do not change.
	TArray<FVersePieceDef> Defs;
	Defs.Add(MakePiece(EVersePieceClass::WallPanel, FVector(0, 0, 0), 0));             // 0 target
	Defs.Add(MakePiece(EVersePieceClass::ContainerWall, FVector(240, 0, 0), 1));       // 1 near wall (vertex at x=120)
	Defs.Add(MakePiece(EVersePieceClass::GlassPane, FVector(0, 80, 0), 2));            // 2 near glass
	Defs.Add(MakePiece(EVersePieceClass::CeilingPanel, FVector(0, 0, 160), 3));        // 3 near ceiling tile (corner within 150)
	Defs.Add(MakePiece(EVersePieceClass::CatwalkSegment, FVector(0, 60, 100), 4));     // 4 near catwalk
	Defs.Add(MakePiece(EVersePieceClass::WallPanel, FVector(2000, 0, 0), 5));          // 5 far wall
	Defs.Add(MakePiece(EVersePieceClass::GlassPane, FVector(0, 1000, 0), 6));          // 6 far glass
	FVerseDestructionSim Sim;
	Sim.Init(Defs, FVerseDestructionSimTuning::Contract(), {}, 11);
	// Pre-damage the near wall to Holed: a side breach must not move it back or past Holed.
	FVersePieceDamage Charge = Breach(Defs[0], FVector(60, -5, 100));
	Charge.PieceIndex = 0;
	Sim.ApplyDamage(Charge, 5000);
	TestEqual(TEXT("target wall Breached"), Sim.GetItem(0).State, EVersePieceState::Breached);
	TestEqual(TEXT("near wall Holed"), Sim.GetItem(1).State, EVersePieceState::Holed);
	TestEqual(TEXT("near glass Destroyed"), Sim.GetItem(2).State, EVersePieceState::Destroyed);
	TestEqual(TEXT("near ceiling panel Destroyed"), Sim.GetItem(3).State, EVersePieceState::Destroyed);
	TestEqual(TEXT("near catwalk unchanged (breach target only)"), Sim.GetItem(4).State, EVersePieceState::Intact);
	TestEqual(TEXT("far wall unchanged"), Sim.GetItem(5).State, EVersePieceState::Intact);
	TestEqual(TEXT("far glass unchanged"), Sim.GetItem(6).State, EVersePieceState::Intact);
	// Second charge next to the Breached target and the Holed wall: forward only.
	Charge.PieceIndex = 1;
	Charge.Location = Defs[1].Transform.TransformPosition(FVector(-100, -5, 100));
	Sim.ApplyDamage(Charge, 6000);
	TestEqual(TEXT("side effect never moves a Breached wall back"), Sim.GetItem(0).State, EVersePieceState::Breached);
	TestEqual(TEXT("the new target goes Breached"), Sim.GetItem(1).State, EVersePieceState::Breached);
	// Variant choice: the breach variant nearest the charge point (standing 110 cm vs low 50 cm).
	TestEqual(TEXT("breach variant nearest the charge"), int32(Sim.GetItem(0).Variant), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesVariants, "Verse.Destruction.States.Variants", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesVariants::RunTest(const FString&)
{
	// Holed: the variant whose opening centroid is closest to the damage centroid.
	FOne Right(EVersePieceClass::WallPanel);
	for (int32 Hit = 0; Hit < 10; ++Hit)
	{
		Right.Hit(Bolt(Right.Def, 10.f, FVector(70, 0, 130 + Hit)));
	}
	TestEqual(TEXT("hits on the right -> Holed"), Right.State(), EVersePieceState::Holed);
	TestEqual(TEXT("right opening variant"), int32(Right.Sim.GetItem(0).Variant), 1);
	FOne Left(EVersePieceClass::WallPanel);
	for (int32 Hit = 0; Hit < 10; ++Hit)
	{
		Left.Hit(Bolt(Left.Def, 10.f, FVector(-80, 0, 150)));
	}
	TestEqual(TEXT("left opening variant"), int32(Left.Sim.GetItem(0).Variant), 0);
	// Breached: the variant nearest the charge position (low breach for a charge at the floor).
	FOne Low(EVersePieceClass::ContainerWall);
	Low.Hit(Breach(Low.Def, FVector(0, -5, 40)));
	TestEqual(TEXT("low charge -> low breach variant"), int32(Low.Sim.GetItem(0).Variant), 1);
	// The fracture event carries the state change, the seed and the instigator.
	const TArray<FVersePendingFracture> Events = Low.Sim.DrainEvents();
	if (TestEqual(TEXT("one fracture event"), Events.Num(), 1))
	{
		const FVerseFractureEvent& Event = Events[0].Event;
		TestEqual(TEXT("event from Intact"), Event.FromState, EVersePieceState::Intact);
		TestEqual(TEXT("event to Breached"), Event.ToState, EVersePieceState::Breached);
		TestEqual(TEXT("event cause Breach"), Event.Cause, EVerseFractureCause::Breach);
		TestEqual(TEXT("event variant"), int32(Event.Variant), 1);
		TestEqual(TEXT("event instigator slot"), int32(Event.Instigator), 1);
		TestEqual(TEXT("event radius 150 cm"), int32(Event.Radius), 150);
		TestEqual(TEXT("event seed = item seed"), Event.Seed, Low.Sim.GetItem(0).LastSeed);
		TestEqual(TEXT("event location piece-local mm"), int32(Event.Location[2]), 400);
	}
	// Noise: a breach is the loudest fracture (destruction.md 6.2).
	const TArray<FVerseNoiseEvent> Noise = Low.Sim.DrainNoise();
	if (TestEqual(TEXT("one fracture noise"), Noise.Num(), 1))
	{
		TestEqual(TEXT("breach loudness 1.0"), Noise[0].Loudness, 1.0f);
		TestEqual(TEXT("world source"), Noise[0].SourceId, -1);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDestructionStatesForward, "Verse.Destruction.States.ForwardOnly", VERSE_DESTRUCTION_TEST_FLAGS)
bool FVerseDestructionStatesForward::RunTest(const FString&)
{
	using namespace Verse::Destruction::Rules;
	const FVerseDestructionSimTuning Tuning = FVerseDestructionSimTuning::Contract();
	const EVersePieceState States[] = {EVersePieceState::Intact, EVersePieceState::Damaged, EVersePieceState::Holed, EVersePieceState::Breached,
		EVersePieceState::Destroyed};
	const EVerseFractureCause Causes[] = {EVerseFractureCause::Bolt, EVerseFractureCause::Breach, EVerseFractureCause::Melee};
	const EHitRole Roles[] = {EHitRole::Direct, EHitRole::BreachTarget, EHitRole::BreachSide};
	int32 Checked = 0;
	for (const TPair<EVersePieceClass, FVersePieceClassTuning>& Row : Tuning.Classes)
	{
		for (const EVersePieceState State : States)
		{
			for (const EVerseFractureCause Cause : Causes)
			{
				for (const EHitRole Role : Roles)
				{
					for (const float Hp : {0.f, 10.f, 1000.f})
					{
						const FOutcome Out = Apply(Row.Value, State, Hp, Cause, Role, 25.f);
						++Checked;
						if (!IsForward(State, Out.State))
						{
							AddError(FString::Printf(TEXT("%s: %s -> %s is backwards"), *UEnum::GetValueAsString(Row.Key),
								*UEnum::GetValueAsString(State), *UEnum::GetValueAsString(Out.State)));
						}
						if (Out.Hp > Hp + KINDA_SMALL_NUMBER)
						{
							AddError(TEXT("damage raised HP"));
						}
						if (Cause == EVerseFractureCause::Bolt && Row.Value.bBreachedByCharge && uint8(Out.State) > uint8(EVersePieceState::Holed)
							&& uint8(State) <= uint8(EVersePieceState::Holed))
						{
							AddError(TEXT("a bolt took a wall past Holed"));
						}
					}
				}
			}
		}
	}
	TestTrue(TEXT("checked every class x state x cause x role"), Checked >= 6 * 5 * 3 * 3 * 3);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

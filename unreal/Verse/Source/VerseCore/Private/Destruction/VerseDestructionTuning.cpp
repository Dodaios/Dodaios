#include "Destruction/VerseDestructionTuning.h"

namespace
{
	FVersePieceClassTuning MakeClass(EVersePenetrationMaterial Material, float MaxHp, bool bDamagedOnFirstHit,
		float HoledAt, bool bBreached, bool bDestroyedAtZero, bool bDestroyedByCharge, bool bMeleeGlass, float RepairS)
	{
		FVersePieceClassTuning Row;
		Row.Material = Material;
		Row.MaxHp = MaxHp;
		Row.bDamagedOnFirstHit = bDamagedOnFirstHit;
		Row.HoledAtOrBelowHp = HoledAt;
		Row.bBreachedByCharge = bBreached;
		Row.bDestroyedAtZeroHp = bDestroyedAtZero;
		Row.bDestroyedByCharge = bDestroyedByCharge;
		Row.bDestroyedByMeleeWhenDamaged = bMeleeGlass;
		Row.RepairTimeS = RepairS;
		return Row;
	}
}

UVerseDestructionTuning::UVerseDestructionTuning()
{
	Classes = MakeContractClasses();
}

TMap<EVersePieceClass, FVersePieceClassTuning> UVerseDestructionTuning::MakeContractClasses()
{
	using C = EVersePieceClass;
	using M = EVersePenetrationMaterial;
	TMap<C, FVersePieceClassTuning> Out;
	Out.Add(C::WallPanel, MakeClass(M::SheetMetal, 200.f, true, 100.f, true, false, false, false, 8.f));
	Out.Add(C::CladdingWall, MakeClass(M::CladdingPanel, 250.f, true, 125.f, true, false, false, false, 8.f));
	Out.Add(C::ContainerWall, MakeClass(M::ContainerWall, 300.f, true, 150.f, true, false, false, false, 8.f));
	Out.Add(C::GlassPane, MakeClass(M::Glass, 20.f, true, -1.f, false, true, true, true, 4.f));
	Out.Add(C::CatwalkSegment, MakeClass(M::CatwalkGrating, 0.f, false, -1.f, false, false, true, false, 10.f));
	Out.Add(C::CeilingPanel, MakeClass(M::CeilingPanel, 60.f, true, -1.f, false, true, true, false, 5.f));
	return Out;
}

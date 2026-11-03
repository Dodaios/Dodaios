#include "Penetration/VersePenetrationMath.h"

namespace VersePenetration
{
	int32 EffectiveMaxPieces(int32 WeaponMaxPieces)
	{
		return FMath::Clamp(WeaponMaxPieces, 0, Verse::Destruction::MaxPenetrations);
	}

	FVersePenetrationStep EvaluatePiece(const FVersePenetrationRow& Row, float TracedThicknessCm, float Power, float Damage,
		bool bLimitReached)
	{
		FVersePenetrationStep Step;
		Step.Cost = UVersePenetrationTable::PassCost(Row, TracedThicknessCm);
		Step.bPassed = !bLimitReached && Power >= Step.Cost;
		if (Step.bPassed)
		{
			Step.PowerLeft = Power - Step.Cost;
			Step.DamageLeft = Damage * Row.DamageMultiplier;
		}
		return Step;
	}

	bool KeepsBoltHoles(EVersePenetrationMaterial Material)
	{
		switch (Material)
		{
		case EVersePenetrationMaterial::SheetMetal:
		case EVersePenetrationMaterial::ContainerWall:
		case EVersePenetrationMaterial::Glass:
		case EVersePenetrationMaterial::CladdingPanel:
		case EVersePenetrationMaterial::CeilingPanel:
			return true;
		default:
			return false;
		}
	}

	bool IsWallMaterial(EVersePenetrationMaterial Material)
	{
		return Material == EVersePenetrationMaterial::SheetMetal || Material == EVersePenetrationMaterial::ContainerWall
			|| Material == EVersePenetrationMaterial::CladdingPanel;
	}

	TConstArrayView<const TCHAR*> FrozenMaterialIds()
	{
		static const TCHAR* const Ids[] = {
			TEXT("sheet_metal"),
			TEXT("container_wall"),
			TEXT("glass"),
			TEXT("cladding_panel"),
			TEXT("catwalk_grating"),
			TEXT("ceiling_panel"),
			TEXT("concrete"),
			TEXT("armor_steel"),
		};
		return Ids;
	}
}

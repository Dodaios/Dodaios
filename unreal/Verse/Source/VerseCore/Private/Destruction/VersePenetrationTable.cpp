#include "Destruction/VersePenetrationTable.h"

#include "VerseGameplayTags.h"

namespace
{
	FVersePenetrationRow MakeRow(EVersePenetrationMaterial Id, float RefCm, float Cost, float Multiplier,
		bool bBullets, bool bBreach, EVerseDebrisType Debris)
	{
		FVersePenetrationRow Row;
		Row.MaterialTag = VerseTags::AllMaterialTags()[uint8(Id)];
		Row.WireId = Id;
		Row.RefThicknessCm = RefCm;
		Row.PenetrationCost = Cost;
		Row.DamageMultiplier = Multiplier;
		Row.bBreakableByBullets = bBullets;
		Row.bBreakableByBreach = bBreach;
		Row.DebrisType = Debris;
		return Row;
	}
}

UVersePenetrationTable::UVersePenetrationTable()
{
	Rows = MakeContractRows();
}

TArray<FVersePenetrationRow> UVersePenetrationTable::MakeContractRows()
{
	using M = EVersePenetrationMaterial;
	using D = EVerseDebrisType;
	return {
		MakeRow(M::SheetMetal, 0.3f, 15.f, 0.85f, true, true, D::MetalShards),
		MakeRow(M::ContainerWall, 0.4f, 25.f, 0.75f, true, true, D::CorrugatedChunks),
		MakeRow(M::Glass, 2.4f, 5.f, 0.95f, true, true, D::GlassShards),
		MakeRow(M::CladdingPanel, 4.0f, 30.f, 0.70f, true, true, D::PanelChunks),
		MakeRow(M::CatwalkGrating, 3.0f, 10.f, 0.90f, false, true, D::GratingTwisted),
		MakeRow(M::CeilingPanel, 2.5f, 8.f, 0.90f, true, true, D::CeilingTile),
		MakeRow(M::Concrete, 30.f, 400.f, 0.f, false, false, D::DustChips),
		MakeRow(M::ArmorSteel, 2.5f, 10000.f, 0.f, false, false, D::SparksOnly),
	};
}

const FVersePenetrationRow* UVersePenetrationTable::FindRow(uint8 WireId) const
{
	return Rows.IsValidIndex(WireId) ? &Rows[WireId] : nullptr;
}

float UVersePenetrationTable::PassCost(const FVersePenetrationRow& Row, float TracedThicknessCm)
{
	const float Ratio = Row.RefThicknessCm > 0.f ? TracedThicknessCm / Row.RefThicknessCm : 1.f;
	return Row.PenetrationCost * FMath::Clamp(Ratio, 0.5f, 3.0f);
}

#include "Pieces/VersePieceTypes.h"

FBox FVersePieceDef::GetLocalBounds(EVersePieceState State, uint8 Variant) const
{
	switch (State)
	{
	case EVersePieceState::Intact:
	case EVersePieceState::Damaged:
		return IntactBounds;
	case EVersePieceState::Holed:
		return HoledBounds.IsValidIndex(Variant) ? HoledBounds[Variant] : (HoledBounds.Num() > 0 ? HoledBounds[0] : IntactBounds);
	case EVersePieceState::Breached:
		return BreachedBounds.IsValidIndex(Variant) ? BreachedBounds[Variant] : (BreachedBounds.Num() > 0 ? BreachedBounds[0] : IntactBounds);
	case EVersePieceState::Destroyed:
		return RemainsBounds;
	case EVersePieceState::Repairing:
		// The caller resolves Repairing to RepairFrom; on its own it has the Intact footprint.
		return IntactBounds;
	}
	return IntactBounds;
}

FBox FVersePieceDef::GetWorldBounds(EVersePieceState State, uint8 Variant) const
{
	const FBox Local = GetLocalBounds(State, Variant);
	return Local.IsValid ? Local.TransformBy(Transform) : FBox(ForceInit);
}

uint8 FVersePieceDef::NearestVariant(TConstArrayView<FVector> Centroids, const FVector& LocalPoint)
{
	uint8 Best = 0;
	double BestDistSq = TNumericLimits<double>::Max();
	for (int32 Index = 0; Index < Centroids.Num() && Index < 4; ++Index)
	{
		const double DistSq = FVector::DistSquared(Centroids[Index], LocalPoint);
		if (DistSq < BestDistSq)
		{
			BestDistSq = DistSq;
			Best = uint8(Index);
		}
	}
	return Best;
}

bool FVersePieceDef::IsWithinRadius(const FVector& WorldPoint, float RadiusCm) const
{
	const FVector Local = Transform.InverseTransformPosition(WorldPoint);
	const double RadiusSq = double(RadiusCm) * RadiusCm;
	if (ProxyVertices.Num() > 0)
	{
		for (const FVector& Vertex : ProxyVertices)
		{
			if (FVector::DistSquared(Vertex, Local) <= RadiusSq)
			{
				return true;
			}
		}
		return false;
	}
	// No vertex list: the eight corners of the Intact proxy box are its vertices.
	if (!IntactBounds.IsValid)
	{
		return false;
	}
	for (int32 Corner = 0; Corner < 8; ++Corner)
	{
		const FVector Vertex((Corner & 1) ? IntactBounds.Max.X : IntactBounds.Min.X,
			(Corner & 2) ? IntactBounds.Max.Y : IntactBounds.Min.Y,
			(Corner & 4) ? IntactBounds.Max.Z : IntactBounds.Min.Z);
		if (FVector::DistSquared(Vertex, Local) <= RadiusSq)
		{
			return true;
		}
	}
	return false;
}

int32 VerseRepairClassPriority(EVersePieceClass Class)
{
	switch (Class)
	{
	case EVersePieceClass::CatwalkSegment:
		return 0;
	case EVersePieceClass::WallPanel:
	case EVersePieceClass::CladdingWall:
	case EVersePieceClass::ContainerWall:
		return 1;
	case EVersePieceClass::GlassPane:
		return 2;
	case EVersePieceClass::CeilingPanel:
		return 3;
	}
	return 4;
}

EVersePenetrationMaterial VerseMaterialOfClass(EVersePieceClass Class)
{
	switch (Class)
	{
	case EVersePieceClass::WallPanel:
		return EVersePenetrationMaterial::SheetMetal;
	case EVersePieceClass::CladdingWall:
		return EVersePenetrationMaterial::CladdingPanel;
	case EVersePieceClass::ContainerWall:
		return EVersePenetrationMaterial::ContainerWall;
	case EVersePieceClass::GlassPane:
		return EVersePenetrationMaterial::Glass;
	case EVersePieceClass::CatwalkSegment:
		return EVersePenetrationMaterial::CatwalkGrating;
	case EVersePieceClass::CeilingPanel:
		return EVersePenetrationMaterial::CeilingPanel;
	}
	return EVersePenetrationMaterial::Concrete;
}

bool VerseMaterialNeverBreaks(EVersePenetrationMaterial Material)
{
	return Material == EVersePenetrationMaterial::Concrete || Material == EVersePenetrationMaterial::ArmorSteel;
}

FVerseDestructionSimTuning FVerseDestructionSimTuning::Contract()
{
	return FromAsset(*GetDefault<UVerseDestructionTuning>());
}

FVerseDestructionSimTuning FVerseDestructionSimTuning::FromAsset(const UVerseDestructionTuning& Asset)
{
	FVerseDestructionSimTuning Out;
	Out.Classes = Asset.Classes;
	for (const TPair<EVersePieceClass, FVersePieceClassTuning>& Row : UVerseDestructionTuning::MakeContractClasses())
	{
		// A class missing from a hand-edited asset falls back to the contract row.
		if (!Out.Classes.Contains(Row.Key))
		{
			Out.Classes.Add(Row.Key, Row.Value);
		}
	}
	Out.BreachSideRadiusCm = Asset.BreachSideRadiusCm;
	Out.RepairDelayS = Asset.RepairDelayS;
	Out.MaxActiveDrones = Asset.MaxActiveDrones;
	Out.DroneMaxHp = Asset.DroneMaxHp;
	Out.RepairEncroachMarginCm = Asset.RepairEncroachMarginCm;
	Out.RepairEncroachRecheckS = Asset.RepairEncroachRecheckS;
	Out.NavDirtyMarginCm = Asset.NavDirtyMarginCm;
	Out.NavMaxTilesInFlight = Asset.NavMaxTilesInFlight;
	Out.MaxFractureEventsPerSecond = Asset.MaxFractureEventsPerSecond;
	return Out;
}

const FVersePieceClassTuning& FVerseDestructionSimTuning::ClassRow(EVersePieceClass Class) const
{
	static const FVersePieceClassTuning Empty;
	const FVersePieceClassTuning* Row = Classes.Find(Class);
	return Row ? *Row : Empty;
}

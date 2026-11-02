#include "Stubs/VerseNullStubs.h"

TArray<FVersePenetrationHit> UVerseNullPenetrationQuery::TraceBolt(const FVector&, const FVector&, float, float, float, uint8, int32) const
{
	return {};
}

bool UVerseNullPenetrationQuery::TestSight(const FVector&, const FVector&) const
{
	return true;
}

void UVerseNullPieceDamage::ApplyPieceDamage(const FVersePieceDamage&)
{
}

EVersePieceState UVerseNullPieceQuery::GetPieceState(uint16) const
{
	return EVersePieceState::Intact;
}

EVersePenetrationMaterial UVerseNullPieceQuery::GetPieceMaterial(uint16) const
{
	return EVersePenetrationMaterial::Concrete;
}

FBox UVerseNullPieceQuery::GetPieceBounds(uint16) const
{
	return FBox(ForceInit);
}

TArray<uint16> UVerseNullPieceQuery::GetPiecesInBox(const FBox&) const
{
	return {};
}

EVerseStance UVerseNullMovementQuery::GetStance() const
{
	return EVerseStance::Stand;
}

bool UVerseNullMovementQuery::IsSprinting() const
{
	return false;
}

bool UVerseNullMovementQuery::IsAirborne() const
{
	return false;
}

bool UVerseNullMovementQuery::IsMantling() const
{
	return false;
}

int8 UVerseNullMovementQuery::GetLeanQuantized() const
{
	return 0;
}

#include "Holes/VerseBoltHoleComponent.h"

#include "Destruction/VerseDestructionTuning.h"
#include "GameFramework/Actor.h"
#include "Net/Core/PushModel/PushModel.h"
#include "Net/UnrealNetwork.h"
#include "Penetration/VersePenetrationMath.h"

void FVerseBoltHoleItem::PostReplicatedAdd(const FVerseBoltHoleArray& InArray)
{
	if (InArray.Owner)
	{
		InArray.Owner->HandleReplicatedChange();
	}
}

void FVerseBoltHoleItem::PostReplicatedChange(const FVerseBoltHoleArray& InArray)
{
	if (InArray.Owner)
	{
		InArray.Owner->HandleReplicatedChange();
	}
}

void FVerseBoltHoleItem::PreReplicatedRemove(const FVerseBoltHoleArray& InArray)
{
	if (InArray.Owner)
	{
		InArray.Owner->HandleReplicatedChange();
	}
}

UVerseBoltHoleComponent::UVerseBoltHoleComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetIsReplicatedByDefault(true);
	Holes.Owner = this;
}

void UVerseBoltHoleComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	FDoRepLifetimeParams Params;
	Params.bIsPushBased = true;
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseBoltHoleComponent, Holes, Params);
	DOREPLIFETIME_WITH_PARAMS_FAST(UVerseBoltHoleComponent, Epoch, Params);
}

void UVerseBoltHoleComponent::ApplyTuning(const UVerseDestructionTuning& Tuning)
{
	HolesPerPiece = FMath::Max(1, Tuning.HolesPerPiece);
	HolesPerArena = FMath::Max(1, Tuning.HolesPerArena);
}

bool UVerseBoltHoleComponent::HasServerAuthority() const
{
	const AActor* OwnerActor = GetOwner();
	return OwnerActor == nullptr || OwnerActor->HasAuthority();
}

EVerseHoleAddResult UVerseBoltHoleComponent::AddHole(uint16 PieceIndex, EVersePenetrationMaterial Material,
	const FVector& AxisPointLocalCm, const FVector& AxisDirectionLocal, uint8 RadiusMm, uint32 ServerTimeMs)
{
	if (!HasServerAuthority())
	{
		return EVerseHoleAddResult::NotAuthority;
	}
	if (!VersePenetration::KeepsBoltHoles(Material) || PieceIndex == VersePenetration::NoPiece)
	{
		return EVerseHoleAddResult::NotHoleMaterial;
	}

	const FVerseBoltHole NewHole = FVerseBoltHole::Make(PieceIndex, AxisPointLocalCm, AxisDirectionLocal, RadiusMm, ServerTimeMs, Epoch);
	if (NumOnPiece(PieceIndex) >= HolesPerPiece)
	{
		if (VersePenetration::IsWallMaterial(Material))
		{
			// Hole 25 on a wall: the piece turns Holed with the variant nearest the hole centroid.
			FVector Centroid = NewHole.GetAxisPointCm();
			const TConstArrayView<FVerseBoltHole> Existing = GetPieceHoles(PieceIndex);
			for (const FVerseBoltHole& Hole : Existing)
			{
				Centroid += Hole.GetAxisPointCm();
			}
			Centroid /= double(Existing.Num() + 1);
			ClearPiece(PieceIndex);
			OnPieceHoleCap.Broadcast(PieceIndex, Centroid);
			return EVerseHoleAddResult::PieceHoled;
		}
		RemoveOldestOnPiece(PieceIndex);
	}
	while (Holes.Items.Num() >= HolesPerArena)
	{
		EvictForArenaCap();
	}

	FVerseBoltHoleItem& Item = Holes.Items.AddDefaulted_GetRef();
	Item.Hole = NewHole;
	Holes.MarkItemDirty(Item);
	MarkChanged();
	return EVerseHoleAddResult::Added;
}

void UVerseBoltHoleComponent::RemoveOldestOnPiece(uint16 PieceIndex)
{
	// Items stay in insertion order, so the first item of a piece is its oldest hole.
	const int32 Index = Holes.Items.IndexOfByPredicate([PieceIndex](const FVerseBoltHoleItem& Item) { return Item.Hole.PieceIndex == PieceIndex; });
	if (Index != INDEX_NONE)
	{
		Holes.Items.RemoveAt(Index);
		Holes.MarkArrayDirty();
		MarkChanged();
	}
}

void UVerseBoltHoleComponent::EvictForArenaCap()
{
	// The piece with the most holes; ties go to the piece whose oldest hole is older.
	TMap<uint16, int32> Counts;
	TMap<uint16, int32> FirstIndex;
	for (int32 Index = 0; Index < Holes.Items.Num(); ++Index)
	{
		const uint16 Piece = Holes.Items[Index].Hole.PieceIndex;
		Counts.FindOrAdd(Piece) += 1;
		FirstIndex.FindOrAdd(Piece, Index);
	}
	uint16 Fullest = 0;
	int32 Best = -1;
	int32 BestFirst = MAX_int32;
	for (const TPair<uint16, int32>& Pair : Counts)
	{
		const int32 First = FirstIndex[Pair.Key];
		if (Pair.Value > Best || (Pair.Value == Best && First < BestFirst))
		{
			Fullest = Pair.Key;
			Best = Pair.Value;
			BestFirst = First;
		}
	}
	if (Best < 0)
	{
		return;
	}
	Holes.Items.RemoveAt(BestFirst);
	Holes.MarkArrayDirty();
	MarkChanged();
}

void UVerseBoltHoleComponent::ClearPiece(uint16 PieceIndex)
{
	if (!HasServerAuthority())
	{
		return;
	}
	const int32 Removed = Holes.Items.RemoveAll([PieceIndex](const FVerseBoltHoleItem& Item) { return Item.Hole.PieceIndex == PieceIndex; });
	if (Removed > 0)
	{
		Holes.MarkArrayDirty();
		MarkChanged();
	}
}

void UVerseBoltHoleComponent::ResetAll(uint16 NewEpoch)
{
	if (!HasServerAuthority())
	{
		return;
	}
	Holes.Items.Reset();
	Holes.MarkArrayDirty();
	Epoch = NewEpoch;
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseBoltHoleComponent, Epoch, this);
	MarkChanged();
}

void UVerseBoltHoleComponent::MarkChanged()
{
	MARK_PROPERTY_DIRTY_FROM_NAME(UVerseBoltHoleComponent, Holes, this);
	bCacheDirty = true;
	OnHolesChanged.Broadcast();
}

void UVerseBoltHoleComponent::HandleReplicatedChange()
{
	bCacheDirty = true;
	OnHolesChanged.Broadcast();
}

void UVerseBoltHoleComponent::OnRep_Epoch()
{
	HandleReplicatedChange();
}

void UVerseBoltHoleComponent::RebuildCache() const
{
	if (!bCacheDirty)
	{
		return;
	}
	ByPiece.Reset();
	for (const FVerseBoltHoleItem& Item : Holes.Items)
	{
		// A client can briefly hold records of the previous epoch; they never count.
		if (Item.Hole.Epoch == Epoch)
		{
			ByPiece.FindOrAdd(Item.Hole.PieceIndex).Add(Item.Hole);
		}
	}
	bCacheDirty = false;
}

TConstArrayView<FVerseBoltHole> UVerseBoltHoleComponent::GetPieceHoles(uint16 PieceIndex) const
{
	RebuildCache();
	const TArray<FVerseBoltHole>* Found = ByPiece.Find(PieceIndex);
	return Found ? TConstArrayView<FVerseBoltHole>(*Found) : TConstArrayView<FVerseBoltHole>();
}

void UVerseBoltHoleComponent::GetAllHoles(TArray<FVerseBoltHole>& OutHoles) const
{
	OutHoles.Reset(Holes.Items.Num());
	for (const FVerseBoltHoleItem& Item : Holes.Items)
	{
		if (Item.Hole.Epoch == Epoch)
		{
			OutHoles.Add(Item.Hole);
		}
	}
}

int32 UVerseBoltHoleComponent::Num() const
{
	RebuildCache();
	int32 Count = 0;
	for (const TPair<uint16, TArray<FVerseBoltHole>>& Pair : ByPiece)
	{
		Count += Pair.Value.Num();
	}
	return Count;
}

int32 UVerseBoltHoleComponent::NumOnPiece(uint16 PieceIndex) const
{
	return GetPieceHoles(PieceIndex).Num();
}

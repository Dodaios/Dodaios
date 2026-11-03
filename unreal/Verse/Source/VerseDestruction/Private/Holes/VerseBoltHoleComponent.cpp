#include "Holes/VerseBoltHoleComponent.h"

#include "Destruction/VerseDestructionTuning.h"
#include "GameFramework/Actor.h"
#include "Net/UnrealNetwork.h"
#include "Penetration/VersePenetrationMath.h"

UVerseBoltHoleComponent::UVerseBoltHoleComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	SetIsReplicatedByDefault(true);
}

void UVerseBoltHoleComponent::GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const
{
	Super::GetLifetimeReplicatedProps(OutLifetimeProps);
	DOREPLIFETIME(UVerseBoltHoleComponent, Slots);
	DOREPLIFETIME(UVerseBoltHoleComponent, Epoch);
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

bool UVerseBoltHoleComponent::IsLiveSlot(int32 SlotIndex) const
{
	return Slots.IsValidIndex(SlotIndex) && Slots[SlotIndex].IsUsed() && Slots[SlotIndex].Hole.Epoch == Epoch;
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
	TArray<uint16, TInlineAllocator<2>> Touched;
	Touched.Add(PieceIndex);
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
		// Glass and ceiling panels: the piece's oldest hole goes.
		RemoveSlot(ByPiece.FindChecked(PieceIndex).SlotIndices[0]);
	}
	while (LiveCount >= HolesPerArena)
	{
		const int32 Before = LiveCount;
		EvictForArenaCap();
		if (LiveCount == Before)
		{
			break;
		}
	}

	const int32 SlotIndex = FreeSlots.IsEmpty() ? Slots.AddDefaulted() : FreeSlots.Pop(EAllowShrinking::No);
	FVerseBoltHoleSlot& Slot = Slots[SlotIndex];
	Slot.Hole = NewHole;
	Slot.Sequence = NextSequence++;
	if (NextSequence == 0)
	{
		NextSequence = 1;
	}
	FPieceHoles& Piece = ByPiece.FindOrAdd(PieceIndex);
	Piece.Holes.Add(NewHole);
	Piece.SlotIndices.Add(SlotIndex);
	Piece.Axes.Emplace(NewHole);
	++LiveCount;
	Broadcast(Touched, false);
	return EVerseHoleAddResult::Added;
}

void UVerseBoltHoleComponent::RemoveSlot(int32 SlotIndex)
{
	if (!Slots.IsValidIndex(SlotIndex) || !Slots[SlotIndex].IsUsed())
	{
		return;
	}
	const uint16 PieceIndex = Slots[SlotIndex].Hole.PieceIndex;
	if (FPieceHoles* Piece = ByPiece.Find(PieceIndex))
	{
		const int32 At = Piece->SlotIndices.IndexOfByKey(SlotIndex);
		if (At != INDEX_NONE)
		{
			Piece->SlotIndices.RemoveAt(At);
			Piece->Holes.RemoveAt(At);
			Piece->Axes.RemoveAt(At);
		}
		if (Piece->SlotIndices.IsEmpty())
		{
			ByPiece.Remove(PieceIndex);
		}
	}
	Slots[SlotIndex] = FVerseBoltHoleSlot();
	FreeSlots.Add(SlotIndex);
	--LiveCount;
	const uint16 Touched[] = {PieceIndex};
	Broadcast(Touched, false);
}

void UVerseBoltHoleComponent::EvictForArenaCap()
{
	// The piece with the most holes; ties go to the piece whose oldest hole is older.
	int32 BestCount = -1;
	uint32 BestSequence = MAX_uint32;
	int32 BestSlot = INDEX_NONE;
	for (const TPair<uint16, FPieceHoles>& Pair : ByPiece)
	{
		const int32 Count = Pair.Value.SlotIndices.Num();
		if (Count == 0)
		{
			continue;
		}
		const int32 OldestSlot = Pair.Value.SlotIndices[0];
		const uint32 Sequence = Slots[OldestSlot].Sequence;
		if (Count > BestCount || (Count == BestCount && Sequence < BestSequence))
		{
			BestCount = Count;
			BestSequence = Sequence;
			BestSlot = OldestSlot;
		}
	}
	RemoveSlot(BestSlot);
}

void UVerseBoltHoleComponent::ClearPiece(uint16 PieceIndex)
{
	if (!HasServerAuthority())
	{
		return;
	}
	FPieceHoles Removed;
	if (!ByPiece.RemoveAndCopyValue(PieceIndex, Removed))
	{
		return;
	}
	for (const int32 SlotIndex : Removed.SlotIndices)
	{
		Slots[SlotIndex] = FVerseBoltHoleSlot();
		FreeSlots.Add(SlotIndex);
		--LiveCount;
	}
	const uint16 Touched[] = {PieceIndex};
	Broadcast(Touched, false);
}

void UVerseBoltHoleComponent::ResetAll(uint16 NewEpoch)
{
	if (!HasServerAuthority())
	{
		return;
	}
	Slots.Reset();
	FreeSlots.Reset();
	ByPiece.Reset();
	LiveCount = 0;
	Epoch = NewEpoch;
	Broadcast({}, true);
}

void UVerseBoltHoleComponent::Broadcast(TConstArrayView<uint16> Pieces, bool bAll)
{
	OnHolesChanged.Broadcast(Pieces, bAll);
}

void UVerseBoltHoleComponent::OnRep_Slots()
{
	// Find the pieces whose slots changed since the last update; rebuild only those.
	TArray<uint16, TInlineAllocator<8>> Touched;
	const int32 Count = FMath::Max(Slots.Num(), SeenSlots.Num());
	for (int32 Index = 0; Index < Count; ++Index)
	{
		const FVerseBoltHoleSlot* Now = Slots.IsValidIndex(Index) ? &Slots[Index] : nullptr;
		const FVerseBoltHoleSlot* Was = SeenSlots.IsValidIndex(Index) ? &SeenSlots[Index] : nullptr;
		if (Now && Was && *Now == *Was)
		{
			continue;
		}
		if (Now && Now->IsUsed())
		{
			Touched.AddUnique(Now->Hole.PieceIndex);
		}
		if (Was && Was->IsUsed())
		{
			Touched.AddUnique(Was->Hole.PieceIndex);
		}
	}
	SeenSlots = Slots;
	RebuildPieces(Touched);
	Broadcast(Touched, false);
}

void UVerseBoltHoleComponent::OnRep_Epoch()
{
	SeenSlots = Slots;
	RebuildAll();
	Broadcast({}, true);
}

void UVerseBoltHoleComponent::RebuildPieces(TConstArrayView<uint16> Pieces)
{
	if (Pieces.IsEmpty())
	{
		return;
	}
	struct FEntry
	{
		uint32 Sequence;
		int32 Slot;
	};
	TMap<uint16, TArray<FEntry>> Found;
	for (const uint16 Piece : Pieces)
	{
		Found.Add(Piece);
		if (const FPieceHoles* Old = ByPiece.Find(Piece))
		{
			LiveCount -= Old->SlotIndices.Num();
		}
		ByPiece.Remove(Piece);
	}
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		// A client can briefly hold records of the previous epoch; they never count.
		if (!IsLiveSlot(Index))
		{
			continue;
		}
		if (TArray<FEntry>* Entries = Found.Find(Slots[Index].Hole.PieceIndex))
		{
			Entries->Add({Slots[Index].Sequence, Index});
		}
	}
	for (TPair<uint16, TArray<FEntry>>& Pair : Found)
	{
		if (Pair.Value.IsEmpty())
		{
			continue;
		}
		Pair.Value.Sort([](const FEntry& A, const FEntry& B) { return A.Sequence < B.Sequence; });
		FPieceHoles& Piece = ByPiece.Add(Pair.Key);
		for (const FEntry& Entry : Pair.Value)
		{
			Piece.Holes.Add(Slots[Entry.Slot].Hole);
			Piece.SlotIndices.Add(Entry.Slot);
			Piece.Axes.Emplace(Slots[Entry.Slot].Hole);
		}
		LiveCount += Pair.Value.Num();
	}
}

void UVerseBoltHoleComponent::RebuildAll()
{
	ByPiece.Reset();
	LiveCount = 0;
	TArray<uint16> Pieces;
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		if (IsLiveSlot(Index))
		{
			Pieces.AddUnique(Slots[Index].Hole.PieceIndex);
		}
	}
	RebuildPieces(Pieces);
}

TConstArrayView<FVerseBoltHole> UVerseBoltHoleComponent::GetPieceHoles(uint16 PieceIndex) const
{
	const FPieceHoles* Found = ByPiece.Find(PieceIndex);
	return Found ? TConstArrayView<FVerseBoltHole>(Found->Holes) : TConstArrayView<FVerseBoltHole>();
}

void UVerseBoltHoleComponent::GetAllHoles(TArray<FVerseBoltHole>& OutHoles) const
{
	TArray<int32> Live;
	Live.Reserve(LiveCount);
	for (int32 Index = 0; Index < Slots.Num(); ++Index)
	{
		if (IsLiveSlot(Index))
		{
			Live.Add(Index);
		}
	}
	Live.Sort([this](int32 A, int32 B) { return Slots[A].Sequence < Slots[B].Sequence; });
	OutHoles.Reset(Live.Num());
	for (const int32 Index : Live)
	{
		OutHoles.Add(Slots[Index].Hole);
	}
}

UVerseBoltHoleComponent::FHoleAxis::FHoleAxis(const FVerseBoltHole& Hole)
	: PointCm(Hole.GetAxisPointCm())
	, Direction(Hole.GetAxisDirection())
{
	const double RadiusCm = double(Hole.RadiusMm) / 10.0;
	RadiusSq = RadiusCm * RadiusCm;
}

bool UVerseBoltHoleComponent::FHoleAxis::Contains(const FVector& PieceLocalCm) const
{
	// Exactly FVerseBoltHole::ContainsPoint, with the axis already decoded.
	const FVector Rel = PieceLocalCm - PointCm;
	return (Rel - Direction * FVector::DotProduct(Rel, Direction)).SizeSquared() <= RadiusSq;
}

bool UVerseBoltHoleComponent::RayPassesPieceHoles(uint16 PieceIndex, const FVector& EntryLocalCm, const FVector& ExitLocalCm) const
{
	const FPieceHoles* Found = ByPiece.Find(PieceIndex);
	if (!Found)
	{
		return false;
	}
	for (const FHoleAxis& Axis : Found->Axes)
	{
		if (Axis.Contains(EntryLocalCm) && Axis.Contains(ExitLocalCm))
		{
			return true;
		}
	}
	return false;
}

int32 UVerseBoltHoleComponent::NumOnPiece(uint16 PieceIndex) const
{
	const FPieceHoles* Found = ByPiece.Find(PieceIndex);
	return Found ? Found->SlotIndices.Num() : 0;
}

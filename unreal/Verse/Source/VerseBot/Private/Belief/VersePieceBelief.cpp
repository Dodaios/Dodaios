#include "Belief/VersePieceBelief.h"

#include "Bot/VersePerceptTypes.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Perception/VersePerceptionModel.h"

namespace
{
	/** Sight is tested to a point this far in front of the piece, so the piece itself does not block it. */
	constexpr double SurfaceStandOffCm = 15.0;
}

void FVersePieceBelief::Initialize(const IVersePieceQuery& Query, const FBox& ArenaBox)
{
	Pieces.Reset();
	SlotOf.Reset();
	Changed.Reset();
	DirtyCover.Reset();
	Cursor = 0;
	TArray<uint16> Indices = Query.GetPiecesInBox(ArenaBox);
	Indices.Sort();
	for (const uint16 Index : Indices)
	{
		if (SlotOf.Contains(Index))
		{
			continue;
		}
		FVerseBelievedPiece& Piece = Pieces.AddDefaulted_GetRef();
		Piece.Index = Index;
		Piece.Material = Query.GetPieceMaterial(Index);
		Piece.Bounds = Query.GetPieceBounds(Index);
		Piece.State = EVersePieceState::Intact;
		SlotOf.Add(Index, Pieces.Num() - 1);
	}
}

void FVersePieceBelief::Initialize(TConstArrayView<FVersePieceLayoutEntry> Layout)
{
	Pieces.Reset();
	SlotOf.Reset();
	Changed.Reset();
	DirtyCover.Reset();
	Cursor = 0;
	TArray<FVersePieceLayoutEntry> Sorted(Layout.GetData(), Layout.Num());
	Sorted.Sort([](const FVersePieceLayoutEntry& A, const FVersePieceLayoutEntry& B) { return A.Index < B.Index; });
	for (const FVersePieceLayoutEntry& Entry : Sorted)
	{
		if (SlotOf.Contains(Entry.Index))
		{
			continue;
		}
		FVerseBelievedPiece& Piece = Pieces.AddDefaulted_GetRef();
		Piece.Index = Entry.Index;
		Piece.Material = Entry.Material;
		Piece.Bounds = Entry.Bounds;
		Piece.State = EVersePieceState::Intact;
		SlotOf.Add(Entry.Index, Pieces.Num() - 1);
	}
}

void FVersePieceBelief::ResetAll()
{
	for (int32 Slot = 0; Slot < Pieces.Num(); ++Slot)
	{
		FVerseBelievedPiece& Piece = Pieces[Slot];
		const bool bWasChanged = Piece.State != EVersePieceState::Intact || Piece.bChangedUnknown;
		Piece.State = EVersePieceState::Intact;
		Piece.bChangedUnknown = false;
		if (bWasChanged)
		{
			MarkChanged(Slot);
		}
	}
}

void FVersePieceBelief::SightPoints(const FBox& Bounds, FVector OutPoints[9])
{
	const FVector Centre = Bounds.GetCenter();
	const FVector Extent = Bounds.GetExtent() * 0.9;
	OutPoints[0] = Centre;
	int32 Out = 1;
	for (int32 Sx = -1; Sx <= 1; Sx += 2)
	{
		for (int32 Sy = -1; Sy <= 1; Sy += 2)
		{
			for (int32 Sz = -1; Sz <= 1; Sz += 2)
			{
				OutPoints[Out++] = Centre + FVector(Extent.X * Sx, Extent.Y * Sy, Extent.Z * Sz);
			}
		}
	}
}

int32 FVersePieceBelief::ObserveSight(const FVector& Eye, const FRotator& View, const IVersePieceQuery& Query,
	const IVersePenetrationQuery& Sight, float NowS, int32 MaxSightTests)
{
	const FVersePerceptionModel::FCone Cone = FVersePerceptionModel::ConeFor(false, VersePerception::DefaultAdsFovDeg);
	int32 Tests = 0;
	int32 Updates = 0;
	const int32 Count = Pieces.Num();
	for (int32 Step = 0; Step < Count && Tests < MaxSightTests; ++Step)
	{
		const int32 Slot = (Cursor + Step) % Count;
		FVerseBelievedPiece& Piece = Pieces[Slot];
		if (!Piece.Bounds.IsValid)
		{
			continue;
		}
		FVector Points[9];
		SightPoints(Piece.Bounds, Points);
		bool bSeen = false;
		for (const FVector& Point : Points)
		{
			if (FVersePerceptionModel::Classify(Eye, View, Cone, Point) != FVersePerceptionModel::EConeZone::Inside)
			{
				continue;
			}
			const FVector ToEye = (Eye - Point).GetSafeNormal();
			const FVector Target = Point + ToEye * SurfaceStandOffCm;
			++Tests;
			if (Sight.TestSight(Eye, Target))
			{
				bSeen = true;
				break;
			}
			if (Tests >= MaxSightTests)
			{
				break;
			}
		}
		if (Tests >= MaxSightTests && !bSeen)
		{
			Cursor = Slot;
			break;
		}
		if (!bSeen)
		{
			continue;
		}
		// Seen: the bot sees what is there (destruction.md 6.2, no error on state).
		const EVersePieceState Truth = Query.GetPieceState(Piece.Index);
		const FBox Bounds = Query.GetPieceBounds(Piece.Index);
		Piece.LastSeenS = NowS;
		if (Bounds.IsValid)
		{
			Piece.Bounds = Bounds;
		}
		if (Truth != Piece.State || Piece.bChangedUnknown)
		{
			const bool bStateChanged = Truth != Piece.State;
			Piece.State = Truth;
			Piece.bChangedUnknown = false;
			MarkChanged(Slot);
			Updates += bStateChanged ? 1 : 0;
		}
		Cursor = (Slot + 1) % FMath::Max(1, Count);
	}
	return Updates;
}

void FVersePieceBelief::OnHeardFracture(const FVerseHeardPercept& Heard, float NowS)
{
	const double Radius = FMath::Max(100.0, 2.0 * double(Heard.ErrorSdM) * 100.0);
	for (int32 Slot = 0; Slot < Pieces.Num(); ++Slot)
	{
		FVerseBelievedPiece& Piece = Pieces[Slot];
		if (!Piece.Bounds.IsValid)
		{
			continue;
		}
		const FVector Closest = Piece.Bounds.GetClosestPointTo(Heard.Location);
		const double Horizontal = FVector2D(Closest.X - Heard.Location.X, Closest.Y - Heard.Location.Y).Size();
		if (Horizontal <= Radius && !Piece.bChangedUnknown)
		{
			Piece.bChangedUnknown = true;
			MarkChanged(Slot);
		}
	}
}

void FVersePieceBelief::OnOwnAction(uint16 PieceIndex, EVersePieceState NewState, float NowS)
{
	const int32 Slot = FindIndex(PieceIndex);
	if (Slot == INDEX_NONE)
	{
		return;
	}
	FVerseBelievedPiece& Piece = Pieces[Slot];
	if (Piece.State != NewState || Piece.bChangedUnknown)
	{
		Piece.State = NewState;
		Piece.bChangedUnknown = false;
		MarkChanged(Slot);
	}
}

int32 FVersePieceBelief::FindIndex(uint16 Piece) const
{
	const int32* Slot = SlotOf.Find(Piece);
	return Slot ? *Slot : INDEX_NONE;
}

void FVersePieceBelief::MarkChanged(int32 Slot)
{
	const uint16 Index = Pieces[Slot].Index;
	Changed.AddUnique(Index);
	for (const TPair<int32, TArray<uint16>>& Cover : CoverDeps)
	{
		if (Cover.Value.Contains(Index))
		{
			DirtyCover.Add(Cover.Key);
		}
	}
}

const FVerseBelievedPiece* FVersePieceBelief::Find(uint16 Piece) const
{
	const int32 Slot = FindIndex(Piece);
	return Slot == INDEX_NONE ? nullptr : &Pieces[Slot];
}

EVersePieceState FVersePieceBelief::GetBelievedState(uint16 Piece) const
{
	const FVerseBelievedPiece* Found = Find(Piece);
	return Found ? Found->State : EVersePieceState::Intact;
}

bool FVersePieceBelief::IsBelievedOpen(int32 Piece) const
{
	if (Piece < 0 || Piece > MAX_uint16)
	{
		return false;
	}
	const EVersePieceState State = GetBelievedState(uint16(Piece));
	return State == EVersePieceState::Breached || State == EVersePieceState::Destroyed;
}

bool FVersePieceBelief::IsBelievedStanding(int32 Piece) const
{
	if (Piece < 0 || Piece > MAX_uint16)
	{
		return true;
	}
	return GetBelievedState(uint16(Piece)) != EVersePieceState::Destroyed;
}

void FVersePieceBelief::RegisterCover(int32 CoverId, TConstArrayView<uint16> DependsOn)
{
	CoverDeps.FindOrAdd(CoverId) = TArray<uint16>(DependsOn.GetData(), DependsOn.Num());
}

void FVersePieceBelief::UnregisterCover(int32 CoverId)
{
	CoverDeps.Remove(CoverId);
	DirtyCover.Remove(CoverId);
}

TArray<int32> FVersePieceBelief::ConsumeDirtyCover()
{
	TArray<int32> Out = DirtyCover.Array();
	Out.Sort();
	DirtyCover.Reset();
	return Out;
}

TArray<uint16> FVersePieceBelief::ConsumeChangedPieces()
{
	TArray<uint16> Out = MoveTemp(Changed);
	Changed.Reset();
	return Out;
}

float FVersePieceBelief::OpaqueDistance(const FVector& Origin, const FVector& Direction, float MaxDistCm) const
{
	const FVector Dir = Direction.GetSafeNormal();
	if (Dir.IsNearlyZero())
	{
		return MaxDistCm;
	}
	const FVector End = Origin + Dir * MaxDistCm;
	float Best = MaxDistCm;
	for (const FVerseBelievedPiece& Piece : Pieces)
	{
		const bool bStops = Piece.Material == EVersePenetrationMaterial::Concrete ||
			Piece.Material == EVersePenetrationMaterial::ArmorSteel;
		if (!bStops || !Piece.Bounds.IsValid || Piece.State == EVersePieceState::Breached ||
			Piece.State == EVersePieceState::Destroyed)
		{
			continue;
		}
		FVector HitLocation;
		FVector HitNormal;
		float HitTime = 0.f;
		if (FMath::LineExtentBoxIntersection(Piece.Bounds, Origin, End, FVector::ZeroVector, HitLocation, HitNormal, HitTime))
		{
			Best = FMath::Min(Best, HitTime * MaxDistCm);
		}
	}
	return Best;
}

#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Destruction/VerseDestructionInterfaces.h"

namespace VerseBotBeliefTests
{
	/** One fake piece: truth state, material, bounds; blocks sight unless Breached or Destroyed. */
	struct FFakePiece
	{
		uint16 Index = 0;
		EVersePieceState State = EVersePieceState::Intact;
		EVersePenetrationMaterial Material = EVersePenetrationMaterial::SheetMetal;
		FBox Bounds = FBox(ForceInit);
	};

	/** An opaque static box (non-destructible architecture). */
	struct FFakeWall
	{
		FBox Box = FBox(ForceInit);
	};

	/**
	 * Fake of WP03's IVersePenetrationQuery (sight) and WP06's IVersePieceQuery (piece truth)
	 * for the belief tests (work-packages 0.3). Sight is blocked by walls and by pieces that are
	 * not Breached or Destroyed. GetPieceState calls are logged so tests can prove the belief reads
	 * a piece's truth only when it perceives it (bot.md F1, destruction.md DR6).
	 */
	class FFakeVerseBeliefWorld : public IVersePenetrationQuery, public IVersePieceQuery
	{
	public:
		TArray<FFakeWall> Walls;
		TArray<FFakePiece> Pieces;
		mutable int32 SightCalls = 0;
		mutable TArray<uint16> StateReads;

		void AddWall(const FVector& Min, const FVector& Max) { Walls.Add({FBox(Min, Max)}); }

		FFakePiece& AddPiece(uint16 Index, const FVector& Min, const FVector& Max, EVersePenetrationMaterial Material)
		{
			FFakePiece& Piece = Pieces.AddDefaulted_GetRef();
			Piece.Index = Index;
			Piece.Bounds = FBox(Min, Max);
			Piece.Material = Material;
			return Piece;
		}

		const FFakePiece* FindPiece(uint16 Index) const
		{
			return Pieces.FindByPredicate([Index](const FFakePiece& Piece) { return Piece.Index == Index; });
		}

		static bool SegmentHits(const FBox& Box, const FVector& A, const FVector& B)
		{
			FVector HitLocation;
			FVector HitNormal;
			float HitTime = 0.f;
			return FMath::LineExtentBoxIntersection(Box, A, B, FVector::ZeroVector, HitLocation, HitNormal, HitTime);
		}

		/** Geometry only (no call counting): used for neighbour connectivity at build. */
		bool Clear(const FVector& A, const FVector& B) const
		{
			for (const FFakeWall& Wall : Walls)
			{
				if (SegmentHits(Wall.Box, A, B))
				{
					return false;
				}
			}
			for (const FFakePiece& Piece : Pieces)
			{
				if (Piece.State != EVersePieceState::Breached && Piece.State != EVersePieceState::Destroyed &&
					SegmentHits(Piece.Bounds, A, B))
				{
					return false;
				}
			}
			return true;
		}

		// IVersePenetrationQuery
		virtual TArray<FVersePenetrationHit> TraceBolt(const FVector& Origin, const FVector& Dir, float MaxDist, float Power,
			float Damage, uint8 RadiusMm, int32 MaxPieces) const override
		{
			return {};
		}

		virtual bool TestSight(const FVector& Eye, const FVector& Target) const override
		{
			++SightCalls;
			return Clear(Eye, Target);
		}

		// IVersePieceQuery
		virtual EVersePieceState GetPieceState(uint16 PieceIndex) const override
		{
			StateReads.Add(PieceIndex);
			const FFakePiece* Piece = FindPiece(PieceIndex);
			return Piece ? Piece->State : EVersePieceState::Intact;
		}

		virtual EVersePenetrationMaterial GetPieceMaterial(uint16 PieceIndex) const override
		{
			const FFakePiece* Piece = FindPiece(PieceIndex);
			return Piece ? Piece->Material : EVersePenetrationMaterial::Concrete;
		}

		virtual FBox GetPieceBounds(uint16 PieceIndex) const override
		{
			const FFakePiece* Piece = FindPiece(PieceIndex);
			return Piece ? Piece->Bounds : FBox(ForceInit);
		}

		virtual TArray<uint16> GetPiecesInBox(const FBox& WorldBox) const override
		{
			TArray<uint16> Out;
			for (const FFakePiece& Piece : Pieces)
			{
				if (WorldBox.Intersect(Piece.Bounds))
				{
					Out.Add(Piece.Index);
				}
			}
			return Out;
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS

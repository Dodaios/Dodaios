#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Bot/VerseBotTier.h"
#include "Brain/VerseBotBelief.h"
#include "Brain/VerseBotWorldQueries.h"
#include "CoreMinimal.h"

/**
 * A box-wall arena that answers IVerseBotWorldQueries (WP08 fake of the world queries: the WP06
 * piece belief, the Recast path and the WP11 arena data). Walls are axis-aligned boxes on the floor;
 * a wall can be a destructible piece (penetrable, breachable). Sight and bolt traces are exact
 * segment-box tests, paths go straight or around one wall corner.
 */
class FFakeVerseBotWorldQueries final : public IVerseBotWorldQueries
{
public:
	struct FWall
	{
		FBox Box;
		int32 PieceIndex = INDEX_NONE;
		bool bPenetrable = false;
		bool bBreachable = false;
		bool bOpen = false;
	};

	TArray<FWall> Walls;
	TArray<FVector> Spawns;
	TArray<FVerseBotCoverPoint> Cover;
	bool bFinisherReady = true;
	FVerseBotWeaponInfo Weapon;
	int32 Calls = 0;

	/** Wall from (X0, Y0) to (X1, Y1) in metres, Height metres. */
	int32 AddWall(float X0, float Y0, float X1, float Y1, float HeightM, int32 Piece = INDEX_NONE, bool bPen = false, bool bBreach = false)
	{
		FWall W;
		W.Box = FBox(FVector(FMath::Min(X0, X1) * 100.f, FMath::Min(Y0, Y1) * 100.f, 0.f),
			FVector(FMath::Max(X0, X1) * 100.f, FMath::Max(Y0, Y1) * 100.f, HeightM * 100.f));
		W.PieceIndex = Piece;
		W.bPenetrable = bPen;
		W.bBreachable = bBreach;
		return Walls.Add(W);
	}

	/** Cover points on both long sides of every wall, one per end (edges) and one in the middle. */
	void BuildCover()
	{
		Cover.Reset();
		int32 Id = 0;
		for (int32 w = 0; w < Walls.Num(); ++w)
		{
			const FWall& W = Walls[w];
			const FVector C = W.Box.GetCenter();
			const FVector E = W.Box.GetExtent();
			const bool bAlongX = E.X >= E.Y;
			const FVector Along = bAlongX ? FVector(1, 0, 0) : FVector(0, 1, 0);
			const FVector Normal = bAlongX ? FVector(0, 1, 0) : FVector(1, 0, 0);
			const float Half = float(bAlongX ? E.X : E.Y);
			const float Thick = float(bAlongX ? E.Y : E.X);
			for (const float Side : {-1.f, 1.f})
			{
				for (const float T : {-0.8f, 0.f, 0.8f})
				{
					FVerseBotCoverPoint P;
					P.Id = Id++;
					P.Location = FVector(C.X, C.Y, 0.f) + Along * (T * Half) + Normal * Side * (Thick + 60.f);
					P.bHigh = W.Box.Max.Z >= 160.f;
					P.Facing = -Normal * Side;
					P.EdgeId = T != 0.f ? P.Id : INDEX_NONE;
					P.MaterialProtection = W.bPenetrable ? 0.4f : 1.f;
					P.bBulwarkSpot = false;
					if (W.PieceIndex != INDEX_NONE)
					{
						P.DependsOnPieces.Add(uint16(W.PieceIndex));
					}
					Cover.Add(P);
				}
			}
		}
		// Open-ground Bulwark spots on a 10 m grid.
		for (int32 x = -2; x <= 2; ++x)
		{
			for (int32 y = -2; y <= 2; ++y)
			{
				FVerseBotCoverPoint P;
				P.Id = Id++;
				P.Location = FVector(x * 1000.f, y * 800.f, 0.f);
				P.bBulwarkSpot = true;
				P.bHigh = true;
				if (!Blocked(P.Location + FVector(0, 0, 50), P.Location + FVector(0, 0, 50)))
				{
					Cover.Add(P);
				}
			}
		}
	}

	/** True when the segment enters a closed wall (Penetrable filter: -1 any, 0 solid only, 1 penetrable only). */
	bool Blocked(const FVector& A, const FVector& B, int32 Penetrable = -1, int32* OutCount = nullptr) const
	{
		int32 Count = 0;
		for (const FWall& W : Walls)
		{
			if (W.bOpen)
			{
				continue;
			}
			if (Penetrable == 0 && W.bPenetrable) continue;
			if (Penetrable == 1 && !W.bPenetrable) continue;
			if (SegmentHitsBox(A, B, W.Box))
			{
				++Count;
				if (!OutCount)
				{
					return true;
				}
			}
		}
		if (OutCount)
		{
			*OutCount = Count;
		}
		return Count > 0;
	}

	static bool SegmentHitsBox(const FVector& A, const FVector& B, const FBox& Box)
	{
		if (A.Equals(B))
		{
			return Box.IsInside(A);
		}
		return FMath::LineBoxIntersection(Box, A, B, B - A);
	}

	bool IsWalkable(const FVector& P) const
	{
		for (const FWall& W : Walls)
		{
			if (!W.bOpen && W.Box.ExpandBy(FVector(30.f, 30.f, 0.f)).IsInsideOrOnXY(P))
			{
				return false;
			}
		}
		return FMath::Abs(P.X) < 2600.f && FMath::Abs(P.Y) < 2100.f;
	}

	bool ClearWalk(const FVector& A, const FVector& B) const
	{
		const FVector Lift(0, 0, 50.f);
		for (const FWall& W : Walls)
		{
			if (!W.bOpen && SegmentHitsBox(A + Lift, B + Lift, W.Box.ExpandBy(FVector(30.f, 30.f, 0.f))))
			{
				return false;
			}
		}
		return true;
	}

	virtual bool TestSight(const FVector& Eye, const FVector& Target) override
	{
		++Calls;
		return !Blocked(Eye, Target);
	}

	virtual FVerseBotBoltTrace TraceBolt(const FVector& Origin, const FVector& Target, const FVerseBotWeaponInfo& InWeapon) override
	{
		++Calls;
		FVerseBotBoltTrace R;
		if (Blocked(Origin, Target, 0))
		{
			R.DamageFrac = 0.f;
			R.Pieces = 9;
			return R;
		}
		int32 N = 0;
		Blocked(Origin, Target, 1, &N);
		R.Pieces = N;
		R.DamageFrac = FMath::Pow(0.6f, float(N));
		return R;
	}

	virtual FVerseBotPath FindPath(const FVector& From, const FVector& To, bool bCrouch) override
	{
		++Calls;
		FVerseBotPath P;
		const FVector F(From.X, From.Y, 0.f), T(To.X, To.Y, 0.f);
		if (ClearWalk(F, T))
		{
			P.bValid = true;
			P.Waypoints.Add(T);
			P.LengthCm = float(FVector::Dist2D(F, T));
			return P;
		}
		float Best = 1.0e9f;
		FVector BestCorner = T;
		for (const FWall& W : Walls)
		{
			if (W.bOpen)
			{
				continue;
			}
			const FBox E = W.Box.ExpandBy(FVector(70.f, 70.f, 0.f));
			const FVector Corners[4] = {FVector(E.Min.X, E.Min.Y, 0), FVector(E.Min.X, E.Max.Y, 0), FVector(E.Max.X, E.Min.Y, 0), FVector(E.Max.X, E.Max.Y, 0)};
			for (const FVector& C : Corners)
			{
				if (IsWalkable(C) && ClearWalk(F, C) && ClearWalk(C, T))
				{
					const float L = float(FVector::Dist2D(F, C) + FVector::Dist2D(C, T));
					if (L < Best)
					{
						Best = L;
						BestCorner = C;
					}
				}
			}
		}
		if (Best < 1.0e9f)
		{
			P.bValid = true;
			P.Waypoints.Add(BestCorner);
			P.Waypoints.Add(T);
			P.LengthCm = Best;
		}
		return P;
	}

	virtual void GetCoverPoints(const FVector& Center, float RadiusCm, TArray<FVerseBotCoverPoint>& Out) override
	{
		++Calls;
		Out.Reset();
		for (const FVerseBotCoverPoint& P : Cover)
		{
			if (FVector::Dist2D(P.Location, Center) <= RadiusCm)
			{
				Out.Add(P);
			}
		}
	}

	virtual void GetPieces(const FVector& Center, float RadiusCm, TArray<FVerseBotPieceInfo>& Out) override
	{
		++Calls;
		Out.Reset();
		for (const FWall& W : Walls)
		{
			if (W.PieceIndex == INDEX_NONE || FVector::Dist2D(W.Box.GetCenter(), Center) > RadiusCm)
			{
				continue;
			}
			FVerseBotPieceInfo P;
			P.PieceIndex = uint16(W.PieceIndex);
			P.Center = FVector(W.Box.GetCenter().X, W.Box.GetCenter().Y, 100.f);
			const FVector E = W.Box.GetExtent();
			P.Normal = E.X >= E.Y ? FVector(0, 1, 0) : FVector(1, 0, 0);
			P.bBreachable = W.bBreachable;
			P.bPenetrable = W.bPenetrable;
			Out.Add(P);
		}
	}

	virtual void GetSpawnPoints(TArray<FVector>& Out) override
	{
		++Calls;
		Out = Spawns;
	}

	virtual int32 GetZoneId(const FVector& Location) override
	{
		++Calls;
		const int32 X = FMath::Clamp(FMath::FloorToInt32((Location.X + 2500.f) / 1000.f), 0, 4);
		const int32 Y = FMath::Clamp(FMath::FloorToInt32((Location.Y + 2000.f) / 1000.f), 0, 3);
		return Y * 5 + X;
	}

	virtual FVerseBotWeaponInfo GetOwnWeapon() override
	{
		++Calls;
		return Weapon;
	}

	virtual bool CanActivateFinisher() override
	{
		++Calls;
		return bFinisherReady;
	}

	/** The standard WP08 fixture: a 50 x 40 m arena with high walls, low cover and two breachable panels. */
	static void BuildStandardArena(FFakeVerseBotWorldQueries& W)
	{
		W.Walls.Reset();
		W.AddWall(-12.f, -1.f, -11.6f, 9.f, 3.f);
		W.AddWall(11.6f, -9.f, 12.f, 1.f, 3.f);
		W.AddWall(-4.f, 6.f, 4.f, 6.4f, 3.f, 1, true, true);
		W.AddWall(-4.f, -6.4f, 4.f, -6.f, 3.f, 2, true, true);
		W.AddWall(-1.f, -1.f, 1.f, 1.f, 1.f);
		W.AddWall(-20.f, -14.f, -16.f, -13.6f, 3.f);
		W.AddWall(16.f, 13.6f, 20.f, 14.f, 3.f);
		W.AddWall(-20.f, 10.f, -19.6f, 16.f, 1.f);
		W.AddWall(19.6f, -16.f, 20.f, -10.f, 1.f);
		W.Spawns = {FVector(-2200.f, -1700.f, 0.f), FVector(2200.f, 1700.f, 0.f), FVector(-2200.f, 1700.f, 0.f),
			FVector(2200.f, -1700.f, 0.f), FVector(0.f, 1700.f, 0.f), FVector(0.f, -1700.f, 0.f)};
		W.BuildCover();
	}
};

/** A scripted belief (WP07 fake): every derived value is set by the test. */
class FFakeVerseBotBelief final : public IVerseBotBelief
{
public:
	FVerseBotBeliefSummary S;
	float Mass = 0.f;
	float SupportedMass = 0.f;
	TArray<FVector> Cells;
	TMap<uint16, EVersePieceState> PieceStates;

	virtual void Reset() override {}
	virtual void Step(const FVersePerceptFrame&, float, const FVerseBotMatchMemory*, TConstArrayView<FVector>) override {}
	virtual void NoteOwnPieceChange(uint16 PieceIndex, EVersePieceState NewState) override { PieceStates.Add(PieceIndex, NewState); }
	virtual FVerseBotBeliefSummary Summary() const override { return S; }
	virtual float MassWithin(const FVector& L, float R) const override { return FVector::Dist2D(L, S.TopCenter) <= R + 300.f ? Mass : 0.f; }
	virtual float SupportedMassWithin(const FVector& L, float R) const override { return FVector::Dist2D(L, S.TopCenter) <= R + 300.f ? SupportedMass : 0.f; }
	virtual void TopCells(int32 N, TArray<FVector>& Out) const override
	{
		Out = Cells.Num() > 0 ? Cells : TArray<FVector>({S.TopCenter});
		if (Out.Num() > N)
		{
			Out.SetNum(N);
		}
	}
	virtual EVersePieceState GetPieceBelief(uint16 PieceIndex) const override
	{
		const EVersePieceState* St = PieceStates.Find(PieceIndex);
		return St ? *St : EVersePieceState::Intact;
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

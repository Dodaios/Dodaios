#include "Eqs/VerseBotEqs.h"

#include "Audit/VerseBotFireAudit.h"
#include "Bot/VerseBotTier.h"
#include "Eqs/VerseBeliefNavFilter.h"
#include "Learning/VerseBotMatchMemory.h"

namespace
{
	using FLayer = FVerseBotMatchMemory::ELayer;

	/** Candidate cap per query (budget, bot.md 2: EQS 0.2 ms amortised). */
	constexpr int32 MaxCoverCandidates = 10;
	constexpr int32 MaxWallbangCandidates = 6;
	constexpr int32 MaxBreachCandidates = 6;
	/** Chest height of a believed opponent, cm above the cell. */
	constexpr float EqsChestCm = 120.f;
	/** Radius of the learned danger sample around a point, cm. */
	constexpr float LearnRadiusCm = 500.f;

	float LearnedWeight(const FVerseBotQueryContext& Ctx, float Samples)
	{
		return (Ctx.bIgnoreLearned || !Ctx.Memory) ? 0.f : Ctx.Memory->Weight(Samples);
	}

	bool PieceBelievedBroken(const FVerseBotQueryContext& Ctx, uint16 Piece)
	{
		const EVersePieceState S = Ctx.BeliefMap->GetPieceBelief(Piece);
		return S == EVersePieceState::Holed || S == EVersePieceState::Breached || S == EVersePieceState::Destroyed;
	}

	/** Share of a path's waypoints the believed opponent can see (path exposure). */
	float PathExposure(const FVerseBotQueryContext& Ctx, const FVerseBotPath& Path, float EyeCm)
	{
		if (Path.Waypoints.Num() == 0)
		{
			return 0.f;
		}
		const FVector Top = Ctx.Belief->TopCenter + FVector(0, 0, VerseBotEqs::StandEyeCm);
		int32 Seen = 0;
		int32 Tested = 0;
		const int32 Step = FMath::Max(1, Path.Waypoints.Num() / 3);
		for (int32 i = 0; i < Path.Waypoints.Num(); i += Step)
		{
			++Tested;
			Seen += Ctx.World->TestSight(Top, Path.Waypoints[i] + FVector(0, 0, EyeCm)) ? 1 : 0;
		}
		return Tested > 0 ? float(Seen) / float(Tested) : 0.f;
	}

	template <typename T, typename F>
	void SortByDistance(TArray<T>& Items, const FVector& From, F&& LocationOf)
	{
		Items.StableSort([&](const T& A, const T& B)
			{ return FVector::DistSquared(LocationOf(A), From) < FVector::DistSquared(LocationOf(B), From); });
	}
}

namespace VerseBotEqs
{
	FVector BeliefTop(const FVerseBotQueryContext& Ctx)
	{
		return Ctx.Belief->TopCenter;
	}

	void BeliefCells(const FVerseBotQueryContext& Ctx, TArray<FVector>& Out)
	{
		Ctx.BeliefMap->TopCells(8, Out);
	}

	FVector BeliefFacing(const FVerseBotQueryContext& Ctx)
	{
		return FRotator(0.f, Ctx.Belief->FacingYawDeg, 0.f).Vector();
	}

	float Blend(float Base, float Learned, float W)
	{
		const float Wc = FMath::Clamp(W, 0.f, float(UVerseBotTier::LearnWeightMaxCap));
		return (1.f - Wc) * Base + Wc * Learned;
	}

	float OffFacingDeg(const FVerseBotQueryContext& Ctx, const FVector& Point)
	{
		const FVector To = (Point - Ctx.Belief->TopCenter).GetSafeNormal2D();
		const FVector Facing = BeliefFacing(Ctx);
		return FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(To, Facing)), -1.f, 1.f)));
	}

	bool HiddenFromBelief(const FVerseBotQueryContext& Ctx, const FVector& Point, TConstArrayView<FVector> Cells, bool bLowCover)
	{
		const FVector BotEye = Point + FVector(0, 0, bLowCover ? CrouchEyeCm : StandEyeCm);
		for (const FVector& Cell : Cells)
		{
			if (Ctx.World->TestSight(Cell + FVector(0, 0, StandEyeCm), BotEye)
				|| Ctx.World->TestSight(Cell + FVector(0, 0, CrouchEyeCm), BotEye))
			{
				return false;
			}
		}
		return true;
	}

	FVerseBotCoverResult Cover(const FVerseBotQueryContext& Ctx, EVerseBotCoverMode Mode)
	{
		FVerseBotCoverResult Result;
		const FVector Self = Ctx.Self->Location;
		const FVector Top = Ctx.Belief->TopCenter;
		TArray<FVerseBotCoverPoint> Points;
		Ctx.World->GetCoverPoints(Self, CoverRadiusCm, Points);
		SortByDistance(Points, Self, [](const FVerseBotCoverPoint& P) { return P.Location; });
		TArray<FVector> Cells;
		BeliefCells(Ctx, Cells);

		float BestScore = -1.0e9f;
		int32 Tested = 0;
		for (const FVerseBotCoverPoint& P : Points)
		{
			if (Tested >= MaxCoverCandidates)
			{
				break;
			}
			if (Mode == EVerseBotCoverMode::Bulwark ? !P.bBulwarkSpot : false)
			{
				continue;
			}
			bool bBroken = false;
			for (uint16 Piece : P.DependsOnPieces)
			{
				bBroken |= PieceBelievedBroken(Ctx, Piece);
			}
			if (bBroken)
			{
				continue;
			}
			++Tested;
			const FVerseBotPath Path = Ctx.World->FindPath(Self, P.Location, false);
			if (!Path.bValid || Path.LengthCm > CoverRadiusCm)
			{
				continue;
			}
			// A Bulwark brings its own cover; every other point must hide the bot from the belief.
			if (Mode != EVerseBotCoverMode::Bulwark && !HiddenFromBelief(Ctx, P.Location, Cells, !P.bHigh))
			{
				continue;
			}
			++Result.Candidates;
			const float DistTop = float(FVector::Dist2D(P.Location, Top));
			float Base = -0.35f * Path.LengthCm / CoverRadiusCm;
			Base -= 0.25f * PathExposure(Ctx, Path, StandEyeCm);
			switch (Mode)
			{
			case EVerseBotCoverMode::Near:
			case EVerseBotCoverMode::Bulwark:
				Base -= 0.2f * FMath::Abs(DistTop - Ctx.PreferredRangeCm) / FMath::Max(Ctx.PreferredRangeCm, 100.f);
				break;
			case EVerseBotCoverMode::Far:
				Base += 0.3f * FMath::Min(DistTop / 3000.f, 1.f);
				break;
			case EVerseBotCoverMode::Flank:
			{
				const float Off = OffFacingDeg(Ctx, P.Location);
				Base += 0.4f * FMath::Clamp(1.f - FMath::Abs(Off - 110.f) / 70.f, 0.f, 1.f);
				Base -= 0.1f * FMath::Abs(DistTop - Ctx.PreferredRangeCm) / FMath::Max(Ctx.PreferredRangeCm, 100.f);
				break;
			}
			}
			Base += 0.15f * FMath::Clamp(P.MaterialProtection, 0.f, 1.f);
			Base += P.EdgeId != INDEX_NONE ? 0.1f : 0.f;

			float Samples = 0.f;
			float Learned = Base;
			if (Ctx.Memory)
			{
				Samples = Ctx.Memory->SamplesNear(FLayer::Shooting, P.Location, LearnRadiusCm, Ctx.NowS);
				const float Danger = Ctx.Memory->HeatShare(FLayer::Shooting, P.Location, LearnRadiusCm, Ctx.NowS);
				Learned = Base - FMath::Clamp(Danger * 2.f, 0.f, 1.f);
			}
			const float Score = Blend(Base, Learned, LearnedWeight(Ctx, Samples));
			if (Score > BestScore)
			{
				BestScore = Score;
				Result.bFound = true;
				Result.Point = P;
				Result.Score = Score;
			}
		}
		return Result;
	}

	FVerseBotPeekResult PeekCorner(const FVerseBotQueryContext& Ctx, const FVerseBotCoverPoint& From)
	{
		struct FCandidate
		{
			EVerseBotPeekType Type;
			float Lateral;
			float EyeCm;
			float Exposure;
		};
		const UVerseBotTier& Tier = *Ctx.Tier;
		TArray<FCandidate, TInlineAllocator<10>> Candidates;
		Candidates.Add({EVerseBotPeekType::LeanLeft, -45.f, StandEyeCm, 0.3f});
		Candidates.Add({EVerseBotPeekType::LeanRight, 45.f, StandEyeCm, 0.3f});
		if (!From.bHigh)
		{
			Candidates.Add({EVerseBotPeekType::CrouchRise, 0.f, StandEyeCm, 0.5f});
		}
		for (const float Step : {120.f, 200.f, 280.f})
		{
			const float Exposure = 0.6f + 0.2f * (Step - 120.f) / 80.f;
			Candidates.Add({EVerseBotPeekType::StepOut, -Step, StandEyeCm, Exposure});
			Candidates.Add({EVerseBotPeekType::StepOut, Step, StandEyeCm, Exposure});
		}
		Candidates.Add({EVerseBotPeekType::JumpPeek, 0.f, StandEyeCm + 60.f, 0.7f});

		const FVector Facing = From.Facing.GetSafeNormal2D();
		const FVector Right = FVector::CrossProduct(FVector::UpVector, Facing).GetSafeNormal();
		const FVector Top = Ctx.Belief->TopCenter + FVector(0, 0, EqsChestCm);
		const FVector ViewAxis = Ctx.Self->ViewRotation.Vector();

		int32 Repeats = 0;
		for (int32 Edge : Ctx.RecentPeekEdges)
		{
			Repeats += (Edge != INDEX_NONE && Edge == From.EdgeId) ? 1 : 0;
		}

		FVerseBotPeekResult Best;
		float BestScore = -1.0e9f;
		for (const FCandidate& C : Candidates)
		{
			const FVector Stand = From.Location + Right * C.Lateral;
			const FVector Eye = Stand + FVector(0, 0, C.EyeCm);
			if (!Ctx.World->TestSight(Eye, Top))
			{
				continue;
			}
			const FVector Dir = (Top - Eye).GetSafeNormal();
			const float Angle = FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(float(FVector::DotProduct(Dir, ViewAxis)), -1.f, 1.f)));
			float Base = -0.4f * C.Exposure - 0.2f * Angle / 180.f;
			switch (C.Type)
			{
			case EVerseBotPeekType::LeanLeft:
			case EVerseBotPeekType::LeanRight:
				Base += 0.2f * Tier.LeanUse;
				break;
			case EVerseBotPeekType::CrouchRise:
				Base += 0.2f * Tier.CrouchPeekUse;
				break;
			default:
				break;
			}
			Base -= Tier.PeekRepeatPenalty * float(Repeats) / 3.f;

			float Samples = 0.f;
			float Learned = Base;
			if (Ctx.Memory)
			{
				// Avoid angles the person holds (they fire from there), prefer peeks onto their frequent spots.
				Samples = Ctx.Memory->SamplesNear(FLayer::Position, Ctx.Belief->TopCenter, LearnRadiusCm, Ctx.NowS)
					+ Ctx.Memory->SamplesNear(FLayer::Shooting, Ctx.Belief->TopCenter, LearnRadiusCm, Ctx.NowS);
				const float Frequent = Ctx.Memory->HeatShare(FLayer::Position, Ctx.Belief->TopCenter, LearnRadiusCm, Ctx.NowS);
				const float Held = Ctx.Memory->HeatShare(FLayer::Shooting, Ctx.Belief->TopCenter, LearnRadiusCm, Ctx.NowS);
				Learned = Base + 0.5f * Frequent - 0.5f * Held * C.Exposure;
			}
			const float Score = Blend(Base, Learned, LearnedWeight(Ctx, Samples));
			if (Score > BestScore)
			{
				BestScore = Score;
				Best.bFound = true;
				Best.Type = C.Type;
				Best.StandPoint = Stand;
				Best.Eye = Eye;
				Best.Score = Score;
			}
		}
		return Best;
	}

	FVerseBotWallbangResult WallbangSpot(const FVerseBotQueryContext& Ctx)
	{
		FVerseBotWallbangResult Best;
		const FVerseBotBeliefSummary& B = *Ctx.Belief;
		if (B.State == EVerseBeliefState::Dead || B.bPriorOnly)
		{
			return Best;
		}
		const FVector Aim = B.TopCenter + FVector(0, 0, EqsChestCm);
		TArray<FVector, TInlineAllocator<8>> Spots;
		Spots.Add(Ctx.Self->Location);
		TArray<FVerseBotCoverPoint> Points;
		Ctx.World->GetCoverPoints(Ctx.Self->Location, 800.f, Points);
		SortByDistance(Points, Ctx.Self->Location, [](const FVerseBotCoverPoint& P) { return P.Location; });
		for (const FVerseBotCoverPoint& P : Points)
		{
			if (Spots.Num() >= MaxWallbangCandidates)
			{
				break;
			}
			Spots.Add(P.Location);
		}
		TArray<FVector> Cells;
		BeliefCells(Ctx, Cells);

		float BestScore = -1.0e9f;
		for (const FVector& Spot : Spots)
		{
			const FVector Eye = Spot + FVector(0, 0, StandEyeCm);
			if (Ctx.World->TestSight(Eye, Aim))
			{
				continue; // In sight: not a wall shot.
			}
			const FVerseBotBoltTrace Trace = Ctx.World->TraceBolt(Eye, Aim, Ctx.Weapon);
			if (Trace.Pieces <= 0)
			{
				continue;
			}
			FVerseBotFireEvidence E;
			E.AimPoint = Aim;
			E.bAimInTopCluster = true;
			E.TraceDamageFrac = Trace.DamageFrac;
			E.TracePieces = Trace.Pieces;
			E.MassAtAim = Ctx.BeliefMap->MassWithin(Aim, FVerseBotFireClassifier::MassRadiusCm);
			E.SupportedMassAtAim = Ctx.BeliefMap->SupportedMassWithin(Aim, FVerseBotFireClassifier::MassRadiusCm);
			E.SupportAgeS = B.SupportAgeS;
			E.bPriorOnly = B.bPriorOnly;
			if (!FVerseBotFireClassifier::HasWallShotAuthority(E, *Ctx.Tier))
			{
				continue;
			}
			const bool bHidden = HiddenFromBelief(Ctx, Spot, Cells, false);
			const float Score = E.SupportedMassAtAim + 0.5f * Trace.DamageFrac - (bHidden ? 0.f : 0.3f)
				- 0.1f * float(FVector::Dist(Spot, Ctx.Self->Location)) / 800.f;
			if (Score > BestScore)
			{
				BestScore = Score;
				Best.bFound = true;
				Best.FireFrom = Spot;
				Best.AimPoint = Aim;
				Best.DamageFrac = Trace.DamageFrac;
				Best.Pieces = Trace.Pieces;
				Best.Score = Score;
			}
		}
		return Best;
	}

	FVerseBotBreachResult BreachSpot(const FVerseBotQueryContext& Ctx)
	{
		FVerseBotBreachResult Best;
		const FVerseBotBeliefSummary& B = *Ctx.Belief;
		if (B.State == EVerseBeliefState::Dead)
		{
			return Best;
		}
		const FVector Self = Ctx.Self->Location;
		TArray<FVerseBotPieceInfo> Pieces;
		Ctx.World->GetPieces(Self, BreachRadiusCm, Pieces);
		SortByDistance(Pieces, Self, [](const FVerseBotPieceInfo& P) { return P.Center; });
		TArray<FVector> Cells;
		BeliefCells(Ctx, Cells);
		const FVerseBotPath Direct = Ctx.World->FindPath(Self, B.TopCenter, false);
		const float DirectLen = Direct.bValid ? Direct.LengthCm : 2.f * float(FVector::Dist(Self, B.TopCenter)) + 2000.f;

		TPair<int32, int32> Route(INDEX_NONE, INDEX_NONE);
		if (Ctx.Memory)
		{
			Route = Ctx.Memory->MostUsedRoute();
		}

		float BestScore = -1.0e9f;
		int32 Tested = 0;
		for (const FVerseBotPieceInfo& P : Pieces)
		{
			if (!P.bBreachable || Ctx.BeliefMap->GetPieceBelief(P.PieceIndex) != EVersePieceState::Intact)
			{
				continue;
			}
			if (++Tested > MaxBreachCandidates)
			{
				break;
			}
			const FVector N = P.Normal.GetSafeNormal2D();
			const float Side = FVector::DotProduct(Self - P.Center, N) >= 0.f ? 1.f : -1.f;
			const FVector Plant = P.Center + N * Side * 60.f;
			const FVector Wait = P.Center + N * Side * (BreachSelfDamageRadiusCm + 60.f);
			// The far side must face the belief, or the breach opens nothing useful.
			if (FVector::DotProduct(B.TopCenter - P.Center, N) * Side >= 0.f)
			{
				continue;
			}
			if (float(FVector::Dist(Wait, P.Center)) <= BreachSelfDamageRadiusCm)
			{
				continue;
			}
			if (!HiddenFromBelief(Ctx, Plant, Cells, false))
			{
				continue;
			}
			const FVerseBotPath ToPlant = Ctx.World->FindPath(Self, Plant, false);
			if (!ToPlant.bValid)
			{
				continue;
			}
			const float Through = ToPlant.LengthCm + float(FVector::Dist(Plant, B.TopCenter));
			const float Shortening = (DirectLen - Through) / 2000.f;
			const float Angle = OffFacingDeg(Ctx, P.Center) / 180.f;
			const float NoiseDist = float(FVector::Dist(Plant, B.TopCenter));
			const float Noise = NoiseDist < 1000.f ? 0.3f * (1.f - NoiseDist / 1000.f) : 0.f;
			const float SpreadGrowth = 450.f * BreachFuseS / 2000.f;
			const float Base = Shortening + 0.3f * Angle - Noise - 0.2f * SpreadGrowth * (1.f - B.Confidence);

			float Learned = Base;
			float Samples = 0.f;
			if (Ctx.Memory && Route.Key != INDEX_NONE)
			{
				const int32 Zone = Ctx.World->GetZoneId(P.Center);
				Samples = 6.f * Ctx.Memory->ZoneTransitionProb(Route.Key, Route.Value) + 1.f;
				Learned = Base + ((Zone == Route.Key || Zone == Route.Value) ? 0.5f : 0.f);
			}
			const float Score = Blend(Base, Learned, LearnedWeight(Ctx, Samples));
			if (Score > BestScore && Shortening > -0.5f)
			{
				BestScore = Score;
				Best.bFound = true;
				Best.PieceIndex = P.PieceIndex;
				Best.PlantPoint = Plant;
				Best.WaitPoint = Wait;
				Best.Score = Score;
			}
		}
		return Best;
	}

	FVerseBotFinisherResult FinisherApproach(const FVerseBotQueryContext& Ctx)
	{
		FVerseBotFinisherResult Best;
		const FVerseBotBeliefSummary& B = *Ctx.Belief;
		const UVerseBotTier& Tier = *Ctx.Tier;
		if (B.State == EVerseBeliefState::Dead || B.Confidence < Tier.FinisherCommitConfidence)
		{
			return Best;
		}
		const FVector Facing = BeliefFacing(Ctx);
		const FVector TopEye = B.TopCenter + FVector(0, 0, StandEyeCm);
		const float CosCone = FMath::Cos(FMath::DegreesToRadians(BelievedViewHalfAngleDeg));
		float BestScore = -1.0e9f;
		for (const float RelDeg : {130.f, 155.f, 180.f, 205.f, 230.f})
		{
			const FVector Dir = Facing.RotateAngleAxis(RelDeg, FVector::UpVector);
			const FVector Point = B.TopCenter + Dir * (FinisherRangeCm * 0.8f);
			if (OffFacingDeg(Ctx, Point) <= FinisherArcDeg)
			{
				continue;
			}
			const FVerseBotPath Path = Ctx.World->FindPath(Ctx.Self->Location, Point, true);
			if (!Path.bValid)
			{
				continue;
			}
			const float Arrival = Path.LengthCm / CrouchSpeedCmS;
			if (Arrival > Tier.MaxStalkS)
			{
				continue;
			}
			// The whole crouch path stays outside the believed view cone (or out of its sight).
			bool bExposed = false;
			int32 InCone = 0;
			for (const FVector& W : Path.Waypoints)
			{
				const FVector To = (W - B.TopCenter).GetSafeNormal2D();
				if (float(FVector::DotProduct(To, Facing)) > CosCone)
				{
					++InCone;
					if (Ctx.World->TestSight(TopEye, W + FVector(0, 0, CrouchEyeCm)))
					{
						bExposed = true;
						break;
					}
				}
			}
			if (bExposed)
			{
				continue;
			}
			const float Score = -Path.LengthCm / 1000.f - 0.2f * float(InCone) / FMath::Max(1, Path.Waypoints.Num());
			if (Score > BestScore)
			{
				BestScore = Score;
				Best.bFound = true;
				Best.Approach = Point;
				Best.PathLengthCm = Path.LengthCm;
				Best.ArrivalS = Arrival;
				Best.Score = Score;
			}
		}
		return Best;
	}
}

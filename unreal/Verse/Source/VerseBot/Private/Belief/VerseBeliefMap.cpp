#include "Belief/VerseBeliefMap.h"

#include "Destruction/VerseDestructionInterfaces.h"
#include "Perception/VersePerceptionModel.h"
#include "VerseGameplayTags.h"

namespace
{
	/** Sample heights of a cell test, in rotation order: 1.6 m, 1.0 m, then 0.4 m where prone is possible. */
	constexpr float CellSightHeightsCm[3] = {160.f, 100.f, 40.f};
	/** Bound on the hurt and bolt wedges, cm. */
	constexpr float WedgeMaxRangeCm = 8000.f;

	/** The view cone of bot.md 3.1 as cheap comparisons (no trigonometry per point). */
	struct FClearCone
	{
		double Fx = 1.0;
		double Fy = 0.0;
		double CosHalf = 0.0;
		double TanLo = 0.0;
		double TanHi = 0.0;
		bool bLoOpen = false;
		bool bHiOpen = false;

		explicit FClearCone(const FRotator& View)
		{
			const double Yaw = FMath::DegreesToRadians(double(View.Yaw));
			Fx = FMath::Cos(Yaw);
			Fy = FMath::Sin(Yaw);
			CosHalf = FMath::Cos(FMath::DegreesToRadians(double(VersePerception::ViewHalfAngleDeg)));
			const double Pitch = double(FRotator::NormalizeAxis(View.Pitch));
			const double Lo = Pitch - double(VersePerception::VerticalHalfAngleDeg);
			const double Hi = Pitch + double(VersePerception::VerticalHalfAngleDeg);
			bLoOpen = Lo <= -89.999;
			bHiOpen = Hi >= 89.999;
			TanLo = bLoOpen ? 0.0 : FMath::Tan(FMath::DegreesToRadians(Lo));
			TanHi = bHiOpen ? 0.0 : FMath::Tan(FMath::DegreesToRadians(Hi));
		}

		/** Horizontal half-angle against the view yaw, elevation within the vertical half-angle of the pitch. */
		bool Contains(const FVector& Eye, const FVector& Point) const
		{
			const double Vx = Point.X - Eye.X;
			const double Vy = Point.Y - Eye.Y;
			const double Vz = Point.Z - Eye.Z;
			const double H = FMath::Sqrt(Vx * Vx + Vy * Vy);
			if (H < 1.0)
			{
				return true;
			}
			if (Vx * Fx + Vy * Fy < CosHalf * H)
			{
				return false;
			}
			if (!bLoOpen && Vz < H * TanLo)
			{
				return false;
			}
			return bHiOpen || Vz <= H * TanHi;
		}
	};
}

void FVerseBeliefMap::Initialize(const FVerseBeliefGridSource& Source, const FVerseBeliefMapConfig& InConfig,
	const FVerseBeliefWorld& World, const FVerseBeliefTuning& Tuning)
{
	Config = InConfig;
	Grid.Build(Source, Tuning);
	Opponent = FVerseOpponentEstimate();
	Pieces = FVersePieceBelief();
	if (Config.PieceLayout.Num() > 0)
	{
		Pieces.Initialize(Config.PieceLayout);
	}
	else if (World.Pieces)
	{
		Pieces.Initialize(*World.Pieces, Config.ArenaBox);
	}
	RefreshGates();
	Grid.ResetUniform();
	const int32 Num = Grid.NumCells();
	CachedVisible.Init(0, Num);
	CachedEye.Init(FVector(TNumericLimits<float>::Max()), Num);
	CachedAtS.Init(-1000.f, Num);
	CachedHeight.Init(0, Num);
	VisibleScratch.Reset();
	ClearCursor = 0;
	LastClearSightTests = 0;
	LastStepS = -1.f;
	StepCount = 0;
	bHasFrame = false;
	Derived = Grid.ComputeDerived(0.f, false);
}

void FVerseBeliefMap::RefreshGates()
{
	Pieces.ConsumeChangedPieces();
	Grid.ApplyGates([this](int32 Piece) { return Pieces.IsBelievedOpen(Piece); },
		[this](int32 Piece) { return Pieces.IsBelievedStanding(Piece); });
}

bool FVerseBeliefMap::TestCellVisible(int32 Cell, const FVector& Eye, const FRotator& View, const IVersePenetrationQuery& Sight) const
{
	const FVector Centre = Grid.GetCellCentre(Cell);
	const FClearCone Cone(View);
	const int32 Heights = Grid.GetCell(Cell).bProneCapable ? 3 : 2;
	for (int32 Height = 0; Height < Heights; ++Height)
	{
		const FVector Point = Centre + FVector(0.0, 0.0, CellSightHeightsCm[Height]);
		if (Cone.Contains(Eye, Point) && Sight.TestSight(Eye, Point))
		{
			return true;
		}
	}
	return false;
}

void FVerseBeliefMap::RunClear(const FVerseSelfPercept& Self, const FVerseBeliefWorld& World, float NowS)
{
	LastClearSightTests = 0;
	if (!World.Sight || Self.Phase == EVerseCombatPhase::Dead)
	{
		return;
	}
	const FVector Eye = Self.EyeLocation;
	const FClearCone Cone(Self.ViewRotation);
	const int32 Num = Grid.NumCells();
	if (Num == 0)
	{
		return;
	}
	const double RangeSq = FMath::Square(double(Config.ClearRangeCm));
	const double MoveSq = FMath::Square(double(Config.VisibilityCacheMoveCm));
	const float MaxAgeS = Config.VisibilityCacheMaxAgeS;

	// Every in-cone cell with a valid cache is cleared from the cache; stale ones are retested, one
	// trace each, in a rotating order until the budget is spent. The rest wait for the next step.
	VisibleScratch.Reset();
	int32 Budget = Config.MaxCellSightTestsPerStep;
	int32 StoppedAt = INDEX_NONE;
	for (int32 Step = 0; Step < Num; ++Step)
	{
		int32 Cell = ClearCursor + Step;
		Cell -= Cell >= Num ? Num : 0;
		if (!Grid.IsActive(Cell))
		{
			continue;
		}
		const FVector Centre = Grid.GetCellCentre(Cell);
		const FVector Mid = Centre + FVector(0.0, 0.0, 130.0);
		if (FVector::DistSquared(Eye, Mid) > RangeSq || !Cone.Contains(Eye, Mid))
		{
			continue;
		}
		const bool bCacheValid = FVector::DistSquared(CachedEye[Cell], Eye) <= MoveSq && NowS - CachedAtS[Cell] <= MaxAgeS;
		if (!bCacheValid)
		{
			if (Budget <= 0)
			{
				if (StoppedAt == INDEX_NONE)
				{
					StoppedAt = Cell;
				}
				continue;
			}
			--Budget;
			const int32 Heights = Grid.GetCell(Cell).bProneCapable ? 3 : 2;
			const int32 Height = CachedHeight[Cell] % Heights;
			CachedHeight[Cell] = uint8((Height + 1) % Heights);
			const FVector Point = Centre + FVector(0.0, 0.0, CellSightHeightsCm[Height]);
			CachedVisible[Cell] = Cone.Contains(Eye, Point) && World.Sight->TestSight(Eye, Point) ? 1 : 0;
			CachedEye[Cell] = Eye;
			CachedAtS[Cell] = NowS;
		}
		if (CachedVisible[Cell])
		{
			VisibleScratch.Add(Cell);
		}
	}
	LastClearSightTests = Config.MaxCellSightTestsPerStep - Budget;
	if (StoppedAt != INDEX_NONE)
	{
		ClearCursor = StoppedAt;
	}
	Grid.Clear(Eye, VisibleScratch, NowS);
}

TArray<FVector> FVerseBeliefMap::RankSpawnPoints(const FVector& Eye, const IVersePenetrationQuery* Sight) const
{
	struct FRanked
	{
		FVector Point;
		bool bHidden;
		double Dist;
		int32 Index;
	};
	TArray<FRanked> Ranked;
	for (int32 Index = 0; Index < Config.SpawnPoints.Num(); ++Index)
	{
		const FVector& Point = Config.SpawnPoints[Index];
		const bool bHidden = Sight ? !Sight->TestSight(Eye, Point + FVector(0.0, 0.0, 150.0)) : true;
		Ranked.Add({Point, bHidden, FVector::Dist(Eye, Point), Index});
	}
	Ranked.Sort([](const FRanked& A, const FRanked& B) {
		if (A.bHidden != B.bHidden)
		{
			return A.bHidden;
		}
		if (A.Dist != B.Dist)
		{
			return A.Dist > B.Dist;
		}
		return A.Index < B.Index;
	});
	TArray<FVector> Out;
	for (const FRanked& Item : Ranked)
	{
		Out.Add(Item.Point);
	}
	return Out;
}

bool FVerseBeliefMap::ApplyFrame(const FVersePerceptFrame& Frame, const FVerseBeliefWorld& World)
{
	const float NowS = float(double(Frame.ServerTimeMs) / 1000.0);

	bool bPositive = Frame.Sightings.Num() > 0 || Frame.Bolts.Num() > 0 || Frame.bHasHurt;
	for (const FVerseHeardPercept& Heard : Frame.Heard)
	{
		bPositive |= Heard.Noise != VerseTags::Noise_Impact && Heard.Noise != VerseTags::Noise_Drone;
	}
	bPositive |= Frame.Hud.Num() > 0;
	const bool bDue = !bHasFrame || NowS - LastStepS >= Config.StepIntervalS - 1e-4f;
	if (!bDue && !bPositive)
	{
		return false;
	}
	const float DeltaS = bHasFrame ? FMath::Clamp(NowS - LastStepS, 0.f, 1.f) : 0.f;

	// Own death first: the belief is cleared before this step's evidence lands.
	for (const FVerseHudEvent& Hud : Frame.Hud)
	{
		if (Hud.Kind == EVerseHudEventKind::Kill && Hud.VictimId == Config.SelfPlayerId)
		{
			Grid.ResetUniform();
			Grid.ClearMomentum();
		}
	}

	// bot.md 4.2 order: predict, clear, sighting, heard, hurt / bolt, kill feed, normalise. Clearing
	// and looking at pieces trace sight, so they run on the 10 Hz steps only; a step that runs at
	// once for a positive percept between them skips the traces (bot.md 2 budget).
	Grid.Predict(DeltaS, NowS);
	if (bDue)
	{
		RunClear(Frame.Self, World, NowS);
	}
	else
	{
		LastClearSightTests = 0;
	}

	const bool bSighted = Frame.Sightings.Num() > 0;
	if (bSighted)
	{
		// One opponent in a duel: the first sighting is the opponent.
		const FVerseSightPercept& Sight = Frame.Sightings[0];
		Grid.ApplySighting(Sight.PelvisLocation, NowS);
		Grid.SetMomentum(Sight.Velocity, NowS);
		Opponent.OnSighting(Sight, NowS);
	}

	for (const FVerseHeardPercept& Heard : Frame.Heard)
	{
		Opponent.OnHeard(Heard, NowS);
		if (Heard.Noise == VerseTags::Noise_Fracture)
		{
			// A fracture says a piece changed, not where the opponent is.
			Pieces.OnHeardFracture(Heard, NowS);
			continue;
		}
		if (Heard.Noise == VerseTags::Noise_Impact || Heard.Noise == VerseTags::Noise_Drone || bSighted)
		{
			continue;
		}
		Grid.ApplyHeard(Heard, NowS);
	}

	if (!bSighted)
	{
		if (Frame.bHasHurt)
		{
			const FVector Eye = Frame.Self.EyeLocation;
			const FVector Back = Frame.Hurt.IncomingDirection.GetSafeNormal();
			Grid.ApplyWedge(Eye, Back, Pieces.OpaqueDistance(Eye, Back, WedgeMaxRangeCm), NowS);
		}
		for (const FVerseBoltPercept& Bolt : Frame.Bolts)
		{
			Opponent.OnSeenShot(NowS);
			const FVector Back = -Bolt.Direction.GetSafeNormal();
			Grid.ApplyWedge(Bolt.Position, Back, Pieces.OpaqueDistance(Bolt.Position, Back, WedgeMaxRangeCm), NowS);
		}
	}

	for (const FVerseHudEvent& Hud : Frame.Hud)
	{
		switch (Hud.Kind)
		{
		case EVerseHudEventKind::Kill:
			if (Hud.VictimId != Config.SelfPlayerId)
			{
				Grid.ApplyOpponentDead();
				Opponent.OnOpponentDead();
			}
			else if (Hud.bKillerPositionShown)
			{
				// The kill cam showed where the killer stood.
				Grid.ApplySighting(Hud.KillerPosition, NowS);
			}
			break;
		case EVerseHudEventKind::OpponentRespawned:
			if (Hud.VictimId != Config.SelfPlayerId)
			{
				Grid.ApplySpawnPrior(RankSpawnPoints(Frame.Self.EyeLocation, World.Sight), NowS);
				Opponent.OnOpponentRespawned();
			}
			break;
		case EVerseHudEventKind::HitMarker:
			Opponent.OnOwnHit(Config.OwnHitDamage, NowS);
			break;
		case EVerseHudEventKind::HeadshotMarker:
			Opponent.OnOwnHit(Config.OwnHeadshotDamage, NowS);
			break;
		default:
			break;
		}
	}

	Grid.Normalise();

	if (bDue && World.Pieces && World.Sight && Frame.Self.Phase != EVerseCombatPhase::Dead)
	{
		Pieces.ObserveSight(Frame.Self.EyeLocation, Frame.Self.ViewRotation, *World.Pieces, *World.Sight, NowS,
			Config.MaxPieceSightTestsPerStep);
	}
	if (Pieces.ConsumeChangedPieces().Num() > 0)
	{
		Grid.ApplyGates([this](int32 Piece) { return Pieces.IsBelievedOpen(Piece); },
			[this](int32 Piece) { return Pieces.IsBelievedStanding(Piece); });
	}

	Derived = Grid.ComputeDerived(NowS, bSighted);
	LastStepS = NowS;
	++StepCount;
	bHasFrame = true;
	return true;
}

void FVerseBeliefMap::OnOwnDeath(float NowS)
{
	Grid.ResetUniform();
	Grid.ClearMomentum();
	Derived = Grid.ComputeDerived(NowS, false);
}

void FVerseBeliefMap::OnOwnPieceAction(uint16 Piece, EVersePieceState NewState, float NowS)
{
	Pieces.OnOwnAction(Piece, NewState, NowS);
	RefreshGates();
}

void FVerseBeliefMap::OnDestructionReset()
{
	Pieces.ResetAll();
	RefreshGates();
}

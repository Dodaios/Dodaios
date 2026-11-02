#include "Belief/VerseBeliefMap.h"

#include "Destruction/VerseDestructionInterfaces.h"
#include "Perception/VersePerceptionModel.h"
#include "VerseGameplayTags.h"

namespace
{
	constexpr float CellSightHeightsCm[2] = {100.f, 160.f};
	constexpr float ProneSightHeightCm = 40.f;
	constexpr float CacheMaxAgeS = 1.0f;
	/** Bound on the hurt and bolt wedges, cm. */
	constexpr float WedgeMaxRangeCm = 8000.f;
}

void FVerseBeliefMap::Initialize(const FVerseBeliefGridSource& Source, const FVerseBeliefMapConfig& InConfig,
	const FVerseBeliefWorld& World, const FVerseBeliefTuning& Tuning)
{
	Config = InConfig;
	Grid.Build(Source, Tuning);
	Opponent = FVerseOpponentEstimate();
	Pieces = FVersePieceBelief();
	if (World.Pieces)
	{
		Pieces.Initialize(*World.Pieces, Config.ArenaBox);
	}
	RefreshGates();
	Grid.ResetUniform();
	const int32 Num = Grid.NumCells();
	CachedVisible.Init(0, Num);
	CachedEye.Init(FVector(TNumericLimits<float>::Max()), Num);
	CachedAtS.Init(-1000.f, Num);
	ClearCursor = 0;
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

bool FVerseBeliefMap::InViewCone(const FVector& Eye, const FVector& ForwardFlat, float ViewPitchDeg, const FVector& Point) const
{
	const FVector V = Point - Eye;
	const double H = FMath::Sqrt(V.X * V.X + V.Y * V.Y);
	if (H < 1.0)
	{
		return true;
	}
	static const double CosHalf = FMath::Cos(FMath::DegreesToRadians(double(VersePerception::ViewHalfAngleDeg)));
	if ((V.X * ForwardFlat.X + V.Y * ForwardFlat.Y) < CosHalf * H)
	{
		return false;
	}
	const double ElevationDeg = FMath::RadiansToDegrees(FMath::Atan2(V.Z, H));
	return FMath::Abs(ElevationDeg - double(ViewPitchDeg)) <= VersePerception::VerticalHalfAngleDeg;
}

bool FVerseBeliefMap::TestCellVisible(int32 Cell, const FVector& Eye, const FRotator& View, const IVersePenetrationQuery& Sight) const
{
	const FVector Centre = Grid.GetCellCentre(Cell);
	const FVector Forward = FRotator(0.f, View.Yaw, 0.f).Vector();
	const float Pitch = FRotator::NormalizeAxis(View.Pitch);
	for (const float Height : CellSightHeightsCm)
	{
		const FVector Point = Centre + FVector(0.0, 0.0, Height);
		if (InViewCone(Eye, Forward, Pitch, Point) && Sight.TestSight(Eye, Point))
		{
			return true;
		}
	}
	if (Grid.GetCell(Cell).bProneCapable)
	{
		const FVector Point = Centre + FVector(0.0, 0.0, ProneSightHeightCm);
		return InViewCone(Eye, Forward, Pitch, Point) && Sight.TestSight(Eye, Point);
	}
	return false;
}

void FVerseBeliefMap::RunClear(const FVerseSelfPercept& Self, const FVerseBeliefWorld& World, float NowS)
{
	if (!World.Sight || Self.Phase == EVerseCombatPhase::Dead)
	{
		return;
	}
	const FVector Eye = Self.EyeLocation;
	const FVector Forward = FRotator(0.f, Self.ViewRotation.Yaw, 0.f).Vector();
	const float Pitch = FRotator::NormalizeAxis(Self.ViewRotation.Pitch);
	const int32 Num = Grid.NumCells();
	const double RangeSq = FMath::Square(double(Config.ClearRangeCm));
	const double MoveSq = FMath::Square(double(Config.VisibilityCacheMoveCm));

	TArray<uint8> Visible;
	Visible.Init(0, Num);
	int32 Budget = Config.MaxCellSightTestsPerStep;
	int32 StoppedAt = INDEX_NONE;
	for (int32 Step = 0; Step < Num; ++Step)
	{
		const int32 Cell = (ClearCursor + Step) % Num;
		if (!Grid.IsActive(Cell))
		{
			continue;
		}
		const FVector Mid = Grid.GetCellCentre(Cell) + FVector(0.0, 0.0, 130.0);
		if (FVector::DistSquared(Eye, Mid) > RangeSq || !InViewCone(Eye, Forward, Pitch, Mid))
		{
			continue;
		}
		const bool bCacheValid =
			FVector::DistSquared(CachedEye[Cell], Eye) <= MoveSq && NowS - CachedAtS[Cell] <= CacheMaxAgeS;
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
			CachedVisible[Cell] = TestCellVisible(Cell, Eye, Self.ViewRotation, *World.Sight) ? 1 : 0;
			CachedEye[Cell] = Eye;
			CachedAtS[Cell] = NowS;
		}
		Visible[Cell] = CachedVisible[Cell];
	}
	if (StoppedAt != INDEX_NONE)
	{
		ClearCursor = StoppedAt;
	}
	Grid.Clear(Eye, [&Visible](int32 Cell) { return Visible[Cell] != 0; }, NowS);
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

	// bot.md 4.2 order: predict, clear, sighting, heard, hurt / bolt, kill feed, normalise.
	Grid.Predict(DeltaS, NowS);
	RunClear(Frame.Self, World, NowS);

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

	if (World.Pieces && World.Sight && Frame.Self.Phase != EVerseCombatPhase::Dead)
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

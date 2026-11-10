#pragma once

#include "Bot/VersePerceptTypes.h"
#include "Brain/VerseBotTypes.h"
#include "CoreMinimal.h"
#include "Templates/Function.h"
#include "Destruction/VerseDestructionTypes.h"

// The belief grid (contracts/bot.md 4.1-4.3): where the opponent probably is, from percepts only.
// 1 x 1 m columns over the arena, one cell per walkable nav level in that column, 8-neighbour
// adjacency on a level plus authored links (stairs, ladders, mantles, jumps, drops). Mass P sums
// to 1 while the opponent is alive. Pure data and arithmetic: no UWorld, no pawn, no RNG, so a
// replay of the same percepts gives bit-identical mass (bot.md B5).

/** Kind of the newest positive percept that touched a cell (bot.md 4.1 LastSupport). */
enum class EVerseBeliefSupport : uint8
{
	None,
	Seen,
	Heard,
	Inferred
};

// EVerseBeliefState (bot.md 4.3 states plus Dead) is the brain's enum, so the grid and the brain
// read one type.

/** When a cell or link exists, by the believed state of the piece that gates it (destruction.md 6.1). */
enum class EVerseBeliefGate : uint8
{
	/** Always there. */
	Always,
	/** Only while the piece is believed Breached or Destroyed (a breach opening). */
	WhenOpen,
	/** Only while the piece is not believed Destroyed (a catwalk segment). */
	WhenStanding
};

enum class EVerseBeliefLinkKind : uint8
{
	Stair,
	Ladder,
	Mantle,
	Jump,
	Drop,
	Breach
};

/** A cell as a source (nav sampler, fixture) describes it. */
struct VERSEBOT_API FVerseBeliefCellDesc
{
	/** Column index on the grid (X, Y), cell size apart. */
	FIntPoint Column = FIntPoint::ZeroValue;
	/** Floor height of the cell, world cm. */
	float FloorZ = 0.f;
	EVerseArenaLevel Level = EVerseArenaLevel::Floor;
	/** Arena VisibilityFactor at the cell (1 lit). */
	float Visibility = 1.f;
	/** Prone is possible here (clear also tests 0.4 m). */
	bool bProneCapable = false;
	/** Learning zone id (bot.md 7.1 routes), 0..254; 255 = none. */
	uint8 Zone = 255;
	EVerseBeliefGate Gate = EVerseBeliefGate::Always;
	int32 GatePiece = INDEX_NONE;
};

/** A link between two cells (indices into the source's cell list). */
struct VERSEBOT_API FVerseBeliefLinkDesc
{
	int32 From = INDEX_NONE;
	int32 To = INDEX_NONE;
	/** Seconds to traverse at a run. */
	float TraversalS = 1.f;
	bool bBidirectional = true;
	EVerseBeliefLinkKind Kind = EVerseBeliefLinkKind::Stair;
	EVerseBeliefGate Gate = EVerseBeliefGate::Always;
	int32 GatePiece = INDEX_NONE;
};

/** Everything a grid is built from. */
struct VERSEBOT_API FVerseBeliefGridSource
{
	/** World position of column (0, 0)'s centre, cm. */
	FVector2D Origin = FVector2D::ZeroVector;
	float CellSizeCm = 100.f;
	TArray<FVerseBeliefCellDesc> Cells;
	TArray<FVerseBeliefLinkDesc> Links;
	/**
	 * Optional: may an 8-neighbour step go from cell A to cell B (a wall between them says no)?
	 * Called once per neighbour pair at build. Null = every same-level neighbour is connected.
	 */
	TFunction<bool(int32 A, int32 B)> AreNeighboursConnected;
};

/** bot.md 4.3 TopCluster. */
struct VERSEBOT_API FVerseBeliefCluster
{
	/** Mass-weighted centre of the disc, world cm (floor height). */
	FVector Centre = FVector::ZeroVector;
	EVerseArenaLevel Level = EVerseArenaLevel::Floor;
	float Mass = 0.f;
	/** The cell the disc is centred on. */
	int32 CentreCell = INDEX_NONE;
};

/** The read API of the decision layer (bot.md 4.3). */
struct VERSEBOT_API FVerseBeliefDerived
{
	FVerseBeliefCluster TopCluster;
	/** Mass of TopCluster, 0-1. */
	float Confidence = 0.f;
	/** Seconds since the newest seen or heard support inside TopCluster; large when none. */
	float SupportAgeS = TNumericLimits<float>::Max();
	EVerseBeliefSupport SupportKind = EVerseBeliefSupport::None;
	/** Weighted sd of the top 90 % of mass, metres. */
	float SpreadM = 0.f;
	EVerseBeliefState State = EVerseBeliefState::Lost;
};

/** Tuning of the update rules (bot.md 4.2; thresholds may be retuned, rules may not). */
struct VERSEBOT_API FVerseBeliefTuning
{
	/** Typical opponent speed, cm/s. */
	float TypicalSpeedCmS = 450.f;
	/** Most of a cell's mass that may diffuse in one step. */
	float MaxDiffusionFraction = 0.5f;
	/**
	 * Momentum: after a sighting, part of the flow follows the seen velocity (a running person
	 * keeps running). Neighbour weight cos^Exponent; the advected speed decays with this time.
	 * Not a bot.md 4.2 rule yet: proposed to the integration owner as a contract change (A7.4 needs
	 * it). MomentumMaxFraction = 0 gives the contract rules exactly.
	 */
	float MomentumExponent = 4.f;
	float MomentumDecayS = 60.f;
	/** Momentum stops this long after the sighting that set it. */
	float MomentumMaxAgeS = 6.f;
	float MomentumMaxFraction = 0.45f;
	/** Clear: detection probability at up to NearM, falling linearly to FarPd at FarM. */
	float ClearNearPd = 0.95f;
	float ClearNearM = 30.f;
	float ClearFarPd = 0.7f;
	float ClearFarM = 50.f;
	/** Sighting Gaussian sd, cm. */
	float SightingSdCm = 50.f;
	/** Heard likelihood floor and level weights. */
	float HeardEps = 0.02f;
	float HeardLevelWeight = 0.9f;
	/** Hurt / bolt wedge half-angle, degrees, and its likelihood floor. */
	float WedgeHalfAngleDeg = 8.f;
	float WedgeEps = 0.02f;
	/** Spawn prior: top 3 spawn points weighted, sd cm. */
	float SpawnWeights[3] = {0.5f, 0.3f, 0.2f};
	float SpawnSdCm = 150.f;
	/** Normalise: share of the learned heatmap prior mixed in. */
	float PriorMix = 0.01f;
	/** Zone-transition bias gain (bot.md 7.2: x (1 + 0.5 x p)). */
	float ZoneBiasGain = 0.5f;
	/** TopCluster disc radius, cm. */
	float ClusterRadiusCm = 300.f;
	/** Unused: every active cell is a disc centre candidate; kept for tuning files. */
	int32 ClusterCandidates = 128;
	/** States: Tracked at or above, Rough at or above, else Lost. */
	float TrackedConfidence = 0.5f;
	float RoughConfidence = 0.2f;
};

/**
 * The grid. Build once from a source; ApplyGates when the piece belief changes; then the update
 * steps of bot.md 4.2 in order: Predict, Clear, Sighting / Heard / Wedge / KillFeed, Normalise.
 */
class VERSEBOT_API FVerseBeliefGrid
{
public:
	FVerseBeliefGrid() = default;

	void Build(const FVerseBeliefGridSource& Source, const FVerseBeliefTuning& InTuning = FVerseBeliefTuning());

	int32 NumCells() const { return Cells.Num(); }
	bool IsActive(int32 Cell) const { return bCellActive.IsValidIndex(Cell) && bCellActive[Cell] != 0; }
	const FVerseBeliefCellDesc& GetCell(int32 Cell) const { return Cells[Cell]; }
	FVector GetCellCentre(int32 Cell) const { return Centres[Cell]; }
	float GetMass(int32 Cell) const { return P[Cell]; }
	TConstArrayView<float> GetMassArray() const { return P; }
	float GetLastClearedS(int32 Cell) const { return LastClearedS[Cell]; }
	float GetLastSupportS(int32 Cell) const { return LastSupportS[Cell]; }
	EVerseBeliefSupport GetLastSupportKind(int32 Cell) const { return LastSupportKind[Cell]; }
	const FVerseBeliefTuning& GetTuning() const { return Tuning; }
	float GetCellSizeCm() const { return CellSizeCm; }

	/** Active cell nearest to a world point (same level preferred by height); INDEX_NONE if none. */
	int32 FindCell(const FVector& WorldLocation) const;
	/** Active cell of a column and level, or INDEX_NONE. */
	int32 FindCell(const FIntPoint& Column, EVerseArenaLevel Level) const;
	/** Cell of a column and level whether active or not (gated cells), or INDEX_NONE. */
	int32 FindCellAnyState(const FIntPoint& Column, EVerseArenaLevel Level) const;
	FIntPoint ColumnOf(const FVector& WorldLocation) const;

	/** Number of active neighbours (adjacency and links) of a cell. */
	int32 NumNeighbours(int32 Cell) const;
	/** Every active neighbour of a cell (for tests and plans). */
	void GetNeighbours(int32 Cell, TArray<int32>& Out) const;

	/**
	 * Re-evaluate gated cells and links. IsOpen(piece): believed Breached or Destroyed;
	 * IsStanding(piece): not believed Destroyed. Returns true when anything changed. Mass on a cell
	 * that went inactive is dropped and the grid renormalised.
	 */
	bool ApplyGates(TFunctionRef<bool(int32 Piece)> IsOpen, TFunctionRef<bool(int32 Piece)> IsStanding);

	/** Uniform mass over active cells (no information). */
	void ResetUniform();

	/** Learned position heatmap prior per cell (bot.md 7.2), any scale; empty = uniform. */
	void SetPositionPrior(TConstArrayView<float> PerCell);
	/** Zone-transition probabilities, Zones x Zones row-major (From * Zones + To); empty = none. */
	void SetZoneTransitionPrior(int32 Zones, TConstArrayView<float> Matrix);
	/** Last seen velocity of the opponent (cm/s) and its server time, for the momentum term. */
	void SetMomentum(const FVector& Velocity, float AtS);
	void ClearMomentum();

	// ---- update steps, bot.md 4.2 order ----

	/** Diffuse mass to reachable neighbours over DeltaS. */
	void Predict(float DeltaS, float NowS);
	/**
	 * Multiply visible empty cells by 1 - Pd. IsVisible(cell) answers whether the cell is in the view
	 * cone with line of sight at 1.0 m and 1.6 m (0.4 m when prone-capable); Eye for the range term.
	 */
	void Clear(const FVector& Eye, TFunctionRef<bool(int32 Cell)> IsVisible, float NowS);
	/** The same for a list of cells already known visible (the map's cached visibility). */
	void Clear(const FVector& Eye, TConstArrayView<int32> VisibleCells, float NowS);
	/** Replace the grid by a Gaussian at the sighted pelvis (level known). */
	void ApplySighting(const FVector& PelvisLocation, float NowS);
	/** Multiply by eps + level weight x exp(-d^2 / 2 sd^2). */
	void ApplyHeard(const FVerseHeardPercept& Heard, float NowS);
	/**
	 * Multiply by a wedge along a line traced back from Point toward the shooter (BackDirection),
	 * up to MaxDistCm (the first opaque piece in the piece belief).
	 */
	void ApplyWedge(const FVector& Point, const FVector& BackDirection, float MaxDistCm, float NowS);
	/** Opponent dead: no mass anywhere until a respawn. */
	void ApplyOpponentDead();
	/** Opponent respawned: prior over the 3 best spawn points (already ranked by the caller). */
	void ApplySpawnPrior(TConstArrayView<FVector> RankedSpawnPoints, float NowS);
	/** Renormalise to 1 and mix in the prior, so no active cell is ever exactly 0. */
	void Normalise();

	bool IsOpponentDead() const { return bOpponentDead; }

	/** bot.md 4.3 derived values. bKnown: a sighting in this step. */
	FVerseBeliefDerived ComputeDerived(float NowS, bool bKnown) const;

	/** Sum of active mass (tests: 1 within 1e-6 after Normalise). */
	double TotalMass() const;

	/**
	 * Cells reachable from From to To over active adjacency and links, breadth first; empty if
	 * none. A believed path: it never uses a link the piece belief has not opened.
	 */
	TArray<int32> FindPath(int32 From, int32 To) const;

	/** Bit pattern hash of the mass (replay and counterfactual tests). */
	uint32 HashMass() const;

private:
	struct FNeighbour
	{
		int32 Cell = INDEX_NONE;
		/** dt-independent rate: 1 / traversal seconds. */
		float Rate = 0.f;
		/** Horizontal unit direction (momentum). */
		FVector2f Dir = FVector2f::ZeroVector;
		/** Gating of this edge (links); Always for plain adjacency. */
		EVerseBeliefGate Gate = EVerseBeliefGate::Always;
		int32 GatePiece = INDEX_NONE;
		bool bActive = true;
		/** Learned zone-transition multiplier. */
		float Bias = 1.f;
		/** Index into the 8 adjacency directions, 255 for a link. */
		uint8 DirIndex = 255;
	};

	void RecomputeRateSums();
	/** Momentum weights that depend only on the direction (cached until it or the edges change). */
	void RefreshMomentumWeights(const FVector2f& Dir);
	float ClearPd(int32 Cell, const FVector& Eye) const;

	int32 Level3(const FIntPoint& Column, EVerseArenaLevel Level) const;

	FVerseBeliefTuning Tuning;
	FVector2D Origin = FVector2D::ZeroVector;
	float CellSizeCm = 100.f;
	FIntPoint MinColumn = FIntPoint::ZeroValue;
	FIntPoint ColumnSpan = FIntPoint::ZeroValue;

	TArray<FVerseBeliefCellDesc> Cells;
	TArray<FVector> Centres;
	TArray<uint8> bCellActive;
	/** Per cell: sum of Rate x Bias over its active edges. */
	TArray<float> RateSum;
	/**
	 * Derived values: a padded per-level layout (Reach zero columns and rows around each level) so
	 * the disc sum of every cell is a few contiguous box-sum passes. DiscPadMask is 1 on active cells.
	 */
	int32 DiscPadWidth = 0;
	int32 DiscPadSize = 0;
	TArray<int32> CellDiscPad;
	TArray<int32> DiscPadCell;
	TArray<float> DiscPadMask;
	mutable TArray<float> DiscPadMass;
	/** Horizontal box sums of half-width h, h = 1 .. Reach (h = 0 is the mass itself). */
	mutable TArray<float> DiscPadRows[8];
	mutable TArray<float> DiscPadSum;
	/** Per cell, 4 floats: centre X, Y, Z in metres from the grid middle, and their squared length (moment sums). */
	TArray<float> CellMoment;
	FVector MomentOrigin = FVector::ZeroVector;
	/** Per cell: 1 when active, else 0 (branch-free passes), and the active count. */
	TArray<float> ActiveMaskF;
	int32 ActiveCount = 0;
	/** Dense padded per-level layout for the predict stencil, rebuilt when gates or biases change. */
	int32 DenseSize = 0;
	TArray<int32> CellDense;
	int32 DirOffset[8] = {0, 0, 0, 0, 0, 0, 0, 0};
	TArray<float> DenseRateBias[8];
	TArray<float> DenseRate[8];
	TArray<float> DenseOut;
	TArray<float> DenseDiffuse;
	TArray<float> DenseAdvect;
	/** Momentum, per direction: Cos x Rate / (sum of Cos x Rate of the cell); empty when Cos <= 0. */
	TArray<float> DenseAdvectWeight[8];
	TArray<uint8> DenseHasAdvect;
	float MomentumCos[8] = {0.f, 0.f, 0.f, 0.f, 0.f, 0.f, 0.f, 0.f};
	FVector2f MomentumWeightsDir = FVector2f::ZeroVector;
	bool bMomentumWeightsValid = false;
	/** Active link edges. */
	TArray<int32> LinkFrom;
	TArray<int32> LinkTo;
	TArray<float> LinkRateBias;
	TArray<float> LinkRate;
	TArray<FVector2f> LinkDirs;
	/** Per link: Cos x Rate / (the from cell's momentum weight sum). */
	TArray<float> LinkAdvectWeight;
	/** Disc row half-widths in columns, index dy + reach. */
	TArray<int32> DiscHalfWidth;
	/** Neighbours of cell i are Neighbours[NeighbourStart[i] .. NeighbourStart[i + 1]). */
	TArray<int32> NeighbourStart;
	TArray<FNeighbour> Neighbours;
	/** Column x level -> cell index or INDEX_NONE. */
	TArray<int32> ColumnLookup;

	TArray<float> P;
	TArray<float> Scratch;
	TArray<float> Prior;
	TArray<float> LastClearedS;
	TArray<float> LastSupportS;
	TArray<EVerseBeliefSupport> LastSupportKind;

	FVector2f MomentumVelocity = FVector2f::ZeroVector;
	float MomentumAtS = 0.f;
	bool bMomentum = false;
	bool bOpponentDead = false;

	/** Disc offsets (column deltas) within ClusterRadius. */
	TArray<FIntPoint> DiscOffsets;
};

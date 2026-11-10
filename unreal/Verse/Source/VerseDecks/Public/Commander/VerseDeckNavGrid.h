#pragma once

#include "CoreMinimal.h"

struct FVerseDeckManifest;

/**
 * Where the commander can walk on a deck (stream S5), a port of today's cooked nav grid
 * (`nav/pathfind.ts`): square cells over the deck's room polygons, each either walkable with
 * its floor height or blocked. A* over 8 neighbours that never cuts a blocked corner nor climbs
 * more than `MaxStepCm`, then string pulling, so a path is a few straight legs between corners.
 *
 * The grid is probed from the level's own collision (`FFloorProbe`, a capsule sweep in the
 * game), so it follows whatever the deck's art places; a cell is walkable when a standing body
 * fits there. Probing is sliced (`ProbeRows`) so a big deck spreads it over a few frames.
 */
class VERSEDECKS_API FVerseDeckNavGrid
{
public:
	/** Floor height under a plan point, cm, or unset when a body cannot stand there; `RoomZCm` is the room's floor. */
	using FFloorProbe = TFunctionRef<TOptional<double>(const FVector2D& PlanCm, double RoomZCm)>;

	/** 20 cm cells, as today's 0.2 m grid. */
	static constexpr double DefaultCellCm = 20.0;
	/** Largest height step between neighbouring cells a walk takes (stairs and ramps). */
	static constexpr double DefaultMaxStepCm = 30.0;

	/** Sizes the grid over a box on the plan; every cell starts blocked and unprobed. */
	void Init(const FBox2D& BoundsCm, double CellCm = DefaultCellCm);
	/** Sizes the grid over the manifest's rooms and marks the cells inside a room for probing. */
	void InitFromManifest(const FVerseDeckManifest& Manifest, double CellCm = DefaultCellCm);
	/** Probes `NumRows` rows from the next unprobed one; returns the rows left. */
	int32 ProbeRows(int32 NumRows, FFloorProbe Probe);
	bool IsComplete() const { return NextRow >= Rows; }

	/** Tests and tools: set one cell directly. */
	void SetCell(int32 Index, bool bWalkable, double HeightCm = 0.0);

	int32 CellIndex(const FVector2D& PlanCm) const;
	FVector2D CellCentre(int32 Index) const;
	bool IsWalkable(const FVector2D& PlanCm) const;
	/** Floor height at a walkable plan point, cm; unset off the floor. */
	TOptional<double> FloorHeight(const FVector2D& PlanCm) const;
	/** The walkable cell nearest to `PlanCm` within `MaxCm`, by rings; INDEX_NONE when none. */
	int32 NearestWalkableCell(const FVector2D& PlanCm, double MaxCm) const;
	/** The point itself when walkable, else the centre of the nearest walkable cell within `MaxCm` (with its floor height). */
	TOptional<FVector> NearestWalkable(const FVector2D& PlanCm, double MaxCm) const;
	/** True when a body can walk straight from A to B (every cell crossed is walkable, corners included). */
	bool LineOfWalk(const FVector2D& A, const FVector2D& B) const;
	/**
	 * A walkable route from `From` to `To`: the start, the corners, the goal, each at its floor
	 * height. A goal off the floor moves to the nearest walkable cell. False when there is no way.
	 */
	bool FindPath(const FVector& From, const FVector& To, TArray<FVector>& OutPoints) const;

	int32 NumCols() const { return Cols; }
	int32 NumRows() const { return Rows; }
	int32 NumWalkable() const;
	double GetCellCm() const { return Cell; }

	double MaxStepCm = DefaultMaxStepCm;

private:
	bool IsOpen(int32 Col, int32 Row) const;
	bool AStar(int32 Start, int32 Goal, TArray<int32>& OutCells) const;
	void StringPull(TArray<FVector2D>& Points) const;

	double Cell = DefaultCellCm;
	FVector2D Origin = FVector2D::ZeroVector;
	int32 Cols = 0;
	int32 Rows = 0;
	int32 NextRow = 0;
	TArray<uint8> Walkable;
	TArray<float> Heights;
	/** Floor height of the room a cell lies in, or NaN outside every room (not probed). */
	TArray<float> RoomZ;
};

#pragma once

#include "CoreMinimal.h"
#include "Destruction/VersePenetrationTable.h"
#include "UObject/SoftObjectPath.h"

// Importer from unreal/Verse/Data/destruction/penetration.json (schema verse.penetration/1,
// propose-only: it changes only through the destruction contract's change rule) into the rows
// of DA_PenetrationTable. The wire order is frozen: row i must carry wire i and the i-th id of
// destruction.md 2; new materials only append.

namespace VersePenetrationImport
{
	inline const TCHAR* const Schema = TEXT("verse.penetration/1");

	/** <ProjectDir>/Data/destruction/penetration.json */
	VERSEDESTRUCTION_API FString DefaultTablePath();

	/** DA_PenetrationTable, the cooked table the game loads (written from the JSON by the WP03.2 import step). */
	VERSEDESTRUCTION_API FSoftObjectPath TableAssetPath();

	/**
	 * The table the game uses: the DA_PenetrationTable asset, which cooks and ships with every
	 * build, dedicated servers included. Editor builds warn when the asset and the JSON disagree
	 * (the import step was not re-run after a retune). Without the asset: the JSON when it is on
	 * disk, else the contract table, and both fallbacks log.
	 */
	VERSEDESTRUCTION_API UVersePenetrationTable* LoadRuntimeTable(UObject* Outer);

	/** Parses the JSON text. Returns false and fills OutErrors on any schema, value or wire order error. */
	VERSEDESTRUCTION_API bool ParseTableJson(const FString& JsonText, TArray<FVersePenetrationRow>& OutRows, TArray<FString>& OutErrors);

	/** The frozen wire order check alone: ids and wire numbers of the first 8 rows, nothing removed. */
	VERSEDESTRUCTION_API bool CheckWireOrder(TConstArrayView<FVersePenetrationRow> Rows, TArray<FString>& OutErrors);

	/** Reads and parses the file and replaces Table.Rows. Leaves the table untouched on failure. */
	VERSEDESTRUCTION_API bool ImportIntoTable(UVersePenetrationTable& Table, const FString& Path, TArray<FString>& OutErrors);

	/** Human-readable differences between two row sets (empty = equal within Tolerance). */
	VERSEDESTRUCTION_API TArray<FString> DiffRows(TConstArrayView<FVersePenetrationRow> A, TConstArrayView<FVersePenetrationRow> B,
		float Tolerance = 1e-6f);
}

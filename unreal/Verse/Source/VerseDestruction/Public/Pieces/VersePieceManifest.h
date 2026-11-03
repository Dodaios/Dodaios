#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VersePieceManifest.generated.h"

class UWorld;

/**
 * DA_PieceManifest (destruction.md 8): the One File Per Actor GUIDs of every AVerseDestructible
 * of one arena, sorted by GUID at cook time. PieceIndex = position in this list, the same on
 * server and clients; the hash is checked in the server welcome.
 */
UCLASS(BlueprintType)
class VERSEDESTRUCTION_API UVersePieceManifest : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	static constexpr int32 MaxPieces = 2000;

	/** Sorted ascending (FGuid order). */
	UPROPERTY(VisibleAnywhere, Category = "Manifest")
	TArray<FGuid> PieceGuids;

	/** ComputeHash(PieceGuids). */
	UPROPERTY(VisibleAnywhere, Category = "Manifest")
	uint32 Hash = 0;

	/** Sorts, de-duplicates and hashes. False if over MaxPieces or a GUID is invalid. */
	bool Build(TArray<FGuid> Guids, FString* OutError = nullptr);

	/** INDEX_NONE when the GUID is not in the manifest. */
	int32 IndexOf(const FGuid& Guid) const;

	/** True if PieceGuids is sorted, unique and Hash matches. */
	bool IsConsistent() const;

	static uint32 ComputeHash(TConstArrayView<FGuid> Guids);

	/** The GUID order rule, shared with the manager when no manifest asset is assigned. */
	static void SortGuids(TArray<FGuid>& Guids);

#if WITH_EDITOR
	/** Collects every AVerseDestructible of a world (editor and cook). */
	static TArray<FGuid> CollectFromWorld(const UWorld& World);
#endif
};

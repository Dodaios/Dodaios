#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"

#include "VersePenetrationTableLibrary.generated.h"

class AActor;
class UStaticMesh;
class UVersePenetrationTable;
class UWorld;

/**
 * The WP03.2 import step, callable from editor Python (Content/Verse/Test/WP03/Python/wp03_content.py):
 * Data/destruction/penetration.json into the rows of the DA_PenetrationTable asset, with the
 * frozen wire order check. The game loads the asset (VersePenetrationImport::LoadRuntimeTable).
 */
UCLASS()
class VERSEDESTRUCTION_API UVersePenetrationTableLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** Reads Path (empty = Data/destruction/penetration.json) into Table. False leaves Table untouched; OutErrors says why. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Penetration")
	static bool ImportPenetrationJson(UVersePenetrationTable* Table, const FString& Path, FString& OutErrors);

	/** Differences between Table and the JSON at Path (empty = the default), one per line; empty when they agree. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Penetration")
	static FString DiffPenetrationJson(const UVersePenetrationTable* Table, const FString& Path);

	/**
	 * WP03.8 fixture map step: a static mesh actor in World with Mesh, Transform, the collision
	 * Profile and Tags. Spawned directly in the world, so it works in the headless commandlet
	 * (the editor actor subsystem places through a level viewport).
	 */
	UFUNCTION(BlueprintCallable, Category = "Verse|Penetration")
	static AActor* SpawnFixturePiece(UWorld* World, UStaticMesh* Mesh, const FTransform& Transform, FName Profile, const TArray<FName>& Tags,
		const FString& Label);
};

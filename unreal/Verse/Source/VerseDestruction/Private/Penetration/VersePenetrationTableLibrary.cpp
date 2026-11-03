#include "Penetration/VersePenetrationTableLibrary.h"

#include "Components/StaticMeshComponent.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/World.h"
#include "Misc/FileHelper.h"
#include "Penetration/VersePenetrationTableImport.h"

bool UVersePenetrationTableLibrary::ImportPenetrationJson(UVersePenetrationTable* Table, const FString& Path, FString& OutErrors)
{
	OutErrors.Reset();
	if (!Table)
	{
		OutErrors = TEXT("no table");
		return false;
	}
	TArray<FString> Errors;
	const FString Source = Path.IsEmpty() ? VersePenetrationImport::DefaultTablePath() : Path;
	if (!VersePenetrationImport::ImportIntoTable(*Table, Source, Errors))
	{
		OutErrors = FString::Join(Errors, TEXT("\n"));
		return false;
	}
	Table->MarkPackageDirty();
	return true;
}

FString UVersePenetrationTableLibrary::DiffPenetrationJson(const UVersePenetrationTable* Table, const FString& Path)
{
	if (!Table)
	{
		return TEXT("no table");
	}
	const FString Source = Path.IsEmpty() ? VersePenetrationImport::DefaultTablePath() : Path;
	FString Text;
	if (!FFileHelper::LoadFileToString(Text, *Source))
	{
		return FString::Printf(TEXT("cannot read %s"), *Source);
	}
	TArray<FVersePenetrationRow> Rows;
	TArray<FString> Errors;
	if (!VersePenetrationImport::ParseTableJson(Text, Rows, Errors))
	{
		return FString::Join(Errors, TEXT("\n"));
	}
	return FString::Join(VersePenetrationImport::DiffRows(Table->Rows, Rows), TEXT("\n"));
}

AActor* UVersePenetrationTableLibrary::SpawnFixturePiece(UWorld* World, UStaticMesh* Mesh, UMaterialInterface* Material, const FTransform& Transform,
	FName Profile,
	const TArray<FName>& Tags, const FString& Label)
{
	if (!World || !Mesh)
	{
		return nullptr;
	}
	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AStaticMeshActor* Actor = World->SpawnActor<AStaticMeshActor>(AStaticMeshActor::StaticClass(), Transform, Params);
	if (!Actor)
	{
		return nullptr;
	}
	UStaticMeshComponent* Component = Actor->GetStaticMeshComponent();
	Component->SetStaticMesh(Mesh);
	for (int32 Slot = 0; Material && Slot < Component->GetNumMaterials(); ++Slot)
	{
		Component->SetMaterial(Slot, Material);
	}
	Component->SetCollisionProfileName(Profile);
	Actor->SetActorTransform(Transform);
	Actor->Tags = Tags;
#if WITH_EDITOR
	if (!Label.IsEmpty())
	{
		Actor->SetActorLabel(Label);
	}
#endif
	return Actor;
}

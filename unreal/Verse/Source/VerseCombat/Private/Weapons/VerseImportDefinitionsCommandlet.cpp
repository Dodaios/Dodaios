#include "Weapons/VerseImportDefinitionsCommandlet.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "VerseLog.h"
#include "Weapons/VerseDefinitionJson.h"
#include "Weapons/VerseWeaponRegistry.h"

UVerseImportDefinitionsCommandlet::UVerseImportDefinitionsCommandlet()
{
	IsClient = false;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
}

namespace
{
	template <typename T>
	bool SaveDefinition(const FString& AssetName, TFunctionRef<bool(T&, TArray<FString>&)> Fill, TArray<FString>& Errors)
	{
#if WITH_EDITOR
		const FString PackageName = FString::Printf(TEXT("%s/%s"), FVerseDefinitionJson::AssetFolder, *AssetName);
		UPackage* Package = CreatePackage(*PackageName);
		Package->FullyLoad();
		T* Asset = FindObject<T>(Package, *AssetName);
		if (!Asset)
		{
			Asset = NewObject<T>(Package, *AssetName, RF_Public | RF_Standalone | RF_Transactional);
		}
		if (!Fill(*Asset, Errors))
		{
			return false;
		}
		Package->MarkPackageDirty();
		const FString File = FPackageName::LongPackageNameToFilename(PackageName, FPackageName::GetAssetPackageExtension());
		FSavePackageArgs Args;
		Args.TopLevelFlags = RF_Public | RF_Standalone;
		Args.SaveFlags = SAVE_NoError;
		if (!UPackage::SavePackage(Package, Asset, *File, Args))
		{
			Errors.Add(FString::Printf(TEXT("%s: save failed"), *File));
			return false;
		}
		UE_LOG(LogVerseCombat, Display, TEXT("saved %s"), *File);
		return true;
#else
		Errors.Add(TEXT("the importer needs an editor build"));
		return false;
#endif
	}
}

int32 UVerseImportDefinitionsCommandlet::Main(const FString& Params)
{
	const bool bCheckOnly = Params.Contains(TEXT("-check"));
	TArray<FString> Errors;
	TArray<FString> Diffs;

	const TArray<UVerseWeaponDefinition*> Weapons = FVerseDefinitionJson::LoadAllWeapons(GetTransientPackage(), Errors);
	for (const UVerseWeaponDefinition* W : Weapons)
	{
		const TSharedRef<FJsonObject> Want = FVerseDefinitionJson::ExportWeapon(*W);
		const FString AssetName = FVerseDefinitionJson::WeaponAssetName(W->WeaponId);
		if (bCheckOnly)
		{
			const UVerseWeaponDefinition* Asset = FVerseWeaponRegistry::LoadWeaponAsset(W->WeaponId);
			if (!Asset)
			{
				Diffs.Add(AssetName + TEXT(": missing"));
				continue;
			}
			FVerseDefinitionJson::JsonEqual(MakeShared<FJsonValueObject>(Want),
				MakeShared<FJsonValueObject>(FVerseDefinitionJson::ExportWeapon(*Asset)), AssetName, Diffs);
			continue;
		}
		SaveDefinition<UVerseWeaponDefinition>(AssetName, [&Want](UVerseWeaponDefinition& Asset, TArray<FString>& E)
		{
			return FVerseDefinitionJson::ApplyWeapon(*Want, Asset, E);
		}, Errors);
	}

	FString GadgetText;
	TArray<UVerseGadgetDefinition*> Gadgets;
	if (!FFileHelper::LoadFileToString(GadgetText, *FPaths::Combine(FVerseDefinitionJson::DataDir(), TEXT("gadgets.json"))))
	{
		Errors.Add(TEXT("gadgets.json: cannot read"));
	}
	else
	{
		FVerseDefinitionJson::LoadGadgetsText(GadgetText, GetTransientPackage(), Gadgets, Errors);
	}
	for (const UVerseGadgetDefinition* G : Gadgets)
	{
		const TSharedRef<FJsonObject> Want = FVerseDefinitionJson::ExportGadget(*G);
		const FString AssetName = FVerseDefinitionJson::GadgetAssetName(G->GadgetId);
		if (bCheckOnly)
		{
			const UVerseGadgetDefinition* Asset = FVerseWeaponRegistry::LoadGadgetAsset(G->GadgetId);
			if (!Asset)
			{
				Diffs.Add(AssetName + TEXT(": missing"));
				continue;
			}
			FVerseDefinitionJson::JsonEqual(MakeShared<FJsonValueObject>(Want),
				MakeShared<FJsonValueObject>(FVerseDefinitionJson::ExportGadget(*Asset)), AssetName, Diffs);
			continue;
		}
		SaveDefinition<UVerseGadgetDefinition>(AssetName, [&Want](UVerseGadgetDefinition& Asset, TArray<FString>& E)
		{
			return FVerseDefinitionJson::ApplyGadget(*Want, Asset, E);
		}, Errors);
	}

	for (const FString& E : Errors)
	{
		UE_LOG(LogVerseCombat, Error, TEXT("import: %s"), *E);
	}
	for (const FString& D : Diffs)
	{
		UE_LOG(LogVerseCombat, Error, TEXT("drift: %s"), *D);
	}
	UE_LOG(LogVerseCombat, Display, TEXT("VerseImportDefinitions: %d weapons, %d gadgets, %d errors, %d diffs"), Weapons.Num(),
		Gadgets.Num(), Errors.Num(), Diffs.Num());
	return (Errors.Num() == 0 && Diffs.Num() == 0) ? 0 : 1;
}

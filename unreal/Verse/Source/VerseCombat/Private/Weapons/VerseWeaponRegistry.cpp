#include "Weapons/VerseWeaponRegistry.h"

#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Weapons/VerseDefinitionJson.h"

namespace
{
	TMap<FName, UVerseWeaponDefinition*>& WeaponCache()
	{
		static TMap<FName, UVerseWeaponDefinition*> Cache;
		return Cache;
	}

	TMap<FName, UVerseGadgetDefinition*>& GadgetCache()
	{
		static TMap<FName, UVerseGadgetDefinition*> Cache;
		return Cache;
	}

	FString ObjectPath(const FString& AssetName)
	{
		return FString::Printf(TEXT("%s/%s.%s"), FVerseDefinitionJson::AssetFolder, *AssetName, *AssetName);
	}
}

const UVerseWeaponDefinition* FVerseWeaponRegistry::LoadWeaponAsset(FName WeaponId)
{
	const FString Name = FVerseDefinitionJson::WeaponAssetName(WeaponId);
	return LoadObject<UVerseWeaponDefinition>(nullptr, *ObjectPath(Name), nullptr, LOAD_NoWarn | LOAD_Quiet);
}

const UVerseGadgetDefinition* FVerseWeaponRegistry::LoadGadgetAsset(FName GadgetId)
{
	const FString Name = FVerseDefinitionJson::GadgetAssetName(GadgetId);
	return LoadObject<UVerseGadgetDefinition>(nullptr, *ObjectPath(Name), nullptr, LOAD_NoWarn | LOAD_Quiet);
}

const UVerseWeaponDefinition* FVerseWeaponRegistry::FindWeapon(FName WeaponId)
{
	if (const UVerseWeaponDefinition* Asset = LoadWeaponAsset(WeaponId))
	{
		return Asset;
	}
	if (UVerseWeaponDefinition* const* Cached = WeaponCache().Find(WeaponId))
	{
		return *Cached;
	}
	FString Text;
	const FString File = FPaths::Combine(FVerseDefinitionJson::DataDir(), WeaponId.ToString() + TEXT(".json"));
	if (!FFileHelper::LoadFileToString(Text, *File))
	{
		return nullptr;
	}
	UVerseWeaponDefinition* Def = NewObject<UVerseWeaponDefinition>(GetTransientPackage());
	TArray<FString> Errors;
	if (!FVerseDefinitionJson::ApplyWeaponText(Text, *Def, Errors))
	{
		return nullptr;
	}
	Def->AddToRoot(); // process lifetime; never released
	WeaponCache().Add(WeaponId, Def);
	return Def;
}

const UVerseGadgetDefinition* FVerseWeaponRegistry::FindGadget(FName GadgetId)
{
	if (const UVerseGadgetDefinition* Asset = LoadGadgetAsset(GadgetId))
	{
		return Asset;
	}
	if (GadgetCache().Num() == 0)
	{
		FString Text;
		if (FFileHelper::LoadFileToString(Text, *FPaths::Combine(FVerseDefinitionJson::DataDir(), TEXT("gadgets.json"))))
		{
			TArray<UVerseGadgetDefinition*> Defs;
			TArray<FString> Errors;
			FVerseDefinitionJson::LoadGadgetsText(Text, GetTransientPackage(), Defs, Errors);
			for (UVerseGadgetDefinition* D : Defs)
			{
				D->AddToRoot();
				GadgetCache().Add(D->GadgetId, D);
			}
		}
	}
	UVerseGadgetDefinition* const* Found = GadgetCache().Find(GadgetId);
	return Found ? *Found : nullptr;
}

void FVerseWeaponRegistry::ResetCache()
{
	for (TPair<FName, UVerseWeaponDefinition*>& P : WeaponCache())
	{
		P.Value->RemoveFromRoot();
	}
	for (TPair<FName, UVerseGadgetDefinition*>& P : GadgetCache())
	{
		P.Value->RemoveFromRoot();
	}
	WeaponCache().Reset();
	GadgetCache().Reset();
}

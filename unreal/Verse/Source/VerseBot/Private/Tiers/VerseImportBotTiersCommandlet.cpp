#include "Tiers/VerseImportBotTiersCommandlet.h"

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Tiers/VerseBotTierData.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "VerseLog.h"

namespace VerseImportBotTiersImpl
{
	struct FTierAssetJob
	{
		FString PackagePath;
		UObject* FromJson = nullptr;
	};

	UObject* LoadExisting(const FString& PackagePath, UClass* Class)
	{
		const FString ObjectPath = PackagePath + TEXT(".") + VerseBotTierData::ObjectNameOf(PackagePath);
		if (!FPackageName::DoesPackageExist(PackagePath))
		{
			return nullptr;
		}
		return StaticLoadObject(Class, nullptr, *ObjectPath);
	}

	bool WriteAsset(const FTierAssetJob& Job)
	{
#if WITH_EDITOR
		UPackage* Package = CreatePackage(*Job.PackagePath);
		Package->FullyLoad();
		const FName Name(*VerseBotTierData::ObjectNameOf(Job.PackagePath));
		UObject* Existing = StaticFindObjectFast(nullptr, Package, Name);
		if (Existing)
		{
			Existing->Rename(nullptr, GetTransientPackage(), REN_DontCreateRedirectors | REN_NonTransactional);
		}
		UObject* Asset = NewObject<UObject>(Package, Job.FromJson->GetClass(), Name, RF_Public | RF_Standalone, Job.FromJson);
		Asset->ClearFlags(RF_Transient);
		Package->MarkPackageDirty();

		const FString Filename =
			FPackageName::LongPackageNameToFilename(Job.PackagePath, FPackageName::GetAssetPackageExtension());
		FSavePackageArgs Args;
		Args.TopLevelFlags = RF_Public | RF_Standalone;
		Args.SaveFlags = SAVE_NoError;
		const bool bSaved = UPackage::SavePackage(Package, Asset, *Filename, Args);
		UE_LOG(LogVerseBot, Display, TEXT("VerseImportBotTiers: %s %s"), bSaved ? TEXT("wrote") : TEXT("FAILED to write"), *Filename);
		return bSaved;
#else
		UE_LOG(LogVerseBot, Error, TEXT("VerseImportBotTiers: writing assets needs an editor build"));
		return false;
#endif
	}
}

using namespace VerseImportBotTiersImpl;

UVerseImportBotTiersCommandlet::UVerseImportBotTiersCommandlet()
{
	IsClient = false;
	IsEditor = true;
	IsServer = false;
	LogToConsole = true;
}

int32 UVerseImportBotTiersCommandlet::Main(const FString& Params)
{
	const bool bCheck = FParse::Param(*Params, TEXT("check"));
	FString DataDir;
	if (!FParse::Value(*Params, TEXT("data="), DataDir))
	{
		DataDir = VerseBotTierData::DefaultDataDir();
	}

	FString TiersText;
	FString AdaptiveText;
	if (!FFileHelper::LoadFileToString(TiersText, *FPaths::Combine(DataDir, TEXT("tiers.json")))
		|| !FFileHelper::LoadFileToString(AdaptiveText, *FPaths::Combine(DataDir, TEXT("adaptive.json"))))
	{
		UE_LOG(LogVerseBot, Error, TEXT("VerseImportBotTiers: cannot read tiers.json and adaptive.json in %s"), *DataDir);
		return 1;
	}

	TArray<FString> Errors;
	TMap<FName, UVerseBotTier*> Tiers;
	UVerseBotAdaptiveConfig* Adaptive = nullptr;
	VerseBotTierData::ReadTiers(TiersText, nullptr, Tiers, Errors);
	VerseBotTierData::ReadAdaptive(AdaptiveText, nullptr, Adaptive, Errors);
	if (Errors.Num() > 0)
	{
		for (const FString& Error : Errors)
		{
			UE_LOG(LogVerseBot, Error, TEXT("VerseImportBotTiers: %s"), *Error);
		}
		return 1;
	}

	TArray<FTierAssetJob> Jobs;
	for (const FName Id : VerseBotTierData::TierIds())
	{
		Jobs.Add({VerseBotTierData::TierPackagePath(Id), Tiers[Id]});
	}
	Jobs.Add({VerseBotTierData::AdaptivePackagePath(), Adaptive});

	int32 Differing = 0;
	int32 Failed = 0;
	for (const FTierAssetJob& Job : Jobs)
	{
		const UObject* Existing = LoadExisting(Job.PackagePath, Job.FromJson->GetClass());
		const TArray<FString> Diffs = Existing ? VerseBotTierData::DiffObjects(*Existing, *Job.FromJson) : TArray<FString>{TEXT("asset missing")};
		if (Diffs.Num() == 0)
		{
			UE_LOG(LogVerseBot, Display, TEXT("VerseImportBotTiers: %s matches the JSON"), *Job.PackagePath);
			continue;
		}
		++Differing;
		for (const FString& Diff : Diffs)
		{
			UE_LOG(LogVerseBot, Display, TEXT("VerseImportBotTiers: %s differs: %s"), *Job.PackagePath, *Diff);
		}
		if (!bCheck && !WriteAsset(Job))
		{
			++Failed;
		}
	}

	if (bCheck)
	{
		if (Differing > 0)
		{
			UE_LOG(LogVerseBot, Error, TEXT("VerseImportBotTiers -check: %d asset(s) differ from the JSON; run the commandlet and commit"),
				Differing);
			return 1;
		}
		UE_LOG(LogVerseBot, Display, TEXT("VerseImportBotTiers -check: all %d assets match"), Jobs.Num());
		return 0;
	}
	return Failed > 0 ? 1 : 0;
}

#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "CoreMinimal.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Tiers/VerseBotTierData.h"
#include "UObject/StrongObjectPtr.h"

/** Test helpers shared by the WP09 suites: the tiers as tiers.json says, the evidence folder. */
namespace VerseBotTierTest
{
	/** The three tiers read from unreal/Verse/Data/bot/tiers.json (the source of truth). */
	struct FTierSet
	{
		TStrongObjectPtr<UVerseBotTier> Normal;
		TStrongObjectPtr<UVerseBotTier> Hard;
		TStrongObjectPtr<UVerseBotTier> Elite;
		TStrongObjectPtr<UVerseBotAdaptiveConfig> Adaptive;
		TArray<FString> Errors;

		bool IsValid() const { return Errors.Num() == 0 && Normal && Hard && Elite && Adaptive; }

		const UVerseBotTier* Get(FName Id) const
		{
			if (Id == TEXT("normal")) return Normal.Get();
			if (Id == TEXT("hard")) return Hard.Get();
			if (Id == TEXT("elite")) return Elite.Get();
			return nullptr;
		}
	};

	inline FTierSet LoadTierSet()
	{
		FTierSet Set;
		FString TiersText;
		FString AdaptiveText;
		const FString Dir = VerseBotTierData::DefaultDataDir();
		if (!FFileHelper::LoadFileToString(TiersText, *FPaths::Combine(Dir, TEXT("tiers.json")))
			|| !FFileHelper::LoadFileToString(AdaptiveText, *FPaths::Combine(Dir, TEXT("adaptive.json"))))
		{
			Set.Errors.Add(FString::Printf(TEXT("cannot read the bot data in %s"), *Dir));
			return Set;
		}
		TMap<FName, UVerseBotTier*> Tiers;
		UVerseBotAdaptiveConfig* Adaptive = nullptr;
		VerseBotTierData::ReadTiers(TiersText, nullptr, Tiers, Set.Errors);
		VerseBotTierData::ReadAdaptive(AdaptiveText, nullptr, Adaptive, Set.Errors);
		if (UVerseBotTier** T = Tiers.Find(TEXT("normal"))) Set.Normal.Reset(*T);
		if (UVerseBotTier** T = Tiers.Find(TEXT("hard"))) Set.Hard.Reset(*T);
		if (UVerseBotTier** T = Tiers.Find(TEXT("elite"))) Set.Elite.Reset(*T);
		Set.Adaptive.Reset(Adaptive);
		return Set;
	}

	/** unreal/Verse/Saved/Harness/proof/WP09/<SubTask>/ (ignored; uploaded as CI artifacts, work-packages 0.4). */
	inline FString ProofDir(const TCHAR* SubTask)
	{
		const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness/proof/WP09"), SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		return Dir;
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "HAL/PlatformFileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

/**
 * Writes WP08 evidence (work-packages.md 0.4) to Saved/Harness/proof/WP08/<SubTask>/. Metrics and
 * reports only; never match-memory content (L1).
 */
namespace VerseBotTestProof
{
	inline FString Dir(const TCHAR* SubTask)
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP08"), SubTask);
	}

	inline bool Write(const TCHAR* SubTask, const TCHAR* FileName, const FString& Text)
	{
		const FString Folder = Dir(SubTask);
		IPlatformFile& PF = FPlatformFileManager::Get().GetPlatformFile();
		PF.CreateDirectoryTree(*Folder);
		return FFileHelper::SaveStringToFile(Text, *FPaths::Combine(Folder, FileName), FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM);
	}

	/** p-th percentile (0..100) of a copy of Values. */
	inline double Percentile(TArray<double> Values, double P)
	{
		if (Values.Num() == 0)
		{
			return 0.0;
		}
		Values.Sort();
		const int32 Index = FMath::Clamp(int32(FMath::CeilToDouble(P / 100.0 * Values.Num())) - 1, 0, Values.Num() - 1);
		return Values[Index];
	}

	inline float Median(TArray<float> Values)
	{
		if (Values.Num() == 0)
		{
			return 0.f;
		}
		Values.Sort();
		return Values[Values.Num() / 2];
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

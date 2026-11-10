#include "Audio/VerseAudioCueSet.h"

#include "AssetRegistry/AssetData.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Misc/PackageName.h"
#include "Noise/VerseAudibilityTable.h"

const TCHAR* UVerseAudioCueSet::DefaultAssetPath = TEXT("/Game/Verse/Audio/DA_AudioCues.DA_AudioCues");
const TCHAR* UVerseAudioCueSet::SharedAudibilityPath = TEXT("/Game/Verse/Core/DA_Audibility.DA_Audibility");

FVerseAudioMixSettings::FVerseAudioMixSettings()
{
	// mix.json bus_gain_db, EVerseAudioBus order.
	BusGainDb = {0.f, -3.f, -4.f, -2.f, -3.f, -6.f, -8.f};
	// occlusion.json, penetration-table wire order (destruction.md 2).
	OcclusionLossDb = {-9.f, -12.f, -4.f, -10.f, -1.f, -6.f, -20.f, -18.f};
	OcclusionLowpassHz = {2500.f, 1500.f, 6000.f, 2000.f, 15000.f, 3000.f, 700.f, 900.f};
}

const FVerseAudioCue* UVerseAudioCueSet::FindCue(FName CueId) const
{
	if (Index.Num() != Cues.Num())
	{
		const_cast<UVerseAudioCueSet*>(this)->RebuildIndex();
	}
	const int32* Found = Index.Find(CueId);
	return Found && Cues.IsValidIndex(*Found) && Cues[*Found].CueId == CueId ? &Cues[*Found] : nullptr;
}

const UVerseAudibilityTable* UVerseAudioCueSet::FindSharedAudibility()
{
	const FString PackageName = FPackageName::ObjectPathToPackageName(FString(SharedAudibilityPath));
	if (FPackageName::DoesPackageExist(PackageName))
	{
		if (const UVerseAudibilityTable* AtPath =
				LoadObject<UVerseAudibilityTable>(nullptr, SharedAudibilityPath, nullptr, LOAD_NoWarn | LOAD_Quiet))
		{
			return AtPath;
		}
	}
	// The asset may live elsewhere; there is exactly one table in the project (bot.md 3.2, F6).
	if (IAssetRegistry* Registry = IAssetRegistry::Get())
	{
		TArray<FAssetData> Assets;
		Registry->GetAssetsByClass(UVerseAudibilityTable::StaticClass()->GetClassPathName(), Assets, true);
		Assets.Sort([](const FAssetData& A, const FAssetData& B) { return A.PackageName.LexicalLess(B.PackageName); });
		for (const FAssetData& Asset : Assets)
		{
			if (const UVerseAudibilityTable* Found = Cast<UVerseAudibilityTable>(Asset.GetAsset()))
			{
				return Found;
			}
		}
	}
	return nullptr;
}

const UVerseAudibilityTable& UVerseAudioCueSet::GetAudibility() const
{
	if (Audibility)
	{
		return *Audibility;
	}
	if (!bSearchedSharedAudibility)
	{
		bSearchedSharedAudibility = true;
		SharedAudibility = FindSharedAudibility();
	}
	if (const UVerseAudibilityTable* Shared = SharedAudibility.Get())
	{
		return *Shared;
	}
	return *GetDefault<UVerseAudibilityTable>();
}

FName UVerseAudioCueSet::WeaponProfileFor(FName WeaponId) const
{
	if (const FName* Mapped = WeaponIdProfiles.Find(WeaponId))
	{
		return *Mapped;
	}
	const FString Id = WeaponId.ToString();
	for (const FName& Profile : WeaponProfiles)
	{
		if (Id.Contains(Profile.ToString(), ESearchCase::IgnoreCase))
		{
			return Profile;
		}
	}
	return DefaultWeaponProfile;
}

void UVerseAudioCueSet::RebuildIndex()
{
	Index.Reset();
	for (int32 I = 0; I < Cues.Num(); ++I)
	{
		Index.Add(Cues[I].CueId, I);
	}
}

void UVerseAudioCueSet::PostLoad()
{
	Super::PostLoad();
	RebuildIndex();
}

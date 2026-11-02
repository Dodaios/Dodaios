#pragma once

#include "Audio/VerseAudioTypes.h"
#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseAudioCueSet.generated.h"

class UVerseAudibilityTable;

/**
 * DA_AudioCues: every Verse cue, the mix and the occlusion table. Written by
 * art/verse/audio/import_audio.py from unreal/Verse/Data/audio/{cues,mix,occlusion}.json.
 */
UCLASS(BlueprintType)
class VERSEUI_API UVerseAudioCueSet : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	/** Object path of the shipped asset. */
	static const TCHAR* DefaultAssetPath;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	TArray<FVerseAudioCue> Cues;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FVerseAudioMixSettings Mix;

	/**
	 * Weapon sound profiles (cue prefix wpn_<profile>_, rld_<profile>_, eqp_<profile>). A weapon id
	 * uses the first profile its name contains, else DefaultWeaponProfile.
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	TArray<FName> WeaponProfiles;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FName DefaultWeaponProfile = TEXT("rifle");

	/** DA_Audibility (Core). Unset: the contract table of bot.md 3.2. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	TObjectPtr<UVerseAudibilityTable> Audibility;

	const FVerseAudioCue* FindCue(FName CueId) const;

	/** The audibility table in use: Audibility, or the class default (the contract rows). */
	const UVerseAudibilityTable& GetAudibility() const;

	FName WeaponProfileFor(FName WeaponId) const;

	/** Rebuild the id index after Cues changed (import, tests). */
	void RebuildIndex();

	virtual void PostLoad() override;

private:
	mutable TMap<FName, int32> Index;
};

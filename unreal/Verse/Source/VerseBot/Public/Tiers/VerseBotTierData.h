#pragma once

#include "CoreMinimal.h"

class UVerseBotAdaptiveConfig;
class UVerseBotTier;

/**
 * Tiers as data (bot.md 9): unreal/Verse/Data/bot/tiers.json and adaptive.json are the source of
 * truth; the VerseImportBotTiers commandlet writes /Game/Verse/Bot/Tiers/DA_BotTier_* and
 * DA_BotAdaptive from them, and Verse.Bot.Tiers.AssetsMatchJson fails CI when the assets differ.
 *
 * The readers are strict: every field of the asset class must appear exactly once with the right
 * JSON type, and an unknown field is an error, so a renamed or dropped field never imports silently.
 */
namespace VerseBotTierData
{
	/** Schema ids written at the top of the two files. */
	inline const TCHAR* TiersSchema = TEXT("verse.bot.tiers/1");
	inline const TCHAR* AdaptiveSchema = TEXT("verse.bot.adaptive/1");

	/** The tier ids of tiers.json, in ladder order. */
	VERSEBOT_API const TArray<FName>& TierIds();

	/** Asset package of a tier id: /Game/Verse/Bot/Tiers/DA_BotTier_Normal and so on. */
	VERSEBOT_API FString TierPackagePath(FName TierId);

	/** /Game/Verse/Bot/Tiers/DA_BotAdaptive. */
	VERSEBOT_API FString AdaptivePackagePath();

	/** Object name inside the package (the package's short name). */
	VERSEBOT_API FString ObjectNameOf(const FString& PackagePath);

	/** unreal/Verse/Data/bot/ of the running project. */
	VERSEBOT_API FString DefaultDataDir();

	/**
	 * Reads tiers.json text into one object per tier id (TierIds order). Objects are created in
	 * Outer (transient package when null). Returns false and fills Errors on any schema problem.
	 */
	VERSEBOT_API bool ReadTiers(const FString& JsonText, UObject* Outer, TMap<FName, UVerseBotTier*>& OutTiers,
		TArray<FString>& Errors);

	/** Reads adaptive.json text. */
	VERSEBOT_API bool ReadAdaptive(const FString& JsonText, UObject* Outer, UVerseBotAdaptiveConfig*& OutConfig,
		TArray<FString>& Errors);

	/**
	 * Contract floors and caps (bot.md 4.5, 7.3: WallbangMinBelief >= 0.25,
	 * WallbangMaxSourceAgeS <= 4, LearnWeightMax <= 0.35) plus the sanity ranges every consumer
	 * relies on: probabilities in [0, 1], times and rates positive, pairs ordered.
	 */
	VERSEBOT_API void ValidateTier(const UVerseBotTier& Tier, TArray<FString>& Errors);

	/** The adaptive bounds: StartSkill in [0, 1], 0 < MaxStepPerKill <= 0.05, apply at respawn, ... */
	VERSEBOT_API void ValidateAdaptive(const UVerseBotAdaptiveConfig& Config, TArray<FString>& Errors);

	/** Hard step cap of the adaptive controller (A9.5, BG10). */
	inline constexpr float AdaptiveMaxStepCap = 0.05f;

	/**
	 * Field-by-field difference of two objects of the same class (own UPROPERTYs only), as
	 * "Field: a != b" lines. Empty when equal. Floats compare exactly: the asset holds what the
	 * JSON said, nothing else.
	 */
	VERSEBOT_API TArray<FString> DiffObjects(const UObject& A, const UObject& B);
}

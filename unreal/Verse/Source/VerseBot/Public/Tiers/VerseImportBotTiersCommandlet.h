#pragma once

#include "Commandlets/Commandlet.h"
#include "CoreMinimal.h"

#include "VerseImportBotTiersCommandlet.generated.h"

/**
 * VerseImportBotTiers (bot.md 9.1): writes /Game/Verse/Bot/Tiers/DA_BotTier_Normal, _Hard, _Elite and
 * DA_BotAdaptive from unreal/Verse/Data/bot/tiers.json and adaptive.json.
 *
 *   UnrealEditor-Cmd Verse.uproject -run=VerseImportBotTiers            write the assets that differ
 *   UnrealEditor-Cmd Verse.uproject -run=VerseImportBotTiers -check     CI diff: exit 1 when an asset is
 *                                                                        missing or differs from the JSON
 *   -data=<dir>   read the JSON from another folder (default unreal/Verse/Data/bot)
 *
 * Both modes validate the floors and caps first and exit 1 on a violation, so an asset outside the
 * contract is never written.
 */
UCLASS()
class VERSEBOT_API UVerseImportBotTiersCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UVerseImportBotTiersCommandlet();

	virtual int32 Main(const FString& Params) override;
};

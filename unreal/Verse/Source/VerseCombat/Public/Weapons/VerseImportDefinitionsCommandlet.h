#pragma once

#include "Commandlets/Commandlet.h"
#include "CoreMinimal.h"

#include "VerseImportDefinitionsCommandlet.generated.h"

/**
 * WP02.1 importer: writes every weapon JSON of Data/weapons to its DA_Weapon_* asset and every
 * entry of gadgets.json to its DA_Gadget_* asset under FVerseDefinitionJson::AssetFolder.
 *
 *     UnrealEditor-Cmd.exe Verse.uproject -run=VerseImportDefinitions -unattended -nullrhi
 *     UnrealEditor-Cmd.exe Verse.uproject -run=VerseImportDefinitions -check   (diff only, exit 1 on drift)
 *
 * Agents run it through scripts/unreal/with_lock.py (machine lock).
 */
UCLASS()
class VERSECOMBAT_API UVerseImportDefinitionsCommandlet : public UCommandlet
{
	GENERATED_BODY()

public:
	UVerseImportDefinitionsCommandlet();

	virtual int32 Main(const FString& Params) override;
};

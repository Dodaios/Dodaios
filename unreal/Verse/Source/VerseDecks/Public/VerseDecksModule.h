#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseDecks. Scope: see docs/verse/unreal/architecture.md. */
class FVerseDecksModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

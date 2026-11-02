#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseBot. Scope: see docs/verse/unreal/architecture.md. */
class FVerseBotModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseDestruction. Scope: see docs/verse/unreal/architecture.md. */
class FVerseDestructionModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

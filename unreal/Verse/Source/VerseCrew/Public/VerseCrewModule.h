#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseCrew. Scope: see docs/verse/unreal/architecture.md. */
class FVerseCrewModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

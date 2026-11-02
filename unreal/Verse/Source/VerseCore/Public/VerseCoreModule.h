#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseCore. Scope: see docs/verse/unreal/architecture.md. */
class FVerseCoreModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

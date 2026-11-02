#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseGore. Scope: see docs/verse/unreal/architecture.md. */
class FVerseGoreModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

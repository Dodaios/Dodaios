#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseHarness. Scope: see docs/verse/unreal/architecture.md. */
class FVerseHarnessModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

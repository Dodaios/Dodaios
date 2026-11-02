#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseUI. Scope: see docs/verse/unreal/architecture.md. */
class FVerseUIModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

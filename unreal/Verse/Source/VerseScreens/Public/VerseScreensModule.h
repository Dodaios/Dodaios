#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseScreens. Scope: see docs/verse/unreal/architecture.md. */
class FVerseScreensModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

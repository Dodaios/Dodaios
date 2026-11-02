#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseBridge. Scope: see docs/verse/unreal/architecture.md. */
class FVerseBridgeModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

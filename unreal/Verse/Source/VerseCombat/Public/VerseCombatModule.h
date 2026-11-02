#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseCombat. Scope: see docs/verse/unreal/architecture.md. */
class FVerseCombatModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseMovement. Scope: see docs/verse/unreal/architecture.md. */
class FVerseMovementModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

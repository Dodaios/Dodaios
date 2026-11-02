#pragma once

#include "Modules/ModuleManager.h"

/** Runtime module VerseStream. Scope: see docs/verse/unreal/architecture.md. */
class FVerseStreamModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

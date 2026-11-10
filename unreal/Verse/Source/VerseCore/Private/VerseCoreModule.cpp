#include "VerseCoreModule.h"

#include "VerseFramePacing.h"

void FVerseCoreModule::StartupModule()
{
	FVerseFramePacing::Start();
}

void FVerseCoreModule::ShutdownModule()
{
	FVerseFramePacing::Stop();
}

IMPLEMENT_MODULE(FVerseCoreModule, VerseCore);

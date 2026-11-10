#include "VerseGameInstance.h"

#include "CoreGlobals.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"

void UVerseGameInstance::Init()
{
	Super::Init();
	// A player never sees the engine's developer warnings (renderer notes, shader compile lines)
	// over the game; the editor's own viewports keep them.
	if (!GIsEditor && !FParse::Param(FCommandLine::Get(), TEXT("ScreenMessages")))
	{
		GAreScreenMessagesEnabled = false;
	}
}

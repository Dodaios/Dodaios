#include "VerseDefaultGameMode.h"

#include "VerseDefaultCharacter.h"
#include "VerseDefaultPlayerController.h"

AVerseDefaultGameMode::AVerseDefaultGameMode()
{
	DefaultPawnClass = AVerseDefaultCharacter::StaticClass();
	PlayerControllerClass = AVerseDefaultPlayerController::StaticClass();
}

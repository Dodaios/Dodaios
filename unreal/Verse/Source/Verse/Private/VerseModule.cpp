#include "Modules/ModuleManager.h"

// The primary game module. It wires the feature modules together through the
// default classes below and holds no feature logic itself (architecture.md 2).
IMPLEMENT_PRIMARY_GAME_MODULE(FDefaultGameModuleImpl, Verse, "Verse");

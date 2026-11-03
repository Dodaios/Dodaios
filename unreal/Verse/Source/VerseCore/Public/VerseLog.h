#pragma once

#include "CoreMinimal.h"
#include "Logging/LogMacros.h"

// One log category per Verse module, declared in Core so every module logs under its own
// name without new include edges (architecture.md 2). A module uses only its own category.

VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerse, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseCore, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseBridge, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseMovement, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseDestruction, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseCombat, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseGore, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseDecks, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseCrew, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseScreens, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseBot, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseUI, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseStream, Log, All);
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseHarness, Log, All);
/** Verse.QA.* console commands and the qa.exec bridge path (parity.md 19). */
VERSECORE_API DECLARE_LOG_CATEGORY_EXTERN(LogVerseQa, Log, All);

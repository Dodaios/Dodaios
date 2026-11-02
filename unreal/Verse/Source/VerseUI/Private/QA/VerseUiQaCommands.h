#pragma once

class UVerseUiSubsystem;

/** The Verse.QA.* commands of the UI area (parity 19, work-packages 0.2: UI owns Stats). */
namespace VerseUiQa
{
	/** Registers Verse.QA.Stats once; it reports on the most recent game-world UI. */
	void RegisterCommands(UVerseUiSubsystem* Owner);

	/** The UI is going away; the command keeps answering without HUD numbers. */
	void Release(UVerseUiSubsystem* Owner);
}

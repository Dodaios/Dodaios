#pragma once

#include "CoreMinimal.h"

/**
 * The one owner of t.MaxFPS. The Verse runs beside the app and other work, so an uncapped frame
 * rate burns CPU cores for frames nobody needs. Several parts want a cap: the person's frame limit
 * (game settings), the bridge lifecycle (panel 30, dormant 2), the panel stream, and the pacing
 * rules below. Each part sets its own input here; a ticker applies the lowest cap.
 *
 * Pacing rules:
 * - outside a duel (decks, menus, loading) at most DeckFps;
 * - while the Verse window is not the foreground window at most BackgroundFps.
 *
 * A t.MaxFPS set from the console or the command line (-ExecCmds, perf runs) wins: the pacer
 * never overrides a value set with a higher priority than code.
 */
struct VERSECORE_API FVerseFramePacing
{
	static constexpr float DeckFps = 60.f;
	static constexpr float BackgroundFps = 30.f;

	struct FInputs
	{
		/** The person's frame limit; 0 = unlimited. */
		float UserLimit = 0.f;
		/** Bridge lifecycle cap; 0 = none. */
		float LifecycleCap = 0.f;
		/** Panel stream cap; 0 = none. */
		float StreamCap = 0.f;
		bool bDuelRunning = false;
		bool bForeground = true;
	};

	/** The cap for these inputs, the lowest of every active one; 0 = uncapped. */
	static float Resolve(const FInputs& In);

	static void SetLifecycleCap(float Fps);
	static void SetStreamCap(float Fps);
	static void SetDuelRunning(bool bRunning);

	/** Reads the person's limit and the window focus, then writes t.MaxFPS when it differs. Game thread. */
	static void Apply();

	/** Starts the ticker (VerseCore startup); does nothing in the editor, commandlets and servers. */
	static void Start();
	static void Stop();
};

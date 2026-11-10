#pragma once

#include "CoreMinimal.h"
#include "Stream/VerseStreamTypes.h"

/**
 * Decides whether the panel streams (WP20.5, architecture.md 6). Pure logic, no engine state.
 *
 * - The panel streams only while it is visible and the full Verse window is not.
 * - Both visible at once: the full window wins. The stream stops with the error
 *   `full_view_open`, so the panel keeps its last frame and shows "Verse is open"; the GPU
 *   never renders two views.
 * - The panel never hosts a duel; panel and duel are separate questions (input policy).
 */
class VERSESTREAM_API FVerseStreamArbiter
{
public:
	/** `panel.visibility`. A hidden panel clears its geometry. */
	void SetPanelVisible(bool bVisible, const FVersePanelGeometry& Geometry);

	/** `panel.resize`. Ignored while the panel is hidden. Returns true when the size changed. */
	bool SetPanelGeometry(const FVersePanelGeometry& Geometry);

	/** The lifecycle reports whether the full Verse window is showing (state Visible). */
	void SetFullViewVisible(bool bVisible);

	bool IsPanelVisible() const { return bPanelVisible; }
	bool IsFullViewVisible() const { return bFullViewVisible; }
	const FVersePanelGeometry& GetGeometry() const { return Geometry; }

	/** True when the stream should run now. */
	bool WantsStream() const;

	/** True when the lifecycle should be in Panel (panel visible, full view hidden). */
	bool WantsPanelState() const { return WantsStream(); }

	/** Why the stream is not running although the panel is visible; empty otherwise. */
	FString BlockReason() const;

private:
	bool bPanelVisible = false;
	bool bFullViewVisible = false;
	FVersePanelGeometry Geometry;
};

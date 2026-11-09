#pragma once

#include "CoreMinimal.h"
#include "GenericPlatform/GenericWindow.h"
#include "Stream/VerseStreamDriver.h"

/**
 * Drives the Pixel Streaming 2 plugin's default streamer through console variables and
 * commands only (no module dependency):
 *
 * - `PixelStreaming2.ConnectionURL` = the signalling URL with the streamer key,
 * - `PixelStreaming2.WebRTC.Fps` 30, `PixelStreaming2.WebRTC.MaxBitrate` 8 Mbit/s,
 *   `PixelStreaming2.Encoder.Codec` H264 (hardware encoder),
 * - `PixelStreaming2.WebRTC.PortAllocatorFlags` without STUN and relay (loopback ICE only),
 * - `PixelStreaming2.AllowPixelStreamingCommands` false, `PixelStreaming2.KeyFilter` from
 *   the panel input policy,
 * - `t.MaxFPS` 30 for the session, restored on stop.
 *
 * The default streamer captures the back buffer, so for the session the window renders
 * windowed at the panel size. Start saves the window's resolution and mode, and Stop (and a
 * failed Start) restores them, so the full view comes back as it was. Rendering offscreen at
 * the panel size (WP20.2) needs the PixelStreaming2 module edge and replaces this later.
 */
class VERSESTREAM_API FVerseConsoleStreamDriver : public IVerseStreamDriver
{
public:
	virtual bool IsAvailable() const override;
	virtual void Start(const FVerseStreamConfig& Config, FOnStarted OnStarted) override;
	virtual void Stop() override;
	virtual void Resize(FIntPoint RenderSize) override;
	virtual bool IsStreaming() const override { return bStreaming; }

	/** Console variables and values Start applies for Config (tests read them). */
	static TArray<TPair<FString, FString>> SettingsFor(const FVerseStreamConfig& Config);

	/** A window resolution and mode, as the driver saves and restores it. */
	struct FWindowState
	{
		int32 ResX = 0;
		int32 ResY = 0;
		EWindowMode::Type Mode = EWindowMode::Windowed;
	};

protected:
	/** Runs a console command of the plugin (virtual so tests run without the plugin). */
	virtual bool RunCommand(const TCHAR* Command) const;
	/** The window's current resolution and mode. */
	virtual FWindowState CurrentWindow() const;
	/** Asks the engine for a window resolution and mode. */
	virtual void RequestWindow(const FWindowState& State) const;

private:
	void ApplyRenderSize(FIntPoint RenderSize) const;
	void RestoreWindow();

	bool bStreaming = false;
	FWindowState SavedWindow;
	bool bSavedWindow = false;
	FString SavedMaxFps;
	bool bSavedMaxFps = false;
};

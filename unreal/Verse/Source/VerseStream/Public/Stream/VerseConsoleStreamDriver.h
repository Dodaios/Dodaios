#pragma once

#include "CoreMinimal.h"
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
 * - `t.MaxFPS` 30 for the session, restored on stop; the window renders at the panel size.
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

private:
	bool RunCommand(const TCHAR* Command) const;
	void ApplyRenderSize(FIntPoint RenderSize) const;

	bool bStreaming = false;
	FString SavedMaxFps;
	bool bSavedMaxFps = false;
};

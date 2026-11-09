#pragma once

#include "Cells/VerseCells.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Render/VerseTerminalPainter.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseScreensSubsystem.generated.h"

class IVerseCommandLink;
class UVerseChatTailScreenComponent;
class UVerseTerminalMonitorComponent;

/** A desk that could be watched: one pane at one place. */
struct FVerseWatchCandidate
{
	FString PaneId;
	FVector Location = FVector::ZeroVector;
};

/** One entry of a `screens.watch` list. */
struct FVerseWatchEntry
{
	FString PaneId;
	int32 Hz = 2;
	double DistanceCm = 0.0;

	bool operator==(const FVerseWatchEntry& O) const { return PaneId == O.PaneId && Hz == O.Hz; }
};

/** The watch rules of WP16.3 (architecture 5.3): view distance, at most 8, far desks at 2 Hz. */
struct FVerseWatchSettings
{
	/** `welcome.limits.screens_max_panes`. */
	int32 MaxPanes = 8;
	/** `welcome.limits.screens_max_hz`. */
	int32 MaxHz = 10;
	int32 FarHz = 2;
	/** Desks farther than this are not watched. */
	double ViewDistanceCm = 2500.0;
	/** Desks this close and in front of the view get the full rate. */
	double NearDistanceCm = 800.0;
};

/** Counters of the screens path (A16.2 load test, bridge counters of architecture 7). */
struct FVerseScreensStats
{
	uint64 BytesIn = 0;
	int32 FramesIn = 0;
	int32 FramesApplied = 0;
	int32 Resyncs = 0;
	int32 UnknownRefs = 0;
	int32 Rejected = 0;
	int32 Redraws = 0;
	int32 RowsDrawn = 0;
	/** Game-thread seconds spent decoding, applying and repainting. */
	double WorkSeconds = 0.0;
	int32 WatchesSent = 0;
	int32 ChatWatchesSent = 0;
};

/**
 * Feeds desk monitors and consoles (WP16.1-16.5): plans the watch set from the view, sends
 * `screens.watch` and `chat_tails.watch`, routes `cells.bin/1` and JSON frames to monitors by
 * `ref` and pane id, asks for a resync on a gap, repaints a few dirty screens per frame (far ones
 * at 2 Hz), and runs desk takeover. Inbound frames come from the bridge client through
 * HandleBridgeBinary / HandleBridgeFrame.
 */
UCLASS()
class VERSESCREENS_API UVerseScreensSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseScreensSubsystem* Get(const UObject* WorldContext);

	void RegisterMonitor(UVerseTerminalMonitorComponent* Monitor);
	void UnregisterMonitor(UVerseTerminalMonitorComponent* Monitor);
	void RegisterChatScreen(UVerseChatTailScreenComponent* Screen);
	void UnregisterChatScreen(UVerseChatTailScreenComponent* Screen);

	/** Registers the desk takeover use target of a monitor with the station framework. */
	int32 AddTakeoverTarget(UVerseTerminalMonitorComponent* Monitor);

	/** Nearest first, unique panes, at most MaxPanes, near and in front at MaxHz, the rest at FarHz. */
	static TArray<FVerseWatchEntry> PlanWatch(TConstArrayView<FVerseWatchCandidate> Candidates, const FVector& ViewLocation,
		const FVector& ViewDirection, const FVerseWatchSettings& Settings);

	/** Reads `welcome.limits` (screens_max_panes, screens_max_hz, chat_tails_max_agents). */
	void ApplyWelcome(const FJsonObject& WelcomeData);

	/** A binary frame from the bridge (cells.bin/1). */
	void HandleBridgeBinary(TConstArrayView<uint8> Bytes);
	/** A JSON frame from the bridge: screens.frame, screens.meta, screens.gone, chat_tails.update, welcome. */
	void HandleBridgeFrame(const FJsonObject& Envelope);
	/** The link reconnected: refs are void, every pane gets a fresh snapshot after the next watch. */
	void HandleLinkReset();

	/** Re-plans now and sends the watch lists when they changed (the tick does it every 0.5 s). */
	void UpdateWatch();
	/** Repaints up to MaxRedrawsPerFrame screens that need it (the tick does it every frame). */
	int32 RedrawDirty(double Now);

	/** Desk takeover (WP16.5): `ide.focus_terminal {pane_id}`; on ok the app takes the foreground. */
	bool RequestTakeover(UVerseTerminalMonitorComponent* Monitor);
	/** Milliseconds from the use key to handing the foreground to the app, of the last takeover; -1 if none. */
	double LastTakeoverMs() const { return TakeoverMs; }
	bool IsTakeoverInFlight() const { return bTakeoverInFlight; }

	void SetViewOverride(const FVector& Location, const FVector& Direction);
	void ClearViewOverride() { bViewOverride = false; }

	const FVerseWatchSettings& Settings() const { return WatchSettings; }
	FVerseWatchSettings& MutableSettings() { return WatchSettings; }
	int32 MaxChatAgents = 6;
	int32 MaxRedrawsPerFrame = 3;

	const FVerseScreensStats& Stats() const { return Counters; }
	void ResetStats() { Counters = FVerseScreensStats(); }
	const TArray<FVerseWatchEntry>& SentWatch() const { return LastSent; }
	const TArray<FString>& SentChatWatch() const { return LastChatSent; }
	/** The pane a `ref` is bound to, or empty. */
	FString PaneForRef(uint16 Ref) const;

	// UTickableWorldSubsystem
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

private:
	IVerseCommandLink* Link() const;
	bool ReadView(FVector& OutLocation, FVector& OutDirection) const;
	void ApplyToPane(const FString& PaneId, FVerseCellFrame&& Frame);
	void RequestResync(const FString& PaneId);
	void HandleWatchReply(const TArray<FVerseWatchEntry>& Sent, const struct FVerseCommandReply& Reply);
	TArray<UVerseTerminalMonitorComponent*> MonitorsFor(const FString& PaneId) const;

	TArray<TWeakObjectPtr<UVerseTerminalMonitorComponent>> Monitors;
	TArray<TWeakObjectPtr<UVerseChatTailScreenComponent>> ChatScreens;
	FVerseWatchSettings WatchSettings;
	TArray<FVerseWatchEntry> LastSent;
	TArray<FString> LastChatSent;
	bool bWatchInFlight = false;
	bool bWatchStale = false;
	TMap<uint16, FString> RefToPane;
	TSet<FString> ResyncInFlight;
	FVerseScreensStats Counters;
	FVerseTerminalDrawList Scratch;
	int32 RedrawCursor = 0;
	float SinceWatch = 0.f;
	bool bViewOverride = false;
	FVector OverrideLocation = FVector::ZeroVector;
	FVector OverrideDirection = FVector::ForwardVector;
	bool bTakeoverInFlight = false;
	double TakeoverMs = -1.0;
	/** Bumped on reset and deinitialize, so replies to a dead generation are dropped. */
	int32 Generation = 0;
};

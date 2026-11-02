#pragma once

#include "CoreMinimal.h"
#include "Bridge/VerseBridgeCodec.h"
#include "Bridge/VerseBridgeFeeds.h"
#include "Bridge/VerseWsClient.h"

/**
 * The Verse side of verse.bridge/1 (WP17.11, bridge-protocol.md 1-3, 8): discovery, hello,
 * ping every second, 5 s dead-link rule, reconnect with backoff (250 ms, 1 s, 2 s, 4 s, then
 * every 5 s) and the same token, fresh snapshots on resubscribe (no replay), seq gap
 * detection with resync, typed feeds, and commands with exactly one reply each.
 *
 * Plain C++ so it is testable outside a world: UVerseBridgeSubsystem owns one and ticks it.
 */
class VERSEBRIDGE_API FVerseBridgeClient
{
public:
	using FReply = TFunction<void(bool bOk, const TSharedPtr<FJsonObject>& Result, const FString& ErrorCode)>;

	enum class EState : uint8
	{
		Idle,
		Connecting,
		Handshaking,
		Linked,
		Waiting,   // backing off before the next attempt
		LaunchOver // 4401 on reconnect: the launch is over
	};

	struct FDiscovery
	{
		FString Url;
		FString Token;
	};

	/** DODAIOS_VERSE_BRIDGE + DODAIOS_VERSE_TOKEN, else (non-Shipping) <DATA_DIR>/verse/bridge.json. */
	static bool Discover(FDiscovery& Out, const FString& DevFileOverride = FString());

	FVerseBridgeClient();
	~FVerseBridgeClient();

	void Start(const FDiscovery& Discovery);
	void Stop();

	/** Drains socket events and runs timers; Now is seconds (FPlatformTime::Seconds). */
	void Tick(double Now);

	/** A command: exactly one reply comes back (a lost link answers internal). */
	FString SendCommand(const FString& Type, TSharedPtr<FJsonObject> Data, FReply OnReply = FReply());
	/** A notice: no id, no reply (lifecycle.state, log, ...). */
	void SendNotice(const FString& Type, TSharedPtr<FJsonObject> Data);

	/** Topics to (re)subscribe after every welcome. */
	void Subscribe(const TArray<FString>& Topics);
	void WatchScreens(const TArray<TPair<FString, int32>>& PanesNearestFirst);
	void WatchChatTails(const TArray<FString>& AgentIds);

	EState GetState() const { return State; }
	bool IsLinked() const { return State == EState::Linked; }
	TSharedPtr<FJsonObject> GetWelcome() const { return Welcome; }
	int64 GetLastSeq() const { return LastSeq; }
	int32 GetAttempts() const { return Attempts; }

	/** Every server frame after the client handled it (lifecycle, panel, gpu and tests). */
	TMulticastDelegate<void(const FVerseBridgeFrame&)> OnFrame;
	TMulticastDelegate<void()> OnLinked;
	TMulticastDelegate<void(int32 /*CloseCode*/)> OnUnlinked;
	TMulticastDelegate<void()> OnLaunchOver;
	/** A server -> Verse command (qa.exec): answer with Reply(Frame.Id, ...). */
	TMulticastDelegate<void(const FVerseBridgeFrame&)> OnServerCommand;

	void Reply(const FString& Re, bool bOk, TSharedPtr<FJsonObject> Result, const FString& ErrorCode = FString(), const FString& Message = FString());

	FVerseRosterFeed Roster;
	FVerseGroupsFeed Groups;
	FVerseScreensFeed Screens;
	FVerseChatTailsFeed ChatTails;
	FVerseProgressionFeed Progression;
	FVerseCompanionFeed Companion;
	FVerseSettingsFeed Settings;

	/** Build info sent in hello. */
	FString BuildVersion = TEXT("0.1.0");
	FString BuildChangelist;
	bool bPreferJsonScreens = false;

	static constexpr double PingInterval = 1.0;
	static constexpr double DeadLink = 5.0;
	static double BackoffFor(int32 Attempt);

private:
	void Connect(double Now);
	void HandleText(const FString& Text, double Now);
	void HandleBinary(const TArray<uint8>& Bytes, double Now);
	void HandleClosed(int32 Code, double Now);
	void Dispatch(const FVerseBridgeFrame& Frame);
	bool CheckBase(const FString& Slot, const FVerseBridgeFrame& Frame);
	void Resync(const FString& Topic, const FString& PaneId = FString());
	void SendFrame(const FVerseBridgeFrame& Frame);
	void FailPending(const FString& Code);
	void Unlink(int32 Code, double Now);

	FVerseWsClient Socket;
	FDiscovery Target;
	EState State = EState::Idle;
	double NextAttemptAt = 0.0;
	double LastFrameAt = 0.0;
	double LastPingAt = 0.0;
	int32 Attempts = 0;
	bool bEverLinked = false;
	int64 LastSeq = 0;
	int32 NextId = 1;
	TSharedPtr<FJsonObject> Welcome;
	TMap<FString, FReply> Pending;
	TMap<FString, int64> LastSeqOf;
	TArray<FString> Topics;
	TArray<TPair<FString, int32>> ScreenWatch;
	TArray<FString> ChatWatch;
	TMap<FString, FString> ResyncInFlight;
};

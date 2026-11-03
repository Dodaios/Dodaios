#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Duel/VerseDuelResultCodec.h"
#include "Duel/VerseDuelResultSink.h"
#include "Templates/SharedPointer.h"

class UVerseEventHub;

// The duel.result reporter (WP21.6, bridge-protocol.md 10, combat-state.md 9.1).
//
// One result per set: every FVerseSetSummary the hub raises on OnSetEnded becomes one
// duel.result. Before it is sent it is written to a pending file, and only a `reply` that says
// stored removes the file. A Verse that dies after a set therefore still has the result on the
// next launch, which sends it on its first `welcome` with end_reason `crash_recovered`. The
// server is idempotent on match_id, so a result sent twice is harmless.

namespace VerseDuel
{
	class FDuelReporter : public TSharedFromThis<FDuelReporter>
	{
	public:
		struct FConfig
		{
			/** Folder of the pending results; created on first write. */
			FString PendingDir;
			/** Unique per process launch; a pending file of another launch is a crash leftover. */
			FString LaunchId;
			FBuildStamp Build;
		};

		/** Pending folder of the running build: `Saved/Verse/Duel/Pending`. */
		static FString DefaultPendingDir();

		explicit FDuelReporter(FConfig InConfig);
		~FDuelReporter();

		/** The bridge connection to send through; null while there is none. */
		void SetSink(TSharedPtr<IDuelResultSink> InSink);

		/** Listen to OnSetEnded of a world's hub (one hub at a time). */
		void Bind(UVerseEventHub& Hub);
		void Unbind();
		/** Unbind only when bound to this hub (a second world must not cut the first one's link). */
		void UnbindFrom(const UVerseEventHub& Hub);

		/** One set ended (finished, or left mid-way): persist it, then send it. */
		void HandleSetEnded(const FVerseSetSummary& Summary);

		/** `welcome` arrived: send every pending result, an earlier launch's as crash_recovered. */
		void HandleWelcome();

		/** Verse or the app is going away: an unfinished set from now on ends with this reason. */
		void NotifyQuitting(EEndReason Reason);

		/** Match ids of the results not yet stored by the server, in send order. */
		TArray<FString> PendingMatchIds() const;

		/** How many results this reporter has sent (every attempt counts). */
		int32 NumSent() const { return SentCount; }

	private:
		struct FPending
		{
			FString MatchId;
			FString LaunchId;
			TSharedPtr<FJsonObject> Data;
			bool bInFlight = false;
		};

		FString PathFor(const FString& MatchId) const;
		void LoadPendingFromDisk();
		bool Persist(const FPending& Pending) const;
		void Forget(const FString& MatchId);
		void Send(FPending& Pending);
		void OnSent(const FString& MatchId, ESendResult Result);

		FConfig Config;
		TSharedPtr<IDuelResultSink> Sink;
		TArray<FPending> Pending;
		/** Match ids the server has confirmed during this launch; a repeat raise is dropped. */
		TSet<FString> Stored;
		TWeakObjectPtr<UVerseEventHub> BoundHub;
		FDelegateHandle SetEndedHandle;
		TOptional<EEndReason> QuitReason;
		bool bLoaded = false;
		int32 SentCount = 0;
	};

	/**
	 * The reporter of this process, created on first use with the default pending folder. The
	 * bridge client (WP17) hands it the sink and calls HandleWelcome on every `welcome`;
	 * UVerseDuelReporterSubsystem binds it to the game world's hub.
	 */
	FDuelReporter& ProcessReporter();
}

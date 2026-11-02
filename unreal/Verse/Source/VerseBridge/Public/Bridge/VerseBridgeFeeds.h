#pragma once

#include "CoreMinimal.h"
#include "Bridge/VerseCellsCodec.h"
#include "Dom/JsonObject.h"

/**
 * Typed feeds of verse.bridge/1 (bridge-protocol.md 4-7, 9, 14). Each feed keeps the
 * server's view of one topic, applies snapshots and partial deltas, and tells listeners
 * what changed. Unknown enum values read as the documented fallback.
 */

struct VERSEBRIDGE_API FVerseAgent
{
	FString AgentId;
	FString Name;
	FString Title;
	FString Tier;
	FString Lifecycle;   // active | paused
	FString RunState;    // paused | waiting | working | idle
	FString WaitingReason;
	FString Duty;        // working | waiting | idle | paused | error
	int32 Level = 1;
	FString Rank;
	FString Look;
	FString Archetype;
	FString Palette;
	TArray<FString> TeamIds;
	FString PaneId;

	static FVerseAgent FromJson(const TSharedPtr<FJsonObject>& O);
};

struct VERSEBRIDGE_API FVersePane
{
	FString PaneId;
	FString WorkspaceId;
	FString Key;
	FString Name;
	FString DisplayName;
	FString Agent;
	FString Title;
	FString Status;      // pending | live | exited | error
	FString Activity;    // starting | working | waiting | asking | failed | exited | stopped | unknown | ""
	double ActivitySince = 0.0;
	bool bWorked = false;
	FString Duty;
	bool bWorkspaceActive = false;
	int32 Cols = 80;
	int32 Rows = 24;

	static FVersePane FromJson(const TSharedPtr<FJsonObject>& O);
};

struct VERSEBRIDGE_API FVerseCommander
{
	int32 Level = 1;
	FString Rank;
	FString Title;
	FString Uniform;
};

DECLARE_MULTICAST_DELEGATE(FVerseFeedChanged);

/** Rows keyed by id, merged from snapshots and partial upserts. */
class VERSEBRIDGE_API FVerseKeyedRows
{
public:
	void Reset() { Rows.Reset(); }
	void Replace(const TArray<TSharedPtr<FJsonValue>>* List, const TCHAR* IdField);
	/** Merges partial rows (id plus changed fields; unknown ids arrive complete). */
	void Upsert(const TArray<TSharedPtr<FJsonValue>>* List, const TCHAR* IdField);
	void Remove(const TArray<TSharedPtr<FJsonValue>>* Ids);
	const TMap<FString, TSharedPtr<FJsonObject>>& Get() const { return Rows; }

private:
	TMap<FString, TSharedPtr<FJsonObject>> Rows;
};

class VERSEBRIDGE_API FVerseRosterFeed
{
public:
	void ApplySnapshot(const TSharedPtr<FJsonObject>& Data);
	void ApplyDelta(const TSharedPtr<FJsonObject>& Data);

	TArray<FVerseAgent> GetAgents() const;
	TArray<FVersePane> GetPanes() const;
	bool FindAgent(const FString& AgentId, FVerseAgent& Out) const;
	bool FindPane(const FString& PaneId, FVersePane& Out) const;
	const FVerseCommander& GetCommander() const { return Commander; }
	bool HasSnapshot() const { return bHasSnapshot; }

	FVerseFeedChanged OnChanged;

private:
	void ReadCommander(const TSharedPtr<FJsonObject>& O);

	FVerseKeyedRows Agents;
	FVerseKeyedRows Panes;
	FVerseCommander Commander;
	bool bHasSnapshot = false;
};

class VERSEBRIDGE_API FVerseGroupsFeed
{
public:
	void ApplySnapshot(const TSharedPtr<FJsonObject>& Data);
	void ApplyDelta(const TSharedPtr<FJsonObject>& Data);
	void ApplyMeeting(const TSharedPtr<FJsonObject>& Data);

	const TMap<FString, TSharedPtr<FJsonObject>>& GetGroups() const { return Groups.Get(); }
	/** The last meetings.update per group. */
	const TMap<FString, TSharedPtr<FJsonObject>>& GetMeetings() const { return Meetings; }

	FVerseFeedChanged OnChanged;
	TMulticastDelegate<void(const FString& /*GroupId*/)> OnMeeting;

private:
	FVerseKeyedRows Groups;
	TMap<FString, TSharedPtr<FJsonObject>> Meetings;
};

/** One desk monitor's grid, rebuilt from cells frames. */
struct VERSEBRIDGE_API FVerseScreen
{
	FString PaneId;
	uint16 Cols = 0;
	uint16 Rows = 0;
	int16 CursorRow = -1;
	int16 CursorCol = -1;
	bool bStyled = true;
	bool bCut = false;
	double At = 0.0;
	/** Row index -> the row's runs (absent rows are blank). */
	TMap<uint16, FVerseCellRow> Lines;
	uint32 LastSeq = 0;
};

class VERSEBRIDGE_API FVerseScreensFeed
{
public:
	/** Applies a screens.watch reply: binds refs to pane ids. */
	void Bind(const TSharedPtr<FJsonObject>& Result);
	void ApplyMeta(const TSharedPtr<FJsonObject>& Data);
	/** Returns false when a delta does not apply on top of the last frame (gap: resync). */
	bool ApplyFrame(const FVerseCellsFrame& Frame, const FString& PaneIdOverride = FString());
	void ApplyGone(const TSharedPtr<FJsonObject>& Data);
	void Reset();

	const FVerseScreen* Find(const FString& PaneId) const { return Screens.Find(PaneId); }
	FString PaneForRef(uint16 Ref) const;

	TMulticastDelegate<void(const FString& /*PaneId*/)> OnFrame;
	TMulticastDelegate<void(const FString& /*PaneId*/, const FString& /*Reason*/)> OnGone;

private:
	TMap<uint16, FString> Refs;
	TMap<FString, FVerseScreen> Screens;
};

struct FVerseChatLine
{
	FString Kind; // user | agent | tool | notice | error
	FString Text;
};

class VERSEBRIDGE_API FVerseChatTailsFeed
{
public:
	void Apply(const TSharedPtr<FJsonObject>& Data);
	const TArray<FVerseChatLine>* Find(const FString& AgentId) const { return Lines.Find(AgentId); }

	TMulticastDelegate<void(const FString& /*AgentId*/)> OnUpdate;

private:
	TMap<FString, TArray<FVerseChatLine>> Lines;
	TMap<FString, FString> Versions;
};

class VERSEBRIDGE_API FVerseProgressionFeed
{
public:
	void ApplySnapshot(const TSharedPtr<FJsonObject>& Data);
	void ApplyAward(const TSharedPtr<FJsonObject>& Data);

	TSharedPtr<FJsonObject> GetSnapshot() const { return Snapshot; }
	int64 GetToldSeq() const { return ToldSeq; }
	void SetToldSeq(int64 Seq) { ToldSeq = FMath::Max(ToldSeq, Seq); }
	int32 LevelOf(const FString& SubjectId) const;

	FVerseFeedChanged OnChanged;
	TMulticastDelegate<void(const TSharedPtr<FJsonObject>& /*Award*/)> OnAward;

private:
	TSharedPtr<FJsonObject> Snapshot;
	int64 ToldSeq = 0;
};

class VERSEBRIDGE_API FVerseCompanionFeed
{
public:
	void Apply(const TSharedPtr<FJsonObject>& Data);
	FString PetId;
	FString Look;
	FString Style;
	FVerseFeedChanged OnChanged;
};

/** Locale and verse.* settings from welcome and settings.changed (contract 3.2, 12). */
class VERSEBRIDGE_API FVerseSettingsFeed
{
public:
	void ApplyWelcome(const TSharedPtr<FJsonObject>& Welcome);
	void ApplyChanged(const TSharedPtr<FJsonObject>& Data);

	/** A localised string by key ("verse.ranks.duty.working"), or the key itself. */
	FString Text(const FString& Key) const;
	FString GetLang() const { return Lang; }
	TSharedPtr<FJsonObject> GetSettings() const { return Settings; }
	FString ReturnKey() const;

	FVerseFeedChanged OnChanged;

private:
	FString Lang = TEXT("en");
	TMap<FString, FString> Strings;
	TSharedPtr<FJsonObject> Settings = MakeShared<FJsonObject>();
};

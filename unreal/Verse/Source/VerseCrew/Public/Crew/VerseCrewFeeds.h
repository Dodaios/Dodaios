#pragma once

#include "Crew/VerseCrewTypes.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/** What one roster frame changed. */
struct VERSECREW_API FVerseCrewRosterChange
{
	TArray<FString> Added;
	TArray<FString> Removed;
	TArray<FString> Changed;
	bool bSnapshot = false;
	bool bCommanderChanged = false;

	bool IsEmpty() const { return Added.Num() == 0 && Removed.Num() == 0 && Changed.Num() == 0 && !bSnapshot && !bCommanderChanged; }
};

struct VERSECREW_API FVerseCrewCommander
{
	FString SubjectId;
	int32 Level = 1;
	FString RankId;
	FString Title;
	FString Uniform;
};

/**
 * The roster topic as Verse holds it (bridge-protocol.md 4.2, 4.3). Rows are kept as the
 * JSON objects the bridge sent and partial upserts merge into them field by field, so a
 * field Verse does not read survives untouched. Members are derived on demand.
 */
class VERSECREW_API FVerseCrewRoster
{
public:
	FVerseCrewRosterChange ApplySnapshot(const TSharedRef<FJsonObject>& Data);
	FVerseCrewRosterChange ApplyDelta(const TSharedRef<FJsonObject>& Data);
	void Reset();

	bool HasSnapshot() const { return bHasSnapshot; }
	int32 NumAgents() const { return Agents.Num(); }
	int32 NumPanes() const { return Panes.Num(); }
	bool Contains(const FString& Id) const { return Agents.Contains(Id) || Panes.Contains(Id); }
	bool IsPane(const FString& Id) const { return Panes.Contains(Id); }
	const FVerseCrewCommander& GetCommander() const { return Commander; }

	/** Every member, agents then panes, with their duty parsed (unknown -> idle). */
	TArray<FVerseCrewMember> Members() const;
	bool FindMember(const FString& Id, FVerseCrewMember& Out) const;

	/** The backend's duty value as sent (for the duty sheet); "" when the id is unknown. */
	FString RawDuty(const FString& Id) const;

private:
	struct FRow
	{
		TSharedRef<FJsonObject> Fields = MakeShared<FJsonObject>();
		int64 ArrivalOrder = 0;
	};

	void Upsert(TMap<FString, FRow>& Rows, TArray<FString>& Order, const TSharedPtr<FJsonObject>& Patch, const TCHAR* IdField, FVerseCrewRosterChange& Change);
	void ReadCommander(const TSharedPtr<FJsonObject>& Object);
	FVerseCrewMember MemberOf(const FRow& Row, bool bPane) const;

	TMap<FString, FRow> Agents;
	TMap<FString, FRow> Panes;
	TArray<FString> AgentOrder;
	TArray<FString> PaneOrder;
	FVerseCrewCommander Commander;
	int64 NextArrival = 0;
	bool bHasSnapshot = false;
};

struct VERSECREW_API FVerseCrewGroup
{
	FString GroupId;
	FString Name;
	TArray<FString> Members;
	FString Lead;
};

struct VERSECREW_API FVerseCrewMeeting
{
	FString GroupId;
	bool bRunning = false;
	int32 Round = 0;
	FString Speaker;
	FString RoomId;
	FString Topic;
};

/** Groups and meetings topics (bridge-protocol.md 7). */
class VERSECREW_API FVerseCrewMeetings
{
public:
	void ApplyGroupsSnapshot(const TSharedRef<FJsonObject>& Data);
	void ApplyGroupsDelta(const TSharedRef<FJsonObject>& Data);
	/** Returns true when the set of rounds or a speaker changed. */
	bool ApplyMeetingUpdate(const TSharedRef<FJsonObject>& Data);
	void Reset();

	/** Each member's part in a running round: the speaker talks, the other members listen. */
	TMap<FString, EVerseCrewRoundPart> Rounds() const;
	/** Group ids with a running round. */
	TArray<FString> RunningGroups() const;
	const FVerseCrewGroup* FindGroup(const FString& GroupId) const { return Groups.Find(GroupId); }
	const FVerseCrewMeeting* FindMeeting(const FString& GroupId) const { return Meetings.Find(GroupId); }
	bool HasGroupsSnapshot() const { return bHasGroups; }

private:
	void UpsertGroup(const TSharedPtr<FJsonObject>& Patch);

	TMap<FString, FVerseCrewGroup> Groups;
	TMap<FString, FVerseCrewMeeting> Meetings;
	bool bHasGroups = false;
};

/** The companion topic (bridge-protocol.md 14): which pet, its look, the overlay style. */
struct VERSECREW_API FVerseCrewCompanion
{
	FString PetId;
	FString Look;
	FString Style;
	bool bKnown = false;

	/** A drone flies when a pet is chosen and the style is not "hidden". */
	bool IsActive() const { return bKnown && !PetId.IsEmpty() && Style != TEXT("hidden"); }
	/** Returns true when anything changed. */
	bool Apply(const TSharedRef<FJsonObject>& Data);
};

/**
 * walk_together metering (bridge-protocol.md 9, port of life/useWorldActions.ts): every
 * WalkMetres the commander walks with the drone within HeelMetres, one action; never two
 * within the server's cooldown.
 */
class VERSECREW_API FVerseCrewWalkTogether
{
public:
	float WalkCm = 5000.f;
	float HeelCm = 250.f;
	float CooldownSeconds = 20.f;

	/** One sample (every 0.5 s); true when an action is due now. */
	bool Sample(const FVector& Commander, const FVector* Drone, double NowSeconds);
	void Reset();

	float TogetherCm() const { return Together; }
	int32 Sent() const { return SentCount; }

private:
	TOptional<FVector2D> Last;
	float Together = 0.f;
	double LastSentSeconds = -1.0e9;
	int32 SentCount = 0;
};

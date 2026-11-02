#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

class IVerseCommandLink;
struct FVerseCommandReply;

/** The station commands of contracts/bridge-protocol.md 11 and 14, as `{type, data}` (WP16.7). */
namespace VerseStationCommands
{
	struct FCommand
	{
		FString Type;
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
	};

	VERSEUI_API FCommand AgentsOpenList();
	VERSEUI_API FCommand GroupOpen(const FString& GroupId);
	VERSEUI_API FCommand SimulatorOpen(const FString& Programme);
	VERSEUI_API FCommand IdeOpen();
	VERSEUI_API FCommand LauncherOptions();
	VERSEUI_API FCommand LauncherStart(const FString& WorkspaceId, const FString& Agent, int32 Count, const FString& Brief);
	VERSEUI_API FCommand LauncherCancel();
	/** The arrivals desk creates an officer with the app's defaults: no name, title or figure. */
	VERSEUI_API FCommand AgentCreate();
}

/** A simulator programme (today's arcade list, frontend arcade/arcadeGames.ts). */
struct FVerseProgramme
{
	FString Id;
	FString Title;
};

/** One choice of the launcher (workspace or CLI agent). */
struct FVerseLauncherOption
{
	FString Id;
	FString Name;
	/** Workspace: the active one; agent: installed. */
	bool bFlag = false;
};

enum class EVerseStationPanel : uint8
{
	None,
	Launcher,
	Simulator
};

enum class EVerseLauncherPhase : uint8
{
	Loading,
	Ready,
	Starting,
	Done
};

/** The launcher panel (parity X-03 to X-06). */
struct FVerseLauncherState
{
	EVerseLauncherPhase Phase = EVerseLauncherPhase::Loading;
	TArray<FVerseLauncherOption> Workspaces;
	TArray<FVerseLauncherOption> Agents;
	int32 Workspace = INDEX_NONE;
	int32 Agent = INDEX_NONE;
	/** 1 to 4 (LauncherPanel.tsx). */
	int32 Count = 1;
	FString Brief;
	/** The status line under the form (starting, started, failed, none, no workspace, busy). */
	FString Line;
};

/** A group as the briefing table sees it (groups.snapshot, meetings.update). */
struct FVerseGroupInfo
{
	FString GroupId;
	FString Name;
	bool bInSession = false;
};

/**
 * What every station kind does when used (WP16.7), without any widget: commands, the notice line,
 * the launcher and simulator panels. The Slate view and the tests drive the same object.
 */
class VERSEUI_API FVerseStationController
{
public:
	TFunction<IVerseCommandLink*()> GetLink;
	TFunction<void(const FString&)> Notice;
	TFunction<FString(const FString&, const FString&)> Localize;
	/** Station error text for a reply code (UVerseStationSubsystem::ErrorText). */
	TFunction<FString(const FString&)> ErrorText;

	/** WP21's service record view opens on "record", "ladder" or "rewards" (parity S-04, S-05). */
	TFunction<void(FName Tab)> OpenServiceRecord;
	/** WP15's mess call (parity S-06) and WP12's lift (parity S-10). */
	TFunction<void(FName StationId)> MessCall;
	TFunction<void(FName StationId)> OpenLift;

	/** FVerseStationUsedEvent from the hub. Room is the station's room id. */
	void HandleStationUsed(FName Kind, FName StationId, const FString& Room);

	/** groups.snapshot, groups.delta and meetings.update feed the briefing table. */
	void HandleBridgeFrame(const FJsonObject& Envelope);
	const TArray<FVerseGroupInfo>& Groups() const { return GroupList; }
	/** The team in session if there is one, else the first team; null when none (parity S-03). */
	const FVerseGroupInfo* TeamAtTable() const;

	EVerseStationPanel Panel() const { return OpenPanel; }
	void ClosePanel();

	const FVerseLauncherState& Launcher() const { return LauncherState; }
	void LauncherSelectWorkspace(int32 Index);
	void LauncherSelectAgent(int32 Index);
	void LauncherSetCount(int32 Count);
	void LauncherSetBrief(const FString& Brief);
	bool LauncherStart();
	void LauncherOpenIde();

	static const TArray<FVerseProgramme>& Programmes();
	bool OpenProgramme(const FString& ProgrammeId);

	/** True while a command of this type waits for its reply (a second one is not sent). */
	bool IsInFlight(const FString& Type) const { return InFlight.Contains(Type); }

private:
	bool Send(const VerseStationCommands::FCommand& Command, TFunction<void(const FVerseCommandReply&)> OnReply);
	/** Open commands: on ok the app takes the foreground; on error one notice. */
	bool SendOpen(const VerseStationCommands::FCommand& Command);
	void OpenLauncher();
	void ShowError(const FVerseCommandReply& Reply);
	FString Text(const TCHAR* Key, const TCHAR* Fallback) const;

	EVerseStationPanel OpenPanel = EVerseStationPanel::None;
	FVerseLauncherState LauncherState;
	TArray<FVerseGroupInfo> GroupList;
	TSet<FString> InFlight;
	/** Bumped when a panel closes, so a late launcher reply does not reopen it. */
	int32 PanelGeneration = 0;
	TSharedRef<int32> Alive = MakeShared<int32>(0);
};

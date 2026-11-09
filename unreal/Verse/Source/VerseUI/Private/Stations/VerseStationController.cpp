#include "Stations/VerseStationController.h"

#include "Dom/JsonValue.h"
#include "Stations/VerseCommandLink.h"

namespace VerseStationCommands
{
	FCommand AgentsOpenList() { return {TEXT("agents.open_list")}; }

	FCommand GroupOpen(const FString& GroupId)
	{
		FCommand C{TEXT("group.open")};
		C.Data->SetStringField(TEXT("group_id"), GroupId);
		return C;
	}

	FCommand SimulatorOpen(const FString& Programme)
	{
		FCommand C{TEXT("simulator.open")};
		C.Data->SetStringField(TEXT("programme"), Programme);
		return C;
	}

	FCommand IdeOpen() { return {TEXT("ide.open")}; }
	FCommand LauncherOptions() { return {TEXT("launcher.options")}; }

	FCommand LauncherStart(const FString& WorkspaceId, const FString& Agent, int32 Count, const FString& Brief)
	{
		FCommand C{TEXT("launcher.start")};
		if (!WorkspaceId.IsEmpty())
		{
			C.Data->SetStringField(TEXT("workspace_id"), WorkspaceId);
		}
		TSharedRef<FJsonObject> Entry = MakeShared<FJsonObject>();
		Entry->SetStringField(TEXT("agent"), Agent);
		Entry->SetNumberField(TEXT("count"), Count);
		TArray<TSharedPtr<FJsonValue>> Agents;
		Agents.Add(MakeShared<FJsonValueObject>(Entry));
		C.Data->SetArrayField(TEXT("agents"), Agents);
		C.Data->SetStringField(TEXT("brief"), Brief);
		return C;
	}

	FCommand LauncherCancel() { return {TEXT("launcher.cancel")}; }
	FCommand AgentCreate() { return {TEXT("agent.create")}; }
}

namespace
{
	FString Fill(FString Text, const TCHAR* Name, const FString& Value)
	{
		return Text.Replace(*FString::Printf(TEXT("{%s}"), Name), *Value);
	}
}

FString FVerseStationController::Text(const TCHAR* Key, const TCHAR* Fallback) const
{
	return Localize ? Localize(Key, Fallback) : FString(Fallback);
}

const TArray<FVerseProgramme>& FVerseStationController::Programmes()
{
	static const TArray<FVerseProgramme> List = {
		{TEXT("asteroid-run"), TEXT("Asteroid Run")}, {TEXT("neon-snake"), TEXT("Neon Snake")},
		{TEXT("brick-breaker"), TEXT("Brick Breaker")}, {TEXT("paddle-duel"), TEXT("Paddle Duel")},
		{TEXT("block-drop"), TEXT("Block Drop")}, {TEXT("maze-muncher"), TEXT("Maze Muncher")},
		{TEXT("desert-dash"), TEXT("Desert Dash")}, {TEXT("pixel-raiders"), TEXT("Pixel Raiders")},
		{TEXT("road-hopper"), TEXT("Road Hopper")}, {TEXT("city-defense"), TEXT("City Defense")},
	};
	return List;
}

bool FVerseStationController::Send(const VerseStationCommands::FCommand& Command, TFunction<void(const FVerseCommandReply&)> OnReply)
{
	IVerseCommandLink* Link = GetLink ? GetLink() : nullptr;
	if (!Link || InFlight.Contains(Command.Type))
	{
		return false;
	}
	InFlight.Add(Command.Type);
	const TWeakPtr<int32> Weak = Alive;
	const FString Type = Command.Type;
	Link->SendCommand(Command.Type, Command.Data, [this, Weak, Type, OnReply = MoveTemp(OnReply)](const FVerseCommandReply& Reply)
	{
		if (!Weak.IsValid())
		{
			return;
		}
		InFlight.Remove(Type);
		if (OnReply)
		{
			OnReply(Reply);
		}
	});
	return true;
}

void FVerseStationController::ShowError(const FVerseCommandReply& Reply)
{
	if (Notice)
	{
		Notice(ErrorText ? ErrorText(Reply.ErrorCode) : Reply.ErrorCode);
	}
}

bool FVerseStationController::SendOpen(const VerseStationCommands::FCommand& Command)
{
	return Send(Command, [this](const FVerseCommandReply& Reply)
	{
		if (Reply.bOk)
		{
			OpenPanel = EVerseStationPanel::None;
			if (IVerseCommandLink* Link = GetLink ? GetLink() : nullptr)
			{
				Link->ReturnToApp(TEXT("station"));
			}
		}
		else
		{
			ShowError(Reply);
		}
	});
}

void FVerseStationController::HandleStationUsed(FName Kind, FName StationId, const FString& Room)
{
	const FString K = Kind.ToString();
	if (K == TEXT("agents_list"))
	{
		SendOpen(VerseStationCommands::AgentsOpenList());
	}
	else if (K == TEXT("team"))
	{
		if (const FVerseGroupInfo* Team = TeamAtTable())
		{
			SendOpen(VerseStationCommands::GroupOpen(Team->GroupId));
		}
		else if (Notice)
		{
			Notice(Text(TEXT("verse.notice.no_team"), TEXT("No team meets at this table yet. Create one in the crew list.")));
		}
	}
	else if (K == TEXT("service_record"))
	{
		if (OpenServiceRecord)
		{
			OpenServiceRecord(Room.Contains(TEXT("records")) ? FName(TEXT("ladder")) : FName(TEXT("record")));
		}
	}
	else if (K == TEXT("quartermaster"))
	{
		if (OpenServiceRecord)
		{
			OpenServiceRecord(FName(TEXT("rewards")));
		}
	}
	else if (K == TEXT("mess_call"))
	{
		if (MessCall)
		{
			MessCall(StationId);
		}
	}
	else if (K == TEXT("games"))
	{
		OpenPanel = EVerseStationPanel::Simulator;
	}
	else if (K == TEXT("coding_launcher"))
	{
		OpenLauncher();
	}
	else if (K == TEXT("create_agent"))
	{
		Send(VerseStationCommands::AgentCreate(), [this](const FVerseCommandReply& Reply)
		{
			// The new officer arrives in roster.delta; only a failure needs words. A declined
			// create flow (conflict) is no error (parity S-09).
			if (!Reply.bOk && Reply.ErrorCode != TEXT("conflict"))
			{
				ShowError(Reply);
			}
		});
	}
	else if (K == TEXT("lift"))
	{
		if (OpenLift)
		{
			OpenLift(StationId);
		}
	}
	// "armoury": WP18's armoury view listens to the hub itself.
}

const FVerseGroupInfo* FVerseStationController::TeamAtTable() const
{
	for (const FVerseGroupInfo& G : GroupList)
	{
		if (G.bInSession)
		{
			return &G;
		}
	}
	return GroupList.Num() > 0 ? &GroupList[0] : nullptr;
}

void FVerseStationController::HandleBridgeFrame(const FJsonObject& Envelope)
{
	FString Type;
	Envelope.TryGetStringField(TEXT("type"), Type);
	const TSharedPtr<FJsonObject>* Data = nullptr;
	if (!Envelope.TryGetObjectField(TEXT("data"), Data) || !Data)
	{
		return;
	}
	auto ReadGroups = [](const FJsonObject& Holder, TArray<FVerseGroupInfo>& Out)
	{
		const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
		if (!Holder.TryGetArrayField(TEXT("groups"), Rows))
		{
			return;
		}
		for (const TSharedPtr<FJsonValue>& V : *Rows)
		{
			const TSharedPtr<FJsonObject>* O = nullptr;
			FVerseGroupInfo G;
			if (V.IsValid() && V->TryGetObject(O) && (*O)->TryGetStringField(TEXT("group_id"), G.GroupId))
			{
				(*O)->TryGetStringField(TEXT("name"), G.Name);
				Out.Add(G);
			}
		}
	};
	if (Type == TEXT("groups.snapshot"))
	{
		TArray<FVerseGroupInfo> Next;
		ReadGroups(**Data, Next);
		for (FVerseGroupInfo& G : Next)
		{
			if (const FVerseGroupInfo* Old = GroupList.FindByPredicate([&G](const FVerseGroupInfo& O) { return O.GroupId == G.GroupId; }))
			{
				G.bInSession = Old->bInSession;
			}
		}
		GroupList = MoveTemp(Next);
	}
	else if (Type == TEXT("groups.delta"))
	{
		const TSharedPtr<FJsonObject>* Upsert = nullptr;
		if ((*Data)->TryGetObjectField(TEXT("upsert"), Upsert) && Upsert)
		{
			TArray<FVerseGroupInfo> Rows;
			ReadGroups(**Upsert, Rows);
			for (const FVerseGroupInfo& Row : Rows)
			{
				if (FVerseGroupInfo* Have = GroupList.FindByPredicate([&Row](const FVerseGroupInfo& O) { return O.GroupId == Row.GroupId; }))
				{
					if (!Row.Name.IsEmpty())
					{
						Have->Name = Row.Name;
					}
				}
				else
				{
					GroupList.Add(Row);
				}
			}
		}
		const TSharedPtr<FJsonObject>* Remove = nullptr;
		const TArray<TSharedPtr<FJsonValue>>* Ids = nullptr;
		if ((*Data)->TryGetObjectField(TEXT("remove"), Remove) && Remove && (*Remove)->TryGetArrayField(TEXT("groups"), Ids))
		{
			for (const TSharedPtr<FJsonValue>& Id : *Ids)
			{
				const FString Gone = Id.IsValid() ? Id->AsString() : FString();
				GroupList.RemoveAll([&Gone](const FVerseGroupInfo& G) { return G.GroupId == Gone; });
			}
		}
	}
	else if (Type == TEXT("meetings.update"))
	{
		FString GroupId;
		bool bRunning = false;
		(*Data)->TryGetStringField(TEXT("group_id"), GroupId);
		(*Data)->TryGetBoolField(TEXT("running"), bRunning);
		if (FVerseGroupInfo* G = GroupList.FindByPredicate([&GroupId](const FVerseGroupInfo& O) { return O.GroupId == GroupId; }))
		{
			G->bInSession = bRunning;
		}
	}
}

void FVerseStationController::ClosePanel()
{
	// Closing the launcher while it starts panes stops the batch (parity X-04).
	if (OpenPanel == EVerseStationPanel::Launcher && LauncherState.Phase == EVerseLauncherPhase::Starting)
	{
		Send(VerseStationCommands::LauncherCancel(), nullptr);
	}
	OpenPanel = EVerseStationPanel::None;
	++PanelGeneration;
}

void FVerseStationController::OpenLauncher()
{
	OpenPanel = EVerseStationPanel::Launcher;
	if (LauncherState.Phase == EVerseLauncherPhase::Starting)
	{
		return;
	}
	LauncherState = FVerseLauncherState();
	const int32 Gen = ++PanelGeneration;
	Send(VerseStationCommands::LauncherOptions(), [this, Gen](const FVerseCommandReply& Reply)
	{
		if (Gen != PanelGeneration)
		{
			return;
		}
		if (!Reply.bOk || !Reply.Result.IsValid())
		{
			LauncherState.Phase = EVerseLauncherPhase::Ready;
			LauncherState.Line = ErrorText ? ErrorText(Reply.ErrorCode) : Reply.ErrorCode;
			return;
		}
		auto Read = [&Reply](const TCHAR* Field, const TCHAR* IdField, const TCHAR* NameField, const TCHAR* FlagField, TArray<FVerseLauncherOption>& Out)
		{
			const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
			if (!Reply.Result->TryGetArrayField(Field, Rows))
			{
				return;
			}
			for (const TSharedPtr<FJsonValue>& V : *Rows)
			{
				const TSharedPtr<FJsonObject>* O = nullptr;
				FVerseLauncherOption Opt;
				if (V.IsValid() && V->TryGetObject(O) && (*O)->TryGetStringField(IdField, Opt.Id))
				{
					(*O)->TryGetStringField(NameField, Opt.Name);
					(*O)->TryGetBoolField(FlagField, Opt.bFlag);
					Out.Add(Opt);
				}
			}
		};
		Read(TEXT("workspaces"), TEXT("workspace_id"), TEXT("name"), TEXT("active"), LauncherState.Workspaces);
		Read(TEXT("agents"), TEXT("agent"), TEXT("display_name"), TEXT("available"), LauncherState.Agents);
		LauncherState.Workspace = LauncherState.Workspaces.IndexOfByPredicate([](const FVerseLauncherOption& O) { return O.bFlag; });
		if (LauncherState.Workspace == INDEX_NONE && LauncherState.Workspaces.Num() > 0)
		{
			LauncherState.Workspace = 0;
		}
		LauncherState.Agent = LauncherState.Agents.IndexOfByPredicate([](const FVerseLauncherOption& O) { return O.bFlag; });
		LauncherState.Phase = EVerseLauncherPhase::Ready;
		if (LauncherState.Agent == INDEX_NONE)
		{
			LauncherState.Line = Text(TEXT("verse.launcher.none"), TEXT("No coding agent is installed."));
		}
		else if (LauncherState.Workspace == INDEX_NONE)
		{
			LauncherState.Line = Text(TEXT("verse.launcher.no_workspace"), TEXT("Open a workspace in the IDE first."));
		}
	});
}

void FVerseStationController::LauncherSelectWorkspace(int32 Index)
{
	if (LauncherState.Workspaces.IsValidIndex(Index))
	{
		LauncherState.Workspace = Index;
	}
}

void FVerseStationController::LauncherSelectAgent(int32 Index)
{
	if (LauncherState.Agents.IsValidIndex(Index) && LauncherState.Agents[Index].bFlag)
	{
		LauncherState.Agent = Index;
	}
}

void FVerseStationController::LauncherSetCount(int32 Count)
{
	LauncherState.Count = FMath::Clamp(Count, 1, 4);
}

void FVerseStationController::LauncherSetBrief(const FString& Brief)
{
	LauncherState.Brief = Brief;
}

bool FVerseStationController::LauncherStart()
{
	FVerseLauncherState& S = LauncherState;
	if (S.Phase != EVerseLauncherPhase::Ready && S.Phase != EVerseLauncherPhase::Done)
	{
		return false;
	}
	if (!S.Agents.IsValidIndex(S.Agent) || !S.Workspaces.IsValidIndex(S.Workspace))
	{
		return false;
	}
	const int32 Count = S.Count;
	const bool bSent = Send(
		VerseStationCommands::LauncherStart(S.Workspaces[S.Workspace].Id, S.Agents[S.Agent].Id, Count, S.Brief),
		[this, Count](const FVerseCommandReply& Reply)
		{
			FVerseLauncherState& L = LauncherState;
			if (!Reply.bOk)
			{
				// busy: another batch runs; shown once, never retried (parity X-04, A16.5).
				L.Phase = EVerseLauncherPhase::Ready;
				L.Line = ErrorText ? ErrorText(Reply.ErrorCode) : Reply.ErrorCode;
				return;
			}
			int32 Submitted = 0;
			int32 Failed = 0;
			const TArray<TSharedPtr<FJsonValue>>* Panes = nullptr;
			if (Reply.Result.IsValid() && Reply.Result->TryGetArrayField(TEXT("panes"), Panes))
			{
				for (const TSharedPtr<FJsonValue>& V : *Panes)
				{
					const TSharedPtr<FJsonObject>* O = nullptr;
					bool bSubmitted = false;
					if (V.IsValid() && V->TryGetObject(O))
					{
						const TSharedPtr<FJsonValue> Field = (*O)->TryGetField(TEXT("submitted"));
						if (Field.IsValid() && !Field->IsNull() && Field->TryGetBool(bSubmitted))
						{
							bSubmitted ? ++Submitted : ++Failed;
						}
						else
						{
							// null: the pane opened but the brief's delivery is unknown; it is running.
							++Submitted;
						}
					}
				}
			}
			L.Phase = EVerseLauncherPhase::Done;
			if (Failed > 0)
			{
				L.Line = Fill(Text(TEXT("verse.launcher.failed"), TEXT("Could not start: {reason}")), TEXT("reason"),
					FString::Printf(TEXT("%d/%d"), Failed, Count));
			}
			else
			{
				L.Line = Fill(Text(TEXT("verse.launcher.started"), TEXT("{count} started.")), TEXT("count"), FString::FromInt(Submitted));
			}
		});
	if (bSent)
	{
		S.Phase = EVerseLauncherPhase::Starting;
		S.Line = Fill(Text(TEXT("verse.launcher.starting"), TEXT("Starting {count}…")), TEXT("count"), FString::FromInt(Count));
	}
	return bSent;
}

void FVerseStationController::LauncherOpenIde()
{
	SendOpen(VerseStationCommands::IdeOpen());
}

bool FVerseStationController::OpenProgramme(const FString& ProgrammeId)
{
	if (!Programmes().ContainsByPredicate([&ProgrammeId](const FVerseProgramme& P) { return P.Id == ProgrammeId; }))
	{
		return false;
	}
	return SendOpen(VerseStationCommands::SimulatorOpen(ProgrammeId));
}

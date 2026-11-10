#include "Bridge/VerseBridgeFeeds.h"

#include "Bridge/VerseBridgeCodec.h"

using namespace VerseBridgeJson;

namespace
{
	TArray<FString> Strings(const TSharedPtr<FJsonObject>& O, const TCHAR* Field)
	{
		TArray<FString> Out;
		if (const TArray<TSharedPtr<FJsonValue>>* A = Arr(O, Field))
		{
			for (const TSharedPtr<FJsonValue>& V : *A)
			{
				Out.Add(V->AsString());
			}
		}
		return Out;
	}
}

FVerseAgent FVerseAgent::FromJson(const TSharedPtr<FJsonObject>& O)
{
	FVerseAgent A;
	A.AgentId = Str(O, TEXT("agent_id"));
	A.Name = Str(O, TEXT("name"));
	A.Title = Str(O, TEXT("title"));
	A.Tier = Str(O, TEXT("tier"));
	A.Lifecycle = Enum(O, TEXT("lifecycle"), {TEXT("active"), TEXT("paused")}, TEXT("active"));
	A.RunState = Enum(O, TEXT("run_state"), {TEXT("paused"), TEXT("waiting"), TEXT("working"), TEXT("idle")}, TEXT("idle"));
	A.WaitingReason = Str(O, TEXT("waiting_reason"));
	A.Duty = Enum(O, TEXT("duty"), {TEXT("working"), TEXT("waiting"), TEXT("idle"), TEXT("paused"), TEXT("error")}, TEXT("idle"));
	A.Level = int32(Int(O, TEXT("level"), 1));
	A.Rank = Str(O, TEXT("rank"), TEXT("recruit"));
	A.Look = Str(O, TEXT("look"));
	const TSharedPtr<FJsonObject> Figure = Obj(O, TEXT("figure"));
	A.Archetype = Str(Figure, TEXT("archetype"));
	A.Palette = Str(Figure, TEXT("palette"));
	A.TeamIds = Strings(O, TEXT("team_ids"));
	A.PaneId = Str(O, TEXT("pane"));
	return A;
}

FVersePane FVersePane::FromJson(const TSharedPtr<FJsonObject>& O)
{
	FVersePane P;
	P.PaneId = Str(O, TEXT("pane_id"));
	P.WorkspaceId = Str(O, TEXT("workspace_id"));
	P.Key = Str(O, TEXT("key"));
	P.Name = Str(O, TEXT("name"));
	P.DisplayName = Str(O, TEXT("display_name"));
	P.Agent = Str(O, TEXT("agent"));
	P.Title = Str(O, TEXT("title"));
	P.Status = Enum(O, TEXT("status"), {TEXT("pending"), TEXT("live"), TEXT("exited"), TEXT("error")}, TEXT("pending"));
	P.Activity = Enum(O, TEXT("activity"),
		{TEXT("starting"), TEXT("working"), TEXT("waiting"), TEXT("asking"), TEXT("failed"), TEXT("exited"), TEXT("stopped"), TEXT("unknown"), TEXT("")},
		TEXT("unknown"));
	P.ActivitySince = Num(O, TEXT("activity_since"));
	P.bWorked = Bool(O, TEXT("worked"));
	P.Duty = Enum(O, TEXT("duty"), {TEXT("working"), TEXT("waiting"), TEXT("idle"), TEXT("paused"), TEXT("error")}, TEXT("idle"));
	P.bWorkspaceActive = Bool(O, TEXT("workspace_active"));
	P.Cols = int32(Int(O, TEXT("cols"), 80));
	P.Rows = int32(Int(O, TEXT("rows"), 24));
	return P;
}

void FVerseKeyedRows::Replace(const TArray<TSharedPtr<FJsonValue>>* List, const TCHAR* IdField)
{
	Rows.Reset();
	Upsert(List, IdField);
}

void FVerseKeyedRows::Upsert(const TArray<TSharedPtr<FJsonValue>>* List, const TCHAR* IdField)
{
	if (!List)
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : *List)
	{
		const TSharedPtr<FJsonObject> Row = V.IsValid() ? V->AsObject() : nullptr;
		const FString Id = Str(Row, IdField);
		if (Id.IsEmpty())
		{
			continue;
		}
		TSharedPtr<FJsonObject>& Held = Rows.FindOrAdd(Id);
		if (!Held.IsValid())
		{
			Held = MakeShared<FJsonObject>();
		}
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Field : Row->Values)
		{
			Held->Values.Add(Field.Key, Field.Value);
		}
	}
}

void FVerseKeyedRows::Remove(const TArray<TSharedPtr<FJsonValue>>* Ids)
{
	if (!Ids)
	{
		return;
	}
	for (const TSharedPtr<FJsonValue>& V : *Ids)
	{
		Rows.Remove(V->AsString());
	}
}

void FVerseRosterFeed::ReadCommander(const TSharedPtr<FJsonObject>& O)
{
	if (!O.IsValid())
	{
		return;
	}
	Commander.Level = int32(Int(O, TEXT("level"), 1));
	Commander.Rank = Str(O, TEXT("rank"), TEXT("recruit"));
	Commander.Title = Str(O, TEXT("title"));
	Commander.Uniform = Str(O, TEXT("uniform"), TEXT("standard"));
}

void FVerseRosterFeed::ApplySnapshot(const TSharedPtr<FJsonObject>& Data)
{
	Agents.Replace(Arr(Data, TEXT("agents")), TEXT("agent_id"));
	Panes.Replace(Arr(Data, TEXT("panes")), TEXT("pane_id"));
	ReadCommander(Obj(Data, TEXT("commander")));
	bHasSnapshot = true;
	OnChanged.Broadcast();
}

void FVerseRosterFeed::ApplyDelta(const TSharedPtr<FJsonObject>& Data)
{
	const TSharedPtr<FJsonObject> Up = Obj(Data, TEXT("upsert"));
	const TSharedPtr<FJsonObject> Rm = Obj(Data, TEXT("remove"));
	Agents.Upsert(Arr(Up, TEXT("agents")), TEXT("agent_id"));
	Panes.Upsert(Arr(Up, TEXT("panes")), TEXT("pane_id"));
	Agents.Remove(Arr(Rm, TEXT("agents")));
	Panes.Remove(Arr(Rm, TEXT("panes")));
	ReadCommander(Obj(Data, TEXT("commander")));
	OnChanged.Broadcast();
}

TArray<FVerseAgent> FVerseRosterFeed::GetAgents() const
{
	TArray<FVerseAgent> Out;
	for (const TPair<FString, TSharedPtr<FJsonObject>>& P : Agents.Get())
	{
		Out.Add(FVerseAgent::FromJson(P.Value));
	}
	Out.Sort([](const FVerseAgent& A, const FVerseAgent& B) { return A.AgentId < B.AgentId; });
	return Out;
}

TArray<FVersePane> FVerseRosterFeed::GetPanes() const
{
	TArray<FVersePane> Out;
	for (const TPair<FString, TSharedPtr<FJsonObject>>& P : Panes.Get())
	{
		Out.Add(FVersePane::FromJson(P.Value));
	}
	Out.Sort([](const FVersePane& A, const FVersePane& B) { return A.PaneId < B.PaneId; });
	return Out;
}

bool FVerseRosterFeed::FindAgent(const FString& AgentId, FVerseAgent& Out) const
{
	if (const TSharedPtr<FJsonObject>* Row = Agents.Get().Find(AgentId))
	{
		Out = FVerseAgent::FromJson(*Row);
		return true;
	}
	return false;
}

bool FVerseRosterFeed::FindPane(const FString& PaneId, FVersePane& Out) const
{
	if (const TSharedPtr<FJsonObject>* Row = Panes.Get().Find(PaneId))
	{
		Out = FVersePane::FromJson(*Row);
		return true;
	}
	return false;
}

void FVerseGroupsFeed::ApplySnapshot(const TSharedPtr<FJsonObject>& Data)
{
	Groups.Replace(Arr(Data, TEXT("groups")), TEXT("group_id"));
	OnChanged.Broadcast();
}

void FVerseGroupsFeed::ApplyDelta(const TSharedPtr<FJsonObject>& Data)
{
	Groups.Upsert(Arr(Obj(Data, TEXT("upsert")), TEXT("groups")), TEXT("group_id"));
	Groups.Remove(Arr(Obj(Data, TEXT("remove")), TEXT("groups")));
	OnChanged.Broadcast();
}

void FVerseGroupsFeed::ApplyMeeting(const TSharedPtr<FJsonObject>& Data)
{
	const FString Id = Str(Data, TEXT("group_id"));
	if (Id.IsEmpty())
	{
		return;
	}
	Meetings.Add(Id, Data);
	OnMeeting.Broadcast(Id);
}

void FVerseScreensFeed::Bind(const TSharedPtr<FJsonObject>& Result)
{
	Refs.Reset();
	if (const TArray<TSharedPtr<FJsonValue>>* Bound = Arr(Result, TEXT("bound")))
	{
		for (const TSharedPtr<FJsonValue>& V : *Bound)
		{
			const TSharedPtr<FJsonObject> B = V->AsObject();
			Refs.Add(uint16(Int(B, TEXT("ref"))), Str(B, TEXT("pane_id")));
		}
	}
	TArray<FString> Gone;
	for (const TPair<FString, FVerseScreen>& S : Screens)
	{
		bool bKept = false;
		for (const TPair<uint16, FString>& R : Refs)
		{
			bKept |= R.Value == S.Key;
		}
		if (!bKept)
		{
			Gone.Add(S.Key);
		}
	}
	for (const FString& G : Gone)
	{
		Screens.Remove(G);
	}
}

FString FVerseScreensFeed::PaneForRef(uint16 Ref) const
{
	const FString* P = Refs.Find(Ref);
	return P ? *P : FString();
}

void FVerseScreensFeed::ApplyMeta(const TSharedPtr<FJsonObject>& Data)
{
	const FString PaneId = Str(Data, TEXT("pane_id"));
	if (PaneId.IsEmpty())
	{
		return;
	}
	const uint16 Ref = uint16(Int(Data, TEXT("ref")));
	if (Ref)
	{
		Refs.Add(Ref, PaneId);
	}
	FVerseScreen& S = Screens.FindOrAdd(PaneId);
	S.PaneId = PaneId;
	S.bStyled = Str(Data, TEXT("style"), TEXT("styled")) != TEXT("plain");
	S.bCut = Bool(Data, TEXT("cut"));
	S.At = Num(Data, TEXT("at"));
}

bool FVerseScreensFeed::ApplyFrame(const FVerseCellsFrame& Frame, const FString& PaneIdOverride)
{
	const FString PaneId = PaneIdOverride.IsEmpty() ? PaneForRef(Frame.Ref) : PaneIdOverride;
	if (PaneId.IsEmpty())
	{
		return true;
	}
	FVerseScreen& S = Screens.FindOrAdd(PaneId);
	if (!Frame.bSnapshot && (S.LastSeq == 0 || Frame.Base != S.LastSeq))
	{
		return false;
	}
	S.PaneId = PaneId;
	if (Frame.bSnapshot)
	{
		S.Lines.Reset();
	}
	S.Cols = Frame.Cols;
	S.Rows = Frame.Rows;
	S.CursorRow = Frame.CursorRow;
	S.CursorCol = Frame.CursorCol;
	for (const FVerseCellRow& Row : Frame.RowsChanged)
	{
		if (Row.Runs.Num() == 0)
		{
			S.Lines.Remove(Row.Row);
		}
		else
		{
			S.Lines.Add(Row.Row, Row);
		}
	}
	TArray<uint16> Outside;
	for (const TPair<uint16, FVerseCellRow>& L : S.Lines)
	{
		if (L.Key >= S.Rows)
		{
			Outside.Add(L.Key);
		}
	}
	for (uint16 R : Outside)
	{
		S.Lines.Remove(R);
	}
	S.LastSeq = Frame.Seq;
	OnFrame.Broadcast(PaneId);
	return true;
}

void FVerseScreensFeed::ApplyGone(const TSharedPtr<FJsonObject>& Data)
{
	const FString PaneId = Str(Data, TEXT("pane_id"));
	Screens.Remove(PaneId);
	OnGone.Broadcast(PaneId, Str(Data, TEXT("reason"), TEXT("closed")));
}

void FVerseScreensFeed::Reset()
{
	Refs.Reset();
	Screens.Reset();
}

void FVerseChatTailsFeed::Apply(const TSharedPtr<FJsonObject>& Data)
{
	const FString Agent = Str(Data, TEXT("agent_id"));
	const FString Version = Str(Data, TEXT("version"));
	if (Agent.IsEmpty() || (Versions.Contains(Agent) && Versions[Agent] == Version && !Version.IsEmpty()))
	{
		return;
	}
	Versions.Add(Agent, Version);
	TArray<FVerseChatLine>& Out = Lines.FindOrAdd(Agent);
	Out.Reset();
	if (const TArray<TSharedPtr<FJsonValue>>* L = Arr(Data, TEXT("lines")))
	{
		for (const TSharedPtr<FJsonValue>& V : *L)
		{
			const TSharedPtr<FJsonObject> Line = V->AsObject();
			Out.Add({Enum(Line, TEXT("kind"), {TEXT("user"), TEXT("agent"), TEXT("tool"), TEXT("notice"), TEXT("error")}, TEXT("notice")),
				Str(Line, TEXT("text"))});
		}
	}
	OnUpdate.Broadcast(Agent);
}

void FVerseProgressionFeed::ApplySnapshot(const TSharedPtr<FJsonObject>& Data)
{
	Snapshot = Data;
	ToldSeq = FMath::Max(ToldSeq, Int(Data, TEXT("told_seq")));
	OnChanged.Broadcast();
}

void FVerseProgressionFeed::ApplyAward(const TSharedPtr<FJsonObject>& Data)
{
	if (Snapshot.IsValid())
	{
		const FString Subject = Str(Data, TEXT("subject_id"));
		if (const TArray<TSharedPtr<FJsonValue>>* Subjects = Arr(Snapshot, TEXT("subjects")))
		{
			for (const TSharedPtr<FJsonValue>& V : *Subjects)
			{
				const TSharedPtr<FJsonObject> S = V->AsObject();
				if (Str(S, TEXT("subject_id")) == Subject)
				{
					S->SetNumberField(TEXT("level"), double(Int(Data, TEXT("level"), 1)));
					S->SetNumberField(TEXT("total_xp"), double(Int(Data, TEXT("total_xp"))));
					S->SetStringField(TEXT("title"), Str(Data, TEXT("title")));
				}
			}
		}
		Snapshot->SetNumberField(TEXT("latest_seq"), double(FMath::Max(Int(Snapshot, TEXT("latest_seq")), Int(Data, TEXT("seq")))));
	}
	OnAward.Broadcast(Data);
	OnChanged.Broadcast();
}

int32 FVerseProgressionFeed::LevelOf(const FString& SubjectId) const
{
	if (const TArray<TSharedPtr<FJsonValue>>* Subjects = Arr(Snapshot, TEXT("subjects")))
	{
		for (const TSharedPtr<FJsonValue>& V : *Subjects)
		{
			if (Str(V->AsObject(), TEXT("subject_id")) == SubjectId)
			{
				return int32(Int(V->AsObject(), TEXT("level"), 1));
			}
		}
	}
	return 1;
}

void FVerseCompanionFeed::Apply(const TSharedPtr<FJsonObject>& Data)
{
	PetId = Str(Data, TEXT("pet_id"));
	Look = Str(Data, TEXT("look"));
	Style = Str(Data, TEXT("style"), TEXT("default"));
	OnChanged.Broadcast();
}

void FVerseSettingsFeed::ApplyWelcome(const TSharedPtr<FJsonObject>& Welcome)
{
	const TSharedPtr<FJsonObject> Locale = Obj(Welcome, TEXT("locale"));
	Lang = Str(Locale, TEXT("lang"), TEXT("en"));
	Strings.Reset();
	if (const TSharedPtr<FJsonObject> S = Obj(Locale, TEXT("strings")))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& P : S->Values)
		{
			Strings.Add(P.Key, P.Value->AsString());
		}
	}
	if (const TSharedPtr<FJsonObject> Set = Obj(Welcome, TEXT("settings")))
	{
		Settings = Set;
	}
	OnChanged.Broadcast();
}

void FVerseSettingsFeed::ApplyChanged(const TSharedPtr<FJsonObject>& Data)
{
	if (!Data.IsValid())
	{
		return;
	}
	for (const TPair<FString, TSharedPtr<FJsonValue>>& P : Data->Values)
	{
		if (P.Key == TEXT("lang"))
		{
			Lang = P.Value->AsString();
		}
		else if (P.Key == TEXT("strings") && P.Value->Type == EJson::Object)
		{
			for (const TPair<FString, TSharedPtr<FJsonValue>>& S : P.Value->AsObject()->Values)
			{
				Strings.Add(S.Key, S.Value->AsString());
			}
		}
		else if ((P.Key == TEXT("view") || P.Key == TEXT("game")) && P.Value.IsValid() && P.Value->Type == EJson::Object)
		{
			// view and game arrive as subsets of the changed ids: merge them into what welcome gave.
			const TSharedPtr<FJsonObject>* Have = nullptr;
			if (Settings->TryGetObjectField(P.Key, Have) && Have && (*Have).IsValid())
			{
				TSharedRef<FJsonObject> Merged = MakeShared<FJsonObject>();
				Merged->Values = (*Have)->Values;
				for (const TPair<FString, TSharedPtr<FJsonValue>>& Field : P.Value->AsObject()->Values)
				{
					Merged->Values.Add(Field.Key, Field.Value);
				}
				Settings->SetObjectField(P.Key, Merged);
			}
			else
			{
				Settings->Values.Add(P.Key, P.Value);
			}
		}
		else
		{
			Settings->Values.Add(P.Key, P.Value);
		}
	}
	OnChanged.Broadcast();
}

FString FVerseSettingsFeed::Text(const FString& Key) const
{
	const FString* S = Strings.Find(Key);
	return S ? *S : Key;
}

FString FVerseSettingsFeed::ReturnKey() const
{
	return Str(Settings, TEXT("return_key"), TEXT("F10"));
}

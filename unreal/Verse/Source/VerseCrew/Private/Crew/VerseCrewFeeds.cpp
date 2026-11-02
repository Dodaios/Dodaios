#include "Crew/VerseCrewFeeds.h"

namespace
{
	FString StringOr(const TSharedRef<FJsonObject>& Object, const TCHAR* Field, const FString& Fallback = FString())
	{
		FString Value;
		return Object->TryGetStringField(Field, Value) ? Value : Fallback;
	}

	int32 IntOr(const TSharedRef<FJsonObject>& Object, const TCHAR* Field, int32 Fallback)
	{
		double Value = 0.0;
		return Object->TryGetNumberField(Field, Value) ? static_cast<int32>(Value) : Fallback;
	}

	bool SameJson(const TSharedPtr<FJsonValue>& A, const TSharedPtr<FJsonValue>& B)
	{
		if (!A.IsValid() || !B.IsValid())
		{
			return A.IsValid() == B.IsValid();
		}
		return FJsonValue::CompareEqual(*A, *B);
	}
}

void FVerseCrewRoster::Reset()
{
	Agents.Reset();
	Panes.Reset();
	AgentOrder.Reset();
	PaneOrder.Reset();
	Commander = FVerseCrewCommander();
	bHasSnapshot = false;
}

void FVerseCrewRoster::ReadCommander(const TSharedPtr<FJsonObject>& Object)
{
	if (!Object.IsValid())
	{
		return;
	}
	const TSharedRef<FJsonObject> C = Object.ToSharedRef();
	Commander.SubjectId = StringOr(C, TEXT("subject_id"), TEXT("person"));
	Commander.Level = IntOr(C, TEXT("level"), 1);
	Commander.RankId = StringOr(C, TEXT("rank"));
	Commander.Title = StringOr(C, TEXT("title"));
	Commander.Uniform = StringOr(C, TEXT("uniform"), TEXT("standard"));
}

void FVerseCrewRoster::Upsert(TMap<FString, FRow>& Rows, TArray<FString>& Order, const TSharedPtr<FJsonObject>& Patch, const TCHAR* IdField, FVerseCrewRosterChange& Change)
{
	if (!Patch.IsValid())
	{
		return;
	}
	FString Id;
	if (!Patch->TryGetStringField(IdField, Id) || Id.IsEmpty())
	{
		return;
	}
	FRow* Row = Rows.Find(Id);
	if (!Row)
	{
		FRow& Fresh = Rows.Add(Id);
		Fresh.ArrivalOrder = NextArrival++;
		Fresh.Fields = MakeShared<FJsonObject>(*Patch);
		Order.Add(Id);
		Change.Added.Add(Id);
		return;
	}
	bool bChanged = false;
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Field : Patch->Values)
	{
		const TSharedPtr<FJsonValue>* Old = Row->Fields->Values.Find(Field.Key);
		if (!Old || !SameJson(*Old, Field.Value))
		{
			Row->Fields->Values.Add(Field.Key, Field.Value);
			bChanged = true;
		}
	}
	if (bChanged)
	{
		Change.Changed.Add(Id);
	}
}

FVerseCrewRosterChange FVerseCrewRoster::ApplySnapshot(const TSharedRef<FJsonObject>& Data)
{
	FVerseCrewRosterChange Change;
	Change.bSnapshot = true;
	TSet<FString> Seen;
	auto Read = [&](const TCHAR* ArrayField, const TCHAR* IdField, TMap<FString, FRow>& Rows, TArray<FString>& Order) {
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		TSet<FString> Present;
		if (Data->TryGetArrayField(ArrayField, Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				const TSharedPtr<FJsonObject> Object = Value->AsObject();
				FString Id;
				if (!Object.IsValid() || !Object->TryGetStringField(IdField, Id) || Id.IsEmpty())
				{
					continue;
				}
				Present.Add(Id);
				if (FRow* Row = Rows.Find(Id))
				{
					// A snapshot row is complete: replace it, report a change when it differs.
					bool bDifferent = Row->Fields->Values.Num() != Object->Values.Num();
					for (const TPair<FString, TSharedPtr<FJsonValue>>& Field : Object->Values)
					{
						const TSharedPtr<FJsonValue>* Old = Row->Fields->Values.Find(Field.Key);
						bDifferent = bDifferent || !Old || !SameJson(*Old, Field.Value);
					}
					Row->Fields = MakeShared<FJsonObject>(*Object);
					if (bDifferent)
					{
						Change.Changed.Add(Id);
					}
				}
				else
				{
					FRow& Fresh = Rows.Add(Id);
					Fresh.ArrivalOrder = NextArrival++;
					Fresh.Fields = MakeShared<FJsonObject>(*Object);
					Order.Add(Id);
					Change.Added.Add(Id);
				}
			}
		}
		for (auto It = Rows.CreateIterator(); It; ++It)
		{
			if (!Present.Contains(It.Key()))
			{
				Change.Removed.Add(It.Key());
				Order.Remove(It.Key());
				It.RemoveCurrent();
			}
		}
	};
	Read(TEXT("agents"), TEXT("agent_id"), Agents, AgentOrder);
	Read(TEXT("panes"), TEXT("pane_id"), Panes, PaneOrder);
	const TSharedPtr<FJsonObject>* CommanderObject = nullptr;
	if (Data->TryGetObjectField(TEXT("commander"), CommanderObject) && CommanderObject)
	{
		ReadCommander(*CommanderObject);
		Change.bCommanderChanged = true;
	}
	bHasSnapshot = true;
	return Change;
}

FVerseCrewRosterChange FVerseCrewRoster::ApplyDelta(const TSharedRef<FJsonObject>& Data)
{
	FVerseCrewRosterChange Change;
	const TSharedPtr<FJsonObject>* UpsertObject = nullptr;
	if (Data->TryGetObjectField(TEXT("upsert"), UpsertObject) && UpsertObject && UpsertObject->IsValid())
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if ((*UpsertObject)->TryGetArrayField(TEXT("agents"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				Upsert(Agents, AgentOrder, Value->AsObject(), TEXT("agent_id"), Change);
			}
		}
		if ((*UpsertObject)->TryGetArrayField(TEXT("panes"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				Upsert(Panes, PaneOrder, Value->AsObject(), TEXT("pane_id"), Change);
			}
		}
	}
	const TSharedPtr<FJsonObject>* RemoveObject = nullptr;
	if (Data->TryGetObjectField(TEXT("remove"), RemoveObject) && RemoveObject && RemoveObject->IsValid())
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if ((*RemoveObject)->TryGetArrayField(TEXT("agents"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				const FString Id = Value->AsString();
				if (Agents.Remove(Id) > 0)
				{
					AgentOrder.Remove(Id);
					Change.Removed.Add(Id);
				}
			}
		}
		if ((*RemoveObject)->TryGetArrayField(TEXT("panes"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				const FString Id = Value->AsString();
				if (Panes.Remove(Id) > 0)
				{
					PaneOrder.Remove(Id);
					Change.Removed.Add(Id);
				}
			}
		}
	}
	const TSharedPtr<FJsonObject>* CommanderObject = nullptr;
	if (Data->TryGetObjectField(TEXT("commander"), CommanderObject) && CommanderObject && CommanderObject->IsValid())
	{
		ReadCommander(*CommanderObject);
		Change.bCommanderChanged = true;
	}
	return Change;
}

FVerseCrewMember FVerseCrewRoster::MemberOf(const FRow& Row, bool bPane) const
{
	const TSharedRef<FJsonObject>& F = Row.Fields;
	FVerseCrewMember M;
	M.ArrivalOrder = Row.ArrivalOrder;
	M.Duty = VerseCrew::ParseDuty(StringOr(F, TEXT("duty"), TEXT("idle")));
	M.Level = IntOr(F, TEXT("level"), 1);
	M.RankId = StringOr(F, TEXT("rank"));
	if (bPane)
	{
		M.Id = StringOr(F, TEXT("pane_id"));
		M.Role = EVerseCrewRole::Technician;
		M.Name = StringOr(F, TEXT("name"), M.Id);
		M.Title = StringOr(F, TEXT("display_name"));
		M.HistoryId = StringOr(F, TEXT("history_id"), M.Id);
		M.WorkspaceId = StringOr(F, TEXT("workspace_id"));
		M.Look = StringOr(F, TEXT("agent"));
	}
	else
	{
		M.Id = StringOr(F, TEXT("agent_id"));
		M.Role = EVerseCrewRole::Officer;
		M.Name = StringOr(F, TEXT("name"), M.Id);
		M.Title = StringOr(F, TEXT("title"));
		M.Tier = StringOr(F, TEXT("tier"));
		M.bLead = M.Tier.Equals(TEXT("lead"), ESearchCase::CaseSensitive);
		M.Look = StringOr(F, TEXT("look"));
		const TSharedPtr<FJsonObject>* Figure = nullptr;
		if (F->TryGetObjectField(TEXT("figure"), Figure) && Figure && Figure->IsValid())
		{
			M.FigureArchetype = StringOr(Figure->ToSharedRef(), TEXT("archetype"));
			M.FigurePalette = StringOr(Figure->ToSharedRef(), TEXT("palette"));
		}
		const TArray<TSharedPtr<FJsonValue>>* Teams = nullptr;
		if (F->TryGetArrayField(TEXT("team_ids"), Teams))
		{
			for (const TSharedPtr<FJsonValue>& Team : *Teams)
			{
				M.TeamIds.Add(Team->AsString());
			}
		}
		// A paused lifecycle is paused duty whatever the run state says (dutyStatus.ts precedence);
		// the backend already folds it in, this keeps an older relay honest.
		if (StringOr(F, TEXT("lifecycle"), TEXT("active")).Equals(TEXT("paused"), ESearchCase::CaseSensitive))
		{
			M.Duty = EVerseCrewDuty::Paused;
		}
	}
	return M;
}

TArray<FVerseCrewMember> FVerseCrewRoster::Members() const
{
	TArray<FVerseCrewMember> Out;
	Out.Reserve(Agents.Num() + Panes.Num());
	for (const FString& Id : AgentOrder)
	{
		if (const FRow* Row = Agents.Find(Id))
		{
			Out.Add(MemberOf(*Row, false));
		}
	}
	for (const FString& Id : PaneOrder)
	{
		if (const FRow* Row = Panes.Find(Id))
		{
			Out.Add(MemberOf(*Row, true));
		}
	}
	return Out;
}

bool FVerseCrewRoster::FindMember(const FString& Id, FVerseCrewMember& Out) const
{
	if (const FRow* Row = Agents.Find(Id))
	{
		Out = MemberOf(*Row, false);
		return true;
	}
	if (const FRow* Row = Panes.Find(Id))
	{
		Out = MemberOf(*Row, true);
		return true;
	}
	return false;
}

FString FVerseCrewRoster::RawDuty(const FString& Id) const
{
	const FRow* Row = Agents.Find(Id);
	Row = Row ? Row : Panes.Find(Id);
	return Row ? StringOr(Row->Fields, TEXT("duty")) : FString();
}

// ---------------------------------------------------------------------------------------------

void FVerseCrewMeetings::Reset()
{
	Groups.Reset();
	Meetings.Reset();
	bHasGroups = false;
}

void FVerseCrewMeetings::UpsertGroup(const TSharedPtr<FJsonObject>& Patch)
{
	if (!Patch.IsValid())
	{
		return;
	}
	const TSharedRef<FJsonObject> P = Patch.ToSharedRef();
	const FString Id = StringOr(P, TEXT("group_id"));
	if (Id.IsEmpty())
	{
		return;
	}
	FVerseCrewGroup& Group = Groups.FindOrAdd(Id);
	Group.GroupId = Id;
	P->TryGetStringField(TEXT("name"), Group.Name);
	P->TryGetStringField(TEXT("lead"), Group.Lead);
	const TArray<TSharedPtr<FJsonValue>>* Members = nullptr;
	if (P->TryGetArrayField(TEXT("members"), Members))
	{
		Group.Members.Reset();
		for (const TSharedPtr<FJsonValue>& Member : *Members)
		{
			Group.Members.Add(Member->AsString());
		}
	}
}

void FVerseCrewMeetings::ApplyGroupsSnapshot(const TSharedRef<FJsonObject>& Data)
{
	Groups.Reset();
	const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
	if (Data->TryGetArrayField(TEXT("groups"), Values))
	{
		for (const TSharedPtr<FJsonValue>& Value : *Values)
		{
			UpsertGroup(Value->AsObject());
		}
	}
	for (auto It = Meetings.CreateIterator(); It; ++It)
	{
		if (!Groups.Contains(It.Key()))
		{
			It.RemoveCurrent();
		}
	}
	bHasGroups = true;
}

void FVerseCrewMeetings::ApplyGroupsDelta(const TSharedRef<FJsonObject>& Data)
{
	const TSharedPtr<FJsonObject>* UpsertObject = nullptr;
	if (Data->TryGetObjectField(TEXT("upsert"), UpsertObject) && UpsertObject && UpsertObject->IsValid())
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if ((*UpsertObject)->TryGetArrayField(TEXT("groups"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				UpsertGroup(Value->AsObject());
			}
		}
	}
	const TSharedPtr<FJsonObject>* RemoveObject = nullptr;
	if (Data->TryGetObjectField(TEXT("remove"), RemoveObject) && RemoveObject && RemoveObject->IsValid())
	{
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if ((*RemoveObject)->TryGetArrayField(TEXT("groups"), Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				Groups.Remove(Value->AsString());
				Meetings.Remove(Value->AsString());
			}
		}
	}
}

bool FVerseCrewMeetings::ApplyMeetingUpdate(const TSharedRef<FJsonObject>& Data)
{
	const FString GroupId = StringOr(Data, TEXT("group_id"));
	if (GroupId.IsEmpty())
	{
		return false;
	}
	FVerseCrewMeeting Next;
	Next.GroupId = GroupId;
	Data->TryGetBoolField(TEXT("running"), Next.bRunning);
	Next.Round = IntOr(Data, TEXT("round"), 0);
	Next.Speaker = StringOr(Data, TEXT("speaker"));
	const TSharedPtr<FJsonObject>* Room = nullptr;
	if (Data->TryGetObjectField(TEXT("room"), Room) && Room && Room->IsValid())
	{
		Next.RoomId = StringOr(Room->ToSharedRef(), TEXT("room_id"));
		Next.Topic = StringOr(Room->ToSharedRef(), TEXT("topic"));
	}
	const FVerseCrewMeeting* Old = Meetings.Find(GroupId);
	const bool bChanged = !Old || Old->bRunning != Next.bRunning || Old->Speaker != Next.Speaker || Old->Round != Next.Round;
	if (Next.bRunning)
	{
		Meetings.Add(GroupId, Next);
	}
	else
	{
		Meetings.Remove(GroupId);
	}
	return bChanged;
}

TMap<FString, EVerseCrewRoundPart> FVerseCrewMeetings::Rounds() const
{
	TMap<FString, EVerseCrewRoundPart> Out;
	for (const TPair<FString, FVerseCrewMeeting>& Pair : Meetings)
	{
		if (!Pair.Value.bRunning)
		{
			continue;
		}
		if (const FVerseCrewGroup* Group = Groups.Find(Pair.Key))
		{
			for (const FString& Member : Group->Members)
			{
				if (Member != Pair.Value.Speaker && !Out.Contains(Member))
				{
					Out.Add(Member, EVerseCrewRoundPart::Listener);
				}
			}
		}
		if (!Pair.Value.Speaker.IsEmpty())
		{
			Out.Add(Pair.Value.Speaker, EVerseCrewRoundPart::Speaker);
		}
	}
	return Out;
}

TArray<FString> FVerseCrewMeetings::RunningGroups() const
{
	TArray<FString> Out;
	for (const TPair<FString, FVerseCrewMeeting>& Pair : Meetings)
	{
		if (Pair.Value.bRunning)
		{
			Out.Add(Pair.Key);
		}
	}
	Out.Sort();
	return Out;
}

// ---------------------------------------------------------------------------------------------

bool FVerseCrewCompanion::Apply(const TSharedRef<FJsonObject>& Data)
{
	FString NextPet;
	if (!Data->TryGetStringField(TEXT("pet_id"), NextPet))
	{
		NextPet.Reset();
	}
	const FString NextLook = StringOr(Data, TEXT("look"));
	const FString NextStyle = StringOr(Data, TEXT("style"), TEXT("overlay"));
	const bool bChanged = !bKnown || NextPet != PetId || NextLook != Look || NextStyle != Style;
	PetId = NextPet;
	Look = NextLook;
	Style = NextStyle;
	bKnown = true;
	return bChanged;
}

// ---------------------------------------------------------------------------------------------

void FVerseCrewWalkTogether::Reset()
{
	Last.Reset();
	Together = 0.f;
	LastSentSeconds = -1.0e9;
	SentCount = 0;
}

bool FVerseCrewWalkTogether::Sample(const FVector& Commander, const FVector* Drone, double NowSeconds)
{
	const FVector2D Me(Commander.X, Commander.Y);
	bool bDue = false;
	if (Last.IsSet() && Drone && FVector2D::Distance(FVector2D(Drone->X, Drone->Y), Me) < HeelCm)
	{
		Together += static_cast<float>(FVector2D::Distance(Me, *Last));
	}
	if (Together >= WalkCm)
	{
		if (NowSeconds - LastSentSeconds >= CooldownSeconds)
		{
			Together -= WalkCm;
			LastSentSeconds = NowSeconds;
			++SentCount;
			bDue = true;
		}
		else
		{
			// The server would eat it: hold the 50 m until the cooldown is over.
			Together = WalkCm;
		}
	}
	Last = Me;
	return bDue;
}

#include "ServiceRecord/VerseServiceRecordModel.h"
#include "Dom/JsonObject.h"

#include "VerseLog.h"

namespace
{
	int64 NumberOr(const FJsonObject& Object, const TCHAR* Field, int64 Fallback)
	{
		double Value = 0.0;
		return Object.TryGetNumberField(Field, Value) && FMath::IsFinite(Value) ? int64(Value) : Fallback;
	}

	FString StringOr(const FJsonObject& Object, const TCHAR* Field)
	{
		FString Value;
		return Object.TryGetStringField(Field, Value) ? Value : FString();
	}

	int32 Count(const FJsonObject& Object, const TCHAR* Field)
	{
		return int32(FMath::Clamp<int64>(NumberOr(Object, Field, 0), 0, MAX_int32));
	}

	EVerseSubjectKind KindOf(const FString& SubjectId, const FString& Kind)
	{
		if (Kind == TEXT("agent") || SubjectId.StartsWith(TEXT("agent:")))
		{
			return EVerseSubjectKind::Agent;
		}
		if (Kind == TEXT("pet") || SubjectId.StartsWith(TEXT("pet:")))
		{
			return EVerseSubjectKind::Pet;
		}
		return EVerseSubjectKind::Person;
	}

	const TArray<FName>& TierOrder()
	{
		static const TArray<FName> Order = {FName(TEXT("deck")), FName(TEXT("line")), FName(TEXT("command")), FName(TEXT("flag"))};
		return Order;
	}
}

FName FVerseRewardRow::Key() const
{
	const FString Id = RewardId.ToString();
	int32 Underscore = INDEX_NONE;
	return Id.FindChar(TEXT('_'), Underscore) ? FName(*Id.Mid(Underscore + 1)) : RewardId;
}

int32 FVerseRewardRow::LevelFor(EVerseSubjectKind Kind) const
{
	switch (Kind)
	{
	case EVerseSubjectKind::Person: return PersonLevel;
	case EVerseSubjectKind::Agent: return AgentLevel;
	default: return PetLevel;
	}
}

int64 FVerseServiceRecordModel::XpToNext(int32 Level)
{
	if (Level >= MaxLevel)
	{
		return 0;
	}
	const int32 L = FMath::Max(1, Level);
	const double Raw = 40.0 + 25.0 * FMath::Pow(double(L - 1), 1.1);
	return int64(FMath::RoundToDouble(Raw / 5.0) * 5.0);
}

int64 FVerseServiceRecordModel::TotalXpForLevel(int32 Level)
{
	const int32 Target = FMath::Clamp(Level, 1, MaxLevel);
	int64 Total = 0;
	for (int32 Step = 1; Step < Target; ++Step)
	{
		Total += XpToNext(Step);
	}
	return Total;
}

int32 FVerseServiceRecordModel::LevelForXp(int64 TotalXp)
{
	int32 Level = 1;
	int64 Remaining = FMath::Max<int64>(0, TotalXp);
	while (Level < MaxLevel)
	{
		const int64 Need = XpToNext(Level);
		if (Remaining < Need)
		{
			break;
		}
		Remaining -= Need;
		++Level;
	}
	return Level;
}

const TArray<FVerseRankRow>& FVerseServiceRecordModel::Ladder()
{
	// VERSE_RANK_LADDER_BEGIN (read by tests/unit/progression/test_duel_parity.py)
	static const TArray<FVerseRankRow> Rows = {
		{TEXT("recruit"), 1, TEXT("deck"), TEXT("000|010")},
		{TEXT("deckhand"), 3, TEXT("deck"), TEXT("000|101")},
		{TEXT("technician"), 5, TEXT("deck"), TEXT("000|111")},
		{TEXT("senior_technician"), 8, TEXT("deck"), TEXT("010|111")},
		{TEXT("ensign"), 11, TEXT("line"), TEXT("010|000")},
		{TEXT("lieutenant"), 14, TEXT("line"), TEXT("101|000")},
		{TEXT("senior_lieutenant"), 17, TEXT("line"), TEXT("111|000")},
		{TEXT("commander"), 21, TEXT("line"), TEXT("111|010")},
		{TEXT("captain"), 25, TEXT("line"), TEXT("111|101")},
		{TEXT("line_captain"), 29, TEXT("command"), TEXT("010|010")},
		{TEXT("commodore"), 33, TEXT("command"), TEXT("101|010")},
		{TEXT("rear_admiral"), 37, TEXT("flag"), TEXT("010|101")},
		{TEXT("vice_admiral"), 41, TEXT("flag"), TEXT("101|101")},
		{TEXT("admiral"), 45, TEXT("flag"), TEXT("101|111")},
		{TEXT("fleet_admiral"), 50, TEXT("flag"), TEXT("111|111")},
	};
	// VERSE_RANK_LADDER_END
	return Rows;
}

const FVerseRankRow& FVerseServiceRecordModel::RankFor(int32 Level)
{
	const TArray<FVerseRankRow>& Rows = Ladder();
	const FVerseRankRow* Held = &Rows[0];
	for (const FVerseRankRow& Row : Rows)
	{
		if (Level >= Row.Level)
		{
			Held = &Row;
		}
	}
	return *Held;
}

const FVerseRankRow* FVerseServiceRecordModel::NextRank(int32 Level)
{
	for (const FVerseRankRow& Row : Ladder())
	{
		if (Row.Level > Level)
		{
			return &Row;
		}
	}
	return nullptr;
}

void FVerseServiceRecordModel::SetCommander(int32 Level, int64 TotalXp, const FString& Title)
{
	Record.Level = FMath::Clamp(Level, 1, MaxLevel);
	Record.TotalXp = FMath::Max<int64>(0, TotalXp);
	Record.ForNext = XpToNext(Record.Level);
	// The server's level wins; the bar is placed inside it even when the numbers disagree.
	Record.IntoLevel = FMath::Clamp<int64>(Record.TotalXp - TotalXpForLevel(Record.Level), 0, Record.ForNext);
	Record.Title = Title;
	// An automatic choice follows the level; tell the material when the worn uniform changed.
	const FName Worn = EffectiveUniform();
	if (Worn != LastWorn)
	{
		LastWorn = Worn;
		if (OnUniformWorn)
		{
			OnUniformWorn(Worn);
		}
	}
}

bool FVerseServiceRecordModel::ApplySnapshot(const FJsonObject& Data)
{
	const TArray<TSharedPtr<FJsonValue>>* Subjects = nullptr;
	if (!Data.TryGetArrayField(TEXT("subjects"), Subjects) || !Subjects)
	{
		return false;
	}
	for (const TSharedPtr<FJsonValue>& Value : *Subjects)
	{
		const TSharedPtr<FJsonObject>* Subject = nullptr;
		FString Id;
		if (Value.IsValid() && Value->TryGetObject(Subject) && Subject && (*Subject)->TryGetStringField(TEXT("subject_id"), Id) && Id == TEXT("person"))
		{
			const FJsonObject& Person = **Subject;
			SetCommander(int32(NumberOr(Person, TEXT("level"), 1)), NumberOr(Person, TEXT("total_xp"), 0), StringOr(Person, TEXT("title")));
			const int64 Into = NumberOr(Person, TEXT("into_level"), -1);
			const int64 ForNext = NumberOr(Person, TEXT("for_next"), -1);
			if (Into >= 0 && ForNext >= 0)
			{
				Record.IntoLevel = Into;
				Record.ForNext = ForNext;
			}
		}
	}
	for (const TSharedPtr<FJsonValue>& Value : *Subjects)
	{
		const TSharedPtr<FJsonObject>* Subject = nullptr;
		FString Id;
		if (Value.IsValid() && Value->TryGetObject(Subject) && Subject && (*Subject)->TryGetStringField(TEXT("subject_id"), Id) && Id != TEXT("person"))
		{
			const FJsonObject& Row = **Subject;
			const int64 Xp = NumberOr(Row, TEXT("total_xp"), NumberOr(Row, TEXT("xp"), 0));
			ApplySubject(Id, KindOf(Id, StringOr(Row, TEXT("kind"))), int32(NumberOr(Row, TEXT("level"), LevelForXp(Xp))), Xp);
		}
	}
	FString Pet;
	if (Data.TryGetStringField(TEXT("pet_id"), Pet))
	{
		PetId = Pet;
	}
	ParseRulebook(Data);
	Latest = FMath::Max(Latest, NumberOr(Data, TEXT("latest_seq"), 0));
	Told = FMath::Max(Told, NumberOr(Data, TEXT("told_seq"), 0));
	const TSharedPtr<FJsonObject>* Stats = nullptr;
	if (Data.TryGetObjectField(TEXT("duel_stats"), Stats) && Stats)
	{
		ApplyDuelStats(**Stats);
	}
	bHasSnapshot = true;
	DropToldPromotions();
	OnChanged.Broadcast();
	return true;
}

bool FVerseServiceRecordModel::ApplyAwarded(const FJsonObject& Data)
{
	FString Subject;
	if (!Data.TryGetStringField(TEXT("subject_id"), Subject))
	{
		return false;
	}
	const EVerseSubjectKind Kind = KindOf(Subject, StringOr(Data, TEXT("subject_kind")));
	const int64 Seq = NumberOr(Data, TEXT("seq"), 0);
	const int32 Level = int32(NumberOr(Data, TEXT("level"), Record.Level));
	const int32 Previous = int32(NumberOr(Data, TEXT("previous_level"), Level));

	// The log keeps what was paid, newest last.
	if (Seq > 0 && !Ledger.ContainsByPredicate([Seq](const FVerseAwardRow& Row) { return Row.Seq == Seq; }))
	{
		FVerseAwardRow Row;
		Row.Seq = Seq;
		Row.SubjectId = Subject;
		Row.Kind = Kind;
		Row.Source = FName(*StringOr(Data, TEXT("xp_source")));
		Row.Xp = Count(Data, TEXT("xp"));
		Row.LevelBefore = Previous;
		Row.LevelAfter = Level;
		Row.TimestampMs = NumberOr(Data, TEXT("ts_ms"), int64(FDateTime::UtcNow().ToUnixTimestamp()) * 1000);
		Ledger.Add(Row);
		if (Ledger.Num() > 200)
		{
			Ledger.RemoveAt(0, Ledger.Num() - 200);
		}
	}
	if (Kind == EVerseSubjectKind::Person)
	{
		SetCommander(Level, NumberOr(Data, TEXT("total_xp"), Record.TotalXp), StringOr(Data, TEXT("title")));
	}
	else
	{
		ApplySubject(Subject, Kind, Level, NumberOr(Data, TEXT("total_xp"), 0));
	}
	Latest = FMath::Max(Latest, Seq);

	bool bQueued = false;
	const bool bKnown = Promotions.ContainsByPredicate([Seq](const FVersePromotion& P) { return P.Seq == Seq; })
		|| Quiet.ContainsByPredicate([Seq](const FVerseQuietLine& L) { return L.Seq == Seq; });
	if (Level > Previous && Seq > Told && !bKnown)
	{
		const FName RankNow = RankFor(Level).Id;
		const FName RankBefore = RankFor(Previous).Id;
		// The commander and the drone get the full notice for a new rank; every other level-up is a quiet line.
		if (Kind != EVerseSubjectKind::Agent && (Kind == EVerseSubjectKind::Person || RankNow != RankBefore))
		{
			FVersePromotion Promotion;
			Promotion.Seq = Seq;
			Promotion.Kind = Kind;
			Promotion.Level = Level;
			Promotion.PreviousLevel = Previous;
			Promotion.RankId = RankNow;
			Promotion.PreviousRankId = RankBefore;
			const TArray<TSharedPtr<FJsonValue>>* Unlocked = nullptr;
			if (Data.TryGetArrayField(TEXT("unlocked"), Unlocked) && Unlocked)
			{
				for (const TSharedPtr<FJsonValue>& Item : *Unlocked)
				{
					FString Id;
					if (Item.IsValid() && Item->TryGetString(Id))
					{
						Promotion.Unlocked.Add(Id);
					}
				}
			}
			Promotions.Add(MoveTemp(Promotion));
			bQueued = true;
		}
		else
		{
			FVerseQuietLine Line;
			Line.Seq = Seq;
			Line.SubjectId = Subject;
			Line.Kind = Kind;
			Line.Level = Level;
			Line.RankId = RankNow;
			Line.bPromoted = RankNow != RankBefore;
			Quiet.Add(Line);
		}
	}
	OnChanged.Broadcast();
	return bQueued;
}

void FVerseServiceRecordModel::ApplySubject(const FString& SubjectId, EVerseSubjectKind Kind, int32 Level, int64 TotalXp)
{
	FVerseSubjectRow* Row = Others.FindByPredicate([&SubjectId](const FVerseSubjectRow& R) { return R.SubjectId == SubjectId; });
	if (!Row)
	{
		Row = &Others.AddDefaulted_GetRef();
		Row->SubjectId = SubjectId;
	}
	Row->Kind = Kind;
	Row->Level = FMath::Clamp(Level, 1, MaxLevel);
	if (TotalXp > 0)
	{
		Row->TotalXp = TotalXp;
	}
}

void FVerseServiceRecordModel::ParseRulebook(const FJsonObject& Data)
{
	// The rulebook sits in a `rulebook` object (bridge) or at the top level (the app read); either may be present.
	const FJsonObject* Books[2] = {&Data, nullptr};
	const TSharedPtr<FJsonObject>* Nested = nullptr;
	if (Data.TryGetObjectField(TEXT("rulebook"), Nested) && Nested)
	{
		Books[1] = Nested->Get();
	}
	auto Array = [&Books](const TCHAR* Field) -> const TArray<TSharedPtr<FJsonValue>>*
	{
		for (const FJsonObject* Book : Books)
		{
			const TArray<TSharedPtr<FJsonValue>>* Out = nullptr;
			if (Book && Book->TryGetArrayField(Field, Out) && Out && Out->Num() > 0)
			{
				return Out;
			}
		}
		return nullptr;
	};
	if (const TArray<TSharedPtr<FJsonValue>>* RewardRows = Array(TEXT("rewards")))
	{
		ServerRewards.Reset();
		for (const TSharedPtr<FJsonValue>& Value : *RewardRows)
		{
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (!Value.IsValid() || !Value->TryGetObject(Row) || !Row)
			{
				continue;
			}
			FVerseRewardRow Reward;
			Reward.RewardId = FName(*StringOr(**Row, TEXT("reward_id")));
			Reward.Slot = FName(*StringOr(**Row, TEXT("slot")));
			const TSharedPtr<FJsonObject>* Levels = nullptr;
			if ((*Row)->TryGetObjectField(TEXT("levels"), Levels) && Levels)
			{
				Reward.PersonLevel = int32(NumberOr(**Levels, TEXT("person"), -1));
				Reward.AgentLevel = int32(NumberOr(**Levels, TEXT("agent"), -1));
				Reward.PetLevel = int32(NumberOr(**Levels, TEXT("pet"), -1));
			}
			// An id this build does not know cannot be drawn: left out, like the app does.
			if ((Reward.Slot == FName(TEXT("uniform")) || Reward.Slot == FName(TEXT("ribbon"))) && !Reward.RewardId.IsNone())
			{
				ServerRewards.Add(Reward);
			}
		}
	}
	if (const TArray<TSharedPtr<FJsonValue>>* RuleRows = Array(TEXT("rules")))
	{
		XpRules.Reset();
		for (const TSharedPtr<FJsonValue>& Value : *RuleRows)
		{
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (!Value.IsValid() || !Value->TryGetObject(Row) || !Row)
			{
				continue;
			}
			FVerseXpRule Rule;
			Rule.Source = FName(*StringOr(**Row, TEXT("source")));
			Rule.Kind = KindOf(FString(), StringOr(**Row, TEXT("kind")));
			Rule.Xp = Count(**Row, TEXT("xp"));
			Rule.bWorld = StringOr(**Row, TEXT("trigger")) == TEXT("world");
			Rule.CooldownSeconds = Count(**Row, TEXT("cooldown_s"));
			Rule.DailyCap = Count(**Row, TEXT("daily_cap"));
			if (!Rule.Source.IsNone())
			{
				XpRules.Add(Rule);
			}
		}
	}
	if (const TArray<TSharedPtr<FJsonValue>>* Recent = Array(TEXT("recent")))
	{
		for (const TSharedPtr<FJsonValue>& Value : *Recent)
		{
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (!Value.IsValid() || !Value->TryGetObject(Row) || !Row)
			{
				continue;
			}
			FVerseAwardRow Award;
			Award.Seq = NumberOr(**Row, TEXT("seq"), 0);
			Award.SubjectId = StringOr(**Row, TEXT("subject_id"));
			Award.Kind = KindOf(Award.SubjectId, StringOr(**Row, TEXT("kind")));
			Award.Source = FName(*StringOr(**Row, TEXT("source")));
			Award.Xp = Count(**Row, TEXT("xp"));
			Award.LevelBefore = int32(NumberOr(**Row, TEXT("level_before"), 1));
			Award.LevelAfter = int32(NumberOr(**Row, TEXT("level_after"), 1));
			Award.TimestampMs = NumberOr(**Row, TEXT("ts_ms"), 0);
			if (Award.Seq > 0 && !Ledger.ContainsByPredicate([&Award](const FVerseAwardRow& R) { return R.Seq == Award.Seq; }))
			{
				Ledger.Add(Award);
			}
		}
		Ledger.Sort([](const FVerseAwardRow& A, const FVerseAwardRow& B) { return A.Seq < B.Seq; });
	}
}

const TArray<FVerseRewardRow>& FVerseServiceRecordModel::DefaultRewards()
{
	// rules.py REWARDS (levelCatalog.ts REWARD_LEVELS), in the rulebook order.
	static const TArray<FVerseRewardRow> Rows = []
	{
		auto Make = [](const TCHAR* Id, const TCHAR* Slot, int32 Person, int32 Agent)
		{
			FVerseRewardRow Row;
			Row.RewardId = Id;
			Row.Slot = Slot;
			Row.PersonLevel = Person;
			Row.AgentLevel = Agent;
			return Row;
		};
		return TArray<FVerseRewardRow>{
			Make(TEXT("uniform_deck"), TEXT("uniform"), 1, -1),
			Make(TEXT("uniform_line"), TEXT("uniform"), 11, -1),
			Make(TEXT("uniform_command"), TEXT("uniform"), 29, -1),
			Make(TEXT("uniform_flag"), TEXT("uniform"), 37, -1),
			Make(TEXT("ribbon_good_conduct"), TEXT("ribbon"), 6, 4),
			Make(TEXT("ribbon_meritorious"), TEXT("ribbon"), 19, 16),
			Make(TEXT("ribbon_distinguished"), TEXT("ribbon"), 31, 27),
			Make(TEXT("ribbon_fleet_cross"), TEXT("ribbon"), 47, 43),
		};
	}();
	return Rows;
}

const TArray<FVerseRewardRow>& FVerseServiceRecordModel::Rewards() const
{
	return ServerRewards.Num() > 0 ? ServerRewards : DefaultRewards();
}

TArray<FVerseAwardRow> FVerseServiceRecordModel::CommanderLog(int32 Limit) const
{
	TArray<FVerseAwardRow> Out;
	for (int32 I = Ledger.Num() - 1; I >= 0 && Out.Num() < Limit; --I)
	{
		if (Ledger[I].Kind == EVerseSubjectKind::Person)
		{
			Out.Add(Ledger[I]);
		}
	}
	return Out;
}

FVerseSubjectRow FVerseServiceRecordModel::Companion() const
{
	const FVerseSubjectRow* Row = Others.FindByPredicate([](const FVerseSubjectRow& R) { return R.Kind == EVerseSubjectKind::Pet; });
	if (Row)
	{
		return *Row;
	}
	FVerseSubjectRow Fresh;
	Fresh.Kind = EVerseSubjectKind::Pet;
	Fresh.SubjectId = TEXT("pet:") + PetId;
	return Fresh;
}

TArray<FName> FVerseServiceRecordModel::IssuedUniforms(int32 Level) const
{
	TSet<FName> Issued;
	Issued.Add(TEXT("deck"));
	for (const FVerseRewardRow& Reward : Rewards())
	{
		if (Reward.Slot == FName(TEXT("uniform")) && Reward.PersonLevel >= 0 && Level >= Reward.PersonLevel)
		{
			Issued.Add(Reward.Key());
		}
	}
	TArray<FName> Out;
	for (const FName Tier : TierOrder())
	{
		if (Issued.Contains(Tier))
		{
			Out.Add(Tier);
		}
	}
	return Out;
}

FName FVerseServiceRecordModel::EffectiveUniform() const
{
	const TArray<FName> Issued = IssuedUniforms(Record.Level);
	if (UniformChoice != FName(TEXT("auto")) && Issued.Contains(UniformChoice))
	{
		return UniformChoice;
	}
	return Issued.Num() > 0 ? Issued.Last() : FName(TEXT("deck"));
}

bool FVerseServiceRecordModel::ChooseUniform(FName Choice)
{
	if (Choice != FName(TEXT("auto")) && !IssuedUniforms(Record.Level).Contains(Choice))
	{
		return false;
	}
	UniformChoice = Choice;
	if (SaveUniformChoice)
	{
		SaveUniformChoice(Choice);
	}
	LastWorn = EffectiveUniform();
	if (OnUniformWorn)
	{
		OnUniformWorn(LastWorn);
	}
	OnChanged.Broadcast();
	return true;
}

void FVerseServiceRecordModel::RestoreUniformChoice(FName Choice)
{
	UniformChoice = (Choice == FName(TEXT("auto")) || TierOrder().Contains(Choice)) ? Choice : FName(TEXT("auto"));
	LastWorn = EffectiveUniform();
	if (OnUniformWorn)
	{
		OnUniformWorn(LastWorn);
	}
}

void FVerseServiceRecordModel::SetCrewNames(const TMap<FString, FString>& Names, const FString& CompanionName)
{
	CrewNames = Names;
	CompanionLabel = CompanionName;
	OnChanged.Broadcast();
}

bool FVerseServiceRecordModel::PopQuietLine(FVerseQuietLine& Out)
{
	if (Quiet.Num() == 0)
	{
		return false;
	}
	Out = Quiet[0];
	Quiet.RemoveAt(0);
	return true;
}

void FVerseServiceRecordModel::ApplyDuelStats(const FJsonObject& Stats)
{
	FVerseDuelTotals Next;
	Next.Matches = Count(Stats, TEXT("matches"));
	Next.Wins = Count(Stats, TEXT("wins"));
	Next.Losses = Count(Stats, TEXT("losses"));
	Next.Unfinished = Count(Stats, TEXT("unfinished"));
	Next.Kills = Count(Stats, TEXT("kills"));
	Next.Deaths = Count(Stats, TEXT("deaths"));
	Next.Headshots = Count(Stats, TEXT("headshots"));
	Next.Finishers = Count(Stats, TEXT("finishers"));
	Next.BestStreak = Count(Stats, TEXT("best_streak"));
	const TSharedPtr<FJsonObject>* Tiers = nullptr;
	if (Stats.TryGetObjectField(TEXT("by_tier"), Tiers) && Tiers)
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Pair : (*Tiers)->Values)
		{
			const TSharedPtr<FJsonObject>* Row = nullptr;
			if (Pair.Value.IsValid() && Pair.Value->TryGetObject(Row) && Row)
			{
				Next.ByTier.Add(Pair.Key, FIntPoint(Count(**Row, TEXT("wins")), Count(**Row, TEXT("losses"))));
			}
		}
	}
	DuelTotals = MoveTemp(Next);
	OnChanged.Broadcast();
}

const FVersePromotion* FVerseServiceRecordModel::PendingPromotion() const
{
	return Promotions.Num() > 0 ? &Promotions[0] : nullptr;
}

void FVerseServiceRecordModel::MarkPromotionShown()
{
	if (Promotions.Num() == 0)
	{
		return;
	}
	const int64 Seq = Promotions[0].Seq;
	Promotions.RemoveAt(0);
	if (Seq > Told)
	{
		Told = Seq;
		if (SendTold)
		{
			SendTold(Seq);
		}
		else
		{
			UE_LOG(LogVerseUI, Verbose, TEXT("service record: promotion %lld shown with no bridge to tell"), Seq);
		}
	}
	DropToldPromotions();
	OnChanged.Broadcast();
}

void FVerseServiceRecordModel::DropToldPromotions()
{
	// Shown elsewhere (or earlier): told_seq covers it, so it is never shown again.
	Promotions.RemoveAll([this](const FVersePromotion& P) { return P.Seq <= Told; });
	Quiet.RemoveAll([this](const FVerseQuietLine& L) { return L.Seq <= Told; });
}

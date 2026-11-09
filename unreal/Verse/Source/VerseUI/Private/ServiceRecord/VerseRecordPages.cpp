#include "ServiceRecord/VerseRecordPages.h"

#include "Core/VerseUiStrings.h"
#include "ServiceRecord/SVerseServiceRecord.h"

namespace
{
	const TArray<FName>& TierIds()
	{
		static const TArray<FName> Ids = {FName(TEXT("deck")), FName(TEXT("line")), FName(TEXT("command")), FName(TEXT("flag"))};
		return Ids;
	}

	FString RankKey(FName RankId)
	{
		return FString::Printf(TEXT("verse.ranks.rank.%s"), *RankId.ToString());
	}

	/** The level the first rank of a tier starts at. */
	int32 TierStart(FName Tier)
	{
		for (const FVerseRankRow& Row : FVerseServiceRecordModel::Ladder())
		{
			if (Row.Tier == Tier)
			{
				return Row.Level;
			}
		}
		return 1;
	}

	/** XP still missing to reach Level from the commander's total. */
	int64 XpUntilLevel(const FVerseServiceRecordModel& Model, int32 Level)
	{
		return FMath::Max<int64>(0, FVerseServiceRecordModel::TotalXpForLevel(Level) - Model.Commander().TotalXp);
	}
}

const TArray<FVerseRecordPages::FTab>& FVerseRecordPages::Tabs()
{
	static const TArray<FTab> Tabs = []
	{
		TArray<FTab> Out;
		const TPair<EVerseRecordTab, const TCHAR*> Order[] = {
			{EVerseRecordTab::Record, TEXT("record")},
			{EVerseRecordTab::Ladder, TEXT("ladder")},
			{EVerseRecordTab::Rewards, TEXT("rewards")},
			{EVerseRecordTab::Earn, TEXT("earn")},
			{EVerseRecordTab::Crew, TEXT("crew")},
		};
		for (const TPair<EVerseRecordTab, const TCHAR*>& Entry : Order)
		{
			FTab Tab;
			Tab.Tab = Entry.Key;
			Tab.Id = FName(Entry.Value);
			Tab.LabelKey = FString::Printf(TEXT("verse.ranks.record.tabs.%s"), Entry.Value);
			Out.Add(Tab);
		}
		return Out;
	}();
	return Tabs;
}

FText FVerseRecordPages::Figure(int64 Value)
{
	return FText::AsCultureInvariant(SVerseServiceRecord::FormatFigure(Value));
}

FText FVerseRecordPages::Fill(const FVerseUiStrings& Strings, const FString& Key, const TMap<FString, FString>& Values)
{
	FFormatNamedArguments Args;
	for (const TPair<FString, FString>& Pair : Values)
	{
		Args.Add(Pair.Key, FText::AsCultureInvariant(Pair.Value));
	}
	return Strings.Format(Key, Args);
}

FText FVerseRecordPages::RankName(const FVerseUiStrings& Strings, FName RankId)
{
	return Strings.Get(RankKey(RankId));
}

FText FVerseRecordPages::TierName(const FVerseUiStrings& Strings, FName Tier)
{
	return Strings.Get(FString::Printf(TEXT("verse.ranks.tier.%s"), *Tier.ToString()));
}

FString FVerseRecordPages::CooldownText(int32 Seconds)
{
	return Seconds >= 60 ? FString::Printf(TEXT("%d min"), FMath::RoundToInt(Seconds / 60.f)) : FString::Printf(TEXT("%d s"), Seconds);
}

// ------------------------------------------------------------------ Record

FVerseRecordPages::FRecordPage FVerseRecordPages::Record(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	FRecordPage Page;
	const FVerseCommanderRecord& C = Model.Commander();
	// The rank comes from the level, whatever rank id the server named.
	const FVerseRankRow& Rank = FVerseServiceRecordModel::RankFor(C.Level);
	const FVerseRankRow* Next = FVerseServiceRecordModel::NextRank(C.Level);
	Page.RankId = Rank.Id;
	Page.Rank = RankName(Strings, Rank.Id);
	Page.Tier = TierName(Strings, Rank.Tier);
	Page.Level = Figure(C.Level);
	Page.TotalXp = Figure(C.TotalXp);
	Page.ThisLevel = C.ForNext > 0 ? FText::AsCultureInvariant(SVerseServiceRecord::FormatFigure(C.IntoLevel) + TEXT(" / ") + SVerseServiceRecord::FormatFigure(C.ForNext)) : FText::AsCultureInvariant(TEXT("-"));
	Page.Fraction = C.ForNext > 0 ? float(double(C.IntoLevel) / double(C.ForNext)) : 1.f;
	if (Next)
	{
		Page.NextRankXp = Fill(Strings, TEXT("verse.ranks.record.xp_ahead"), {{TEXT("xp"), SVerseServiceRecord::FormatFigure(XpUntilLevel(Model, Next->Level))}});
		Page.NextRank = RankName(Strings, Next->Id);
	}
	else
	{
		Page.NextRank = Strings.Get(TEXT("verse.ranks.record.top_rank"));
	}

	const FVerseDuelTotals& D = Model.Duels();
	Page.bHasDuels = D.Matches > 0;
	Page.Sets = Figure(D.Matches);
	Page.WonLost = Fill(Strings, TEXT("verse.ranks.record.duel.won_lost"), {{TEXT("won"), SVerseServiceRecord::FormatFigure(D.Wins)}, {TEXT("lost"), SVerseServiceRecord::FormatFigure(D.Losses)}});
	Page.KillDeath = FText::AsCultureInvariant(SVerseServiceRecord::FormatRatio(D.KillDeathRatio()));
	Page.Headshots = Figure(D.Headshots);
	Page.Finishers = Figure(D.Finishers);
	Page.BestStreak = Figure(D.BestStreak);
	if (D.Unfinished > 0)
	{
		Page.Unfinished = FText::AsCultureInvariant(Strings.Get(TEXT("verse.ranks.record.duel.unfinished")).ToString() + TEXT(" ") + SVerseServiceRecord::FormatFigure(D.Unfinished));
	}

	for (const FVerseRewardRow& Reward : Model.Rewards())
	{
		if (Reward.Slot == FName(TEXT("ribbon")) && Reward.PersonLevel >= 0 && C.Level >= Reward.PersonLevel)
		{
			Page.Ribbons.Add(Strings.Get(FString::Printf(TEXT("verse.ranks.ribbon.%s"), *Reward.RewardId.ToString())));
		}
	}
	Page.NoRibbons = Strings.Get(TEXT("verse.ranks.record.no_ribbons"));

	for (const FVerseAwardRow& Award : Model.CommanderLog(8))
	{
		FLogRow Row;
		const FString SourceKey = FString::Printf(TEXT("verse.ranks.source.%s"), *Award.Source.ToString());
		// A source this build no longer pays shares one word.
		Row.Source = Strings.GetIn(SourceKey, TEXT("en")).IsEmpty() ? Strings.Get(TEXT("verse.ranks.source.retired")) : Strings.Get(SourceKey);
		Row.When = Award.TimestampMs > 0
			? FText::AsDateTime(FDateTime::FromUnixTimestamp(Award.TimestampMs / 1000), EDateTimeStyle::Short, EDateTimeStyle::Short, FText::GetInvariantTimeZone(), Strings.GetCulture())
			: FText::GetEmpty();
		Row.Xp = FText::AsCultureInvariant(FString::Printf(TEXT("+%d"), Award.Xp));
		Page.Log.Add(Row);
	}
	Page.NoLog = Strings.Get(TEXT("verse.ranks.record.log_empty"));
	Page.bBellOn = Model.IsBellOn();
	return Page;
}

// ------------------------------------------------------------------ Ladder

TArray<FVerseRecordPages::FTierBlock> FVerseRecordPages::Ladder(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	TArray<FTierBlock> Out;
	const int32 Level = Model.Commander().Level;
	const FName Current = FVerseServiceRecordModel::RankFor(Level).Id;
	for (const FName Tier : TierIds())
	{
		FTierBlock Block;
		Block.Tier = Tier;
		Block.Name = TierName(Strings, Tier);
		Block.FromLevel = Fill(Strings, TEXT("verse.ranks.record.from_level"), {{TEXT("level"), FString::FromInt(TierStart(Tier))}});
		for (const FVerseRankRow& Row : FVerseServiceRecordModel::Ladder())
		{
			if (Row.Tier != Tier)
			{
				continue;
			}
			FStep Step;
			Step.RankId = Row.Id;
			Step.Level = Row.Level;
			Step.Name = RankName(Strings, Row.Id);
			Step.State = Row.Id == Current ? EStepState::Current : (Row.Level <= Level ? EStepState::Held : EStepState::Ahead);
			if (Step.State == EStepState::Ahead)
			{
				Step.Right = Fill(Strings, TEXT("verse.ranks.record.xp_ahead"), {{TEXT("xp"), SVerseServiceRecord::FormatFigure(XpUntilLevel(Model, Row.Level))}});
			}
			else
			{
				Step.StateText = Strings.Get(Step.State == EStepState::Current ? TEXT("verse.ranks.record.current") : TEXT("verse.ranks.record.held"));
				Step.Right = Fill(Strings, TEXT("verse.ranks.record.from_level"), {{TEXT("level"), FString::FromInt(Row.Level)}});
			}
			Block.Steps.Add(Step);
		}
		Out.Add(Block);
	}
	return Out;
}

// ------------------------------------------------------------------ Quartermaster

FVerseRecordPages::FQuartermasterPage FVerseRecordPages::Quartermaster(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	FQuartermasterPage Page;
	const int32 Level = Model.Commander().Level;
	const TArray<FName> Issued = Model.IssuedUniforms(Level);
	const FName Choice = Model.GetUniformChoice();
	TArray<FName> Options;
	Options.Add(TEXT("auto"));
	Options.Append(TierIds());
	for (const FName Option : Options)
	{
		const bool bAuto = Option == FName(TEXT("auto"));
		FUniformOption Row;
		Row.Id = Option;
		Row.SwatchTier = bAuto ? (Issued.Num() > 0 ? Issued.Last() : FName(TEXT("deck"))) : Option;
		Row.bOpen = bAuto || Issued.Contains(Option);
		Row.bChosen = Choice == Option;
		if (bAuto)
		{
			Row.Name = Strings.Get(TEXT("verse.ranks.record.auto"));
			Row.Note = Strings.Get(TEXT("verse.ranks.record.auto_hint"));
		}
		else
		{
			Row.Name = Strings.Get(FString::Printf(TEXT("verse.ranks.uniform.%s"), *Option.ToString()));
			if (Row.bOpen)
			{
				Row.Note = Strings.Get(FString::Printf(TEXT("verse.ranks.uniform_note.%s"), *Option.ToString()));
			}
			else
			{
				int32 OpensAt = TierStart(Option);
				for (const FVerseRewardRow& Reward : Model.Rewards())
				{
					if (Reward.Slot == FName(TEXT("uniform")) && Reward.Key() == Option && Reward.PersonLevel >= 0)
					{
						OpensAt = Reward.PersonLevel;
					}
				}
				Row.Note = Fill(Strings, TEXT("verse.ranks.record.opens_at"), {{TEXT("level"), FString::FromInt(OpensAt)}});
			}
		}
		if (Row.bChosen)
		{
			Row.StateText = Strings.Get(TEXT("verse.ranks.record.wearing"));
		}
		else if (Row.bOpen && !bAuto)
		{
			Row.StateText = Strings.Get(TEXT("verse.ranks.record.issued"));
		}
		Page.Uniforms.Add(Row);
	}

	for (const FVerseRewardRow& Reward : Model.Rewards())
	{
		if (Reward.Slot != FName(TEXT("ribbon")))
		{
			continue;
		}
		FRibbonRow Row;
		Row.Id = Reward.RewardId;
		Row.Name = Strings.Get(FString::Printf(TEXT("verse.ranks.ribbon.%s"), *Reward.RewardId.ToString()));
		Row.Note = Strings.Get(FString::Printf(TEXT("verse.ranks.ribbon_note.%s"), *Reward.RewardId.ToString()));
		Row.bOpen = Reward.PersonLevel >= 0 && Level >= Reward.PersonLevel;
		if (Reward.PersonLevel >= 0)
		{
			Row.ForYou = Fill(Strings, TEXT("verse.ranks.record.for_you"), {{TEXT("level"), FString::FromInt(Reward.PersonLevel)}});
		}
		if (Reward.AgentLevel >= 0)
		{
			Row.ForCrew = Fill(Strings, TEXT("verse.ranks.record.for_crew"), {{TEXT("level"), FString::FromInt(Reward.AgentLevel)}});
		}
		Page.Ribbons.Add(Row);
	}
	return Page;
}

// ------------------------------------------------------------------ How to earn

FVerseRecordPages::FEarnPage FVerseRecordPages::Earn(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	FEarnPage Page;
	Page.Hint = Strings.Get(TEXT("verse.ranks.record.earn_hint"));
	const TPair<EVerseSubjectKind, const TCHAR*> Kinds[] = {
		{EVerseSubjectKind::Person, TEXT("person")},
		{EVerseSubjectKind::Agent, TEXT("agent")},
		{EVerseSubjectKind::Pet, TEXT("pet")},
	};
	for (const TPair<EVerseSubjectKind, const TCHAR*>& Kind : Kinds)
	{
		FEarnGroup Group;
		Group.Kind = Kind.Key;
		Group.Title = Strings.Get(FString::Printf(TEXT("verse.ranks.record.earn_%s"), Kind.Value));
		for (const FVerseXpRule& Rule : Model.Rules())
		{
			const FString Key = FString::Printf(TEXT("verse.ranks.rule.%s"), *Rule.Source.ToString());
			// A rule of a newer server has no words here and is left out.
			if (Rule.Kind != Kind.Key || Strings.GetIn(Key, TEXT("en")).IsEmpty())
			{
				continue;
			}
			FRuleRow Row;
			Row.Source = Rule.Source;
			Row.Text = Strings.Get(Key);
			TArray<FString> Limits;
			if (Rule.DailyCap > 0)
			{
				Limits.Add(Fill(Strings, TEXT("verse.ranks.limit.per_day"), {{TEXT("xp"), FString::FromInt(Rule.DailyCap)}}).ToString());
			}
			if (Rule.CooldownSeconds > 0)
			{
				Limits.Add(Fill(Strings, TEXT("verse.ranks.limit.cooldown"), {{TEXT("time"), CooldownText(Rule.CooldownSeconds)}}).ToString());
			}
			Row.Limits = FText::AsCultureInvariant(FString::Join(Limits, TEXT(" · ")));
			Row.Xp = FText::AsCultureInvariant(FString::Printf(TEXT("+%d"), Rule.Xp));
			Group.Rules.Add(Row);
		}
		if (Group.Rules.Num() > 0)
		{
			Page.Groups.Add(Group);
		}
	}
	return Page;
}

// ------------------------------------------------------------------ Crew

FVerseRecordPages::FCrewPage FVerseRecordPages::Crew(const FVerseServiceRecordModel& Model, const FVerseUiStrings& Strings)
{
	FCrewPage Page;
	Page.Empty = Strings.Get(TEXT("verse.ranks.record.crew_empty"));
	for (const FVerseSubjectRow& Subject : Model.Subjects())
	{
		if (Subject.Kind != EVerseSubjectKind::Agent)
		{
			continue;
		}
		FCrewRow Row;
		Row.SubjectId = Subject.SubjectId;
		const FString AgentId = Subject.SubjectId.Mid(Subject.SubjectId.Find(TEXT(":")) + 1);
		const FString* Name = Model.GetCrewNames().Find(AgentId);
		Row.Name = FText::AsCultureInvariant(Name ? *Name : AgentId);
		Row.Level = Subject.Level;
		Row.Xp = Subject.TotalXp;
		Row.RankId = FVerseServiceRecordModel::RankFor(Subject.Level).Id;
		Row.Rank = RankName(Strings, Row.RankId);
		Page.Rows.Add(Row);
	}
	Page.bNoOfficers = Page.Rows.Num() == 0;
	// Highest first, then by name.
	Page.Rows.Sort([](const FCrewRow& A, const FCrewRow& B)
	{
		return A.Xp != B.Xp ? A.Xp > B.Xp : A.Name.ToString() < B.Name.ToString();
	});
	const FVerseSubjectRow Drone = Model.Companion();
	FCrewRow Companion;
	Companion.SubjectId = Drone.SubjectId;
	Companion.bCompanion = true;
	Companion.Name = Model.GetCompanionName().IsEmpty() ? Strings.Get(TEXT("verse.ranks.record.companion")) : FText::AsCultureInvariant(Model.GetCompanionName());
	Companion.Level = Drone.Level;
	Companion.Xp = Drone.TotalXp;
	Companion.RankId = FVerseServiceRecordModel::RankFor(Drone.Level).Id;
	Companion.Rank = RankName(Strings, Companion.RankId);
	Page.Rows.Add(Companion);
	return Page;
}

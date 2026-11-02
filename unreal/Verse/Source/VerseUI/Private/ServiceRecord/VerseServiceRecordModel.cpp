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
		{TEXT("recruit"), 1, TEXT("deck")},
		{TEXT("deckhand"), 3, TEXT("deck")},
		{TEXT("technician"), 5, TEXT("deck")},
		{TEXT("senior_technician"), 8, TEXT("deck")},
		{TEXT("ensign"), 11, TEXT("line")},
		{TEXT("lieutenant"), 14, TEXT("line")},
		{TEXT("senior_lieutenant"), 17, TEXT("line")},
		{TEXT("commander"), 21, TEXT("line")},
		{TEXT("captain"), 25, TEXT("line")},
		{TEXT("line_captain"), 29, TEXT("command")},
		{TEXT("commodore"), 33, TEXT("command")},
		{TEXT("rear_admiral"), 37, TEXT("flag")},
		{TEXT("vice_admiral"), 41, TEXT("flag")},
		{TEXT("admiral"), 45, TEXT("flag")},
		{TEXT("fleet_admiral"), 50, TEXT("flag")},
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
	if (!Data.TryGetStringField(TEXT("subject_id"), Subject) || Subject != TEXT("person"))
	{
		return false;  // officers and the drone have their own surfaces
	}
	const int64 Seq = NumberOr(Data, TEXT("seq"), 0);
	const int32 Level = int32(NumberOr(Data, TEXT("level"), Record.Level));
	const int32 Previous = int32(NumberOr(Data, TEXT("previous_level"), Level));
	SetCommander(Level, NumberOr(Data, TEXT("total_xp"), Record.TotalXp), StringOr(Data, TEXT("title")));
	Latest = FMath::Max(Latest, Seq);

	bool bQueued = false;
	const bool bKnown = Promotions.ContainsByPredicate([Seq](const FVersePromotion& P) { return P.Seq == Seq; });
	if (Level > Previous && Seq > Told && !bKnown)
	{
		FVersePromotion Promotion;
		Promotion.Seq = Seq;
		Promotion.Level = Level;
		Promotion.PreviousLevel = Previous;
		Promotion.RankId = RankFor(Level).Id;
		Promotion.PreviousRankId = RankFor(Previous).Id;
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
	OnChanged.Broadcast();
	return bQueued;
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
}

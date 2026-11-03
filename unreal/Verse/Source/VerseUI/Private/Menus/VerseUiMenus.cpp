#include "Menus/VerseUiMenus.h"

#include "Internationalization/Culture.h"
#include "Internationalization/Internationalization.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

// ---------------------------------------------------------------------------------------------
// Armoury

FString FVerseArmouryModel::DefaultPath()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"), TEXT("armoury.json"));
}

bool FVerseArmouryModel::LoadFile(const FString& Path, FString* OutError)
{
	FString Json;
	if (!FFileHelper::LoadFileToString(Json, *Path))
	{
		if (OutError)
		{
			*OutError = FString::Printf(TEXT("cannot read %s"), *Path);
		}
		return false;
	}
	return LoadJson(Json, OutError);
}

bool FVerseArmouryModel::LoadJson(const FString& Json, FString* OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		if (OutError)
		{
			*OutError = TEXT("armoury.json is not JSON");
		}
		return false;
	}
	Tiers.Reset();
	const TArray<TSharedPtr<FJsonValue>>* TierList = nullptr;
	if (Root->TryGetArrayField(TEXT("tiers"), TierList))
	{
		for (const TSharedPtr<FJsonValue>& V : *TierList)
		{
			FString Tier;
			if (V.IsValid() && V->TryGetString(Tier))
			{
				Tiers.Add(FName(*Tier));
			}
		}
	}
	Loadout.Reset();
	const TArray<TSharedPtr<FJsonValue>>* Items = nullptr;
	if (Root->TryGetArrayField(TEXT("loadout"), Items))
	{
		const UEnum* SlotEnum = StaticEnum<EVerseLoadoutSlot>();
		for (const TSharedPtr<FJsonValue>& V : *Items)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!V.IsValid() || !V->TryGetObject(Obj))
			{
				continue;
			}
			FVerseArmouryItem Item;
			FString Slot;
			FString Id;
			(*Obj)->TryGetStringField(TEXT("slot"), Slot);
			(*Obj)->TryGetStringField(TEXT("item"), Id);
			(*Obj)->TryGetStringField(TEXT("kind"), Item.Kind);
			const int64 SlotValue = SlotEnum->GetValueByNameString(Slot);
			if (SlotValue == INDEX_NONE || Id.IsEmpty())
			{
				if (OutError)
				{
					*OutError = FString::Printf(TEXT("bad loadout entry %s / %s"), *Slot, *Id);
				}
				return false;
			}
			Item.Slot = EVerseLoadoutSlot(SlotValue);
			Item.ItemId = FName(*Id);
			Loadout.Add(Item);
		}
	}
	FString Default;
	if (Root->TryGetStringField(TEXT("default_tier"), Default))
	{
		SelectTier(FName(*Default));
	}
	return Tiers.Num() > 0 && Loadout.Num() > 0;
}

bool FVerseArmouryModel::SelectTier(FName Tier)
{
	if (!Tiers.Contains(Tier))
	{
		return false;
	}
	SelectedTier = Tier;
	return true;
}

void FVerseArmouryModel::CycleTier(int32 Direction)
{
	if (Tiers.Num() == 0)
	{
		return;
	}
	const int32 Index = FMath::Max(0, Tiers.IndexOfByKey(SelectedTier));
	SelectedTier = Tiers[(Index + Direction % Tiers.Num() + Tiers.Num()) % Tiers.Num()];
}

// ---------------------------------------------------------------------------------------------
// Verse bar

TArray<FVerseBarEntry> FVerseBarModel::Build(const TArray<FName>& Decks, FName CurrentDeck, bool bDuelRunning)
{
	TArray<FVerseBarEntry> Out;
	FVerseBarEntry Quick;
	Quick.Kind = EVerseBarEntryKind::QuickStartDuel;
	Quick.LabelKey = bDuelRunning ? TEXT("verse.bar.leave_duel") : TEXT("verse.bar.quick_duel");
	Quick.bActive = bDuelRunning;
	Out.Add(Quick);
	for (const FName& Deck : Decks)
	{
		FVerseBarEntry Entry;
		Entry.Kind = EVerseBarEntryKind::Deck;
		Entry.Id = Deck;
		Entry.LabelKey = FString::Printf(TEXT("verse.deck.%s"), *Deck.ToString().ToLower());
		Entry.bActive = Deck == CurrentDeck;
		// Leaving the hangar mid-duel goes through "leave duel" first.
		Entry.bEnabled = !bDuelRunning || Deck == CurrentDeck;
		Out.Add(Entry);
	}
	FVerseBarEntry Return;
	Return.Kind = EVerseBarEntryKind::ReturnToApp;
	Return.LabelKey = TEXT("verse.bar.return");
	Out.Add(Return);
	return Out;
}

// ---------------------------------------------------------------------------------------------
// End of set

FVerseEndScreen FVerseEndScreen::Build(const FVerseSetSummary& Summary, float BotEffectiveSkill, const FString& Lang)
{
	FVerseEndScreen Screen;
	Screen.Outcome = Summary.Outcome;
	Screen.TitleKey = Summary.Outcome == EVerseSetOutcome::Won ? TEXT("verse.end.won")
		: Summary.Outcome == EVerseSetOutcome::Lost ? TEXT("verse.end.lost")
		: TEXT("verse.end.unfinished");
	Screen.SetIndex = Summary.SetIndex;
	Screen.PersonKills = Summary.Person.Kills;
	Screen.OpponentKills = Summary.Opponent.Kills;
	Screen.Tier = Summary.BotTier;
	Screen.bShowSkill = Summary.BotTier == FName(TEXT("adaptive")) && BotEffectiveSkill >= 0.f;
	Screen.Skill = Screen.bShowSkill ? FMath::Clamp(BotEffectiveSkill, 0.f, 1.f) : -1.f;

	FCulturePtr Culture = FInternationalization::Get().GetCulture(Lang);
	if (!Culture.IsValid())
	{
		Culture = FInternationalization::Get().GetCulture(TEXT("en"));
	}
	auto Int = [Culture](int32 V) { return FText::AsNumber(V, &FNumberFormattingOptions::DefaultNoGrouping(), Culture); };
	auto Percent = [Culture](const FVerseSetLine& Line)
	{
		FNumberFormattingOptions Options;
		Options.MaximumFractionalDigits = 0;
		const double Ratio = Line.ShotsFired > 0 ? double(Line.ShotsHit) / Line.ShotsFired : 0.0;
		return FText::AsPercent(Ratio, &Options, Culture);
	};
	auto Ratio = [Culture](const FVerseSetLine& Line)
	{
		FNumberFormattingOptions Options;
		Options.MinimumFractionalDigits = 2;
		Options.MaximumFractionalDigits = 2;
		return FText::AsNumber(Line.Deaths > 0 ? double(Line.Kills) / Line.Deaths : double(Line.Kills), &Options, Culture);
	};
	const FVerseSetLine& P = Summary.Person;
	const FVerseSetLine& O = Summary.Opponent;
	Screen.Rows = {
		{TEXT("verse.end.row.kills"), Int(P.Kills), Int(O.Kills)},
		{TEXT("verse.end.row.deaths"), Int(P.Deaths), Int(O.Deaths)},
		{TEXT("verse.end.row.kd"), Ratio(P), Ratio(O)},
		{TEXT("verse.end.row.headshots"), Int(P.Headshots), Int(O.Headshots)},
		{TEXT("verse.end.row.finishers"), Int(P.Finishers), Int(O.Finishers)},
		{TEXT("verse.end.row.accuracy"), Percent(P), Percent(O)},
		{TEXT("verse.end.row.damage"), Int(P.DamageDealt), Int(O.DamageDealt)},
		{TEXT("verse.end.row.walls"), Int(P.WallsBreached), Int(O.WallsBreached)},
		{TEXT("verse.end.row.streak"), Int(P.BestStreak), Int(O.BestStreak)},
	};
	return Screen;
}

// ---------------------------------------------------------------------------------------------
// Session summary

namespace
{
	void AddLine(FVerseSetLine& Sum, const FVerseSetLine& Line)
	{
		Sum.PlayerId = Line.PlayerId;
		Sum.bIsBot = Line.bIsBot;
		Sum.Kills += Line.Kills;
		Sum.Deaths += Line.Deaths;
		Sum.Headshots += Line.Headshots;
		Sum.Finishers += Line.Finishers;
		Sum.MeleeKills += Line.MeleeKills;
		Sum.ShotsFired += Line.ShotsFired;
		Sum.ShotsHit += Line.ShotsHit;
		Sum.DamageDealt += Line.DamageDealt;
		Sum.DamageTaken += Line.DamageTaken;
		Sum.WallsBreached += Line.WallsBreached;
		Sum.BestStreak = FMath::Max(Sum.BestStreak, Line.BestStreak);
	}
}

void FVerseSessionSummary::AddSet(const FVerseSetSummary& Set)
{
	if (Set.Outcome == EVerseSetOutcome::Won)
	{
		++SetsWon;
	}
	else if (Set.Outcome == EVerseSetOutcome::Lost)
	{
		++SetsLost;
	}
	else
	{
		return;
	}
	AddLine(Totals.Person, Set.Person);
	AddLine(Totals.Opponent, Set.Opponent);
	Totals.BotTier = Set.BotTier;
	Totals.SetIndex = Set.SetIndex;
}

FVerseEndScreen FVerseSessionSummary::BuildScreen(const FString& Lang) const
{
	FVerseSetSummary Sum = Totals;
	Sum.Outcome = EVerseSetOutcome::Unfinished;
	FVerseEndScreen Screen = FVerseEndScreen::Build(Sum, -1.f, Lang);
	Screen.TitleKey = TEXT("verse.duel.result.cancelled");
	Screen.SetIndex = NumSets();
	Screen.PersonKills = SetsWon;
	Screen.OpponentKills = SetsLost;
	return Screen;
}

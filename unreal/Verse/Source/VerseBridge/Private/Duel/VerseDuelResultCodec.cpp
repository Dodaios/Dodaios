#include "Duel/VerseDuelResultCodec.h"

#include "Misc/ConfigCacheIni.h"
#include "Misc/EngineVersion.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace VerseDuel
{
	namespace
	{
		const TCHAR* const EndReasonNames[] = {
			TEXT("set_complete"),
			TEXT("player_left"),
			TEXT("verse_quit"),
			TEXT("crash_recovered"),
			TEXT("app_quit"),
		};

		bool IsWireTier(const FString& Tier)
		{
			return Tier == TEXT("normal") || Tier == TEXT("hard") || Tier == TEXT("elite");
		}

		/** Seconds rounded to the millisecond, so a float match time reads as the clock showed it. */
		double Millis(double Seconds)
		{
			return FMath::RoundToDouble(FMath::Max(0.0, Seconds) * 1000.0) / 1000.0;
		}

		void SetCount(FJsonObject& Object, const TCHAR* Name, int32 Value)
		{
			Object.SetNumberField(Name, double(FMath::Max(0, Value)));
		}
	}

	const TCHAR* EndReasonName(EEndReason Reason)
	{
		const int32 Index = int32(Reason);
		return Index >= 0 && Index < UE_ARRAY_COUNT(EndReasonNames) ? EndReasonNames[Index] : EndReasonNames[1];
	}

	bool ParseEndReason(const FString& Name, EEndReason& Out)
	{
		for (int32 Index = 0; Index < UE_ARRAY_COUNT(EndReasonNames); ++Index)
		{
			if (Name == EndReasonNames[Index])
			{
				Out = EEndReason(Index);
				return true;
			}
		}
		return false;
	}

	const TCHAR* OutcomeName(EVerseSetOutcome Outcome)
	{
		switch (Outcome)
		{
		case EVerseSetOutcome::Won:
			return TEXT("won");
		case EVerseSetOutcome::Lost:
			return TEXT("lost");
		default:
			return TEXT("unfinished");
		}
	}

	FBuildStamp FBuildStamp::Current()
	{
		FBuildStamp Stamp;
		if (GConfig)
		{
			GConfig->GetString(TEXT("/Script/EngineSettings.GeneralProjectSettings"), TEXT("ProjectVersion"), Stamp.Version, GGameIni);
		}
		if (Stamp.Version.IsEmpty())
		{
			Stamp.Version = TEXT("0.0.0");
		}
		const uint32 Changelist = FEngineVersion::Current().GetChangelist();
		Stamp.Changelist = Changelist != 0 ? FString::Printf(TEXT("%u"), Changelist) : FString(TEXT("local"));
		return Stamp;
	}

	FString WireId(FName Id)
	{
		FString Out = Id.ToString().ToLower();
		for (TCHAR& Char : Out)
		{
			const bool bOk = (Char >= TEXT('a') && Char <= TEXT('z')) || (Char >= TEXT('0') && Char <= TEXT('9')) || Char == TEXT('_');
			if (!bOk)
			{
				Char = TEXT('_');
			}
		}
		return Out.IsEmpty() ? FString(TEXT("unknown")) : Out;
	}

	EEndReason DefaultEndReason(const FVerseSetSummary& Summary)
	{
		return Summary.Outcome == EVerseSetOutcome::Unfinished ? EEndReason::PlayerLeft : EEndReason::SetComplete;
	}

	TSharedRef<FJsonObject> EncodeResult(const FVerseSetSummary& Summary, EEndReason EndReason, const FBuildStamp& Build)
	{
		// A finished set always completed; only an unfinished one carries a leave reason.
		if (Summary.Outcome != EVerseSetOutcome::Unfinished && EndReason != EEndReason::CrashRecovered)
		{
			EndReason = EEndReason::SetComplete;
		}
		else if (Summary.Outcome == EVerseSetOutcome::Unfinished && EndReason == EEndReason::SetComplete)
		{
			EndReason = EEndReason::PlayerLeft;
		}

		const FVerseSetLine& Person = Summary.Person;
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("match_id"), Summary.MatchId);
		Data->SetStringField(TEXT("session_id"), Summary.SessionId.IsEmpty() ? Summary.MatchId : Summary.SessionId);
		Data->SetNumberField(TEXT("set_index"), double(FMath::Max(1, Summary.SetIndex)));
		Data->SetStringField(TEXT("mode"), DeathmatchMode);
		Data->SetStringField(TEXT("ruleset"), Summary.RulesetId.IsNone() ? FString(TEXT("endless/1")) : Summary.RulesetId.ToString());

		TSharedRef<FJsonObject> Opponent = MakeShared<FJsonObject>();
		if (Summary.Opponent.bIsBot)
		{
			Opponent->SetStringField(TEXT("kind"), TEXT("bot"));
			const FString Tier = Summary.BotTier.IsNone() ? FString() : Summary.BotTier.ToString().ToLower();
			const bool bAdaptive = Tier == TEXT("adaptive");
			if (bAdaptive)
			{
				Opponent->SetStringField(TEXT("tier"), AdaptiveStartTier);
			}
			else if (IsWireTier(Tier))
			{
				Opponent->SetStringField(TEXT("tier"), Tier);
			}
			Opponent->SetBoolField(TEXT("adaptive"), bAdaptive);
		}
		else
		{
			Opponent->SetStringField(TEXT("kind"), TEXT("player"));
			Opponent->SetBoolField(TEXT("adaptive"), false);
		}
		Data->SetObjectField(TEXT("opponent"), Opponent);

		Data->SetNumberField(TEXT("started_at"), FMath::Max(0.0, Summary.StartedAtUnix));
		Data->SetNumberField(TEXT("ended_at"), FMath::Max(0.0, Summary.EndedAtUnix));
		Data->SetNumberField(TEXT("match_time_s"), Millis(Summary.MatchTimeS));
		Data->SetStringField(TEXT("end_reason"), EndReasonName(EndReason));
		Data->SetStringField(TEXT("outcome"), OutcomeName(Summary.Outcome));

		TSharedRef<FJsonObject> Score = MakeShared<FJsonObject>();
		SetCount(*Score, TEXT("player"), Person.Kills);
		SetCount(*Score, TEXT("opponent"), Summary.Opponent.Kills);
		Data->SetObjectField(TEXT("score"), Score);

		TSharedRef<FJsonObject> Stats = MakeShared<FJsonObject>();
		SetCount(*Stats, TEXT("kills"), Person.Kills);
		SetCount(*Stats, TEXT("deaths"), Person.Deaths);
		SetCount(*Stats, TEXT("headshots"), Person.Headshots);
		SetCount(*Stats, TEXT("finishers"), Person.Finishers);
		SetCount(*Stats, TEXT("melee_kills"), Person.MeleeKills);
		SetCount(*Stats, TEXT("shots_fired"), Person.ShotsFired);
		SetCount(*Stats, TEXT("shots_hit"), Person.ShotsHit);
		SetCount(*Stats, TEXT("damage_dealt"), Person.DamageDealt);
		SetCount(*Stats, TEXT("damage_taken"), Person.DamageTaken);
		SetCount(*Stats, TEXT("walls_breached"), Person.WallsBreached);
		SetCount(*Stats, TEXT("bulwarks_placed"), Person.BulwarksPlaced);
		SetCount(*Stats, TEXT("best_streak"), Person.BestStreak);
		Data->SetObjectField(TEXT("stats"), Stats);

		// Weapons in id order, so the same set always encodes to the same text.
		TArray<FName> WeaponIds;
		Person.PerWeapon.GetKeys(WeaponIds);
		WeaponIds.Sort([](const FName& A, const FName& B) { return A.LexicalLess(B); });
		TArray<TSharedPtr<FJsonValue>> Weapons;
		for (const FName& Id : WeaponIds)
		{
			const FIntVector4& Line = Person.PerWeapon.FindChecked(Id);
			TSharedRef<FJsonObject> Weapon = MakeShared<FJsonObject>();
			Weapon->SetStringField(TEXT("weapon_id"), WireId(Id));
			SetCount(*Weapon, TEXT("kills"), Line.X);
			SetCount(*Weapon, TEXT("headshots"), Line.Y);
			SetCount(*Weapon, TEXT("shots_fired"), Line.Z);
			SetCount(*Weapon, TEXT("shots_hit"), Line.W);
			Weapons.Add(MakeShared<FJsonValueObject>(Weapon));
		}
		Data->SetArrayField(TEXT("weapons"), Weapons);

		TSharedRef<FJsonObject> BuildObject = MakeShared<FJsonObject>();
		BuildObject->SetStringField(TEXT("version"), Build.Version.IsEmpty() ? FString(TEXT("0.0.0")) : Build.Version);
		BuildObject->SetStringField(TEXT("changelist"), Build.Changelist.IsEmpty() ? FString(TEXT("local")) : Build.Changelist);
		Data->SetObjectField(TEXT("build"), BuildObject);
		return Data;
	}

	FString ToJsonString(const TSharedRef<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer =
			TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object, Writer);
		return Out;
	}

	TSharedPtr<FJsonObject> FromJsonString(const FString& Text)
	{
		TSharedPtr<FJsonObject> Object;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Object))
		{
			return nullptr;
		}
		return Object;
	}
}

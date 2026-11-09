#include "Tiers/VerseBotTierData.h"

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Misc/Paths.h"
#include "Tiers/VerseBotJsonLite.h"
#include "UObject/Package.h"
#include "UObject/UnrealType.h"

// Named (not anonymous) so unity builds of VerseBot never collide with another file's helpers.
namespace VerseBotTierDataImpl
{
	/** The data fields of a class: its own UPROPERTYs, without TierId (the JSON key carries it). */
	TArray<const FProperty*> DataFields(const UClass* Class)
	{
		TArray<const FProperty*> Out;
		for (TFieldIterator<FProperty> It(Class, EFieldIteratorFlags::ExcludeSuper); It; ++It)
		{
			if (It->GetFName() != GET_MEMBER_NAME_CHECKED(UVerseBotTier, TierId))
			{
				Out.Add(*It);
			}
		}
		return Out;
	}

	bool IsVector2f(const FProperty* Prop)
	{
		const FStructProperty* StructProp = CastField<FStructProperty>(Prop);
		return StructProp && StructProp->Struct && StructProp->Struct->GetFName() == FName(TEXT("Vector2f"));
	}

	using VerseBotJsonLite::EType;
	using VerseBotJsonLite::FValue;

	/** Writes one JSON value into one property; false with an error line on a type mismatch. */
	bool ReadField(const FProperty* Prop, const FValue& Value, UObject& Out, const FString& Where, TArray<FString>& Errors)
	{
		const FString Name = Prop->GetName();
		if (const FFloatProperty* FloatProp = CastField<FFloatProperty>(Prop))
		{
			if (Value.Type != EType::Number)
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: expected a number"), *Where, *Name));
				return false;
			}
			FloatProp->SetPropertyValue_InContainer(&Out, float(Value.Number));
			return true;
		}
		if (const FIntProperty* IntProp = CastField<FIntProperty>(Prop))
		{
			if (Value.Type != EType::Number || Value.Number != FMath::RoundToDouble(Value.Number))
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: expected an integer"), *Where, *Name));
				return false;
			}
			IntProp->SetPropertyValue_InContainer(&Out, int32(Value.Number));
			return true;
		}
		if (IsVector2f(Prop))
		{
			if (Value.Type != EType::Array || Value.Array.Num() != 2 || Value.Array[0]->Type != EType::Number
				|| Value.Array[1]->Type != EType::Number)
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: expected a pair [a, b] of numbers"), *Where, *Name));
				return false;
			}
			FVector2f& Dest = *CastField<FStructProperty>(Prop)->ContainerPtrToValuePtr<FVector2f>(&Out);
			Dest = FVector2f(float(Value.Array[0]->Number), float(Value.Array[1]->Number));
			return true;
		}
		if (const FNameProperty* NameProp = CastField<FNameProperty>(Prop))
		{
			if (Value.Type != EType::String)
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: expected a string"), *Where, *Name));
				return false;
			}
			NameProp->SetPropertyValue_InContainer(&Out, FName(*Value.String));
			return true;
		}
		Errors.Add(FString::Printf(TEXT("%s.%s: field type is not supported by the reader"), *Where, *Name));
		return false;
	}

	/** Strict object read: every data field once, no unknown keys (IgnoreKeys excepted). */
	bool ReadObject(const FValue& Json, UObject& Out, const FString& Where, const TSet<FString>& IgnoreKeys, TArray<FString>& Errors)
	{
		const int32 ErrorsBefore = Errors.Num();
		if (Json.Type != EType::Object)
		{
			Errors.Add(FString::Printf(TEXT("%s: expected an object"), *Where));
			return false;
		}
		const TArray<const FProperty*> Fields = DataFields(Out.GetClass());
		TSet<FString> Known;
		for (const FProperty* Prop : Fields)
		{
			const FString Name = Prop->GetName();
			Known.Add(Name);
			const FValue* Value = Json.Find(Name);
			if (!Value)
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: missing"), *Where, *Name));
				continue;
			}
			ReadField(Prop, *Value, Out, Where, Errors);
		}
		for (const TPair<FString, TSharedRef<FValue>>& Pair : Json.Object)
		{
			if (!Known.Contains(Pair.Key) && !IgnoreKeys.Contains(Pair.Key))
			{
				Errors.Add(FString::Printf(TEXT("%s.%s: unknown field"), *Where, *Pair.Key));
			}
		}
		return Errors.Num() == ErrorsBefore;
	}

	TSharedPtr<FValue> ParseRoot(const FString& JsonText, const TCHAR* Schema, const TCHAR* FileName, TArray<FString>& Errors)
	{
		FString ParseError;
		TSharedPtr<FValue> Root = VerseBotJsonLite::Parse(JsonText, ParseError);
		if (!Root.IsValid() || Root->Type != EType::Object)
		{
			Errors.Add(FString::Printf(TEXT("%s: not valid JSON (%s)"), FileName, ParseError.IsEmpty() ? TEXT("not an object") : *ParseError));
			return nullptr;
		}
		const FValue* Got = Root->Find(TEXT("schema"));
		if (!Got || Got->Type != EType::String || Got->String != Schema)
		{
			Errors.Add(FString::Printf(TEXT("%s: schema must be \"%s\", got \"%s\""), FileName, Schema, Got ? *Got->String : TEXT("")));
			return nullptr;
		}
		return Root;
	}

	void CheckRange(TArray<FString>& Errors, const UVerseBotTier& T, const TCHAR* Field, float Value, float Min, float Max)
	{
		if (!(Value >= Min && Value <= Max))
		{
			Errors.Add(FString::Printf(TEXT("%s.%s = %g is outside [%g, %g]"), *T.TierId.ToString(), Field, Value, Min, Max));
		}
	}
}

namespace VerseBotTierData
{
	using namespace VerseBotTierDataImpl;

	const TArray<FName>& TierIds()
	{
		static const TArray<FName> Ids = {FName(TEXT("normal")), FName(TEXT("hard")), FName(TEXT("elite"))};
		return Ids;
	}

	FString TierPackagePath(FName TierId)
	{
		FString Suffix = TierId.ToString();
		if (!Suffix.IsEmpty())
		{
			Suffix[0] = FChar::ToUpper(Suffix[0]);
		}
		return FString::Printf(TEXT("/Game/Verse/Bot/Tiers/DA_BotTier_%s"), *Suffix);
	}

	FString AdaptivePackagePath()
	{
		return TEXT("/Game/Verse/Bot/Tiers/DA_BotAdaptive");
	}

	FString ObjectNameOf(const FString& PackagePath)
	{
		return FPaths::GetBaseFilename(PackagePath);
	}

	FString DefaultDataDir()
	{
		return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/bot"));
	}

	bool ReadTiers(const FString& JsonText, UObject* Outer, TMap<FName, UVerseBotTier*>& OutTiers, TArray<FString>& Errors)
	{
		const int32 ErrorsBefore = Errors.Num();
		const TSharedPtr<FValue> Root = ParseRoot(JsonText, TiersSchema, TEXT("tiers.json"), Errors);
		if (!Root.IsValid())
		{
			return false;
		}
		const FValue* TiersObject = Root->Find(TEXT("tiers"));
		if (!TiersObject || TiersObject->Type != EType::Object)
		{
			Errors.Add(TEXT("tiers.json: missing object \"tiers\""));
			return false;
		}
		for (const TPair<FString, TSharedRef<FValue>>& Pair : Root->Object)
		{
			if (Pair.Key != TEXT("schema") && Pair.Key != TEXT("tiers"))
			{
				Errors.Add(FString::Printf(TEXT("tiers.json: unknown top-level field \"%s\""), *Pair.Key));
			}
		}
		for (const TPair<FString, TSharedRef<FValue>>& Pair : TiersObject->Object)
		{
			if (!TierIds().Contains(FName(*Pair.Key)))
			{
				Errors.Add(FString::Printf(TEXT("tiers.json: unknown tier \"%s\""), *Pair.Key));
			}
		}
		UObject* Owner = Outer ? Outer : GetTransientPackage();
		for (const FName Id : TierIds())
		{
			const FValue* TierJson = TiersObject->Find(Id.ToString());
			if (!TierJson)
			{
				Errors.Add(FString::Printf(TEXT("tiers.json: missing tier \"%s\""), *Id.ToString()));
				continue;
			}
			UVerseBotTier* Tier = NewObject<UVerseBotTier>(Owner, NAME_None, RF_Transient);
			Tier->TierId = Id;
			ReadObject(*TierJson, *Tier, Id.ToString(), {}, Errors);
			ValidateTier(*Tier, Errors);
			OutTiers.Add(Id, Tier);
		}
		return Errors.Num() == ErrorsBefore;
	}

	bool ReadAdaptive(const FString& JsonText, UObject* Outer, UVerseBotAdaptiveConfig*& OutConfig, TArray<FString>& Errors)
	{
		const int32 ErrorsBefore = Errors.Num();
		OutConfig = nullptr;
		const TSharedPtr<FValue> Root = ParseRoot(JsonText, AdaptiveSchema, TEXT("adaptive.json"), Errors);
		if (!Root.IsValid())
		{
			return false;
		}
		UVerseBotAdaptiveConfig* Config = NewObject<UVerseBotAdaptiveConfig>(Outer ? Outer : GetTransientPackage(), NAME_None, RF_Transient);
		ReadObject(*Root, *Config, TEXT("adaptive"), {TEXT("schema")}, Errors);
		ValidateAdaptive(*Config, Errors);
		OutConfig = Config;
		return Errors.Num() == ErrorsBefore;
	}

	void ValidateTier(const UVerseBotTier& T, TArray<FString>& Errors)
	{
		const FString Id = T.TierId.ToString();
		// Contract floors and caps (bot.md frozen interface).
		if (T.WallbangMinBelief < UVerseBotTier::WallbangMinBeliefFloor)
		{
			Errors.Add(FString::Printf(TEXT("%s.WallbangMinBelief = %g is below the contract floor %g"), *Id, T.WallbangMinBelief,
				UVerseBotTier::WallbangMinBeliefFloor));
		}
		if (T.WallbangMaxSourceAgeS > UVerseBotTier::WallbangMaxSourceAgeCapS)
		{
			Errors.Add(FString::Printf(TEXT("%s.WallbangMaxSourceAgeS = %g is above the contract cap %g"), *Id, T.WallbangMaxSourceAgeS,
				UVerseBotTier::WallbangMaxSourceAgeCapS));
		}
		if (T.LearnWeightMax > UVerseBotTier::LearnWeightMaxCap)
		{
			Errors.Add(FString::Printf(TEXT("%s.LearnWeightMax = %g is above the contract cap %g"), *Id, T.LearnWeightMax,
				UVerseBotTier::LearnWeightMaxCap));
		}

		// Sanity ranges: the aim and reflex code divides by and samples with these.
		constexpr float Big = 1.0e6f;
		CheckRange(Errors, T, TEXT("ReactionMs.mean"), T.ReactionMs.X, 1.f, 5000.f);
		CheckRange(Errors, T, TEXT("ReactionMs.sd"), T.ReactionMs.Y, 0.f, T.ReactionMs.X);
		CheckRange(Errors, T, TEXT("PeripheralReactionMul"), T.PeripheralReactionMul, 1.f, 10.f);
		CheckRange(Errors, T, TEXT("PartialExposureAcquireMul"), T.PartialExposureAcquireMul, 1.f, 10.f);
		CheckRange(Errors, T, TEXT("TrackLatencyMs"), T.TrackLatencyMs, 0.f, 2000.f);
		CheckRange(Errors, T, TEXT("HearingErrorBaseM"), T.HearingErrorBaseM, 0.f, 50.f);
		CheckRange(Errors, T, TEXT("HearingErrorPerM"), T.HearingErrorPerM, 0.f, 5.f);
		CheckRange(Errors, T, TEXT("AimNoiseDeg"), T.AimNoiseDeg, 0.f, 45.f);
		CheckRange(Errors, T, TEXT("AimNoiseRate"), T.AimNoiseRate, 0.01f, 100.f);
		CheckRange(Errors, T, TEXT("AcquireErrorDeg"), T.AcquireErrorDeg, 0.f, 90.f);
		CheckRange(Errors, T, TEXT("AcquireMs"), T.AcquireMs, 1.f, 10000.f);
		CheckRange(Errors, T, TEXT("TurnRateDegS"), T.TurnRateDegS, 1.f, 10000.f);
		CheckRange(Errors, T, TEXT("AimStiffness"), T.AimStiffness, 0.01f, 1000.f);
		CheckRange(Errors, T, TEXT("LeadSkill"), T.LeadSkill, 0.f, 1.5f);
		CheckRange(Errors, T, TEXT("LeadNoise"), T.LeadNoise, 0.f, 2.f);
		CheckRange(Errors, T, TEXT("MotionWindowMs"), T.MotionWindowMs, 0.f, 2000.f);
		CheckRange(Errors, T, TEXT("RecoilPatternComp"), T.RecoilPatternComp, 0.f, 1.f);
		CheckRange(Errors, T, TEXT("RecoilResidualGain"), T.RecoilResidualGain, 0.f, 1.f);
		CheckRange(Errors, T, TEXT("FireTolerance"), T.FireTolerance, 0.1f, 20.f);
		CheckRange(Errors, T, TEXT("AdsRangeM"), T.AdsRangeM, 0.f, Big);
		CheckRange(Errors, T, TEXT("BurstRangeM"), T.BurstRangeM, 0.f, Big);
		CheckRange(Errors, T, TEXT("MaxBurstShots"), float(T.MaxBurstShots), 1.f, 1000.f);
		CheckRange(Errors, T, TEXT("DecisionMs"), T.DecisionMs, 16.f, 5000.f);
		CheckRange(Errors, T, TEXT("UtilityNoise"), T.UtilityNoise, 0.f, 1.f);
		CheckRange(Errors, T, TEXT("PreferredRangeM"), T.PreferredRangeM, 0.f, 200.f);
		CheckRange(Errors, T, TEXT("StrafeMs.min"), T.StrafeMs.X, 1.f, T.StrafeMs.Y);
		CheckRange(Errors, T, TEXT("NavLinkCostMul"), T.NavLinkCostMul, 0.1f, 100.f);
		CheckRange(Errors, T, TEXT("WallbangMinDamageFrac"), T.WallbangMinDamageFrac, 0.f, 1.f);
		CheckRange(Errors, T, TEXT("MaxStalkS"), T.MaxStalkS, 0.f, 120.f);
		CheckRange(Errors, T, TEXT("LearnSamplesHalf"), T.LearnSamplesHalf, 0.01f, Big);
		CheckRange(Errors, T, TEXT("HabitHalfLifeS"), T.HabitHalfLifeS, 1.f, Big);

		// Probabilities, shares and 0..1 weights.
		const TPair<const TCHAR*, float> Unit[] = {
			{TEXT("HeadAimChance"), T.HeadAimChance}, {TEXT("Aggression"), T.Aggression}, {TEXT("CoverUse"), T.CoverUse},
			{TEXT("FlankUse"), T.FlankUse}, {TEXT("LeanUse"), T.LeanUse}, {TEXT("CrouchPeekUse"), T.CrouchPeekUse},
			{TEXT("ProneUse"), T.ProneUse}, {TEXT("SlideUse"), T.SlideUse}, {TEXT("SoundDiscipline"), T.SoundDiscipline},
			{TEXT("PeekRepeatPenalty"), T.PeekRepeatPenalty}, {TEXT("BulwarkUse"), T.BulwarkUse}, {TEXT("BreachUse"), T.BreachUse},
			{TEXT("WallbangUse"), T.WallbangUse}, {TEXT("WallbangMinBelief"), T.WallbangMinBelief},
			{TEXT("PrefireChance"), T.PrefireChance}, {TEXT("StalkUse"), T.StalkUse},
			{TEXT("FinisherCommitConfidence"), T.FinisherCommitConfidence}, {TEXT("KnifeChoice"), T.KnifeChoice},
			{TEXT("TacticalReloadAtFrac"), T.TacticalReloadAtFrac}, {TEXT("ReloadOnlyWhenSafe"), T.ReloadOnlyWhenSafe},
			{TEXT("PistolSwitchChance"), T.PistolSwitchChance}, {TEXT("LearnWeightMax"), T.LearnWeightMax},
			{TEXT("ExplorationRate"), T.ExplorationRate},
		};
		for (const TPair<const TCHAR*, float>& Field : Unit)
		{
			CheckRange(Errors, T, Field.Key, Field.Value, 0.f, 1.f);
		}
		CheckRange(Errors, T, TEXT("WallbangMaxSourceAgeS"), T.WallbangMaxSourceAgeS, 0.f, UVerseBotTier::WallbangMaxSourceAgeCapS);
	}

	void ValidateAdaptive(const UVerseBotAdaptiveConfig& C, TArray<FString>& Errors)
	{
		auto Check = [&Errors](bool bOk, const FString& What)
		{
			if (!bOk)
			{
				Errors.Add(FString::Printf(TEXT("adaptive.%s"), *What));
			}
		};
		Check(C.StartSkill >= 0.f && C.StartSkill <= 1.f, FString::Printf(TEXT("StartSkill = %g is outside [0, 1]"), C.StartSkill));
		Check(C.WindowKills >= 1, FString::Printf(TEXT("WindowKills = %d must be at least 1"), C.WindowKills));
		Check(C.TargetPersonShare > 0.f && C.TargetPersonShare < 1.f,
			FString::Printf(TEXT("TargetPersonShare = %g is outside (0, 1)"), C.TargetPersonShare));
		Check(C.Deadband >= 0.f && C.Deadband < 0.5f, FString::Printf(TEXT("Deadband = %g is outside [0, 0.5)"), C.Deadband));
		Check(C.Gain > 0.f && C.Gain <= 10.f, FString::Printf(TEXT("Gain = %g is outside (0, 10]"), C.Gain));
		Check(C.MaxStepPerKill > 0.f && C.MaxStepPerKill <= AdaptiveMaxStepCap,
			FString::Printf(TEXT("MaxStepPerKill = %g is outside (0, %g]"), C.MaxStepPerKill, AdaptiveMaxStepCap));
		Check(C.WarmupKills >= 0, FString::Printf(TEXT("WarmupKills = %d must not be negative"), C.WarmupKills));
		Check(C.ApplyAt == FName(TEXT("bot_respawn")), FString::Printf(TEXT("ApplyAt = %s must be bot_respawn"), *C.ApplyAt.ToString()));
	}

	TArray<FString> DiffObjects(const UObject& A, const UObject& B)
	{
		TArray<FString> Diffs;
		if (A.GetClass() != B.GetClass())
		{
			Diffs.Add(FString::Printf(TEXT("class %s != %s"), *A.GetClass()->GetName(), *B.GetClass()->GetName()));
			return Diffs;
		}
		for (TFieldIterator<FProperty> It(A.GetClass(), EFieldIteratorFlags::ExcludeSuper); It; ++It)
		{
			const void* ValueA = It->ContainerPtrToValuePtr<void>(&A);
			const void* ValueB = It->ContainerPtrToValuePtr<void>(&B);
			if (!It->Identical(ValueA, ValueB, PPF_None))
			{
				FString TextA;
				FString TextB;
				It->ExportTextItem_Direct(TextA, ValueA, nullptr, nullptr, PPF_None);
				It->ExportTextItem_Direct(TextB, ValueB, nullptr, nullptr, PPF_None);
				Diffs.Add(FString::Printf(TEXT("%s: %s != %s"), *It->GetName(), *TextA, *TextB));
			}
		}
		return Diffs;
	}
}

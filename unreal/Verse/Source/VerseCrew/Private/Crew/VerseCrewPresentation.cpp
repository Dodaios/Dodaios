#include "Crew/VerseCrewPresentation.h"

#include "Dom/JsonObject.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"

namespace
{
	FVerseCrewDutyLook MakeDuty(EVerseCrewDuty Duty, EVerseCrewBeacon Beacon, const TCHAR* Hex, bool bOnDuty)
	{
		FVerseCrewDutyLook Look;
		Look.Duty = Duty;
		Look.Beacon = Beacon;
		Look.Colour = FLinearColor::FromSRGBColor(FColor::FromHex(Hex));
		Look.bOnDuty = bOnDuty;
		Look.LabelKey = FString::Printf(TEXT("verse.ranks.duty.%s"), VerseCrew::DutyName(Duty));
		return Look;
	}

	FVerseCrewRank MakeRank(const TCHAR* Id, int32 Level, const TCHAR* Tier, const TCHAR* Plate)
	{
		FVerseCrewRank Rank;
		Rank.Id = Id;
		Rank.Level = Level;
		Rank.Tier = Tier;
		for (const TCHAR* C = Plate; *C; ++C)
		{
			if (*C == TEXT('0') || *C == TEXT('1'))
			{
				Rank.PlateLit.Add(*C == TEXT('1'));
			}
		}
		return Rank;
	}

	bool ReadJson(const FString& Path, TSharedPtr<FJsonObject>& Out, FString& OutError)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			OutError = FString::Printf(TEXT("cannot read %s"), *Path);
			return false;
		}
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Out) || !Out.IsValid())
		{
			OutError = FString::Printf(TEXT("%s is not JSON"), *Path);
			return false;
		}
		return true;
	}

	EVerseCrewBeacon ParseBeacon(const FString& Text)
	{
		if (Text == TEXT("steady")) return EVerseCrewBeacon::Steady;
		if (Text == TEXT("slow_pulse")) return EVerseCrewBeacon::SlowPulse;
		return EVerseCrewBeacon::None;
	}
}

FVerseCrewPresentation::FVerseCrewPresentation()
{
	// Built-in values; Data/crew/duty_presentation.json carries the same and wins when present.
	Duties = {
		MakeDuty(EVerseCrewDuty::Working, EVerseCrewBeacon::Steady, TEXT("#d9a441"), true),
		MakeDuty(EVerseCrewDuty::Waiting, EVerseCrewBeacon::SlowPulse, TEXT("#e08a1e"), true),
		MakeDuty(EVerseCrewDuty::Idle, EVerseCrewBeacon::None, TEXT("#6b6e72"), false),
		MakeDuty(EVerseCrewDuty::Paused, EVerseCrewBeacon::None, TEXT("#4a4c50"), false),
		MakeDuty(EVerseCrewDuty::Error, EVerseCrewBeacon::SlowPulse, TEXT("#c8321e"), true),
	};
	Ladder = {
		MakeRank(TEXT("recruit"), 1, TEXT("deck"), TEXT("000|010")),
		MakeRank(TEXT("deckhand"), 3, TEXT("deck"), TEXT("000|101")),
		MakeRank(TEXT("technician"), 5, TEXT("deck"), TEXT("000|111")),
		MakeRank(TEXT("senior_technician"), 8, TEXT("deck"), TEXT("010|111")),
		MakeRank(TEXT("ensign"), 11, TEXT("line"), TEXT("010|000")),
		MakeRank(TEXT("lieutenant"), 14, TEXT("line"), TEXT("101|000")),
		MakeRank(TEXT("senior_lieutenant"), 17, TEXT("line"), TEXT("111|000")),
		MakeRank(TEXT("commander"), 21, TEXT("line"), TEXT("111|010")),
		MakeRank(TEXT("captain"), 25, TEXT("line"), TEXT("111|101")),
		MakeRank(TEXT("line_captain"), 29, TEXT("command"), TEXT("010|010")),
		MakeRank(TEXT("commodore"), 33, TEXT("command"), TEXT("101|010")),
		MakeRank(TEXT("rear_admiral"), 37, TEXT("flag"), TEXT("010|101")),
		MakeRank(TEXT("vice_admiral"), 41, TEXT("flag"), TEXT("101|101")),
		MakeRank(TEXT("admiral"), 45, TEXT("flag"), TEXT("101|111")),
		MakeRank(TEXT("fleet_admiral"), 50, TEXT("flag"), TEXT("111|111")),
	};
	auto Tier = [](const TCHAR* Id, const TCHAR* Uniform, const TCHAR* Hex) {
		FVerseCrewTierStyle Style;
		Style.Tier = Id;
		Style.Uniform = Uniform;
		Style.Tile = FLinearColor::FromSRGBColor(FColor::FromHex(Hex));
		return Style;
	};
	Tiers = {
		Tier(TEXT("deck"), TEXT("deck"), TEXT("#a9adb2")),
		Tier(TEXT("line"), TEXT("line"), TEXT("#d08a2e")),
		Tier(TEXT("command"), TEXT("command"), TEXT("#b8432f")),
		Tier(TEXT("flag"), TEXT("flag"), TEXT("#c8a24a")),
	};
}

FString FVerseCrewPresentation::DefaultDataDir()
{
	return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir() / TEXT("Data/crew"));
}

bool FVerseCrewPresentation::LoadFrom(const FString& Dir, FString& OutError)
{
	TSharedPtr<FJsonObject> Root;
	if (!ReadJson(Dir / TEXT("duty_presentation.json"), Root, OutError))
	{
		return false;
	}
	const TSharedPtr<FJsonObject>* Statuses = nullptr;
	if (Root->TryGetObjectField(TEXT("statuses"), Statuses) && Statuses)
	{
		for (FVerseCrewDutyLook& Look : Duties)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if (!(*Statuses)->TryGetObjectField(VerseCrew::DutyName(Look.Duty), Entry) || !Entry)
			{
				continue;
			}
			FString Text;
			if ((*Entry)->TryGetStringField(TEXT("beacon"), Text)) Look.Beacon = ParseBeacon(Text);
			if ((*Entry)->TryGetStringField(TEXT("colour"), Text)) Look.Colour = FLinearColor::FromSRGBColor(FColor::FromHex(Text));
			(*Entry)->TryGetBoolField(TEXT("on_duty"), Look.bOnDuty);
			double Pulse = 0.0;
			if ((*Entry)->TryGetNumberField(TEXT("pulse_s"), Pulse)) Look.PulseSeconds = static_cast<float>(Pulse);
		}
	}
	TSharedPtr<FJsonObject> RanksRoot;
	if (!ReadJson(Dir / TEXT("ranks.json"), RanksRoot, OutError))
	{
		return false;
	}
	const TArray<TSharedPtr<FJsonValue>>* RankValues = nullptr;
	if (RanksRoot->TryGetArrayField(TEXT("ranks"), RankValues) && RankValues->Num() > 0)
	{
		Ladder.Reset();
		for (const TSharedPtr<FJsonValue>& Value : *RankValues)
		{
			const TSharedPtr<FJsonObject> R = Value->AsObject();
			Ladder.Add(MakeRank(*R->GetStringField(TEXT("id")), static_cast<int32>(R->GetNumberField(TEXT("level"))),
				*R->GetStringField(TEXT("tier")), *R->GetStringField(TEXT("plate"))));
		}
	}
	const TSharedPtr<FJsonObject>* TierObject = nullptr;
	if (RanksRoot->TryGetObjectField(TEXT("tiers"), TierObject) && TierObject)
	{
		for (FVerseCrewTierStyle& Style : Tiers)
		{
			const TSharedPtr<FJsonObject>* Entry = nullptr;
			if ((*TierObject)->TryGetObjectField(Style.Tier, Entry) && Entry)
			{
				FString Text;
				if ((*Entry)->TryGetStringField(TEXT("uniform"), Text)) Style.Uniform = Text;
				if ((*Entry)->TryGetStringField(TEXT("tile"), Text)) Style.Tile = FLinearColor::FromSRGBColor(FColor::FromHex(Text));
			}
		}
	}
	return true;
}

const FVerseCrewDutyLook& FVerseCrewPresentation::DutyLook(EVerseCrewDuty Duty) const
{
	for (const FVerseCrewDutyLook& Look : Duties)
	{
		if (Look.Duty == Duty)
		{
			return Look;
		}
	}
	return Duties[2];
}

const FVerseCrewDutyLook& FVerseCrewPresentation::DutyLookOf(const FString& RawDuty) const
{
	return DutyLook(VerseCrew::ParseDuty(RawDuty));
}

const FVerseCrewRank& FVerseCrewPresentation::Rank(const FString& RankId) const
{
	for (const FVerseCrewRank& R : Ladder)
	{
		if (R.Id == RankId)
		{
			return R;
		}
	}
	return Ladder[0];
}

const FVerseCrewRank& FVerseCrewPresentation::RankForLevel(int32 Level) const
{
	const FVerseCrewRank* Held = &Ladder[0];
	for (const FVerseCrewRank& R : Ladder)
	{
		if (Level >= R.Level)
		{
			Held = &R;
		}
	}
	return *Held;
}

const FVerseCrewTierStyle& FVerseCrewPresentation::TierStyle(const FString& Tier) const
{
	for (const FVerseCrewTierStyle& Style : Tiers)
	{
		if (Style.Tier == Tier)
		{
			return Style;
		}
	}
	return Tiers[0];
}

FVerseCrewLook FVerseCrewPresentation::LookOf(const FVerseCrewMember& Member) const
{
	const FVerseCrewRank& R = Member.RankId.IsEmpty() ? RankForLevel(Member.Level) : Rank(Member.RankId);
	const FVerseCrewTierStyle& Style = TierStyle(R.Tier);
	FVerseCrewLook Look;
	Look.RankId = R.Id;
	Look.Tier = R.Tier;
	Look.Uniform = Style.Uniform;
	Look.Tile = Style.Tile;
	Look.PlateLit = R.PlateLit;
	const FString& Seed = Member.Role == EVerseCrewRole::Technician ? Member.HistoryId : (Member.Look.IsEmpty() ? Member.Id : Member.Look);
	Look.AccentHue = static_cast<float>(VerseCrew::Hash32(Seed + TEXT(":accent")) % 360u) / 360.f;
	return Look;
}

// ---------------------------------------------------------------------------------------------

FString FVerseCrewTuning::DefaultPath()
{
	return FPaths::ConvertRelativePathToFull(FPaths::ProjectDir() / TEXT("Data/crew/crew_tuning.json"));
}

bool FVerseCrewTuning::LoadFrom(const FString& Path, FString& OutError)
{
	TSharedPtr<FJsonObject> Root;
	if (!ReadJson(Path, Root, OutError))
	{
		return false;
	}
	auto Num = [&](const TCHAR* Field, float& Target) {
		double Value = 0.0;
		if (Root->TryGetNumberField(Field, Value))
		{
			Target = static_cast<float>(Value);
		}
	};
	Num(TEXT("replan_s"), ReplanSeconds);
	Num(TEXT("arrival_s"), ArrivalSeconds);
	Num(TEXT("walk_together_m"), WalkTogetherMetres);
	Num(TEXT("heel_m"), HeelMetres);
	Num(TEXT("walk_together_cooldown_s"), WalkTogetherCooldownSeconds);
	Num(TEXT("world_action_tick_s"), WorldActionTickSeconds);
	Num(TEXT("companion_pace_cm_s"), CompanionPaceCmS);
	Num(TEXT("companion_max_cm_s"), CompanionMaxCmS);
	Num(TEXT("companion_hover_cm"), CompanionHoverCm);
	Num(TEXT("crew_radius_cm"), CrewRadiusCm);
	Num(TEXT("separation_gain"), SeparationGain);
	Num(TEXT("stuck_s"), StuckSeconds);
	Num(TEXT("yield_s"), YieldSeconds);
	Num(TEXT("arrive_tolerance_cm"), ArriveToleranceCm);
	Num(TEXT("open_commands_per_s"), OpenCommandsPerSecond);
	Num(TEXT("sit_drop_cm"), SitDropCm);
	Num(TEXT("beacon_height_cm"), BeaconHeightCm);
	Num(TEXT("nameplate_height_cm"), NameplateHeightCm);
	Num(TEXT("salute_s"), SaluteSeconds);
	Num(TEXT("tick_budget_ms"), TickBudgetMs);
	Num(TEXT("tick_hard_cap_ms"), TickHardCapMs);
	double Pool = 0.0;
	if (Root->TryGetNumberField(TEXT("pawn_pool_size"), Pool))
	{
		PawnPoolSize = FMath::Max(0, static_cast<int32>(Pool));
	}
	const TArray<TSharedPtr<FJsonValue>>* Extent = nullptr;
	if (Root->TryGetArrayField(TEXT("nav_project_extent_cm"), Extent) && Extent->Num() == 3)
	{
		NavProjectExtentCm = FVector((*Extent)[0]->AsNumber(), (*Extent)[1]->AsNumber(), (*Extent)[2]->AsNumber());
	}
	const TArray<TSharedPtr<FJsonValue>>* Heel = nullptr;
	if (Root->TryGetArrayField(TEXT("companion_heel_offset_cm"), Heel) && Heel->Num() == 2)
	{
		CompanionHeelOffsetCm = FVector2D((*Heel)[0]->AsNumber(), (*Heel)[1]->AsNumber());
	}
	const TSharedPtr<FJsonObject>* Arena = nullptr;
	if (Root->TryGetObjectField(TEXT("arena_bounds_cm"), Arena) && Arena)
	{
		const TArray<TSharedPtr<FJsonValue>>* Min = nullptr;
		const TArray<TSharedPtr<FJsonValue>>* Max = nullptr;
		if ((*Arena)->TryGetArrayField(TEXT("min"), Min) && (*Arena)->TryGetArrayField(TEXT("max"), Max) && Min->Num() == 3 && Max->Num() == 3)
		{
			ArenaBoundsCm = FBox(FVector((*Min)[0]->AsNumber(), (*Min)[1]->AsNumber(), (*Min)[2]->AsNumber()),
				FVector((*Max)[0]->AsNumber(), (*Max)[1]->AsNumber(), (*Max)[2]->AsNumber()));
		}
	}
	Root->TryGetStringField(TEXT("body_mesh"), BodyMesh);
	return true;
}

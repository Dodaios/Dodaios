#include "Noise/VerseAudibilityTable.h"

#include "Destruction/VerseDestructionTypes.h"
#include "VerseGameplayTags.h"

namespace
{
	FVerseAudibilityRow MakeRow(const FGameplayTag& Noise, float RangeM, float ErrorMultiplier,
		bool bWholeArena = false, bool bScales = false)
	{
		FVerseAudibilityRow Row;
		Row.Noise = Noise;
		Row.RangeM = RangeM;
		Row.ErrorMultiplier = ErrorMultiplier;
		Row.bWholeArena = bWholeArena;
		Row.bRangeScalesWithLoudness = bScales;
		return Row;
	}
}

UVerseAudibilityTable::UVerseAudibilityTable()
{
	Rows = MakeContractRows();
}

TArray<FVerseAudibilityRow> UVerseAudibilityTable::MakeContractRows()
{
	using namespace VerseTags;
	const float FractureRange = Verse::Destruction::FractureRangePerLoudnessM;
	return {
		MakeRow(Noise_Shot, 0.f, 1.0f, true),
		MakeRow(Noise_Footstep_Sprint, 20.f, 1.3f),
		MakeRow(Noise_Footstep_Run, 10.f, 1.3f),
		MakeRow(Noise_Footstep_Walk, 4.f, 1.5f),
		MakeRow(Noise_Move_Slide, 12.f, 1.2f),
		MakeRow(Noise_Move_Land, 12.f, 1.2f),
		MakeRow(Noise_Move_Mantle, 12.f, 1.2f),
		MakeRow(Noise_Reload, 7.f, 1.0f),
		MakeRow(Noise_Gadget_BulwarkDeploy, 15.f, 1.0f),
		MakeRow(Noise_Gadget_BulwarkHum, 5.f, 1.0f),
		MakeRow(Noise_Gadget_BreachPlant, 10.f, 1.0f),
		MakeRow(Noise_Gadget_BreachDetonate, 0.f, 0.5f, true),
		MakeRow(Noise_Fracture, FractureRange, 1.0f, false, true),
		MakeRow(Noise_Drone, FractureRange, 1.0f, false, true),
		MakeRow(Noise_Melee, 8.f, 1.0f),
		MakeRow(Noise_Finisher, 8.f, 1.0f),
		// Bolt impact within 3 m of the listener: always heard, at the impact point.
		MakeRow(Noise_Impact, 3.f, 0.0f),
	};
}

const FVerseAudibilityRow* UVerseAudibilityTable::FindRow(const FGameplayTag& Noise) const
{
	return Rows.FindByPredicate([&Noise](const FVerseAudibilityRow& Row) { return Row.Noise == Noise; });
}

float UVerseAudibilityTable::GetAudibleRangeM(const FGameplayTag& Noise, float Loudness) const
{
	const FVerseAudibilityRow* Row = FindRow(Noise);
	if (!Row)
	{
		return 0.f;
	}
	if (Row->bWholeArena)
	{
		return WholeArenaRangeM;
	}
	return Row->bRangeScalesWithLoudness ? Row->RangeM * FMath::Max(0.f, Loudness) : Row->RangeM;
}

#include "Audio/VerseAudioMath.h"

#include "AudioDevice.h"
#include "Curves/RichCurve.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Noise/VerseAudibilityTable.h"
#include "Sound/SoundAttenuation.h"
#include "VerseGameplayTags.h"

namespace Verse::Audio
{
	float DbToGain(float Db)
	{
		return FMath::Pow(10.f, Db / 20.f);
	}

	FGameplayTag NoiseTagByName(FName TagName)
	{
		for (const FGameplayTag& Tag : VerseTags::AllNoiseTags())
		{
			if (Tag.GetTagName() == TagName)
			{
				return Tag;
			}
		}
		return FGameplayTag();
	}

	float DistanceGain(float DistanceM, float RangeM, const FVerseAudioMixSettings& Mix)
	{
		const float D = FMath::Max(0.f, DistanceM);
		const float Ref = FMath::Max(0.01f, Mix.ReferenceM);
		float Gain = D <= Ref ? 1.f : FMath::Pow(Ref / D, Mix.Rolloff);
		Gain = FMath::Max(Gain, DbToGain(Mix.FloorDb));
		if (RangeM <= 0.f)
		{
			return Gain;
		}
		if (D >= RangeM)
		{
			return 0.f;
		}
		const float Start = Mix.FadeStartFraction * RangeM;
		if (D > Start)
		{
			const float U = (D - Start) / FMath::Max(KINDA_SMALL_NUMBER, RangeM - Start);
			Gain *= 1.f - (3.f * U * U - 2.f * U * U * U);
		}
		return Gain;
	}

	float MaxAttenuationDistanceCm(float RangeM)
	{
		const float WorldMax = FAudioDevice::GetMaxWorldDistance();
		return FMath::Min(FMath::Max(0.f, RangeM) * 100.f, WorldMax);
	}

	void BuildAttenuation(float RangeM, const FVerseAudioMixSettings& Mix, FSoundAttenuationSettings& Out)
	{
		Out = FSoundAttenuationSettings();
		Out.bAttenuate = true;
		Out.bSpatialize = true;
		Out.bEnableOcclusion = false; // occlusion is traced through pieces by the subsystem
		Out.DistanceAlgorithm = EAttenuationDistanceModel::Custom;
		Out.AttenuationShape = EAttenuationShape::Sphere;
		Out.AttenuationShapeExtents = FVector::ZeroVector;
		const float RangeCm = MaxAttenuationDistanceCm(RangeM);
		Out.FalloffDistance = RangeCm;

		FRichCurve* Curve = Out.CustomAttenuationCurve.GetRichCurve();
		Curve->Reset();
		auto Key = [Curve](float Time, float Value)
		{
			const FKeyHandle Handle = Curve->AddKey(FMath::Clamp(Time, 0.f, 1.f), Value);
			Curve->SetKeyInterpMode(Handle, RCIM_Linear);
		};
		const float RangeEffM = FMath::Max(0.01f, RangeCm / 100.f);
		const float FadeStartM = Mix.FadeStartFraction * RangeEffM;
		Key(0.f, 1.f);
		for (float D = FMath::Max(0.05f, Mix.ReferenceM); D < FadeStartM; D *= 1.4f)
		{
			Key(D / RangeEffM, DistanceGain(D, RangeM, Mix));
		}
		constexpr int32 FadeKeys = 8;
		for (int32 I = 0; I < FadeKeys; ++I)
		{
			const float D = FadeStartM + (RangeEffM - FadeStartM) * float(I) / float(FadeKeys);
			Key(D / RangeEffM, DistanceGain(D, RangeM, Mix));
		}
		Key(1.f, 0.f); // the curve ends at 0, so the attenuation ends exactly at FalloffDistance

		const bool bFinite = RangeM < UVerseAudibilityTable::WholeArenaRangeM;
		Out.bAttenuateWithLPF = bFinite;
		Out.LPFRadiusMin = 0.35f * RangeCm;
		Out.LPFRadiusMax = RangeCm;
		Out.LPFFrequencyAtMin = 20000.f;
		Out.LPFFrequencyAtMax = 3500.f;
	}

	float ShotFarWeight(float DistanceM, const FVerseAudioMixSettings& Mix)
	{
		return FMath::SmoothStep(Mix.ShotNearFullM, Mix.ShotFarFullM, DistanceM);
	}

	float FractureLoudness(EVersePieceState From, EVersePieceState To, EVerseFractureCause Cause,
		EVersePenetrationMaterial Material)
	{
		if (Cause == EVerseFractureCause::Repair || Cause == EVerseFractureCause::Reset)
		{
			return 0.f;
		}
		switch (To)
		{
		case EVersePieceState::Damaged:
		case EVersePieceState::Holed:
			return Verse::Destruction::FractureLoudness(EVerseFractureNoise::BoltHole);
		case EVersePieceState::Breached:
		case EVersePieceState::Destroyed:
			if (Cause == EVerseFractureCause::Breach)
			{
				return Verse::Destruction::FractureLoudness(EVerseFractureNoise::Breach);
			}
			if (Material == EVersePenetrationMaterial::Glass)
			{
				return Verse::Destruction::FractureLoudness(EVerseFractureNoise::Glass);
			}
			if (Material == EVersePenetrationMaterial::CeilingPanel)
			{
				return Verse::Destruction::FractureLoudness(EVerseFractureNoise::Tile);
			}
			return Verse::Destruction::FractureLoudness(EVerseFractureNoise::WallBreak);
		default:
			return 0.f;
		}
	}

	FName DestructionCueFor(EVersePenetrationMaterial Material)
	{
		switch (Material)
		{
		case EVersePenetrationMaterial::ContainerWall: return TEXT("dst_container_wall");
		case EVersePenetrationMaterial::Glass: return TEXT("dst_glass_pane");
		case EVersePenetrationMaterial::CladdingPanel: return TEXT("dst_cladding_wall");
		case EVersePenetrationMaterial::CatwalkGrating: return TEXT("dst_catwalk_segment");
		case EVersePenetrationMaterial::CeilingPanel: return TEXT("dst_ceiling_panel");
		default: return TEXT("dst_wall_panel");
		}
	}

	FName SettleCueFor(EVersePenetrationMaterial Material)
	{
		switch (Material)
		{
		case EVersePenetrationMaterial::Glass: return TEXT("dst_settle_glass");
		case EVersePenetrationMaterial::CladdingPanel:
		case EVersePenetrationMaterial::CeilingPanel:
		case EVersePenetrationMaterial::Concrete: return TEXT("dst_settle_dust");
		default: return TEXT("dst_settle_metal");
		}
	}

	FName ImpactCueFor(EVersePenetrationMaterial Material)
	{
		switch (Material)
		{
		case EVersePenetrationMaterial::SheetMetal: return TEXT("imp_sheet_metal");
		case EVersePenetrationMaterial::ContainerWall: return TEXT("imp_container_wall");
		case EVersePenetrationMaterial::Glass: return TEXT("imp_glass");
		case EVersePenetrationMaterial::CladdingPanel: return TEXT("imp_cladding_panel");
		case EVersePenetrationMaterial::CatwalkGrating: return TEXT("imp_catwalk_grating");
		case EVersePenetrationMaterial::CeilingPanel: return TEXT("imp_ceiling_panel");
		case EVersePenetrationMaterial::Concrete: return TEXT("imp_concrete");
		case EVersePenetrationMaterial::ArmorSteel: return TEXT("imp_armor_steel");
		default: return TEXT("imp_concrete");
		}
	}

	bool BoltClosestApproach(const FVector& Origin, const FVector& Direction, const FVector& Listener,
		float BoltSpeedMps, float& OutDistanceM, float& OutTimeS, FVector& OutPoint)
	{
		const FVector Dir = Direction.GetSafeNormal();
		const double AlongCm = FVector::DotProduct(Listener - Origin, Dir);
		if (AlongCm <= 0.0 || Dir.IsNearlyZero())
		{
			return false;
		}
		OutPoint = Origin + Dir * AlongCm;
		OutDistanceM = float(FVector::Dist(Listener, OutPoint) / 100.0);
		OutTimeS = float(AlongCm / 100.0 / FMath::Max(1.f, BoltSpeedMps));
		return true;
	}

	FVerseOcclusion OcclusionFromHits(TConstArrayView<FVersePenetrationHit> Hits, const FVerseAudioMixSettings& Mix)
	{
		FVerseOcclusion Result;
		Result.LowpassHz = Mix.OpenLowpassHz;
		for (const FVersePenetrationHit& Hit : Hits)
		{
			const int32 Id = Hit.MaterialWireId;
			Result.LossDb += Mix.OcclusionLossDb.IsValidIndex(Id) ? Mix.OcclusionLossDb[Id] : -12.f;
			Result.LowpassHz = FMath::Min(Result.LowpassHz,
				Mix.OcclusionLowpassHz.IsValidIndex(Id) ? Mix.OcclusionLowpassHz[Id] : 1500.f);
			++Result.Pieces;
		}
		Result.LossDb = FMath::Max(Result.LossDb, Mix.OcclusionMaxLossDb);
		return Result;
	}

	FVerseOcclusion TraceOcclusion(const IVersePenetrationQuery* Query, const FVector& Listener,
		const FVector& Source, const FVerseAudioMixSettings& Mix)
	{
		FVerseOcclusion Open;
		Open.LowpassHz = Mix.OpenLowpassHz;
		const FVector Delta = Source - Listener;
		const double Dist = Delta.Size();
		if (!Query || Dist < 1.0)
		{
			return Open;
		}
		// Power high enough that the trace reports every piece it enters (at most 3); damage 0: a query only.
		const TArray<FVersePenetrationHit> Hits = Query->TraceBolt(Listener, Delta / Dist, float(Dist), 1.0e9f, 0.f, 0,
			Verse::Destruction::MaxPenetrations);
		return OcclusionFromHits(Hits, Mix);
	}
}

FVerseVoiceBudget::FDecision FVerseVoiceBudget::Request(FName CueId, float Priority, int32 CueMaxVoices, double Now)
{
	Prune(Now);
	FDecision Decision;
	if (CueMaxVoices > 0 && NumOf(CueId) >= CueMaxVoices)
	{
		const FVerseVoice* Oldest = nullptr;
		for (const FVerseVoice& Voice : Voices)
		{
			if (Voice.CueId == CueId && (!Oldest || Voice.StartTime < Oldest->StartTime))
			{
				Oldest = &Voice;
			}
		}
		Decision.bAdmit = true;
		Decision.StealHandle = Oldest ? Oldest->Handle : 0;
		return Decision;
	}
	if (Voices.Num() < Max)
	{
		Decision.bAdmit = true;
		return Decision;
	}
	const FVerseVoice* Victim = nullptr;
	for (const FVerseVoice& Voice : Voices)
	{
		if (!Victim || Voice.Priority < Victim->Priority
			|| (Voice.Priority == Victim->Priority && Voice.StartTime < Victim->StartTime))
		{
			Victim = &Voice;
		}
	}
	if (Victim && Victim->Priority <= Priority)
	{
		Decision.bAdmit = true;
		Decision.StealHandle = Victim->Handle;
	}
	return Decision;
}

void FVerseVoiceBudget::Add(const FVerseVoice& Voice)
{
	Voices.Add(Voice);
}

void FVerseVoiceBudget::Remove(int32 Handle)
{
	Voices.RemoveAll([Handle](const FVerseVoice& Voice) { return Voice.Handle == Handle; });
}

void FVerseVoiceBudget::Prune(double Now)
{
	Voices.RemoveAll([Now](const FVerseVoice& Voice) { return Voice.EndTime >= 0.0 && Voice.EndTime <= Now; });
}

int32 FVerseVoiceBudget::NumOf(FName CueId) const
{
	int32 Count = 0;
	for (const FVerseVoice& Voice : Voices)
	{
		Count += Voice.CueId == CueId ? 1 : 0;
	}
	return Count;
}

int32 FVerseVariantPicker::Pick(FName CueId, int32 Count)
{
	if (Count <= 1)
	{
		return 0;
	}
	const int32* LastPtr = Last.Find(CueId);
	const int32 Prev = LastPtr ? *LastPtr : INDEX_NONE;
	int32 Variant;
	if (Prev == INDEX_NONE)
	{
		Variant = Stream.RandRange(0, Count - 1);
	}
	else
	{
		Variant = Stream.RandRange(0, Count - 2);
		Variant += Variant >= Prev ? 1 : 0;
	}
	Last.Add(CueId, Variant);
	return Variant;
}

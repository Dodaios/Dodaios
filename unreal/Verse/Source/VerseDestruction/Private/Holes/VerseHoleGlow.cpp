#include "Holes/VerseHoleGlow.h"

namespace VerseHoleGlow
{
	namespace
	{
		// Incandescent steel: hue drifts from about 38 deg (white-amber) to about 6 deg (dull red).
		const FLinearColor WhiteAmber(1.0f, 0.78f, 0.46f);
		const FLinearColor Amber(1.0f, 0.42f, 0.08f);
		const FLinearColor DullRed(0.62f, 0.07f, 0.02f);
	}

	FLinearColor ColorAt(float AgeS)
	{
		const float Age = FMath::Max(0.f, AgeS);
		if (Age <= 1.f)
		{
			return FMath::Lerp(WhiteAmber, Amber, Age);
		}
		const float T = FMath::Clamp((Age - 1.f) / 1.5f, 0.f, 1.f);
		return FMath::Lerp(Amber, DullRed, T);
	}

	FVerseHoleGlowSample Sample(float AgeS, float TauS, float EndS)
	{
		FVerseHoleGlowSample Out;
		const float Age = FMath::Max(0.f, AgeS);
		if (Age >= EndS || TauS <= 0.f)
		{
			Out.Color = CharredColor();
			return Out;
		}
		const float FadeStart = EndS - EndFadeS;
		const float Fade = Age <= FadeStart ? 1.f : FMath::Clamp((EndS - Age) / EndFadeS, 0.f, 1.f);
		Out.Color = ColorAt(Age);
		Out.Intensity = FMath::Exp(-Age / TauS) * Fade;
		Out.bGlowing = Out.Intensity > 0.f;
		return Out;
	}

	FLinearColor CharredColor()
	{
		return FLinearColor(0.018f, 0.014f, 0.011f);
	}

	float AgeS(uint32 TimeMs, uint32 NowMs, uint32 MaxFutureMs)
	{
		if (TimeMs <= NowMs)
		{
			return (NowMs - TimeMs) / 1000.f;
		}
		// Within the skew window a record from the future is fresh; beyond it the clock that
		// stamped it is not this one, and the hole reads as long cooled.
		return TimeMs - NowMs <= MaxFutureMs ? 0.f : MAX_flt;
	}

	TArray<int32> SelectGlowing(TConstArrayView<uint32> TimesMs, uint32 NowMs, int32 Cap, float EndS, uint32 MaxFutureMs)
	{
		TArray<int32> Young;
		for (int32 Index = 0; Index < TimesMs.Num(); ++Index)
		{
			if (AgeS(TimesMs[Index], NowMs, MaxFutureMs) < EndS)
			{
				Young.Add(Index);
			}
		}
		// Newest first; ties keep the later record.
		Young.Sort([&TimesMs](int32 A, int32 B) { return TimesMs[A] != TimesMs[B] ? TimesMs[A] > TimesMs[B] : A > B; });
		if (Cap >= 0 && Young.Num() > Cap)
		{
			Young.SetNum(Cap);
		}
		return Young;
	}

	bool IsBannedPixel(const FColor& Srgb)
	{
		const float R = Srgb.R / 255.f;
		const float G = Srgb.G / 255.f;
		const float B = Srgb.B / 255.f;
		const float Max = FMath::Max3(R, G, B);
		const float Min = FMath::Min3(R, G, B);
		const float Delta = Max - Min;
		const float Value = Max;
		const float Saturation = Max > 0.f ? Delta / Max : 0.f;
		if (Delta <= 0.f || Saturation <= 0.25f || Value <= 0.08f)
		{
			return false;
		}
		float Hue;
		if (Max == R)
		{
			Hue = 60.f * FMath::Fmod((G - B) / Delta, 6.f);
		}
		else if (Max == G)
		{
			Hue = 60.f * ((B - R) / Delta + 2.f);
		}
		else
		{
			Hue = 60.f * ((R - G) / Delta + 4.f);
		}
		if (Hue < 0.f)
		{
			Hue += 360.f;
		}
		return Hue >= 160.f && Hue <= 330.f;
	}
}

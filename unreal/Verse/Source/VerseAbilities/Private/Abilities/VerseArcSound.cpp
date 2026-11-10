#include "Abilities/VerseArcSound.h"

namespace
{
	/** Per-sample smoothing toward a target with time constant `TauS` (WebAudio's setTargetAtTime). */
	float Smooth(float Value, float Target, float TauS, float SampleRate)
	{
		return Value + (Target - Value) * (1.f - FMath::Exp(-1.f / (TauS * SampleRate)));
	}
}

FVerseArcSynth::FVerseArcSynth(float InSampleRate)
	: SampleRate(FMath::Max(8000.f, InSampleRate))
{
	// Band-pass (RBJ cookbook, 0 dB peak) at 2.6 kHz, Q 0.7: the crackle's colour.
	const float W0 = 2.f * PI * 2600.f / SampleRate;
	const float Alpha = FMath::Sin(W0) / (2.f * 0.7f);
	const float A0 = 1.f + Alpha;
	B0 = Alpha / A0;
	B2 = -Alpha / A0;
	A1 = -2.f * FMath::Cos(W0) / A0;
	A2 = (1.f - Alpha) / A0;
}

void FVerseArcSynth::SetTargets(float Level, float InCrackle, float Volume)
{
	const float L = FMath::Clamp(Level, 0.f, 1.f);
	TargetOut.store(FMath::Clamp(Volume, 0.f, 1.f) * L, std::memory_order_relaxed);
	TargetHum.store(0.35f * L, std::memory_order_relaxed);
	TargetCrackle.store(FMath::Max(0.f, InCrackle), std::memory_order_relaxed);
}

void FVerseArcSynth::Render(float* Samples, int32 NumSamples)
{
	const float WantOut = TargetOut.load(std::memory_order_relaxed);
	const float WantHum = TargetHum.load(std::memory_order_relaxed);
	const float WantCrackle = TargetCrackle.load(std::memory_order_relaxed);
	// Hum: two detuned saws (55 and 56.3 Hz) through two one-pole low-passes at 420 Hz.
	const double Step[2] = {55.0 / SampleRate, 56.3 / SampleRate};
	const float LowK = 1.f - FMath::Exp(-2.f * PI * 420.f / SampleRate);
	for (int32 I = 0; I < NumSamples; ++I)
	{
		Out = Smooth(Out, WantOut, 0.04f, SampleRate);
		Hum = Smooth(Hum, WantHum, 0.05f, SampleRate);
		Crackle = Smooth(Crackle, WantCrackle, 0.01f, SampleRate);
		float Saw = 0.f;
		for (int32 O = 0; O < 2; ++O)
		{
			Phase[O] += Step[O];
			Phase[O] -= FMath::FloorToDouble(Phase[O]);
			Saw += 0.5f * float(2.0 * Phase[O] - 1.0);
		}
		Low[0] += (Saw - Low[0]) * LowK;
		Low[1] += (Low[0] - Low[1]) * LowK;
		// White noise (xorshift32) through the band-pass.
		Noise ^= Noise << 13;
		Noise ^= Noise >> 17;
		Noise ^= Noise << 5;
		const float X = float(double(Noise) / 2147483648.0 - 1.0);
		const float Y = B0 * X + B2 * X2 - A1 * Y1 - A2 * Y2;
		X2 = X1;
		X1 = X;
		Y2 = Y1;
		Y1 = Y;
		Samples[I] = FMath::Clamp(Out * (Hum * Low[1] + Crackle * Y), -1.f, 1.f);
	}
}

UVerseArcSoundWave::UVerseArcSoundWave(const FObjectInitializer& ObjectInitializer)
	: Super(ObjectInitializer)
	, Synth(48000.f)
{
	SetSampleRate(48000);
	NumChannels = 1;
	Duration = INDEFINITELY_LOOPING_DURATION;
	bLooping = true;
}

int32 UVerseArcSoundWave::OnGeneratePCMAudio(TArray<uint8>& OutAudio, int32 NumSamples)
{
	TArray<float, TInlineAllocator<2048>> Buffer;
	Buffer.SetNumUninitialized(NumSamples);
	Synth.Render(Buffer.GetData(), NumSamples);
	OutAudio.SetNumUninitialized(NumSamples * sizeof(int16));
	int16* Pcm = reinterpret_cast<int16*>(OutAudio.GetData());
	for (int32 I = 0; I < NumSamples; ++I)
	{
		Pcm[I] = int16(FMath::RoundToInt32(Buffer[I] * 32767.f));
	}
	return NumSamples;
}

#pragma once

#include "CoreMinimal.h"
#include "Sound/SoundWaveProcedural.h"

#include <atomic>

#include "VerseArcSound.generated.h"

/**
 * Arc Storm's sound, synthesised (parity Z-07, reference `abilities/arcSound.ts`):
 * a low electric hum (two detuned saws, low-passed) under a crackle of
 * band-passed noise whose loudness jumps with every strike. Own work, no
 * recorded sample. The game thread sets targets; the audio thread renders.
 */
struct VERSEABILITIES_API FVerseArcSynth
{
	explicit FVerseArcSynth(float InSampleRate = 48000.f);

	/** Targets from the game thread: `Level` 0..1 is how far the power is up, `Crackle` the strike loudness. */
	void SetTargets(float Level, float Crackle, float Volume);

	/** Mono samples in [-1, 1]. */
	void Render(float* Out, int32 NumSamples);

	float GetSampleRate() const { return SampleRate; }

private:
	float SampleRate;
	std::atomic<float> TargetOut{0.f};
	std::atomic<float> TargetHum{0.f};
	std::atomic<float> TargetCrackle{0.f};
	float Out = 0.f;
	float Hum = 0.f;
	float Crackle = 0.f;
	double Phase[2] = {0.0, 0.37};
	float Low[2] = {0.f, 0.f};
	/** Band-pass biquad state (2.6 kHz, Q 0.7). */
	float B0 = 0.f, B2 = 0.f, A1 = 0.f, A2 = 0.f;
	float X1 = 0.f, X2 = 0.f, Y1 = 0.f, Y2 = 0.f;
	uint32 Noise = 0x9e3779b9u;
};

/** The procedural wave an audio component plays: pulls samples from an `FVerseArcSynth`. */
UCLASS()
class VERSEABILITIES_API UVerseArcSoundWave : public USoundWaveProcedural
{
	GENERATED_BODY()

public:
	UVerseArcSoundWave(const FObjectInitializer& ObjectInitializer);

	void SetTargets(float Level, float Crackle, float OutVolume) { Synth.SetTargets(Level, Crackle, OutVolume); }

protected:
	virtual int32 OnGeneratePCMAudio(TArray<uint8>& OutAudio, int32 NumSamples) override;

private:
	FVerseArcSynth Synth;
};

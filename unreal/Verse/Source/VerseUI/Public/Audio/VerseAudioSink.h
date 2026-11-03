#pragma once

#include "CoreMinimal.h"

enum class EVerseAudioBus : uint8;
class USoundBase;
class USoundAttenuation;
class UWorld;
struct FVerseAudioMixSettings;

/** One voice to start. */
struct FVerseAudioPlayRequest
{
	FName CueId;
	USoundBase* Sound = nullptr;
	bool bSpatial = false;
	FVector Location = FVector::ZeroVector;
	USoundAttenuation* Attenuation = nullptr;
	/** The voice's volume multiplier: cue volume x gain x bus x master. Never changes after the start. */
	float Volume = 1.f;
	/**
	 * The voice's fader at the start: the occlusion gain. Only the fader moves later
	 * (SetVoiceOcclusion), so the heard level is always Volume x the current fader.
	 */
	float Fader = 1.f;
	float Pitch = 1.f;
	float LowpassHz = 20000.f;
};

/**
 * Where the audio subsystem sends its voices. The engine sink plays them through audio components
 * on the Verse master submix; tests use a recording fake (Private/Tests/Audio/Fakes).
 */
class IVerseAudioSink
{
public:
	virtual ~IVerseAudioSink() = default;

	/** Builds the master submix with its limiter; false when there is no audio device. */
	virtual bool Initialize(UWorld* World, const FVerseAudioMixSettings& Mix) = 0;
	/** Starts a voice under the given handle (handles come from the subsystem). */
	virtual void Play(int32 Handle, const FVerseAudioPlayRequest& Request) = 0;
	virtual void Stop(int32 Handle, float FadeOutS) = 0;
	virtual void SetVoiceLocation(int32 Handle, const FVector& Location) = 0;
	/** Occlusion of a running voice: sets its fader to Gain (not its multiplier) and its low-pass. */
	virtual void SetVoiceOcclusion(int32 Handle, float Gain, float LowpassHz) = 0;
	/** Linear gain of the whole Verse (master gain x user volume x mute). */
	virtual void SetMasterVolume(float Volume) = 0;
	/** Route a sound to its bus submix (a child of the Verse master submix). */
	virtual void Route(USoundBase* Sound, EVerseAudioBus Bus) = 0;
	virtual void Shutdown() = 0;
};

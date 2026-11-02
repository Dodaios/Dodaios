#pragma once

#include "Audio/VerseAudioSink.h"
#include "CoreMinimal.h"
#include "UObject/GCObject.h"
#include "UObject/WeakObjectPtr.h"

class UAudioComponent;
class USoundSubmix;

/**
 * Plays voices through audio components. All Verse sounds route to one transient master submix
 * whose effect chain is a look-ahead limiter (mix.json limiter); the mute and the user volume are
 * the device's transient primary volume, after the limiter.
 */
class FVerseEngineAudioSink final : public IVerseAudioSink, public FGCObject
{
public:
	virtual bool Initialize(UWorld* World, const FVerseAudioMixSettings& Mix) override;
	virtual void Play(int32 Handle, const FVerseAudioPlayRequest& Request) override;
	virtual void Stop(int32 Handle, float FadeOutS) override;
	virtual void SetVoiceLocation(int32 Handle, const FVector& Location) override;
	virtual void SetVoiceVolume(int32 Handle, float Volume, float LowpassHz) override;
	virtual void SetMasterVolume(float Volume) override;
	virtual void Route(USoundBase* Sound) override;
	virtual void Shutdown() override;

	virtual void AddReferencedObjects(FReferenceCollector& Collector) override;
	virtual FString GetReferencerName() const override { return TEXT("FVerseEngineAudioSink"); }

	/** The limiter preset for these settings; nullptr when the audio mixer module is not loaded. */
	static class USoundEffectSubmixPreset* MakeLimiterPreset(UObject* Outer, const FVerseAudioMixSettings& Mix);

private:
	TWeakObjectPtr<UWorld> World;
	TObjectPtr<USoundSubmix> MasterSubmix = nullptr;
	TMap<int32, TWeakObjectPtr<UAudioComponent>> Voices;
};

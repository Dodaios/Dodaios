#pragma once

#include "Audio/VerseAudioSink.h"
#include "CoreMinimal.h"
#include "UObject/GCObject.h"
#include "UObject/WeakObjectPtr.h"

class UAudioComponent;
class USoundSubmix;

/**
 * Plays voices through audio components. Every Verse sound routes to the transient submix of its
 * bus (weapons, impacts, foley, destruction, gadgets, ambience, UI); the bus submixes feed one
 * master submix whose effect chain is a look-ahead limiter (mix.json limiter). The mute and the
 * user volume are the device's transient primary volume, after the limiter.
 *
 * A voice's volume multiplier is set once at the start; occlusion moves only the component's
 * fader, so the engine's level (multiplier x fader) never counts the base volume twice.
 */
class FVerseEngineAudioSink final : public IVerseAudioSink, public FGCObject
{
public:
	virtual bool Initialize(UWorld* World, const FVerseAudioMixSettings& Mix) override;
	virtual void Play(int32 Handle, const FVerseAudioPlayRequest& Request) override;
	virtual void Stop(int32 Handle, float FadeOutS) override;
	virtual void SetVoiceLocation(int32 Handle, const FVector& Location) override;
	virtual void SetVoiceOcclusion(int32 Handle, float Gain, float LowpassHz) override;
	virtual void SetMasterVolume(float Volume) override;
	virtual void Route(USoundBase* Sound, EVerseAudioBus Bus) override;
	virtual void Shutdown() override;

	virtual void AddReferencedObjects(FReferenceCollector& Collector) override;
	virtual FString GetReferencerName() const override { return TEXT("FVerseEngineAudioSink"); }

	/** The limiter preset for these settings; nullptr when the audio mixer module is not loaded. */
	static class USoundEffectSubmixPreset* MakeLimiterPreset(UObject* Outer, const FVerseAudioMixSettings& Mix);

	/** Voices the sink still tracks; finished one-shots are pruned. */
	int32 NumTrackedVoices() const { return Voices.Num(); }
	USoundSubmix* GetMasterSubmix() const { return MasterSubmix; }
	/** The submix of a bus; the master when the bus has none. */
	USoundSubmix* GetBusSubmix(EVerseAudioBus Bus) const;

private:
	/** Drops voices whose component finished or is gone; one-shots are never stopped by hand. */
	void PruneFinished();

	TWeakObjectPtr<UWorld> World;
	TObjectPtr<USoundSubmix> MasterSubmix = nullptr;
	TArray<TObjectPtr<USoundSubmix>> BusSubmixes;
	TMap<int32, TWeakObjectPtr<UAudioComponent>> Voices;
	int32 PlaysSincePrune = 0;
};

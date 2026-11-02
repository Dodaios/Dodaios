#include "VerseEngineAudioSink.h"

#include "Audio/VerseAudioTypes.h"
#include "AudioDevice.h"
#include "Components/AudioComponent.h"
#include "Engine/World.h"
#include "Kismet/GameplayStatics.h"
#include "Modules/ModuleManager.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundBase.h"
#include "Sound/SoundEffectSubmix.h"
#include "Sound/SoundSubmix.h"
#include "VerseLog.h"

namespace
{
	bool SetFloatField(const UScriptStruct* Struct, void* Data, const TCHAR* Name, float Value)
	{
		const FFloatProperty* Prop = FindFProperty<FFloatProperty>(Struct, Name);
		if (!Prop)
		{
			return false;
		}
		Prop->SetPropertyValue_InContainer(Data, Value);
		return true;
	}

	bool SetEnumField(const UScriptStruct* Struct, void* Data, const TCHAR* Name, const TCHAR* ValueName)
	{
		const FEnumProperty* Prop = FindFProperty<FEnumProperty>(Struct, Name);
		if (!Prop || !Prop->GetEnum())
		{
			return false;
		}
		const int64 Value = Prop->GetEnum()->GetValueByNameString(ValueName);
		if (Value == INDEX_NONE)
		{
			return false;
		}
		Prop->GetUnderlyingProperty()->SetIntPropertyValue(Prop->ContainerPtrToValuePtr<void>(Data), Value);
		return true;
	}
}

USoundEffectSubmixPreset* FVerseEngineAudioSink::MakeLimiterPreset(UObject* Outer, const FVerseAudioMixSettings& Mix)
{
	// The dynamics processor lives in the AudioMixer module, which VerseUI does not link
	// (architecture 2 edges); it is configured through reflection, by its stable property names.
	static const TCHAR* ClassPath = TEXT("/Script/AudioMixer.SubmixEffectDynamicsProcessorPreset");
	UClass* PresetClass = FindObject<UClass>(nullptr, ClassPath);
	if (!PresetClass && FModuleManager::Get().ModuleExists(TEXT("AudioMixer")))
	{
		FModuleManager::Get().LoadModule(TEXT("AudioMixer"));
		PresetClass = FindObject<UClass>(nullptr, ClassPath);
	}
	if (!PresetClass || !PresetClass->IsChildOf(USoundEffectSubmixPreset::StaticClass()))
	{
		return nullptr;
	}
	USoundEffectSubmixPreset* Preset = NewObject<USoundEffectSubmixPreset>(Outer, PresetClass, NAME_None, RF_Transient);
	const FStructProperty* SettingsProp = FindFProperty<FStructProperty>(PresetClass, TEXT("Settings"));
	if (!SettingsProp)
	{
		return nullptr;
	}
	void* Settings = SettingsProp->ContainerPtrToValuePtr<void>(Preset);
	const UScriptStruct* Struct = SettingsProp->Struct;
	const bool bOk = SetEnumField(Struct, Settings, TEXT("DynamicsProcessorType"), TEXT("Limiter"))
		&& SetEnumField(Struct, Settings, TEXT("PeakMode"), TEXT("Peak"))
		&& SetFloatField(Struct, Settings, TEXT("ThresholdDb"), Mix.LimiterThresholdDb)
		&& SetFloatField(Struct, Settings, TEXT("LookAheadMsec"), Mix.LimiterLookaheadMs)
		&& SetFloatField(Struct, Settings, TEXT("AttackTimeMsec"), Mix.LimiterAttackMs)
		&& SetFloatField(Struct, Settings, TEXT("ReleaseTimeMsec"), Mix.LimiterReleaseMs);
	if (!bOk)
	{
		UE_LOG(LogVerseUI, Warning, TEXT("Verse audio: dynamics processor settings changed shape; no limiter"));
		return nullptr;
	}
	Preset->Init(); // copies Settings into the preset's runtime copy
	return Preset;
}

bool FVerseEngineAudioSink::Initialize(UWorld* InWorld, const FVerseAudioMixSettings& Mix)
{
	World = InWorld;
	FAudioDevice* Device = InWorld ? InWorld->GetAudioDeviceRaw() : nullptr;
	if (!Device)
	{
		return false;
	}
	MasterSubmix = NewObject<USoundSubmix>(GetTransientPackage(), TEXT("VerseMasterSubmix"), RF_Transient);
	if (USoundEffectSubmixPreset* Limiter = MakeLimiterPreset(MasterSubmix, Mix))
	{
		MasterSubmix->SubmixEffectChain.Add(Limiter);
	}
	Device->RegisterSoundSubmix(MasterSubmix, true);
	return true;
}

void FVerseEngineAudioSink::Play(int32 Handle, const FVerseAudioPlayRequest& Request)
{
	UWorld* W = World.Get();
	if (!W || !Request.Sound)
	{
		return;
	}
	UAudioComponent* Component = Request.bSpatial
		? UGameplayStatics::SpawnSoundAtLocation(W, Request.Sound, Request.Location, FRotator::ZeroRotator,
			  Request.Volume, Request.Pitch, 0.f, Request.Attenuation, nullptr, true)
		: UGameplayStatics::SpawnSound2D(W, Request.Sound, Request.Volume, Request.Pitch, 0.f, nullptr, false, true);
	if (!Component)
	{
		return; // no audio device (-nosound): the subsystem still logged the play
	}
	if (Request.LowpassHz < 19999.f)
	{
		Component->SetLowPassFilterEnabled(true);
		Component->SetLowPassFilterFrequency(Request.LowpassHz);
	}
	Voices.Add(Handle, Component);
}

void FVerseEngineAudioSink::Stop(int32 Handle, float FadeOutS)
{
	if (TWeakObjectPtr<UAudioComponent>* Found = Voices.Find(Handle))
	{
		if (UAudioComponent* Component = Found->Get())
		{
			if (FadeOutS > 0.f)
			{
				Component->FadeOut(FadeOutS, 0.f);
			}
			else
			{
				Component->Stop();
			}
		}
		Voices.Remove(Handle);
	}
}

void FVerseEngineAudioSink::SetVoiceLocation(int32 Handle, const FVector& Location)
{
	if (TWeakObjectPtr<UAudioComponent>* Found = Voices.Find(Handle))
	{
		if (UAudioComponent* Component = Found->Get())
		{
			Component->SetWorldLocation(Location);
		}
	}
}

void FVerseEngineAudioSink::SetVoiceVolume(int32 Handle, float Volume, float LowpassHz)
{
	if (TWeakObjectPtr<UAudioComponent>* Found = Voices.Find(Handle))
	{
		if (UAudioComponent* Component = Found->Get())
		{
			Component->AdjustVolume(0.1f, Volume);
			Component->SetLowPassFilterEnabled(LowpassHz < 19999.f);
			Component->SetLowPassFilterFrequency(LowpassHz);
		}
	}
}

void FVerseEngineAudioSink::SetMasterVolume(float Volume)
{
	if (UWorld* W = World.Get())
	{
		if (FAudioDevice* Device = W->GetAudioDeviceRaw())
		{
			Device->SetTransientPrimaryVolume(Volume);
		}
	}
}

void FVerseEngineAudioSink::Route(USoundBase* Sound)
{
	if (Sound && MasterSubmix)
	{
		Sound->SoundSubmixObject = MasterSubmix;
	}
}

void FVerseEngineAudioSink::Shutdown()
{
	for (TPair<int32, TWeakObjectPtr<UAudioComponent>>& Pair : Voices)
	{
		if (UAudioComponent* Component = Pair.Value.Get())
		{
			Component->Stop();
		}
	}
	Voices.Reset();
	if (UWorld* W = World.Get())
	{
		if (FAudioDevice* Device = W->GetAudioDeviceRaw())
		{
			Device->SetTransientPrimaryVolume(1.f);
			if (MasterSubmix)
			{
				Device->UnregisterSoundSubmix(MasterSubmix, false);
			}
		}
	}
	MasterSubmix = nullptr;
}

void FVerseEngineAudioSink::AddReferencedObjects(FReferenceCollector& Collector)
{
	Collector.AddReferencedObject(MasterSubmix);
}

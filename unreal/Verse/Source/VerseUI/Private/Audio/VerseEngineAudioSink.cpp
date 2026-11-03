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
#include "UObject/Package.h"
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
	UPackage* Transient = GetTransientPackage();
	MasterSubmix = NewObject<USoundSubmix>(Transient,
		MakeUniqueObjectName(Transient, USoundSubmix::StaticClass(), TEXT("VerseMasterSubmix")), RF_Transient);
	if (USoundEffectSubmixPreset* Limiter = MakeLimiterPreset(MasterSubmix, Mix))
	{
		MasterSubmix->SubmixEffectChain.Add(Limiter);
	}
	// One child submix per bus under the master, in EVerseAudioBus order. The bus gain of mix.json
	// stays on the voice multiplier, where the subsystem log and the reference mix see it.
	BusSubmixes.Reset();
	const UEnum* BusEnum = StaticEnum<EVerseAudioBus>();
	for (int32 Bus = 0; Bus < VerseAudioBusCount; ++Bus)
	{
		const FString Name = FString::Printf(TEXT("VerseBus_%s"),
			BusEnum ? *BusEnum->GetNameStringByValue(Bus) : *FString::FromInt(Bus));
		USoundSubmix* Child = NewObject<USoundSubmix>(Transient,
			MakeUniqueObjectName(Transient, USoundSubmix::StaticClass(), FName(*Name)), RF_Transient);
		Child->ParentSubmix = MasterSubmix;
		MasterSubmix->ChildSubmixes.Add(Child);
		BusSubmixes.Add(Child);
	}
	Device->RegisterSoundSubmix(MasterSubmix, true);
	for (USoundSubmix* Child : BusSubmixes)
	{
		Device->RegisterSoundSubmix(Child, true);
	}
	return true;
}

void FVerseEngineAudioSink::Play(int32 Handle, const FVerseAudioPlayRequest& Request)
{
	UWorld* W = World.Get();
	if (!W || !Request.Sound)
	{
		return;
	}
	if (++PlaysSincePrune >= 32)
	{
		PruneFinished();
	}
	UAudioComponent* Component = Request.bSpatial
		? UGameplayStatics::SpawnSoundAtLocation(W, Request.Sound, Request.Location, FRotator::ZeroRotator,
			  Request.Volume, Request.Pitch, 0.f, Request.Attenuation, nullptr, true)
		: UGameplayStatics::SpawnSound2D(W, Request.Sound, Request.Volume, Request.Pitch, 0.f, nullptr, false, true);
	if (!Component)
	{
		return; // no audio device (-nosound): the subsystem still logged the play
	}
	if (!FMath::IsNearlyEqual(Request.Fader, 1.f))
	{
		// The occlusion gain lives on the fader only; multiplier x fader is the heard level.
		Component->AdjustVolume(0.f, FMath::Max(Request.Fader, UE_KINDA_SMALL_NUMBER));
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

void FVerseEngineAudioSink::SetVoiceOcclusion(int32 Handle, float Gain, float LowpassHz)
{
	if (TWeakObjectPtr<UAudioComponent>* Found = Voices.Find(Handle))
	{
		if (UAudioComponent* Component = Found->Get())
		{
			// Fader only: the multiplier set at the start already holds the base volume.
			Component->AdjustVolume(0.1f, FMath::Max(Gain, UE_KINDA_SMALL_NUMBER));
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

USoundSubmix* FVerseEngineAudioSink::GetBusSubmix(EVerseAudioBus Bus) const
{
	return BusSubmixes.IsValidIndex(int32(Bus)) ? BusSubmixes[int32(Bus)].Get() : MasterSubmix.Get();
}

void FVerseEngineAudioSink::Route(USoundBase* Sound, EVerseAudioBus Bus)
{
	if (Sound)
	{
		if (USoundSubmix* Target = GetBusSubmix(Bus))
		{
			Sound->SoundSubmixObject = Target;
		}
	}
}

void FVerseEngineAudioSink::PruneFinished()
{
	PlaysSincePrune = 0;
	for (auto It = Voices.CreateIterator(); It; ++It)
	{
		const UAudioComponent* Component = It.Value().Get();
		if (!Component || !Component->IsPlaying())
		{
			It.RemoveCurrent();
		}
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
			for (USoundSubmix* Child : BusSubmixes)
			{
				if (Child)
				{
					Device->UnregisterSoundSubmix(Child, false);
				}
			}
			if (MasterSubmix)
			{
				Device->UnregisterSoundSubmix(MasterSubmix, false);
			}
		}
	}
	BusSubmixes.Reset();
	MasterSubmix = nullptr;
}

void FVerseEngineAudioSink::AddReferencedObjects(FReferenceCollector& Collector)
{
	Collector.AddReferencedObject(MasterSubmix);
	Collector.AddReferencedObjects(BusSubmixes);
}

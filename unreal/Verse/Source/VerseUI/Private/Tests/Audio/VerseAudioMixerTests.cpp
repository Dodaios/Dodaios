#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Audio/VerseAudioCueSet.h"
#include "Audio/VerseAudioSubsystem.h"
#include "AudioDevice.h"
#include "AudioDeviceManager.h"
#include "AudioThread.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Fakes/VerseAudioFakes.h"
#include "HAL/FileManager.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformProcess.h"
#include "HAL/PlatformTime.h"
#include "ISubmixBufferListener.h"
#include "Misc/FileHelper.h"
#include "Misc/OutputDevice.h"
#include "Misc/Paths.h"
#include "Misc/ScopeLock.h"
#include "Modules/ModuleManager.h"
#include "Sound/SoundSubmix.h"
#include "Sound/SoundWave.h"
#include "../../Audio/VerseEngineAudioSink.h"

// A19.3 with the audio mixer: destruction_storm through the engine sink and the shipped DA_AudioCues,
// measuring the audio thread per frame and the mixer's render time per buffer. It needs a run with
// sound (no -nosound); the headless -nosound lane only notes that it was skipped.
//
//   python scripts/unreal/with_lock.py --label wp19-mixer -- <UnrealEditor-Cmd> <Verse.uproject>
//     "-ExecCmds=Automation RunTests Verse.UI.Audio.MixerLoad; Quit" "-TestExit=Automation Test Queue Empty"
//     -unattended -nullrhi -nosplash -NoP4 -stdout -ReportExportPath=<dir> -abslog=<dir>/run.log

#define VERSE_AUDIO_MIXER_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseAudioMixerTest
{
	constexpr int32 MixerSelfId = 7;
	constexpr int32 MixerBotId = 9;
	constexpr double FrameS = 1.0 / 60.0;

	/** Every buffer the Verse master submix renders: wall time and peak sample. */
	class FMasterTap final : public ISubmixBufferListener
	{
	public:
		struct FBuffer
		{
			double Time = 0.0;
			float Peak = 0.f;
		};

		virtual void OnNewSubmixBuffer(const USoundSubmix*, float* AudioData, int32 NumSamples, int32 NumChannels,
			const int32 SampleRate, double) override
		{
			float Peak = 0.f;
			for (int32 I = 0; I < NumSamples; ++I)
			{
				Peak = FMath::Max(Peak, FMath::Abs(AudioData[I]));
			}
			FScopeLock Lock(&Guard);
			Buffers.Add({FPlatformTime::Seconds(), Peak});
			Frames = NumChannels > 0 ? NumSamples / NumChannels : 0;
			Rate = SampleRate;
		}

		virtual const FString& GetListenerName() const override
		{
			static const FString Name = TEXT("VerseAudioMixerLoadTap");
			return Name;
		}

		TArray<FBuffer> Snapshot() const
		{
			FScopeLock Lock(&Guard);
			return Buffers;
		}

		int32 Frames = 0;
		int32 Rate = 0;

	private:
		mutable FCriticalSection Guard;
		TArray<FBuffer> Buffers;
	};

	/** The mixer's own render timing lines (au.LogRenderTimes 1, every 32 buffers). */
	class FRenderTimeCapture final : public FOutputDevice
	{
	public:
		virtual void Serialize(const TCHAR* V, ELogVerbosity::Type, const FName& Category) override
		{
			const FString Line(V);
			if (!Line.StartsWith(TEXT("Render Time [id:")))
			{
				return;
			}
			auto Field = [&Line](const TCHAR* Key) -> double
			{
				const int32 At = Line.Find(Key);
				return At == INDEX_NONE ? -1.0 : FCString::Atod(*Line.Mid(At + FCString::Strlen(Key)));
			};
			FScopeLock Lock(&Guard);
			MaxDeltaMs.Add(Field(TEXT("MaxDelta: ")));
			AvgDeltaMs.Add(Field(TEXT("Delta Avg: ")));
		}
		virtual bool CanBeUsedOnMultipleThreads() const override { return true; }
		virtual bool CanBeUsedOnAnyThread() const override { return true; }

		void Read(TArray<double>& OutMax, TArray<double>& OutAvg) const
		{
			FScopeLock Lock(&Guard);
			OutMax = MaxDeltaMs;
			OutAvg = AvgDeltaMs;
		}

	private:
		mutable FCriticalSection Guard;
		TArray<double> MaxDeltaMs;
		TArray<double> AvgDeltaMs;
	};

	double Percentile(TArray<double> Values, double P)
	{
		if (Values.Num() == 0)
		{
			return 0.0;
		}
		Values.Sort();
		return Values[FMath::Clamp(int32(FMath::CeilToDouble(P * Values.Num())) - 1, 0, Values.Num() - 1)];
	}

	double Mean(const TArray<double>& Values)
	{
		double Sum = 0.0;
		for (double V : Values)
		{
			Sum += V;
		}
		return Values.Num() > 0 ? Sum / Values.Num() : 0.0;
	}

	FString Json(const TArray<TPair<FString, FString>>& Fields)
	{
		TArray<FString> Parts;
		for (const TPair<FString, FString>& F : Fields)
		{
			Parts.Add(FString::Printf(TEXT("\"%s\": %s"), *F.Key, *F.Value));
		}
		return TEXT("{") + FString::Join(Parts, TEXT(", ")) + TEXT("}");
	}

	FString Num(double V) { return FString::Printf(TEXT("%.6g"), V); }
	FString Str(const FString& V) { return TEXT("\"") + V.ReplaceCharWithEscapedChar() + TEXT("\""); }
}

using namespace VerseAudioMixerTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioMixerLoad, "Verse.UI.Audio.MixerLoad", VERSE_AUDIO_MIXER_TEST_FLAGS)
bool FVerseAudioMixerLoad::RunTest(const FString&)
{
	FAudioDeviceManager* Manager = GEngine ? GEngine->GetAudioDeviceManager() : nullptr;
	FAudioDevice* Device = GEngine && GEngine->UseSound() ? GEngine->GetMainAudioDeviceRaw() : nullptr;
	if (!Manager || !Device)
	{
		AddInfo(TEXT("No audio mixer in this run (-nosound): A19.3 audio-thread cost is measured in a run with sound."));
		return true;
	}
	FModuleManager::Get().LoadModule(TEXT("BinkAudioDecoder"));
	UVerseAudioCueSet* Shipped = LoadObject<UVerseAudioCueSet>(nullptr, UVerseAudioCueSet::DefaultAssetPath);
	if (!TestNotNull(TEXT("DA_AudioCues is imported"), Shipped))
	{
		return false;
	}
	int32 Waves = 0;
	for (const FVerseAudioCue& Cue : Shipped->Cues)
	{
		for (USoundBase* Sound : Cue.Variants)
		{
			if (USoundWave* Wave = Cast<USoundWave>(Sound))
			{
				Device->Precache(Wave, true);
				++Waves;
			}
		}
	}

	UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseAudioMixerWorld"));
	UVerseAudioSubsystem* Audio = World ? World->GetSubsystem<UVerseAudioSubsystem>() : nullptr;
	UVerseEventHub* Hub = World ? World->GetSubsystem<UVerseEventHub>() : nullptr;
	if (!TestNotNull(TEXT("audio subsystem"), Audio) || !TestNotNull(TEXT("hub"), Hub))
	{
		if (World)
		{
			World->DestroyWorld(false);
		}
		return false;
	}
	TSharedPtr<FVerseEngineAudioSink> Sink = MakeShared<FVerseEngineAudioSink>();
	Audio->SetSink(Sink);
	Audio->SetCueSet(Shipped);
	Audio->SetLocalPlayerId(MixerSelfId);
	Audio->SetListenerOverride(FVector::ZeroVector);
	USoundSubmix* Master = Sink->GetMasterSubmix();
	TestNotNull(TEXT("Verse master submix registered"), Master);
	TestTrue(TEXT("one bus submix under the master per bus"),
		Master && Master->ChildSubmixes.Num() == VerseAudioBusCount
			&& Sink->GetBusSubmix(EVerseAudioBus::Weapons) != Master);

	TSharedRef<FMasterTap, ESPMode::ThreadSafe> Tap = MakeShared<FMasterTap, ESPMode::ThreadSafe>();
	if (Master)
	{
		Device->RegisterSubmixBufferListener(Tap, *Master);
	}
	FRenderTimeCapture Capture;
	GLog->AddOutputDevice(&Capture);
	IConsoleVariable* LogRenderTimes = IConsoleManager::Get().FindConsoleVariable(TEXT("au.LogRenderTimes"));
	const int32 OldLogRenderTimes = LogRenderTimes ? LogRenderTimes->GetInt() : 0;
	if (LogRenderTimes)
	{
		LogRenderTimes->Set(1, ECVF_SetByCode);
	}

	TArray<double> AudioThreadMs;
	auto Frame = [&]()
	{
		const double FrameStart = FPlatformTime::Seconds();
		Audio->Tick(float(FrameS));
		const double T0 = FPlatformTime::Seconds();
		Manager->UpdateActiveAudioDevices(true);
		FAudioCommandFence Fence;
		Fence.BeginFence();
		Fence.Wait();
		AudioThreadMs.Add((FPlatformTime::Seconds() - T0) * 1000.0);
		const double Left = FrameS - (FPlatformTime::Seconds() - FrameStart);
		if (Left > 0.0)
		{
			FPlatformProcess::Sleep(float(Left));
		}
	};

	// 1. Shot to first rendered buffer: own shots into silence.
	TArray<double> ShotToRenderMs;
	for (int32 Shot = 0; Shot < 5; ++Shot)
	{
		for (int32 I = 0; I < 90; ++I)
		{
			Frame(); // let the previous tail ring out
		}
		const int32 Before = Tap->Snapshot().Num();
		FVerseFireEvent Fire;
		Fire.ShooterId = MixerSelfId;
		Fire.WeaponId = TEXT("rifle");
		Fire.ShotCounter = uint16(Shot);
		Fire.Origin = FVector(0.0, 0.0, 150.0);
		Fire.Direction = FVector(1.0, 0.0, 0.0);
		const double ShotAt = FPlatformTime::Seconds();
		Hub->OnFire.Broadcast(Fire);
		for (int32 I = 0; I < 30; ++I)
		{
			Frame();
		}
		const TArray<FMasterTap::FBuffer> Buffers = Tap->Snapshot();
		for (int32 I = Before; I < Buffers.Num(); ++I)
		{
			if (Buffers[I].Time >= ShotAt && Buffers[I].Peak > 1e-4f)
			{
				ShotToRenderMs.Add((Buffers[I].Time - ShotAt) * 1000.0);
				break;
			}
		}
	}

	// 2. destruction_storm, as Verse.UI.Audio.DestructionStorm but heard through the mixer.
	FFakeVerseWall Wall;
	Wall.WallX = 850.f;
	Wall.Material = EVersePenetrationMaterial::ContainerWall;
	Audio->SetPieceQuery(&Wall);
	Audio->ResetPeakVoices();
	AudioThreadMs.Reset();
	FRandomStream Rng(19);
	int32 Fractures = 0;
	auto Burst = [&](int32 Count)
	{
		for (int32 I = 0; I < Count; ++I)
		{
			FVerseFractureEvent F;
			F.PieceIndex = uint16(Rng.RandRange(0, 599));
			F.FromState = EVersePieceState::Intact;
			F.ToState = Rng.FRand() < 0.6f ? EVersePieceState::Destroyed : EVersePieceState::Holed;
			F.Cause = Rng.FRand() < 0.3f ? EVerseFractureCause::Breach : EVerseFractureCause::Bolt;
			F.Seed = Rng.GetUnsignedInt();
			Hub->OnFracture.Broadcast(F);
			++Fractures;
		}
	};
	const int32 BuffersBeforeStorm = Tap->Snapshot().Num();
	Audio->StartDroneLoop(1, true, FVector(400.0, 100.0, 100.0));
	Audio->SetAmbience(EVerseAmbience::Hangar);
	Burst(400);
	for (int32 Tick = 0; Tick < 60 * 8; ++Tick)
	{
		Burst(1 + (Tick % 2));
		if (Tick % 6 == 0)
		{
			FVerseFireEvent Fire;
			Fire.ShooterId = (Tick / 6) % 2 ? MixerBotId : MixerSelfId;
			Fire.WeaponId = TEXT("rifle");
			Fire.Origin = FVector(1200.0, 300.0, 150.0);
			Fire.Direction = FVector(-1.0, 0.0, 0.0);
			Hub->OnFire.Broadcast(Fire);
		}
		Frame();
	}
	const int32 PeakVoices = Audio->GetPeakVoices();
	Audio->StopDroneLoop(1);
	Audio->SetAmbience(EVerseAmbience::None);
	for (int32 I = 0; I < 40; ++I)
	{
		Frame(); // flush the last render-time line
	}

	if (LogRenderTimes)
	{
		LogRenderTimes->Set(OldLogRenderTimes, ECVF_SetByCode);
	}
	GLog->FlushThreadedLogs();
	GLog->RemoveOutputDevice(&Capture);
	if (Master)
	{
		Device->UnregisterSubmixBufferListener(Tap, *Master);
	}
	const TArray<FMasterTap::FBuffer> Buffers = Tap->Snapshot();
	int32 StormBuffers = 0, Loud = 0;
	for (int32 I = BuffersBeforeStorm; I < Buffers.Num(); ++I)
	{
		++StormBuffers;
		Loud += Buffers[I].Peak > 1e-4f ? 1 : 0;
	}
	TArray<double> RenderMaxMs, RenderAvgMs;
	Capture.Read(RenderMaxMs, RenderAvgMs);
	const int32 Tracked = Sink->NumTrackedVoices();
	Audio->SetPieceQuery(nullptr);
	World->DestroyWorld(false);

	const double ThreadMean = Mean(AudioThreadMs);
	const double RenderMean = Mean(RenderAvgMs);
	const double BufferMs = Tap->Rate > 0 ? 1000.0 * Tap->Frames / Tap->Rate : 0.0;
	TestTrue(TEXT("the master submix rendered sound during the storm"), Loud > 0);
	TestTrue(TEXT("A19.3 peak voices at most 64"), PeakVoices <= 64);
	TestTrue(FString::Printf(TEXT("A19.3 audio thread %.3f ms per frame at most 1.5 ms"), ThreadMean), ThreadMean <= 1.5);
	if (RenderAvgMs.Num() > 0)
	{
		TestTrue(FString::Printf(TEXT("A19.3 mixer render %.3f ms per buffer at most 1.5 ms"), RenderMean), RenderMean <= 1.5);
	}
	else
	{
		AddWarning(TEXT("au.LogRenderTimes gave no render-time lines; render cost not measured"));
	}
	TestTrue(TEXT("finished one-shots are pruned from the sink"), Tracked < 64);

	const FString Report = Json({
		{TEXT("test"), Str(TEXT("A19.3 load, destruction_storm with the audio mixer"))},
		{TEXT("sound_waves_precached"), Num(Waves)},
		{TEXT("fractures"), Num(Fractures)},
		{TEXT("peak_voices"), Num(PeakVoices)},
		{TEXT("max_voices"), Num(64)},
		{TEXT("frames"), Num(AudioThreadMs.Num())},
		{TEXT("audio_thread_ms_mean"), Num(ThreadMean)},
		{TEXT("audio_thread_ms_p95"), Num(Percentile(AudioThreadMs, 0.95))},
		{TEXT("audio_thread_ms_max"), Num(Percentile(AudioThreadMs, 1.0))},
		{TEXT("audio_thread_measures"), Str(TEXT("UpdateActiveAudioDevices plus an audio command fence, per 60 Hz frame"))},
		{TEXT("render_ms_per_buffer_mean"), Num(RenderMean)},
		{TEXT("render_ms_per_buffer_max"), Num(Percentile(RenderMaxMs, 1.0))},
		{TEXT("render_time_samples"), Num(RenderAvgMs.Num())},
		{TEXT("buffer_frames"), Num(Tap->Frames)},
		{TEXT("sample_rate"), Num(Tap->Rate)},
		{TEXT("buffer_ms"), Num(BufferMs)},
		{TEXT("storm_buffers"), Num(StormBuffers)},
		{TEXT("storm_buffers_with_sound"), Num(Loud)},
		{TEXT("shot_to_first_rendered_buffer_ms_mean"), Num(Mean(ShotToRenderMs))},
		{TEXT("shot_to_first_rendered_buffer_ms_max"), Num(Percentile(ShotToRenderMs, 1.0))},
		{TEXT("shots_measured"), Num(ShotToRenderMs.Num())},
		{TEXT("sink_voices_tracked_at_end"), Num(Tracked)},
	});
	const FString Dir = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP19"), TEXT("19.6"));
	IFileManager::Get().MakeDirectory(*Dir, true);
	FFileHelper::SaveStringToFile(Report, *FPaths::Combine(Dir, TEXT("mixer_load.json")));
	AddInfo(Report);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

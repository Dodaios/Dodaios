#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Audio/VerseAudioCueSet.h"
#include "Audio/VerseAudioMath.h"
#include "Audio/VerseAudioSubsystem.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "Fakes/VerseAudioFakes.h"
#include "GameplayTagContainer.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Modules/ModuleManager.h"
#include "Noise/VerseAudibilityTable.h"
#include "Internationalization/Regex.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundEffectSubmix.h"
#include "Sound/SoundWave.h"
#include "../../Audio/VerseEngineAudioSink.h"
#include "VerseGameplayTags.h"

// WP19 acceptance tests A19.1-A19.6 and the occlusion, fairness and variant rules. They run headless
// (-nullrhi -nosound) against a recording sink; Verse.UI.Audio.ShippedCues checks the imported asset.

#define VERSE_AUDIO_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseAudioTest
{
	constexpr int32 LocalId = 7;
	constexpr int32 BotId = 9;

	FString ProofDir(const TCHAR* SubTask)
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Harness"), TEXT("proof"), TEXT("WP19"), SubTask);
	}

	/** Tiny JSON writer for the proof files (VerseUI does not link the Json module). */
	struct FProof
	{
		TArray<FString> Fields;
		void Str(const TCHAR* K, const FString& V) { Fields.Add(FString::Printf(TEXT("\"%s\": \"%s\""), K, *V.ReplaceCharWithEscapedChar())); }
		void Num(const TCHAR* K, double V) { Fields.Add(FString::Printf(TEXT("\"%s\": %.6g"), K, V)); }
		void Bool(const TCHAR* K, bool V) { Fields.Add(FString::Printf(TEXT("\"%s\": %s"), K, V ? TEXT("true") : TEXT("false"))); }
		void Raw(const TCHAR* K, const FString& V) { Fields.Add(FString::Printf(TEXT("\"%s\": %s"), K, *V)); }
		FString ToString() const { return TEXT("{") + FString::Join(Fields, TEXT(", ")) + TEXT("}"); }
		static FString Array(const TArray<FProof>& Items)
		{
			TArray<FString> Parts;
			for (const FProof& P : Items)
			{
				Parts.Add(P.ToString());
			}
			return TEXT("[") + FString::Join(Parts, TEXT(", ")) + TEXT("]");
		}
	};

	void WriteProof(const TCHAR* SubTask, const TCHAR* File, const FProof& Proof)
	{
		const FString Dir = ProofDir(SubTask);
		IFileManager::Get().MakeDirectory(*Dir, true);
		FFileHelper::SaveStringToFile(Proof.ToString(), *FPaths::Combine(Dir, File));
	}

	USoundWave* MakeWave(UObject* Outer, float DurationS, bool bLoop)
	{
		USoundWave* Wave = NewObject<USoundWave>(Outer, NAME_None, RF_Transient);
		Wave->Duration = DurationS;
		Wave->bLooping = bLoop;
		return Wave;
	}

	void AddCue(UVerseAudioCueSet* Set, const TCHAR* Id, bool bSpatial, const TCHAR* Noise, float RangeM, float Priority,
		int32 MaxVoices, bool bLoop = false, float DurationS = 0.6f, int32 Variants = 3)
	{
		FVerseAudioCue Cue;
		Cue.CueId = Id;
		Cue.bSpatial = bSpatial;
		Cue.NoiseTag = Noise ? FName(Noise) : NAME_None;
		Cue.RangeM = RangeM;
		Cue.Priority = Priority;
		Cue.MaxVoices = MaxVoices;
		Cue.bLoop = bLoop;
		Cue.Licence = TEXT("own");
		for (int32 I = 0; I < Variants; ++I)
		{
			Cue.Variants.Add(MakeWave(Set, DurationS, bLoop));
		}
		Set->Cues.Add(Cue);
	}

	/** The cue list of cues.json with placeholder waves: the rules under test never read audio data. */
	UVerseAudioCueSet* MakeCueSet(UObject* Outer)
	{
		UVerseAudioCueSet* Set = NewObject<UVerseAudioCueSet>(Outer, NAME_None, RF_Transient);
		Set->WeaponProfiles = {TEXT("pistol"), TEXT("rifle")};
		for (const TCHAR* W : {TEXT("rifle"), TEXT("pistol")})
		{
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_fp_mech"), W), false, nullptr, 0, 10, 6, false, 0.22f);
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_fp_body"), W), false, nullptr, 0, 10, 6, false, 0.45f);
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_tail"), W), false, nullptr, 0, 8, 4, false, 2.0f);
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_tp_near"), W), true, TEXT("Noise.Shot"), 0, 10, 6, false, 0.9f);
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_tp_far"), W), true, TEXT("Noise.Shot"), 0, 9, 4, false, 3.0f);
			AddCue(Set, *FString::Printf(TEXT("wpn_%s_tp_tail"), W), true, TEXT("Noise.Shot"), 0, 7, 4, false, 2.4f);
			AddCue(Set, *FString::Printf(TEXT("rld_%s_tactical"), W), true, TEXT("Noise.Reload"), 0, 7, 2, false, 1.2f);
			AddCue(Set, *FString::Printf(TEXT("rld_%s_empty"), W), true, TEXT("Noise.Reload"), 0, 7, 2, false, 1.9f);
		}
		AddCue(Set, TEXT("bolt_flyby"), true, nullptr, 6, 9, 4, false, 0.35f);
		for (const TCHAR* M : {TEXT("sheet_metal"), TEXT("container_wall"), TEXT("glass"), TEXT("cladding_panel"),
				 TEXT("catwalk_grating"), TEXT("ceiling_panel"), TEXT("concrete"), TEXT("armor_steel"), TEXT("flesh")})
		{
			AddCue(Set, *FString::Printf(TEXT("imp_%s"), M), true, TEXT("Noise.Impact"), 60, 6, 6, false, 0.45f);
		}
		AddCue(Set, TEXT("imp_penetration_exit"), true, TEXT("Noise.Impact"), 60, 6, 4);
		AddCue(Set, TEXT("imp_hurt"), false, nullptr, 0, 10, 2);
		for (const TCHAR* S : {TEXT("fs_metal"), TEXT("fs_metal_boots"), TEXT("fs_grating"), TEXT("fs_concrete"), TEXT("fs_rubble")})
		{
			AddCue(Set, S, true, TEXT("Noise.Footstep.Run"), 0, 5, 4, false, 0.25f, 4);
		}
		AddCue(Set, TEXT("fol_slide"), true, TEXT("Noise.Move.Slide"), 0, 6, 4);
		AddCue(Set, TEXT("fol_land"), true, TEXT("Noise.Move.Land"), 0, 6, 4);
		AddCue(Set, TEXT("fol_mantle"), true, TEXT("Noise.Move.Mantle"), 0, 6, 4);
		AddCue(Set, TEXT("fol_lean"), false, nullptr, 0, 3, 2);
		AddCue(Set, TEXT("mel_knife_swing"), true, TEXT("Noise.Melee"), 0, 8, 4);
		AddCue(Set, TEXT("mel_knife_hit"), true, TEXT("Noise.Melee"), 0, 9, 4);
		for (const TCHAR* P : {TEXT("dst_wall_panel"), TEXT("dst_cladding_wall"), TEXT("dst_container_wall"),
				 TEXT("dst_glass_pane"), TEXT("dst_catwalk_segment"), TEXT("dst_ceiling_panel"), TEXT("dst_hole")})
		{
			AddCue(Set, P, true, TEXT("Noise.Fracture"), 0, 7, 6, false, 2.2f);
		}
		for (const TCHAR* K : {TEXT("dst_settle_metal"), TEXT("dst_settle_glass"), TEXT("dst_settle_dust")})
		{
			AddCue(Set, K, true, TEXT("Noise.Fracture"), 0, 2, 6, false, 1.5f);
		}
		AddCue(Set, TEXT("drn_flight"), true, TEXT("Noise.Drone"), 0, 5, 3, true, 3.6f, 1);
		AddCue(Set, TEXT("drn_weld"), true, TEXT("Noise.Drone"), 0, 5, 3, true, 3.6f, 1);
		AddCue(Set, TEXT("amb_hangar"), false, nullptr, 0, 2, 1, true, 10.f, 1);
		AddCue(Set, TEXT("ui_click"), false, nullptr, 0, 4, 2);
		Set->RebuildIndex();
		return Set;
	}

	struct FRig
	{
		UWorld* World = nullptr;
		UVerseAudioSubsystem* Audio = nullptr;
		UVerseEventHub* Hub = nullptr;
		TSharedPtr<FFakeVerseAudioSink> Sink;

		bool Make(FAutomationTestBase& Test)
		{
			World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseAudioTestWorld"));
			if (!Test.TestNotNull(TEXT("test world"), World))
			{
				return false;
			}
			Audio = World->GetSubsystem<UVerseAudioSubsystem>();
			Hub = World->GetSubsystem<UVerseEventHub>();
			if (!Test.TestNotNull(TEXT("audio subsystem in a game world"), Audio) || !Test.TestNotNull(TEXT("hub"), Hub))
			{
				return false;
			}
			Sink = MakeShared<FFakeVerseAudioSink>();
			Audio->SetSink(Sink);
			Audio->SetCueSet(MakeCueSet(Audio));
			Audio->SetLocalPlayerId(LocalId);
			Audio->SetListenerOverride(FVector::ZeroVector);
			return true;
		}

		~FRig()
		{
			if (World)
			{
				World->DestroyWorld(false);
			}
		}

		void Advance(float Seconds, float Step = 1.f / 60.f)
		{
			for (float T = 0.f; T < Seconds - KINDA_SMALL_NUMBER; T += Step)
			{
				Audio->Tick(Step);
			}
		}
	};

	const FVerseAudioLogEntry* LastOf(const UVerseAudioSubsystem& Audio, FName CueId)
	{
		const TArray<FVerseAudioLogEntry>& Log = Audio.GetEventLog();
		for (int32 I = Log.Num() - 1; I >= 0; --I)
		{
			if (Log[I].CueId == CueId)
			{
				return &Log[I];
			}
		}
		return nullptr;
	}
}

using namespace VerseAudioTest;

// A19.1 F6 symmetry: the attenuation of every Noise.* tag ends exactly at its DA_Audibility range.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioAudibilitySymmetry, "Verse.UI.Audio.AudibilitySymmetry", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioAudibilitySymmetry::RunTest(const FString&)
{
	const UVerseAudibilityTable& Table = *GetDefault<UVerseAudibilityTable>();
	const FVerseAudioMixSettings Mix;
	TArray<FProof> Rows;
	int32 Mismatches = 0;
	auto Check = [&](const FGameplayTag& Tag, float Loudness)
	{
		const float RangeM = Table.GetAudibleRangeM(Tag, Loudness);
		FSoundAttenuationSettings Att;
		Verse::Audio::BuildAttenuation(RangeM, Mix, Att);
		const float Expected = Verse::Audio::MaxAttenuationDistanceCm(RangeM);
		const float Got = Att.GetMaxDimension();
		const FVerseAudibilityRow* Row = Table.FindRow(Tag);
		const bool bFinite = Row && !Row->bWholeArena;
		bool bOk = FMath::IsNearlyEqual(Got, Expected, 1.f) && RangeM > 0.f;
		if (bFinite)
		{
			bOk &= FMath::IsNearlyEqual(Got, RangeM * 100.f, 1.f);
			bOk &= Verse::Audio::DistanceGain(RangeM, RangeM, Mix) == 0.f;
			bOk &= Verse::Audio::DistanceGain(RangeM * 0.98f, RangeM, Mix) > 0.f;
		}
		else
		{
			bOk &= Verse::Audio::DistanceGain(150.f, RangeM, Mix) > 0.f; // heard across the whole hangar
		}
		Mismatches += bOk ? 0 : 1;
		TestTrue(FString::Printf(TEXT("%s x%.2f: attenuation ends at %.0f cm, table %.0f cm"), *Tag.ToString(), Loudness, Got,
					 RangeM * 100.f),
			bOk);
		FProof& J = Rows.AddDefaulted_GetRef();
		J.Str(TEXT("noise"), Tag.ToString());
		J.Num(TEXT("loudness"), Loudness);
		J.Num(TEXT("table_range_m"), RangeM);
		J.Num(TEXT("attenuation_max_cm"), Got);
		J.Bool(TEXT("ok"), bOk);
	};
	for (const FGameplayTag& Tag : VerseTags::AllNoiseTags())
	{
		const FVerseAudibilityRow* Row = Table.FindRow(Tag);
		if (!TestNotNull(*FString::Printf(TEXT("row for %s"), *Tag.ToString()), Row))
		{
			++Mismatches;
			continue;
		}
		if (Row->bRangeScalesWithLoudness)
		{
			for (const EVerseFractureNoise Kind : {EVerseFractureNoise::Breach, EVerseFractureNoise::WallBreak,
					 EVerseFractureNoise::Glass, EVerseFractureNoise::Tile, EVerseFractureNoise::BoltHole})
			{
				Check(Tag, Tag == VerseTags::Noise_Drone ? Verse::Destruction::DroneLoudness : Verse::Destruction::FractureLoudness(Kind));
			}
		}
		else
		{
			Check(Tag, 1.f);
		}
	}

	// The subsystem uses the same table for a remote source.
	FRig Rig;
	if (Rig.Make(*this))
	{
		TestEqual(TEXT("subsystem footstep range = table"), Rig.Audio->RangeForNoise(TEXT("Noise.Footstep.Sprint"), 1.f), 20.f);
		TestEqual(TEXT("subsystem drone range = 6 m"), Rig.Audio->RangeForNoise(TEXT("Noise.Drone"), Verse::Destruction::DroneLoudness), 6.f);
	}
	TestEqual(TEXT("A19.1 mismatches"), Mismatches, 0);

	FProof Report;
	Report.Str(TEXT("test"), TEXT("A19.1 F6 symmetry"));
	Report.Num(TEXT("mismatches"), Mismatches);
	Report.Raw(TEXT("rows"), FProof::Array(Rows));
	WriteProof(TEXT("19.1"), TEXT("audibility_symmetry.json"), Report);
	return true;
}

// A19.2: shot to sound start within one frame (the play is issued in the frame of the fire event).
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioShotLatency, "Verse.UI.Audio.ShotLatency", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioShotLatency::RunTest(const FString&)
{
	FRig Rig;
	if (!Rig.Make(*this))
	{
		return false;
	}
	int64 MaxFrames = 0;
	for (int32 Shot = 0; Shot < 30; ++Shot)
	{
		FVerseFireEvent Fire;
		Fire.ShooterId = Shot % 2 ? BotId : LocalId;
		Fire.WeaponId = Shot % 3 ? TEXT("rifle_ar1") : TEXT("pistol_p1");
		Fire.ShotCounter = uint16(Shot);
		Fire.Origin = FVector(1500.0 * (Shot % 2), 0.0, 150.0);
		Fire.Direction = FVector(-1.0, 0.0, 0.0);
		const int32 Before = Rig.Sink->Plays.Num();
		const int64 Frame = int64(GFrameCounter);
		Rig.Hub->OnFire.Broadcast(Fire);
		TestTrue(FString::Printf(TEXT("shot %d starts a voice at once"), Shot), Rig.Sink->Plays.Num() > Before);
		if (Rig.Sink->Plays.Num() > Before)
		{
			MaxFrames = FMath::Max(MaxFrames, Rig.Sink->Plays[Before].Frame - Frame);
		}
		Rig.Advance(0.1f);
	}
	TestTrue(TEXT("A19.2 shot to sound start at most 1 frame"), MaxFrames <= 1);
	TestTrue(TEXT("own shot plays the first-person body"), Rig.Sink->CountOf(TEXT("wpn_rifle_fp_body")) > 0);
	TestTrue(TEXT("own pistol uses the pistol profile"), Rig.Sink->CountOf(TEXT("wpn_pistol_fp_body")) > 0);
	TestTrue(TEXT("remote shot at 15 m plays the third-person layers"), Rig.Sink->CountOf(TEXT("wpn_rifle_tp_tail")) > 0);
	TestTrue(TEXT("a bolt aimed at the listener flies by"), Rig.Sink->CountOf(TEXT("bolt_flyby")) > 0);

	FProof Report;
	Report.Str(TEXT("test"), TEXT("A19.2 latency"));
	Report.Num(TEXT("shots"), 30);
	Report.Num(TEXT("max_frames_shot_to_play"), double(MaxFrames));
	WriteProof(TEXT("19.2"), TEXT("shot_latency.json"), Report);
	return true;
}

// A19.3 destruction_storm: never more than 64 voices; shots still get a voice inside the storm.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioDestructionStorm, "Verse.UI.Audio.DestructionStorm", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioDestructionStorm::RunTest(const FString&)
{
	FRig Rig;
	if (!Rig.Make(*this))
	{
		return false;
	}
	FFakeVerseWall Wall;
	Wall.WallX = 850.f; // pieces 8.5 m away
	Wall.Material = EVersePenetrationMaterial::ContainerWall;
	Rig.Audio->SetPieceQuery(&Wall);
	FRandomStream Rng(19);
	int32 Fractures = 0, Shots = 0, ShotsAdmitted = 0;
	const double Start = FPlatformTime::Seconds();
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
			Rig.Hub->OnFracture.Broadcast(F);
			++Fractures;
		}
	};
	Burst(400); // the breach that opens a whole wall section in one tick
	for (int32 Tick = 0; Tick < 60 * 8; ++Tick)
	{
		Burst(1 + (Tick % 2));
		if (Tick % 6 == 0)
		{
			FVerseFireEvent Fire;
			Fire.ShooterId = (Tick / 6) % 2 ? BotId : LocalId;
			Fire.WeaponId = TEXT("rifle");
			Fire.Origin = FVector(1200.0, 300.0, 150.0);
			Fire.Direction = FVector(-1.0, 0.0, 0.0);
			const int32 Before = Rig.Audio->GetEventLog().Num();
			Rig.Hub->OnFire.Broadcast(Fire);
			++Shots;
			bool bAdmitted = false;
			const TArray<FVerseAudioLogEntry>& Log = Rig.Audio->GetEventLog();
			for (int32 I = FMath::Max(0, Before); I < Log.Num(); ++I)
			{
				bAdmitted |= Log[I].CueId.ToString().StartsWith(TEXT("wpn_")) && Log[I].bAdmitted;
			}
			ShotsAdmitted += bAdmitted ? 1 : 0;
		}
		TestTrue(TEXT("voices never above 64"), Rig.Audio->GetActiveVoices() <= 64);
		Rig.Audio->Tick(1.f / 60.f);
	}
	const double GameThreadMs = (FPlatformTime::Seconds() - Start) * 1000.0 / (60 * 8);
	TestTrue(TEXT("A19.3 peak voices at most 64"), Rig.Audio->GetPeakVoices() <= 64);
	TestEqual(TEXT("every shot gets a voice inside the storm"), ShotsAdmitted, Shots);

	FProof Report;
	Report.Str(TEXT("test"), TEXT("A19.3 load, destruction_storm"));
	Report.Num(TEXT("fractures"), Fractures);
	Report.Num(TEXT("shots"), Shots);
	Report.Num(TEXT("shots_admitted"), ShotsAdmitted);
	Report.Num(TEXT("peak_voices"), Rig.Audio->GetPeakVoices());
	Report.Num(TEXT("max_voices"), 64);
	Report.Num(TEXT("subsystem_game_thread_ms_per_tick"), GameThreadMs);
	Report.Str(TEXT("audio_thread_ms"), TEXT("needs the rendered lane (WP10 unreal-perf); -nosound has no mixer"));
	WriteProof(TEXT("19.6"), TEXT("destruction_storm.json"), Report);
	return true;
}

// A19.5 dormant: muted within 100 ms of hide (at once), back with a short fade on show.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioDormant, "Verse.UI.Audio.Dormant", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioDormant::RunTest(const FString&)
{
	FRig Rig;
	if (!Rig.Make(*this))
	{
		return false;
	}
	Rig.Audio->SetAmbience(EVerseAmbience::Hangar);
	TestEqual(TEXT("visible: full volume"), Rig.Sink->Master, 1.f);
	Rig.Audio->SetDormant(true);
	TestEqual(TEXT("A19.5 muted at the hide call (0 ms)"), Rig.Sink->Master, 0.f);
	Rig.Advance(0.1f);
	TestEqual(TEXT("still muted 100 ms later"), Rig.Sink->Master, 0.f);
	Rig.Audio->SetDormant(false);
	TestTrue(TEXT("unmute fades in, no jump"), Rig.Sink->Master < 0.5f);
	Rig.Advance(0.2f);
	TestEqual(TEXT("back to full within the fade"), Rig.Sink->Master, 1.f);
	Rig.Audio->SetUiSoundEnabled(false);
	TestEqual(TEXT("ui_sound off silences the Verse (Z-14)"), Rig.Sink->Master, 0.f);
	Rig.Audio->SetUiSoundEnabled(true);
	Rig.Audio->SetUserVolume(0.f);
	TestEqual(TEXT("volume 0 silences (Z-14)"), Rig.Sink->Master, 0.f);
	return true;
}

// 19.7 occlusion: a wall muffles a source behind it; a hole or breach opens it again.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioOcclusion, "Verse.UI.Audio.Occlusion", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioOcclusion::RunTest(const FString&)
{
	const FVerseAudioMixSettings Mix;
	FFakeVerseWall Wall;
	TArray<FProof> Rows;
	auto Row = [&Rows](const TCHAR* Case, const FVerseOcclusion& Occ)
	{
		FProof& J = Rows.AddDefaulted_GetRef();
		J.Str(TEXT("case"), Case);
		J.Num(TEXT("loss_db"), Occ.LossDb);
		J.Num(TEXT("lowpass_hz"), Occ.LowpassHz);
		J.Num(TEXT("pieces"), Occ.Pieces);
	};
	const FVector Listener(0.0, 0.0, 150.0);
	const FVector Behind(900.0, 0.0, 150.0);
	const FVector Front(300.0, 0.0, 150.0);

	FVerseOcclusion Occ = Verse::Audio::TraceOcclusion(&Wall, Listener, Behind, Mix);
	Row(TEXT("sheet metal wall intact"), Occ);
	TestEqual(TEXT("intact sheet metal: -9 dB"), Occ.LossDb, -9.f);
	TestEqual(TEXT("intact sheet metal: 2.5 kHz low-pass"), Occ.LowpassHz, 2500.f);
	Occ = Verse::Audio::TraceOcclusion(&Wall, Listener, Front, Mix);
	Row(TEXT("source in front of the wall"), Occ);
	TestTrue(TEXT("same side: open"), Occ.IsOpen());
	Wall.State = EVersePieceState::Holed;
	Occ = Verse::Audio::TraceOcclusion(&Wall, Listener, Behind, Mix);
	Row(TEXT("sheet metal wall holed"), Occ);
	TestTrue(TEXT("a hole opens the path"), Occ.IsOpen());
	Wall.State = EVersePieceState::Intact;
	Wall.Material = EVersePenetrationMaterial::Concrete;
	Occ = Verse::Audio::TraceOcclusion(&Wall, Listener, Behind, Mix);
	Row(TEXT("concrete intact"), Occ);
	TestEqual(TEXT("concrete: -20 dB"), Occ.LossDb, -20.f);
	Wall.Material = EVersePenetrationMaterial::CatwalkGrating;
	Occ = Verse::Audio::TraceOcclusion(&Wall, Listener, Behind, Mix);
	Row(TEXT("grating"), Occ);
	TestTrue(TEXT("grating barely occludes"), Occ.LossDb >= -1.f);
	TestTrue(TEXT("no query: open"), Verse::Audio::TraceOcclusion(nullptr, Listener, Behind, Mix).IsOpen());

	// In the subsystem: a one-shot behind the wall is muffled; a loop opens up after a breach.
	FRig Rig;
	if (Rig.Make(*this))
	{
		Wall.Material = EVersePenetrationMaterial::SheetMetal;
		Wall.State = EVersePieceState::Intact;
		Rig.Audio->SetPenetrationQuery(&Wall);
		Rig.Audio->SetListenerOverride(Listener);
		Rig.Audio->PlayKnifeSwing(BotId, FVector(560.0, 0.0, 150.0));
		const FVerseAudioLogEntry* Swing = LastOf(*Rig.Audio, TEXT("mel_knife_swing"));
		TestTrue(TEXT("remote knife behind sheet metal: -9 dB in the log"),
			Swing && Swing->bAdmitted && FMath::IsNearlyEqual(Swing->OcclusionLossDb, -9.f));
		Rig.Audio->StartDroneLoop(1, true, FVector(560.0, 0.0, 150.0));
		const FVerseAudioLogEntry* Weld = LastOf(*Rig.Audio, TEXT("drn_weld"));
		TestTrue(TEXT("drone weld behind the wall starts muffled"), Weld && Weld->bAdmitted && Weld->LowpassHz <= 2500.f);
		Wall.State = EVersePieceState::Breached;
		Rig.Advance(0.3f);
		bool bOpened = false;
		for (const TPair<int32, float>& Pair : Rig.Sink->VoiceLowpass)
		{
			bOpened |= Pair.Value >= 19999.f;
		}
		TestTrue(TEXT("after the breach the loop re-traces and opens"), bOpened);
		Rig.Audio->StopDroneLoop(1);
		TestEqual(TEXT("loop stopped"), Rig.Audio->GetLoopCount(), 0);
	}

	FProof Report;
	Report.Str(TEXT("test"), TEXT("19.7 occlusion"));
	Report.Raw(TEXT("cases"), FProof::Array(Rows));
	WriteProof(TEXT("19.7"), TEXT("occlusion.json"), Report);
	return true;
}

// F6 in practice: the person hears others only where the bot would hear them.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioFairness, "Verse.UI.Audio.Fairness", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioFairness::RunTest(const FString&)
{
	FRig Rig;
	if (!Rig.Make(*this))
	{
		return false;
	}
	const int32 Before = Rig.Sink->Plays.Num();
	Rig.Audio->PlayFootstep(BotId, EVerseFootSurface::Metal, EVerseGait::CrouchWalk, FVector(200.0, 0.0, 0.0));
	Rig.Audio->PlayFoley(BotId, EVerseFoley::LeanIn, FVector(200.0, 0.0, 0.0));
	Rig.Audio->PlayEquip(BotId, TEXT("rifle"));
	TestEqual(TEXT("crouch steps, lean and equip of the bot are silent"), Rig.Sink->Plays.Num(), Before);
	Rig.Audio->PlayFootstep(BotId, EVerseFootSurface::Concrete, EVerseGait::Run, FVector(900.0, 0.0, 0.0));
	TestEqual(TEXT("run step at 9 m (range 10 m) plays"), Rig.Sink->Plays.Num(), Before + 1);
	Rig.Audio->PlayFootstep(BotId, EVerseFootSurface::Concrete, EVerseGait::Run, FVector(1100.0, 0.0, 0.0));
	TestEqual(TEXT("run step at 11 m is out of range"), Rig.Sink->Plays.Num(), Before + 1);
	Rig.Audio->PlayFootstep(BotId, EVerseFootSurface::Concrete, EVerseGait::Sprint, FVector(1900.0, 0.0, 0.0));
	TestEqual(TEXT("sprint step at 19 m (range 20 m) plays"), Rig.Sink->Plays.Num(), Before + 2);
	const FVerseAudioLogEntry* Step = LastOf(*Rig.Audio, TEXT("fs_concrete"));
	TestTrue(TEXT("the sprint step uses the 20 m range"), Step && FMath::IsNearlyEqual(Step->RangeM, 20.f));
	Rig.Audio->PlayFootstep(LocalId, EVerseFootSurface::Metal, EVerseGait::CrouchWalk, FVector::ZeroVector);
	TestEqual(TEXT("own crouch steps play for the person"), Rig.Sink->Plays.Num(), Before + 3);

	// Bolt impact of the opponent: heard within 3 m only (Noise.Impact); own impacts are shooter feedback.
	FVersePenetrationEvent Pen;
	Pen.ShooterId = BotId;
	Pen.MaterialWireId = uint8(EVersePenetrationMaterial::Concrete);
	Pen.Entry = FVector(800.0, 0.0, 0.0);
	const int32 Mid = Rig.Sink->Plays.Num();
	Rig.Hub->OnPenetration.Broadcast(Pen);
	TestEqual(TEXT("opponent's impact 8 m away: not heard"), Rig.Sink->Plays.Num(), Mid);
	Pen.ShooterId = LocalId;
	Rig.Hub->OnPenetration.Broadcast(Pen);
	TestEqual(TEXT("own impact 8 m away: heard"), Rig.Sink->Plays.Num(), Mid + 1);
	return true;
}

// Parity Z-15: never the same take twice in a row; every take gets used.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioVariants, "Verse.UI.Audio.VariantNoRepeat", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioVariants::RunTest(const FString&)
{
	FVerseVariantPicker Picker(3);
	int32 Last = INDEX_NONE;
	TSet<int32> Seen;
	bool bRepeat = false;
	for (int32 I = 0; I < 200; ++I)
	{
		const int32 V = Picker.Pick(TEXT("fs_metal"), 4);
		bRepeat |= V == Last;
		Seen.Add(V);
		Last = V;
	}
	TestFalse(TEXT("no consecutive repeat over 200 plays"), bRepeat);
	TestEqual(TEXT("all 4 takes used"), Seen.Num(), 4);
	TestEqual(TEXT("one take: always 0"), Picker.Pick(TEXT("amb_hangar"), 1), 0);
	return true;
}

// Voice budget rules on their own.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioBudget, "Verse.UI.Audio.VoiceBudget", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioBudget::RunTest(const FString&)
{
	FVerseVoiceBudget Budget;
	Budget.Max = 3;
	auto Add = [&Budget](int32 Handle, FName Cue, float Priority, double Start, double End)
	{
		Budget.Add({Handle, Cue, Priority, Start, End});
	};
	Add(1, TEXT("a"), 2.f, 0.0, 5.0);
	Add(2, TEXT("b"), 5.f, 0.1, 5.0);
	Add(3, TEXT("c"), 1.f, 0.2, -1.0);
	FVerseVoiceBudget::FDecision D = Budget.Request(TEXT("d"), 3.f, 4, 1.0);
	TestTrue(TEXT("full: a higher priority steals"), D.bAdmit && D.StealHandle == 3);
	D = Budget.Request(TEXT("d"), 0.5f, 4, 1.0);
	TestFalse(TEXT("full: a lower priority is refused"), D.bAdmit);
	D = Budget.Request(TEXT("a"), 0.1f, 1, 1.0);
	TestTrue(TEXT("over its own limit a cue replaces its oldest voice"), D.bAdmit && D.StealHandle == 1);
	Budget.Prune(6.0);
	TestEqual(TEXT("finished voices are pruned; loops stay"), Budget.Num(), 1);
	return true;
}

// Mix: the Verse master limiter is built with the mix.json settings.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioLimiter, "Verse.UI.Audio.Limiter", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioLimiter::RunTest(const FString&)
{
	FVerseAudioMixSettings Mix;
	Mix.LimiterThresholdDb = -2.5f;
	USoundEffectSubmixPreset* Preset = FVerseEngineAudioSink::MakeLimiterPreset(GetTransientPackage(), Mix);
	if (!TestNotNull(TEXT("dynamics processor preset (AudioMixer loaded)"), Preset))
	{
		return false;
	}
	const FStructProperty* SettingsProp = FindFProperty<FStructProperty>(Preset->GetClass(), TEXT("Settings"));
	const FFloatProperty* Threshold = SettingsProp ? FindFProperty<FFloatProperty>(SettingsProp->Struct, TEXT("ThresholdDb")) : nullptr;
	if (TestNotNull(TEXT("threshold property"), Threshold))
	{
		TestEqual(TEXT("threshold from mix.json"), Threshold->GetPropertyValue_InContainer(SettingsProp->ContainerPtrToValuePtr<void>(Preset)), -2.5f);
	}
	return true;
}

// A19.6 and the import: DA_AudioCues holds every cue of cues.json, each variant set, each licence cited.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseAudioShippedCues, "Verse.UI.Audio.ShippedCues", VERSE_AUDIO_TEST_FLAGS)
bool FVerseAudioShippedCues::RunTest(const FString&)
{
	// Headless test runs create no audio device, so the default (BINKA) decoder is never
	// registered and loading a sound wave would fail an engine ensure.
	FModuleManager::Get().LoadModule(TEXT("BinkAudioDecoder"));
	const UVerseAudioCueSet* Set = LoadObject<UVerseAudioCueSet>(nullptr, UVerseAudioCueSet::DefaultAssetPath);
	if (!TestNotNull(TEXT("DA_AudioCues is imported"), Set))
	{
		return false;
	}
	FString CuesJson;
	const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Data/audio/cues.json"));
	if (!TestTrue(TEXT("cues.json readable"), FFileHelper::LoadFileToString(CuesJson, *Path)))
	{
		return false;
	}
	// One chunk per cue object; the fields read here are flat strings and numbers (verse.audio.cues/1).
	auto Field = [](const FString& Chunk, const TCHAR* Pattern) -> FString
	{
		FRegexMatcher M(FRegexPattern(Pattern), Chunk);
		return M.FindNext() ? M.GetCaptureGroup(1) : FString();
	};
	TArray<FString> Chunks;
	CuesJson.ParseIntoArray(Chunks, TEXT("\"id\": \""), true);
	int32 Problems = 0;
	int32 Sounds = 0;
	int32 Listed = 0;
	for (int32 I = 1; I < Chunks.Num(); ++I)
	{
		const FString& Chunk = Chunks[I];
		const FName Id(*Chunk.Left(Chunk.Find(TEXT("\""))));
		++Listed;
		const FVerseAudioCue* Cue = Set->FindCue(Id);
		if (!TestNotNull(*FString::Printf(TEXT("cue %s in DA_AudioCues"), *Id.ToString()), Cue))
		{
			++Problems;
			continue;
		}
		const int32 Want = FCString::Atoi(*Field(Chunk, TEXT("\"variants\": (\\d+)")));
		const FString Licence = Field(Chunk, TEXT("\"licence\": \"([^\"]*)\""));
		const FString Noise = Field(Chunk, TEXT("\"noise\": \"([^\"]*)\""));
		bool bOk = Want > 0 && Cue->Variants.Num() == Want;
		for (const TObjectPtr<USoundBase>& Sound : Cue->Variants)
		{
			bOk &= Sound != nullptr;
			Sounds += Sound ? 1 : 0;
		}
		bOk &= Cue->Licence == Licence && (Licence == TEXT("own") || Licence.StartsWith(TEXT("cc0:")));
		bOk &= Noise.IsEmpty() || Verse::Audio::NoiseTagByName(FName(*Noise)).IsValid();
		TestTrue(*FString::Printf(TEXT("cue %s: %d variants, licence %s, noise tag valid"), *Id.ToString(), Want, *Licence), bOk);
		Problems += bOk ? 0 : 1;
	}
	TestTrue(TEXT("cues.json lists cues"), Listed > 0);
	TestEqual(TEXT("DA_AudioCues has exactly the cues of cues.json"), Set->Cues.Num(), Listed);
	TestEqual(TEXT("A19.6 cue problems"), Problems, 0);

	FProof Report;
	Report.Str(TEXT("test"), TEXT("A19.6 licence (asset side)"));
	Report.Num(TEXT("cues"), Set->Cues.Num());
	Report.Num(TEXT("sound_waves"), Sounds);
	Report.Num(TEXT("problems"), Problems);
	WriteProof(TEXT("19.9"), TEXT("shipped_cues.json"), Report);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Audio/VerseAudioSubsystem.h"

#include "Audio/VerseAudioCueSet.h"
#include "Destruction/VerseDestructionInterfaces.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameFramework/GameStateBase.h"
#include "GameFramework/Pawn.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "GameplayTagContainer.h"
#include "Noise/VerseAudibilityTable.h"
#include "Sound/SoundAttenuation.h"
#include "Sound/SoundBase.h"
#include "Stubs/VerseNullStubs.h"
#include "VerseEngineAudioSink.h"
#include "VerseLog.h"

namespace
{
	enum class ELoopKind : int64
	{
		Drone = 1,
		Bulwark = 2,
		Ambience = 3,
		CrewBed = 4,
		Lift = 5,
	};

	int64 LoopKey(ELoopKind Kind, int32 Id)
	{
		return (int64(Kind) << 32) | int64(uint32(Id));
	}

	FName AmbienceCue(EVerseAmbience Ambience)
	{
		switch (Ambience)
		{
		case EVerseAmbience::Bridge: return TEXT("amb_bridge");
		case EVerseAmbience::Ops: return TEXT("amb_ops");
		case EVerseAmbience::Engineering: return TEXT("amb_engineering");
		case EVerseAmbience::Hangar: return TEXT("amb_hangar");
		default: return NAME_None;
		}
	}

	FName FootstepCue(EVerseFootSurface Surface)
	{
		switch (Surface)
		{
		case EVerseFootSurface::Grating: return TEXT("fs_grating");
		case EVerseFootSurface::Concrete: return TEXT("fs_concrete");
		case EVerseFootSurface::Rubble: return TEXT("fs_rubble");
		default: return TEXT("fs_metal");
		}
	}

	FName GaitNoise(EVerseGait Gait)
	{
		switch (Gait)
		{
		case EVerseGait::Walk: return TEXT("Noise.Footstep.Walk");
		case EVerseGait::Run: return TEXT("Noise.Footstep.Run");
		case EVerseGait::Sprint: return TEXT("Noise.Footstep.Sprint");
		default: return NAME_None; // crouch walk, prone crawl: no noise (bot.md 3.2)
		}
	}

	float GaitGain(EVerseGait Gait)
	{
		switch (Gait)
		{
		case EVerseGait::CrouchWalk: return 0.35f;
		case EVerseGait::ProneCrawl: return 0.25f;
		case EVerseGait::Walk: return 0.6f;
		case EVerseGait::Run: return 0.85f;
		default: return 1.f;
		}
	}

	FVector PieceLocalToWorld(const FBox& Bounds, const int16 LocalMm[3])
	{
		// The fracture location is piece-local in mm; the piece bounds centre is a good anchor for sound.
		return Bounds.IsValid ? Bounds.GetCenter() : FVector(LocalMm[0], LocalMm[1], LocalMm[2]) * 0.1;
	}
}

UVerseAudioSubsystem* UVerseAudioSubsystem::Get(const UObject* WorldContextObject)
{
	if (!WorldContextObject || !GEngine)
	{
		return nullptr;
	}
	const UWorld* World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull);
	return World ? World->GetSubsystem<UVerseAudioSubsystem>() : nullptr;
}

bool UVerseAudioSubsystem::ShouldCreateSubsystem(UObject* Outer) const
{
	const UWorld* World = Cast<UWorld>(Outer);
	return World && (World->WorldType == EWorldType::Game || World->WorldType == EWorldType::PIE)
		&& Super::ShouldCreateSubsystem(Outer);
}

void UVerseAudioSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	UVerseEventHub* EventHub = Collection.InitializeDependency<UVerseEventHub>();
	Hub = EventHub;
	if (EventHub)
	{
		EventHub->OnFire.AddUObject(this, &UVerseAudioSubsystem::HandleFire);
		EventHub->OnHit.AddUObject(this, &UVerseAudioSubsystem::HandleHit);
		EventHub->OnPenetration.AddUObject(this, &UVerseAudioSubsystem::HandlePenetration);
		EventHub->OnReload.AddUObject(this, &UVerseAudioSubsystem::HandleReload);
		EventHub->OnGadget.AddUObject(this, &UVerseAudioSubsystem::HandleGadget);
		EventHub->OnFracture.AddUObject(this, &UVerseAudioSubsystem::HandleFracture);
		EventHub->OnFinisher.AddUObject(this, &UVerseAudioSubsystem::HandleFinisher);
	}
	SetSink(nullptr);
	SetCueSet(nullptr);
}

void UVerseAudioSubsystem::Deinitialize()
{
	if (UVerseEventHub* EventHub = Hub.Get())
	{
		EventHub->OnFire.RemoveAll(this);
		EventHub->OnHit.RemoveAll(this);
		EventHub->OnPenetration.RemoveAll(this);
		EventHub->OnReload.RemoveAll(this);
		EventHub->OnGadget.RemoveAll(this);
		EventHub->OnFracture.RemoveAll(this);
		EventHub->OnFinisher.RemoveAll(this);
	}
	if (Sink)
	{
		Sink->Shutdown();
		Sink.Reset();
	}
	Loops.Reset();
	Pending.Reset();
	Budget.Reset();
	Super::Deinitialize();
}

TStatId UVerseAudioSubsystem::GetStatId() const
{
	RETURN_QUICK_DECLARE_CYCLE_STAT(UVerseAudioSubsystem, STATGROUP_Tickables);
}

void UVerseAudioSubsystem::SetCueSet(UVerseAudioCueSet* InCueSet)
{
	CueSet = InCueSet;
	if (!CueSet)
	{
		CueSet = LoadObject<UVerseAudioCueSet>(nullptr, UVerseAudioCueSet::DefaultAssetPath, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}
	if (!CueSet)
	{
		CueSet = NewObject<UVerseAudioCueSet>(this, NAME_None, RF_Transient); // no sounds; rules still apply
	}
	CueSet->RebuildIndex();
	Budget.Max = FMath::Max(1, CueSet->Mix.MaxVoices);
	AttenuationCache.Reset();
	RouteCueSet();
	PreloadDuelSet();
	ApplyMasterVolume();
}

void UVerseAudioSubsystem::SetSink(TSharedPtr<IVerseAudioSink> InSink)
{
	if (Sink)
	{
		Sink->Shutdown();
	}
	Sink = InSink ? InSink : MakeShared<FVerseEngineAudioSink>();
	const FVerseAudioMixSettings Mix = CueSet ? CueSet->Mix : FVerseAudioMixSettings();
	Sink->Initialize(GetWorld(), Mix);
	Budget.Reset();
	Loops.Reset();
	RouteCueSet();
	ApplyMasterVolume();
}

void UVerseAudioSubsystem::RouteCueSet()
{
	if (!Sink || !CueSet)
	{
		return;
	}
	for (const FVerseAudioCue& Cue : CueSet->Cues)
	{
		for (USoundBase* Sound : Cue.Variants)
		{
			Sink->Route(Sound, Cue.Bus);
		}
	}
}

int32 UVerseAudioSubsystem::GetLocalPlayerId() const
{
	if (LocalPlayerIdOverride != INDEX_NONE)
	{
		return LocalPlayerIdOverride;
	}
	if (const UWorld* World = GetWorld())
	{
		if (const APlayerController* PC = World->GetFirstPlayerController())
		{
			if (PC->IsLocalController() && PC->PlayerState)
			{
				return PC->PlayerState->GetPlayerId();
			}
		}
	}
	return INDEX_NONE;
}

FVector UVerseAudioSubsystem::GetListenerLocation() const
{
	if (ListenerOverride.IsSet())
	{
		return ListenerOverride.GetValue();
	}
	if (const UWorld* World = GetWorld())
	{
		if (const APlayerController* PC = World->GetFirstPlayerController())
		{
			FVector Location, Front, Right;
			PC->GetAudioListenerPosition(Location, Front, Right);
			return Location;
		}
	}
	return FVector::ZeroVector;
}

bool UVerseAudioSubsystem::IsLocal(int32 PlayerId) const
{
	const int32 Local = GetLocalPlayerId();
	return Local != INDEX_NONE && PlayerId == Local;
}

const IVersePieceQuery& UVerseAudioSubsystem::Pieces() const
{
	return PieceQuery ? *PieceQuery : *GetDefault<UVerseNullPieceQuery>();
}

// ---------------------------------------------------------------------------------------- lifecycle

void UVerseAudioSubsystem::SetDormant(bool bInDormant)
{
	bDormant = bInDormant;
	if (bDormant)
	{
		FadeLevel = 0.f; // A19.5: muted at once, never later than the next audio buffer
	}
	ApplyMasterVolume();
}

void UVerseAudioSubsystem::SetUiSoundEnabled(bool bEnabled)
{
	bUiSoundEnabled = bEnabled;
	ApplyMasterVolume();
}

void UVerseAudioSubsystem::SetLevelSoundEnabled(bool bEnabled)
{
	bLevelSoundEnabled = bEnabled;
}

TArray<FName> UVerseAudioSubsystem::DuelCueIds(const TArray<FName>& WeaponProfiles)
{
	TArray<FName> Ids;
	for (const FName& Profile : WeaponProfiles)
	{
		const FString P = Profile.ToString();
		for (const TCHAR* Suffix : {TEXT("fp_mech"), TEXT("fp_body"), TEXT("tp_near"), TEXT("tp_far"), TEXT("tp_tail")})
		{
			Ids.Add(*FString::Printf(TEXT("wpn_%s_%s"), *P, Suffix));
		}
		Ids.Add(*FString::Printf(TEXT("wpn_%s_tail"), *P));
		Ids.Add(*FString::Printf(TEXT("rld_%s_tactical"), *P));
		Ids.Add(*FString::Printf(TEXT("rld_%s_empty"), *P));
		Ids.Add(*FString::Printf(TEXT("eqp_%s"), *P));
	}
	for (const TCHAR* Id : {TEXT("bolt_flyby"), TEXT("imp_sheet_metal"), TEXT("imp_container_wall"), TEXT("imp_glass"),
			 TEXT("imp_cladding_panel"), TEXT("imp_catwalk_grating"), TEXT("imp_ceiling_panel"), TEXT("imp_concrete"),
			 TEXT("imp_armor_steel"), TEXT("imp_flesh"), TEXT("imp_penetration_exit"), TEXT("imp_hurt"), TEXT("fs_metal"),
			 TEXT("fs_grating"), TEXT("fs_concrete"), TEXT("fs_rubble"), TEXT("fs_metal_boots"), TEXT("fol_slide"),
			 TEXT("fol_land"), TEXT("fol_mantle"), TEXT("fol_lean"), TEXT("mel_knife_swing"), TEXT("mel_knife_hit"),
			 TEXT("eqp_knife"), TEXT("fin_takedown"), TEXT("fin_struggle"), TEXT("fin_kill"), TEXT("dst_wall_panel"),
			 TEXT("dst_cladding_wall"), TEXT("dst_container_wall"), TEXT("dst_glass_pane"), TEXT("dst_catwalk_segment"),
			 TEXT("dst_ceiling_panel"), TEXT("dst_hole"), TEXT("dst_settle_metal"), TEXT("dst_settle_glass"),
			 TEXT("dst_settle_dust"), TEXT("drn_flight"), TEXT("drn_weld"), TEXT("gad_bulwark_deploy"), TEXT("gad_bulwark_hum"),
			 TEXT("gad_bulwark_destroyed"), TEXT("gad_breach_plant"), TEXT("gad_breach_detonate"), TEXT("ui_click"),
			 TEXT("ui_confirm"), TEXT("ui_back")})
	{
		Ids.Add(Id);
	}
	return Ids;
}

TArray<FName> UVerseAudioSubsystem::PreloadDuelSet()
{
	MissingDuelCues.Reset();
	if (!CueSet)
	{
		bDuelPreloaded = false;
		return MissingDuelCues;
	}
	TArray<FName> Profiles = CueSet->WeaponProfiles;
	Profiles.AddUnique(CueSet->DefaultWeaponProfile);
	for (const FName& CueId : DuelCueIds(Profiles))
	{
		const FVerseAudioCue* Cue = CueSet->FindCue(CueId);
		bool bAnySound = false;
		if (Cue)
		{
			for (USoundBase* Sound : Cue->Variants)
			{
				if (Sound)
				{
					// Fully load it now: a first shot never waits for a PostLoad.
					Sound->ConditionalPostLoad();
					bAnySound = true;
				}
			}
		}
		if (!bAnySound)
		{
			MissingDuelCues.Add(CueId);
			UE_LOG(LogVerseUI, Verbose, TEXT("Verse audio: duel cue %s is missing or has no sound"), *CueId.ToString());
		}
	}
	bDuelPreloaded = true;
	return MissingDuelCues;
}

void UVerseAudioSubsystem::SetUserVolume(float Volume)
{
	UserVolume = FMath::Clamp(Volume, 0.f, 1.f);
	ApplyMasterVolume();
}

void UVerseAudioSubsystem::ApplyMasterVolume()
{
	const bool bMuted = bDormant || !bUiSoundEnabled;
	MasterVolume = bMuted ? 0.f : UserVolume * FadeLevel;
	if (Sink)
	{
		Sink->SetMasterVolume(MasterVolume);
	}
}

void UVerseAudioSubsystem::Tick(float DeltaTime)
{
	Super::Tick(DeltaTime);
	Now += DeltaTime;

	if (!bDormant && FadeLevel < 1.f)
	{
		const float FadeS = CueSet ? FMath::Max(0.001f, CueSet->Mix.DormantUnmuteFadeS) : 0.15f;
		FadeLevel = FMath::Min(1.f, FadeLevel + DeltaTime / FadeS);
		ApplyMasterVolume();
	}

	if (Pending.Num() > 0)
	{
		TArray<FPending> Due;
		for (int32 I = Pending.Num() - 1; I >= 0; --I)
		{
			if (Pending[I].At <= Now)
			{
				Due.Add(Pending[I]);
				Pending.RemoveAtSwap(I);
			}
		}
		Due.Sort([](const FPending& A, const FPending& B) { return A.At < B.At; });
		for (const FPending& P : Due)
		{
			PlayCue(P.CueId, P.Params);
		}
	}

	Budget.Prune(Now);

	// Loops: follow the listener's occlusion (a hole opened in a wall opens the sound, 19.7).
	if (CueSet && Sink)
	{
		const FVector Listener = GetListenerLocation();
		for (TPair<int64, FLoop>& Pair : Loops)
		{
			FLoop& Loop = Pair.Value;
			const FVerseAudioCue* Cue = CueSet->FindCue(Loop.CueId);
			if (!Cue || !Cue->bSpatial || Now < Loop.NextOcclusionAt)
			{
				continue;
			}
			Loop.NextOcclusionAt = Now + CueSet->Mix.OcclusionRefreshS;
			const FVerseOcclusion Occ = Verse::Audio::TraceOcclusion(PenetrationQuery, Listener, Loop.Params.Location, CueSet->Mix);
			Sink->SetVoiceOcclusion(Loop.Handle, Occ.Gain(), Occ.LowpassHz);
		}
	}
}

// ---------------------------------------------------------------------------------------- core play

float UVerseAudioSubsystem::RangeForNoise(FName NoiseTag, float Loudness) const
{
	const FGameplayTag Tag = Verse::Audio::NoiseTagByName(NoiseTag);
	if (!Tag.IsValid() || !CueSet)
	{
		return 0.f;
	}
	return CueSet->GetAudibility().GetAudibleRangeM(Tag, Loudness);
}

void UVerseAudioSubsystem::MakeNoiseAttenuation(FName NoiseTag, float Loudness, FSoundAttenuationSettings& Out) const
{
	Verse::Audio::BuildAttenuation(RangeForNoise(NoiseTag, Loudness), CueSet ? CueSet->Mix : FVerseAudioMixSettings(), Out);
}

USoundAttenuation* UVerseAudioSubsystem::AttenuationFor(float RangeM)
{
	const int32 Key = FMath::RoundToInt(FMath::Min(RangeM, UVerseAudibilityTable::WholeArenaRangeM) * 10.f);
	if (TObjectPtr<USoundAttenuation>* Found = AttenuationCache.Find(Key))
	{
		return *Found;
	}
	USoundAttenuation* Attenuation = NewObject<USoundAttenuation>(this, NAME_None, RF_Transient);
	Verse::Audio::BuildAttenuation(RangeM, CueSet->Mix, Attenuation->Attenuation);
	AttenuationCache.Add(Key, Attenuation);
	return Attenuation;
}

int32 UVerseAudioSubsystem::PlayCue(FName CueId, const FPlayParams& Params, float* OutBaseVolume)
{
	if (!CueSet || !Sink)
	{
		return 0;
	}
	const FVerseAudioCue* Cue = CueSet->FindCue(CueId);
	if (!Cue)
	{
		UE_LOG(LogVerseUI, Verbose, TEXT("Verse audio: no cue %s"), *CueId.ToString());
		return 0;
	}
	const FVerseAudioMixSettings& Mix = CueSet->Mix;
	const bool bOwn = Params.SourceId != INDEX_NONE && IsLocal(Params.SourceId);
	const bool bSpatial = Cue->bSpatial && !bOwn;

	float RangeM = 0.f;
	if (bSpatial)
	{
		if (Params.RangeOverrideM > 0.f)
		{
			RangeM = Params.RangeOverrideM;
		}
		else if (!Cue->NoiseTag.IsNone())
		{
			RangeM = RangeForNoise(Cue->NoiseTag, Params.Loudness);
		}
		else
		{
			RangeM = Cue->RangeM > 0.f ? Cue->RangeM : 50.f;
		}
	}

	const FVector Listener = GetListenerLocation();
	FVerseOcclusion Occ;
	Occ.LowpassHz = Mix.OpenLowpassHz;
	if (bSpatial)
	{
		const float DistM = float(FVector::Dist(Listener, Params.Location) / 100.0);
		if (RangeM <= 0.f || DistM >= RangeM)
		{
			// Out of range: the bot would not hear it either (F6). Nothing plays, no voice is used.
			Log(CueId, INDEX_NONE, Params, bSpatial, RangeM, 0.f, 1.f, Occ, false, false);
			return 0;
		}
		Occ = Verse::Audio::TraceOcclusion(PenetrationQuery, Listener, Params.Location, Mix);
	}

	const int32 VariantCount = Cue->Variants.Num();
	const int32 Variant = Picker.Pick(CueId, FMath::Max(1, VariantCount));
	USoundBase* Sound = Cue->Variants.IsValidIndex(Variant) ? Cue->Variants[Variant].Get() : nullptr;
	const float Pitch = Picker.Range(Cue->Pitch);
	const float BusDb = Mix.BusGainDb.IsValidIndex(int32(Cue->Bus)) ? Mix.BusGainDb[int32(Cue->Bus)] : 0.f;
	const float BaseVolume = Picker.Range(Cue->Volume) * Params.Gain * Verse::Audio::DbToGain(BusDb + Mix.MasterGainDb);
	const float Volume = BaseVolume * Occ.Gain();
	if (OutBaseVolume)
	{
		*OutBaseVolume = BaseVolume;
	}

	const FVerseVoiceBudget::FDecision Decision = Budget.Request(CueId, Cue->Priority, Cue->MaxVoices, Now);
	if (!Decision.bAdmit)
	{
		Log(CueId, Variant, Params, bSpatial, RangeM, Volume, Pitch, Occ, false, false);
		return 0;
	}
	if (Decision.StealHandle != 0)
	{
		StopVoice(Decision.StealHandle, 0.03f);
	}

	const int32 Handle = NextHandle++;
	const float Duration = Sound ? Sound->GetDuration() : 1.f;
	const bool bLoop = Cue->bLoop || (Sound && Sound->IsLooping());
	FVerseVoice Voice;
	Voice.Handle = Handle;
	Voice.CueId = CueId;
	Voice.Priority = Cue->Priority;
	Voice.StartTime = Now;
	Voice.EndTime = bLoop ? -1.0 : Now + Duration / FMath::Max(0.1f, Pitch);
	Budget.Add(Voice);
	PeakVoices = FMath::Max(PeakVoices, Budget.Num());

	FVerseAudioPlayRequest Request;
	Request.CueId = CueId;
	Request.Sound = Sound;
	Request.bSpatial = bSpatial;
	Request.Location = Params.Location;
	Request.Attenuation = bSpatial ? AttenuationFor(RangeM) : nullptr;
	Request.Volume = BaseVolume; // the multiplier; occlusion rides on the fader
	Request.Fader = Occ.Gain();
	Request.Pitch = Pitch;
	Request.LowpassHz = Occ.LowpassHz;
	Sink->Play(Handle, Request);
	Log(CueId, Variant, Params, bSpatial, RangeM, Volume, Pitch, Occ, true, Decision.StealHandle != 0);
	return Handle;
}

void UVerseAudioSubsystem::StopVoice(int32 Handle, float FadeOutS)
{
	if (Handle == 0)
	{
		return;
	}
	Budget.Remove(Handle);
	if (Sink)
	{
		Sink->Stop(Handle, FadeOutS);
	}
}

void UVerseAudioSubsystem::StartLoop(int64 Key, FName CueId, const FPlayParams& Params)
{
	StopLoop(Key, 0.1f);
	float BaseVolume = 1.f;
	const int32 Handle = PlayCue(CueId, Params, &BaseVolume);
	if (Handle == 0)
	{
		return;
	}
	FLoop Loop;
	Loop.Handle = Handle;
	Loop.CueId = CueId;
	Loop.Params = Params;
	Loop.NextOcclusionAt = Now + (CueSet ? CueSet->Mix.OcclusionRefreshS : 0.25f);
	Loop.BaseVolume = BaseVolume;
	Loops.Add(Key, Loop);
}

void UVerseAudioSubsystem::StopLoop(int64 Key, float FadeOutS)
{
	FLoop Loop;
	if (Loops.RemoveAndCopyValue(Key, Loop))
	{
		StopVoice(Loop.Handle, FadeOutS);
		FPlayParams None;
		FVerseOcclusion Occ;
		Log(Loop.CueId, INDEX_NONE, None, false, 0.f, 0.f, 1.f, Occ, true, false, true);
	}
}

void UVerseAudioSubsystem::Log(FName CueId, int32 Variant, const FPlayParams& Params, bool bSpatial, float RangeM, float Volume,
	float Pitch, const FVerseOcclusion& Occlusion, bool bAdmitted, bool bStole, bool bStop)
{
	if (EventLog.Num() >= MaxLogEntries)
	{
		EventLog.RemoveAt(0, MaxLogEntries / 4);
	}
	FVerseAudioLogEntry& Entry = EventLog.AddDefaulted_GetRef();
	Entry.CueId = CueId;
	Entry.Variant = Variant;
	Entry.Frame = int64(GFrameCounter);
	Entry.Time = Now;
	Entry.Location = Params.Location;
	Entry.bSpatial = bSpatial;
	Entry.RangeM = RangeM;
	Entry.Volume = Volume;
	Entry.Pitch = Pitch;
	Entry.OcclusionLossDb = Occlusion.LossDb;
	Entry.LowpassHz = Occlusion.LowpassHz;
	Entry.bAdmitted = bAdmitted;
	Entry.bStole = bStole;
	Entry.bStop = bStop;
}

FName UVerseAudioSubsystem::WeaponCue(FName WeaponId, const TCHAR* Prefix, const TCHAR* Suffix) const
{
	const FName Profile = CueSet ? CueSet->WeaponProfileFor(WeaponId) : FName(TEXT("rifle"));
	return FName(*FString::Printf(TEXT("%s_%s%s"), Prefix, *Profile.ToString(), Suffix));
}

// ---------------------------------------------------------------------------------------- hub events

void UVerseAudioSubsystem::HandleFire(const FVerseFireEvent& Event)
{
	// A19.2: the first layer is issued in the same frame the shot is published.
	FPlayParams Params;
	Params.Location = Event.Origin;
	Params.SourceId = Event.ShooterId;
	if (IsLocal(Event.ShooterId))
	{
		PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_fp_body")), Params);
		PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_fp_mech")), Params);
		PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_tail")), Params);
		return;
	}
	const FVector Listener = GetListenerLocation();
	const float DistM = float(FVector::Dist(Listener, FVector(Event.Origin)) / 100.0);
	const float Far = Verse::Audio::ShotFarWeight(DistM, CueSet->Mix);
	if (Far < 0.999f)
	{
		FPlayParams Near = Params;
		Near.Gain = 1.f - Far;
		PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_tp_near")), Near);
	}
	if (Far > 0.001f)
	{
		FPlayParams FarParams = Params;
		FarParams.Gain = Far;
		PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_tp_far")), FarParams);
	}
	PlayCue(WeaponCue(Event.WeaponId, TEXT("wpn"), TEXT("_tp_tail")), Params);

	float PassM = 0.f, TimeS = 0.f;
	FVector Point;
	if (Verse::Audio::BoltClosestApproach(Event.Origin, Event.Direction, Listener, CueSet->Mix.BoltSpeedMps, PassM, TimeS, Point)
		&& PassM <= CueSet->Mix.FlybyRadiusM)
	{
		FPending Flyby;
		Flyby.At = Now + TimeS;
		Flyby.CueId = TEXT("bolt_flyby");
		Flyby.Params.Location = Point;
		Flyby.Params.SourceId = INDEX_NONE; // the bolt, not the shooter, makes this sound
		Pending.Add(Flyby);
	}
}

void UVerseAudioSubsystem::HandleHit(const FVerseHitEvent& Event)
{
	if (IsLocal(Event.VictimId))
	{
		FPlayParams Hurt;
		Hurt.SourceId = Event.VictimId;
		PlayCue(TEXT("imp_hurt"), Hurt);
		return;
	}
	FPlayParams Params;
	Params.Location = Event.ImpactWorld;
	Params.SourceId = INDEX_NONE;
	if (IsLocal(Event.InstigatorId))
	{
		// The shooter's own hit feedback; the bot gets its own hits as hit confirms too.
		const FVerseAudioCue* Cue = CueSet->FindCue(TEXT("imp_flesh"));
		Params.RangeOverrideM = Cue ? Cue->RangeM : 0.f;
	}
	PlayCue(Event.Source == EVerseDamageSource::Melee ? FName(TEXT("mel_knife_hit")) : FName(TEXT("imp_flesh")), Params);
}

void UVerseAudioSubsystem::HandlePenetration(const FVersePenetrationEvent& Event)
{
	const EVersePenetrationMaterial Material = EVersePenetrationMaterial(Event.MaterialWireId);
	const FName Impact = Verse::Audio::ImpactCueFor(Material);
	FPlayParams Params;
	Params.Location = Event.Entry;
	if (IsLocal(Event.ShooterId))
	{
		const FVerseAudioCue* Cue = CueSet->FindCue(Impact);
		Params.RangeOverrideM = Cue ? Cue->RangeM : 0.f;
	}
	PlayCue(Impact, Params);
	if (Event.bPassed)
	{
		FPlayParams Exit = Params;
		Exit.Location = Event.Exit;
		PlayCue(TEXT("imp_penetration_exit"), Exit);
	}
}

void UVerseAudioSubsystem::PlayImpact(int32 ShooterId, EVersePenetrationMaterial Material, const FVector& Location)
{
	const FName Impact = Verse::Audio::ImpactCueFor(Material);
	FPlayParams Params;
	Params.Location = Location;
	if (IsLocal(ShooterId))
	{
		const FVerseAudioCue* Cue = CueSet->FindCue(Impact);
		Params.RangeOverrideM = Cue ? Cue->RangeM : 0.f;
	}
	PlayCue(Impact, Params);
}

TOptional<FVector> UVerseAudioSubsystem::FindPlayerLocation(int32 PlayerId) const
{
	if (PlayerLocationResolver)
	{
		return PlayerLocationResolver(PlayerId);
	}
	if (const UWorld* World = GetWorld())
	{
		if (const AGameStateBase* GameState = World->GetGameState())
		{
			for (const APlayerState* State : GameState->PlayerArray)
			{
				if (State && State->GetPlayerId() == PlayerId)
				{
					if (const APawn* Pawn = State->GetPawn())
					{
						return Pawn->GetActorLocation();
					}
					break;
				}
			}
		}
	}
	return {};
}

void UVerseAudioSubsystem::HandleReload(const FVerseReloadEvent& Event)
{
	const FName CueId = WeaponCue(Event.WeaponId, TEXT("rld"), Event.bTactical ? TEXT("_tactical") : TEXT("_empty"));
	int32 Existing = 0;
	if (ReloadVoices.RemoveAndCopyValue(Event.PlayerId, Existing))
	{
		// A new reload or a cancel ends the player's previous reload voice; it is never left running.
		StopVoice(Existing, 0.08f);
		if (Event.bCancelled)
		{
			FPlayParams None;
			FVerseOcclusion Occ;
			Log(CueId, INDEX_NONE, None, false, 0.f, 0.f, 1.f, Occ, true, false, true);
		}
	}
	if (Event.bCancelled)
	{
		return;
	}
	FPlayParams Params;
	Params.SourceId = Event.PlayerId;
	if (!IsLocal(Event.PlayerId))
	{
		// Someone else's reload (the listen-server host gets the bot's server-raised event): it
		// plays at the reloading pawn with the Noise.Reload range, the range the bot hears the
		// person's reloads at (F6). Without a known location nothing plays, never at the origin.
		const TOptional<FVector> Where = FindPlayerLocation(Event.PlayerId);
		if (!Where.IsSet())
		{
			return;
		}
		Params.Location = Where.GetValue();
	}
	const int32 Handle = PlayCue(CueId, Params);
	if (Handle != 0)
	{
		ReloadVoices.Add(Event.PlayerId, Handle);
	}
}

void UVerseAudioSubsystem::HandleGadget(const FVerseGadgetEvent& Event)
{
	const FString Id = Event.GadgetId.ToString();
	const bool bBulwark = Id.Contains(TEXT("bulwark"), ESearchCase::IgnoreCase);
	FPlayParams Params;
	Params.Location = Event.Location;
	Params.SourceId = INDEX_NONE; // gadgets are world objects: placed and attenuated for everyone
	const int64 Key = LoopKey(ELoopKind::Bulwark, Event.OwnerId);
	switch (Event.Kind)
	{
	case EVerseGadgetEventKind::Deploy:
		if (bBulwark)
		{
			PlayCue(TEXT("gad_bulwark_deploy"), Params);
			StartLoop(Key, TEXT("gad_bulwark_hum"), Params);
		}
		break;
	case EVerseGadgetEventKind::Destroyed:
		if (bBulwark)
		{
			StopLoop(Key, 0.05f);
			PlayCue(TEXT("gad_bulwark_destroyed"), Params);
		}
		break;
	case EVerseGadgetEventKind::Expired:
		if (bBulwark)
		{
			StopLoop(Key, 0.6f);
		}
		break;
	case EVerseGadgetEventKind::Plant:
		PlayCue(TEXT("gad_breach_plant"), Params);
		break;
	case EVerseGadgetEventKind::Detonate:
		PlayCue(TEXT("gad_breach_detonate"), Params);
		break;
	}
}

void UVerseAudioSubsystem::HandleFracture(const FVerseFractureEvent& Event)
{
	if (Event.PieceIndex == Verse::Destruction::AllPieces)
	{
		return; // arena reset: silent
	}
	const IVersePieceQuery& Query = Pieces();
	const EVersePenetrationMaterial Material = Query.GetPieceMaterial(Event.PieceIndex);
	const float Loudness = Verse::Audio::FractureLoudness(Event.FromState, Event.ToState, Event.Cause, Material);
	if (Loudness <= 0.f)
	{
		return;
	}
	FPlayParams Params;
	Params.Location = PieceLocalToWorld(Query.GetPieceBounds(Event.PieceIndex), Event.Location);
	Params.Loudness = Loudness;
	const bool bBreak = Event.ToState == EVersePieceState::Breached || Event.ToState == EVersePieceState::Destroyed;
	if (!bBreak)
	{
		PlayCue(TEXT("dst_hole"), Params);
		return;
	}
	PlayCue(Verse::Audio::DestructionCueFor(Material), Params);
	FPending Settle;
	const FVerseAudioMixSettings& Mix = CueSet->Mix;
	Settle.At = Now + Mix.SettleDelayMinS + (Mix.SettleDelayMaxS - Mix.SettleDelayMinS) * float(Event.Seed % 1000) / 1000.f;
	Settle.CueId = Verse::Audio::SettleCueFor(Material);
	Settle.Params = Params;
	Pending.Add(Settle);
}

void UVerseAudioSubsystem::HandleFinisher(const FVerseFinisherEvent& Event)
{
	FName Cue;
	switch (Event.Phase)
	{
	case EVerseFinisherPhase::Takedown: Cue = TEXT("fin_takedown"); break;
	case EVerseFinisherPhase::Struggle: Cue = TEXT("fin_struggle"); break;
	case EVerseFinisherPhase::Kill: Cue = TEXT("fin_kill"); break;
	default: return;
	}
	FPlayParams Params;
	Params.Location = Event.WarpTarget.GetLocation();
	// Attacker and victim hear it at the listener; everyone else at the warp point with Noise.Finisher.
	Params.SourceId = IsLocal(Event.VictimId) ? Event.VictimId : Event.AttackerId;
	PlayCue(Cue, Params);
}

// ---------------------------------------------------------------------------------------- calls

void UVerseAudioSubsystem::PlayFootstep(int32 PlayerId, EVerseFootSurface Surface, EVerseGait Gait, const FVector& Location)
{
	const bool bOwn = IsLocal(PlayerId);
	const FName Noise = GaitNoise(Gait);
	if (!bOwn && Noise.IsNone())
	{
		return; // crouched or prone steps of others: silent, as for the bot (F6)
	}
	FPlayParams Params;
	Params.Location = Location;
	Params.SourceId = PlayerId;
	Params.Gain = GaitGain(Gait);
	const float RangeM = bOwn ? 0.f : RangeForNoise(Noise, 1.f);
	Params.RangeOverrideM = RangeM;
	FName Cue = FootstepCue(Surface);
	if (Surface == EVerseFootSurface::Metal && (Picker.Range(FVector2D(0.0, 1.0)) < 0.5f))
	{
		Cue = TEXT("fs_metal_boots"); // recorded boots and synthesised steps alternate on deck plating
	}
	PlayCue(Cue, Params);
}

void UVerseAudioSubsystem::PlayFoley(int32 PlayerId, EVerseFoley Foley, const FVector& Location)
{
	FName Cue;
	switch (Foley)
	{
	case EVerseFoley::Slide: Cue = TEXT("fol_slide"); break;
	case EVerseFoley::Land: Cue = TEXT("fol_land"); break;
	case EVerseFoley::Mantle: Cue = TEXT("fol_mantle"); break;
	case EVerseFoley::LeanIn:
	case EVerseFoley::LeanOut: Cue = TEXT("fol_lean"); break;
	case EVerseFoley::ProneDown: Cue = TEXT("fol_prone_down"); break;
	case EVerseFoley::ProneUp: Cue = TEXT("fol_prone_up"); break;
	}
	const FVerseAudioCue* Data = CueSet->FindCue(Cue);
	if (!IsLocal(PlayerId) && (!Data || !Data->bSpatial))
	{
		return; // lean and prone foley raise no noise: own player only
	}
	FPlayParams Params;
	Params.Location = Location;
	Params.SourceId = PlayerId;
	PlayCue(Cue, Params);
}

void UVerseAudioSubsystem::PlayEquip(int32 PlayerId, FName WeaponId)
{
	if (!IsLocal(PlayerId))
	{
		return; // equip raises no noise
	}
	const FString Id = WeaponId.ToString();
	FPlayParams Params;
	Params.SourceId = PlayerId;
	PlayCue(Id.Contains(TEXT("knife"), ESearchCase::IgnoreCase) ? FName(TEXT("eqp_knife")) : WeaponCue(WeaponId, TEXT("eqp"), TEXT("")),
		Params);
}

void UVerseAudioSubsystem::PlayKnifeSwing(int32 PlayerId, const FVector& Location)
{
	FPlayParams Params;
	Params.Location = Location;
	Params.SourceId = PlayerId;
	PlayCue(TEXT("mel_knife_swing"), Params);
}

void UVerseAudioSubsystem::StartDroneLoop(int32 DroneKey, bool bWelding, const FVector& Location)
{
	FPlayParams Params;
	Params.Location = Location;
	Params.Loudness = Verse::Destruction::DroneLoudness;
	StartLoop(LoopKey(ELoopKind::Drone, DroneKey), bWelding ? FName(TEXT("drn_weld")) : FName(TEXT("drn_flight")), Params);
}

void UVerseAudioSubsystem::UpdateDroneLoop(int32 DroneKey, const FVector& Location)
{
	if (FLoop* Loop = Loops.Find(LoopKey(ELoopKind::Drone, DroneKey)))
	{
		Loop->Params.Location = Location;
		if (Sink)
		{
			Sink->SetVoiceLocation(Loop->Handle, Location);
		}
	}
}

void UVerseAudioSubsystem::StopDroneLoop(int32 DroneKey)
{
	StopLoop(LoopKey(ELoopKind::Drone, DroneKey), 0.3f);
}

void UVerseAudioSubsystem::SetAmbience(EVerseAmbience Ambience)
{
	if (Ambience == CurrentAmbience)
	{
		return;
	}
	CurrentAmbience = Ambience;
	const int64 Key = LoopKey(ELoopKind::Ambience, 0);
	StopLoop(Key, 1.5f);
	if (Ambience != EVerseAmbience::None)
	{
		StartLoop(Key, AmbienceCue(Ambience), FPlayParams());
	}
}

void UVerseAudioSubsystem::SetCrewBed(bool bOn)
{
	const int64 Key = LoopKey(ELoopKind::CrewBed, 0);
	if (bOn && !Loops.Contains(Key))
	{
		StartLoop(Key, TEXT("amb_crew_bed"), FPlayParams());
	}
	else if (!bOn)
	{
		StopLoop(Key, 1.f);
	}
}

void UVerseAudioSubsystem::PlayUi(EVerseUiSound Sound)
{
	if (Sound == EVerseUiSound::LevelBell && !bLevelSoundEnabled)
	{
		return; // R-12: the bell is switched off, every other UI cue still plays
	}
	static const TCHAR* Names[] = {TEXT("ui_click"), TEXT("ui_hover"), TEXT("ui_confirm"), TEXT("ui_back"),
		TEXT("ui_panel_open"), TEXT("ui_panel_close"), TEXT("ui_level_bell")};
	PlayCue(Names[FMath::Clamp(int32(Sound), 0, int32(UE_ARRAY_COUNT(Names)) - 1)], FPlayParams());
}

void UVerseAudioSubsystem::PlayLift(EVerseLiftSound Sound)
{
	const int64 Key = LoopKey(ELoopKind::Lift, 0);
	switch (Sound)
	{
	case EVerseLiftSound::DoorOpen: PlayCue(TEXT("lift_door_open"), FPlayParams()); break;
	case EVerseLiftSound::DoorClose: PlayCue(TEXT("lift_door_close"), FPlayParams()); break;
	case EVerseLiftSound::RideStart: StartLoop(Key, TEXT("lift_ride"), FPlayParams()); break;
	case EVerseLiftSound::RideStop: StopLoop(Key, 0.4f); break;
	}
}

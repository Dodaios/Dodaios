#pragma once

#include "Audio/VerseAudioMath.h"
#include "Audio/VerseAudioSink.h"
#include "Audio/VerseAudioTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseAudioSubsystem.generated.h"

class IVersePenetrationQuery;
class IVersePieceQuery;
class USoundAttenuation;
class UVerseAudioCueSet;
class UVerseEventHub;

/**
 * The Verse's sound (WP19). Listens to the event hub (fire, hit, penetration, reload, gadget,
 * fracture, finisher) and plays layered, located cues; other packages call the Play* functions for
 * sounds that have no hub event (footsteps, foley, drones, decks, UI).
 *
 * Fairness F6: a sound of anyone but the listener is attenuated to exactly the DA_Audibility range
 * of its Noise.* tag, the range the bot hears it at; sounds the bot cannot hear (crouch steps,
 * lean, equip) play only for their own player.
 */
UCLASS()
class VERSEUI_API UVerseAudioSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseAudioSubsystem* Get(const UObject* WorldContextObject);

	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickableWhenPaused() const override { return true; }

	// --- setup (integration and tests)

	/** Cue set to use; nullptr loads DA_AudioCues. */
	void SetCueSet(UVerseAudioCueSet* InCueSet);
	UVerseAudioCueSet* GetCueSet() const { return CueSet; }
	/** Replace the output (tests); nullptr restores the engine sink. */
	void SetSink(TSharedPtr<IVerseAudioSink> InSink);
	/** Occlusion source (VerseDestruction); nullptr = open paths. Not owned. */
	void SetPenetrationQuery(const IVersePenetrationQuery* Query) { PenetrationQuery = Query; }
	/** Piece truth for fracture sounds (material, location); nullptr = the null stub. Not owned. */
	void SetPieceQuery(const IVersePieceQuery* Query) { PieceQuery = Query; }
	/** The listener's player state id; INDEX_NONE resolves it from the first local player controller. */
	void SetLocalPlayerId(int32 PlayerId) { LocalPlayerIdOverride = PlayerId; }
	int32 GetLocalPlayerId() const;
	void SetListenerOverride(TOptional<FVector> Location) { ListenerOverride = Location; }
	FVector GetListenerLocation() const;

	// --- lifecycle and settings

	/** Hidden, minimised or focus back to the app (architecture 1.2): mute now; unmute fades in. */
	void SetDormant(bool bDormant);
	bool IsDormant() const { return bDormant; }
	/** settings.changed {ui_sound}: off silences the whole Verse (parity Z-14). */
	void SetUiSoundEnabled(bool bEnabled);
	/** User volume 0..1 (parity Z-14). */
	void SetUserVolume(float Volume);
	/** Linear master volume handed to the sink right now. */
	float GetMasterVolume() const { return MasterVolume; }

	// --- sounds without a hub event

	void PlayFootstep(int32 PlayerId, EVerseFootSurface Surface, EVerseGait Gait, const FVector& Location);
	void PlayFoley(int32 PlayerId, EVerseFoley Foley, const FVector& Location);
	void PlayEquip(int32 PlayerId, FName WeaponId);
	void PlayKnifeSwing(int32 PlayerId, const FVector& Location);
	/** A bolt hit world geometry that is no piece and no body. */
	void PlayImpact(int32 ShooterId, EVersePenetrationMaterial Material, const FVector& Location);
	void StartDroneLoop(int32 DroneKey, bool bWelding, const FVector& Location);
	void UpdateDroneLoop(int32 DroneKey, const FVector& Location);
	void StopDroneLoop(int32 DroneKey);
	void SetAmbience(EVerseAmbience Ambience);
	void SetCrewBed(bool bOn);
	void PlayUi(EVerseUiSound Sound);
	void PlayLift(EVerseLiftSound Sound);

	// --- introspection (audio event log of the parity AT checks)

	const TArray<FVerseAudioLogEntry>& GetEventLog() const { return EventLog; }
	void ClearEventLog() { EventLog.Reset(); }
	int32 GetActiveVoices() const { return Budget.Num(); }
	int32 GetPeakVoices() const { return PeakVoices; }
	void ResetPeakVoices() { PeakVoices = Budget.Num(); }
	double GetTime() const { return Now; }
	int32 GetLoopCount() const { return Loops.Num(); }

	/** Attenuation range in m for a source with this tag and loudness (DA_Audibility, F6). */
	float RangeForNoise(FName NoiseTag, float Loudness) const;
	/** The attenuation a remote source with this tag gets. */
	void MakeNoiseAttenuation(FName NoiseTag, float Loudness, FSoundAttenuationSettings& Out) const;

private:
	struct FPlayParams
	{
		FVector Location = FVector::ZeroVector;
		int32 SourceId = INDEX_NONE;
		float Gain = 1.f;
		float Loudness = 1.f;
		/** Range instead of the cue's noise range (own bolt impacts). */
		float RangeOverrideM = 0.f;
	};

	struct FLoop
	{
		int32 Handle = 0;
		FName CueId;
		FPlayParams Params;
		double NextOcclusionAt = 0.0;
		float BaseVolume = 1.f;
	};

	struct FPending
	{
		double At = 0.0;
		FName CueId;
		FPlayParams Params;
	};

	void HandleFire(const FVerseFireEvent& Event);
	void HandleHit(const FVerseHitEvent& Event);
	void HandlePenetration(const FVersePenetrationEvent& Event);
	void HandleReload(const FVerseReloadEvent& Event);
	void HandleGadget(const FVerseGadgetEvent& Event);
	void HandleFracture(const FVerseFractureEvent& Event);
	void HandleFinisher(const FVerseFinisherEvent& Event);

	/** Plays a cue; returns the voice handle or 0 when nothing played. */
	int32 PlayCue(FName CueId, const FPlayParams& Params, float* OutBaseVolume = nullptr);
	void StartLoop(int64 Key, FName CueId, const FPlayParams& Params);
	void StopLoop(int64 Key, float FadeOutS = 0.25f);
	void StopVoice(int32 Handle, float FadeOutS);
	void Log(FName CueId, int32 Variant, const FPlayParams& Params, bool bSpatial, float RangeM, float Volume, float Pitch,
		const FVerseOcclusion& Occlusion, bool bAdmitted, bool bStole, bool bStop = false);
	bool IsLocal(int32 PlayerId) const;
	USoundAttenuation* AttenuationFor(float RangeM);
	void ApplyMasterVolume();
	void RouteCueSet();
	FName WeaponCue(FName WeaponId, const TCHAR* Prefix, const TCHAR* Suffix) const;
	const IVersePieceQuery& Pieces() const;

	UPROPERTY(Transient)
	TObjectPtr<UVerseAudioCueSet> CueSet;

	UPROPERTY(Transient)
	TMap<int32, TObjectPtr<USoundAttenuation>> AttenuationCache;

	TWeakObjectPtr<UVerseEventHub> Hub;
	TSharedPtr<IVerseAudioSink> Sink;
	const IVersePenetrationQuery* PenetrationQuery = nullptr;
	const IVersePieceQuery* PieceQuery = nullptr;
	int32 LocalPlayerIdOverride = INDEX_NONE;
	TOptional<FVector> ListenerOverride;

	FVerseVoiceBudget Budget;
	FVerseVariantPicker Picker;
	TArray<FVerseAudioLogEntry> EventLog;
	TMap<int64, FLoop> Loops;
	TArray<FPending> Pending;
	/** Reload voice per player, stopped when the reload is cancelled. */
	TMap<int32, int32> ReloadVoices;

	double Now = 0.0;
	int32 NextHandle = 1;
	int32 PeakVoices = 0;
	bool bDormant = false;
	bool bUiSoundEnabled = true;
	float UserVolume = 1.f;
	/** Fade multiplier 0..1 towards the dormant target. */
	float FadeLevel = 1.f;
	float MasterVolume = 1.f;
	EVerseAmbience CurrentAmbience = EVerseAmbience::None;

	static constexpr int32 MaxLogEntries = 8192;
};

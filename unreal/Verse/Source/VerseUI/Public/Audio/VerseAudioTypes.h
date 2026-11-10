#pragma once

#include "CoreMinimal.h"

#include "VerseAudioTypes.generated.h"

class USoundBase;

// Audio types of WP19. One cue is one kind of sound (a weapon layer, an impact on one material,
// a footstep on one surface) with its recorded or synthesised variants. Cues are data:
// unreal/Verse/Data/audio/cues.json is the source, DA_AudioCues the imported asset.

/** Mix bus of a cue; its gain is mix.json bus_gain_db. Order is the index of FVerseAudioMixSettings::BusGainDb. */
UENUM(BlueprintType)
enum class EVerseAudioBus : uint8
{
	Weapons,
	Impacts,
	Foley,
	Destruction,
	Gadgets,
	Ambience,
	UI
};

inline constexpr int32 VerseAudioBusCount = 7;

/** Surface a foot lands on (footstep cue fs_<surface>). */
UENUM(BlueprintType)
enum class EVerseFootSurface : uint8
{
	Metal,
	Grating,
	Concrete,
	Rubble
};

/**
 * Gait of a footstep. Walk, run and sprint raise Noise.Footstep.*; crouch walk and prone crawl raise
 * no noise (bot.md 3.2), so another player's crouched steps are silent to the person too (F6).
 */
UENUM(BlueprintType)
enum class EVerseGait : uint8
{
	CrouchWalk,
	ProneCrawl,
	Walk,
	Run,
	Sprint
};

/** Movement foley that is not a footstep. Slide, land and mantle raise Noise.Move.*; the rest is own-only. */
UENUM(BlueprintType)
enum class EVerseFoley : uint8
{
	Slide,
	Land,
	Mantle,
	LeanIn,
	LeanOut,
	ProneDown,
	ProneUp
};

UENUM(BlueprintType)
enum class EVerseUiSound : uint8
{
	Click,
	Hover,
	Confirm,
	Back,
	PanelOpen,
	PanelClose,
	LevelBell
};

/** The deck bed that loops while the person is on that deck (parity Z-14). */
UENUM(BlueprintType)
enum class EVerseAmbience : uint8
{
	None,
	Bridge,
	Ops,
	Engineering,
	Hangar
};

UENUM(BlueprintType)
enum class EVerseLiftSound : uint8
{
	DoorOpen,
	DoorClose,
	RideStart,
	RideStop
};

/** One cue of DA_AudioCues. */
USTRUCT(BlueprintType)
struct VERSEUI_API FVerseAudioCue
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FName CueId;

	/** Variants; the picker never plays the same one twice in a row (parity Z-15). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	TArray<TObjectPtr<USoundBase>> Variants;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	EVerseAudioBus Bus = EVerseAudioBus::Weapons;

	/** Placed in the world (attenuated, panned, occluded). False: plays at the listener (own first-person layers, UI, beds). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	bool bSpatial = true;

	/**
	 * Noise.* tag of bot.md 3.2. A source other than the listener is attenuated to exactly the
	 * DA_Audibility range of this tag, so the person and the bot hear the same world (fairness F6).
	 */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FName NoiseTag;

	/** Range for a spatial cue with no noise tag, and for the listener's own bullet impacts (shooter feedback). 0 = none. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio", meta = (Units = "m"))
	float RangeM = 0.f;

	/** Random linear volume range per play. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FVector2D Volume = FVector2D(1.0, 1.0);

	/** Random pitch range per play. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FVector2D Pitch = FVector2D(1.0, 1.0);

	/** Voice stealing: a cue may take the voice of a lower-priority one when the budget is full. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	float Priority = 1.f;

	/** Concurrency of this cue; a new play over the limit replaces its oldest voice. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	int32 MaxVoices = 4;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	bool bLoop = false;

	/** "own" (synthesised by art/verse/audio) or "cc0:<keys>" citing art/verse/LICENSES.md rows (A19.6). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Audio")
	FString Licence;
};

/** mix.json, imported into DA_AudioCues. Defaults equal the committed file. */
USTRUCT(BlueprintType)
struct VERSEUI_API FVerseAudioMixSettings
{
	GENERATED_BODY()

	FVerseAudioMixSettings();

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mix")
	float MasterGainDb = -5.7f;

	/** Indexed by EVerseAudioBus. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mix")
	TArray<float> BusGainDb;

	/** Voice budget of the whole Verse (A19.3: at most 64 voices). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mix")
	int32 MaxVoices = 64;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Mix", meta = (Units = "s"))
	float DormantUnmuteFadeS = 0.15f;

	/** Distance law: (reference / d) ^ rolloff beyond the reference distance, floored. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Distance", meta = (Units = "m"))
	float ReferenceM = 1.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Distance")
	float Rolloff = 0.6f;

	/** The last (1 - this) of a finite range fades to silence, so the range end is exact. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Distance")
	float FadeStartFraction = 0.7f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Distance")
	float FloorDb = -48.f;

	/** Third-person shot: the near layer alone up to here, the far layer alone from FarFullM. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "m"))
	float ShotNearFullM = 8.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "m"))
	float ShotFarFullM = 35.f;

	/** A bullet passing the listener closer than this plays a flyby (crack and zip) at its closest point. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "m"))
	float FlybyRadiusM = 3.5f;

	/** Bullet speed for the flyby timing when the firing weapon has no definition (its ProjectileSpeed wins). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "m/s"))
	float BulletSpeedMps = 880.f;

	/** The spent casing (casing_<profile>) lands this long after the shot: a random time in [min, max]. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "s"))
	float CasingDelayMinS = 0.35f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "s"))
	float CasingDelayMaxS = 0.55f;

	/** The casing lands this far below the muzzle (the shooter's feet). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Weapons", meta = (Units = "m"))
	float CasingDropM = 1.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Destruction", meta = (Units = "s"))
	float SettleDelayMinS = 0.6f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Destruction", meta = (Units = "s"))
	float SettleDelayMaxS = 0.9f;

	/** Loops (drones, Bulwark hum) re-trace their occlusion at this interval. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Occlusion", meta = (Units = "s"))
	float OcclusionRefreshS = 0.25f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Occlusion")
	float OcclusionMaxLossDb = -36.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Occlusion")
	float OpenLowpassHz = 20000.f;

	/** Per penetration-table material (wire order): loss through one piece and the low-pass behind it. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Occlusion")
	TArray<float> OcclusionLossDb;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Occlusion")
	TArray<float> OcclusionLowpassHz;

	/** Look-ahead limiter on the Verse master submix (true peak at most -1 dBTP, A19.4). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Limiter")
	float LimiterThresholdDb = -2.5f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Limiter")
	float LimiterLookaheadMs = 3.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Limiter")
	float LimiterAttackMs = 1.f;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Limiter")
	float LimiterReleaseMs = 120.f;
};

/** One line of the audio event log the parity AT checks and the acceptance tests read. */
USTRUCT(BlueprintType)
struct VERSEUI_API FVerseAudioLogEntry
{
	GENERATED_BODY()

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	FName CueId;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	int32 Variant = 0;

	/** GFrameCounter when the play was issued (A19.2). */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	int64 Frame = 0;

	/** Subsystem clock, s. */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	double Time = 0.0;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	FVector Location = FVector::ZeroVector;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	bool bSpatial = false;

	/** Attenuation range used, m; 0 for a non-spatial play. */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	float RangeM = 0.f;

	/** Linear volume handed to the voice (cue x bus x layer x occlusion; master is applied on the submix). */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	float Volume = 1.f;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	float Pitch = 1.f;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	float OcclusionLossDb = 0.f;

	UPROPERTY(VisibleAnywhere, Category = "Audio")
	float LowpassHz = 20000.f;

	/** False when the voice budget refused the play. */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	bool bAdmitted = true;

	/** True when this play took another cue's voice. */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	bool bStole = false;

	/** Stop of a loop or a cancelled reload. */
	UPROPERTY(VisibleAnywhere, Category = "Audio")
	bool bStop = false;
};

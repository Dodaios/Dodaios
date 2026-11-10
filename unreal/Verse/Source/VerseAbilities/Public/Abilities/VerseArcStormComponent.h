#pragma once

#include "Abilities/VerseArcStorm.h"
#include "Components/SceneComponent.h"
#include "CoreMinimal.h"
#include "Math/RandomStream.h"

#include "VerseArcStormComponent.generated.h"

class UAudioComponent;
class UInstancedStaticMeshComponent;
class UMaterialInstanceDynamic;
class UPointLightComponent;
class USkeletalMeshComponent;
class UVerseArcSoundWave;

/** Where the bolts go: the view at eye level (first and third person) or the body's facing (overview). */
UENUM(BlueprintType)
enum class EVerseArcAim : uint8
{
	View,
	Facing,
};

/** One entry of the sound log the tests read (parity Z-07). */
struct FVerseArcSoundEvent
{
	enum class EKind : uint8
	{
		HumOn,
		Crackle,
		Stop,
	};
	EKind Kind = EKind::HumOn;
	float Value = 0.f;
	int32 Strike = 0;
};

/**
 * Arc Storm on the commander (parity Z-05..Z-08, Z-10, K-07). Hold it
 * (`SetHeld`, key F on a deck): the level rises over 0.18 s (the body's arms
 * follow `GetLevel`), then bolts leave both hands toward the aim, re-strike
 * about 22 times a second, a light at the hands flickers with them, sparks
 * fly where they land and a hum with a crackle plays. Let go and it fades.
 *
 * Bolts are drawn as two layers of thin cylinders (a cool white core and an
 * amber glow, additive, `M_Sov_ArcBolt`). Off in the arena (the hub's arena
 * switch) and released when the app loses focus.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSEABILITIES_API UVerseArcStormComponent : public USceneComponent
{
	GENERATED_BODY()

public:
	UVerseArcStormComponent();

	/** Material of both bolt layers; parameters `Color` (vector) and `Intensity` (scalar). */
	static const TCHAR* BoltMaterialPath;

	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetHeld(bool bInHeld);

	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	bool IsHeld() const { return bHeld; }

	/** 0..1: how far the power is up (the arms rise with it). */
	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	float GetLevel() const { return Level; }

	/** Bolts are out this frame. */
	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	bool IsStriking() const { return bStriking; }

	/** The body whose hands cast (sockets `Middle_03_L/R`, else `Hand_L/R`). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetBody(USkeletalMeshComponent* InBody);

	/** World points the bolts leave from instead of the body's hands (first person: the view's bottom corners). Empty clears. */
	void SetHandsOverride(TArray<FVector> WorldHands) { HandsOverride = MoveTemp(WorldHands); }

	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetAimMode(EVerseArcAim InMode) { AimMode = InMode; }

	/** Arena on: the power is off and the key does nothing (parity Z-10). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Abilities")
	void SetArenaOn(bool bOn);

	UFUNCTION(BlueprintPure, Category = "Verse|Abilities")
	bool IsAllowed() const { return !bArenaOn; }

	/** The app lost focus: held keys are cleared, so the storm stops (parity K-07). */
	void ReleaseOnFocusLoss();

	/** Where the bolts leave from this frame, world. */
	TArray<FVector> GetHands() const;

	/** Unit direction the bolts go this frame. */
	FVector GetAim() const;

	/** One frame of the power (the tick calls it; tests call it with a fixed step). */
	void Step(float DeltaTime);

	const VerseArc::FStrike& GetLastStrike() const { return LastStrike; }
	int32 GetStrikeCount() const { return StrikeCount; }
	const TArray<FVerseArcSoundEvent>& GetSoundLog() const { return SoundLog; }
	float GetHandLightIntensity() const;
	int32 GetDrawnSegments() const;

	/** Linear output level 0..1 the sound plays at (the Verse volume setting). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Abilities")
	float Volume = 0.45f;

	/** Seed of the first strike; each strike uses the next. */
	UPROPERTY(EditAnywhere, Category = "Verse|Abilities")
	int32 Seed = 1;

protected:
	virtual void OnRegister() override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	void Strike();
	void Draw(const VerseArc::FStrike& InStrike);
	void Hide();
	void UpdateSound(float Crackle);
	void Log(FVerseArcSoundEvent::EKind Kind, float Value);
	float FloorBelow(const FVector& From) const;
	void OnArenaSwitch(const struct FVerseArenaSwitchEvent& Event);
	void OnAppDeactivate();

	bool bHeld = false;
	bool bArenaOn = false;
	bool bStriking = false;
	bool bSounding = false;
	float Level = 0.f;
	float UntilStrike = 0.f;
	int32 StrikeCount = 0;
	EVerseArcAim AimMode = EVerseArcAim::View;
	TArray<FVector> HandsOverride;
	VerseArc::FStrike LastStrike;
	TArray<FVerseArcSoundEvent> SoundLog;
	FRandomStream Flicker;
	FDelegateHandle ArenaHandle;
	FDelegateHandle FocusHandle;

	UPROPERTY(Transient)
	TWeakObjectPtr<USkeletalMeshComponent> Body;

	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> CoreLayer;

	UPROPERTY(Transient)
	TObjectPtr<UInstancedStaticMeshComponent> GlowLayer;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> CoreMaterial;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> GlowMaterial;

	UPROPERTY(Transient)
	TObjectPtr<UPointLightComponent> HandLight;

	UPROPERTY(Transient)
	TObjectPtr<UPointLightComponent> ImpactLight;

	UPROPERTY(Transient)
	TObjectPtr<UAudioComponent> Sound;

	UPROPERTY(Transient)
	TObjectPtr<UVerseArcSoundWave> Wave;
};

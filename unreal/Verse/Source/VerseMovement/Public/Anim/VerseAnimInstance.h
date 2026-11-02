#pragma once

#include "Anim/VerseAnimRuntime.h"
#include "Anim/VerseAnimTypes.h"
#include "Animation/AnimInstance.h"
#include "Animation/AnimInstanceProxy.h"
#include "CoreMinimal.h"

#include "VerseAnimInstance.generated.h"

class UAnimSequence;
class USceneComponent;

/** Worker-thread side of `UVerseAnimInstance`: evaluates the frame natively, no anim graph. */
struct VERSEMOVEMENT_API FVerseAnimInstanceProxy : public FAnimInstanceProxy
{
	FVerseAnimInstanceProxy() = default;
	explicit FVerseAnimInstanceProxy(UAnimInstance* Instance) : FAnimInstanceProxy(Instance) {}

	virtual void Initialize(UAnimInstance* InAnimInstance) override;
	virtual void PreUpdate(UAnimInstance* InAnimInstance, float DeltaSeconds) override;
	virtual void Update(float DeltaSeconds) override;
	virtual void CacheBones() override;
	virtual bool Evaluate(FPoseContext& Output) override;

	/** Montages play in this full-body slot over everything (finisher root motion, WP04). */
	static const FName FullBodySlot;

	FVerseAnimFrame Frame;
	float IdleTime = 0.f;
	FVerseAnimBones Bones;
	FVerseAnimEvalInfo LastInfo;
	float SlotWeight = 0.f;
	float SourceWeight = 1.f;
	float TotalWeight = 0.f;
	bool bBonesValid = false;
};

/**
 * The animation runtime of every `SKEL_Verse_Human` character (WP13.10):
 * the locomotion state machine from `IVerseMovementQuery` (stance, sprint,
 * airborne, mantle, lean), the weapon layer, lean over three spine bones,
 * aim pitch, off-hand IK to the weapon's `SOCKET_Support` and foot IK.
 * Evaluated natively (`FVerseAnimInstanceProxy`), so no animation
 * blueprint asset is needed; montages in the `FullBody` slot still play.
 */
UCLASS(Transient, Blueprintable, BlueprintType)
class VERSEMOVEMENT_API UVerseAnimInstance : public UAnimInstance
{
	GENERATED_BODY()

public:
	/** Drive the instance from `Inputs` instead of the owning pawn (crew, kill cam, tests). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void SetExternalInputs(const FVerseAnimInputs& Inputs);

	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void ClearExternalInputs();

	/** Weapon state from combat (WP02): the class held and the ADS blend. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void SetWeaponState(EVerseAnimWeapon Weapon, float Ads);

	/** Start an upper-body action (fire, reload, equip, holster, knife strike). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void PlayAction(EVerseAnimAction Action);

	/** The weapon whose `SOCKET_Support` the off hand holds; null uses the reference grip. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void SetWeaponComponent(USceneComponent* Weapon);

	UFUNCTION(BlueprintCallable, Category = "Verse|Anim")
	void SetFootIKEnabled(bool bEnabled) { bFootIK = bEnabled; }

	const FVerseAnimInputs& GetInputs() const { return Inputs; }
	const FVerseAnimFrame& GetFrame() const { return Frame; }
	const FVerseAnimClipSet& GetClips() const { return Clips; }
	EVerseLocoState GetLocoState() const { return Machine.GetState(); }
	float GetIdleTime() const { return Machine.GetIdleTime(); }

	/** Support socket in the weapon's root frame (cm): the attached weapon's, else the reference. */
	FTransform GetSupportInWeapon() const;

protected:
	virtual void NativeInitializeAnimation() override;
	virtual void NativeUpdateAnimation(float DeltaSeconds) override;
	virtual FAnimInstanceProxy* CreateAnimInstanceProxy() override;
	virtual void DestroyAnimInstanceProxy(FAnimInstanceProxy* InProxy) override;

private:
	void GatherInputs(float DeltaSeconds);
	void TraceFeet();

	FVerseAnimInputs Inputs;
	FVerseAnimFrame Frame;
	FVerseAnimClipSet Clips;
	FVerseAnimStateMachine Machine;
	bool bExternal = false;
	bool bFootIK = true;
	bool bClipsLoaded = false;
	EVerseAnimWeapon Weapon = EVerseAnimWeapon::Rifle;
	float Ads = 0.f;
	EVerseAnimAction Action = EVerseAnimAction::None;
	float ActionStart = 0.f;

	UPROPERTY(Transient)
	TArray<TObjectPtr<UAnimSequence>> Loaded;

	UPROPERTY(Transient)
	TWeakObjectPtr<USceneComponent> WeaponComponent;

	friend struct FVerseAnimInstanceProxy;
};

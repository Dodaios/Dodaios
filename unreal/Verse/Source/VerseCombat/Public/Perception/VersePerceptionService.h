#pragma once

#include "Bot/VersePerceptTypes.h"
#include "CoreMinimal.h"
#include "Perception/VersePerceptionModel.h"
#include "Subsystems/WorldSubsystem.h"
#include "UObject/ScriptInterface.h"

#include "VersePerceptionService.generated.h"

class AController;
class APawn;
class IVersePenetrationQuery;
class UVerseAudibilityTable;
class UVerseEventHub;

DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVersePerceptFrame, AController* /*Observer*/, const FVersePerceptFrame& /*Frame*/);

/**
 * The fairness boundary (contracts/bot.md 2, frozen interface): a server world subsystem that
 * turns world truth into one FVersePerceptFrame per registered observer per tick, with all
 * perception error applied before a percept leaves it. Bots and harness person models read only
 * these frames. The rules live in FVersePerceptionModel; this class gathers truth from pawns and
 * hub events and runs the model once per server tick.
 */
UCLASS()
class VERSECOMBAT_API UVersePerceptionService : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	/** The service of the object's world, or nullptr. */
	static UVersePerceptionService* Get(const UObject* WorldContextObject);

	/** Start producing frames for Observer (its pawn's eye, its player state id). */
	void RegisterObserver(AController* Observer, const FVersePerceptionProfile& Profile);
	void UnregisterObserver(AController* Observer);
	bool IsRegistered(const AController* Observer) const;

	/** One frame per registered observer per tick. Server only. */
	FOnVersePerceptFrame OnPerceptFrame;

	/** Sight query (WP03 penetration query when it lands). Default: a plain trace on VerseSight. */
	void SetSightQuery(TScriptInterface<IVersePenetrationQuery> Query);

	/** DA_Audibility; default: a transient table with the contract rows. */
	void SetAudibilityTable(const UVerseAudibilityTable* Table);

	/** Arena data hooks: dark zones and height levels (bot.md 3.1, 3.2). */
	void SetVisibilityFactorProvider(TFunction<float(const FVector&)> Provider);
	void SetLevelBands(float MidMinZCm, float UpperMinZCm);

	/**
	 * Fills the HUD part of a self percept the service cannot read itself yet (health, armour,
	 * magazine, reserve, gadgets: WP02). Called after the service filled position, view, stance
	 * and combat phase.
	 */
	void SetSelfPerceptFiller(TFunction<void(const APawn&, FVerseSelfPercept&)> Filler);

	/**
	 * Fills what a look at a pawn shows that the service cannot read itself yet: ADS and its field
	 * of view (WP01), the held weapon and the reload animation (WP02). Called after MakeBody. Firing,
	 * the last fired weapon and reloads already come from the hub's OnFire and OnReload events.
	 */
	void SetBodyFiller(TFunction<void(const APawn&, FVersePerceptionBody&)> Filler);

	/** Run one perception tick now (tests and the headless harness step the world themselves). */
	void StepPerception(float DeltaS);

	const FVersePerceptionModel& GetModel() const { return Model; }

	// UTickableWorldSubsystem
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual bool DoesSupportWorldType(const EWorldType::Type WorldType) const override;
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;

	/** Truth snapshot of a pawn (eye from the Camera bone, sample points from the hit-zone bones). */
	static FVersePerceptionBody MakeBody(const APawn& Pawn, int32 PlayerId);

	/** The bone names the sample points read, in EVerseSightSample order (art-pipeline.md 12.1). */
	static const FName SampleBones[8];
	static const FName EyeBone;

private:
	struct FRegistered
	{
		TWeakObjectPtr<AController> Controller;
		int32 PlayerId = INDEX_NONE;
	};

	void BindHub();
	void UnbindHub();
	void HandleNoise(const FVerseNoiseEvent& Event);
	void HandleFire(const FVerseFireEvent& Event);
	void HandleReload(const FVerseReloadEvent& Event);
	void HandleHit(const FVerseHitEvent& Event);
	void HandleDeath(const FVerseDeathEvent& Event);
	void HandleArenaSwitch(const FVerseArenaSwitchEvent& Event);

	void GatherBodies(TArray<FVersePerceptionBody>& OutBodies) const;
	FVersePerceptionWorld MakeWorld() const;
	static int32 PlayerIdOf(const AController& Controller);
	bool IsServer() const;

	FVersePerceptionModel Model;
	TArray<FRegistered> Registered;

	UPROPERTY(Transient)
	TObjectPtr<UObject> SightQueryObject;
	IVersePenetrationQuery* SightQuery = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<const UVerseAudibilityTable> Audibility;

	TFunction<float(const FVector&)> VisibilityProvider;
	TFunction<void(const APawn&, FVerseSelfPercept&)> SelfFiller;
	TFunction<void(const APawn&, FVersePerceptionBody&)> BodyFiller;
	float MidMinZCm = 350.f;
	float UpperMinZCm = 750.f;

	TWeakObjectPtr<UVerseEventHub> Hub;
	FDelegateHandle NoiseHandle;
	FDelegateHandle FireHandle;
	FDelegateHandle ReloadHandle;
	FDelegateHandle HitHandle;
	FDelegateHandle DeathHandle;
	FDelegateHandle ArenaHandle;

	float LastStepDeltaS = 0.f;
};

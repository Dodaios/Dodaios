#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Weapons/VerseFirePrediction.h"
#include "Weapons/VerseRecoil.h"
#include "Weapons/VerseSpread.h"

#include "VerseWeaponComponent.generated.h"

class UVerseInventoryComponent;
class UVerseWeaponDefinition;
struct FVerseBoltResult;

/** Owner-side: a predicted shot left the muzzle (presentation draws the amber bolt). */
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVersePredictedFire, const FVerseFireEvent&);
/** Owner-side: the server answered a shot (Rejected removes the predicted bolt). */
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseShotAnswered, uint16 /*ShotCounter*/, EVerseShotResult /*Result*/);

/** Any shooter's predicted shot was rejected or timed out (presentation removes the bolt). */
DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseAnyShotRejected, int32 /*ShooterId*/, uint16 /*ShotCounter*/);

/** What the owner's fire step reads besides the definition (movement comes through IVerseMovementQuery). */
struct FVerseFireContext
{
	/** Predicted server time at the end of this tick. */
	float Now = 0.f;
	float Dt = 1.f / 60.f;
	bool bTriggerDown = false;
	EVerseStance Stance = EVerseStance::Stand;
	float HorizontalSpeedMps = 0.f;
	bool bAirborne = false;
	/** Sprinting or mantling (IVerseMovementQuery::BlocksFiring). */
	bool bFiringBlocked = false;
	/** Eye point, cm. */
	FVector Eye = FVector::ZeroVector;
	/** Control rotation at the start of the tick (recoil is added on top). */
	FRotator Control = FRotator::ZeroRotator;
};

/** One shot the fire step produced. */
struct FVerseShotOut
{
	uint16 Counter = 0;
	uint32 Seed = 0;
	int32 ShotIndex = 0;
	float Time = 0.f;
	float Sigma = 0.f;
	FVector Origin = FVector::ZeroVector;
	FVector Dir = FVector::ForwardVector;
	FVector2f Kick = FVector2f::ZeroVector;
};

/**
 * Firearms on a pawn (WP02.4-2.6, combat-state.md 4, 5, 11.2): ADS blend, recoil, spread, fire
 * cadence, owner prediction and the server fire path. Recoil and spread are simulated on the owning
 * client and the server from the same seed. ServerFire validates (30 cm origin, sigma + 1.5 deg),
 * spends the round, spawns the bolt with the shooter's latency and raises the fire and shot noise
 * events; the bolt's end comes back as ClientConfirmShot.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseWeaponComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseWeaponComponent();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;
	virtual void BeginPlay() override;

	static UVerseWeaponComponent* FindOn(const AActor* Actor);

	/** 0..255 = 0..1, replicated to all; drives spread, recoil multiplier and speed. */
	UPROPERTY(Replicated)
	uint8 AdsBlend = 0;

	/** Match seed for the per-shot seed hash. The server draws one per spawn (BeginPlay) unless the game mode set it; it replicates. */
	UPROPERTY(Replicated)
	uint32 MatchSeed = 0;

	/** Server: sets the match seed (game mode, per match). */
	void SetMatchSeed(uint32 Seed);

	/** How far a fire request's client time may lead the server clock, s. */
	static constexpr float MaxClientLeadS = 0.05f;
	/** How far it may lag behind; older requests are rejected (the latency advance is capped at 250 ms regardless). */
	static constexpr float MaxClientLagS = 0.5f;
	/** Shots the server-clock cadence lets through back to back (unreliable RPCs arrive bunched). */
	static constexpr float ServerBurstShots = 3.f;

	UFUNCTION(Server, Unreliable)
	void ServerFire(uint16 ShotCounter, uint32 Seed, FVector_NetQuantize10 Origin, FVector_NetQuantizeNormal Dir, float ClientServerTime);

	UFUNCTION(Client, Reliable)
	void ClientConfirmShot(uint16 ShotCounter, EVerseShotResult Result, EVerseHitZone Zone, bool bKillingBlow);

	UFUNCTION(NetMulticast, Unreliable)
	void MulticastFire(const FVerseFireEvent& E);

	UFUNCTION(NetMulticast, Unreliable)
	void MulticastHitCosmetic(const FVerseHitEvent& E);

	/** Unreliable multicast of FVersePenetrationEvent (combat-state.md 5.1). */
	UFUNCTION(NetMulticast, Unreliable)
	void MulticastPenetration(const FVersePenetrationEvent& E);

	/**
	 * One fire step of the owner (person, bot or harness model): cadence, recoil, spread, ammo
	 * prediction. Shots are sent with ServerFire (or handled in place on the server). Returns the
	 * rotation to add to the control rotation this tick (kick minus recovery).
	 */
	FRotator StepFire(const FVerseFireContext& Ctx, TArray<FVerseShotOut>* OutShots = nullptr);

	/** Look input passes through the recoil compensation rule (4.2). */
	void ApplyLookInput(FVector2f& InOutLookDeltaDeg) { Recoil.OnLookInput(InOutLookDeltaDeg); }

	/** Sets the ADS blend target (0..1) and moves AdsBlend toward it at 1 / AdsTime. */
	void StepAds(bool bAdsHeld, float Dt);
	float GetAdsBlend01() const { return float(AdsBlend) / 255.f; }

	/** Server side of a fire request; ServerFire forwards here, the listen-server owner and bots call it directly. */
	EVerseShotResult HandleServerFire(uint16 ShotCounter, uint32 Seed, const FVector& Origin, const FVector& Dir, float ClientServerTime);

	/** The projectile manager reports how a bolt of this shooter ended. */
	void HandleBoltResolved(const FVerseBoltResult& Result);

	/** Owner: the answer for a shot (ClientConfirmShot lands here). */
	void HandleConfirm(uint16 ShotCounter, EVerseShotResult Result);

	/** Raises a cosmetic impact (victim -1) on the local hub when this world has a viewer (not a dedicated server). */
	static void RaiseLocalImpact(const UObject* WorldContext, const FVerseHitEvent& Impact);

	/** Player id of the shooter as events carry it. */
	int32 GetShooterId() const;

	const FVerseRecoilState& GetRecoil() const { return Recoil; }
	const FVerseSpread& GetSpread() const { return Spread; }
	const FVerseFirePredictor& GetPredictor() const { return Predictor; }

	/** Server simulation of this shooter's recoil and spread from the requests it accepted (R5, 4.4). */
	const FVerseRecoilState& GetServerRecoil() const { return ServerRecoil; }
	const FVerseSpread& GetServerSpread() const { return ServerSpread; }
	/** Kick, sigma and shot index the server derived for the last request that passed the clock checks. */
	FVector2f GetLastServerKick() const { return LastServerKick; }
	float GetLastServerSigma() const { return LastServerSigma; }
	int32 GetLastServerShotIndex() const { return LastServerShotIndex; }

	/** Owner-side predicted state of the active weapon. */
	const FVerseWeaponSlotState& GetPredictedSlot() const { return PredictedSlot; }

	/** Re-reads the predicted slot from the replicated state (no shot pending). */
	void ResyncPredictedSlot();

	FOnVersePredictedFire OnPredictedFire;
	FOnVerseShotAnswered OnShotAnswered;
	static FOnVerseAnyShotRejected OnAnyShotRejected;

	/** Server-side validation of the eye point: the rewound eye at the shot's view time. Tests may override. */
	TFunction<FVector(double ViewTime)> RewoundEyeOverride;
	/** Server control-rotation forward. Tests may override. */
	TFunction<FVector()> ServerForwardOverride;

	/** Validation can be turned off for harness bots that fire without a controller (never in a match). */
	bool bServerValidates = true;

private:
	UVerseInventoryComponent* GetInventory() const;
	const UVerseWeaponDefinition* GetActiveDefinition() const;
	FVector ServerEye(double ViewTime) const;
	FVector ServerForward() const;

	FVerseRecoilState Recoil;
	FVerseSpread Spread;
	FVerseFireCadence Cadence;
	FVerseFirePredictor Predictor;
	FVerseWeaponSlotState PredictedSlot;
	FName PredictedWeaponId;
	uint16 NextShotCounter = 0;
	float LastStepTime = -1.f;

	/** Server cadence check on client times. */
	float ServerLastShotClientTime = -1000.f;
	/** Server-clock cadence: shots allowed now (refills at 1 / FireInterval per server second). */
	float ServerShotBudget = ServerBurstShots;
	float ServerBudgetTime = -1.f;
	/** Server simulation of the owner's recoil and spread. */
	FVerseRecoilState ServerRecoil;
	FVerseSpread ServerSpread;
	uint16 ServerLastCounter = 0;
	FVector2f LastServerKick = FVector2f::ZeroVector;
	float LastServerSigma = 0.f;
	int32 LastServerShotIndex = 0;
};

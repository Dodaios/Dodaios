#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Finisher/VerseFinisherTimeline.h"
#include "Melee/VerseMeleeImport.h"
#include "Melee/VerseMeleeRules.h"

#include "VerseMeleeComponent.generated.h"

class ACameraActor;
class APawn;
class IVerseMeleeWorld;
class UVerseMeleeDefinition;

DECLARE_MULTICAST_DELEGATE_TwoParams(FOnVerseFinisherView, APawn* /*Viewer*/, const FVerseFinisherViewState&);

/**
 * Knife strike and paired finisher on one pawn (combat-state.md 7, WP04). The server decides
 * every press (7.2) at the attacker's view time and runs the finisher timeline; every machine
 * plays the same timeline from FVerseFinisherEvent (reliable multicast) and the hub's OnFinisher.
 *
 * The finisher runs as a server-driven sequence in this component (validate, lock both,
 * phases, abort on attacker death, release). It is shaped so a GAS ability can own it once
 * VerseCombat links GameplayAbilities; the attacker's warp to Warp_Finisher is evaluated
 * here from the event on every machine (the motion warping component needs the MotionWarping
 * module edge, also pending).
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSECOMBAT_API UVerseMeleeComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseMeleeComponent();

	/** The melee press, stamped with the client's estimate of server time (its view time). */
	UFUNCTION(Server, Reliable)
	void ServerMelee(float ClientServerTime);

	/** Every phase of a finisher, stamped by the server (combat-state.md 7.4). */
	UFUNCTION(NetMulticast, Reliable)
	void MulticastFinisher(const FVerseFinisherEvent& E);

	/** The server's answer to the owner's press, for the predicted swing. */
	UFUNCTION(Client, Reliable)
	void ClientConfirmMelee(EVerseMeleeOutcome Outcome);

	/** 7.2 with the contract signature. Transforms are base transforms (capsule base, pawn yaw). */
	static EVerseMeleeOutcome Classify(const FTransform& Attacker, const FTransform& Victim,
		const UVerseMeleeDefinition& Def, bool bVictimEligible, bool bSweepClear);

	/** Local press (person input or bot input frame): predicts the swing and sends ServerMelee. */
	void PressMelee(bool bKnifeSlotActive);

	/**
	 * Server: resolves a press at ViewServerTime (clamped to the 250 ms rewind cap). Returns
	 * false when the press was refused (cooldown, attacker not Alive); OutOutcome says what
	 * an accepted press became.
	 */
	bool HandleMeleePress(double ViewServerTime, EVerseMeleeOutcome& OutOutcome);

	const UVerseMeleeDefinition& GetDefinition() const;
	const FVerseMeleePresentationTuning& GetTuning() const { return Tuning; }
	const FVerseFinisherSession& GetSession() const { return Session; }
	const FVerseKnifePresentation& GetKnife() const { return Knife; }
	EVerseKnifeAnim GetKnifeAnim() const;
	bool IsInFinisher() const { return Session.bActive || bPresenting; }
	const FVerseMeleeClock& GetClock() const { return Clock; }

	/** Gore level of this viewer (set from UVerseSettings by the primary module). */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Melee")
	EVerseGoreLevel GoreLevel = EVerseGoreLevel::Full;

	/** Optional asset; when unset the component imports Data/melee/hookbill.json. */
	UPROPERTY(EditAnywhere, Category = "Verse|Melee")
	TObjectPtr<UVerseMeleeDefinition> Definition;

	/** Raised on the machine of a local participant whenever its finisher view changes. */
	FOnVerseFinisherView OnFinisherView;

	/** Server time on this machine (game state clock; world time without a game state). */
	double ServerNow() const;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	IVerseMeleeWorld* MeleeWorld() const;
	APawn* OwnerPawn() const;
	void EnsureDefinition();
	void RaiseNoise(const FGameplayTag& Tag) const;
	void ApplyStrike(TWeakObjectPtr<APawn> Victim);
	void StartFinisher(APawn* Victim, double Now);
	void AdvanceFinisherServer(double Now);
	void SendPhase(EVerseFinisherPhase Phase);
	void OnHubDeath(const FVerseDeathEvent& E);
	void BeginPresentation(const FVerseFinisherEvent& E);
	void TickPresentation(double Now);
	void EndPresentation();
	void UpdateLocalViews(double Elapsed);
	void ApplyView(APawn* Viewer, const FVerseFinisherViewState& State, const FTransform& Camera);

	struct FPendingStrike
	{
		TWeakObjectPtr<APawn> Victim;
		double ApplyAt = 0.0;
	};
	TArray<FPendingStrike> PendingStrikes;

	FVerseMeleePresentationTuning Tuning;
	FVerseMeleeClock Clock;
	FVerseKnifePresentation Knife;

	// Server finisher state.
	FVerseFinisherSession Session;
	TWeakObjectPtr<APawn> SessionVictim;
	FTransform SessionWarpTarget;
	FTransform SessionWarpStart;
	double AttackerDeathTime = FVerseFinisherSession::NoDeath;
	FDelegateHandle DeathHandle;

	// Presentation state (every machine).
	bool bPresenting = false;
	bool bPresentAborted = false;
	double PresentStart = 0.0;
	double WarpStartElapsed = 0.0;
	double SnapStartTime = 0.0;
	FTransform WarpStartPose;
	FTransform WarpTarget;
	FTransform VictimFrom;
	FTransform VictimTo;
	TWeakObjectPtr<APawn> PresentVictim;
	TMap<TWeakObjectPtr<APawn>, FVerseFinisherViewState> LastViews;

	UPROPERTY(Transient)
	TObjectPtr<ACameraActor> FinisherCamera;
};

#pragma once

#include "Crew/VerseCrewPresentation.h"
#include "Crew/VerseCrewTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Pawn.h"

#include "VerseCrewPawn.generated.h"

class UCapsuleComponent;
class UPointLightComponent;
class USkeletalMesh;
class USkeletalMeshComponent;
class USpotLightComponent;
class UTextRenderComponent;

/**
 * One officer or technician on a deck. Moved by UVerseCrewSubsystem (no controller, no own
 * tick, so 40 of them cost one loop). The anim layer of WP13 reads Activity, Duty and the
 * look fields; until then the placeholder body only drops for sitting and lies down to sleep.
 */
UCLASS(NotBlueprintable)
class VERSECREW_API AVerseCrewPawn : public APawn
{
	GENERATED_BODY()

public:
	AVerseCrewPawn();

	/** agent_id or pane_id. */
	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	FString MemberId;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	EVerseCrewRole CrewRole = EVerseCrewRole::Officer;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	EVerseCrewDuty Duty = EVerseCrewDuty::Idle;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	EVerseCrewActivity Activity = EVerseCrewActivity::StandRest;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	EVerseCrewBeacon Beacon = EVerseCrewBeacon::None;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	FString RankId;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	FString Uniform;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	bool bSelected = false;

	/** The capsule the selection trace hits (Visibility channel only). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<UCapsuleComponent> Capsule;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<USkeletalMeshComponent> Body;

	/** Status beacon over the head (parity E-10). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<UPointLightComponent> BeaconLight;

	/** Status ring at the feet (parity E-11): a small downward pool of the status colour. */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<USpotLightComponent> Ring;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<UTextRenderComponent> Nameplate;

	void SetupMember(const FVerseCrewMember& Member, const FVerseCrewLook& Look, USkeletalMesh* Mesh, const FVerseCrewTuning& Tuning);
	void ApplyDuty(const FVerseCrewDutyLook& Look);
	void ApplyLook(const FVerseCrewLook& Look);
	void SetActivity(EVerseCrewActivity NewActivity, const FVerseCrewTuning& Tuning);
	void SetSelected(bool bInSelected);
	/** Pulses the beacon; Seconds is the subsystem clock. */
	void UpdateBeacon(double Seconds);

	const FVerseCrewDutyLook& GetDutyLook() const { return DutyLook; }

private:
	FVerseCrewDutyLook DutyLook;
};

/** The companion drone that follows the commander at heel (parity C-21, F-14). */
UCLASS(NotBlueprintable)
class VERSECREW_API AVerseCompanionDrone : public AActor
{
	GENERATED_BODY()

public:
	AVerseCompanionDrone();

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	FString PetId;

	UPROPERTY(VisibleInstanceOnly, Category = "Verse|Crew")
	FString Look;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Crew")
	TObjectPtr<UPointLightComponent> Glow;
};

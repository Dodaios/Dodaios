#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseBreachCharge.generated.h"

class IVersePieceDamage;
class UStaticMeshComponent;
class UVerseGadgetDefinition;

/** One pawn the detonation reached. */
struct FVerseBreachVictim
{
	TWeakObjectPtr<AActor> Pawn;
	float DistanceM = 0.f;
	float Damage = 0.f;
};

/**
 * The breach charge (combat-state.md 2.3): planted on a piece breakable by breach, detonates
 * FuseTime after the plant completes, damages every pawn whose pelvis is within PawnRadius and in
 * line of sight on VerseBolt (linear falloff, owner included), drives the target piece to its breach
 * result through IVersePieceDamage and removes Bulwarks within 3 m. No pawn collision; cannot be
 * shot or defused. Server spawns it; it replicates to all.
 */
UCLASS()
class VERSECOMBAT_API AVerseBreachCharge : public AActor
{
	GENERATED_BODY()

public:
	AVerseBreachCharge();

	virtual void GetLifetimeReplicatedProps(TArray<FLifetimeProperty>& OutLifetimeProps) const override;

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	/** Bulwarks within this distance of a detonation are removed, cm. */
	static constexpr double BulwarkClearRadiusCm = 300.0;

	/** Server: arms the charge. PlantCompleteTime is when the plant (UseTime) finished. */
	void InitCharge(const UVerseGadgetDefinition& Def, AActor* InOwnerPawn, uint16 InPieceIndex, const FVector& SurfaceNormal,
		double PlantCompleteTime);

	/** Server: detonates once the fuse is over. Tick calls it with the server time; tests call it directly. */
	void ServerAdvance(double Now);

	/** Server: the detonation itself (normally from ServerAdvance). */
	void Detonate(double Now);

	/** Piece damage target; unset uses the null stub. Destruction (WP06) or tests set it. */
	void SetPieceDamage(IVersePieceDamage* InPieceDamage) { PieceDamage = InPieceDamage; }

	double GetDetonateAt() const { return DetonateAt; }
	bool IsArmed() const { return bArmed; }
	bool HasDetonated() const { return bDetonated; }
	double GetDetonatedTime() const { return DetonatedTime; }
	uint16 GetPieceIndex() const { return PieceIndex; }
	const TArray<FVerseBreachVictim>& GetLastVictims() const { return LastVictims; }

	/** Pelvis point of a pawn: the Hips bone when it has a skeletal mesh, else the actor location. */
	static FVector PelvisOf(const AActor* Pawn);

	UFUNCTION(NetMulticast, Unreliable)
	void MulticastGadgetEvent(const FVerseGadgetEvent& Event);

	UPROPERTY(VisibleAnywhere, Category = "Verse|Gadget")
	TObjectPtr<UStaticMeshComponent> Look;

	/** Called on the server after the detonation (charge bookkeeping in the gadget component). */
	TFunction<void(AVerseBreachCharge*)> OnDetonated;

private:
	void Raise(EVerseGadgetEventKind Kind);

	/** Clients raise the spawn event (Plant) from replication: a multicast in the spawn frame has no open channel yet. */
	UFUNCTION()
	void OnRep_SpawnEvent();

	UPROPERTY(ReplicatedUsing = OnRep_SpawnEvent)
	FVerseGadgetEvent SpawnEvent;

	UPROPERTY()
	TObjectPtr<const UVerseGadgetDefinition> Definition;

	TWeakObjectPtr<AActor> OwnerPawn;
	IVersePieceDamage* PieceDamage = nullptr;
	FVector Normal = FVector::UpVector;
	int32 OwnerId = -1;
	uint16 PieceIndex = 0;
	double DetonateAt = 0.0;
	double DetonatedTime = -1.0;
	bool bArmed = false;
	bool bDetonated = false;
	TArray<FVerseBreachVictim> LastVictims;
};

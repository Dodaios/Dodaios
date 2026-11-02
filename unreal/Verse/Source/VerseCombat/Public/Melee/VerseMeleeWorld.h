#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Melee/VerseMeleeRules.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseMeleeWorld.generated.h"

class APawn;

/**
 * Everything melee and the finisher need from the rest of combat, as one seam:
 * rewound transforms (WP02.8), the participant flags (WP01 movement query, combat state) and
 * the damage path (WP02.9). Until those land the interim implementation below answers with
 * current transforms and a small health ledger; WP02 replaces it with SetWorld() and keeps
 * these semantics.
 */
class VERSECOMBAT_API IVerseMeleeWorld
{
public:
	virtual ~IVerseMeleeWorld() = default;

	/** Server time in seconds. */
	virtual double ServerNow() const = 0;

	/** Base transform (capsule base location, pawn yaw) at ServerTime, rewound (capped at 250 ms). */
	virtual FTransform GetBaseTransformAt(const APawn* Pawn, double ServerTime) const = 0;

	virtual FVerseMeleeParticipant Describe(const APawn* Pawn) const = 0;

	/** No world geometry between the two capsules (7.2, "clear capsule sweep"). */
	virtual bool IsSweepClear(const APawn* Attacker, const APawn* Victim) const = 0;

	/** Every pawn that could be a melee target of Attacker. */
	virtual void GetCandidates(const APawn* Attacker, TArray<APawn*>& Out) const = 0;

	/**
	 * Applies a melee or finisher hit on the server. In: ids, source, zone, damage asked for
	 * (a finisher asks for the victim's remaining health). Out: the damage applied and the
	 * killing-blow and spawn-protection flags. Raises FVerseHitEvent and, on a kill,
	 * FVerseDeathEvent on the hub, honouring VerseMelee::AllowsDamage.
	 */
	virtual void ApplyMeleeHit(APawn* Attacker, APawn* Victim, FVerseHitEvent& InOutHit) = 0;

	virtual float GetHealth(const APawn* Pawn) const = 0;
};

namespace VerseMelee
{
	/** Player state id, or the pawn's object id when it has no player state (tests, placeholders). */
	VERSECOMBAT_API int32 PlayerIdOf(const APawn* Pawn);

	/** The pawn whose PlayerIdOf is Id, or nullptr. */
	VERSECOMBAT_API APawn* FindPawnById(const UWorld* World, int32 Id);

	/** Sets the combat phase on the pawn's UVerseCombatStateComponent (server, push model). */
	VERSECOMBAT_API void SetPhase(APawn* Pawn, EVerseCombatPhase Phase);

	/**
	 * Ends spawn protection on the first own offensive action (combat-state.md 9.3): clears the
	 * flag and pulls SpawnProtectedUntil back to ServerNow, so protection derived from the end
	 * time cannot come back on the next tick.
	 */
	VERSECOMBAT_API void EndSpawnProtection(APawn* Pawn, double ServerNow);

	/** Capsule half height, 0 when the pawn has no capsule. */
	VERSECOMBAT_API double HalfHeightOf(const APawn* Pawn);
}

/**
 * Interim melee world (until WP02.8 rewind and WP02.9 damage land): current transforms,
 * movement flags from IVerseMovementQuery (null stub answers when absent), a world-static
 * capsule sweep, and a per-world health ledger that starts every pawn at 100.
 */
class VERSECOMBAT_API FVerseInterimMeleeWorld : public IVerseMeleeWorld
{
public:
	explicit FVerseInterimMeleeWorld(UWorld* InWorld) : World(InWorld) {}

	static constexpr float StartHealth = 100.f;

	virtual double ServerNow() const override;
	virtual FTransform GetBaseTransformAt(const APawn* Pawn, double ServerTime) const override;
	virtual FVerseMeleeParticipant Describe(const APawn* Pawn) const override;
	virtual bool IsSweepClear(const APawn* Attacker, const APawn* Victim) const override;
	virtual void GetCandidates(const APawn* Attacker, TArray<APawn*>& Out) const override;
	virtual void ApplyMeleeHit(APawn* Attacker, APawn* Victim, FVerseHitEvent& InOutHit) override;
	virtual float GetHealth(const APawn* Pawn) const override;

	/** Tests and respawn: put a pawn back at full health. */
	void ResetHealth(const APawn* Pawn) { Health.Remove(Pawn); }

private:
	TWeakObjectPtr<UWorld> World;
	TMap<TWeakObjectPtr<const APawn>, float> Health;
};

/** Holds the melee world of one game world: the interim one, or the one WP02 installs. */
UCLASS()
class VERSECOMBAT_API UVerseMeleeWorldSubsystem : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	static IVerseMeleeWorld* Get(const UObject* WorldContextObject);

	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;

	IVerseMeleeWorld& GetWorldPort() const { return Override.IsValid() ? *Override : *Interim; }

	/** Install another implementation (WP02, tests); nullptr restores the interim one. */
	void SetWorld(TSharedPtr<IVerseMeleeWorld> InWorld) { Override = MoveTemp(InWorld); }

	FVerseInterimMeleeWorld* GetInterim() const { return Interim.Get(); }

private:
	TSharedPtr<FVerseInterimMeleeWorld> Interim;
	TSharedPtr<IVerseMeleeWorld> Override;
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Rules/VerseRulesetConfig.h"
#include "UObject/Object.h"

#include "VerseRuleset.generated.h"

class AVerseGameMode;
class AVersePlayerState;
class AVerseSpawnPoint;
class UPrimaryDataAsset;
class UVerseCombatStateComponent;

/**
 * A boundary in a match at which a ruleset may want the destructible pieces reset
 * (destruction.md 11). Arena on, arena off and match end always reset fully and are not asked;
 * respawns never reset. VerseCombat asks UVerseRuleset::ShouldResetDestruction, VerseDestruction
 * executes the reset (WP06).
 */
UENUM()
enum class EVerseBoundary : uint8
{
	/** One round of a round-based mode. */
	Round,
	/** One set of an endless mode (deathmatch: first to KillsPerSet). */
	Set,
};

/**
 * Everything a ruleset needs from the world, as functions. AVerseGameMode fills it from the
 * real world (FillDefaultHost); tests fill it with a scripted world, so the rules run the same
 * code in both. Every function may be left empty; the ruleset then uses the documented fallback.
 */
struct VERSECOMBAT_API FVerseRulesHost
{
	/** Server time in seconds (the world's time, paused time excluded). */
	TFunction<float()> ServerTime;
	/** Wall clock for FVerseSetSummary::StartedAtUnix / EndedAtUnix. Fallback FDateTime::UtcNow. */
	TFunction<double()> UnixNow;
	/** The duel players. */
	TFunction<TArray<AVersePlayerState*>()> Players;
	/** The spawn points of the arena data layer. */
	TFunction<TArray<AVerseSpawnPoint*>()> SpawnPoints;
	/** Floor point under a spawn point, world cm. Fallback: the actor location. */
	TFunction<FVector(const AVerseSpawnPoint*)> SpawnFloor;
	/** Current eye point of a player's pawn; false when the player has no pawn. */
	TFunction<bool(const AVersePlayerState*, FVector&)> EyePoint;
	/** Is the segment clear on VerseBolt against the current piece proxies? Fallback: clear. */
	TFunction<bool(const FVector&, const FVector&)> LineClear;
	/** Floor point under a player's pawn (the navmesh agent location); false without a pawn. Fallback: eye minus 165 cm. */
	TFunction<bool(const AVersePlayerState*, FVector&)> FloorPoint;
	/** Navmesh path length in cm, floor point to floor point; negative when there is no path. Fallback: Euclidean. */
	TFunction<float(const FVector&, const FVector&)> PathLength;
	/** Is a pawn other than `Ignore`'s within the radius of `Floor`? */
	TFunction<bool(const FVector& Floor, float RadiusCm, const AVersePlayerState* Ignore)> PawnNear;
	/** Puts the player's new pawn on the spawn point. */
	TFunction<void(AVersePlayerState*, AVerseSpawnPoint*)> Respawn;
	/** The combat state component of the player's current pawn, or nullptr. */
	TFunction<UVerseCombatStateComponent*(const AVersePlayerState*)> CombatState;
};

/**
 * One game mode's rules (combat-state.md 10). AVerseGameMode is a thin forwarder that owns one
 * instance and asks it every rule question; a new mode is a subclass plus a config asset.
 */
UCLASS(Abstract)
class VERSECOMBAT_API UVerseRuleset : public UObject
{
	GENERATED_BODY()

public:
	virtual void Init(AVerseGameMode* InMode, const UVerseRulesetConfig* InConfig);
	virtual void OnMatchStart() PURE_VIRTUAL(UVerseRuleset::OnMatchStart, );
	virtual void GetLoadout(const AVersePlayerState* P, TMap<EVerseLoadoutSlot, const UPrimaryDataAsset*>& Out) const;
	virtual bool CanDamage(const FVerseDamageContext& Ctx) const { return true; }
	virtual float ModifyDamage(const FVerseDamageContext& Ctx, float Damage) const { return Damage; }
	virtual void OnPlayerAction(AVersePlayerState* P, EVersePlayerAction Action) {}
	virtual void OnKill(const FVerseDeathEvent& E) PURE_VIRTUAL(UVerseRuleset::OnKill, );
	virtual float GetRespawnDelay(const AVersePlayerState* P) const;
	virtual AVerseSpawnPoint* ChooseSpawn(const AVersePlayerState* P) PURE_VIRTUAL(UVerseRuleset::ChooseSpawn, return nullptr;);
	virtual float GetSpawnProtection(const AVersePlayerState* P) const;
	virtual bool IsSetOver(AVersePlayerState*& OutWinner) const { return false; }
	virtual void BuildSetSummary(FVerseSetSummary& Out) const {}
	/** Reset the destructible pieces at this boundary? (destruction.md 11) Endless modes: no. */
	virtual bool ShouldResetDestruction(EVerseBoundary Boundary) const { return false; }

	/** Replaces the world functions (tests, the harness). */
	void SetHost(const FVerseRulesHost& InHost) { Host = InHost; }
	const FVerseRulesHost& GetHost() const { return Host; }
	const UVerseRulesetConfig* GetConfig() const { return Config; }
	AVerseGameMode* GetMode() const { return Mode; }

protected:
	float Now() const;
	TArray<AVersePlayerState*> GetPlayers() const;
	AVersePlayerState* FindPlayer(int32 PlayerId) const;

	UPROPERTY(Transient)
	TObjectPtr<AVerseGameMode> Mode = nullptr;

	UPROPERTY(Transient)
	TObjectPtr<const UVerseRulesetConfig> Config = nullptr;

	FVerseRulesHost Host;
};

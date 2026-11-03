#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Rules/VersePlayerState.h"
#include "Rules/VerseRuleset.h"
#include "Rules/VerseSpawnSelection.h"
#include "Tickable.h"

#include "VerseRuleset_Deathmatch.generated.h"

/**
 * Endless 1v1 deathmatch (combat-state.md 9.1-9.4): kill +1, sets of first to KillsPerSet with
 * one FVerseSetSummary per finished set and one Unfinished summary when the arena closes
 * mid-set, respawn after RespawnDelay at the 9.2 spawn, spawn protection that ends at
 * SpawnProtectionMax or on the first own offensive action. Server only.
 *
 * It listens on the event hub itself for what only feeds statistics (fire, hit, gadget,
 * fracture) and for the arena closing; AVerseGameMode forwards the rule questions.
 */
UCLASS()
class VERSECOMBAT_API UVerseRuleset_Deathmatch : public UVerseRuleset, public FTickableGameObject
{
	GENERATED_BODY()

public:
	/** FVerseSetSummary::RulesetId of this mode. */
	static const FName RulesetId;

	virtual void Init(AVerseGameMode* InMode, const UVerseRulesetConfig* InConfig) override;
	virtual void OnMatchStart() override;
	virtual bool CanDamage(const FVerseDamageContext& Ctx) const override;
	virtual void OnPlayerAction(AVersePlayerState* P, EVersePlayerAction Action) override;
	virtual void OnKill(const FVerseDeathEvent& E) override;
	virtual AVerseSpawnPoint* ChooseSpawn(const AVersePlayerState* P) override;
	virtual bool IsSetOver(AVersePlayerState*& OutWinner) const override;
	virtual void BuildSetSummary(FVerseSetSummary& Out) const override;
	/** Endless deathmatch never resets the world between sets (destruction.md 11). */
	virtual bool ShouldResetDestruction(EVerseBoundary Boundary) const override { return false; }
	virtual void BeginDestroy() override;

	/** Runs respawns and protection timeouts up to `ServerTime`. Ticked every frame unless bAutoTick is off. */
	void Advance(float ServerTime);

	/** The arena closed or the Verse quits: the running set is sent as Unfinished, the match stops. */
	void EndMatch();

	bool IsMatchRunning() const { return bRunning; }
	bool IsSpawnProtected(const AVersePlayerState* P) const;
	/** CanDamage for a known victim (the pawn-free form tests and the harness use). */
	bool CanDamagePlayer(const AVersePlayerState* Victim, EVerseDamageSource Source) const;
	bool IsAlive(const AVersePlayerState* P) const;
	int32 GetSetIndex() const { return SetIndex; }
	const FString& GetSessionId() const { return SessionId; }
	/** The last spawn decision, for logs and the D2/D3 tests. */
	const FVerseSpawnChoice& GetLastSpawnChoice() const { return LastChoice; }

	/** Tests and the harness step time themselves. */
	bool bAutoTick = true;
	/** Seed of the spawn tie-break stream (VerseRng salt Spawn). */
	uint64 MatchSeed = 0x5EED11;

	// FTickableGameObject
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual bool IsTickable() const override;
	virtual UWorld* GetTickableGameObjectWorld() const override;

private:
	struct FPlayerRecord
	{
		bool bAlive = false;
		bool bProtected = false;
		float ProtectedUntil = 0.f;
		float RespawnAt = 0.f;
		int32 Streak = 0;
		FVerseSetLine Line;
	};

	FPlayerRecord& Record(const AVersePlayerState* P);
	const FPlayerRecord* FindRecord(const AVersePlayerState* P) const;
	void SpawnPlayer(AVersePlayerState* P);
	void EndProtection(AVersePlayerState* P);
	void WriteProtection(const AVersePlayerState* P, bool bOn, float Until) const;
	void FinishSet(AVersePlayerState* Winner);
	void StartSet();
	void BuildSummary(FVerseSetSummary& Out, const AVersePlayerState* Winner) const;
	bool IsSpawnBlocked(const FVector& Floor, const AVersePlayerState* Respawning) const;
	void Subscribe();
	void Unsubscribe();

	void HandleFire(const FVerseFireEvent& E);
	void HandleHit(const FVerseHitEvent& E);
	void HandleGadget(const FVerseGadgetEvent& E);
	void HandleFracture(const FVerseFractureEvent& E);
	void HandleArenaSwitch(const FVerseArenaSwitchEvent& E);

	TMap<TWeakObjectPtr<const AVersePlayerState>, FPlayerRecord> Records;
	/** Bulwarks and armed breach charges by owner and kind: they block spawns within 3 m (2.3). */
	TArray<FVerseGadgetEvent> ActiveGadgets;
	FVerseSpawnChoice LastChoice;
	bool bRunning = false;
	FString SessionId;
	int32 SetIndex = 0;
	float SetStartTime = 0.f;
	double SetStartUnix = 0.0;
	uint64 DeathCount = 0;
	TWeakObjectPtr<class UVerseEventHub> BoundHub;
	TArray<FDelegateHandle> Handles;
};

#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Net/Serialization/FastArraySerializer.h"

#include "VerseWeaponSlot.generated.h"

class UVerseWeaponDefinition;

/** combat-state.md 11.2 */
UENUM()
enum class EVerseReloadPhase : uint8
{
	None,
	Tactical,
	Empty
};

/**
 * Per-slot weapon state (combat-state.md 2.1, 11.2): definition, magazine, chambered round,
 * reserve, reload phase. Replicated to the owner only, inside UVerseInventoryComponent::Slots.
 * Magazine never counts the chambered round.
 */
USTRUCT()
struct VERSECOMBAT_API FVerseWeaponSlotState : public FFastArraySerializerItem
{
	GENERATED_BODY()

	UPROPERTY()
	EVerseLoadoutSlot Slot = EVerseLoadoutSlot::Primary;

	UPROPERTY()
	TObjectPtr<const UVerseWeaponDefinition> Definition;

	UPROPERTY()
	uint8 Magazine = 0;

	UPROPERTY()
	bool bChambered = false;

	UPROPERTY()
	uint16 Reserve = 0;

	UPROPERTY()
	EVerseReloadPhase Reload = EVerseReloadPhase::None;

	/** Server time. */
	UPROPERTY()
	float ReloadEndsAt = 0.f;

	/** Server time the reload started; local bookkeeping, not replicated. */
	UPROPERTY(NotReplicated)
	float ReloadStartedAt = 0.f;

	/** The rounds of the running reload have moved (ReloadCommitFraction passed). Not replicated. */
	UPROPERTY(NotReplicated)
	bool bReloadCommitted = false;
};

USTRUCT()
struct VERSECOMBAT_API FVerseWeaponSlotArray : public FFastArraySerializer
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FVerseWeaponSlotState> Items;

	bool NetDeltaSerialize(FNetDeltaSerializeInfo& DeltaParms)
	{
		return FFastArraySerializer::FastArrayDeltaSerialize<FVerseWeaponSlotState, FVerseWeaponSlotArray>(Items, DeltaParms, *this);
	}

	FVerseWeaponSlotState* Find(EVerseLoadoutSlot Slot);
	const FVerseWeaponSlotState* Find(EVerseLoadoutSlot Slot) const;
};

template <>
struct TStructOpsTypeTraits<FVerseWeaponSlotArray> : public TStructOpsTypeTraitsBase2<FVerseWeaponSlotArray>
{
	enum
	{
		WithNetDeltaSerializer = true,
	};
};

/** What a magazine tick or call did, for events and noise. */
enum class EVerseMagazineChange : uint8
{
	None,
	ReloadStarted,
	ReloadCommitted,
	ReloadFinished,
	ReloadCancelled
};

/**
 * The magazine and reload state machine (WP02.3): tactical vs empty, commit fraction, cancel,
 * chambered round. Pure functions on a slot state; the inventory component calls them on the
 * server and the owning client predicts with the same calls.
 */
struct VERSECOMBAT_API FVerseMagazine
{
	/** Full magazine and chamber, full reserve (spawn and respawn loadout). */
	static void InitFull(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	/** Rounds that can be fired without a reload (magazine plus a chambered round). */
	static int32 RoundsReady(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	static bool IsReloading(const FVerseWeaponSlotState& S) { return S.Reload != EVerseReloadPhase::None; }

	/** A reload now would be tactical (a round is chambered, or an open-bolt magazine is not empty). */
	static bool WouldBeTactical(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	static bool CanFire(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	/** Spends one round; false when nothing could be fired. */
	static bool ConsumeRound(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	/** Undoes one ConsumeRound (a predicted shot the server rejected). */
	static void RefundRound(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	static bool CanReload(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	/** Starts a tactical or empty reload at Now. */
	static bool StartReload(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W, float Now);

	/** Time at which the rounds move. */
	static float CommitTime(const FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);

	/** Advances a running reload to Now; returns the last change that happened. */
	static EVerseMagazineChange Tick(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W, float Now);

	/** Cancels a running reload: before the commit the old magazine stays, after it the new one. */
	static EVerseMagazineChange Cancel(FVerseWeaponSlotState& S);

private:
	static void Commit(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W);
};

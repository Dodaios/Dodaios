#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

// The UI's three seams to code it may not include or that has not landed yet. Each has a
// default adapter in the UI subsystem and a fake in Private/Tests/UI/Fakes/.
//
//  - IVerseUiBridgePort: the Verse -> app frames the UI sends (bridge-protocol 12, 14). WP17's
//    VerseBridge client implements it; until then the default logs the frame it would send.
//  - IVerseUiGamePort: start or leave the duel and change deck (WP11 switch, WP12 decks). The
//    default runs the registered Verse.QA.Duel.* commands, the only cross-module seam Core has.
//  - IVerseHudSource: what the HUD reads from the local pawn and the player states
//    (combat-state 2.1). The default reads the engine player states, the combat state
//    component and IVerseMovementQuery; magazine and gadget numbers need WP02's inventory.

/** Verse -> app frames the UI sends. */
class VERSEUI_API IVerseUiBridgePort
{
public:
	virtual ~IVerseUiBridgePort() = default;

	/** settings.set with any subset of welcome.settings (bridge-protocol 14). */
	virtual void SendSettingsSet(const TSharedRef<FJsonObject>& Data) = 0;

	/** focus.return_to_app {reason: return_key | station | esc_menu} (bridge-protocol 12). */
	virtual void SendReturnToApp(const FString& Reason) = 0;
};

/** Duel and deck control. */
class VERSEUI_API IVerseUiGamePort
{
public:
	virtual ~IVerseUiGamePort() = default;

	/** Tier normal, hard, elite or adaptive. */
	virtual void StartDuel(FName Tier) = 0;
	virtual void LeaveDuel() = 0;
	virtual void TravelToDeck(FName Deck) = 0;
	virtual bool IsDuelRunning() const = 0;
	virtual FName GetCurrentDeck() const = 0;
	/** Holds or releases the match while a menu covers it (parity D-09). */
	virtual void SetPaused(bool bPaused) = 0;
};

struct VERSEUI_API FVerseHudGadgetState
{
	FName GadgetId;
	int32 Charges = 0;
	int32 MaxCharges = 0;
	/** s; 0 = ready. */
	float CooldownRemaining = 0.f;
};

/** The local pawn as the HUD shows it (bot.md 3.3: only what the person may know). */
struct VERSEUI_API FVerseHudPawnState
{
	bool bValid = false;
	/** False when the source cannot read health yet: the UI tracks it from own-hit events. */
	bool bHealthKnown = true;
	float Health = 100.f;
	float MaxHealth = 100.f;
	EVerseCombatPhase Phase = EVerseCombatPhase::Alive;
	EVerseStance Stance = EVerseStance::Stand;
	bool bSpawnProtected = false;
	/** s left; 0 when not protected. */
	float SpawnProtectionRemaining = 0.f;

	/** False until a weapon state is known: the ammo block is hidden then. */
	bool bHasWeapon = false;
	FName WeaponId;
	EVerseLoadoutSlot ActiveSlot = EVerseLoadoutSlot::Primary;
	int32 Magazine = 0;
	int32 MagazineSize = 0;
	bool bChambered = false;
	int32 Reserve = 0;
	bool bReloading = false;
	/** 0..1 */
	float ReloadProgress = 0.f;
	bool bTacticalReload = true;

	TArray<FVerseHudGadgetState> Gadgets;
};

/** The camera the HUD projects through. */
struct VERSEUI_API FVerseHudView
{
	FVector Location = FVector::ZeroVector;
	FRotator Rotation = FRotator::ZeroRotator;
	/** Horizontal field of view, degrees (aspect ratio keeps the horizontal FOV). */
	float HorizontalFovDeg = 100.f;
};

/** One recorded pose for the kill cam. */
struct VERSEUI_API FVersePawnPose
{
	int32 PlayerId = 0;
	FVector Location = FVector::ZeroVector;
	/** Control (view) rotation. */
	FRotator Rotation = FRotator::ZeroRotator;
	/**
	 * Server time of the state this pose shows, s; negative = the source's server time now.
	 * A source sets it when the pawn is drawn later than its replicated state (smoothing).
	 */
	double ServerTime = -1.0;
};

/** What the HUD reads every frame. */
class VERSEUI_API IVerseHudSource
{
public:
	virtual ~IVerseHudSource() = default;

	/** Player state id of the person; INDEX_NONE when there is no local player. */
	virtual int32 GetLocalPlayerId() const = 0;
	/** Server world time, s (the clock of every event's ServerTime and of RespawnAt). */
	virtual double GetServerTime() const = 0;
	virtual void GetPawnState(FVerseHudPawnState& Out) const = 0;
	virtual bool GetView(FVerseHudView& Out) const = 0;

	/**
	 * Direction the next own bolt leaves in (owner prediction: camera, recoil and sway; not the
	 * random spread, which is shown as the circle). False when no weapon aims: the crosshair
	 * then sits on the camera axis.
	 */
	virtual bool GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const = 0;

	virtual FText GetDisplayName(int32 PlayerId) const = 0;
	virtual bool IsBot(int32 PlayerId) const = 0;
	/** AVersePlayerState::BotTier: normal, hard, elite, adaptive; None for a person. */
	virtual FName GetBotTier(int32 PlayerId) const = 0;
	/** AVersePlayerState::BotEffectiveSkill: adaptive s, -1 for a person. */
	virtual float GetBotEffectiveSkill(int32 PlayerId) const = 0;

	/** Current poses of every pawn the client sees (kill cam recording). */
	virtual void GetPawnPoses(TArray<FVersePawnPose>& Out) const = 0;
};

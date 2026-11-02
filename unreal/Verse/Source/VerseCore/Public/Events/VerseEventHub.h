#pragma once

#include "Combat/VerseCombatTypes.h"
#include "CoreMinimal.h"
#include "Destruction/VerseDestructionTypes.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseEventHub.generated.h"

// The hub delegates of combat-state.md 11.1. All cross-module traffic that goes "up" the module
// graph travels through these (architecture.md 2, rule 2): Combat never includes Gore, UI or
// Bot; they subscribe. The hub only relays: it holds no state and never filters.

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseFire, const FVerseFireEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseHit, const FVerseHitEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVersePenetration, const FVersePenetrationEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseDeath, const FVerseDeathEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseFinisher, const FVerseFinisherEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseNoise, const FVerseNoiseEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseReload, const FVerseReloadEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseGadget, const FVerseGadgetEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseFracture, const FVerseFractureEvent&);    // destruction 4
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseArenaSwitch, const FVerseArenaSwitchEvent&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseSetEnded, const FVerseSetSummary&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseStationUsed, const FVerseStationUsedEvent&);

/** Core world subsystem; one per game world (server and each client). */
UCLASS()
class VERSECORE_API UVerseEventHub : public UWorldSubsystem
{
	GENERATED_BODY()

public:
	/** The hub of the object's world, or nullptr (no world, or a world type without subsystems). */
	static UVerseEventHub* Get(const UObject* WorldContextObject);

	FOnVerseFire OnFire;
	FOnVerseHit OnHit;
	FOnVersePenetration OnPenetration;
	FOnVerseDeath OnDeath;
	FOnVerseFinisher OnFinisher;
	/** Server only; Bot listens. */
	FOnVerseNoise OnNoise;
	FOnVerseReload OnReload;
	FOnVerseGadget OnGadget;
	/** Server and clients. */
	FOnVerseFracture OnFracture;
	/** Decks raises; Combat rules, Destruction reset, Crew, Bot listen. */
	FOnVerseArenaSwitch OnArenaSwitch;
	/** Server; the Bridge duel reporter and the UI listen. */
	FOnVerseSetEnded OnSetEnded;
	/** Local; Decks raises, UI and Screens listen (no Decks -> UI include). */
	FOnVerseStationUsed OnStationUsed;

	virtual void Deinitialize() override;
};

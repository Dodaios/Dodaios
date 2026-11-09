#pragma once

#include "Combat/VerseCombatTypes.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"

#include "VerseCombatDriverComponent.generated.h"

/**
 * Routes the pawn's input frame (bot.md B1: one FVerseInputFrame for persons, bots and harness
 * models) into the combat components of combat-state.md 2.1. Movement never includes Combat
 * (decision C8), so the primary module is where a frame's buttons become shots, reloads, slot
 * switches, knife presses and gadget uses:
 *
 * - person: the frame AVerseCharacter::ApplyInputFrame consumed this tick,
 * - AVerseBotController: its last input frame (the bot moves the pawn itself),
 * - any other controller (harness person models): the frame it hands to SetExternalFrame.
 *
 * Runs on the locally controlled person and on the server for AI controllers; the weapon component
 * predicts and sends ServerFire itself, gadgets go through ServerUseGadget.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSE_API UVerseCombatDriverComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseCombatDriverComponent();

	static UVerseCombatDriverComponent* FindOn(const AActor* Actor);

	/** A controller that does not drive the pawn through ApplyInputFrame hands its frame here, once per tick. */
	void SetExternalFrame(const FVerseInputFrame& Frame);

	/** Server: starts a gadget use for a remote owner. */
	UFUNCTION(Server, Reliable)
	void ServerUseGadget(EVerseLoadoutSlot Slot);

	/** Shots this pawn's owner fired through the driver (stats and tests). */
	int32 GetShotsFired() const { return ShotsFired; }

	/** One drive step with an explicit frame (tests); TickComponent calls it with the frame it reads. */
	void Drive(const FVerseInputFrame& Frame, float DeltaSeconds);

	virtual void BeginPlay() override;
	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;

private:
	/** False when this machine does not drive the pawn (simulated proxies, remote persons on the server). */
	bool ReadFrame(FVerseInputFrame& OutFrame);
	void UseGadget(EVerseLoadoutSlot Slot);
	void SwitchSlot(EVerseLoadoutSlot Slot);

	FVerseInputFrame External;
	bool bHasExternal = false;
	bool bExternalFresh = false;
	uint32 PrevButtons = 0;
	int32 ShotsFired = 0;
	/** Server time of the last automatic reload request, s. */
	float LastAutoReloadAt = -100.f;
};

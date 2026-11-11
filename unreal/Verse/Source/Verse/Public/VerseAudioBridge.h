#pragma once

#include "CoreMinimal.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseAudioBridge.generated.h"

class AVerseCharacter;
class UPhysicalMaterial;
class UVerseAudioSubsystem;
struct FVerseNoiseEvent;
enum class EVerseFootSurface : uint8;
enum class EVerseLiftCue : uint8;
enum class EVerseUiScreen : uint8;

/**
 * The sounds whose sources the audio subsystem (VerseUI) cannot reach by itself, because they
 * live in modules VerseUI may not include: footsteps and movement foley (VerseMovement), the
 * equip sound on a weapon change (VerseCombat), the knife swing (the melee noise), the lift
 * doors and ride (VerseDecks), the deck ambience bed, the menu panels (VerseUI's own screens),
 * the level bell on an award (VerseBridge) and where another player's reload plays.
 */
UCLASS()
class VERSE_API UVerseAudioBridge : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	virtual bool ShouldCreateSubsystem(UObject* Outer) const override;
	virtual void Initialize(FSubsystemCollectionBase& Collection) override;
	virtual void Deinitialize() override;
	virtual void OnWorldBeginPlay(UWorld& InWorld) override;
	virtual void Tick(float DeltaTime) override;
	virtual bool IsTickableWhenPaused() const override { return true; }
	virtual TStatId GetStatId() const override;

	/** The footstep surface of a floor's physical material (deck plating is metal). */
	static EVerseFootSurface SurfaceOf(const UPhysicalMaterial* Material);

	/** Sounds the bridge started (tests). */
	int32 GetFootsteps() const { return Footsteps; }
	int32 GetEquips() const { return Equips; }

private:
	void HandleFootstep(const FVerseNoiseEvent& Event, const UPhysicalMaterial* Surface);
	void HandleNoise(const FVerseNoiseEvent& Event);
	void HandleLiftCue(EVerseLiftCue Cue);
	void HandleDeckArrived(FName Deck, bool bByLift);
	void HandleScreen(EVerseUiScreen Screen);
	void UpdateAmbience();
	void BindPawns();
	void WatchEquip();
	UVerseAudioSubsystem* Audio() const;

	TSet<TWeakObjectPtr<AVerseCharacter>> BoundPawns;
	TWeakObjectPtr<APawn> EquipPawn;
	EVerseLoadoutSlot EquipSlot = EVerseLoadoutSlot::Primary;
	bool bPanelOpen = false;
	int32 Footsteps = 0;
	int32 Equips = 0;
	FDelegateHandle NoiseHandle;
	FDelegateHandle LiftHandle;
	FDelegateHandle ArrivedHandle;
	FDelegateHandle ScreenHandle;
	FDelegateHandle AwardHandle;
};

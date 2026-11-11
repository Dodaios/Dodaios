#pragma once

#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"

class APlayerController;
class APlayerState;
class UVerseBridgeSubsystem;
class UWorld;

/**
 * The UI's frames to the app (IVerseUiBridgePort) through the bridge: settings.set as a command
 * on the link, focus.return_to_app through the lifecycle (which also hides the window).
 */
class FVerseDuelBridgePort : public IVerseUiBridgePort
{
public:
	explicit FVerseDuelBridgePort(UVerseBridgeSubsystem* InBridge);

	virtual void SendSettingsSet(const TSharedRef<FJsonObject>& Data) override;
	virtual void SendReturnToApp(const FString& Reason) override;

private:
	TWeakObjectPtr<UVerseBridgeSubsystem> Bridge;
};

/** The UI's duel and deck control (IVerseUiGamePort) on top of UVerseDuelSubsystem and the deck subsystem. */
class FVerseDuelGamePort : public IVerseUiGamePort
{
public:
	explicit FVerseDuelGamePort(UWorld* InWorld) : World(InWorld) {}

	virtual void StartDuel(FName Tier) override;
	virtual void LeaveDuel() override;
	virtual void TravelToDeck(FName Deck) override;
	virtual bool IsDuelRunning() const override;
	virtual FName GetCurrentDeck() const override;
	virtual void SetPaused(bool bPaused) override;

private:
	TWeakObjectPtr<UWorld> World;
};

/**
 * What the HUD reads (IVerseHudSource) with the combat parts that VerseUI cannot include: health
 * and armour from UVerseHealthSet, magazine, reserve and reload from the inventory, gadget charges
 * and cooldown, and the predicted bolt direction with the weapon's spread.
 */
class FVerseDuelHudSource : public IVerseHudSource
{
public:
	explicit FVerseDuelHudSource(UWorld* InWorld) : World(InWorld) {}

	virtual int32 GetLocalPlayerId() const override;
	virtual double GetServerTime() const override;
	virtual void GetPawnState(FVerseHudPawnState& Out) const override;
	virtual bool GetView(FVerseHudView& Out) const override;
	virtual bool GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const override;
	virtual bool IsAimingThroughOptic() const override;
	virtual FText GetDisplayName(int32 PlayerId) const override;
	virtual bool IsBot(int32 PlayerId) const override;
	virtual FName GetBotTier(int32 PlayerId) const override;
	virtual float GetBotEffectiveSkill(int32 PlayerId) const override;
	virtual void GetPawnPoses(TArray<FVersePawnPose>& Out) const override;

private:
	APlayerController* LocalController() const;
	APlayerState* FindPlayer(int32 PlayerId) const;

	TWeakObjectPtr<UWorld> World;
};

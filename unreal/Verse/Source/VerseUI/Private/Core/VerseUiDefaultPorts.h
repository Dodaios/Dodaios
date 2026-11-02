#pragma once

#include "Core/VerseUiPorts.h"
#include "CoreMinimal.h"

class UWorld;

/** Logs the frame it would send; WP17's VerseBridge client replaces it (SetBridgePort). */
class FVerseUiLogBridgePort : public IVerseUiBridgePort
{
public:
	virtual void SendSettingsSet(const TSharedRef<FJsonObject>& Data) override;
	virtual void SendReturnToApp(const FString& Reason) override;

	int32 NumSent = 0;
};

/**
 * Runs the Verse.QA.Duel.* commands the duel owner registers (the one seam Core offers for it),
 * and tracks the arena state from FVerseArenaSwitchEvent.
 */
class FVerseUiQaGamePort : public IVerseUiGamePort
{
public:
	virtual void StartDuel(FName Tier) override;
	virtual void LeaveDuel() override;
	virtual void TravelToDeck(FName Deck) override;
	virtual bool IsDuelRunning() const override { return bArenaOn; }
	virtual FName GetCurrentDeck() const override { return CurrentDeck; }

	void NoteArenaSwitch(bool bOn, FName Deck);

	bool bArenaOn = false;
	FName CurrentDeck = TEXT("bridge");
};

/**
 * Reads the engine's player states and the local pawn: the combat state component, the
 * movement query, and the contract fields of AVersePlayerState (BotTier, BotEffectiveSkill)
 * by reflection, so VerseUI needs no include of the class that WP11 lands.
 */
class FVerseUiWorldHudSource : public IVerseHudSource
{
public:
	explicit FVerseUiWorldHudSource(UWorld* InWorld) : World(InWorld) {}

	virtual int32 GetLocalPlayerId() const override;
	virtual double GetServerTime() const override;
	virtual void GetPawnState(FVerseHudPawnState& Out) const override;
	virtual bool GetView(FVerseHudView& Out) const override;
	virtual bool GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const override;
	virtual FText GetDisplayName(int32 PlayerId) const override;
	virtual bool IsBot(int32 PlayerId) const override;
	virtual FName GetBotTier(int32 PlayerId) const override;
	virtual float GetBotEffectiveSkill(int32 PlayerId) const override;
	virtual void GetPawnPoses(TArray<FVersePawnPose>& Out) const override;

private:
	class APlayerController* LocalController() const;
	class APlayerState* FindPlayer(int32 PlayerId) const;

	TWeakObjectPtr<UWorld> World;
};

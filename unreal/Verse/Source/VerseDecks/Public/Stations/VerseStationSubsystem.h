#pragma once

#include "CoreMinimal.h"
#include "Stations/VerseCommandLink.h"
#include "Subsystems/WorldSubsystem.h"

#include "VerseStationSubsystem.generated.h"

class AVerseStation;

/** Something the use key can work: a station, or a desk monitor offering takeover (parity S-15). */
struct FVerseUseTarget
{
	/** The actor the crosshair hits for this target (parity S-12). */
	TWeakObjectPtr<AActor> Owner;
	TFunction<FVector()> Location;
	TFunction<bool()> CanUse;
	/** Localized name and action for the prompt (parity S-13, S-16). */
	TFunction<FString()> Label;
	TFunction<FString()> Action;
	TFunction<void(int32 UserId)> Use;
};

/** What the prompt below the view centre shows (parity S-13). */
struct FVerseStationPrompt
{
	int32 Handle = INDEX_NONE;
	FString Label;
	FString Action;
	FString Key = TEXT("E");

	bool IsValid() const { return Handle != INDEX_NONE; }
	bool operator==(const FVerseStationPrompt& O) const { return Handle == O.Handle && Label == O.Label && Action == O.Action; }
};

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseStationPrompt, const FVerseStationPrompt&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseStationNotice, const FString&);

/**
 * The station framework of a world (WP16.6): use targets, the prompt (5 Hz), the use key, the
 * notice line, and the command link every station view shares.
 */
UCLASS()
class VERSEDECKS_API UVerseStationSubsystem : public UTickableWorldSubsystem
{
	GENERATED_BODY()

public:
	static UVerseStationSubsystem* Get(const UObject* WorldContext);

	int32 AddUseTarget(FVerseUseTarget Target);
	void RemoveUseTarget(int32 Handle);
	int32 NumUseTargets() const { return Targets.Num(); }

	void RegisterStation(AVerseStation* Station);
	void UnregisterStation(AVerseStation* Station);
	AVerseStation* FindStation(FName StationId) const;

	/**
	 * Port of life/control.ts stationWithin: the target within Reach (cm, on the floor plane) with
	 * the lowest d * (1.5 - 0.5 cos), cos against Facing; one under the feet counts as in front.
	 */
	static int32 PickWithin(TConstArrayView<FVector> Locations, const FVector& At, float Reach, const FVector* Facing);

	/** The target the crosshair is on if it can be used, else the one within reach. */
	int32 PickTarget(const FVector& At, const FVector* Facing, const AActor* CrosshairActor) const;

	/** Tests and tools: the viewer and crosshair the prompt uses instead of the local player. */
	void SetViewerOverride(const FVector& Location, const FVector& Facing, AActor* CrosshairActor = nullptr);
	void ClearViewerOverride();

	/** Re-evaluates the prompt now (the tick does it every 0.2 s). */
	void RefreshPrompt();
	const FVerseStationPrompt& Prompt() const { return CurrentPrompt; }

	/** The use key: works the prompted target. False when nothing is in reach. */
	bool UseFocused(int32 UserId);
	bool UseTarget(int32 Handle, int32 UserId);

	void PostNotice(const FString& Text);

	/** Localized notice text for a reply error code (`verse.station.error.<code>`). */
	FString ErrorText(const FString& Code) const;

	void SetLink(TSharedPtr<IVerseCommandLink> InLink) { Link = MoveTemp(InLink); }
	IVerseCommandLink* GetLink() const { return Link.Get(); }
	FString Localize(const FString& Key, const FString& Fallback) const { return Link ? Link->Localize(Key, Fallback) : Fallback; }

	FOnVerseStationPrompt OnPromptChanged;
	FOnVerseStationNotice OnNotice;

	// UTickableWorldSubsystem
	virtual void Tick(float DeltaTime) override;
	virtual TStatId GetStatId() const override;
	virtual void Deinitialize() override;

private:
	bool ReadViewer(FVector& OutLocation, FVector& OutFacing, const AActor*& OutCrosshair) const;

	TMap<int32, FVerseUseTarget> Targets;
	TArray<TWeakObjectPtr<AVerseStation>> Stations;
	int32 NextHandle = 1;
	FVerseStationPrompt CurrentPrompt;
	float SincePrompt = 0.f;
	bool bViewerOverride = false;
	FVector OverrideLocation = FVector::ZeroVector;
	FVector OverrideFacing = FVector::ForwardVector;
	TWeakObjectPtr<AActor> OverrideCrosshair;
	TSharedPtr<IVerseCommandLink> Link;
};

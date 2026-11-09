#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "Stations/VerseStationTypes.h"

#include "VerseStation.generated.h"

class USceneComponent;

/**
 * A station (WP16.6): something the commander works with the use key. Zone owners place them
 * (work-packages.md 3); this class only offers the prompt and raises FVerseStationUsedEvent on the
 * hub when used, so VerseUI opens the matching view without VerseDecks including it.
 */
UCLASS(Blueprintable)
class VERSEDECKS_API AVerseStation : public AActor
{
	GENERATED_BODY()

public:
	AVerseStation();

	/** The manifest station id (placement `station.id`). */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Station")
	FName StationId;

	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Station")
	EVerseStationKind Kind = EVerseStationKind::AgentsList;

	/** The room the station stands in (manifest room id); a service record in a records hall opens the ladder. */
	UPROPERTY(EditAnywhere, BlueprintReadOnly, Category = "Station")
	FString Room;

	/** Where the commander stands to work it (parity S-11). */
	UPROPERTY(VisibleAnywhere, BlueprintReadOnly, Category = "Station")
	TObjectPtr<USceneComponent> UseSpot;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Station")
	bool bEnabled = true;

	/** Raises FVerseStationUsedEvent {StationId, KindName(Kind), UserId} on the world's hub. */
	UFUNCTION(BlueprintCallable, Category = "Station")
	virtual void Use(int32 UserId);

	FString PromptName() const;
	FString PromptAction() const;

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	int32 UseHandle = INDEX_NONE;
};

/** The hangar armoury station (WP16.8): its use raises the event WP18's armoury view listens to. */
UCLASS(Blueprintable)
class VERSEDECKS_API AVerseArmouryStation : public AVerseStation
{
	GENERATED_BODY()

public:
	AVerseArmouryStation();
};

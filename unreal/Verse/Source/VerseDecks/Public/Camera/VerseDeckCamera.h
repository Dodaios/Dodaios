#pragma once

#include "Camera/VerseDeckView.h"
#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseDeckCamera.generated.h"

class UCameraComponent;

/**
 * The deck camera rig (WP12.10): overview, third and first person on one camera, with mouse look,
 * the wheel hand-over between third and first person, and focus on the commander with the return
 * key back to the framing before. The deck subsystem spawns one per deck and makes it the view
 * target; input (Enhanced Input in the player controller) calls the functions below.
 */
UCLASS()
class VERSEDECKS_API AVerseDeckCamera : public AActor
{
	GENERATED_BODY()

public:
	AVerseDeckCamera();

	virtual void Tick(float DeltaSeconds) override;

	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void SetViewByName(const FString& Name);

	void SetView(EVerseDeckView NewView);
	EVerseDeckView GetView() const { return View; }

	/** V: the next view that can be shown (parity V-02). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void CycleView();

	/** Mouse movement in pixels; `bCaptured` when the mouse is captured (mouse look on). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void Look(float Dx, float Dy, bool bCaptured);

	/** Wheel or +/-: Factor > 1 moves out. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void Zoom(float Factor);

	/** Overview panning with held keys (X right, Y forward). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void Pan(FVector2D Input, float DeltaSeconds);

	/** The commander button: third person reframes behind, overview centres on the commander (parity V-17). */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	void FocusCommander();

	/** The return key: back to the overview framing before the last focus. */
	UFUNCTION(BlueprintCallable, Category = "Verse|Decks|Camera")
	bool ReturnFocus();

	/** A new deck frames the commander where they come aboard (parity V-22). */
	void FrameArrival(const FTransform& Arrival, TOptional<double> PitchDeg = {});

	/** `{view, person, distance, hfov, yaw, pitch, commander_hidden, locked}` (parity Q-05). */
	FString StateJson() const;

	/** First person is offered only where the deck has an eye-level scene (always, on a deck). */
	bool bEyeCapable = true;
	/** Mouse captured for shooter look (parity V-19, V-20). */
	bool bMouseLocked = false;

	FVerseShoulderRig Rig;
	FVerseOverviewCamera Overview;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks|Camera")
	TObjectPtr<UCameraComponent> Camera;

private:
	bool CommanderPose(FVerseRigBody& Out) const;
	TOptional<double> Trace(const FVector& From, const FVector& To) const;
	void Apply();

	EVerseDeckView View = EVerseDeckView::Third;
};

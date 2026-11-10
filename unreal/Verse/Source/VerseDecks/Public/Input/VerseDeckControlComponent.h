#pragma once

#include "Camera/VerseDeckView.h"
#include "Commander/VerseDeckNavGrid.h"
#include "Commander/VerseDeckWalk.h"
#include "Components/ActorComponent.h"
#include "CoreMinimal.h"
#include "Decks/VerseDeckManifest.h"
#include "Input/VerseDeckInput.h"

#include "VerseDeckControlComponent.generated.h"

class AActor;
class APawn;
class APlayerController;
class AVerseDeckCamera;
class AVerseDeckCommander;
class UEnhancedInputComponent;
class UInputMappingContext;
class UCanvas;
struct FInputActionValue;
struct FCollisionQueryParams;

/** What is under a screen point or the reticle. */
struct VERSEDECKS_API FVerseDeckPick
{
	enum class EKind : uint8
	{
		None,
		Floor,
		/** A wall, a console side, anything a body cannot stand on. */
		Wall,
		Crew,
		Station,
	};
	EKind Kind = EKind::None;
	FVector Point = FVector::ZeroVector;
	TWeakObjectPtr<AActor> Actor;
	FName Station;
};

/** What the deck overlay draws this frame (parity H-09, H-10, S-14). */
struct VERSEDECKS_API FVerseDeckPointerState
{
	/** Eye level with the mouse captured: the centre reticle. */
	bool bReticle = false;
	/** Something usable (a crew member, a station) is under the reticle. */
	bool bReticleMarked = false;
	/** Eye level, the window focused, the mouse free: "click to look". */
	bool bClickToLook = false;
	/** Overview hover over a station: its label at `LabelScreen`. */
	FName HoverStation;
	FText HoverLabel;
	FVector2D LabelScreen = FVector2D::ZeroVector;
	/** A crew member under the pointer or the reticle. */
	TWeakObjectPtr<AActor> HoverCrew;
};

/** Who has the mouse, as the deck control last told the player controller. */
enum class EVerseDeckMouseMode : uint8
{
	/** Nothing applied yet. */
	None,
	/** On a deck with the cursor free (overview, or eye level before "click to look"). */
	Free,
	/** On a deck in mouse look: game-only input, hidden cursor, captured raw deltas. */
	Look,
	/** Off the deck (the duel owns input): game-only input, hidden cursor, captured mouse. */
	Game,
};

DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseDeckStation, const FVerseDeckStation&);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseDeckCrew, AActor*);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseDeckFlag, bool);
DECLARE_MULTICAST_DELEGATE_OneParam(FOnVerseDeckViewChanged, EVerseDeckView);

/**
 * The deck commander's controls (stream S5). One per player controller while a deck is shown;
 * the deck subsystem adds it on every arrival.
 *
 * - Keys and mouse through Enhanced Input (`IMC_VerseDeck`, Verse::DeckInput): WASD and the
 *   arrows walk the commander relative to the view at eye level (V-12) or pan the overview
 *   (V-14), Shift hurries (V-13), V and 1/2/3 pick a view (V-03), E uses, L toggles mouse look
 *   (V-19), F (held) and B go to the abilities (stream S7), +/- and the wheel zoom.
 * - Keys only while the Verse window has focus and no Ctrl/Alt/Cmd chord is held (K-01, K-04).
 * - Choosing third or first person takes the mouse, the overview gives it back (V-20); captured
 *   look is raw (no smoothing, high precision mode; V-11).
 * - A click on the floor walks the commander there along the deck's nav grid (V-15); clicks pick
 *   a crew member only in plain view (V-16); a station click walks to it and uses it (S-11, S-18).
 * - The commander pawn is its own actor; the player controller's pawn (the duel body) is parked
 *   on the decks and handed back while the hangar is an arena.
 */
UCLASS()
class VERSEDECKS_API UVerseDeckControlComponent : public UActorComponent
{
	GENERATED_BODY()

public:
	UVerseDeckControlComponent();

	/** The control on the world's first player controller, or nullptr. */
	static UVerseDeckControlComponent* Get(const UWorld* World);
	/** The control on `Controller`, created when missing. */
	static UVerseDeckControlComponent* Ensure(APlayerController* Controller);
	/** Escape for the in-game menu owner: true when the deck used it (parity K-05). */
	static bool TryEscape(const UWorld* World);
	/**
	 * Gives the mouse back to the game after a menu closed: the deck's own mode while it owns
	 * input, game-only (captured, hidden cursor) otherwise. False when the world has no control.
	 */
	static bool RestoreInputMode(const UWorld* World);

	virtual void TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction) override;
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

	/** Draws the reticle, the "click to look" hint and the station label (H-09, H-10, S-14) on the game canvas. */
	void DrawOverlay(UCanvas* Canvas) const;

	/** A deck's first frame: place the commander, reset the walk order and the nav grid (B-07). */
	void OnDeckArrived(FName Deck, const FVerseDeckManifest& Manifest, const FTransform& Arrival, AVerseDeckCamera* Camera);

	// Input (Enhanced Input calls these; tests call them directly) --------------------------------

	void SetMoveAxes(const FVector2D& Axes);
	void SetHurry(bool bHeld);
	void PickView(EVerseDeckView View);
	void CycleView();
	/** L: mouse look on or off, at eye level only (V-19). */
	void ToggleMouseLook();
	void SetMouseLook(bool bOn);
	bool IsMouseLook() const { return bMouseLook; }
	/** E: what the reticle is on at eye level, else the station within reach. */
	void Use();
	/** + / -: true moves in. */
	void ZoomStep(bool bIn);
	/** The wheel: positive moves in. */
	void Wheel(float Value);
	/** Mouse movement in pixels (captured look, or a drag with the button held). */
	void LookDelta(const FVector2D& DeltaPx);
	void PointerDown(const FVector2D& ScreenPx);
	void PointerUp(const FVector2D& ScreenPx);
	/** A click at a screen point: crew, station, floor (overview), or take the mouse (eye level). */
	void Click(const FVector2D& ScreenPx);
	/** Escape (K-05): true when it ended mouse look or closed the selection. */
	bool HandleEscape();
	/** Held Ctrl/Alt/Cmd: the press belongs to the system (K-04). */
	bool IsChordHeld() const;
	/** True while the deck takes keys (K-01). */
	bool TakesKeys() const;

	// Commands ----------------------------------------------------------------------------------

	/** Walk the commander to a floor point; `bSnap` takes the nearest walkable floor within 1.2 m. False when unreachable. */
	bool WalkTo(const FVector& PointCm, bool bSnap = true);
	/** Use a station: the commander walks to its spot, the station's owner opens it (S-11, S-18). */
	bool ActivateStation(FName Station);
	/** Show a crew member: at eye level turn toward them, in the overview centre the map on them (V-18). */
	void ShowActor(const AActor* Actor);
	/** The commander button (V-17). */
	void FocusCommander();
	/** Hand the commander's salute to the body (the crew salutes on a promotion, parity C-19). */
	void Salute();
	/** Wear a uniform (parity F-18, the service record's `OnUniformWorn`). */
	void WearUniform(FName Uniform, const FLinearColor& Colour);

	/** What a screen point shows (V-16): the first thing the view ray meets, ceilings skipped in the overview. */
	FVerseDeckPick PickAt(const FVector2D& ScreenPx) const;
	/** The same for a world ray. */
	FVerseDeckPick PickRay(const FVector& Origin, const FVector& Direction) const;
	/** The view ray through a screen point of the deck camera (pixels, origin top left). */
	bool RayThrough(const FVector2D& ScreenPx, FVector& OutOrigin, FVector& OutDirection) const;

	// State --------------------------------------------------------------------------------------

	AVerseDeckCommander* GetCommander() const { return Commander.Get(); }
	AVerseDeckCamera* GetCamera() const { return Camera.Get(); }
	const FVerseDeckNavGrid& GetNav() const { return Nav; }
	/** Probes the rest of the nav grid now. */
	void CompleteNav();
	const FVerseWalkOrders& GetOrders() const { return Orders; }
	const FVerseDeckPointerState& GetPointer() const { return Pointer; }
	AActor* GetSelected() const { return Selected.Get(); }
	FName GetDeck() const { return Deck; }
	/** Off while the hangar is an arena (the duel owns input) or before the first deck. */
	bool IsDeckActive() const { return bActive; }
	/** The input mode this control last applied to its player controller. */
	EVerseDeckMouseMode GetMouseMode() const { return MouseMode; }
	const Verse::DeckInput::FContext& GetInputContext() const { return Input; }
	/** The pawn kept out of sight on the decks (the duel body). */
	APawn* GetParkedPawn() const { return Parked.Get(); }
	FVector2D GetViewportSize() const;
	/** `{deck, active, mouse_look, view, walking, goal, selected, nav_rows, nav_walkable}` for QA. */
	FString StateJson() const;

	// Hooks for the HUD, the crew and the abilities ----------------------------------------------

	FOnVerseDeckStation OnStationActivated;
	FOnVerseDeckCrew OnCrewSelected;
	FOnVerseDeckCrew OnCrewOpened;
	FSimpleMulticastDelegate OnSelectionCleared;
	/** F held down (true) and let go (false): Arc Storm (stream S7). */
	FOnVerseDeckFlag OnPower;
	/** B: the hoverboard (stream S7). */
	FSimpleMulticastDelegate OnBoard;
	FOnVerseDeckViewChanged OnViewChanged;
	FOnVerseDeckFlag OnMouseLookChanged;
	FSimpleMulticastDelegate OnDebugOverlay;

	/** The "click to look" hint (H-10); the UI replaces it with its string. */
	FText ClickToLookHint = NSLOCTEXT("VerseDecks", "ClickToLook", "Click to look");
	/** False hides the overlay (captures without HUD, the duel). */
	bool bDrawOverlay = true;

	/** A station's hover label (name and action, no key glyph; S-14). The UI replaces it with its strings. */
	TFunction<FText(const FVerseDeckStation&)> StationLabel;

	// Seams for tests ----------------------------------------------------------------------------

	/** Whether the Verse window has OS focus; defaults to FApp::HasFocus. */
	TFunction<bool()> WindowFocused;
	/** Whether a chord modifier is held; defaults to the player input. */
	TFunction<bool()> ChordProbe;
	/** The viewport size in pixels; defaults to the game viewport (1920 x 1080 without one). */
	TFunction<FVector2D()> ViewportSize;
	/** Where the mouse is, pixels; defaults to the player controller's cursor. */
	TFunction<TOptional<FVector2D>()> MousePosition;

	/** Default station label: the kind in words and what using it does. */
	static FText DefaultStationLabel(const FVerseDeckStation& Station);

private:
	void BindInput();
	void UnbindInput();
	void SetDeckActive(bool bOn);
	/** Applies the mouse mode the deck state asks for to the player controller. */
	void ApplyInputMode();
	void ParkPawn();
	void UnparkPawn();
	AVerseDeckCommander* EnsureCommander(const FTransform& Arrival);
	void StepNav(int32 Rows);
	TOptional<double> ProbeFloor(const FVector2D& PlanCm, double RoomZCm, const FCollisionQueryParams& Params) const;
	void UpdatePointer();
	void ApplyView(EVerseDeckView View, bool bTakeMouse);
	bool IsEyeLevel() const;
	const FVerseDeckStation* StationNear(const FVector& PointCm, double RadiusCm) const;
	void Select(AActor* Actor);
	void ClearSelection();

	void OnMoveAction(const FInputActionValue& Value);
	void OnMoveEnd(const FInputActionValue& Value);
	void OnLookAction(const FInputActionValue& Value);
	void OnWheelAction(const FInputActionValue& Value);
	void OnClickDown(const FInputActionValue& Value);
	void OnClickUp(const FInputActionValue& Value);

	UPROPERTY(Transient)
	TObjectPtr<UEnhancedInputComponent> DeckInputComponent;
	UPROPERTY(Transient)
	TArray<TObjectPtr<UObject>> InputObjects;

	Verse::DeckInput::FContext Input;
	TWeakObjectPtr<AVerseDeckCommander> Commander;
	TWeakObjectPtr<AVerseDeckCamera> Camera;
	TWeakObjectPtr<APawn> Parked;
	TWeakObjectPtr<AActor> Selected;
	FVerseDeckManifest Manifest;
	FVerseDeckNavGrid Nav;
	FVerseWalkOrders Orders;
	FVerseDeckPointerState Pointer;
	FName Deck;
	FVector2D MoveAxes = FVector2D::ZeroVector;
	FVector2D PressAt = FVector2D::ZeroVector;
	double DragPx = 0.0;
	bool bPressed = false;
	bool bHurry = false;
	bool bPower = false;
	bool bMouseLook = false;
	bool bActive = false;
	bool bBound = false;
	bool bWasFocused = true;
	EVerseDeckMouseMode MouseMode = EVerseDeckMouseMode::None;
	FDelegateHandle DrawHandle;
	FVector LastGoodFeet = FVector::ZeroVector;
	double FallingS = 0.0;
	/** The arena owned the hangar last frame. */
	bool bArenaWas = false;
};

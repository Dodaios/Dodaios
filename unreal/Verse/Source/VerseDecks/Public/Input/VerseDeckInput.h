#pragma once

#include "CoreMinimal.h"
#include "InputCoreTypes.h"

class UInputAction;
class UInputMappingContext;

/**
 * The deck's keys and mouse rules as pure data and maths (stream S5, parity K-01, K-04, K-05,
 * K-09, V-03, V-14, V-19, V-20). `UVerseDeckControlComponent` builds the Enhanced Input mapping
 * context from this table and routes the actions; the rules here decide what a press means.
 */
namespace Verse::DeckInput
{
	/** Every deck action (`IA_` names; IA_Move and IA_Sprint share the person's names so a rebinding moves both). */
	enum class EAction : uint8
	{
		Move,
		Hurry,
		CycleView,
		ViewOverview,
		ViewThird,
		ViewFirst,
		Use,
		MouseLook,
		Power,
		Board,
		ZoomIn,
		ZoomOut,
		Wheel,
		Look,
		Click,
		Debug,
		Count
	};

	/** How a key feeds an action: plain, or as one direction of the Axis2D move. */
	enum class EKeyRole : uint8
	{
		Press,
		MoveForward,
		MoveBack,
		MoveLeft,
		MoveRight,
	};

	struct FBinding
	{
		EAction Action;
		FKey Key;
		EKeyRole Role = EKeyRole::Press;
	};

	VERSEDECKS_API const TCHAR* ActionName(EAction Action);
	/** The deck's default key map (parity K-09: WASD/arrows, Shift, V, 1/2/3, E, L, F hold, B, +/-, F9). */
	VERSEDECKS_API TConstArrayView<FBinding> DefaultBindings();

	/** The built context and its actions (the mapping context `IMC_VerseDeck`). */
	struct VERSEDECKS_API FContext
	{
		UInputMappingContext* Context = nullptr;
		TArray<UInputAction*> Actions;

		UInputAction* Get(EAction Action) const { return Actions.IsValidIndex(int32(Action)) ? Actions[int32(Action)] : nullptr; }
	};

	/** Builds `IMC_VerseDeck` with one input action per EAction under `Outer`. */
	VERSEDECKS_API FContext BuildContext(UObject* Outer);

	/** A modifier that makes a press a chord the deck never takes (parity K-04): Ctrl, Alt, Cmd/Win. */
	VERSEDECKS_API bool IsChordModifier(const FKey& Key);

	/** What Escape does, in order (parity K-05). */
	enum class EEscape : uint8
	{
		/** Mouse look was on: Escape gives the mouse back, nothing else. */
		EndMouseLook,
		/** A crew card or a selection was open: Escape closes it. */
		CloseCard,
		/** Nothing of the deck's own was open: Escape goes on to the in-game menu. */
		PassThrough,
	};
	VERSEDECKS_API EEscape EscapeStep(bool bMouseLook, bool bCardOpen);

	/** Whether the deck takes the keys now (parity K-01): only with the Verse window focused and nobody typing. */
	VERSEDECKS_API bool TakesKeys(bool bWindowFocused, bool bTextFieldFocused, bool bChordHeld);

	/** A press and release closer than this many pixels is a click; more is a drag that turns the view. */
	inline constexpr double ClickSlopPx = 6.0;

	/** Zoom factors (`Factor > 1` moves out): + and the wheel forward move in. */
	inline constexpr double ZoomInFactor = 0.85;
	inline constexpr double ZoomOutFactor = 1.18;
}

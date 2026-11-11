#pragma once

#include "CoreMinimal.h"
#include "Settings/VerseUiSettings.h"

class UInputComponent;
class UInputMappingContext;
class UEnhancedInputLocalPlayerSubsystem;

/**
 * Applies the person's gameplay key bindings (WP18.8) to the Enhanced Input mapping contexts
 * the input owners add for the local player (WP01's IMC_VersePerson, later the weapon and
 * station contexts). keys.json names per action the input action ("input_action", for
 * example IA_Jump) and the default key: the first mapping of that action on that key is the
 * one the binding moves, so gamepad mappings, second keyboard keys and modifiers stay.
 */
class VERSEUI_API FVerseUiInputRemap
{
public:
	/** Sets Context's bound mappings to KeyMap's current keys; true when a key changed. */
	bool Apply(UInputMappingContext* Context, const FVerseKeyMap& KeyMap);

	/** Applies to every context applied to Subsystem's player; rebuilds its mappings on a change. */
	int32 ApplyToPlayer(UEnhancedInputLocalPlayerSubsystem* Subsystem, const FVerseKeyMap& KeyMap);

	/**
	 * Sets the legacy key bindings of Input (the duel person's keys: VerseMovement's
	 * VersePersonInput::BindDefaults and the combat keys of AVerseDefaultCharacter) to KeyMap's
	 * current keys. Every binding on an action's default key moves (pressed and released);
	 * bindings on other keys (gamepad, the second crouch key) stay. True when a key changed.
	 */
	bool ApplyToInputComponent(UInputComponent* Input, const FVerseKeyMap& KeyMap);

	/** Mapping indices this remap owns in Context (tests). */
	int32 NumBound(const UInputMappingContext* Context) const;

	/** Key binding indices this remap owns in Input (tests). */
	int32 NumBound(const UInputComponent* Input) const;

	void Reset()
	{
		Slots.Reset();
		KeySlots.Reset();
	}

private:
	/** context -> (mapping index -> keys.json action), found once from the default keys. */
	TMap<TWeakObjectPtr<UInputMappingContext>, TMap<int32, FName>> Slots;

	/** input component -> (key binding index -> keys.json action), found once from the default keys. */
	TMap<TWeakObjectPtr<UInputComponent>, TMap<int32, FName>> KeySlots;
};

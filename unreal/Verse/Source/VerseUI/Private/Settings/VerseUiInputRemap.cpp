#include "Settings/VerseUiInputRemap.h"

#include "Components/InputComponent.h"
#include "EnhancedActionKeyMapping.h"
#include "EnhancedInputSubsystems.h"
#include "InputAction.h"
#include "InputMappingContext.h"
#include "UObject/UObjectIterator.h"

bool FVerseUiInputRemap::Apply(UInputMappingContext* Context, const FVerseKeyMap& KeyMap)
{
	if (!Context)
	{
		return false;
	}
	TMap<int32, FName>* Bound = Slots.Find(Context);
	if (!Bound)
	{
		// First sight of this context: find the mapping each binding moves, by its default key.
		Bound = &Slots.Add(Context);
		const TArray<FEnhancedActionKeyMapping>& Mappings = Context->GetMappings();
		TSet<int32> Taken;
		for (const FVerseKeyMap::FAction& Action : KeyMap.GetActions())
		{
			if (Action.InputAction.IsNone())
			{
				continue;
			}
			for (int32 Index = 0; Index < Mappings.Num(); ++Index)
			{
				const UInputAction* InputAction = Mappings[Index].Action;
				if (!Taken.Contains(Index) && InputAction && InputAction->GetFName() == Action.InputAction && Mappings[Index].Key == Action.DefaultKey)
				{
					Bound->Add(Index, Action.Action);
					Taken.Add(Index);
					break;
				}
			}
		}
	}
	bool bChanged = false;
	for (const TPair<int32, FName>& Slot : *Bound)
	{
		if (!Context->GetMappings().IsValidIndex(Slot.Key))
		{
			continue;
		}
		const FKey Want = KeyMap.GetKey(Slot.Value);
		FEnhancedActionKeyMapping& Mapping = Context->GetMapping(Slot.Key);
		if (Want.IsValid() && Mapping.Key != Want)
		{
			Mapping.Key = Want;
			bChanged = true;
		}
	}
	return bChanged;
}

bool FVerseUiInputRemap::ApplyToInputComponent(UInputComponent* Input, const FVerseKeyMap& KeyMap)
{
	if (!IsValid(Input))
	{
		return false;
	}
	// Drop the components of pawns that are gone (one per life).
	for (auto It = KeySlots.CreateIterator(); It; ++It)
	{
		if (!It.Key().IsValid())
		{
			It.RemoveCurrent();
		}
	}
	TMap<int32, FName>* Bound = KeySlots.Find(Input);
	if (!Bound)
	{
		// First sight of this component: every binding on a gameplay action's default key
		// belongs to that action.
		Bound = &KeySlots.Add(Input);
		for (int32 Index = 0; Index < Input->KeyBindings.Num(); ++Index)
		{
			const FKey& Key = Input->KeyBindings[Index].Chord.Key;
			for (const FVerseKeyMap::FAction& Action : KeyMap.GetActions())
			{
				if (!Action.InputAction.IsNone() && Action.Command == EVerseUiCommand::None && Action.DefaultKey == Key)
				{
					Bound->Add(Index, Action.Action);
					break;
				}
			}
		}
	}
	bool bChanged = false;
	for (const TPair<int32, FName>& Slot : *Bound)
	{
		if (!Input->KeyBindings.IsValidIndex(Slot.Key))
		{
			continue;
		}
		const FKey Want = KeyMap.GetKey(Slot.Value);
		FInputChord& Chord = Input->KeyBindings[Slot.Key].Chord;
		if (Want.IsValid() && Chord.Key != Want)
		{
			Chord.Key = Want;
			bChanged = true;
		}
	}
	return bChanged;
}

int32 FVerseUiInputRemap::ApplyToPlayer(UEnhancedInputLocalPlayerSubsystem* Subsystem, const FVerseKeyMap& KeyMap)
{
	if (!Subsystem)
	{
		return 0;
	}
	int32 Changed = 0;
	for (TObjectIterator<UInputMappingContext> It; It; ++It)
	{
		UInputMappingContext* Context = *It;
		if (IsValid(Context) && Subsystem->HasMappingContext(Context) && Apply(Context, KeyMap))
		{
			++Changed;
		}
	}
	if (Changed > 0)
	{
		FModifyContextOptions Options;
		Options.bForceImmediately = true;
		Subsystem->RequestRebuildControlMappings(Options);
	}
	return Changed;
}

int32 FVerseUiInputRemap::NumBound(const UInputMappingContext* Context) const
{
	const TMap<int32, FName>* Bound = Slots.Find(MakeWeakObjectPtr(const_cast<UInputMappingContext*>(Context)));
	return Bound ? Bound->Num() : 0;
}

int32 FVerseUiInputRemap::NumBound(const UInputComponent* Input) const
{
	const TMap<int32, FName>* Bound = KeySlots.Find(MakeWeakObjectPtr(const_cast<UInputComponent*>(Input)));
	return Bound ? Bound->Num() : 0;
}

#include "Settings/VerseUiInputRemap.h"

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

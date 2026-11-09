#include "VerseWorldActionBridge.h"

#include "Bridge/VerseBridgeClient.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Lifecycle/VerseLifecycle.h"
#include "VerseBridgeSubsystem.h"
#include "VerseLog.h"
#include "WorldActions/VerseWorldActionReporter.h"

void UVerseWorldActionBridge::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Collection.InitializeDependency<UVerseBridgeSubsystem>();
	Collection.InitializeDependency<UVerseDeckSubsystem>();
	UVerseBridgeSubsystem* Bridge = GetGameInstance()->GetSubsystem<UVerseBridgeSubsystem>();
	UVerseDeckSubsystem* Decks = GetGameInstance()->GetSubsystem<UVerseDeckSubsystem>();
	if (Bridge == nullptr || Decks == nullptr)
	{
		return;
	}
	TWeakObjectPtr<UVerseWorldActionBridge> WeakSelf(this);
	TWeakObjectPtr<UVerseBridgeSubsystem> WeakBridge(Bridge);
	TWeakObjectPtr<UVerseDeckSubsystem> WeakDecks(Decks);
	Bridge->Lifecycle().OnStateChanged.AddLambda([WeakSelf, WeakDecks](EVerseLifecycleState State)
		{
			if (State == EVerseLifecycleState::Visible)
			{
				if (UVerseDeckSubsystem* Target = WeakDecks.Get())
				{
					Target->NotifyVisible();
				}
			}
			if (UVerseWorldActionBridge* Self = WeakSelf.Get())
			{
				Self->Flush();
			}
		});
	Decks->OnWorldAction.AddLambda([WeakSelf, WeakBridge](const FVerseWorldAction& Action)
		{
			UVerseWorldActionBridge* Self = WeakSelf.Get();
			if (Self != nullptr && WeakBridge.IsValid())
			{
				Self->Pending.Add(Action);
				Self->Flush();
			}
		});
}

void UVerseWorldActionBridge::Flush()
{
	UGameInstance* Instance = GetGameInstance();
	UVerseBridgeSubsystem* Bridge = Instance ? Instance->GetSubsystem<UVerseBridgeSubsystem>() : nullptr;
	// A deck can be entered before the link is up (a cold start loads it first): hold the actions
	// until the link is, rather than lose them to the "internal" answer of a down link.
	if (Bridge == nullptr || !Bridge->Client().IsLinked())
	{
		return;
	}
	TArray<FVerseWorldAction> Actions = MoveTemp(Pending);
	Pending.Reset();
	for (const FVerseWorldAction& Action : Actions)
	{
		Bridge->Client().SendCommand(TEXT("progression.action"), FVerseWorldActionReporter::ToBridgeData(Action));
	}
}

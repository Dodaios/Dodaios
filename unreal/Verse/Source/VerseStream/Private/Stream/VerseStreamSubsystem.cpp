#include "Stream/VerseStreamSubsystem.h"

#include "Engine/GameInstance.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/PlayerController.h"
#include "HAL/PlatformMisc.h"
#include "Stream/VerseConsoleStreamDriver.h"
#include "Stream/VerseStreamKey.h"
#include "VerseLog.h"

const FName UVerseStreamSubsystem::PanelCameraTag(TEXT("verse.panel_camera"));

namespace
{
	/** Stands in until the bridge client (WP17) provides the real link. */
	class FLogStreamLink final : public IVerseStreamLink
	{
	public:
		virtual void SendStreamState(EVersePanelStreamState State, const FString& Error) override
		{
			UE_LOG(LogVerseStream, Log, TEXT("panel.stream_state %s %s"), VerseStream::StateName(State), *Error);
		}
	};
}

void UVerseStreamSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Driver = MakeShared<FVerseConsoleStreamDriver>();
	Link = MakeShared<FLogStreamLink>();
	Rebuild();
}

void UVerseStreamSubsystem::Deinitialize()
{
	if (Driver.IsValid())
	{
		Driver->Stop();
	}
	EnterPanelView(false);
	Session.Reset();
	Super::Deinitialize();
}

void UVerseStreamSubsystem::Rebuild()
{
	if (Driver.IsValid() && Driver->IsStreaming())
	{
		Driver->Stop();
	}
	Session = MakeUnique<FVerseStreamSession>(Driver.ToSharedRef(), Link.ToSharedRef(), &UVerseStreamSubsystem::SignalUrlFromEnvironment);
	Session->OnPanelStateChanged = [this](bool bEnter) { EnterPanelView(bEnter); };
}

void UVerseStreamSubsystem::SetLink(TSharedRef<IVerseStreamLink> InLink)
{
	Link = InLink;
	Rebuild();
}

void UVerseStreamSubsystem::SetDriver(TSharedRef<IVerseStreamDriver> InDriver)
{
	if (Driver.IsValid())
	{
		Driver->Stop();
	}
	Driver = InDriver;
	Rebuild();
}

void UVerseStreamSubsystem::HandlePanelVisibility(bool bVisible, int32 W, int32 H, float Dpr)
{
	Session->OnPanelVisibility(bVisible, FVersePanelGeometry{ W, H, Dpr });
}

void UVerseStreamSubsystem::HandlePanelResize(int32 W, int32 H, float Dpr)
{
	Session->OnPanelResize(FVersePanelGeometry{ W, H, Dpr });
}

void UVerseStreamSubsystem::HandleFullViewVisible(bool bVisible)
{
	Session->OnFullViewVisible(bVisible);
}

EVersePanelStreamState UVerseStreamSubsystem::GetStreamState() const
{
	return Session ? Session->GetState() : EVersePanelStreamState::Stopped;
}

AActor* UVerseStreamSubsystem::FindPanelCamera(UWorld* World)
{
	if (World == nullptr)
	{
		return nullptr;
	}
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		if (It->ActorHasTag(PanelCameraTag))
		{
			return *It;
		}
	}
	return nullptr;
}

void UVerseStreamSubsystem::EnterPanelView(bool bEnter)
{
	bPanelSession = bEnter;
	UGameInstance* GameInstance = GetGameInstance();
	UWorld* World = GameInstance ? GameInstance->GetWorld() : nullptr;
	APlayerController* Controller = GameInstance ? GameInstance->GetFirstLocalPlayerController(World) : nullptr;
	if (Controller == nullptr)
	{
		return;
	}
	if (bEnter)
	{
		if (AActor* Camera = FindPanelCamera(World))
		{
			PreviousViewTarget = Controller->GetViewTarget();
			Controller->SetViewTarget(Camera);
		}
	}
	else if (PreviousViewTarget.IsValid())
	{
		Controller->SetViewTarget(PreviousViewTarget.Get());
		PreviousViewTarget.Reset();
	}
}

FString UVerseStreamSubsystem::SignalUrlFromEnvironment()
{
	const FString Bridge = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_BRIDGE"));
	const FString Token = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_TOKEN"));
	return VerseStreamKey::BuildSignalUrl(Bridge, Token);
}

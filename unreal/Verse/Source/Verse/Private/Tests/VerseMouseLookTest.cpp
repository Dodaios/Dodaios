#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "GameFramework/PlayerController.h"
#include "HangarSwitch/VerseHangarSwitchSubsystem.h"
#include "Input/VerseDeckControlComponent.h"
#include "GenericPlatform/GenericPlatformInputDeviceMapper.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Menus/VerseUiMenus.h"
#include "Core/VerseUiSubsystem.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "UnrealClient.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelSubsystem.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.MouseLook: mouse look in the running game, fed through the game viewport like a real
// mouse (scripts/unreal/screenshot.py runs it in -game). On a deck a click takes the mouse and
// MouseX turns the deck camera; in the duel MouseX/MouseY turn the person's control rotation with
// the viewport capturing permanently and the cursor hidden; a menu frees the cursor and closing it
// gives the game the captured mouse back.

namespace VerseMouseLookTest
{
	UWorld* GameWorld()
	{
		if (!GEngine)
		{
			return nullptr;
		}
		for (const FWorldContext& Context : GEngine->GetWorldContexts())
		{
			if ((Context.WorldType == EWorldType::Game || Context.WorldType == EWorldType::PIE) && Context.World())
			{
				return Context.World();
			}
		}
		return nullptr;
	}

	bool ShadersDone()
	{
		return GShaderCompilingManager == nullptr || GShaderCompilingManager->GetNumRemainingJobs() == 0;
	}

	/** One mouse event through the game viewport client, as the OS would deliver it. */
	void Feed(UWorld* World, const FKey& Key, EInputEvent Event, float Amount)
	{
		UGameViewportClient* Client = World ? World->GetGameViewport() : nullptr;
		if (Client == nullptr)
		{
			return;
		}
		Client->InputKey(FInputKeyEventArgs::CreateSimulated(Key, Event, Amount, 1, IPlatformInputDeviceMapper::Get().GetDefaultInputDevice(), false, Client->Viewport));
	}

	bool IsGameOnly(const APlayerController* PC)
	{
		return PC->GetCurrentInputModeDebugString().StartsWith(TEXT("Game Only"));
	}

	bool PermanentCapture(UWorld* World)
	{
		const UGameViewportClient* Client = World ? World->GetGameViewport() : nullptr;
		return Client && (Client->GetMouseCaptureMode() == EMouseCaptureMode::CapturePermanently
			|| Client->GetMouseCaptureMode() == EMouseCaptureMode::CapturePermanently_IncludingInitialMouseDown);
	}

	struct FState
	{
		int32 Phase = 0;
		int32 Frames = 0;
		double Since = 0.0;
		FRotator Before = FRotator::ZeroRotator;
	};
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualMouseLookTest, "Verse.Visual.MouseLook", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualMouseLookTest::RunTest(const FString&)
{
	using namespace VerseMouseLookTest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.MouseLook needs a game viewport (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> S = MakeShared<FState>();
	S->Since = FPlatformTime::Seconds();
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]() -> bool
	{
		UWorld* World = GameWorld();
		APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
		UVerseDeckControlComponent* Deck = UVerseDeckControlComponent::Get(World);
		UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
		const double Waited = FPlatformTime::Seconds() - S->Since;
		auto Next = [&S]() { ++S->Phase; S->Frames = 0; S->Since = FPlatformTime::Seconds(); };
		auto Fail = [this](const FString& Why) { AddError(Why); return true; };
		if (Waited > 120.0)
		{
			return Fail(FString::Printf(TEXT("phase %d timed out"), S->Phase));
		}
		switch (S->Phase)
		{
		case 0:  // the hangar deck is up
			if (PC && Deck && Deck->IsDeckActive() && Duel && ShadersDone() && World->GetGameViewport())
			{
				Deck->WindowFocused = []() { return true; };
				// Eye level with the mouse given back: the "click to look" state.
				Deck->PickView(EVerseDeckView::Third);
				Deck->SetMouseLook(false);
				TestTrue(TEXT("deck: free cursor before the click"), Deck->GetMouseMode() == EVerseDeckMouseMode::Free && PC->ShouldShowMouseCursor());
				Next();
			}
			return false;
		case 1:  // deck: a click takes the mouse (click to look)
			if (++S->Frames == 2)
			{
				Feed(World, EKeys::LeftMouseButton, IE_Pressed, 1.f);
			}
			else if (S->Frames == 3)
			{
				Feed(World, EKeys::LeftMouseButton, IE_Released, 0.f);
			}
			else if (S->Frames == 8)
			{
				TestTrue(TEXT("deck: a click takes the mouse"), Deck->IsMouseLook() && Deck->GetMouseMode() == EVerseDeckMouseMode::Look);
				TestTrue(TEXT("deck: game-only input while looking"), IsGameOnly(PC));
				TestFalse(TEXT("deck: cursor hidden while looking"), PC->ShouldShowMouseCursor());
				TestTrue(TEXT("deck: the viewport captures permanently"), PermanentCapture(World));
				S->Before = PC->PlayerCameraManager->GetCameraRotation();
			}
			else if (S->Frames > 8 && S->Frames <= 48)
			{
				Feed(World, EKeys::MouseX, IE_Axis, 12.f);
			}
			else if (S->Frames == 54)
			{
				const double Turned = FMath::Abs(FRotator::NormalizeAxis(PC->PlayerCameraManager->GetCameraRotation().Yaw - S->Before.Yaw));
				AddInfo(FString::Printf(TEXT("deck: MouseX turns the deck camera (%.2f deg)"), Turned));
				TestTrue(FString::Printf(TEXT("deck: MouseX turns the deck camera (%.2f deg)"), Turned), Turned > 2.0);
				TestTrue(TEXT("duel starts"), Duel->StartDuel(TEXT("normal")));
				Next();
			}
			return false;
		case 2:  // the duel owns the person and the mouse
			if (Duel->IsDuelRunning() && !Deck->IsDeckActive() && Cast<AVerseDefaultCharacter>(PC->GetPawn()) && ++S->Frames > 30)
			{
				TestTrue(TEXT("duel: the deck handed over a captured mouse"), Deck->GetMouseMode() == EVerseDeckMouseMode::Game);
				TestTrue(TEXT("duel: game-only input"), IsGameOnly(PC));
				TestFalse(TEXT("duel: cursor hidden"), PC->ShouldShowMouseCursor());
				TestTrue(TEXT("duel: the viewport captures permanently"), PermanentCapture(World));
				S->Before = PC->GetControlRotation();
				Next();
			}
			return false;
		case 3:  // duel: MouseX and MouseY through the real input stack turn the control rotation
			if (++S->Frames <= 20)
			{
				Feed(World, EKeys::MouseX, IE_Axis, 6.f);
				Feed(World, EKeys::MouseY, IE_Axis, 2.f);
			}
			else if (S->Frames == 26)
			{
				const FRotator Now = PC->GetControlRotation();
				const double Yaw = FMath::Abs(FRotator::NormalizeAxis(Now.Yaw - S->Before.Yaw));
				const double Pitch = FMath::Abs(FRotator::NormalizeAxis(Now.Pitch - S->Before.Pitch));
				AddInfo(FString::Printf(TEXT("duel: MouseX turns the control yaw (%.2f deg)"), Yaw));
				TestTrue(FString::Printf(TEXT("duel: MouseX turns the control yaw (%.2f deg)"), Yaw), Yaw > 1.0);
				AddInfo(FString::Printf(TEXT("duel: MouseY turns the control pitch (%.2f deg)"), Pitch));
				TestTrue(FString::Printf(TEXT("duel: MouseY turns the control pitch (%.2f deg)"), Pitch), Pitch > 0.2);
				Next();
			}
			return false;
		case 4:  // a menu frees the cursor; closing it gives the game the captured mouse back
		{
			UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(World);
			if (!TestNotNull(TEXT("ui"), Ui))
			{
				return true;
			}
			if (++S->Frames == 1)
			{
				Ui->ShowScreen(EVerseUiScreen::EscMenu);
			}
			else if (S->Frames == 4)
			{
				TestTrue(TEXT("menu: cursor shown"), PC->ShouldShowMouseCursor());
				TestEqual(TEXT("menu: game and UI"), PC->GetCurrentInputModeDebugString(), FString(TEXT("Game and UI")));
				Ui->ShowScreen(EVerseUiScreen::None);
			}
			else if (S->Frames == 7)
			{
				TestTrue(TEXT("menu closed: game-only input"), IsGameOnly(PC));
				TestFalse(TEXT("menu closed: cursor hidden"), PC->ShouldShowMouseCursor());
				TestTrue(TEXT("menu closed: the viewport captures permanently"), PermanentCapture(World));
				S->Before = PC->GetControlRotation();
			}
			else if (S->Frames > 7 && S->Frames <= 20)
			{
				Feed(World, EKeys::MouseX, IE_Axis, 6.f);
			}
			else if (S->Frames == 26)
			{
				const double Yaw = FMath::Abs(FRotator::NormalizeAxis(PC->GetControlRotation().Yaw - S->Before.Yaw));
				AddInfo(FString::Printf(TEXT("menu closed: MouseX still turns the camera (%.2f deg)"), Yaw));
				TestTrue(FString::Printf(TEXT("menu closed: MouseX still turns the camera (%.2f deg)"), Yaw), Yaw > 1.0);
				Duel->LeaveDuel();
				return true;
			}
			return false;
		}
		default:
			return true;
		}
	}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#include "Abilities/VerseArcStormComponent.h"
#include "Bridge/VerseBridgeClient.h"
#include "Bridge/VerseBridgeCodec.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "EngineUtils.h"
#include "Abilities/VerseHoverboardComponent.h"
#include "Commander/VerseDeckCommander.h"
#include "Core/VerseUiSubsystem.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Camera/CameraComponent.h"
#include "Camera/VerseDeckCamera.h"
#include "Engine/Engine.h"
#include "Engine/GameViewportClient.h"
#include "Engine/World.h"
#include "Framework/Application/SlateApplication.h"
#include "Gadgets/VerseGadgetComponent.h"
#include "GameFramework/PlayerController.h"
#include "GameFramework/PlayerState.h"
#include "GenericPlatform/GenericPlatformInputDeviceMapper.h"
#include "HAL/PlatformTime.h"
#include "Input/VerseDeckControlComponent.h"
#include "InputCoreTypes.h"
#include "InputKeyEventArgs.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Inventory/VerseWeaponSlot.h"
#include "Lifecycle/VerseLifecycle.h"
#include "Misc/App.h"
#include "Misc/AutomationTest.h"
#include "Misc/OutputDeviceRedirector.h"
#include "ShaderCompiler.h"
#include "Tests/AutomationCommon.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UnrealClient.h"
#include "VerseBridgeSubsystem.h"
#include "VerseDefaultCharacter.h"
#include "VerseDuelSubsystem.h"
#include "Weapons/VerseWeaponComponent.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Visual.Playtest: one person's whole session in the running game, fed like a real player.
// Keys and mouse go through the game viewport (scripts/unreal/screenshot.py runs it in -game);
// Escape goes through Slate, where the UI's input preprocessor reads it. The run: walk the
// hangar deck, hoverboard and Arc Storm; Quick duel; fire, reload, aim, switch to pistol and
// knife, both gadgets; Escape menu and options; lose a set to the bot, continue, win or lose a
// set on autoplay; leave, rematch, leave; every deck by the bar; Quick duel from another deck;
// back to the app. After every transition the input mode and the mouse capture must fit the screen,
// and no error line may appear in the log.

namespace VersePlaytest
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

	/** One key or mouse event through the game viewport client, as the OS would deliver it. */
	void Feed(UWorld* World, const FKey& Key, EInputEvent Event, float Amount = 1.f)
	{
		UGameViewportClient* Client = World ? World->GetGameViewport() : nullptr;
		if (Client == nullptr)
		{
			return;
		}
		Client->InputKey(FInputKeyEventArgs::CreateSimulated(Key, Event, Amount, Key.IsAxis1D() ? 1 : 0,
			IPlatformInputDeviceMapper::Get().GetDefaultInputDevice(), false, Client->Viewport));
	}

	/** A key press through Slate (input preprocessors first, as for a real key). */
	void SlateKey(const FKey& Key)
	{
		if (!FSlateApplication::IsInitialized())
		{
			return;
		}
		const FKeyEvent Down(Key, FModifierKeysState(), 0, false, 0, 0);
		FSlateApplication::Get().ProcessKeyDownEvent(Down);
		FSlateApplication::Get().ProcessKeyUpEvent(Down);
	}

	bool IsGameOnly(const APlayerController* PC)
	{
		return PC && PC->GetCurrentInputModeDebugString().StartsWith(TEXT("Game Only"));
	}

	bool PermanentCapture(UWorld* World)
	{
		const UGameViewportClient* Client = World ? World->GetGameViewport() : nullptr;
		return Client && (Client->GetMouseCaptureMode() == EMouseCaptureMode::CapturePermanently
			|| Client->GetMouseCaptureMode() == EMouseCaptureMode::CapturePermanently_IncludingInitialMouseDown);
	}

	/** Error lines and ensures of the run (a player-facing session must not log either). */
	class FErrorLog : public FOutputDevice
	{
	public:
		FCriticalSection Lock;
		TArray<FString> Lines;
		virtual void Serialize(const TCHAR* V, ELogVerbosity::Type Verbosity, const FName& Category) override
		{
			const ELogVerbosity::Type Level = ELogVerbosity::Type(Verbosity & ELogVerbosity::VerbosityMask);
			if (Level <= ELogVerbosity::Error || FCString::Strstr(V, TEXT("Ensure condition failed")))
			{
				FScopeLock Guard(&Lock);
				Lines.Add(FString::Printf(TEXT("%s: %s"), *Category.ToString(), V));
			}
		}
		virtual bool CanBeUsedOnAnyThread() const override { return true; }
	};

	struct FState
	{
		int32 Phase = 0;
		int32 Frames = 0;
		double Since = 0.0;
		FVector Spot = FVector::ZeroVector;
		FRotator Look = FRotator::ZeroRotator;
		int32 Count = 0;
		int32 DeckIndex = 0;
		double LookDeg = 0.0;
		double PitchDeg = 0.0;
		float Fov = 0.f;
		EVerseSetOutcome FirstOutcome = EVerseSetOutcome::Unfinished;
		TSharedPtr<FErrorLog> Errors;
	};

	int32 PersonId(const APlayerController* PC)
	{
		return PC && PC->PlayerState ? PC->PlayerState->GetPlayerId() : INDEX_NONE;
	}

	/** Shots, hits, kills and deaths of the person and of the bot so far. */
	void Totals(const UVerseDuelSubsystem* Duel, int32 Person, FVerseDuelPlayerStats& OutPerson, FVerseDuelPlayerStats& OutBot)
	{
		for (const TPair<int32, FVerseDuelPlayerStats>& Pair : Duel->GetPlayerStats())
		{
			FVerseDuelPlayerStats& Into = Pair.Key == Person ? OutPerson : OutBot;
			Into.Shots += Pair.Value.Shots;
			Into.Hits += Pair.Value.Hits;
			Into.Kills += Pair.Value.Kills;
			Into.Deaths += Pair.Value.Deaths;
		}
	}

	UVerseBridgeSubsystem* BridgeOf(UWorld* World)
	{
		UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
		return Instance ? Instance->GetSubsystem<UVerseBridgeSubsystem>() : nullptr;
	}

	TSharedPtr<FJsonObject> Json(const TCHAR* Text)
	{
		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Data);
		return Data;
	}

	/** lifecycle.show onto a monitor far off screen, so the test window never covers the desktop. */
	const TCHAR* OffscreenShow = TEXT("{\"monitor\":{\"x\":-32000,\"y\":-32000,\"w\":1920,\"h\":1080,\"dpi\":96},\"reason\":\"verse_view\"}");
	const TCHAR* QuickDuelShow = TEXT("{\"monitor\":{\"x\":-32000,\"y\":-32000,\"w\":1920,\"h\":1080,\"dpi\":96},\"reason\":\"quick_start_duel\"}");
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualPlaytestTest, "Verse.Visual.Playtest", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualPlaytestTest::RunTest(const FString&)
{
	using namespace VersePlaytest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.Playtest needs a game viewport (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> S = MakeShared<FState>();
	S->Since = FPlatformTime::Seconds();
	S->Errors = MakeShared<FErrorLog>();
	GLog->AddOutputDevice(S->Errors.Get());
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]() -> bool
	{
		UWorld* World = GameWorld();
		APlayerController* PC = World ? World->GetFirstPlayerController() : nullptr;
		UVerseDeckControlComponent* Deck = UVerseDeckControlComponent::Get(World);
		UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
		UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(World);
		UVerseDeckSubsystem* Decks = UVerseDeckSubsystem::Get(World);
		AVerseDefaultCharacter* Person = PC ? Cast<AVerseDefaultCharacter>(PC->GetPawn()) : nullptr;
		UVerseInventoryComponent* Inventory = Person ? UVerseInventoryComponent::FindOn(Person) : nullptr;
		const double Waited = FPlatformTime::Seconds() - S->Since;
		auto Next = [&S]() { ++S->Phase; S->Frames = 0; S->Count = 0; S->Since = FPlatformTime::Seconds(); };
		auto Finish = [this, S]()
		{
			GLog->RemoveOutputDevice(S->Errors.Get());
			FScopeLock Guard(&S->Errors->Lock);
			for (const FString& Line : S->Errors->Lines)
			{
				AddError(FString::Printf(TEXT("error logged during play: %s"), *Line));
			}
			return true;
		};
		auto Fail = [this, Finish](const FString& Why) { AddError(Why); return Finish(); };
		// Sets take a few minutes of game time; everything else is quick.
		const double Limit = (S->Phase == 11 || S->Phase == 13) ? 900.0 : 120.0;
		if (Waited > Limit)
		{
			return Fail(FString::Printf(TEXT("phase %d timed out after %.0f s"), S->Phase, Waited));
		}
		if (!PC || !Duel || !Ui || !Decks)
		{
			return false;
		}
		auto MagazineOf = [Inventory](EVerseLoadoutSlot Slot) -> int32
		{
			const FVerseWeaponSlotState* State = Inventory ? Inventory->GetSlotState(Slot) : nullptr;
			return State ? State->Magazine : -1;
		};
		auto ExpectDuelInput = [this, PC, World](const TCHAR* When)
		{
			TestTrue(FString::Printf(TEXT("%s: game-only input"), When), IsGameOnly(PC));
			TestFalse(FString::Printf(TEXT("%s: cursor hidden"), When), PC->ShouldShowMouseCursor());
			TestTrue(FString::Printf(TEXT("%s: the viewport captures permanently"), When), PermanentCapture(World));
		};
		auto ExpectMenuInput = [this, PC](const TCHAR* When)
		{
			TestTrue(FString::Printf(TEXT("%s: cursor shown"), When), PC->ShouldShowMouseCursor());
			TestEqual(FString::Printf(TEXT("%s: game and UI input"), When), PC->GetCurrentInputModeDebugString(), FString(TEXT("Game and UI")));
		};

		switch (S->Phase)
		{
		case 0:  // the hangar deck is up
			if (Deck && Deck->IsDeckActive() && ShadersDone() && World->GetGameViewport() && AVerseDeckCommander::Find(World)
				&& ++S->Frames > 30)
			{
				Deck->WindowFocused = []() { return true; };
				TestEqual(TEXT("the person arrives on the hangar"), Decks->GetCurrentDeck(), FName(TEXT("hangar")));
				Deck->PickView(EVerseDeckView::Third);
				Deck->SetMouseLook(false);
				S->Spot = AVerseDeckCommander::Find(World)->GetActorLocation();
				Next();
			}
			return false;
		case 1:  // deck: W walks the Sovereign
			if (++S->Frames == 1)
			{
				Feed(World, EKeys::W, IE_Pressed);
			}
			else if (S->Frames == 45)
			{
				Feed(World, EKeys::W, IE_Released);
			}
			else if (S->Frames == 60)
			{
				const double Moved = FVector::Dist2D(AVerseDeckCommander::Find(World)->GetActorLocation(), S->Spot);
				AddInfo(FString::Printf(TEXT("deck: W walked %.0f cm"), Moved));
				TestTrue(FString::Printf(TEXT("deck: W walks the Sovereign (%.0f cm)"), Moved), Moved > 50.0);
				Ui->SetGameSetting(TEXT("controls.sensitivity"), MakeShared<FJsonValueNumber>(2.0));
				Ui->SetGameSetting(TEXT("controls.invert_y"), MakeShared<FJsonValueBoolean>(true));
			}
			else if (S->Frames == 64)
			{
				AVerseDeckCamera* Camera = nullptr;
				for (TActorIterator<AVerseDeckCamera> It(World); It; ++It)
				{
					Camera = *It;
				}
				TestTrue(TEXT("deck: the options' sensitivity reaches the deck camera"), Camera && FMath::IsNearlyEqual(Camera->Rig.Sensitivity, 2.0));
				TestTrue(TEXT("deck: the options' invert Y reaches the deck camera"), Camera && Camera->Rig.bInvertY);
				Ui->SetGameSetting(TEXT("controls.sensitivity"), MakeShared<FJsonValueNumber>(1.0));
				Ui->SetGameSetting(TEXT("controls.invert_y"), MakeShared<FJsonValueBoolean>(false));
				Next();
			}
			return false;
		case 2:  // deck: B boards the hoverboard and leaves it, F holds the Arc Storm
		{
			AVerseDeckCommander* Commander = AVerseDeckCommander::Find(World);
			const UVerseHoverboardComponent* Board = Commander ? Commander->FindComponentByClass<UVerseHoverboardComponent>() : nullptr;
			const UVerseArcStormComponent* Arc = Commander ? Commander->FindComponentByClass<UVerseArcStormComponent>() : nullptr;
			++S->Frames;
			if (S->Frames == 1)
			{
				Feed(World, EKeys::B, IE_Pressed);
				Feed(World, EKeys::B, IE_Released);
			}
			else if (S->Frames == 20)
			{
				TestTrue(TEXT("deck: B puts the Sovereign on the hoverboard"), Board && Board->IsOn());
				Feed(World, EKeys::B, IE_Pressed);
				Feed(World, EKeys::B, IE_Released);
			}
			else if (S->Frames == 40)
			{
				TestTrue(TEXT("deck: B again steps off the hoverboard"), Board && !Board->IsOn());
				Feed(World, EKeys::F, IE_Pressed);
			}
			else if (S->Frames == 70)
			{
				TestTrue(TEXT("deck: F holds the Arc Storm"), Arc && Arc->IsHeld());
				Feed(World, EKeys::F, IE_Released);
			}
			else if (S->Frames == 100)
			{
				TestTrue(TEXT("deck: releasing F ends the Arc Storm"), Arc && !Arc->IsHeld());
				Ui->QuickStartDuel();
				Next();
			}
			return false;
		}
		case 3:  // Quick duel: the person stands in the arena with the rifle and a captured mouse
			if (Duel->IsDuelRunning() && Person && Inventory && !Deck->IsDeckActive() && ++S->Frames > 60)
			{
				ExpectDuelInput(TEXT("duel start"));
				TestEqual(TEXT("duel starts on the rifle"), Inventory->ActiveSlot, EVerseLoadoutSlot::Primary);
				S->Count = MagazineOf(EVerseLoadoutSlot::Primary);
				TestTrue(FString::Printf(TEXT("the rifle starts loaded (%d)"), S->Count), S->Count > 5);
				Feed(World, EKeys::LeftMouseButton, IE_Pressed);
				Next();
				S->Count = MagazineOf(EVerseLoadoutSlot::Primary);
			}
			return false;
		case 4:  // rifle: holding fire empties rounds
			if (++S->Frames == 20)
			{
				Feed(World, EKeys::LeftMouseButton, IE_Released);
			}
			else if (S->Frames == 30)
			{
				const int32 Left = MagazineOf(EVerseLoadoutSlot::Primary);
				FVerseDuelPlayerStats Me, Bot;
				Totals(Duel, PersonId(PC), Me, Bot);
				AddInfo(FString::Printf(TEXT("rifle: %d -> %d rounds, %d shots"), S->Count, Left, Me.Shots));
				TestTrue(FString::Printf(TEXT("rifle: holding fire spends rounds (%d -> %d)"), S->Count, Left), Left >= 0 && Left < S->Count);
				TestTrue(TEXT("rifle: the duel counts the shots"), Me.Shots > 0);
				S->Count = Left;
				Feed(World, EKeys::R, IE_Pressed);
				Feed(World, EKeys::R, IE_Released);
				Next();
			}
			return false;
		case 5:  // reload: R refills the magazine
		{
			const int32 Now = MagazineOf(EVerseLoadoutSlot::Primary);
			++S->Frames;
			if (S->Frames > 3 && !Inventory->bReloading && Now > S->Count)
			{
				AddInfo(FString::Printf(TEXT("reload: %d -> %d after %d frames"), S->Count, Now, S->Frames));
				Feed(World, EKeys::RightMouseButton, IE_Pressed);
				Next();
			}
			else if (S->Frames > 300)
			{
				return Fail(FString::Printf(TEXT("reload: R never refilled the rifle (%d rounds, reloading %d)"), Now, Inventory->bReloading ? 1 : 0));
			}
			return false;
		}
		case 6:  // aim: the right mouse button raises the sights, letting go lowers them
		{
			const UVerseWeaponComponent* Weapon = UVerseWeaponComponent::FindOn(Person);
			if (++S->Frames == 30)
			{
				TestTrue(FString::Printf(TEXT("aim: RMB aims down the sights (%.2f)"), Weapon ? Weapon->GetAdsBlend01() : -1.f), Weapon && Weapon->GetAdsBlend01() > 0.5f);
				Feed(World, EKeys::RightMouseButton, IE_Released);
			}
			else if (S->Frames == 60)
			{
				TestTrue(TEXT("aim: releasing RMB lowers the sights"), Weapon && Weapon->GetAdsBlend01() < 0.5f);
				Feed(World, EKeys::Two, IE_Pressed);
				Feed(World, EKeys::Two, IE_Released);
				Next();
			}
			return false;
		}
		case 7:  // 2: the pistol comes up and fires
			++S->Frames;
			if (S->Count == 0 && Inventory->ActiveSlot == EVerseLoadoutSlot::Secondary && Inventory->IsReady(Inventory->GetReadyAt()) && S->Frames > 30)
			{
				S->Count = MagazineOf(EVerseLoadoutSlot::Secondary);
				Feed(World, EKeys::LeftMouseButton, IE_Pressed);
				Feed(World, EKeys::LeftMouseButton, IE_Released);
				S->Frames = 1000;
			}
			else if (S->Frames == 1020)
			{
				const int32 Left = MagazineOf(EVerseLoadoutSlot::Secondary);
				TestTrue(FString::Printf(TEXT("pistol: a click fires one round (%d -> %d)"), S->Count, Left), Left == S->Count - 1);
				Feed(World, EKeys::Three, IE_Pressed);
				Feed(World, EKeys::Three, IE_Released);
				Next();
			}
			else if (S->Frames == 120)
			{
				return Fail(FString::Printf(TEXT("pistol: 2 did not bring the pistol up (slot %d)"), int32(Inventory->ActiveSlot)));
			}
			return false;
		case 8:  // 3: the knife; a click and V swing it
			if (++S->Frames == 40)
			{
				TestEqual(TEXT("knife: 3 brings the knife"), Inventory->ActiveSlot, EVerseLoadoutSlot::Melee);
				Feed(World, EKeys::LeftMouseButton, IE_Pressed);
				Feed(World, EKeys::LeftMouseButton, IE_Released);
			}
			else if (S->Frames == 80)
			{
				Feed(World, EKeys::V, IE_Pressed);
				Feed(World, EKeys::V, IE_Released);
			}
			else if (S->Frames == 120)
			{
				const UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Person);
				S->Count = Gadgets ? Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA) : -1;
				TestTrue(TEXT("Bulwark has charges"), S->Count > 0);
				Feed(World, EKeys::G, IE_Pressed);
				Feed(World, EKeys::G, IE_Released);
				Next();
			}
			return false;
		case 9:  // G: the Bulwark goes up; T: the breach charge
		{
			const UVerseGadgetComponent* Gadgets = UVerseGadgetComponent::FindOn(Person);
			++S->Frames;
			if (S->Frames == 90)
			{
				const int32 Left = Gadgets ? Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetA) : -1;
				TestTrue(FString::Printf(TEXT("Bulwark: G spends a charge (%d -> %d)"), S->Count, Left), Left == S->Count - 1);
				S->Count = Gadgets ? Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB) : -1;
				TestTrue(TEXT("breach charge has charges"), S->Count > 0);
				Feed(World, EKeys::T, IE_Pressed);
				Feed(World, EKeys::T, IE_Released);
			}
			else if (S->Frames == 180)
			{
				const int32 Left = Gadgets ? Gadgets->GetChargesLeft(EVerseLoadoutSlot::GadgetB) : -1;
				AddInfo(FString::Printf(TEXT("breach charge: %d -> %d, planted %d"), S->Count, Left, Gadgets ? Gadgets->NumPlantedCharges() : -1));
				TestTrue(FString::Printf(TEXT("breach charge: T spends a charge (%d -> %d)"), S->Count, Left), Left == S->Count - 1);
				Feed(World, EKeys::One, IE_Pressed);
				Feed(World, EKeys::One, IE_Released);
			}
			else if (S->Frames == 230)
			{
				TestEqual(TEXT("1 brings the rifle back"), Inventory->ActiveSlot, EVerseLoadoutSlot::Primary);
				SlateKey(EKeys::Escape);
				Next();
			}
			return false;
		}
		case 10:  // Escape: the menu frees the cursor and pauses; options and back
			if (++S->Frames == 4)
			{
				TestEqual(TEXT("Esc opens the menu"), Ui->GetScreen(), EVerseUiScreen::EscMenu);
				TestTrue(TEXT("the menu pauses the duel"), Ui->IsPausedByUi() && World->IsPaused());
				ExpectMenuInput(TEXT("Esc menu"));
				Ui->ShowScreen(EVerseUiScreen::Settings);
			}
			else if (S->Frames == 8)
			{
				ExpectMenuInput(TEXT("options"));
				SlateKey(EKeys::Escape);
			}
			else if (S->Frames == 12)
			{
				TestEqual(TEXT("Esc in the options goes back to the menu"), Ui->GetScreen(), EVerseUiScreen::EscMenu);
				SlateKey(EKeys::Escape);
			}
			else if (S->Frames == 16)
			{
				TestEqual(TEXT("Esc in the menu resumes"), Ui->GetScreen(), EVerseUiScreen::None);
				TestFalse(TEXT("resumed: not paused"), World->IsPaused());
				ExpectDuelInput(TEXT("resumed"));
				S->Look = PC->GetControlRotation();
			}
			else if (S->Frames > 16 && S->Frames <= 30)
			{
				Feed(World, EKeys::MouseX, IE_Axis, 6.f);
			}
			else if (S->Frames == 36)
			{
				const double Yaw = FMath::Abs(FRotator::NormalizeAxis(PC->GetControlRotation().Yaw - S->Look.Yaw));
				TestTrue(FString::Printf(TEXT("resumed: the mouse still turns the view (%.1f deg)"), Yaw), Yaw > 1.0);
				S->LookDeg = Yaw;
				SlateKey(EKeys::Tab);
			}
			else if (S->Frames == 40)
			{
				// Tab opens the bar in the duel: its entries (leave duel, back to app) need the cursor.
				TestTrue(TEXT("Tab opens the bar"), Ui->IsBarOpen());
				ExpectMenuInput(TEXT("bar in the duel"));
				SlateKey(EKeys::Tab);
			}
			else if (S->Frames == 44)
			{
				TestFalse(TEXT("Tab again closes the bar"), Ui->IsBarOpen());
				ExpectDuelInput(TEXT("bar closed"));
				// Options: mouse sensitivity 2.
				TestTrue(TEXT("sensitivity is a setting"), Ui->SetGameSetting(TEXT("controls.sensitivity"), MakeShared<FJsonValueNumber>(2.0)));
				S->Look = PC->GetControlRotation();
			}
			else if (S->Frames > 46 && S->Frames <= 60)
			{
				Feed(World, EKeys::MouseX, IE_Axis, 6.f);
			}
			else if (S->Frames == 66)
			{
				const double Yaw = FMath::Abs(FRotator::NormalizeAxis(PC->GetControlRotation().Yaw - S->Look.Yaw));
				AddInfo(FString::Printf(TEXT("options: the same mouse turns %.1f deg at sensitivity 1, %.1f deg at 2"), S->LookDeg, Yaw));
				TestTrue(FString::Printf(TEXT("options: sensitivity 2 turns faster (%.1f vs %.1f deg)"), Yaw, S->LookDeg), Yaw > 1.6 * S->LookDeg);
				Ui->SetGameSetting(TEXT("controls.sensitivity"), MakeShared<FJsonValueNumber>(1.0));
				S->Look = PC->GetControlRotation();
			}
			else if (S->Frames > 68 && S->Frames <= 76)
			{
				Feed(World, EKeys::MouseY, IE_Axis, 2.f);
			}
			else if (S->Frames == 80)
			{
				S->PitchDeg = FRotator::NormalizeAxis(PC->GetControlRotation().Pitch - S->Look.Pitch);
				Ui->SetGameSetting(TEXT("controls.invert_y"), MakeShared<FJsonValueBoolean>(true));
				S->Look = PC->GetControlRotation();
			}
			else if (S->Frames > 82 && S->Frames <= 90)
			{
				Feed(World, EKeys::MouseY, IE_Axis, 2.f);
			}
			else if (S->Frames == 94)
			{
				const double Pitch = FRotator::NormalizeAxis(PC->GetControlRotation().Pitch - S->Look.Pitch);
				AddInfo(FString::Printf(TEXT("options: mouse up pitches %.2f deg, inverted %.2f deg"), S->PitchDeg, Pitch));
				TestTrue(FString::Printf(TEXT("options: invert Y flips the pitch (%.2f then %.2f deg)"), S->PitchDeg, Pitch),
					FMath::Abs(S->PitchDeg) > 0.2 && FMath::Abs(Pitch) > 0.2 && FMath::Sign(Pitch) != FMath::Sign(S->PitchDeg));
				Ui->SetGameSetting(TEXT("controls.invert_y"), MakeShared<FJsonValueBoolean>(false));
				const UCameraComponent* Camera = Person->GetFirstPersonCamera();
				S->Fov = Camera ? Camera->FieldOfView : 0.f;
				Ui->SetGameSetting(TEXT("controls.fov_duel"), MakeShared<FJsonValueNumber>(S->Fov > 95.f ? 90.0 : 105.0));
			}
			else if (S->Frames == 98)
			{
				const UCameraComponent* Camera = Person->GetFirstPersonCamera();
				const float Want = S->Fov > 95.f ? 90.f : 105.f;
				TestTrue(FString::Printf(TEXT("options: the duel FOV follows the setting (%.1f, want %.1f)"), Camera ? Camera->FieldOfView : -1.f, Want),
					Camera && FMath::IsNearlyEqual(Camera->FieldOfView, Want, 0.5f));
				Ui->SetGameSetting(TEXT("controls.fov_duel"), MakeShared<FJsonValueNumber>(S->Fov));
				Next();
			}
			return false;
		case 11:  // the bot fights: a person who does nothing loses the set
			if (Ui->GetScreen() == EVerseUiScreen::EndOfSet)
			{
				const FVerseEndScreen& End = Ui->GetEndScreen();
				S->FirstOutcome = End.Outcome;
				AddInfo(FString::Printf(TEXT("set 1: %d - %d after %.0f s"), End.PersonKills, End.OpponentKills, Waited));
				TestEqual(TEXT("standing still loses the set to the bot"), End.Outcome, EVerseSetOutcome::Lost);
				TestTrue(TEXT("the end of set pauses"), World->IsPaused());
				ExpectMenuInput(TEXT("end of set"));
				Next();
			}
			else if (++S->Frames % 900 == 0)
			{
				FVerseDuelPlayerStats Me, Bot;
				Totals(Duel, PersonId(PC), Me, Bot);
				AddInfo(FString::Printf(TEXT("set 1 at %.0f s: bot %d shots %d hits %d kills"), Waited, Bot.Shots, Bot.Hits, Bot.Kills));
				if (Bot.Shots == 0 && Waited > 60.0)
				{
					return Fail(TEXT("the bot has not fired a shot in a minute"));
				}
			}
			return false;
		case 12:  // next set: the game takes the mouse back
			if (++S->Frames == 30)
			{
				Ui->ContinueAfterSet();
			}
			else if (S->Frames == 40)
			{
				TestFalse(TEXT("next set: not paused"), World->IsPaused());
				ExpectDuelInput(TEXT("next set"));
				Duel->SetAutoplay(true);
				Next();
			}
			return false;
		case 13:  // autoplay plays a set out (win or lose)
			if (Ui->GetScreen() == EVerseUiScreen::EndOfSet)
			{
				Duel->SetAutoplay(false);
				const FVerseEndScreen& End = Ui->GetEndScreen();
				AddInfo(FString::Printf(TEXT("set 2 (autoplay): %s %d - %d"), End.Outcome == EVerseSetOutcome::Won ? TEXT("won") : TEXT("lost"),
					End.PersonKills, End.OpponentKills));
				TestTrue(TEXT("set 2 ends won or lost"), End.Outcome != EVerseSetOutcome::Unfinished);
				TestEqual(TEXT("set 2 is the second set"), End.SetIndex, 2);
				Next();
			}
			return false;
		case 14:  // leave from the end of set, rematch from the summary
			if (++S->Frames == 10)
			{
				Ui->LeaveDuel();
			}
			else if (S->Frames == 20)
			{
				TestEqual(TEXT("leaving shows the session summary"), Ui->GetScreen(), EVerseUiScreen::SessionSummary);
				TestFalse(TEXT("left: the duel is over"), Duel->IsDuelRunning());
				TestFalse(TEXT("left: not paused"), World->IsPaused());
				TestEqual(TEXT("the summary counts two sets"), Ui->GetSessionScreen().SetIndex, 2);
				ExpectMenuInput(TEXT("session summary"));
				Ui->QuickStartDuel();
			}
			else if (S->Frames > 20 && Duel->IsDuelRunning() && Person && ++S->Count == 60)
			{
				ExpectDuelInput(TEXT("rematch"));
				TestEqual(TEXT("rematch: the rifle again"), Inventory ? Inventory->ActiveSlot : EVerseLoadoutSlot::Melee, EVerseLoadoutSlot::Primary);
				SlateKey(EKeys::Escape);
				Next();
			}
			return false;
		case 15:  // leave mid-set from the menu; the summary's leave brings back the deck
			if (++S->Frames == 5)
			{
				TestEqual(TEXT("Esc opens the menu in the rematch"), Ui->GetScreen(), EVerseUiScreen::EscMenu);
				Ui->LeaveDuel();
			}
			else if (S->Frames == 15)
			{
				TestTrue(TEXT("leaving mid-set is reported"), Ui->GetSession().bLeftMidSet);
				Ui->ShowScreen(EVerseUiScreen::None);
			}
			else if (S->Frames > 15 && Deck && Deck->IsDeckActive() && ++S->Count == 30)
			{
				TestFalse(TEXT("back on the deck: not paused"), World->IsPaused());
				TestEqual(TEXT("back on the deck: the hangar"), Decks->GetCurrentDeck(), FName(TEXT("hangar")));
				TestTrue(TEXT("back on the deck: free cursor"), Deck->GetMouseMode() == EVerseDeckMouseMode::Free && PC->ShouldShowMouseCursor());
				S->DeckIndex = 0;
				Next();
			}
			return false;
		case 16:  // every other deck by the bar
		{
			static const FName Route[] = {TEXT("bridge"), TEXT("ops"), TEXT("engineering")};
			const FName Want = Route[S->DeckIndex];
			if (++S->Frames == 1)
			{
				Ui->TravelToDeck(Want);
			}
			else if (Decks->GetCurrentDeck() == Want && Deck && Deck->IsDeckActive() && Deck->GetDeck() == Want && AVerseDeckCommander::Find(World))
			{
				if (++S->Count == 60)
				{
					AddInfo(FString::Printf(TEXT("deck %s up after %.1f s"), *Want.ToString(), Waited));
					Deck->WindowFocused = []() { return true; };
					TestEqual(FString::Printf(TEXT("%s: no screen open"), *Want.ToString()), Ui->GetScreen(), EVerseUiScreen::None);
					TestFalse(FString::Printf(TEXT("%s: not paused"), *Want.ToString()), World->IsPaused());
					TestTrue(FString::Printf(TEXT("%s: cursor shown"), *Want.ToString()), PC->ShouldShowMouseCursor());
					Deck->PickView(EVerseDeckView::Third);
					S->Spot = AVerseDeckCommander::Find(World)->GetActorLocation();
					Feed(World, EKeys::W, IE_Pressed);
				}
				else if (S->Count == 100)
				{
					Feed(World, EKeys::W, IE_Released);
				}
				else if (S->Count == 115)
				{
					const double Moved = FVector::Dist2D(AVerseDeckCommander::Find(World)->GetActorLocation(), S->Spot);
					TestTrue(FString::Printf(TEXT("%s: W walks (%.0f cm)"), *Want.ToString(), Moved), Moved > 30.0);
					if (++S->DeckIndex == UE_ARRAY_COUNT(Route))
					{
						Next();
					}
					else
					{
						S->Frames = 0;
						S->Count = 0;
						S->Since = FPlatformTime::Seconds();
					}
				}
			}
			return false;
		}
		case 17:  // Quick duel on another deck: the person goes down to the hangar and duels there
			if (++S->Frames == 1)
			{
				Ui->QuickStartDuel();
			}
			else if (Duel->IsDuelRunning() && Person && Decks->GetCurrentDeck() == FName(TEXT("hangar")) && ++S->Count == 60)
			{
				TestTrue(TEXT("quick duel from engineering: the duel runs in the hangar level"),
					World->GetOutermost()->GetName().Contains(TEXT("LV_Hangar")));
				ExpectDuelInput(TEXT("quick duel from engineering"));
				Ui->LeaveDuel();
				Ui->ShowScreen(EVerseUiScreen::None);
				Next();
			}
			else if (S->Frames == 1800 && !Duel->IsDuelRunning())
			{
				return Fail(FString::Printf(TEXT("quick duel from engineering: no duel after 1800 frames (deck %s)"), *Decks->GetCurrentDeck().ToString()));
			}
			return false;
		case 18:  // back on the hangar deck view
			if (Deck && Deck->IsDeckActive() && ++S->Count == 30)
			{
				TestEqual(TEXT("after the cross-deck duel: the hangar"), Decks->GetCurrentDeck(), FName(TEXT("hangar")));
				TestFalse(TEXT("after the cross-deck duel: not paused"), World->IsPaused());
				Next();
			}
			return false;
		case 19:  // back to the app (no app in the test: the bridge port only logs it)
			Ui->ReturnToApp(TEXT("playtest"));
			return Finish();
		default:
			return Finish();
		}
	}));
	return true;
}

// Verse.Visual.AppLink: the UI's link to the app in the running game, through the real bridge
// subsystem. A settings.changed frame re-texts the UI; "Back to app" from the menu hands the
// window back (the lifecycle leaves Visible); the app's Quick duel (lifecycle.show with reason
// quick_start_duel) starts the duel.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseVisualAppLinkTest, "Verse.Visual.AppLink", EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

bool FVerseVisualAppLinkTest::RunTest(const FString&)
{
	using namespace VersePlaytest;
	if (!FApp::CanEverRender())
	{
		AddWarning(TEXT("Verse.Visual.AppLink needs a game viewport (run it through scripts/unreal/screenshot.py)"));
		return true;
	}
	TSharedRef<FState> S = MakeShared<FState>();
	S->Since = FPlatformTime::Seconds();
	ADD_LATENT_AUTOMATION_COMMAND(FFunctionLatentCommand([this, S]() -> bool
	{
		UWorld* World = GameWorld();
		UVerseDeckControlComponent* Deck = UVerseDeckControlComponent::Get(World);
		UVerseDuelSubsystem* Duel = UVerseDuelSubsystem::Get(World);
		UVerseUiSubsystem* Ui = UVerseUiSubsystem::Get(World);
		UVerseBridgeSubsystem* Bridge = BridgeOf(World);
		auto Next = [&S]() { ++S->Phase; S->Frames = 0; S->Since = FPlatformTime::Seconds(); };
		if (FPlatformTime::Seconds() - S->Since > 120.0)
		{
			AddError(FString::Printf(TEXT("phase %d timed out"), S->Phase));
			return true;
		}
		if (!Duel || !Ui || !Bridge)
		{
			return false;
		}
		FVerseLifecycleController& Lifecycle = Bridge->Lifecycle();
		switch (S->Phase)
		{
		case 0:  // the hangar deck is up; the app shows the window
			if (Deck && Deck->IsDeckActive() && ShadersDone() && ++S->Frames > 20)
			{
				Lifecycle.HandleFrame(FVerseBridgeFrame::Make(TEXT("lifecycle.show"), Json(OffscreenShow)));
				Next();
			}
			return false;
		case 1:  // settings.changed from the app re-texts the UI; Back to app; the app's Quick duel
			if (++S->Frames == 2)
			{
				Bridge->Client().OnFrame.Broadcast(FVerseBridgeFrame::Make(TEXT("settings.changed"), Json(TEXT("{\"lang\":\"de\"}"))));
			}
			else if (S->Frames == 4)
			{
				TestEqual(TEXT("settings.changed reaches the UI"), Ui->GetStrings().GetLanguage(), FString(TEXT("de")));
				Bridge->Client().OnFrame.Broadcast(FVerseBridgeFrame::Make(TEXT("settings.changed"), Json(TEXT("{\"lang\":\"en\"}"))));
				Ui->ShowScreen(EVerseUiScreen::EscMenu);
			}
			else if (S->Frames == 6)
			{
				TestEqual(TEXT("the window is visible before Back to app"), Lifecycle.GetState(), EVerseLifecycleState::Visible);
				// The menu's "Back to app" button.
				Ui->ReturnToApp(TEXT("esc_menu"));
			}
			else if (S->Frames == 8)
			{
				TestNotEqual(TEXT("Back to app hands the window to the app"), Lifecycle.GetState(), EVerseLifecycleState::Visible);
				Ui->ShowScreen(EVerseUiScreen::None);
				// The app's Quick duel button.
				Lifecycle.HandleFrame(FVerseBridgeFrame::Make(TEXT("lifecycle.show"), Json(QuickDuelShow)));
				Next();
			}
			return false;
		case 2:  // the app's Quick duel starts the duel
			if (Duel->IsDuelRunning() && ++S->Frames == 30)
			{
				Duel->LeaveDuel();
				Ui->ShowScreen(EVerseUiScreen::None);
				return true;
			}
			return false;
		default:
			return true;
		}
	}));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

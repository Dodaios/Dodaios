#include "Decks/VerseDeckManifest.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Engine/GameInstance.h"
#include "HAL/IConsoleManager.h"
#include "Misc/AutomationTest.h"
#include "QA/VerseDecksOverlay.h"
#include "UObject/Package.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Parity.Q.09 (-VerseDeck=<id>) and Q.11 (alignment overlay): parity.md section 19.

#define VERSE_DECKS_QA_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ09DeckSwitch, "Verse.Parity.Q.09", VERSE_DECKS_QA_TEST_FLAGS)
bool FVerseParityQ09DeckSwitch::RunTest(const FString&)
{
#if UE_BUILD_SHIPPING
	TestEqual(TEXT("Shipping ignores the switch"), UVerseDeckSubsystem::ParseStartupDeck(TEXT("-VerseDeck=hangar")), FName(NAME_None));
#else
	for (const TCHAR* Deck : {TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar")})
	{
		const FString Line = FString::Printf(TEXT("Verse.exe -windowed -VerseDeck=%s -log"), Deck);
		TestEqual(*FString::Printf(TEXT("-VerseDeck=%s picks the deck"), Deck), UVerseDeckSubsystem::ParseStartupDeck(*Line), FName(Deck));
	}
	TestEqual(TEXT("an unknown deck is ignored"), UVerseDeckSubsystem::ParseStartupDeck(TEXT("-VerseDeck=nowhere")), FName(NAME_None));
	TestEqual(TEXT("no switch, no override"), UVerseDeckSubsystem::ParseStartupDeck(TEXT("-windowed -log")), FName(NAME_None));
#endif
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseParityQ11Overlay, "Verse.Parity.Q.11", VERSE_DECKS_QA_TEST_FLAGS)
bool FVerseParityQ11Overlay::RunTest(const FString&)
{
	FVerseDeckManifest Hangar;
	FString Error;
	if (!TestTrue(*FString::Printf(TEXT("hangar manifest loads (%s)"), *Error), FVerseDeckManifest::Load(TEXT("hangar"), Verse::Decks::PlacementsDir(), Hangar, Error)))
	{
		return false;
	}
	const VerseDecksOverlay::FCounts Counts = VerseDecksOverlay::Count(Hangar);
	TestEqual(TEXT("one polygon per room"), Counts.Rooms, Hangar.Rooms.Num());
	TestEqual(TEXT("one marker per station"), Counts.Stations, Hangar.Stations.Num());
	TestEqual(TEXT("every socket is a waypoint or a socket marker"), Counts.Waypoints + Counts.Sockets, Hangar.Sockets.Num());
	TestTrue(TEXT("the hangar has rooms and stations to align"), Counts.Rooms > 0 && Counts.Stations > 0);

#if !UE_BUILD_SHIPPING
	UGameInstance* Instance = NewObject<UGameInstance>(GetTransientPackage());
	UVerseDeckSubsystem* Decks = NewObject<UVerseDeckSubsystem>(Instance);
	VerseDecksOverlay::Install(*Decks);
	IConsoleManager& Console = IConsoleManager::Get();
	TestNotNull(TEXT("Verse.Debug.Overlay is a console command"), Console.FindConsoleObject(TEXT("Verse.Debug.Overlay")));

	TestFalse(TEXT("off by default"), VerseDecksOverlay::IsOn());
	Console.ProcessUserConsoleInput(TEXT("Verse.Debug.Overlay on"), *GLog, nullptr);
	TestTrue(TEXT("'on' turns it on"), VerseDecksOverlay::IsOn());
	Console.ProcessUserConsoleInput(TEXT("Verse.Debug.Overlay"), *GLog, nullptr);
	TestFalse(TEXT("no argument toggles"), VerseDecksOverlay::IsOn());
	Console.ProcessUserConsoleInput(TEXT("Verse.Debug.Overlay on"), *GLog, nullptr);
	Console.ProcessUserConsoleInput(TEXT("Verse.Debug.Overlay off"), *GLog, nullptr);
	TestFalse(TEXT("'off' turns it off"), VerseDecksOverlay::IsOn());
	TestTrue(TEXT("state reports the flag"), VerseDecksOverlay::StateJson(*Decks).Contains(TEXT("\"on\":false")));

	VerseDecksOverlay::SetOn(true);
	VerseDecksOverlay::Remove(*Decks);
	TestFalse(TEXT("removing the owner turns it off"), VerseDecksOverlay::IsOn());
	TestNull(TEXT("and removes the command"), Console.FindConsoleObject(TEXT("Verse.Debug.Overlay")));
#endif
	return true;
}

#endif

#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/PackageName.h"
#include "Misc/Paths.h"
#include "Tests/Tiers/VerseBotTierTestUtil.h"
#include "Tiers/VerseBotTierData.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Bot.Tiers.*: tiers as data (bot.md 9.1, WP09.1): the strict JSON reader, the floor and cap
// validation, and the CI diff of the generated assets against the JSON.

#define VERSE_BOT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseBotTiersTest
{
	FString ReadDataFile(const TCHAR* Name)
	{
		FString Text;
		FFileHelper::LoadFileToString(Text, *FPaths::Combine(VerseBotTierData::DefaultDataDir(), Name));
		return Text;
	}

	/** Errors of tiers.json after replacing one exact substring. */
	TArray<FString> TierErrorsWith(const FString& From, const FString& To)
	{
		FString Text = ReadDataFile(TEXT("tiers.json"));
		Text.ReplaceInline(*From, *To, ESearchCase::CaseSensitive);
		TArray<FString> Errors;
		TMap<FName, UVerseBotTier*> Tiers;
		VerseBotTierData::ReadTiers(Text, nullptr, Tiers, Errors);
		return Errors;
	}

	TArray<FString> AdaptiveErrorsWith(const FString& From, const FString& To)
	{
		FString Text = ReadDataFile(TEXT("adaptive.json"));
		Text.ReplaceInline(*From, *To, ESearchCase::CaseSensitive);
		TArray<FString> Errors;
		UVerseBotAdaptiveConfig* Config = nullptr;
		VerseBotTierData::ReadAdaptive(Text, nullptr, Config, Errors);
		return Errors;
	}

	bool AnyContains(const TArray<FString>& Errors, const TCHAR* Needle)
	{
		for (const FString& E : Errors)
		{
			if (E.Contains(Needle)) return true;
		}
		return false;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotTiersImportTest, "Verse.Bot.Tiers.Import", VERSE_BOT_TEST_FLAGS)
bool FVerseBotTiersImportTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotTiersTest;
	VerseBotTierTest::FTierSet Set = VerseBotTierTest::LoadTierSet();
	for (const FString& Error : Set.Errors) AddError(Error);
	if (!Set.IsValid())
	{
		return false;
	}
	TestTrue(TEXT("normal id"), Set.Normal->TierId == FName(TEXT("normal")));
	TestTrue(TEXT("elite id"), Set.Elite->TierId == FName(TEXT("elite")));
	TestTrue(TEXT("every tier inside the contract"),
		Set.Normal->SatisfiesContractBounds() && Set.Hard->SatisfiesContractBounds() && Set.Elite->SatisfiesContractBounds());

	// The JSON reads every field: spot checks across groups and types against the file.
	TestTrue(TEXT("float pair"), Set.Hard->ReactionMs == FVector2f(270.f, 50.f));
	TestEqual(TEXT("int"), Set.Elite->MaxBurstShots, 4);
	TestEqual(TEXT("learning"), Set.Elite->LearnWeightMax, 0.35f);

	// Today's tiers.json holds the contract start values (bot.md 9.1); a retune changes both together.
	for (const FName Id : VerseBotTierData::TierIds())
	{
		TStrongObjectPtr<UVerseBotTier> Start(NewObject<UVerseBotTier>());
		UVerseBotTier::ApplyStartValues(Id, *Start);
		const TArray<FString> Diffs = VerseBotTierData::DiffObjects(*Start, *Set.Get(Id));
		for (const FString& Diff : Diffs)
		{
			AddInfo(FString::Printf(TEXT("%s differs from the contract start value: %s"), *Id.ToString(), *Diff));
		}
	}

	// Strictness: a missing, unknown or mistyped field is an error; so is a wrong schema.
	TestTrue(TEXT("missing field"), AnyContains(TierErrorsWith(TEXT("\"AimNoiseRate\": 1.6,"), TEXT("")), TEXT("normal.AimNoiseRate: missing")));
	TestTrue(TEXT("unknown field"),
		AnyContains(TierErrorsWith(TEXT("\"AimNoiseRate\": 1.6,"), TEXT("\"AimNoiseRate\": 1.6, \"Wallhack\": 1.0,")), TEXT("normal.Wallhack: unknown field")));
	TestTrue(TEXT("wrong type"), AnyContains(TierErrorsWith(TEXT("\"MaxBurstShots\": 8"), TEXT("\"MaxBurstShots\": 8.5")), TEXT("expected an integer")));
	TestTrue(TEXT("wrong pair"), AnyContains(TierErrorsWith(TEXT("[320.0, 60.0]"), TEXT("320.0")), TEXT("expected a pair")));
	TestTrue(TEXT("wrong schema"), AnyContains(TierErrorsWith(TEXT("verse.bot.tiers/1"), TEXT("verse.bot.tiers/2")), TEXT("schema")));
	TestTrue(TEXT("missing tier"), AnyContains(TierErrorsWith(TEXT("\"elite\""), TEXT("\"legend\"")), TEXT("missing tier \"elite\"")));
	TestTrue(TEXT("not JSON"), AnyContains(TierErrorsWith(TEXT("{"), TEXT("")), TEXT("not valid JSON")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotTiersFloorsTest, "Verse.Bot.Tiers.FloorsAndCaps", VERSE_BOT_TEST_FLAGS)
bool FVerseBotTiersFloorsTest::RunTest(const FString& Parameters)
{
	using namespace VerseBotTiersTest;
	TestTrue(TEXT("WallbangMinBelief floor 0.25"),
		AnyContains(TierErrorsWith(TEXT("\"WallbangMinBelief\": 0.3,"), TEXT("\"WallbangMinBelief\": 0.2,")), TEXT("below the contract floor")));
	TestTrue(TEXT("WallbangMaxSourceAgeS cap 4"),
		AnyContains(TierErrorsWith(TEXT("\"WallbangMaxSourceAgeS\": 3.5,"), TEXT("\"WallbangMaxSourceAgeS\": 4.5,")), TEXT("above the contract cap")));
	TestTrue(TEXT("LearnWeightMax cap 0.35"),
		AnyContains(TierErrorsWith(TEXT("\"LearnWeightMax\": 0.35,"), TEXT("\"LearnWeightMax\": 0.4,")), TEXT("above the contract cap")));
	TestTrue(TEXT("probabilities stay in [0, 1]"),
		AnyContains(TierErrorsWith(TEXT("\"HeadAimChance\": 0.35,"), TEXT("\"HeadAimChance\": 1.2,")), TEXT("HeadAimChance")));
	TestTrue(TEXT("turn rate positive"),
		AnyContains(TierErrorsWith(TEXT("\"TurnRateDegS\": 850.0,"), TEXT("\"TurnRateDegS\": 0.0,")), TEXT("TurnRateDegS")));
	TestTrue(TEXT("the edge values themselves pass"),
		TierErrorsWith(TEXT("\"WallbangMinBelief\": 0.3,"), TEXT("\"WallbangMinBelief\": 0.25,")).Num() == 0);

	TestEqual(TEXT("adaptive.json reads clean"), AdaptiveErrorsWith(TEXT("schema"), TEXT("schema")).Num(), 0);
	TestTrue(TEXT("adaptive step cap 0.05"),
		AnyContains(AdaptiveErrorsWith(TEXT("\"MaxStepPerKill\": 0.05"), TEXT("\"MaxStepPerKill\": 0.06")), TEXT("MaxStepPerKill")));
	TestTrue(TEXT("adaptive start in [0, 1]"),
		AnyContains(AdaptiveErrorsWith(TEXT("\"StartSkill\": 0.5"), TEXT("\"StartSkill\": 1.5")), TEXT("StartSkill")));
	TestTrue(TEXT("adaptive applies at respawn only"),
		AnyContains(AdaptiveErrorsWith(TEXT("bot_respawn"), TEXT("every_kill")), TEXT("ApplyAt")));
	TestTrue(TEXT("adaptive unknown field"),
		AnyContains(AdaptiveErrorsWith(TEXT("\"Gain\": 0.25,"), TEXT("\"Gain\": 0.25, \"Boost\": 2,")), TEXT("unknown field")));
	return true;
}

// The CI diff check (WP09.1): the committed assets hold exactly what the JSON says.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseBotTiersAssetsTest, "Verse.Bot.Tiers.AssetsMatchJson", VERSE_BOT_TEST_FLAGS)
bool FVerseBotTiersAssetsTest::RunTest(const FString& Parameters)
{
	VerseBotTierTest::FTierSet Set = VerseBotTierTest::LoadTierSet();
	for (const FString& Error : Set.Errors) AddError(Error);
	if (!Set.IsValid())
	{
		return false;
	}
	auto Check = [this](const FString& PackagePath, UClass* Class, const UObject& FromJson)
	{
		const FString ObjectPath = PackagePath + TEXT(".") + VerseBotTierData::ObjectNameOf(PackagePath);
		const UObject* Asset = FPackageName::DoesPackageExist(PackagePath) ? StaticLoadObject(Class, nullptr, *ObjectPath) : nullptr;
		if (!TestNotNull(FString::Printf(TEXT("%s exists (run -run=VerseImportBotTiers)"), *PackagePath), Asset))
		{
			return;
		}
		const TArray<FString> Diffs = VerseBotTierData::DiffObjects(*Asset, FromJson);
		for (const FString& Diff : Diffs)
		{
			AddError(FString::Printf(TEXT("%s differs from the JSON: %s (run -run=VerseImportBotTiers and commit)"), *PackagePath, *Diff));
		}
	};
	for (const FName Id : VerseBotTierData::TierIds())
	{
		Check(VerseBotTierData::TierPackagePath(Id), UVerseBotTier::StaticClass(), *Set.Get(Id));
	}
	Check(VerseBotTierData::AdaptivePackagePath(), UVerseBotAdaptiveConfig::StaticClass(), *Set.Adaptive);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

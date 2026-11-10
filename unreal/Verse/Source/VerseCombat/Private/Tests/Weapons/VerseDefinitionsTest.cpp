#include "Dom/JsonValue.h"
#include "Misc/AutomationTest.h"
#include "Serialization/JsonReader.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Definitions.*: the JSON text surface and the DA_Weapon_* / DA_Gadget_* assets are
// field-for-field equal, every field is required, unknown fields and bad names are refused (WP02.1,
// WP02.14), and the gadget start values are those of combat-state.md 2.3.

namespace VerseDefinitionsTest
{
	TSharedPtr<FJsonValue> ReadFile(FAutomationTestBase& Test, const FString& Path)
	{
		FString Text;
		if (!Test.TestTrue(FString::Printf(TEXT("read %s"), *Path), FFileHelper::LoadFileToString(Text, *Path)))
		{
			return nullptr;
		}
		TSharedPtr<FJsonObject> Obj;
		const TSharedRef<TJsonReader<TCHAR>> Reader = TJsonReaderFactory<TCHAR>::Create(Text);
		FJsonSerializer::Deserialize(Reader, Obj);
		return Obj.IsValid() ? TSharedPtr<FJsonValue>(MakeShared<FJsonValueObject>(Obj)) : TSharedPtr<FJsonValue>();
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDefinitionsImportDiff, "Verse.Combat.Definitions.ImportDiff", VERSE_WP02_TEST_FLAGS)
bool FVerseDefinitionsImportDiff::RunTest(const FString&)
{
	const TArray<const UVerseWeaponDefinition*> Weapons = VerseWp02Test::AllWeapons(*this);
	TSet<FName> Ids;
	for (const UVerseWeaponDefinition* W : Weapons)
	{
		Ids.Add(W->WeaponId);
		const FString File = FPaths::Combine(FVerseDefinitionJson::DataDir(), W->WeaponId.ToString() + TEXT(".json"));
		const TSharedPtr<FJsonValue> OnDisk = VerseDefinitionsTest::ReadFile(*this, File);
		TArray<FString> Diffs;
		FVerseDefinitionJson::JsonEqual(OnDisk, MakeShared<FJsonValueObject>(FVerseDefinitionJson::ExportWeapon(*W)), W->WeaponId.ToString(), Diffs);
		for (const FString& D : Diffs)
		{
			AddError(TEXT("json round trip: ") + D);
		}
	}
	for (const TCHAR* Id : {TEXT("graveline"), TEXT("tallow"), TEXT("skitter"), TEXT("longsight")})
	{
		TestTrue(FString::Printf(TEXT("%s.json present"), Id), Ids.Contains(FName(Id)));
	}

	// The two start assets exist and match their JSON field for field.
	for (const TCHAR* Id : {TEXT("graveline"), TEXT("tallow"), TEXT("skitter"), TEXT("longsight")})
	{
		const UVerseWeaponDefinition* Asset = FVerseWeaponRegistry::LoadWeaponAsset(FName(Id));
		if (!TestNotNull(FString::Printf(TEXT("%s asset exists"), *FVerseDefinitionJson::WeaponAssetName(FName(Id))), Asset))
		{
			continue;
		}
		const TSharedPtr<FJsonValue> OnDisk = VerseDefinitionsTest::ReadFile(*this, FPaths::Combine(FVerseDefinitionJson::DataDir(), FString(Id) + TEXT(".json")));
		TArray<FString> Diffs;
		FVerseDefinitionJson::JsonEqual(OnDisk, MakeShared<FJsonValueObject>(FVerseDefinitionJson::ExportWeapon(*Asset)), Id, Diffs);
		for (const FString& D : Diffs)
		{
			AddError(TEXT("asset drift: ") + D);
		}
	}
	for (const TCHAR* Id : {TEXT("bulwark"), TEXT("breach_charge")})
	{
		TestNotNull(FString::Printf(TEXT("%s asset exists"), *FVerseDefinitionJson::GadgetAssetName(FName(Id))),
			FVerseWeaponRegistry::LoadGadgetAsset(FName(Id)));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDefinitionsStrict, "Verse.Combat.Definitions.Strict", VERSE_WP02_TEST_FLAGS)
bool FVerseDefinitionsStrict::RunTest(const FString&)
{
	const UVerseWeaponDefinition* Graveline = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!Graveline)
	{
		return false;
	}
	const TSharedRef<FJsonObject> Good = FVerseDefinitionJson::ExportWeapon(*Graveline);
	{
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>();
		TArray<FString> Errors;
		TestTrue(TEXT("canonical export imports"), FVerseDefinitionJson::ApplyWeapon(*Good, *W, Errors));
	}
	{
		TSharedRef<FJsonObject> Missing = MakeShared<FJsonObject>(*Good);
		Missing->RemoveField(TEXT("RPM"));
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>();
		TArray<FString> Errors;
		TestFalse(TEXT("a missing field is refused"), FVerseDefinitionJson::ApplyWeapon(*Missing, *W, Errors));
	}
	{
		TSharedRef<FJsonObject> Extra = MakeShared<FJsonObject>(*Good);
		Extra->SetNumberField(TEXT("Velocity"), 1.0);
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>();
		TArray<FString> Errors;
		TestFalse(TEXT("an unknown field is refused"), FVerseDefinitionJson::ApplyWeapon(*Extra, *W, Errors));
	}
	{
		TSharedRef<FJsonObject> BadEnum = MakeShared<FJsonObject>(*Good);
		BadEnum->SetStringField(TEXT("FireMode"), TEXT("Rapid"));
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>();
		TArray<FString> Errors;
		TestFalse(TEXT("an unknown enum entry is refused"), FVerseDefinitionJson::ApplyWeapon(*BadEnum, *W, Errors));
	}
	{
		TSharedRef<FJsonObject> Cap = MakeShared<FJsonObject>(*Good);
		Cap->SetNumberField(TEXT("MaxPenetrations"), 4);
		UVerseWeaponDefinition* W = NewObject<UVerseWeaponDefinition>();
		TArray<FString> Errors;
		TestFalse(TEXT("MaxPenetrations above 3 is refused"), FVerseDefinitionJson::ApplyWeapon(*Cap, *W, Errors));
	}
	TArray<FString> NameErrors;
	TestTrue(TEXT("fictional names pass the format"), FVerseDefinitionJson::CheckNames(TEXT("graveline"), FText::FromString(TEXT("Graveline")), NameErrors));
	TestFalse(TEXT("upper-case ids are refused"), FVerseDefinitionJson::CheckNames(TEXT("Grave"), FText::FromString(TEXT("Grave")), NameErrors));
	TestFalse(TEXT("model-number punctuation is refused"), FVerseDefinitionJson::CheckNames(TEXT("x"), FText::FromString(TEXT("X/9")), NameErrors));
	TestEqual(TEXT("asset name"), FVerseDefinitionJson::GadgetAssetName(TEXT("breach_charge")), FString(TEXT("DA_Gadget_BreachCharge")));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDefinitionsStartValues, "Verse.Combat.Definitions.StartValues", VERSE_WP02_TEST_FLAGS)
bool FVerseDefinitionsStartValues::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseWeaponDefinition* T = VerseWp02Test::Weapon(*this, TEXT("tallow"));
	const UVerseGadgetDefinition* B = VerseWp02Test::Gadget(*this, TEXT("bulwark"));
	const UVerseGadgetDefinition* C = VerseWp02Test::Gadget(*this, TEXT("breach_charge"));
	if (!G || !T || !B || !C)
	{
		return false;
	}
	// combat-state.md 3.1 (the fields the acceptance rows depend on).
	TestEqual(TEXT("Graveline RPM"), G->RPM, 690.f);
	TestEqual(TEXT("Graveline magazine"), G->MagazineSize, 30);
	TestEqual(TEXT("Graveline base damage"), G->BaseDamage, 28.f);
	TestEqual(TEXT("Graveline muzzle velocity"), G->ProjectileSpeed, 880.f);
	TestEqual(TEXT("Graveline power"), G->PenetrationPower, 100.f);
	TestEqual(TEXT("Tallow RPM"), T->RPM, 380.f);
	TestEqual(TEXT("Tallow fire mode"), T->FireMode, EVerseFireMode::Semi);
	TestEqual(TEXT("Tallow power"), T->PenetrationPower, 50.f);
	TestEqual(TEXT("Tallow passes"), T->MaxPenetrations, 2);
	TestEqual(TEXT("Graveline slot"), G->Slot, EVerseLoadoutSlot::Primary);
	TestEqual(TEXT("Tallow slot"), T->Slot, EVerseLoadoutSlot::Secondary);

	// combat-state.md 2.3.
	TestEqual(TEXT("Bulwark charges"), B->Charges, 1);
	TestEqual(TEXT("Bulwark cooldown"), B->Cooldown, 20.f);
	TestEqual(TEXT("Bulwark use time"), B->UseTime, 0.6f);
	TestEqual(TEXT("Bulwark lifetime"), B->Lifetime, 25.f);
	TestEqual(TEXT("Bulwark health"), B->MaxHealth, 400.f);
	TestTrue(TEXT("Bulwark size"), B->Size.Equals(FVector3f(1.8f, 1.4f, 0.1f), 1e-6f));
	TestEqual(TEXT("Breach charges"), C->Charges, 2);
	TestEqual(TEXT("Breach fuse"), C->Lifetime, 2.5f);
	TestEqual(TEXT("Breach pawn damage"), C->PawnDamage, 120.f);
	TestEqual(TEXT("Breach pawn radius"), C->PawnRadius, 3.f);
	TestEqual(TEXT("Breach piece radius"), C->PieceBreachRadius, 150.f);
	TestTrue(TEXT("Breach self damage"), C->bSelfDamage);
	return true;
}

// Ballistics decision: real muzzle velocities per weapon class, tracers only on every Nth round and
// on the last rounds of a magazine.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseDefinitionsBallistics, "Verse.Combat.Definitions.Ballistics", VERSE_WP02_TEST_FLAGS)
bool FVerseDefinitionsBallistics::RunTest(const FString&)
{
	struct FWant
	{
		const TCHAR* Id;
		float MinMps;
		float MaxMps;
	};
	for (const FWant& Want : {FWant{TEXT("tallow"), 340.f, 420.f}, FWant{TEXT("skitter"), 380.f, 450.f},
			 FWant{TEXT("graveline"), 840.f, 920.f}, FWant{TEXT("longsight"), 900.f, 1000.f}})
	{
		const UVerseWeaponDefinition* W = VerseWp02Test::Weapon(*this, Want.Id);
		if (!W)
		{
			continue;
		}
		TestTrue(FString::Printf(TEXT("%s muzzle velocity %.0f m/s in [%.0f, %.0f]"), Want.Id, W->ProjectileSpeed, Want.MinMps, Want.MaxMps),
			W->ProjectileSpeed >= Want.MinMps && W->ProjectileSpeed <= Want.MaxMps);
	}
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	if (!G)
	{
		return false;
	}
	int32 Tracers = 0;
	for (int32 Counter = 1; Counter <= 20; ++Counter)
	{
		Tracers += G->IsTracerRound(Counter, 20) ? 1 : 0;
	}
	TestEqual(TEXT("rifle: one tracer in four mid-magazine"), Tracers, 20 / G->TracerInterval);
	TestFalse(TEXT("a ball round mid-magazine"), G->IsTracerRound(1, 20));
	TestTrue(TEXT("the last rounds of a magazine are tracers"), G->IsTracerRound(1, 0) && G->IsTracerRound(1, G->TracerLastRounds - 1));
	TestFalse(TEXT("unknown magazine: interval only"), G->IsTracerRound(1, -1));
	if (const UVerseWeaponDefinition* T = VerseWp02Test::Weapon(*this, TEXT("tallow")))
	{
		TestFalse(TEXT("pistol: no tracer mid-magazine"), T->IsTracerRound(4, 10));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

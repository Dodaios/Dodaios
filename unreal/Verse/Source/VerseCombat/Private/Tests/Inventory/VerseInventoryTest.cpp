#include "Events/VerseEventHub.h"
#include "Inventory/VerseInventoryComponent.h"
#include "Misc/AutomationTest.h"
#include "Net/UnrealNetwork.h"
#include "Tests/Weapons/VerseWp02TestUtils.h"
#include "VerseGameplayTags.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Combat.Reload.Times (A2.4) and Verse.Combat.Inventory.*: the magazine and reload state
// machine (WP02.3) and the inventory component (WP02.2).

namespace VerseInventoryTest
{
	/** Ticks a reload at 60 Hz from Start until it ends; returns the server time it ended. */
	float RunReload(FVerseWeaponSlotState& S, const UVerseWeaponDefinition& W, float Start)
	{
		float Now = Start;
		for (int32 I = 0; I < 1000 && FVerseMagazine::IsReloading(S); ++I)
		{
			Now += VerseWp02Test::Tick;
			FVerseMagazine::Tick(S, W, Now);
		}
		return Now;
	}

	UVerseInventoryComponent* AddInventory(APawn* Pawn, const UVerseWeaponDefinition* Primary, const UVerseWeaponDefinition* Secondary, float Now)
	{
		UVerseInventoryComponent* Inv = NewObject<UVerseInventoryComponent>(Pawn, TEXT("Inventory"));
		Inv->RegisterComponent();
		TMap<EVerseLoadoutSlot, const UVerseWeaponDefinition*> Loadout;
		Loadout.Add(EVerseLoadoutSlot::Primary, Primary);
		Loadout.Add(EVerseLoadoutSlot::Secondary, Secondary);
		Inv->GiveLoadout(Loadout, Now);
		return Inv;
	}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseReloadTimes, "Verse.Combat.Reload.Times", VERSE_WP02_TEST_FLAGS)
bool FVerseReloadTimes::RunTest(const FString&)
{
	for (const UVerseWeaponDefinition* W : VerseWp02Test::AllWeapons(*this))
	{
		const FString Id = W->WeaponId.ToString();
		FVerseWeaponSlotState S;
		FVerseMagazine::InitFull(S, *W);
		TestEqual(FString::Printf(TEXT("%s: spawn holds a full magazine"), *Id), FVerseMagazine::RoundsReady(S, *W), W->MagazineSize);

		// Tactical: fire a few, reload with a round chambered.
		for (int32 I = 0; I < 5; ++I)
		{
			FVerseMagazine::ConsumeRound(S, *W);
		}
		const int32 ReserveBefore = S.Reserve;
		TestTrue(TEXT("tactical reload starts"), FVerseMagazine::StartReload(S, *W, 10.f));
		TestEqual(TEXT("phase tactical"), S.Reload, EVerseReloadPhase::Tactical);
		TestFalse(TEXT("cannot fire while reloading"), FVerseMagazine::CanFire(S, *W));
		const float TacticalEnd = VerseInventoryTest::RunReload(S, *W, 10.f);
		TestTrue(FString::Printf(TEXT("%s: tactical reload within one tick (%.4f vs %.4f)"), *Id, TacticalEnd - 10.f, W->ReloadTactical),
			FMath::Abs((TacticalEnd - 10.f) - W->ReloadTactical) <= VerseWp02Test::Tick + 1e-4f);
		const int32 WantTactical = W->bClosedBolt ? W->MagazineSize + 1 : W->MagazineSize;
		TestEqual(FString::Printf(TEXT("%s: tactical leaves magazine + 1"), *Id), FVerseMagazine::RoundsReady(S, *W), WantTactical);
		TestEqual(TEXT("reserve pays only what was spent"), int32(S.Reserve), ReserveBefore - (W->bClosedBolt ? 6 : 5));

		// Empty: fire everything, reload from empty.
		while (FVerseMagazine::ConsumeRound(S, *W))
		{
		}
		TestEqual(TEXT("empty"), FVerseMagazine::RoundsReady(S, *W), 0);
		TestTrue(TEXT("empty reload starts"), FVerseMagazine::StartReload(S, *W, 20.f));
		TestEqual(TEXT("phase empty"), S.Reload, EVerseReloadPhase::Empty);
		const float EmptyEnd = VerseInventoryTest::RunReload(S, *W, 20.f);
		TestTrue(FString::Printf(TEXT("%s: empty reload within one tick"), *Id),
			FMath::Abs((EmptyEnd - 20.f) - W->ReloadEmpty) <= VerseWp02Test::Tick + 1e-4f);
		TestEqual(FString::Printf(TEXT("%s: empty reload gives a full magazine"), *Id), FVerseMagazine::RoundsReady(S, *W), W->MagazineSize);
		TestTrue(TEXT("tactical is faster than empty"), W->ReloadTactical < W->ReloadEmpty);

		// Cancel before the commit keeps the old magazine; after it the new one is in.
		FVerseMagazine::ConsumeRound(S, *W);
		FVerseMagazine::ConsumeRound(S, *W);
		const FVerseWeaponSlotState Before = S;
		FVerseMagazine::StartReload(S, *W, 30.f);
		const float Commit = FVerseMagazine::CommitTime(S, *W);
		FVerseMagazine::Tick(S, *W, Commit - 0.01f);
		TestEqual(TEXT("cancel before commit"), FVerseMagazine::Cancel(S), EVerseMagazineChange::ReloadCancelled);
		TestEqual(TEXT("old magazine kept"), int32(S.Magazine), int32(Before.Magazine));
		TestEqual(TEXT("old chamber kept"), S.bChambered, Before.bChambered);
		TestEqual(TEXT("reserve untouched"), int32(S.Reserve), int32(Before.Reserve));
		FVerseMagazine::StartReload(S, *W, 40.f);
		FVerseMagazine::Tick(S, *W, FVerseMagazine::CommitTime(S, *W) + 0.001f);
		FVerseMagazine::Cancel(S);
		TestEqual(TEXT("cancel after commit keeps the new magazine"), FVerseMagazine::RoundsReady(S, *W), WantTactical);

		// No reserve, no reload.
		FVerseWeaponSlotState Dry = S;
		Dry.Reserve = 0;
		FVerseMagazine::ConsumeRound(Dry, *W);
		TestFalse(TEXT("no reload without reserve"), FVerseMagazine::StartReload(Dry, *W, 50.f));
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseInventorySlots, "Verse.Combat.Inventory.SlotsAndEquip", VERSE_WP02_TEST_FLAGS)
bool FVerseInventorySlots::RunTest(const FString&)
{
	const UVerseWeaponDefinition* G = VerseWp02Test::Weapon(*this, TEXT("graveline"));
	const UVerseWeaponDefinition* T = VerseWp02Test::Weapon(*this, TEXT("tallow"));
	if (!G || !T)
	{
		return false;
	}

	// Replication conditions of combat-state.md 2.1: slots owner only, active slot and reloading to all.
	TArray<FLifetimeProperty> Props;
	GetDefault<UVerseInventoryComponent>()->GetLifetimeReplicatedProps(Props);
	auto ConditionOf = [&Props](const TCHAR* Name) -> int32
	{
		const FProperty* P = UVerseInventoryComponent::StaticClass()->FindPropertyByName(Name);
		for (const FLifetimeProperty& L : Props)
		{
			if (P && L.RepIndex == P->RepIndex)
			{
				return int32(L.Condition);
			}
		}
		return -1;
	};
	TestEqual(TEXT("Slots owner only"), ConditionOf(TEXT("Slots")), int32(COND_OwnerOnly));
	TestEqual(TEXT("ActiveSlot to all"), ConditionOf(TEXT("ActiveSlot")), int32(COND_None));
	TestEqual(TEXT("bReloading to all"), ConditionOf(TEXT("bReloading")), int32(COND_None));

	VerseWp02Test::FTestWorld W;
	APawn* Pawn = VerseWp02Test::SpawnTarget(W.World, FVector::ZeroVector);
	UVerseInventoryComponent* Inv = VerseInventoryTest::AddInventory(Pawn, G, T, 1.f);
	TestEqual(TEXT("primary drawn"), Inv->ActiveSlot, EVerseLoadoutSlot::Primary);
	TestTrue(TEXT("weapon ready"), Inv->IsReady(1.f));
	TestEqual(TEXT("two slots"), Inv->Slots.Items.Num(), 2);
	TestTrue(TEXT("primary is the Graveline"), Inv->GetActiveWeapon() == G);

	TArray<FVerseReloadEvent> Reloads;
	TArray<FVerseNoiseEvent> Noises;
	UVerseEventHub* Hub = UVerseEventHub::Get(W.World);
	Hub->OnReload.AddLambda([&Reloads](const FVerseReloadEvent& E) { Reloads.Add(E); });
	Hub->OnNoise.AddLambda([&Noises](const FVerseNoiseEvent& E) { Noises.Add(E); });

	TestTrue(TEXT("consume"), Inv->ServerConsumeRound(1.f));
	TestTrue(TEXT("reload starts"), Inv->ServerStartReload(1.1f));
	TestTrue(TEXT("reloading flag"), Inv->bReloading);
	TestEqual(TEXT("one reload event"), Reloads.Num(), 1);
	TestTrue(TEXT("tactical event"), Reloads.Num() == 1 && Reloads[0].bTactical);
	TestTrue(TEXT("reload noise raised"), Noises.Num() == 1 && Noises[0].Noise == VerseTags::Noise_Reload);

	// Switching cancels the reload and readies the new weapon after holster + equip.
	Inv->ServerSwitch(EVerseLoadoutSlot::Secondary, 1.2f);
	TestEqual(TEXT("cancel event"), Reloads.Num(), 2);
	TestTrue(TEXT("cancel flagged"), Reloads.Num() == 2 && Reloads[1].bCancelled);
	TestFalse(TEXT("not reloading"), Inv->bReloading);
	TestEqual(TEXT("active is secondary"), Inv->ActiveSlot, EVerseLoadoutSlot::Secondary);
	TestEqual(TEXT("ready after holster + equip"), Inv->GetReadyAt(), 1.2f + G->HolsterTime + T->EquipTime, 1e-5f);
	TestFalse(TEXT("cannot fire while equipping"), Inv->ServerConsumeRound(1.25f));
	TestTrue(TEXT("fires once equipped"), Inv->ServerConsumeRound(Inv->GetReadyAt()));

	// The server tick finishes a reload on its own.
	Inv->ServerSwitch(EVerseLoadoutSlot::Primary, 5.f);
	const float Ready = Inv->GetReadyAt();
	TestTrue(TEXT("reload after equip"), Inv->ServerStartReload(Ready));
	Inv->ServerAdvance(Ready + G->ReloadTactical + 0.001f);
	TestFalse(TEXT("reload done"), Inv->bReloading);
	TestEqual(TEXT("magazine + 1"), FVerseMagazine::RoundsReady(*Inv->GetActiveState(), *G), G->MagazineSize + 1);

	Inv->RefillAll();
	TestEqual(TEXT("refill"), FVerseMagazine::RoundsReady(*Inv->GetActiveState(), *G), G->MagazineSize);
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

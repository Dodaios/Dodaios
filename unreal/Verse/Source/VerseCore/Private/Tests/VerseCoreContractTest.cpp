#include "Bot/VerseBotAdaptiveConfig.h"
#include "Bot/VerseBotTier.h"
#include "Bot/VersePerceptTypes.h"
#include "Combat/VerseCombatTypes.h"
#include "Combat/VerseGadgetDefinition.h"
#include "Combat/VerseMeleeDefinition.h"
#include "Combat/VerseWeaponDefinition.h"
#include "Destruction/VerseDestructionTuning.h"
#include "Destruction/VersePenetrationTable.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Events/VerseEventHub.h"
#include "GameplayTagsManager.h"
#include "Misc/AutomationTest.h"
#include "Noise/VerseAudibilityTable.h"
#include "Qa/VerseQaRegistry.h"
#include "Stubs/VerseNullStubs.h"
#include "UObject/UnrealType.h"
#include "VerseGameplayTags.h"
#include "VerseLog.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Contract.*: the shared types of VerseCore answer as the contracts say (orchestration.md
// 0.4): enum order, field order of replicated and bridged structs, struct defaults, the frozen
// tags, the data asset schemas and their contract tables, the hub, the QA registry, the stubs.

#define VERSE_CONTRACT_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseContractTest
{
	void CheckEnum(FAutomationTestBase& Test, const UEnum* Enum, std::initializer_list<const TCHAR*> Names)
	{
		if (!Test.TestNotNull(TEXT("enum is reflected"), Enum))
		{
			return;
		}
		const int32 Count = int32(Names.size());
		// NumEnums includes the generated _MAX entry.
		Test.TestEqual(FString::Printf(TEXT("%s entry count"), *Enum->GetName()), Enum->NumEnums() - 1, Count);
		int32 Index = 0;
		for (const TCHAR* Name : Names)
		{
			Test.TestEqual(FString::Printf(TEXT("%s[%d]"), *Enum->GetName(), Index), Enum->GetNameStringByIndex(Index), FString(Name));
			Test.TestEqual(FString::Printf(TEXT("%s::%s value"), *Enum->GetName(), Name), Enum->GetValueByIndex(Index), int64(Index));
			++Index;
		}
	}

	void CheckFields(FAutomationTestBase& Test, const UScriptStruct* Struct, std::initializer_list<const TCHAR*> Names)
	{
		if (!Test.TestNotNull(TEXT("struct is reflected"), Struct))
		{
			return;
		}
		TArray<FString> Actual;
		for (TFieldIterator<FProperty> It(Struct, EFieldIteratorFlags::IncludeSuper); It; ++It)
		{
			Actual.Add(It->GetName());
		}
		TArray<FString> Expected;
		for (const TCHAR* Name : Names)
		{
			Expected.Add(Name);
		}
		Test.TestEqual(FString::Printf(TEXT("%s field order"), *Struct->GetName()),
			FString::Join(Actual, TEXT(",")), FString::Join(Expected, TEXT(",")));
	}

	bool IsTag(const FGameplayTag& Tag, const TCHAR* Name)
	{
		return Tag.IsValid() && Tag.GetTagName() == FName(Name);
	}

	/** A bare game world with its subsystems; destroyed by the caller. */
	UWorld* MakeWorld()
	{
		UWorld* World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseContractTestWorld"));
		return World;
	}
}

using namespace VerseContractTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractCombatEnums, "Verse.Contract.Combat.EnumOrder", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractCombatEnums::RunTest(const FString&)
{
	CheckEnum(*this, StaticEnum<EVerseStance>(), {TEXT("Stand"), TEXT("Crouch"), TEXT("Prone"), TEXT("Slide")});
	CheckEnum(*this, StaticEnum<EVerseHitZone>(), {TEXT("None"), TEXT("Head"), TEXT("Neck"), TEXT("UpperTorso"), TEXT("LowerTorso"), TEXT("Arm"), TEXT("Leg")});
	CheckEnum(*this, StaticEnum<EVerseFireMode>(), {TEXT("Semi"), TEXT("Burst"), TEXT("Auto")});
	CheckEnum(*this, StaticEnum<EVerseLoadoutSlot>(), {TEXT("Primary"), TEXT("Secondary"), TEXT("Melee"), TEXT("GadgetA"), TEXT("GadgetB")});
	CheckEnum(*this, StaticEnum<EVerseCombatPhase>(), {TEXT("Alive"), TEXT("Dead"), TEXT("FinisherAttacker"), TEXT("FinisherVictim")});
	CheckEnum(*this, StaticEnum<EVerseDamageSource>(), {TEXT("Bolt"), TEXT("Melee"), TEXT("Finisher"), TEXT("Gadget"), TEXT("World")});
	CheckEnum(*this, StaticEnum<EVerseShotResult>(), {TEXT("Miss"), TEXT("HitBody"), TEXT("HitPiece"), TEXT("Blocked"), TEXT("Rejected")});
	CheckEnum(*this, StaticEnum<EVerseFinisherPhase>(), {TEXT("Locked"), TEXT("Takedown"), TEXT("Struggle"), TEXT("Kill"), TEXT("Recover"), TEXT("Aborted")});
	CheckEnum(*this, StaticEnum<EVerseGoreLevel>(), {TEXT("Full"), TEXT("Reduced")});
	CheckEnum(*this, StaticEnum<EVerseGadgetEventKind>(), {TEXT("Deploy"), TEXT("Destroyed"), TEXT("Expired"), TEXT("Plant"), TEXT("Detonate")});
	CheckEnum(*this, StaticEnum<EVerseSetOutcome>(), {TEXT("Won"), TEXT("Lost"), TEXT("Unfinished")});
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractInputButtons, "Verse.Contract.Combat.InputButtons", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractInputButtons::RunTest(const FString&)
{
	const TPair<EVerseInputButton, int32> Bits[] = {
		{EVerseInputButton::Fire, 0}, {EVerseInputButton::Ads, 1}, {EVerseInputButton::Reload, 2}, {EVerseInputButton::Melee, 3},
		{EVerseInputButton::Jump, 4}, {EVerseInputButton::Crouch, 5}, {EVerseInputButton::Prone, 6}, {EVerseInputButton::Sprint, 7},
		{EVerseInputButton::LeanLeft, 8}, {EVerseInputButton::LeanRight, 9}, {EVerseInputButton::GadgetA, 10}, {EVerseInputButton::GadgetB, 11},
		{EVerseInputButton::SlotPrimary, 12}, {EVerseInputButton::SlotSecondary, 13}, {EVerseInputButton::SlotMelee, 14},
		{EVerseInputButton::Interact, 15},
	};
	for (const TPair<EVerseInputButton, int32>& Bit : Bits)
	{
		TestEqual(FString::Printf(TEXT("button bit %d"), Bit.Value), uint32(Bit.Key), uint32(1) << Bit.Value);
	}
	TestEqual(TEXT("None is 0"), uint32(EVerseInputButton::None), uint32(0));

	FVerseInputFrame Frame;
	TestEqual(TEXT("default buttons"), Frame.Buttons, uint32(0));
	TestEqual(TEXT("default move"), Frame.Move, FVector2f::ZeroVector);
	Frame.Buttons = uint32(EVerseInputButton::Fire | EVerseInputButton::Sprint);
	Frame.Pressed = uint32(EVerseInputButton::Fire);
	TestTrue(TEXT("fire held"), Frame.IsHeld(EVerseInputButton::Fire));
	TestTrue(TEXT("sprint held"), Frame.IsHeld(EVerseInputButton::Sprint));
	TestFalse(TEXT("ads not held"), Frame.IsHeld(EVerseInputButton::Ads));
	TestTrue(TEXT("fire pressed"), Frame.WasPressed(EVerseInputButton::Fire));
	TestFalse(TEXT("sprint not pressed"), Frame.WasPressed(EVerseInputButton::Sprint));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractCombatFields, "Verse.Contract.Combat.StructFields", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractCombatFields::RunTest(const FString&)
{
	CheckFields(*this, FVerseInputFrame::StaticStruct(), {TEXT("Move"), TEXT("LookDeltaDeg"), TEXT("Buttons"), TEXT("Pressed"), TEXT("ServerTimeMs")});
	CheckFields(*this, FVerseFireEvent::StaticStruct(), {TEXT("ShooterId"), TEXT("WeaponId"), TEXT("ShotCounter"), TEXT("Seed"), TEXT("Origin"), TEXT("Direction"), TEXT("ServerTime")});
	CheckFields(*this, FVerseHitEvent::StaticStruct(), {TEXT("InstigatorId"), TEXT("VictimId"), TEXT("WeaponId"), TEXT("Source"), TEXT("ShotCounter"),
		TEXT("Zone"), TEXT("Bone"), TEXT("ImpactWorld"), TEXT("ImpactBoneLocal"), TEXT("Direction"), TEXT("DistanceM"), TEXT("Damage"),
		TEXT("PenetrationCount"), TEXT("bHeadshot"), TEXT("bKillingBlow"), TEXT("bBlockedBySpawnProtection"), TEXT("ServerTime")});
	CheckFields(*this, FVersePenetrationEvent::StaticStruct(), {TEXT("ShooterId"), TEXT("ShotCounter"), TEXT("PieceIndex"), TEXT("MaterialWireId"),
		TEXT("Entry"), TEXT("Exit"), TEXT("ThicknessCm"), TEXT("PowerBefore"), TEXT("PowerAfter"), TEXT("DamageFactorAfter"), TEXT("bPassed")});
	CheckFields(*this, FVerseDeathEvent::StaticStruct(), {TEXT("VictimId"), TEXT("KillerId"), TEXT("Cause"), TEXT("WeaponId"), TEXT("LastZone"), TEXT("ServerTime"), TEXT("RespawnAt")});
	CheckFields(*this, FVerseFinisherEvent::StaticStruct(), {TEXT("AttackerId"), TEXT("VictimId"), TEXT("Phase"), TEXT("SequenceStartServerTime"), TEXT("WarpTarget")});
	CheckFields(*this, FVerseNoiseEvent::StaticStruct(), {TEXT("Noise"), TEXT("SourceId"), TEXT("Location"), TEXT("Loudness"), TEXT("ServerTime")});
	CheckFields(*this, FVerseReloadEvent::StaticStruct(), {TEXT("PlayerId"), TEXT("WeaponId"), TEXT("bTactical"), TEXT("StartServerTime"), TEXT("EndServerTime"), TEXT("bCancelled")});
	CheckFields(*this, FVerseGadgetEvent::StaticStruct(), {TEXT("Kind"), TEXT("GadgetId"), TEXT("OwnerId"), TEXT("Location"), TEXT("ServerTime")});
	CheckFields(*this, FVerseArenaSwitchEvent::StaticStruct(), {TEXT("bArenaOn"), TEXT("Deck"), TEXT("ServerTime")});
	CheckFields(*this, FVerseStationUsedEvent::StaticStruct(), {TEXT("StationId"), TEXT("Kind"), TEXT("UserId")});
	CheckFields(*this, FVerseSetLine::StaticStruct(), {TEXT("PlayerId"), TEXT("bIsBot"), TEXT("Kills"), TEXT("Deaths"), TEXT("Headshots"), TEXT("Finishers"),
		TEXT("MeleeKills"), TEXT("ShotsFired"), TEXT("ShotsHit"), TEXT("DamageDealt"), TEXT("DamageTaken"), TEXT("WallsBreached"),
		TEXT("BulwarksPlaced"), TEXT("BestStreak"), TEXT("PerWeapon")});
	CheckFields(*this, FVerseSetSummary::StaticStruct(), {TEXT("MatchId"), TEXT("SessionId"), TEXT("SetIndex"), TEXT("RulesetId"), TEXT("BotTier"),
		TEXT("Outcome"), TEXT("StartedAtUnix"), TEXT("EndedAtUnix"), TEXT("MatchTimeS"), TEXT("Person"), TEXT("Opponent")});
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractCombatDefaults, "Verse.Contract.Combat.StructDefaults", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractCombatDefaults::RunTest(const FString&)
{
	const FVerseFireEvent Fire;
	TestEqual(TEXT("fire shooter"), Fire.ShooterId, 0);
	TestTrue(TEXT("fire weapon none"), Fire.WeaponId.IsNone());
	TestEqual(TEXT("fire counter"), Fire.ShotCounter, uint16(0));
	TestEqual(TEXT("fire seed"), Fire.Seed, uint32(0));
	TestEqual(TEXT("fire origin"), FVector(Fire.Origin), FVector::ZeroVector);
	TestEqual(TEXT("fire time"), Fire.ServerTime, 0.f);

	const FVerseHitEvent Hit;
	TestEqual(TEXT("hit source"), Hit.Source, EVerseDamageSource::Bolt);
	TestEqual(TEXT("hit zone"), Hit.Zone, EVerseHitZone::None);
	TestTrue(TEXT("hit bone none"), Hit.Bone.IsNone());
	TestEqual(TEXT("hit impact"), FVector(Hit.ImpactWorld), FVector::ZeroVector);
	TestEqual(TEXT("hit damage"), Hit.Damage, 0.f);
	TestEqual(TEXT("hit penetrations"), Hit.PenetrationCount, uint8(0));
	TestFalse(TEXT("hit headshot"), Hit.bHeadshot != 0);
	TestFalse(TEXT("hit killing blow"), Hit.bKillingBlow != 0);
	TestFalse(TEXT("hit blocked"), Hit.bBlockedBySpawnProtection != 0);

	const FVersePenetrationEvent Pen;
	TestEqual(TEXT("penetration factor"), Pen.DamageFactorAfter, 1.f);
	TestFalse(TEXT("penetration passed"), Pen.bPassed);

	const FVerseDeathEvent Death;
	TestEqual(TEXT("death cause"), Death.Cause, EVerseDamageSource::Bolt);
	TestEqual(TEXT("death zone"), Death.LastZone, EVerseHitZone::None);
	TestEqual(TEXT("death respawn"), Death.RespawnAt, 0.f);

	const FVerseFinisherEvent Finisher;
	TestEqual(TEXT("finisher phase"), Finisher.Phase, EVerseFinisherPhase::Locked);
	TestTrue(TEXT("finisher warp identity"), Finisher.WarpTarget.Equals(FTransform::Identity));

	const FVerseNoiseEvent Noise;
	TestFalse(TEXT("noise tag unset"), Noise.Noise.IsValid());
	TestEqual(TEXT("noise source"), Noise.SourceId, 0);
	TestEqual(TEXT("noise location"), Noise.Location, FVector::ZeroVector);
	TestEqual(TEXT("noise loudness"), Noise.Loudness, 1.f);

	const FVerseReloadEvent Reload;
	TestTrue(TEXT("reload tactical"), Reload.bTactical);
	TestFalse(TEXT("reload cancelled"), Reload.bCancelled);

	const FVerseGadgetEvent Gadget;
	TestEqual(TEXT("gadget kind"), Gadget.Kind, EVerseGadgetEventKind::Deploy);
	TestEqual(TEXT("gadget location"), FVector(Gadget.Location), FVector::ZeroVector);

	const FVerseArenaSwitchEvent Arena;
	TestFalse(TEXT("arena off"), Arena.bArenaOn);
	TestTrue(TEXT("arena deck none"), Arena.Deck.IsNone());

	const FVerseStationUsedEvent Station;
	TestEqual(TEXT("station user"), Station.UserId, 0);

	const FVerseSetSummary Summary;
	TestEqual(TEXT("summary outcome"), Summary.Outcome, EVerseSetOutcome::Unfinished);
	TestEqual(TEXT("summary set index"), Summary.SetIndex, 0);
	TestTrue(TEXT("summary match id empty"), Summary.MatchId.IsEmpty());
	TestEqual(TEXT("summary match time"), Summary.MatchTimeS, 0.f);
	TestFalse(TEXT("person is not a bot"), Summary.Person.bIsBot);
	TestEqual(TEXT("person kills"), Summary.Person.Kills, 0);
	TestEqual(TEXT("person weapons"), Summary.Person.PerWeapon.Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractCombatAssets, "Verse.Contract.Combat.DataAssets", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractCombatAssets::RunTest(const FString&)
{
	const UVerseWeaponDefinition* Weapon = GetDefault<UVerseWeaponDefinition>();
	TestEqual(TEXT("weapon fire interval"), Weapon->FireInterval(), 0.1f);
	TestEqual(TEXT("weapon power anchor"), Weapon->PenetrationPower, 100.f);
	TestEqual(TEXT("weapon max penetrations"), Weapon->GetEffectiveMaxPenetrations(), 3);
	TestEqual(TEXT("weapon hole radius"), Weapon->HoleRadiusMm, uint8(15));
	TestEqual(TEXT("weapon recoil random fraction"), Weapon->RecoilRandomFraction, 0.15f);
	TestEqual(TEXT("empty pattern is zero"), Weapon->PatternAt(4), FVector2f::ZeroVector);

	// R1 with the Graveline start values: 690 RPM, d_r 0.12 s, rho 5 deg/s, pitch 0.45 rising to 0.62.
	UVerseWeaponDefinition* Graveline = NewObject<UVerseWeaponDefinition>();
	Graveline->RPM = 690.f;
	Graveline->MagazineSize = 30;
	Graveline->RecoilRecoveryRate = 5.f;
	Graveline->RecoilRecoveryDelay = 0.12f;
	Graveline->RecoilPitchCurve.GetRichCurve()->AddKey(0.f, 0.45f);
	Graveline->RecoilPitchCurve.GetRichCurve()->AddKey(8.f, 0.62f);
	Graveline->RecoilYawCurve.GetRichCurve()->AddKey(0.f, 0.10f);
	Graveline->RecoilYawCurve.GetRichCurve()->AddKey(10.f, -0.15f);
	TestTrue(TEXT("Graveline satisfies R1"), Graveline->SatisfiesRecoveryBelowKick(0.65f * 0.8f, Graveline->MagazineSize));
	TestEqual(TEXT("pattern holds beyond the last key"), Graveline->PatternAt(40).X, 0.62f);
	Graveline->MaxPenetrations = 7;
	TestEqual(TEXT("max penetrations clamp to 3"), Graveline->GetEffectiveMaxPenetrations(), 3);

	// The three.js blaster of combat-state.md 4.3 breaks R1: 5 shots/s, recovery 9 deg/s from 4/60 s, kick 0.55.
	UVerseWeaponDefinition* Blaster = NewObject<UVerseWeaponDefinition>();
	Blaster->RPM = 300.f;
	Blaster->RecoilRecoveryRate = 9.f;
	Blaster->RecoilRecoveryDelay = 4.f / 60.f;
	Blaster->RecoilRandomFraction = 0.f;
	Blaster->RecoilPitchCurve.GetRichCurve()->AddKey(0.f, 0.55f);
	TestFalse(TEXT("blaster breaks R1"), Blaster->SatisfiesRecoveryBelowKick(1.f, 20));

	const UVerseMeleeDefinition* Melee = GetDefault<UVerseMeleeDefinition>();
	TestEqual(TEXT("strike damage"), Melee->StrikeDamage, 55.f);
	TestTrue(TEXT("two strikes kill 100 hp, one does not"), Melee->StrikeDamage < 100.f && 2.f * Melee->StrikeDamage >= 100.f);
	TestEqual(TEXT("finisher range"), Melee->FinisherRange, 1.5f);
	TestEqual(TEXT("finisher kill time"), Melee->FinisherKillTime, 2.1f);
	TestEqual(TEXT("finisher duration"), Melee->FinisherDuration, 2.5f);

	const UVerseGadgetDefinition* Bulwark = GetDefault<UVerseGadgetDefinition>();
	TestEqual(TEXT("bulwark health"), Bulwark->MaxHealth, 400.f);
	TestEqual(TEXT("bulwark size"), Bulwark->Size, FVector3f(1.8f, 1.4f, 0.1f));
	TestEqual(TEXT("bulwark pawn damage"), Bulwark->PawnDamageAt(0.f), 0.f);

	// GD3 formula: 120 hp at the centre, linear to 0 at 3.0 m.
	UVerseGadgetDefinition* Breach = NewObject<UVerseGadgetDefinition>();
	Breach->PawnDamage = 120.f;
	Breach->PawnRadius = 3.f;
	TestNearlyEqual(TEXT("breach at 0 m"), Breach->PawnDamageAt(0.f), 120.f, 1e-4f);
	TestNearlyEqual(TEXT("breach at 1.5 m"), Breach->PawnDamageAt(1.5f), 60.f, 1e-4f);
	TestNearlyEqual(TEXT("breach at 3.0 m"), Breach->PawnDamageAt(3.f), 0.f, 1e-4f);
	TestNearlyEqual(TEXT("breach beyond"), Breach->PawnDamageAt(5.f), 0.f, 1e-4f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractDestructionTypes, "Verse.Contract.Destruction.Types", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractDestructionTypes::RunTest(const FString&)
{
	CheckEnum(*this, StaticEnum<EVersePieceState>(), {TEXT("Intact"), TEXT("Damaged"), TEXT("Holed"), TEXT("Breached"), TEXT("Destroyed"), TEXT("Repairing")});
	CheckEnum(*this, StaticEnum<EVersePenetrationMaterial>(), {TEXT("SheetMetal"), TEXT("ContainerWall"), TEXT("Glass"), TEXT("CladdingPanel"),
		TEXT("CatwalkGrating"), TEXT("CeilingPanel"), TEXT("Concrete"), TEXT("ArmorSteel")});
	CheckEnum(*this, StaticEnum<EVerseFractureCause>(), {TEXT("Bolt"), TEXT("Breach"), TEXT("Melee"), TEXT("Repair"), TEXT("Reset")});
	CheckEnum(*this, StaticEnum<EVersePieceClass>(), {TEXT("WallPanel"), TEXT("CladdingWall"), TEXT("ContainerWall"), TEXT("GlassPane"),
		TEXT("CatwalkSegment"), TEXT("CeilingPanel")});

	CheckFields(*this, FVerseFractureEvent::StaticStruct(), {TEXT("PieceIndex"), TEXT("FromState"), TEXT("ToState"), TEXT("Cause"), TEXT("Variant"),
		TEXT("Seed"), TEXT("Impulse"), TEXT("Location"), TEXT("Radius"), TEXT("Instigator"), TEXT("ServerTimeMs"), TEXT("Epoch")});
	CheckFields(*this, FVerseBoltHole::StaticStruct(), {TEXT("PieceIndex"), TEXT("AxisPositionMm"), TEXT("AxisDirectionOct"), TEXT("RadiusMm"),
		TEXT("ServerTimeMs"), TEXT("Epoch")});
	CheckFields(*this, FVersePenetrationHit::StaticStruct(), {TEXT("PieceIndex"), TEXT("MaterialWireId"), TEXT("Entry"), TEXT("Exit"),
		TEXT("TracedThicknessCm"), TEXT("PowerLeft"), TEXT("DamageLeft"), TEXT("bPassed")});
	CheckFields(*this, FVersePieceDamage::StaticStruct(), {TEXT("PieceIndex"), TEXT("Amount"), TEXT("Cause"), TEXT("Location"), TEXT("Direction"),
		TEXT("InstigatorId"), TEXT("BreachRadiusCm")});

	const FVerseFractureEvent Fracture;
	TestEqual(TEXT("fracture instigator is world"), Fracture.Instigator, uint8(0xFF));
	TestEqual(TEXT("fracture impulse zero"), int32(Fracture.Impulse[0] | Fracture.Impulse[1] | Fracture.Impulse[2]), 0);
	TestEqual(TEXT("fracture from"), Fracture.FromState, EVersePieceState::Intact);
	TestEqual(TEXT("all pieces id"), Verse::Destruction::AllPieces, uint16(0xFFFF));
	TestEqual(TEXT("impulse array dim"), FVerseFractureEvent::StaticStruct()->FindPropertyByName(TEXT("Impulse"))->ArrayDim, 3);

	TestEqual(TEXT("breach loudness"), Verse::Destruction::FractureLoudness(EVerseFractureNoise::Breach), 1.0f);
	TestEqual(TEXT("wall loudness"), Verse::Destruction::FractureLoudness(EVerseFractureNoise::WallBreak), 0.7f);
	TestEqual(TEXT("glass loudness"), Verse::Destruction::FractureLoudness(EVerseFractureNoise::Glass), 0.6f);
	TestEqual(TEXT("tile loudness"), Verse::Destruction::FractureLoudness(EVerseFractureNoise::Tile), 0.5f);
	TestEqual(TEXT("hole loudness"), Verse::Destruction::FractureLoudness(EVerseFractureNoise::BoltHole), 0.2f);

	TestEqual(TEXT("HealthQ full"), Verse::Destruction::QuantizeHealth(200.f, 200.f), uint8(255));
	TestEqual(TEXT("HealthQ half"), Verse::Destruction::QuantizeHealth(100.f, 200.f), uint8(128));
	TestEqual(TEXT("HealthQ empty"), Verse::Destruction::QuantizeHealth(0.f, 200.f), uint8(0));
	TestEqual(TEXT("HealthQ clamps"), Verse::Destruction::QuantizeHealth(500.f, 200.f), uint8(255));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractBoltHoles, "Verse.Contract.Destruction.BoltHoleSightline", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractBoltHoles::RunTest(const FString&)
{
	// Octahedral round trip over seeded directions: within one quantum (about 1 degree).
	FVerseRng Rng(42, 0, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 2000; ++I)
	{
		const FVector Dir = Rng.UnitVector();
		int8 X = 0, Y = 0;
		Verse::Destruction::EncodeOctahedral(Dir, X, Y);
		const FVector Back = Verse::Destruction::DecodeOctahedral(X, Y);
		if (!TestTrue(FString::Printf(TEXT("octahedral %d within 1.5 deg"), I), FVector::DotProduct(Dir, Back) >= FMath::Cos(FMath::DegreesToRadians(1.5))))
		{
			break;
		}
	}

	// A 15 mm hole through a 4 cm panel along +X at the piece origin.
	const FVerseBoltHole Hole = FVerseBoltHole::Make(7, FVector::ZeroVector, FVector::ForwardVector, 15, 1000, 2);
	TestEqual(TEXT("hole piece"), Hole.PieceIndex, uint16(7));
	TestEqual(TEXT("hole radius"), Hole.RadiusMm, uint8(15));
	TestTrue(TEXT("axis direction"), Hole.GetAxisDirection().Equals(FVector::ForwardVector, 1e-6));
	const TArray<FVerseBoltHole> Holes = {Hole};
	TestTrue(TEXT("straight through passes"), FVerseBoltHole::RayPassesHoles(Holes, FVector(-2, 0.5, 0), FVector(2, 0.5, 0)));
	TestTrue(TEXT("slanted within radius passes"), FVerseBoltHole::RayPassesHoles(Holes, FVector(-2, -1.4, 0), FVector(2, 1.4, 0)));
	TestFalse(TEXT("exit outside the radius is blocked"), FVerseBoltHole::RayPassesHoles(Holes, FVector(-2, 0, 0), FVector(2, 2.0, 0)));
	TestFalse(TEXT("entry outside the radius is blocked"), FVerseBoltHole::RayPassesHoles(Holes, FVector(-2, 0, 1.6), FVector(2, 0, 0)));
	TestFalse(TEXT("no holes blocks"), FVerseBoltHole::RayPassesHoles({}, FVector(-2, 0, 0), FVector(2, 0, 0)));

	// Thin sheet metal gives a wider view cone through the same hole than a thick panel.
	const double SheetHalfCm = 0.15;
	const double PanelHalfCm = 2.0;
	const double Slope = 4.0; // cm lateral per cm of depth
	TestTrue(TEXT("steep ray through thin sheet"), FVerseBoltHole::RayPassesHoles(Holes,
		FVector(-SheetHalfCm, -Slope * SheetHalfCm, 0), FVector(SheetHalfCm, Slope * SheetHalfCm, 0)));
	TestFalse(TEXT("steep ray through thick panel"), FVerseBoltHole::RayPassesHoles(Holes,
		FVector(-PanelHalfCm, -Slope * PanelHalfCm, 0), FVector(PanelHalfCm, Slope * PanelHalfCm, 0)));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractPenetrationTable, "Verse.Contract.Destruction.PenetrationTable", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractPenetrationTable::RunTest(const FString&)
{
	const UVersePenetrationTable* Table = GetDefault<UVersePenetrationTable>();
	if (!TestEqual(TEXT("eight materials"), Table->Rows.Num(), 8))
	{
		return false;
	}
	for (int32 Wire = 0; Wire < Table->Rows.Num(); ++Wire)
	{
		const FVersePenetrationRow& Row = Table->Rows[Wire];
		TestEqual(FString::Printf(TEXT("row %d wire id"), Wire), int32(Row.WireId), Wire);
		TestTrue(FString::Printf(TEXT("row %d tag"), Wire), Row.MaterialTag == VerseTags::AllMaterialTags()[Wire]);
		TestTrue(FString::Printf(TEXT("row %d positive reference thickness"), Wire), Row.RefThicknessCm > 0.f);
	}
	TestNull(TEXT("unknown wire id"), Table->FindRow(8));

	const FVersePenetrationRow& Container = *Table->FindRow(uint8(EVersePenetrationMaterial::ContainerWall));
	TestEqual(TEXT("container at reference"), UVersePenetrationTable::PassCost(Container, 0.4f), 25.f);
	TestEqual(TEXT("cost floor 0.5"), UVersePenetrationTable::PassCost(Container, 0.01f), 12.5f);
	TestEqual(TEXT("cost cap 3.0"), UVersePenetrationTable::PassCost(Container, 40.f), 75.f);

	// The rifle (100) passes two container walls and keeps 0.5625 of its damage (destruction.md 2).
	float Power = 100.f;
	float Factor = 1.f;
	for (int32 Pass = 0; Pass < 2; ++Pass)
	{
		const float Cost = UVersePenetrationTable::PassCost(Container, 0.4f);
		TestTrue(TEXT("rifle passes a container wall"), Power >= Cost);
		Power -= Cost;
		Factor *= Container.DamageMultiplier;
	}
	TestNearlyEqual(TEXT("rifle damage after two walls"), Factor, 0.5625f, 1e-6f);

	// The pistol (50) passes one container wall, or glass plus sheet metal.
	const FVersePenetrationRow& Glass = *Table->FindRow(uint8(EVersePenetrationMaterial::Glass));
	const FVersePenetrationRow& Sheet = *Table->FindRow(uint8(EVersePenetrationMaterial::SheetMetal));
	TestTrue(TEXT("pistol passes glass and sheet"), 50.f - UVersePenetrationTable::PassCost(Glass, 2.4f) - UVersePenetrationTable::PassCost(Sheet, 0.3f) >= 0.f);

	// Nothing passes concrete or armor steel, even at the thinnest clamp.
	for (const EVersePenetrationMaterial Hard : {EVersePenetrationMaterial::Concrete, EVersePenetrationMaterial::ArmorSteel})
	{
		const FVersePenetrationRow& Row = *Table->FindRow(uint8(Hard));
		TestTrue(TEXT("rifle stops"), UVersePenetrationTable::PassCost(Row, 0.f) > 100.f);
		TestEqual(TEXT("no damage after"), Row.DamageMultiplier, 0.f);
		TestFalse(TEXT("never breaks by bullets"), Row.bBreakableByBullets);
		TestFalse(TEXT("never breaks by breach"), Row.bBreakableByBreach);
	}
	TestFalse(TEXT("grating does not break by bullets"), Table->FindRow(uint8(EVersePenetrationMaterial::CatwalkGrating))->bBreakableByBullets);

	const UVerseDestructionTuning* Tuning = GetDefault<UVerseDestructionTuning>();
	TestEqual(TEXT("six piece classes"), Tuning->Classes.Num(), 6);
	TestEqual(TEXT("wall panel hp"), Tuning->Classes.FindChecked(EVersePieceClass::WallPanel).MaxHp, 200.f);
	TestEqual(TEXT("wall panel holed at"), Tuning->Classes.FindChecked(EVersePieceClass::WallPanel).HoledAtOrBelowHp, 100.f);
	TestEqual(TEXT("container hp"), Tuning->Classes.FindChecked(EVersePieceClass::ContainerWall).MaxHp, 300.f);
	TestTrue(TEXT("glass breaks by melee"), Tuning->Classes.FindChecked(EVersePieceClass::GlassPane).bDestroyedByMeleeWhenDamaged);
	TestFalse(TEXT("catwalk ignores bullets"), Tuning->Classes.FindChecked(EVersePieceClass::CatwalkSegment).bDamagedOnFirstHit);
	TestEqual(TEXT("repair delay"), Tuning->RepairDelayS, 60.f);
	TestEqual(TEXT("holes per piece"), Tuning->HolesPerPiece, 24);
	TestEqual(TEXT("holes per arena"), Tuning->HolesPerArena, 512);
	TestEqual(TEXT("drones"), Tuning->MaxActiveDrones, 3);
	TestEqual(TEXT("drone hp"), Tuning->DroneMaxHp, 30.f);
	for (const TPair<EVersePieceClass, FVersePieceClassTuning>& Pair : Tuning->Classes)
	{
		const FVersePenetrationRow* Row = Table->FindRow(uint8(Pair.Value.Material));
		TestTrue(TEXT("class material is breakable by breach"), Row && Row->bBreakableByBreach);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractTags, "Verse.Contract.Tags", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractTags::RunTest(const FString&)
{
	const TCHAR* NoiseNames[] = {
		TEXT("Noise.Shot"), TEXT("Noise.Footstep.Sprint"), TEXT("Noise.Footstep.Run"), TEXT("Noise.Footstep.Walk"),
		TEXT("Noise.Move.Slide"), TEXT("Noise.Move.Land"), TEXT("Noise.Move.Mantle"), TEXT("Noise.Reload"),
		TEXT("Noise.Gadget.BulwarkDeploy"), TEXT("Noise.Gadget.BulwarkHum"), TEXT("Noise.Gadget.BreachPlant"),
		TEXT("Noise.Gadget.BreachDetonate"), TEXT("Noise.Fracture"), TEXT("Noise.Drone"), TEXT("Noise.Melee"),
		TEXT("Noise.Finisher"), TEXT("Noise.Impact"),
	};
	const TConstArrayView<FGameplayTag> Noise = VerseTags::AllNoiseTags();
	if (TestEqual(TEXT("noise tag count (bot.md 3.2)"), Noise.Num(), int32(UE_ARRAY_COUNT(NoiseNames))))
	{
		for (int32 I = 0; I < Noise.Num(); ++I)
		{
			TestTrue(FString::Printf(TEXT("noise tag %s"), NoiseNames[I]), IsTag(Noise[I], NoiseNames[I]));
			TestTrue(FString::Printf(TEXT("%s is registered"), NoiseNames[I]),
				UGameplayTagsManager::Get().RequestGameplayTag(FName(NoiseNames[I]), false).IsValid());
		}
	}

	const TCHAR* States[] = {TEXT("Attack"), TEXT("Hold"), TEXT("Flank"), TEXT("StalkForFinisher"), TEXT("Retreat"),
		TEXT("Reload"), TEXT("DeployBulwark"), TEXT("Breach"), TEXT("Wallbang"), TEXT("Search")};
	const TConstArrayView<FGameplayTag> Bot = VerseTags::AllBotStateTags();
	if (TestEqual(TEXT("bot state tag count (bot.md 5.1)"), Bot.Num(), int32(UE_ARRAY_COUNT(States))))
	{
		for (int32 I = 0; I < Bot.Num(); ++I)
		{
			TestTrue(FString::Printf(TEXT("bot state %s"), States[I]), IsTag(Bot[I], *FString::Printf(TEXT("Bot.State.%s"), States[I])));
		}
	}

	const TCHAR* Materials[] = {TEXT("sheet_metal"), TEXT("container_wall"), TEXT("glass"), TEXT("cladding_panel"),
		TEXT("catwalk_grating"), TEXT("ceiling_panel"), TEXT("concrete"), TEXT("armor_steel")};
	const TConstArrayView<FGameplayTag> Mats = VerseTags::AllMaterialTags();
	if (TestEqual(TEXT("material tag count"), Mats.Num(), int32(UE_ARRAY_COUNT(Materials))))
	{
		for (int32 I = 0; I < Mats.Num(); ++I)
		{
			TestTrue(FString::Printf(TEXT("material %s"), Materials[I]), IsTag(Mats[I], *FString::Printf(TEXT("Verse.Material.%s"), Materials[I])));
		}
	}

	// Every noise tag has exactly one audibility row, and every row is a noise tag.
	const UVerseAudibilityTable* Audibility = GetDefault<UVerseAudibilityTable>();
	TestEqual(TEXT("one audibility row per noise tag"), Audibility->Rows.Num(), Noise.Num());
	for (const FGameplayTag& Tag : Noise)
	{
		TestNotNull(*FString::Printf(TEXT("audibility row for %s"), *Tag.ToString()), Audibility->FindRow(Tag));
	}
	TestEqual(TEXT("sprint 20 m"), Audibility->GetAudibleRangeM(VerseTags::Noise_Footstep_Sprint, 1.f), 20.f);
	TestEqual(TEXT("walk 4 m"), Audibility->GetAudibleRangeM(VerseTags::Noise_Footstep_Walk, 1.f), 4.f);
	TestEqual(TEXT("breach fracture 40 m"), Audibility->GetAudibleRangeM(VerseTags::Noise_Fracture, 1.f), 40.f);
	TestNearlyEqual(TEXT("bolt hole fracture 8 m"), Audibility->GetAudibleRangeM(VerseTags::Noise_Fracture, 0.2f), 8.f, 1e-5f);
	TestNearlyEqual(TEXT("drone 6 m"), Audibility->GetAudibleRangeM(VerseTags::Noise_Drone, Verse::Destruction::DroneLoudness), 6.f, 1e-5f);
	TestTrue(TEXT("shot is whole arena"), Audibility->FindRow(VerseTags::Noise_Shot)->bWholeArena);
	TestEqual(TEXT("detonation error x 0.5"), Audibility->FindRow(VerseTags::Noise_Gadget_BreachDetonate)->ErrorMultiplier, 0.5f);
	TestEqual(TEXT("impact error 0"), Audibility->FindRow(VerseTags::Noise_Impact)->ErrorMultiplier, 0.f);
	TestEqual(TEXT("unknown tag 0 m"), Audibility->GetAudibleRangeM(FGameplayTag(), 1.f), 0.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractBotTypes, "Verse.Contract.Bot.Types", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractBotTypes::RunTest(const FString&)
{
	CheckEnum(*this, StaticEnum<EVerseSightSample>(), {TEXT("Head"), TEXT("Neck"), TEXT("UpperTorso"), TEXT("Pelvis"),
		TEXT("ShoulderLeft"), TEXT("ShoulderRight"), TEXT("KneeLeft"), TEXT("KneeRight")});
	CheckFields(*this, FVersePerceptFrame::StaticStruct(), {TEXT("ServerTimeMs"), TEXT("Self"), TEXT("Sightings"), TEXT("Bolts"),
		TEXT("Heard"), TEXT("bHasHurt"), TEXT("Hurt"), TEXT("Hud")});
	CheckFields(*this, FVerseHeardPercept::StaticStruct(), {TEXT("PerceptId"), TEXT("Noise"), TEXT("Location"), TEXT("ErrorSdM"),
		TEXT("LevelGuess"), TEXT("ServerTimeMs")});

	// A percept never carries truth it must not: no health, ammo, tier or controller field on a sighting.
	for (const TCHAR* Forbidden : {TEXT("Health"), TEXT("Magazine"), TEXT("Reserve"), TEXT("Tier"), TEXT("Controller"), TEXT("TrueLocation")})
	{
		TestNull(*FString::Printf(TEXT("sighting has no %s"), Forbidden), FVerseSightPercept::StaticStruct()->FindPropertyByName(Forbidden));
		TestNull(*FString::Printf(TEXT("heard percept has no %s"), Forbidden), FVerseHeardPercept::StaticStruct()->FindPropertyByName(Forbidden));
	}
	const FVersePerceptFrame Frame;
	TestFalse(TEXT("frame has no hurt by default"), Frame.bHasHurt);
	TestEqual(TEXT("frame empty"), Frame.Sightings.Num() + Frame.Bolts.Num() + Frame.Heard.Num() + Frame.Hud.Num(), 0);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractBotTiers, "Verse.Contract.Bot.Tiers", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractBotTiers::RunTest(const FString&)
{
	UVerseBotTier* Normal = NewObject<UVerseBotTier>();
	UVerseBotTier* Hard = NewObject<UVerseBotTier>();
	UVerseBotTier* Elite = NewObject<UVerseBotTier>();
	TestTrue(TEXT("normal start values"), UVerseBotTier::ApplyStartValues(TEXT("normal"), *Normal));
	TestTrue(TEXT("hard start values"), UVerseBotTier::ApplyStartValues(TEXT("hard"), *Hard));
	TestTrue(TEXT("elite start values"), UVerseBotTier::ApplyStartValues(TEXT("elite"), *Elite));
	TestFalse(TEXT("unknown tier"), UVerseBotTier::ApplyStartValues(TEXT("legendary"), *Elite));

	// The class defaults are the normal tier.
	const UVerseBotTier* Defaults = GetDefault<UVerseBotTier>();
	TestEqual(TEXT("default reaction"), Defaults->ReactionMs, Normal->ReactionMs);
	TestEqual(TEXT("default turn rate"), Defaults->TurnRateDegS, Normal->TurnRateDegS);

	TestEqual(TEXT("hard reaction mean"), Hard->ReactionMs.X, 270.f);
	TestEqual(TEXT("elite turn rate"), Elite->TurnRateDegS, 850.f);
	TestEqual(TEXT("elite bursts"), Elite->MaxBurstShots, 4);
	for (const UVerseBotTier* Tier : {Normal, Hard, Elite})
	{
		TestTrue(*FString::Printf(TEXT("%s within contract bounds"), *Tier->TierId.ToString()), Tier->SatisfiesContractBounds());
	}
	// Higher tiers react faster and turn faster.
	TestTrue(TEXT("reaction ladder"), Normal->ReactionMs.X > Hard->ReactionMs.X && Hard->ReactionMs.X > Elite->ReactionMs.X);
	TestTrue(TEXT("turn ladder"), Normal->TurnRateDegS < Hard->TurnRateDegS && Hard->TurnRateDegS < Elite->TurnRateDegS);

	UVerseBotTier* Loose = NewObject<UVerseBotTier>();
	Loose->WallbangMinBelief = 0.1f;
	Loose->WallbangMaxSourceAgeS = 9.f;
	Loose->LearnWeightMax = 0.9f;
	TestFalse(TEXT("loose tier breaks bounds"), Loose->SatisfiesContractBounds());
	Loose->ClampToContract();
	TestTrue(TEXT("clamped tier holds bounds"), Loose->SatisfiesContractBounds());
	TestEqual(TEXT("belief floor"), Loose->WallbangMinBelief, UVerseBotTier::WallbangMinBeliefFloor);

	// Adaptive interpolation (bot.md 9.2).
	UVerseBotTier* Out = NewObject<UVerseBotTier>();
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, 0.f, *Out);
	TestEqual(TEXT("s = 0 is normal"), Out->TurnRateDegS, Normal->TurnRateDegS);
	TestEqual(TEXT("adaptive id"), Out->TierId, FName(TEXT("adaptive")));
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, 0.5f, *Out);
	TestTrue(TEXT("s = 0.5 is hard"), Out->ReactionMs.Equals(Hard->ReactionMs, 1e-4f));
	TestEqual(TEXT("s = 0.5 bursts"), Out->MaxBurstShots, Hard->MaxBurstShots);
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, 1.f, *Out);
	TestEqual(TEXT("s = 1 is elite"), Out->AimNoiseDeg, Elite->AimNoiseDeg);
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, 0.25f, *Out);
	TestNearlyEqual(TEXT("s = 0.25 halfway normal-hard"), Out->TurnRateDegS, 0.5f * (Normal->TurnRateDegS + Hard->TurnRateDegS), 1e-3f);
	TestEqual(TEXT("int fields round"), Out->MaxBurstShots, FMath::RoundToInt(0.5f * (Normal->MaxBurstShots + Hard->MaxBurstShots)));
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, 7.f, *Out);
	TestEqual(TEXT("never above elite"), Out->TurnRateDegS, Elite->TurnRateDegS);
	UVerseBotAdaptiveConfig::InterpolateTier(*Normal, *Hard, *Elite, -3.f, *Out);
	TestEqual(TEXT("never below normal"), Out->TurnRateDegS, Normal->TurnRateDegS);

	const UVerseBotAdaptiveConfig* Adaptive = GetDefault<UVerseBotAdaptiveConfig>();
	TestEqual(TEXT("start skill"), Adaptive->StartSkill, 0.5f);
	TestEqual(TEXT("warm-up holds"), Adaptive->NextSkill(0.5f, 1.f, 2), 0.5f);
	TestEqual(TEXT("deadband holds"), Adaptive->NextSkill(0.5f, 0.55f, 8), 0.5f);
	TestNearlyEqual(TEXT("step is capped"), Adaptive->NextSkill(0.5f, 1.f, 8), 0.55f, 1e-6f);
	TestNearlyEqual(TEXT("small step"), Adaptive->NextSkill(0.5f, 0.6f, 8), 0.525f, 1e-6f);
	TestEqual(TEXT("clamped at 1"), Adaptive->NextSkill(0.99f, 1.f, 8), 1.f);
	TestEqual(TEXT("clamped at 0"), Adaptive->NextSkill(0.01f, 0.f, 8), 0.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractRng, "Verse.Contract.Rng", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractRng::RunTest(const FString&)
{
	FVerseRng A(1234);
	FVerseRng B(1234);
	for (int32 I = 0; I < 1000; ++I)
	{
		if (!TestEqual(TEXT("same seed, same stream"), A.NextU64(), B.NextU64()))
		{
			break;
		}
	}
	TestNotEqual(TEXT("different seeds differ"), FVerseRng(1).NextU64(), FVerseRng(2).NextU64());
	TestNotEqual(TEXT("salts separate streams"), FVerseRng(9, 3, EVerseRngSalt::Recoil).NextU64(), FVerseRng(9, 3, EVerseRngSalt::Spread).NextU64());
	TestNotEqual(TEXT("indices separate streams"), FVerseRng(9, 3).NextU64(), FVerseRng(9, 4).NextU64());
	TestEqual(TEXT("indexed stream is reproducible"), FVerseRng(9, 3, EVerseRngSalt::Spread).NextU64(), FVerseRng(9, 3, EVerseRngSalt::Spread).NextU64());
	TestNotEqual(TEXT("hash is order-sensitive"), FVerseRng::Hash(1, 2, 3), FVerseRng::Hash(3, 2, 1));
	TestEqual(TEXT("hash is stable"), FVerseRng::Hash(1, 2, 3), FVerseRng::Hash(1, 2, 3));

	// Golden values pin the algorithm: a change here breaks every recorded replay (BR1).
	FVerseRng Golden(0);
	TestEqual(TEXT("SplitMix64(0) first draw"), Golden.NextU64(), uint64(0xE220A8397B1DCDAFull));

	FVerseRng Rng(77, 0, EVerseRngSalt::Harness);
	double Sum = 0.0;
	double DiskX = 0.0;
	double GaussSum = 0.0;
	double GaussSq = 0.0;
	const int32 N = 20000;
	for (int32 I = 0; I < N; ++I)
	{
		const double U = Rng.NextUnit();
		TestTrue(TEXT("unit in [0, 1)"), U >= 0.0 && U < 1.0);
		Sum += U;
		const FVector2D D = Rng.UnitDisk();
		TestTrue(TEXT("disk point inside"), D.SizeSquared() <= 1.0);
		DiskX += D.X;
		const double G = Rng.Gaussian();
		GaussSum += G;
		GaussSq += G * G;
		const int32 R = Rng.RangeInt(-3, 3);
		TestTrue(TEXT("range int inclusive"), R >= -3 && R <= 3);
		const FVector Cone = Rng.ConeDirection(FVector::ForwardVector, 2.0);
		TestTrue(TEXT("cone direction within half-angle"), FVector::DotProduct(Cone, FVector::ForwardVector) >= FMath::Cos(FMath::DegreesToRadians(2.0)) - 1e-12);
	}
	TestNearlyEqual(TEXT("unit mean"), Sum / N, 0.5, 0.01);
	TestNearlyEqual(TEXT("disk mean x"), DiskX / N, 0.0, 0.01);
	TestNearlyEqual(TEXT("gaussian mean"), GaussSum / N, 0.0, 0.03);
	TestNearlyEqual(TEXT("gaussian variance"), GaussSq / N, 1.0, 0.05);
	TestEqual(TEXT("range int with an empty span"), Rng.RangeInt(5, 5), 5);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractEventHub, "Verse.Contract.EventHub", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractEventHub::RunTest(const FString&)
{
	UWorld* World = MakeWorld();
	if (!TestNotNull(TEXT("test world"), World))
	{
		return false;
	}
	UVerseEventHub* Hub = World->GetSubsystem<UVerseEventHub>();
	if (TestNotNull(TEXT("hub exists in a game world"), Hub))
	{
		int32 Calls = 0;
		Hub->OnFire.AddLambda([&Calls](const FVerseFireEvent& E) { Calls += E.ShotCounter == 1 ? 1 : 0; });
		Hub->OnHit.AddLambda([&Calls](const FVerseHitEvent&) { ++Calls; });
		Hub->OnPenetration.AddLambda([&Calls](const FVersePenetrationEvent&) { ++Calls; });
		Hub->OnDeath.AddLambda([&Calls](const FVerseDeathEvent&) { ++Calls; });
		Hub->OnFinisher.AddLambda([&Calls](const FVerseFinisherEvent&) { ++Calls; });
		Hub->OnNoise.AddLambda([&Calls](const FVerseNoiseEvent& E) { Calls += E.Noise == VerseTags::Noise_Shot ? 1 : 0; });
		Hub->OnReload.AddLambda([&Calls](const FVerseReloadEvent&) { ++Calls; });
		Hub->OnGadget.AddLambda([&Calls](const FVerseGadgetEvent&) { ++Calls; });
		Hub->OnFracture.AddLambda([&Calls](const FVerseFractureEvent&) { ++Calls; });
		Hub->OnArenaSwitch.AddLambda([&Calls](const FVerseArenaSwitchEvent& E) { Calls += E.bArenaOn ? 1 : 0; });
		Hub->OnSetEnded.AddLambda([&Calls](const FVerseSetSummary& S) { Calls += S.Outcome == EVerseSetOutcome::Won ? 1 : 0; });
		Hub->OnStationUsed.AddLambda([&Calls](const FVerseStationUsedEvent&) { ++Calls; });

		FVerseFireEvent Fire;
		Fire.ShotCounter = 1;
		Hub->OnFire.Broadcast(Fire);
		Hub->OnHit.Broadcast(FVerseHitEvent());
		Hub->OnPenetration.Broadcast(FVersePenetrationEvent());
		Hub->OnDeath.Broadcast(FVerseDeathEvent());
		Hub->OnFinisher.Broadcast(FVerseFinisherEvent());
		FVerseNoiseEvent Noise;
		Noise.Noise = VerseTags::Noise_Shot;
		Hub->OnNoise.Broadcast(Noise);
		Hub->OnReload.Broadcast(FVerseReloadEvent());
		Hub->OnGadget.Broadcast(FVerseGadgetEvent());
		Hub->OnFracture.Broadcast(FVerseFractureEvent());
		FVerseArenaSwitchEvent Arena;
		Arena.bArenaOn = true;
		Hub->OnArenaSwitch.Broadcast(Arena);
		FVerseSetSummary Summary;
		Summary.Outcome = EVerseSetOutcome::Won;
		Hub->OnSetEnded.Broadcast(Summary);
		Hub->OnStationUsed.Broadcast(FVerseStationUsedEvent());
		TestEqual(TEXT("every delegate of combat-state.md 11.1 relays its event"), Calls, 12);
		TestEqual(TEXT("Get finds the world's hub"), UVerseEventHub::Get(World), Hub);
	}
	World->DestroyWorld(false);
	TestNull(TEXT("no hub without a world"), UVerseEventHub::Get(nullptr));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractQaRegistry, "Verse.Contract.QaRegistry", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractQaRegistry::RunTest(const FString&)
{
	const TConstArrayView<FString> Known = UVerseQaRegistry::KnownCommands();
	TestEqual(TEXT("parity.md 19 command count"), Known.Num(), 20);
	TSet<FString> Unique;
	for (const FString& Name : Known)
	{
		TestTrue(Name + TEXT(" has the prefix"), Name.StartsWith(UVerseQaRegistry::CommandPrefix()));
		Unique.Add(Name);
	}
	TestEqual(TEXT("known commands are unique"), Unique.Num(), Known.Num());

	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (!TestNotNull(TEXT("registry exists"), Registry))
	{
		return false;
	}
	const FString Name = TEXT("Verse.QA.ContractTest.Echo");
	Registry->Unregister(Name);
	const bool bRegistered = Registry->Register(Name, TEXT("Echoes its arguments (contract test)."),
		[](const TArray<FString>& Args) { return FString::Printf(TEXT("{\"args\": \"%s\"}"), *FString::Join(Args, TEXT("|"))); });
	TestTrue(TEXT("register"), bRegistered);
	TestTrue(TEXT("registered"), Registry->IsRegistered(Name));
	TestTrue(TEXT("listed"), Registry->GetRegisteredCommands().Contains(Name));

	AddExpectedError(TEXT("refused"), EAutomationExpectedErrorFlags::Contains, 3);
	TestFalse(TEXT("duplicate refused"), Registry->Register(Name, TEXT(""), [](const TArray<FString>&) { return FString(); }));
	TestFalse(TEXT("prefix required"), Registry->Register(TEXT("Verse.Stats"), TEXT(""), [](const TArray<FString>&) { return FString(); }));
	TestFalse(TEXT("handler required"), Registry->Register(TEXT("Verse.QA.ContractTest.Null"), TEXT(""), FVerseQaHandler()));

	FString Result;
	TestTrue(TEXT("execute"), Registry->Execute(Name, {TEXT("a"), TEXT("b")}, Result));
	TestEqual(TEXT("execute result"), Result, FString(TEXT("{\"args\": \"a|b\"}")));
	TestTrue(TEXT("execute line"), Registry->ExecuteLine(TEXT("Verse.QA.ContractTest.Echo  one \"two words\""), Result));
	TestEqual(TEXT("execute line result"), Result, FString(TEXT("{\"args\": \"one|two words\"}")));
	TestFalse(TEXT("unknown command"), Registry->Execute(TEXT("Verse.QA.ContractTest.Missing"), {}, Result));
	TestTrue(TEXT("unknown command answers an error object"), Result.StartsWith(TEXT("{\"error\"")));
	TestFalse(TEXT("empty line"), Registry->ExecuteLine(TEXT("   "), Result));

	TestTrue(TEXT("unregister"), Registry->Unregister(Name));
	TestFalse(TEXT("gone"), Registry->IsRegistered(Name));
	TestFalse(TEXT("second unregister"), Registry->Unregister(Name));
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractStubs, "Verse.Contract.Stubs", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractStubs::RunTest(const FString&)
{
	UObject* Pen = NewObject<UVerseNullPenetrationQuery>();
	IVersePenetrationQuery* PenQuery = Cast<IVersePenetrationQuery>(Pen);
	if (TestNotNull(TEXT("penetration stub implements the interface"), PenQuery))
	{
		TestEqual(TEXT("no pieces entered"), PenQuery->TraceBolt(FVector::ZeroVector, FVector::ForwardVector, 15000.f, 100.f, 28.f, 15, 3).Num(), 0);
		TestTrue(TEXT("sight is clear"), PenQuery->TestSight(FVector::ZeroVector, FVector(1000, 0, 0)));
	}
	IVersePieceDamage* Damage = NewObject<UVerseNullPieceDamage>();
	if (TestNotNull(TEXT("damage stub implements the interface"), Damage))
	{
		Damage->ApplyPieceDamage(FVersePieceDamage());
	}
	IVersePieceQuery* Pieces = Cast<IVersePieceQuery>(NewObject<UVerseNullPieceQuery>());
	if (TestNotNull(TEXT("piece stub implements the interface"), Pieces))
	{
		TestEqual(TEXT("state"), Pieces->GetPieceState(3), EVersePieceState::Intact);
		TestEqual(TEXT("material"), Pieces->GetPieceMaterial(3), EVersePenetrationMaterial::Concrete);
		TestFalse(TEXT("bounds invalid"), bool(Pieces->GetPieceBounds(3).IsValid));
		TestEqual(TEXT("no pieces in a box"), Pieces->GetPiecesInBox(FBox(FVector(-1e5), FVector(1e5))).Num(), 0);
	}
	const IVerseMovementQuery* Movement = Cast<IVerseMovementQuery>(GetMutableDefault<UVerseNullMovementQuery>());
	if (TestNotNull(TEXT("movement stub implements the interface"), Movement))
	{
		TestEqual(TEXT("stance"), Movement->GetStance(), EVerseStance::Stand);
		TestFalse(TEXT("sprinting"), Movement->IsSprinting());
		TestFalse(TEXT("airborne"), Movement->IsAirborne());
		TestFalse(TEXT("mantling"), Movement->IsMantling());
		TestFalse(TEXT("blocks firing"), Movement->BlocksFiring());
		TestEqual(TEXT("lean"), Movement->GetLeanQuantized(), int8(0));
	}
	TestEqual(TEXT("lean quantise full right"), IVerseMovementQuery::QuantizeLean(1.f), int8(127));
	TestEqual(TEXT("lean quantise clamps"), IVerseMovementQuery::QuantizeLean(-3.f), int8(-127));
	TestNearlyEqual(TEXT("lean round trip"), IVerseMovementQuery::LeanFromQuantized(IVerseMovementQuery::QuantizeLean(0.5f)), 0.5f, 0.5f / 127.f);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseContractLog, "Verse.Contract.LogCategories", VERSE_CONTRACT_TEST_FLAGS)
bool FVerseContractLog::RunTest(const FString&)
{
	TestEqual(TEXT("core"), LogVerseCore.GetCategoryName(), FName(TEXT("LogVerseCore")));
	TestEqual(TEXT("combat"), LogVerseCombat.GetCategoryName(), FName(TEXT("LogVerseCombat")));
	TestEqual(TEXT("bot"), LogVerseBot.GetCategoryName(), FName(TEXT("LogVerseBot")));
	TestEqual(TEXT("qa"), LogVerseQa.GetCategoryName(), FName(TEXT("LogVerseQa")));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

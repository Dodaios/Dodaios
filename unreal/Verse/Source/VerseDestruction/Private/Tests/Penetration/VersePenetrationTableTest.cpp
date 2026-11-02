#include "CoreMinimal.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "Dom/JsonObject.h"
#include "HAL/PlatformTime.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Penetration/VersePenetrationMath.h"
#include "Penetration/VersePenetrationPhysicalMaterial.h"
#include "Penetration/VersePenetrationSubsystem.h"
#include "Penetration/VersePenetrationTableImport.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Tests/Penetration/Fakes/VerseWP03Fakes.h"
#include "VerseLog.h"

namespace
{
	constexpr EAutomationTestFlags WP03Flags = EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter;

	EVersePenetrationMaterial MaterialById(const FString& Id)
	{
		const TConstArrayView<const TCHAR*> Ids = VersePenetration::FrozenMaterialIds();
		for (int32 Wire = 0; Wire < Ids.Num(); ++Wire)
		{
			if (Id == Ids[Wire])
			{
				return EVersePenetrationMaterial(Wire);
			}
		}
		return EVersePenetrationMaterial::Concrete;
	}

	TSharedPtr<FJsonObject> LoadJson(const FString& Path)
	{
		FString Text;
		TSharedPtr<FJsonObject> Root;
		if (FFileHelper::LoadFileToString(Text, *Path))
		{
			FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(Text), Root);
		}
		return Root;
	}

	/** Imported rows of Data/destruction/penetration.json (what the runtime uses). */
	bool ImportedRows(FAutomationTestBase& Test, TArray<FVersePenetrationRow>& OutRows)
	{
		FString Text;
		TArray<FString> Errors;
		if (!Test.TestTrue(TEXT("penetration.json readable"), FFileHelper::LoadFileToString(Text, *VersePenetrationImport::DefaultTablePath())))
		{
			return false;
		}
		const bool bOk = VersePenetrationImport::ParseTableJson(Text, OutRows, Errors);
		for (const FString& Error : Errors)
		{
			Test.AddError(Error);
		}
		return bOk;
	}
}

// WP03.2: the importer reads the propose-only JSON into exactly the contract rows and refuses
// anything that breaks the frozen wire order or a column.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationImportTest, "Verse.Destruction.Penetration.Import", WP03Flags)

bool FVersePenetrationImportTest::RunTest(const FString& Parameters)
{
	TArray<FVersePenetrationRow> Rows;
	if (!ImportedRows(*this, Rows))
	{
		return false;
	}
	for (const FString& Diff : VersePenetrationImport::DiffRows(Rows, UVersePenetrationTable::MakeContractRows()))
	{
		AddError(FString::Printf(TEXT("penetration.json vs destruction.md 2: %s"), *Diff));
	}

	FString Text;
	FFileHelper::LoadFileToString(Text, *VersePenetrationImport::DefaultTablePath());
	struct FBad
	{
		const TCHAR* What;
		FString Json;
	};
	const TArray<FBad> BadInputs = {
		{TEXT("swapped wire order"), Text.Replace(TEXT("\"id\": \"sheet_metal\""), TEXT("\"id\": \"TMP\""))
										 .Replace(TEXT("\"id\": \"container_wall\""), TEXT("\"id\": \"sheet_metal\""))
										 .Replace(TEXT("\"id\": \"TMP\""), TEXT("\"id\": \"container_wall\""))},
		{TEXT("wrong wire number"), Text.Replace(TEXT("\"wire\": 7"), TEXT("\"wire\": 9"))},
		{TEXT("unknown material"), Text.Replace(TEXT("\"armor_steel\""), TEXT("\"steel_plate\""))},
		{TEXT("missing column"), Text.Replace(TEXT("\"damage_multiplier\": 0.95,"), TEXT(""))},
		{TEXT("power anchor"), Text.Replace(TEXT("\"power_anchor\": 100"), TEXT("\"power_anchor\": 40"))},
		{TEXT("piece limit"), Text.Replace(TEXT("\"max_pieces\": 3"), TEXT("\"max_pieces\": 2"))},
		{TEXT("schema"), Text.Replace(TEXT("verse.penetration/1"), TEXT("verse.penetration/2"))},
		{TEXT("not json"), TEXT("{")},
	};
	for (const FBad& Bad : BadInputs)
	{
		TestNotEqual(FString::Printf(TEXT("%s: mutation applied"), Bad.What), Bad.Json, Text);
		TArray<FVersePenetrationRow> Out;
		TArray<FString> Errors;
		TestFalse(FString::Printf(TEXT("%s is refused"), Bad.What), VersePenetrationImport::ParseTableJson(Bad.Json, Out, Errors));
		TestTrue(FString::Printf(TEXT("%s names an error"), Bad.What), Errors.Num() > 0);
	}

	// A table with a removed row fails the frozen order check.
	TArray<FVersePenetrationRow> Short = UVersePenetrationTable::MakeContractRows();
	Short.RemoveAt(3);
	TArray<FString> Errors;
	TestFalse(TEXT("removed row fails the wire order check"), VersePenetrationImport::CheckWireOrder(Short, Errors));

	// ImportIntoTable leaves the table untouched on failure.
	UVersePenetrationTable* Table = NewObject<UVersePenetrationTable>();
	Table->Rows[0].PenetrationCost = 99.f;
	Errors.Reset();
	TestFalse(TEXT("missing file refused"), VersePenetrationImport::ImportIntoTable(*Table, TEXT("Z:/no/such/penetration.json"), Errors));
	TestEqual(TEXT("table untouched on failure"), Table->Rows[0].PenetrationCost, 99.f);
	Errors.Reset();
	TestTrue(TEXT("default file imports"), VersePenetrationImport::ImportIntoTable(*Table, VersePenetrationImport::DefaultTablePath(), Errors));
	TestEqual(TEXT("imported sheet metal cost"), Table->Rows[0].PenetrationCost, 15.f);
	return true;
}

// A3.1: 8 materials x 3 thicknesses x 3 power levels against the hand-computed golden table to
// 1e-4, first as arithmetic, then as real traces through solid boxes of those thicknesses.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationTableTest, "Verse.Destruction.Penetration.Table", WP03Flags)

bool FVersePenetrationTableTest::RunTest(const FString& Parameters)
{
	TArray<FVersePenetrationRow> Rows;
	if (!ImportedRows(*this, Rows))
	{
		return false;
	}
	const TSharedPtr<FJsonObject> Golden = LoadJson(VerseWP03Test::GoldenFixturePath());
	if (!TestTrue(TEXT("golden fixture loads"), Golden.IsValid()))
	{
		return false;
	}
	const double Tol = Golden->GetNumberField(TEXT("tolerance"));
	TestTrue(TEXT("tolerance is 1e-4"), FMath::IsNearlyEqual(Tol, 1e-4, 1e-12));
	const TArray<TSharedPtr<FJsonValue>>& Cases = Golden->GetArrayField(TEXT("cases"));
	TestEqual(TEXT("8 x 3 x 3 cases"), Cases.Num(), 72);

	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}

	int32 Checked = 0;
	uint16 PieceIndex = 0;
	for (const TSharedPtr<FJsonValue>& Value : Cases)
	{
		const TSharedPtr<FJsonObject> Case = Value->AsObject();
		const FString Id = Case->GetStringField(TEXT("material"));
		const EVersePenetrationMaterial Material = MaterialById(Id);
		const FVersePenetrationRow& Row = Rows[uint8(Material)];
		const float Thickness = float(Case->GetNumberField(TEXT("thickness_cm")));
		const float Power = float(Case->GetNumberField(TEXT("power")));
		const FString Label = FString::Printf(TEXT("%s %.2f cm power %.0f"), *Id, Thickness, Power);

		const FVersePenetrationStep Step = VersePenetration::EvaluatePiece(Row, Thickness, Power, 1.f, false);
		TestTrue(Label + TEXT(" cost"), FMath::IsNearlyEqual(Step.Cost, Case->GetNumberField(TEXT("cost")), Tol));
		TestEqual(Label + TEXT(" passed"), Step.bPassed, Case->GetBoolField(TEXT("passed")));
		TestTrue(Label + TEXT(" power left"), FMath::IsNearlyEqual(Step.PowerLeft, Case->GetNumberField(TEXT("power_left")), Tol));
		TestTrue(Label + TEXT(" damage left"), FMath::IsNearlyEqual(Step.DamageLeft, Case->GetNumberField(TEXT("damage_left")), Tol));

		// The same case through a real solid of that thickness, traced on VerseBolt.
		const FVector Center(500.f + 20.f * PieceIndex, 0.f, 0.f);
		AActor* Piece = W.SpawnPiece(PieceIndex, Material, Center, Thickness);
		W.Settle();
		const FVector Origin = Center - FVector(5.f, 0, 0);
		const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(Origin, FVector::ForwardVector, 10.f, Power, 1.f, 15, 3);
		if (TestEqual(Label + TEXT(" traced pieces"), Hits.Num(), 1))
		{
			const FVersePenetrationHit& Hit = Hits[0];
			TestEqual(Label + TEXT(" traced piece index"), Hit.PieceIndex, PieceIndex);
			TestEqual(Label + TEXT(" traced wire id"), Hit.MaterialWireId, uint8(Material));
			TestTrue(Label + FString::Printf(TEXT(" traced thickness %.6f"), Hit.TracedThicknessCm),
				FMath::IsNearlyEqual(Hit.TracedThicknessCm, Thickness, Tol));
			TestEqual(Label + TEXT(" traced passed"), Hit.bPassed, Case->GetBoolField(TEXT("passed")));
			TestTrue(Label + TEXT(" traced power left"), FMath::IsNearlyEqual(Hit.PowerLeft, Case->GetNumberField(TEXT("power_left")), Tol * 10.0));
			TestTrue(Label + TEXT(" traced damage left"), FMath::IsNearlyEqual(Hit.DamageLeft, Case->GetNumberField(TEXT("damage_left")), Tol));
		}
		W.DestroyActor(Piece);
		++PieceIndex;
		++Checked;
	}
	TestEqual(TEXT("every case checked"), Checked, 72);

	// Chains: several pieces, the 3-piece limit and the rifle through two container walls.
	for (const TSharedPtr<FJsonValue>& Value : Golden->GetArrayField(TEXT("chains")))
	{
		const TSharedPtr<FJsonObject> Chain = Value->AsObject();
		const FString Name = Chain->GetStringField(TEXT("name"));
		const TArray<TSharedPtr<FJsonValue>>& Pieces = Chain->GetArrayField(TEXT("pieces"));
		const TArray<TSharedPtr<FJsonValue>>& Passed = Chain->GetArrayField(TEXT("passed"));
		const TArray<TSharedPtr<FJsonValue>>& PowerLeft = Chain->GetArrayField(TEXT("power_left"));
		const TArray<TSharedPtr<FJsonValue>>& DamageLeft = Chain->GetArrayField(TEXT("damage_left"));
		const int32 MaxPieces = int32(Chain->GetNumberField(TEXT("max_pieces")));
		const float Power = float(Chain->GetNumberField(TEXT("power")));

		// Arithmetic.
		float P = Power;
		float D = 1.f;
		int32 Passes = 0;
		for (int32 I = 0; I < Pieces.Num(); ++I)
		{
			const TSharedPtr<FJsonObject> PieceSpec = Pieces[I]->AsObject();
			const FVersePenetrationRow& Row = Rows[uint8(MaterialById(PieceSpec->GetStringField(TEXT("material"))))];
			const FVersePenetrationStep Step = VersePenetration::EvaluatePiece(Row, float(PieceSpec->GetNumberField(TEXT("thickness_cm"))), P, D,
				Passes >= VersePenetration::EffectiveMaxPieces(MaxPieces));
			TestEqual(FString::Printf(TEXT("%s: piece %d passed"), *Name, I), Step.bPassed, Passed[I]->AsBool());
			TestTrue(FString::Printf(TEXT("%s: piece %d power"), *Name, I), FMath::IsNearlyEqual(Step.PowerLeft, PowerLeft[I]->AsNumber(), Tol));
			TestTrue(FString::Printf(TEXT("%s: piece %d damage"), *Name, I), FMath::IsNearlyEqual(Step.DamageLeft, DamageLeft[I]->AsNumber(), Tol));
			if (!Step.bPassed)
			{
				break;
			}
			P = Step.PowerLeft;
			D = Step.DamageLeft;
			++Passes;
		}

		// Traced: the pieces stand 50 cm apart on the bolt's line.
		TArray<AActor*> Spawned;
		for (int32 I = 0; I < Pieces.Num(); ++I)
		{
			const TSharedPtr<FJsonObject> PieceSpec = Pieces[I]->AsObject();
			Spawned.Add(W.SpawnPiece(uint16(1000 + I), MaterialById(PieceSpec->GetStringField(TEXT("material"))), FVector(3000.f + 50.f * I, 0, 0),
				float(PieceSpec->GetNumberField(TEXT("thickness_cm")))));
		}
		W.Settle();
		const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(FVector(2950.f, 0, 0), FVector::ForwardVector, 1000.f, Power, 1.f, 15, MaxPieces);
		if (TestEqual(Name + TEXT(": traced pieces"), Hits.Num(), Passed.Num()))
		{
			for (int32 I = 0; I < Hits.Num(); ++I)
			{
				TestEqual(FString::Printf(TEXT("%s: traced %d passed"), *Name, I), Hits[I].bPassed, Passed[I]->AsBool());
				TestTrue(FString::Printf(TEXT("%s: traced %d damage %.6f"), *Name, I, Hits[I].DamageLeft),
					FMath::IsNearlyEqual(Hits[I].DamageLeft, DamageLeft[I]->AsNumber(), Tol));
			}
		}
		for (AActor* Actor : Spawned)
		{
			W.DestroyActor(Actor);
		}
	}
	return true;
}

// A3.2: concrete, armor steel and the hall floor never pass; the 4th piece always stops a bolt;
// a weapon may lower the limit, never raise it.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationBudgetTest, "Verse.Combat.Penetration.Budget", WP03Flags)

bool FVersePenetrationBudgetTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	const EVerseWorldSurface Floor = EVerseWorldSurface::HallFloor;
	const EVerseWorldSurface Wall = EVerseWorldSurface::StructuralWall;
	const EVerseWorldSurface Beam = EVerseWorldSurface::StructuralBeam;
	struct FSurfaceCase
	{
		const TCHAR* Name;
		const EVerseWorldSurface* Surface;
		EVersePenetrationMaterial Expected;
	};
	const FSurfaceCase Surfaces[] = {
		{TEXT("hall floor"), &Floor, EVersePenetrationMaterial::Concrete},
		{TEXT("structural wall"), &Wall, EVersePenetrationMaterial::Concrete},
		{TEXT("structural beam"), &Beam, EVersePenetrationMaterial::ArmorSteel},
		{TEXT("unmapped geometry"), nullptr, EVersePenetrationMaterial::Concrete},
	};
	const float Thicknesses[] = {0.5f, 1.f, 2.5f, 10.f, 30.f, 90.f};
	const float Powers[] = {50.f, 100.f, 150.f, 199.f};
	for (const FSurfaceCase& Surface : Surfaces)
	{
		for (const float Thickness : Thicknesses)
		{
			AActor* Box = W.SpawnWorldBox(Surface.Surface, FVector(1000.f, 0, 0), Thickness);
			W.Settle();
			for (const float Power : Powers)
			{
				const FString Label = FString::Printf(TEXT("%s %.1f cm power %.0f"), Surface.Name, Thickness, Power);
				const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(FVector(900.f, 0, 0), FVector::ForwardVector, 500.f, Power, 1.f, 15, 3);
				if (TestEqual(Label + TEXT(": one surface"), Hits.Num(), 1))
				{
					TestFalse(Label + TEXT(": never passes"), Hits[0].bPassed);
					TestEqual(Label + TEXT(": row"), Hits[0].MaterialWireId, uint8(Surface.Expected));
					TestEqual(Label + TEXT(": no piece"), Hits[0].PieceIndex, VersePenetration::NoPiece);
					TestEqual(Label + TEXT(": no damage left"), Hits[0].DamageLeft, 0.f);
				}
			}
			W.DestroyActor(Box);
		}
	}

	// Four laminated panes cost 5 each: power is no object, the limit is.
	TArray<AActor*> Panes;
	for (int32 I = 0; I < 4; ++I)
	{
		Panes.Add(W.SpawnPiece(uint16(I), EVersePenetrationMaterial::Glass, FVector(2000.f + 40.f * I, 0, 0), 2.4f));
	}
	W.Settle();
	struct FLimitCase
	{
		int32 WeaponMax;
		int32 Stops;
	};
	const FLimitCase Limits[] = {{3, 3}, {7, 3}, {100, 3}, {2, 2}, {1, 1}, {0, 0}};
	for (const FLimitCase& Limit : Limits)
	{
		const TArray<FVersePenetrationHit> Hits = W.Penetration->TraceBolt(FVector(1900.f, 0, 0), FVector::ForwardVector, 1000.f, 1.0e6f, 1.f, 15, Limit.WeaponMax);
		const FString Label = FString::Printf(TEXT("weapon limit %d"), Limit.WeaponMax);
		if (TestEqual(Label + TEXT(": pieces entered"), Hits.Num(), Limit.Stops + 1))
		{
			for (int32 I = 0; I < Limit.Stops; ++I)
			{
				TestTrue(FString::Printf(TEXT("%s: piece %d passes"), *Label, I), Hits[I].bPassed);
			}
			TestFalse(Label + TEXT(": the next piece stops it"), Hits.Last().bPassed);
			TestEqual(Label + TEXT(": stopped piece index"), Hits.Last().PieceIndex, uint16(Limit.Stops));
		}
	}
	for (AActor* Pane : Panes)
	{
		W.DestroyActor(Pane);
	}
	return true;
}

// WP03.7: non-destructible world geometry maps to table rows through its physical material.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationWorldMaterialsTest, "Verse.Destruction.Penetration.WorldMaterials", WP03Flags)

bool FVersePenetrationWorldMaterialsTest::RunTest(const FString& Parameters)
{
	TestEqual(TEXT("hall floor is concrete"), VersePenetration::WorldSurfaceMaterial(EVerseWorldSurface::HallFloor), EVersePenetrationMaterial::Concrete);
	TestEqual(TEXT("structural wall is concrete"), VersePenetration::WorldSurfaceMaterial(EVerseWorldSurface::StructuralWall),
		EVersePenetrationMaterial::Concrete);
	TestEqual(TEXT("structural beam is armor steel"), VersePenetration::WorldSurfaceMaterial(EVerseWorldSurface::StructuralBeam),
		EVersePenetrationMaterial::ArmorSteel);
	TestEqual(TEXT("no physical material is concrete"), VersePenetration::ResolveWorldMaterial(nullptr), EVersePenetrationMaterial::Concrete);
	UPhysicalMaterial* Plain = NewObject<UPhysicalMaterial>();
	TestEqual(TEXT("a foreign physical material is concrete"), VersePenetration::ResolveWorldMaterial(Plain), EVersePenetrationMaterial::Concrete);
	const UEnum* Surfaces = StaticEnum<EVerseWorldSurface>();
	for (int32 I = 0; I < Surfaces->NumEnums() - 1; ++I)
	{
		UVersePenetrationPhysicalMaterial* Mat = NewObject<UVersePenetrationPhysicalMaterial>();
		Mat->Surface = EVerseWorldSurface(Surfaces->GetValueByIndex(I));
		const EVersePenetrationMaterial Row = VersePenetration::ResolveWorldMaterial(Mat);
		TestTrue(FString::Printf(TEXT("%s maps to an impassable row"), *Surfaces->GetNameStringByIndex(I)),
			Row == EVersePenetrationMaterial::Concrete || Row == EVersePenetrationMaterial::ArmorSteel);
	}
	return true;
}

// A3.5: 64 TraceBolt calls per tick, each through three pieces, at most 0.3 ms game thread.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVersePenetrationCostTest, "Verse.Destruction.Penetration.Cost", WP03Flags)

bool FVersePenetrationCostTest::RunTest(const FString& Parameters)
{
	FVerseWP03World W;
	if (!TestTrue(TEXT("test world"), W.Create()))
	{
		return false;
	}
	// A container row: three walls, then a structural wall behind them.
	for (int32 I = 0; I < 3; ++I)
	{
		W.SpawnPiece(uint16(I), EVersePenetrationMaterial::SheetMetal, FVector(200.f + 100.f * I, 0, 0), 0.3f, 400.f, 400.f);
	}
	const EVerseWorldSurface Wall = EVerseWorldSurface::StructuralWall;
	W.SpawnWorldBox(&Wall, FVector(800.f, 0, 0), 30.f, 600.f, 600.f);
	W.Settle();

	constexpr int32 Ticks = 41;
	constexpr int32 CallsPerTick = 64;
	TArray<double> TickMs;
	int32 Entered = 0;
	for (int32 Tick = 0; Tick < Ticks; ++Tick)
	{
		const double Start = FPlatformTime::Seconds();
		for (int32 Call = 0; Call < CallsPerTick; ++Call)
		{
			const FVector Origin(0.f, -150.f + 300.f * Call / CallsPerTick, -100.f + 3.f * Tick);
			Entered += W.Penetration->TraceBolt(Origin, FVector::ForwardVector, 1500.f, 100.f, 30.f, 15, 3).Num();
		}
		TickMs.Add((FPlatformTime::Seconds() - Start) * 1000.0);
	}
	TickMs.Sort();
	const double Median = TickMs[Ticks / 2];
	const double P90 = TickMs[Ticks * 9 / 10];
	UE_LOG(LogVerseDestruction, Display, TEXT("WP03 cost: 64 TraceBolt per tick, median %.4f ms, p90 %.4f ms, max %.4f ms"), Median, P90, TickMs.Last());
	TestEqual(TEXT("every call enters three walls and the structural wall"), Entered, Ticks * CallsPerTick * 4);
	TestTrue(FString::Printf(TEXT("median tick %.4f ms <= 0.3 ms"), Median), Median <= 0.3);
	AddInfo(FString::Printf(TEXT("TraceBolt cost: median %.4f ms, p90 %.4f ms, max %.4f ms per 64 calls"), Median, P90, TickMs.Last()));
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

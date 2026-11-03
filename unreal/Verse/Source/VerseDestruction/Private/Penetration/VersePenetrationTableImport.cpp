#include "Penetration/VersePenetrationTableImport.h"

#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Penetration/VersePenetrationJson.h"
#include "Penetration/VersePenetrationMath.h"
#include "VerseGameplayTags.h"
#include "VerseLog.h"

namespace VersePenetrationImport
{
	FString DefaultTablePath()
	{
		return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("destruction"), TEXT("penetration.json"));
	}

	FSoftObjectPath TableAssetPath()
	{
		return FSoftObjectPath(TEXT("/Game/Verse/Destruction/_Holes/DA_PenetrationTable.DA_PenetrationTable"));
	}

	UVersePenetrationTable* LoadRuntimeTable(UObject* Outer)
	{
		const FString JsonPath = DefaultTablePath();
		if (UVersePenetrationTable* Asset = Cast<UVersePenetrationTable>(TableAssetPath().TryLoad()))
		{
#if WITH_EDITOR
			TArray<FVersePenetrationRow> JsonRows;
			TArray<FString> Errors;
			FString Text;
			if (FPaths::FileExists(JsonPath) && FFileHelper::LoadFileToString(Text, *JsonPath) && ParseTableJson(Text, JsonRows, Errors))
			{
				const TArray<FString> Diffs = DiffRows(Asset->Rows, JsonRows);
				if (!Diffs.IsEmpty())
				{
					UE_LOG(LogVerseDestruction, Warning,
						TEXT("DA_PenetrationTable differs from %s (%s); re-run Content/Verse/Test/WP03/Python/wp03_content.py"), *JsonPath,
						*FString::Join(Diffs, TEXT("; ")));
				}
			}
#endif
			return Asset;
		}
		UVersePenetrationTable* Table = NewObject<UVersePenetrationTable>(Outer, TEXT("DA_PenetrationTable_Runtime"), RF_Transient);
		if (!FPaths::FileExists(JsonPath))
		{
			UE_LOG(LogVerseDestruction, Warning, TEXT("neither %s nor %s found; using the contract table"), *TableAssetPath().ToString(),
				*JsonPath);
			return Table;
		}
		TArray<FString> Errors;
		if (!ImportIntoTable(*Table, JsonPath, Errors))
		{
			UE_LOG(LogVerseDestruction, Error, TEXT("penetration table %s rejected, using the contract table: %s"), *JsonPath,
				*FString::Join(Errors, TEXT("; ")));
		}
		else
		{
			UE_LOG(LogVerseDestruction, Warning, TEXT("%s missing; using %s directly (not staged in cooked builds)"),
				*TableAssetPath().ToString(), *JsonPath);
		}
		return Table;
	}

	bool CheckWireOrder(TConstArrayView<FVersePenetrationRow> Rows, TArray<FString>& OutErrors)
	{
		const TConstArrayView<const TCHAR*> Ids = VersePenetration::FrozenMaterialIds();
		const TConstArrayView<FGameplayTag> Tags = VerseTags::AllMaterialTags();
		bool bOk = true;
		if (Rows.Num() < Ids.Num())
		{
			OutErrors.Add(FString::Printf(TEXT("%d rows; the frozen table has %d (materials only append)"), Rows.Num(), Ids.Num()));
			bOk = false;
		}
		for (int32 Wire = 0; Wire < FMath::Min(Rows.Num(), Ids.Num()); ++Wire)
		{
			if (int32(Rows[Wire].WireId) != Wire)
			{
				OutErrors.Add(FString::Printf(TEXT("row %d carries wire id %d"), Wire, int32(Rows[Wire].WireId)));
				bOk = false;
			}
			if (Rows[Wire].MaterialTag != Tags[Wire])
			{
				OutErrors.Add(FString::Printf(TEXT("row %d is %s, the frozen order wants Verse.Material.%s"), Wire,
					*Rows[Wire].MaterialTag.ToString(), Ids[Wire]));
				bOk = false;
			}
		}
		return bOk;
	}

	bool ParseTableJson(const FString& JsonText, TArray<FVersePenetrationRow>& OutRows, TArray<FString>& OutErrors)
	{
		OutRows.Reset();
		const int32 ErrorsBefore = OutErrors.Num();
		FVerseJson Doc;
		FString ParseError;
		if (!FVerseJson::Parse(JsonText, Doc, ParseError) || !Doc.IsObject())
		{
			OutErrors.Add(ParseError.IsEmpty() ? FString(TEXT("not a JSON object")) : ParseError);
			return false;
		}
		const FVerseJson* Root = &Doc;
		FString SchemaText;
		if (!Root->TryString(TEXT("schema"), SchemaText) || SchemaText != Schema)
		{
			OutErrors.Add(FString::Printf(TEXT("schema must be %s"), Schema));
		}
		double Anchor = 0.0;
		if (!Root->TryNumber(TEXT("power_anchor"), Anchor) || Anchor != 100.0)
		{
			OutErrors.Add(TEXT("power_anchor must be 100 (the assault rifle, destruction.md 2)"));
		}
		double MaxPieces = 0.0;
		if (!Root->TryNumber(TEXT("max_pieces"), MaxPieces) || int32(MaxPieces) != Verse::Destruction::MaxPenetrations)
		{
			OutErrors.Add(TEXT("max_pieces must be 3 (destruction.md 2)"));
		}
		const TArray<FVerseJson>* Materials = Root->FindArray(TEXT("materials"));
		if (!Materials)
		{
			OutErrors.Add(TEXT("materials array missing"));
			return false;
		}

		const TConstArrayView<const TCHAR*> Ids = VersePenetration::FrozenMaterialIds();
		const TConstArrayView<FGameplayTag> Tags = VerseTags::AllMaterialTags();
		const UEnum* DebrisEnum = StaticEnum<EVerseDebrisType>();
		for (int32 Index = 0; Index < Materials->Num(); ++Index)
		{
			const FVerseJson& M = (*Materials)[Index];
			if (!M.IsObject())
			{
				OutErrors.Add(FString::Printf(TEXT("materials[%d] is not an object"), Index));
				continue;
			}
			FString Id;
			FString Debris;
			double Wire = -1.0;
			double Ref = 0.0;
			double Cost = 0.0;
			double Mult = 0.0;
			bool bBullets = false;
			bool bBreach = false;
			const bool bComplete = M.TryNumber(TEXT("wire"), Wire) && M.TryString(TEXT("id"), Id)
				&& M.TryNumber(TEXT("ref_thickness_cm"), Ref) && M.TryNumber(TEXT("cost"), Cost)
				&& M.TryNumber(TEXT("damage_multiplier"), Mult) && M.TryBool(TEXT("breakable_by_bullets"), bBullets)
				&& M.TryBool(TEXT("breakable_by_breach"), bBreach) && M.TryString(TEXT("debris"), Debris);
			if (!bComplete)
			{
				OutErrors.Add(FString::Printf(TEXT("materials[%d] misses a column"), Index));
				continue;
			}
			// An appended material needs its Core tag and enum value first (a contract change), so
			// every row must name a known id.
			const int32 KnownIndex = Ids.IndexOfByPredicate([&Id](const TCHAR* Known) { return Id == Known; });
			if (KnownIndex == INDEX_NONE)
			{
				OutErrors.Add(FString::Printf(TEXT("materials[%d]: unknown material id %s"), Index, *Id));
				continue;
			}
			if (Ref <= 0.0 || Cost < 0.0 || Mult < 0.0 || Mult > 1.0 || Wire < 0.0 || Wire > 255.0)
			{
				OutErrors.Add(FString::Printf(TEXT("materials[%d] %s: wire 0..255, ref > 0, cost >= 0, multiplier in [0, 1]"), Index, *Id));
				continue;
			}
			const int64 DebrisValue = DebrisEnum->GetValueByNameString(Debris);
			if (DebrisValue == INDEX_NONE)
			{
				OutErrors.Add(FString::Printf(TEXT("materials[%d] %s: unknown debris type %s"), Index, *Id, *Debris));
				continue;
			}
			FVersePenetrationRow Row;
			Row.MaterialTag = Tags[KnownIndex];
			Row.WireId = EVersePenetrationMaterial(uint8(Wire));
			Row.RefThicknessCm = float(Ref);
			Row.PenetrationCost = float(Cost);
			Row.DamageMultiplier = float(Mult);
			Row.bBreakableByBullets = bBullets;
			Row.bBreakableByBreach = bBreach;
			Row.DebrisType = EVerseDebrisType(uint8(DebrisValue));
			OutRows.Add(Row);
		}
		CheckWireOrder(OutRows, OutErrors);
		return OutErrors.Num() == ErrorsBefore;
	}

	bool ImportIntoTable(UVersePenetrationTable& Table, const FString& Path, TArray<FString>& OutErrors)
	{
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			OutErrors.Add(FString::Printf(TEXT("cannot read %s"), *Path));
			return false;
		}
		TArray<FVersePenetrationRow> Rows;
		if (!ParseTableJson(Text, Rows, OutErrors))
		{
			return false;
		}
		Table.Rows = MoveTemp(Rows);
		return true;
	}

	TArray<FString> DiffRows(TConstArrayView<FVersePenetrationRow> A, TConstArrayView<FVersePenetrationRow> B, float Tolerance)
	{
		TArray<FString> Diffs;
		if (A.Num() != B.Num())
		{
			Diffs.Add(FString::Printf(TEXT("row count %d vs %d"), A.Num(), B.Num()));
		}
		auto Near = [Tolerance](float L, float R) { return FMath::Abs(L - R) <= Tolerance; };
		for (int32 I = 0; I < FMath::Min(A.Num(), B.Num()); ++I)
		{
			const FVersePenetrationRow& X = A[I];
			const FVersePenetrationRow& Y = B[I];
			if (X.MaterialTag != Y.MaterialTag || X.WireId != Y.WireId || !Near(X.RefThicknessCm, Y.RefThicknessCm)
				|| !Near(X.PenetrationCost, Y.PenetrationCost) || !Near(X.DamageMultiplier, Y.DamageMultiplier)
				|| X.bBreakableByBullets != Y.bBreakableByBullets || X.bBreakableByBreach != Y.bBreakableByBreach
				|| X.DebrisType != Y.DebrisType)
			{
				Diffs.Add(FString::Printf(TEXT("row %d (%s) differs"), I, *X.MaterialTag.ToString()));
			}
		}
		return Diffs;
	}
}

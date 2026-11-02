#include "Dom/JsonObject.h"
#include "Misc/AutomationTest.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseCoords.h"
#include "VerseRng.h"

#if WITH_DEV_AUTOMATION_TESTS

// Verse.Contract.Coords.*: the required tests of contracts/coordinates.md section 5 (1 to 13;
// 14 is a CI script). Tolerances: positions 1e-6 cm, directions and quaternion components
// 1e-12, angles 1e-9 deg.

#define VERSE_COORDS_TEST_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

namespace VerseCoordsTest
{
	using namespace Verse::Coords;

	constexpr double PosTol = 1e-6;
	constexpr double DirTol = 1e-12;
	constexpr double AngTol = 1e-9;
	constexpr uint64 Seed = 0x5645525345ull;

	FVerseThreeVector T(double X, double Y, double Z) { return FVerseThreeVector(X, Y, Z); }

	FVector MOf(const FVerseThreeVector& V) { return FVector(V.X, V.Z, V.Y); }

	FVerseThreeVector Cross(const FVerseThreeVector& A, const FVerseThreeVector& B)
	{
		return T(A.Y * B.Z - A.Z * B.Y, A.Z * B.X - A.X * B.Z, A.X * B.Y - A.Y * B.X);
	}

	FVerseThreeVector DirFromAngles(double Yaw, double Pitch)
	{
		const double C = FMath::Cos(Pitch);
		return T(FMath::Sin(Yaw) * C, FMath::Sin(Pitch), FMath::Cos(Yaw) * C);
	}

	bool Near(FAutomationTestBase& Test, const FString& What, const FVector& Actual, const FVector& Expected, double Tol)
	{
		const bool bOk = FMath::Abs(Actual.X - Expected.X) <= Tol && FMath::Abs(Actual.Y - Expected.Y) <= Tol
			&& FMath::Abs(Actual.Z - Expected.Z) <= Tol;
		if (!bOk)
		{
			Test.AddError(FString::Printf(TEXT("%s: got (%.15g, %.15g, %.15g), expected (%.15g, %.15g, %.15g)"), *What,
				Actual.X, Actual.Y, Actual.Z, Expected.X, Expected.Y, Expected.Z));
		}
		return bOk;
	}

	bool Near(FAutomationTestBase& Test, const FString& What, const FVerseThreeVector& Actual, const FVerseThreeVector& Expected, double Tol)
	{
		return Near(Test, What, FVector(Actual.X, Actual.Y, Actual.Z), FVector(Expected.X, Expected.Y, Expected.Z), Tol);
	}

	bool Near(FAutomationTestBase& Test, const FString& What, double Actual, double Expected, double Tol)
	{
		if (FMath::Abs(Actual - Expected) > Tol)
		{
			Test.AddError(FString::Printf(TEXT("%s: got %.17g, expected %.17g"), *What, Actual, Expected));
			return false;
		}
		return true;
	}

	/** Angles compared on the circle, so 180 and -180 + epsilon agree. */
	bool NearAngle(FAutomationTestBase& Test, const FString& What, double ActualDeg, double ExpectedDeg, double Tol)
	{
		const double Delta = FMath::FindDeltaAngleDegrees(ExpectedDeg, ActualDeg);
		if (FMath::Abs(Delta) > Tol)
		{
			Test.AddError(FString::Printf(TEXT("%s: got %.17g deg, expected %.17g deg"), *What, ActualDeg, ExpectedDeg));
			return false;
		}
		return true;
	}

	bool NearQuat(FAutomationTestBase& Test, const FString& What, const FQuat& A, const FQuat& B, double Tol)
	{
		if (FMath::Abs(A.X - B.X) > Tol || FMath::Abs(A.Y - B.Y) > Tol || FMath::Abs(A.Z - B.Z) > Tol || FMath::Abs(A.W - B.W) > Tol)
		{
			Test.AddError(FString::Printf(TEXT("%s: got (%.15g, %.15g, %.15g, %.15g), expected (%.15g, %.15g, %.15g, %.15g)"), *What,
				A.X, A.Y, A.Z, A.W, B.X, B.Y, B.Z, B.W));
			return false;
		}
		return true;
	}

	FVerseThreeVector RandomThree(FVerseRng& Rng, double Extent)
	{
		return T(Rng.Range(-Extent, Extent), Rng.Range(-Extent, Extent), Rng.Range(-Extent, Extent));
	}

	FQuat RandomUnitQuat(FVerseRng& Rng)
	{
		FQuat Q(Rng.Gaussian(), Rng.Gaussian(), Rng.Gaussian(), Rng.Gaussian());
		Q.Normalize();
		return Q;
	}

	TSharedPtr<FJsonObject> LoadGolden(FAutomationTestBase& Test)
	{
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/coords_golden.json"));
		FString Text;
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			Test.AddError(FString::Printf(TEXT("cannot read %s"), *Path));
			return nullptr;
		}
		TSharedPtr<FJsonObject> Root;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
		{
			Test.AddError(FString::Printf(TEXT("cannot parse %s"), *Path));
			return nullptr;
		}
		Test.TestEqual(TEXT("golden schema"), Root->GetStringField(TEXT("schema")), FString(TEXT("verse.coords_golden/1")));
		return Root;
	}

	TArray<double> Numbers(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		TArray<double> Out;
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Object->TryGetArrayField(Field, Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				Out.Add(Value->AsNumber());
			}
		}
		return Out;
	}

	FVector Vec(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		const TArray<double> N = Numbers(Object, Field);
		return N.Num() == 3 ? FVector(N[0], N[1], N[2]) : FVector(TNumericLimits<double>::Max());
	}

	FVerseThreeVector Three(const TSharedPtr<FJsonObject>& Object, const TCHAR* Field)
	{
		const FVector V = Vec(Object, Field);
		return T(V.X, V.Y, V.Z);
	}

	TArray<TSharedPtr<FJsonObject>> Rows(const TSharedPtr<FJsonObject>& Root, const TCHAR* Field)
	{
		TArray<TSharedPtr<FJsonObject>> Out;
		const TArray<TSharedPtr<FJsonValue>>* Values = nullptr;
		if (Root.IsValid() && Root->TryGetArrayField(Field, Values))
		{
			for (const TSharedPtr<FJsonValue>& Value : *Values)
			{
				Out.Add(Value->AsObject());
			}
		}
		return Out;
	}

	/** Positions of the given table ("3.1", "3.2"), or every row when Table is empty. Returns the row count. */
	int32 CheckPositions(FAutomationTestBase& Test, const TSharedPtr<FJsonObject>& Root, const FString& Table)
	{
		int32 Count = 0;
		for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("positions")))
		{
			if (!Table.IsEmpty() && Row->GetStringField(TEXT("table")) != Table)
			{
				continue;
			}
			const FString Name = Row->GetStringField(TEXT("name"));
			FVerseDeckFrame Deck;
			Deck.OriginCm = Vec(Row, TEXT("deck_origin_cm"));
			const FVerseThreeVector In = Three(Row, TEXT("three"));
			const FVector Expected = Vec(Row, TEXT("unreal"));
			Near(Test, Name + TEXT(" T->U"), ToUnrealPosition(In, Deck), Expected, PosTol);
			Near(Test, Name + TEXT(" U->T"), ToThreePosition(Expected, Deck), In, PosTol / 100.0);
			++Count;
		}
		return Count;
	}
}

using namespace VerseCoordsTest;

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsBasisTest, "Verse.Contract.Coords.Basis", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsBasisTest::RunTest(const FString&)
{
	Near(*this, TEXT("T +X"), ToUnrealPosition(T(1, 0, 0)), FVector(100, 0, 0), PosTol);
	Near(*this, TEXT("T +Y"), ToUnrealPosition(T(0, 1, 0)), FVector(0, 0, 100), PosTol);
	Near(*this, TEXT("T +Z"), ToUnrealPosition(T(0, 0, 1)), FVector(0, 100, 0), PosTol);
	Near(*this, TEXT("MetresToCm"), MetresToCm(1.0), 100.0, PosTol);
	Near(*this, TEXT("CmToMetres"), CmToMetres(250.0), 2.5, PosTol);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsHandednessTest, "Verse.Contract.Coords.Handedness", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsHandednessTest::RunTest(const FString&)
{
	// det(M) with M's columns the images of the T basis.
	const FMatrix M(ToUnrealDirection(T(1, 0, 0)), ToUnrealDirection(T(0, 1, 0)), ToUnrealDirection(T(0, 0, 1)), FVector::ZeroVector);
	Near(*this, TEXT("det(M)"), M.Determinant(), -1.0, DirTol);

	FVerseRng Rng(Seed, 0, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 1000; ++I)
	{
		const FVerseThreeVector A = RandomThree(Rng, 10.0);
		const FVerseThreeVector B = RandomThree(Rng, 10.0);
		const FVector Lhs = ToUnrealDirection(Cross(A, B));
		const FVector Rhs = -FVector::CrossProduct(ToUnrealDirection(A), ToUnrealDirection(B));
		if (!Near(*this, FString::Printf(TEXT("cross pair %d"), I), Lhs, Rhs, 1e-12 * 100.0))
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsRoundTripTest, "Verse.Contract.Coords.RoundTripPosition", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsRoundTripTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 1, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		FVerseDeckFrame Deck;
		Deck.OriginCm = FVector(Rng.Range(-1e6, 1e6), Rng.Range(-1e6, 1e6), Rng.Range(-1e5, 1e5));
		const FVerseThreeVector P = RandomThree(Rng, 10000.0); // +-10 km
		const FVector U = ToUnrealPosition(P, Deck);
		const FVector UBack = ToUnrealPosition(ToThreePosition(U, Deck), Deck);
		const bool bOk = Near(*this, FString::Printf(TEXT("T->U->T %d"), I), ToThreePosition(U, Deck), P, PosTol / 100.0)
			&& Near(*this, FString::Printf(TEXT("U->T->U %d"), I), UBack, U, PosTol);
		if (!bOk)
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsHangarGoldenTest, "Verse.Contract.Coords.HangarGolden", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsHangarGoldenTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> Root = LoadGolden(*this);
	if (!Root)
	{
		return false;
	}
	TestEqual(TEXT("table 3.1 rows"), CheckPositions(*this, Root, TEXT("3.1")), 13);
	TestEqual(TEXT("table 3.2 rows"), CheckPositions(*this, Root, TEXT("3.2")), 4);

	int32 Spawns = 0;
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("headings")))
	{
		if (Row->GetStringField(TEXT("table")) != TEXT("3.2"))
		{
			continue;
		}
		const FString Name = Row->GetStringField(TEXT("name"));
		const double YawDeg = Row->GetNumberField(TEXT("three_yaw_deg"));
		Near(*this, Name + TEXT(" heading"), ToUnrealHeadingDegFromDeg(YawDeg), Row->GetNumberField(TEXT("unreal_heading_deg")), AngTol);
		Near(*this, Name + TEXT(" mesh yaw"), UVerseCoordsLibrary::ThreeYawDegToUnrealMeshYaw(YawDeg), Row->GetNumberField(TEXT("unreal_mesh_yaw_deg")), AngTol);
		++Spawns;
	}
	TestEqual(TEXT("table 3.2 spawn headings"), Spawns, 3);

	// The commander spawn as a manifest socket, both uses.
	const FTransform Heading = ToUnrealSocketTransform(T(70, 0, 54.2), 0.0, ESocketUse::Heading);
	const FTransform Mesh = ToUnrealSocketTransform(T(70, 0, 54.2), 0.0, ESocketUse::Mesh);
	Near(*this, TEXT("socket location"), Heading.GetLocation(), FVector(7000, 5420, 0), PosTol);
	NearAngle(*this, TEXT("socket heading yaw"), Heading.Rotator().Yaw, 90.0, AngTol);
	NearAngle(*this, TEXT("socket mesh yaw"), Mesh.Rotator().Yaw, 0.0, AngTol);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsHeadingDirTest, "Verse.Contract.Coords.HeadingMatchesDirFromAngles", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsHeadingDirTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 2, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		const double Yaw = Rng.Range(-UE_DOUBLE_PI, UE_DOUBLE_PI);
		const double Pitch = Rng.Range(-0.49 * UE_DOUBLE_PI, 0.49 * UE_DOUBLE_PI);
		if (!Near(*this, FString::Printf(TEXT("view %d"), I), ToUnrealViewRotation(Yaw, Pitch).Vector(),
			ToUnrealDirection(DirFromAngles(Yaw, Pitch)), DirTol))
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsRightAxisTest, "Verse.Contract.Coords.RightAxisParity", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsRightAxisTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 3, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		const double Yaw = Rng.Range(-UE_DOUBLE_PI, UE_DOUBLE_PI);
		const FVector Right = ToUnrealDirection(T(-FMath::Cos(Yaw), 0.0, FMath::Sin(Yaw)));
		const double HeadingRad = FMath::DegreesToRadians(ToUnrealHeadingDeg(Yaw));
		// The pawn's right axis of yaw phi is (-sin phi, cos phi, 0), exact in double.
		const FVector Exact(-FMath::Sin(HeadingRad), FMath::Cos(HeadingRad), 0.0);
		// FRotationMatrix evaluates its sines in single precision, so it agrees to 1e-6 only.
		const FVector Engine = FRotationMatrix(FRotator(0.0, ToUnrealHeadingDeg(Yaw), 0.0)).GetUnitAxis(EAxis::Y);
		const bool bOk = Near(*this, FString::Printf(TEXT("right %d"), I), Right, Exact, DirTol)
			&& Near(*this, FString::Printf(TEXT("engine right axis %d"), I), Right, Engine, 1e-6);
		if (!bOk)
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsYawWrapTest, "Verse.Contract.Coords.YawWrap", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsYawWrapTest::RunTest(const FString&)
{
	Near(*this, TEXT("psi -90 -> 180"), ToUnrealHeadingDeg(-UE_DOUBLE_HALF_PI), 180.0, AngTol);
	Near(*this, TEXT("psi 180 -> -90"), ToUnrealHeadingDeg(UE_DOUBLE_PI), -90.0, AngTol);
	Near(*this, TEXT("WrapPi(-pi) = pi"), WrapPi(-UE_DOUBLE_PI), UE_DOUBLE_PI, DirTol);
	Near(*this, TEXT("Normalize(-180) = 180"), NormalizeDeg(-180.0), 180.0, AngTol);

	FVerseRng Rng(Seed, 4, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		const double Yaw = Rng.Range(-20.0, 20.0);
		const double Heading = ToUnrealHeadingDeg(Yaw);
		const double Back = ToThreeYawRad(Rng.Range(-1000.0, 1000.0));
		const bool bOk = TestTrue(TEXT("heading in (-180, 180]"), Heading > -180.0 && Heading <= 180.0)
			&& TestTrue(TEXT("three yaw in (-pi, pi]"), Back > -UE_DOUBLE_PI && Back <= UE_DOUBLE_PI)
			&& Near(*this, TEXT("round trip"), ToThreeYawRad(Heading), WrapPi(Yaw), 1e-12);
		if (!bOk)
		{
			break;
		}
	}

	const TSharedPtr<FJsonObject> Root = LoadGolden(*this);
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("headings")))
	{
		const FString Name = Row->GetStringField(TEXT("name"));
		const double YawRad = Row->GetNumberField(TEXT("three_yaw_rad"));
		const double Heading = Row->GetNumberField(TEXT("unreal_heading_deg"));
		Near(*this, Name + TEXT(" heading"), ToUnrealHeadingDeg(YawRad), Heading, AngTol);
		Near(*this, Name + TEXT(" back"), ToThreeYawRad(Heading), Row->GetNumberField(TEXT("three_yaw_rad_back")), 1e-12);
		Near(*this, Name + TEXT(" round trip"), ToThreeYawRad(ToUnrealHeadingDeg(YawRad)), WrapPi(YawRad), 1e-12);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsQuatTest, "Verse.Contract.Coords.QuatConjugation", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsQuatTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 5, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		const FQuat QT = RandomUnitQuat(Rng);
		const FVerseThreeVector V = RandomThree(Rng, 5.0);
		const FVector TRotated = QT.RotateVector(FVector(V.X, V.Y, V.Z));
		const FVector Lhs = ToUnrealQuat(QT).RotateVector(MOf(V));
		const FVector Rhs = MOf(T(TRotated.X, TRotated.Y, TRotated.Z));
		const bool bOk = Near(*this, FString::Printf(TEXT("conjugation %d"), I), Lhs, Rhs, 1e-12 * 10.0)
			&& NearQuat(*this, FString::Printf(TEXT("inverse %d"), I), ToThreeQuat(ToUnrealQuat(QT)), QT, 0.0);
		if (!bOk)
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsMeshYawTest, "Verse.Contract.Coords.MeshYawIsHeadingMinus90", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsMeshYawTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 6, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 10000; ++I)
	{
		const double Yaw = I < 8 ? double(I - 4) * UE_DOUBLE_HALF_PI * 0.5 : Rng.Range(-UE_DOUBLE_PI, UE_DOUBLE_PI);
		const double MeshYaw = ToUnrealMeshYawDeg(Yaw);
		const FQuat YawOnly(0.0, FMath::Sin(0.5 * Yaw), 0.0, FMath::Cos(0.5 * Yaw)); // about three.js +Y
		const bool bOk = NearAngle(*this, FString::Printf(TEXT("heading - 90, %d"), I), NormalizeDeg(ToUnrealHeadingDeg(Yaw) - 90.0), MeshYaw, AngTol)
			&& NearAngle(*this, FString::Printf(TEXT("quaternion route, %d"), I), ToUnrealQuat(YawOnly).Rotator().Yaw, MeshYaw, 1e-8)
			&& TestTrue(TEXT("mesh yaw in (-180, 180]"), MeshYaw > -180.0 && MeshYaw <= 180.0);
		if (!bOk)
		{
			break;
		}
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsBoxOrderTest, "Verse.Contract.Coords.BoxOrder", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsBoxOrderTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> Root = LoadGolden(*this);
	const TArray<TSharedPtr<FJsonObject>> Boxes = Rows(Root, TEXT("arena_boxes"));
	TestTrue(TEXT("golden file has arena boxes"), Boxes.Num() > 0);
	for (const TSharedPtr<FJsonObject>& Row : Boxes)
	{
		const FString Id = Row->GetStringField(TEXT("id"));
		const TSharedPtr<FJsonObject> B = Row->GetObjectField(TEXT("three"));
		const FBox Box = ToUnrealBox(B->GetNumberField(TEXT("x0")), B->GetNumberField(TEXT("x1")), B->GetNumberField(TEXT("y0")),
			B->GetNumberField(TEXT("y1")), B->GetNumberField(TEXT("z0")), B->GetNumberField(TEXT("z1")));
		TestTrue(Id + TEXT(" min <= max"), Box.Min.X <= Box.Max.X && Box.Min.Y <= Box.Max.Y && Box.Min.Z <= Box.Max.Z);
		Near(*this, Id + TEXT(" min"), Box.Min, Vec(Row, TEXT("unreal_min")), PosTol);
		Near(*this, Id + TEXT(" max"), Box.Max, Vec(Row, TEXT("unreal_max")), PosTol);
	}
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsDeckFrameTest, "Verse.Contract.Coords.DeckFrameTranslationOnly", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsDeckFrameTest::RunTest(const FString&)
{
	FVerseRng Rng(Seed, 7, EVerseRngSalt::Harness);
	for (int32 I = 0; I < 1000; ++I)
	{
		FVerseDeckFrame Deck;
		Deck.OriginCm = FVector(Rng.Range(-1e6, 1e6), Rng.Range(-1e6, 1e6), Rng.Range(-1e5, 1e5));
		const FVerseThreeVector P = RandomThree(Rng, 100.0);
		const double YawDeg = Rng.Range(-180.0, 180.0);
		const bool bOk = Near(*this, TEXT("offset is exactly OriginCm"), ToUnrealPosition(P, Deck) - ToUnrealPosition(P), Deck.OriginCm, PosTol)
			&& Near(*this, TEXT("box min offset"), ToUnrealBox(P.X, P.X + 1, P.Y, P.Y + 1, P.Z, P.Z + 1, Deck).Min,
				ToUnrealBox(P.X, P.X + 1, P.Y, P.Y + 1, P.Z, P.Z + 1).Min + Deck.OriginCm, PosTol)
			&& NearQuat(*this, TEXT("socket rotation unchanged"),
				ToUnrealSocketTransform(P, YawDeg, ESocketUse::Heading, Deck).GetRotation(),
				ToUnrealSocketTransform(P, YawDeg, ESocketUse::Heading).GetRotation(), 0.0);
		if (!bOk)
		{
			break;
		}
	}
	// Directions, headings and quaternions take no frame at all: the API has no deck parameter for them.
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsYawRateTest, "Verse.Contract.Coords.YawRateSign", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsYawRateTest::RunTest(const FString&)
{
	Near(*this, TEXT("+1 rad/s"), ToUnrealYawRateDeg(1.0), -57.29577951308232, AngTol);
	Near(*this, TEXT("+2 rad/s"), ToUnrealYawRateDeg(2.0), -114.59155902616465, AngTol);
	return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseCoordsCrossLanguageTest, "Verse.Contract.Coords.CrossLanguageGolden", VERSE_COORDS_TEST_FLAGS)
bool FVerseCoordsCrossLanguageTest::RunTest(const FString&)
{
	const TSharedPtr<FJsonObject> Root = LoadGolden(*this);
	if (!Root)
	{
		return false;
	}
	TestTrue(TEXT("positions"), CheckPositions(*this, Root, FString()) > 0);

	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("directions")))
	{
		const FString Name = Row->GetStringField(TEXT("name"));
		Near(*this, Name + TEXT(" T->U"), ToUnrealDirection(Three(Row, TEXT("three"))), Vec(Row, TEXT("unreal")), DirTol);
		Near(*this, Name + TEXT(" U->T"), ToThreeDirection(Vec(Row, TEXT("unreal"))), Three(Row, TEXT("three")), DirTol);
	}
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("headings")))
	{
		const FString Name = Row->GetStringField(TEXT("name"));
		const double YawRad = Row->GetNumberField(TEXT("three_yaw_rad"));
		Near(*this, Name + TEXT(" heading"), ToUnrealHeadingDeg(YawRad), Row->GetNumberField(TEXT("unreal_heading_deg")), AngTol);
		NearAngle(*this, Name + TEXT(" mesh yaw"), ToUnrealMeshYawDeg(YawRad), Row->GetNumberField(TEXT("unreal_mesh_yaw_deg")), AngTol);
		Near(*this, Name + TEXT(" forward"), ToUnrealViewRotation(YawRad, 0.0).Vector(), Vec(Row, TEXT("unreal_forward")), DirTol);
		Near(*this, Name + TEXT(" forward via M"), ToUnrealDirection(Three(Row, TEXT("three_forward"))), Vec(Row, TEXT("unreal_forward")), DirTol);
	}
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("views")))
	{
		const FString Name = Row->GetStringField(TEXT("name"));
		const FRotator R = ToUnrealViewRotation(Row->GetNumberField(TEXT("three_yaw_rad")), Row->GetNumberField(TEXT("three_pitch_rad")));
		const FVector Pyr = Vec(Row, TEXT("unreal_rotator_pyr"));
		Near(*this, Name + TEXT(" pitch"), R.Pitch, Pyr.X, AngTol);
		NearAngle(*this, Name + TEXT(" yaw"), R.Yaw, Pyr.Y, AngTol);
		Near(*this, Name + TEXT(" roll"), R.Roll, Pyr.Z, AngTol);
		Near(*this, Name + TEXT(" forward"), R.Vector(), Vec(Row, TEXT("unreal_forward")), DirTol);
	}
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("quaternions")))
	{
		const FString Name = Row->GetStringField(TEXT("name"));
		const TArray<double> QT = Numbers(Row, TEXT("three_xyzw"));
		const TArray<double> QU = Numbers(Row, TEXT("unreal_xyzw"));
		if (!TestTrue(Name + TEXT(" has 4 components"), QT.Num() == 4 && QU.Num() == 4))
		{
			continue;
		}
		const FQuat QThree(QT[0], QT[1], QT[2], QT[3]);
		const FQuat QUnreal(QU[0], QU[1], QU[2], QU[3]);
		NearQuat(*this, Name + TEXT(" T->U"), ToUnrealQuat(QThree), QUnreal, DirTol);
		NearQuat(*this, Name + TEXT(" U->T"), ToThreeQuat(QUnreal), QThree, DirTol);
		double ExpectedYaw = 0.0;
		if (Row->TryGetNumberField(TEXT("unreal_yaw_deg"), ExpectedYaw))
		{
			NearAngle(*this, Name + TEXT(" yaw"), ToUnrealQuat(QThree).Rotator().Yaw, ExpectedYaw, 1e-8);
		}
	}
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("yaw_rates")))
	{
		Near(*this, TEXT("yaw rate"), ToUnrealYawRateDeg(Row->GetNumberField(TEXT("three_rad_s"))), Row->GetNumberField(TEXT("unreal_deg_s")), AngTol);
	}
	for (const TSharedPtr<FJsonObject>& Row : Rows(Root, TEXT("speeds")))
	{
		Near(*this, Row->GetStringField(TEXT("name")), MetresToCm(Row->GetNumberField(TEXT("three_m_s"))), Row->GetNumberField(TEXT("unreal_cm_s")), PosTol);
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"

#include "VerseCoords.generated.h"

// The one conversion between the three.js Verse frame (T: metres, right-handed, +Y up,
// yaw 0 faces +Z) and the Unreal frame (U: centimetres, left-handed, +Z up, yaw 0 faces +X).
// Frozen by docs/verse/unreal/contracts/coordinates.md; nothing else re-derives the mapping.

/** A point or vector in the three.js Verse frame: metres, +Y up, +Z toward the plate camera.
 *  A distinct type so a metre value can never be passed where an Unreal FVector is expected. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseThreeVector
{
	GENERATED_BODY()

	FVerseThreeVector() = default;
	FVerseThreeVector(double InX, double InY, double InZ) : X(InX), Y(InY), Z(InZ) {}

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Coords")
	double X = 0.0;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Coords")
	double Y = 0.0;

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Coords")
	double Z = 0.0;
};

/** A deck's world placement: translation only, in centimetres. Owned by VerseDecks. */
USTRUCT(BlueprintType)
struct VERSECORE_API FVerseDeckFrame
{
	GENERATED_BODY()

	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Verse|Coords")
	FVector OriginCm = FVector::ZeroVector;

	static FVerseDeckFrame Local() { return FVerseDeckFrame(); }
};

namespace Verse::Coords
{
	inline constexpr double CmPerMetre = 100.0;

	// Scalars
	VERSECORE_API double MetresToCm(double Metres);
	VERSECORE_API double CmToMetres(double Cm);

	// Points (scaled and offset) and directions (swapped only)
	VERSECORE_API FVector            ToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());
	VERSECORE_API FVerseThreeVector  ToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());
	VERSECORE_API FVector            ToUnrealDirection(const FVerseThreeVector& D);
	VERSECORE_API FVerseThreeVector  ToThreeDirection(const FVector& D);
	VERSECORE_API FBox               ToUnrealBox(double X0, double X1, double Y0, double Y1, double Z0, double Z1,
	                                             const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());

	// Heading (gameplay forward, +X)
	VERSECORE_API double   ToUnrealHeadingDeg(double ThreeYawRad);        // Normalize(90 - deg(yaw))
	VERSECORE_API double   ToUnrealHeadingDegFromDeg(double ThreeYawDeg); // manifest yaw_deg
	VERSECORE_API double   ToThreeYawRad(double UnrealYawDeg);            // WrapPi(rad(90 - yaw))
	VERSECORE_API double   ToUnrealYawRateDeg(double ThreeYawRateRad);    // sign flips
	VERSECORE_API FRotator ToUnrealViewRotation(double ThreeYawRad, double ThreePitchRad);

	// Object rotation (geometry as authored; mesh front = local +Y)
	VERSECORE_API double   ToUnrealMeshYawDeg(double ThreeYawRad);        // Normalize(-deg(yaw)) == heading - 90
	VERSECORE_API FQuat    ToUnrealQuat(const FQuat& ThreeQuat);          // (-x, -z, -y, w)
	VERSECORE_API FQuat    ToThreeQuat(const FQuat& UnrealQuat);          // (-x, -z, -y, w)

	// Manifest sockets: position + yaw_deg in one step
	enum class ESocketUse : uint8 { Heading, Mesh };
	VERSECORE_API FTransform ToUnrealSocketTransform(const FVerseThreeVector& P, double ThreeYawDeg, ESocketUse Use,
	                                                 const FVerseDeckFrame& Deck = FVerseDeckFrame::Local());

	/** Angle in degrees normalised to (-180, 180] (FRotator::NormalizeAxis). */
	VERSECORE_API double NormalizeDeg(double Deg);
	/** Angle in radians wrapped to (-pi, pi]. */
	VERSECORE_API double WrapPi(double Rad);
}

/** Blueprint and editor-utility access; same functions, no extra logic. */
UCLASS()
class VERSECORE_API UVerseCoordsLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintPure, Category = "Verse|Coords")
	static FVector ThreeToUnrealPosition(const FVerseThreeVector& P, const FVerseDeckFrame& Deck);

	UFUNCTION(BlueprintPure, Category = "Verse|Coords")
	static FVerseThreeVector UnrealToThreePosition(const FVector& PCm, const FVerseDeckFrame& Deck);

	UFUNCTION(BlueprintPure, Category = "Verse|Coords")
	static double ThreeYawDegToUnrealHeading(double ThreeYawDeg);

	UFUNCTION(BlueprintPure, Category = "Verse|Coords")
	static double ThreeYawDegToUnrealMeshYaw(double ThreeYawDeg);
};

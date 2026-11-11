#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseSpaceView.generated.h"

class UStaticMeshComponent;
class UMaterialInterface;

/**
 * How space looks outside the windows (WP12.9), the same knobs as today's `SPACE_LOOK`
 * (`engine/realtime/spaceView.ts:50-66`): Earth in low orbit below and ahead of the viewports,
 * the sun, the stars, turning at about orbital speed.
 */
struct VERSEDECKS_API FVerseSpaceLook
{
	double AltitudeKm = 900.0;
	double CentreDownDeg = 56.0;
	double RollDeg = -9.0;
	double LatDeg = 40.0;
	double LonDeg = -68.0;
	double SunAzimuthDeg = 15.0;
	double SunElevationDeg = 32.0;
	double SunRadiance = 8.0;
	double NightGain = 3.0;
	double HazeGain = 0.6;
	double StarGain = 1.0;
	/** Ground speed as a multiple of the real one (7.7 km/s). */
	double OrbitSpeed = 2.0;
	/** QA: 0 leaves the planet out. */
	double Planet = 1.0;

	/** Earth radius and orbital ground speed of today's view. */
	static constexpr double EarthKm = 6371.0;
	static constexpr double GroundKmPerS = 7.7;

	/** Turn rate of the Earth under the ship, radians per second (`ORBIT_RAD_PER_S * orbitSpeed`). */
	double OrbitRadPerS() const { return GroundKmPerS / EarthKm * OrbitSpeed; }

	/** Sets one field by today's JSON name (`orbitSpeed`, `latDeg`, ...). False for an unknown name. */
	bool Set(const FString& Field, double Value);
	/** Every field by today's JSON name, plus `orbit_rad_per_s`. */
	FString ToJson(double ElapsedS) const;
	/** Every field name `Set` takes. */
	static TConstArrayView<const TCHAR*> FieldNames();
};

/** The per-frame values of the space shader (`SpaceView.update` in spaceView.ts), three.js axes. */
struct VERSEDECKS_API FVerseSpaceFrame
{
	/** Earth centre from the camera, Earth radii. */
	FVector EarthCentre = FVector::ZeroVector;
	/** Rows of `worldToEarth` (world direction -> the texture frame of the Earth's maps). */
	FVector Rows[3] = { FVector::XAxisVector, FVector::YAxisVector, FVector::ZAxisVector };
	FVector SunDir = FVector::YAxisVector;
	double Spin = 0.0;
	double CloudSpin = 0.0;

	/** `SpaceView.update` for windows looking along `OutwardThree` (three.js axes, level). */
	static FVerseSpaceFrame Compute(const FVerseSpaceLook& Look, const FVector& OutwardThree, double ElapsedS);
};

/**
 * The space view (WP12.9, parity with `engine/realtime/spaceView.ts`): the Earth in low orbit, its
 * atmosphere, the sun and the stars, drawn per pixel by `M_Verse_Space` from the view direction
 * alone, so the view sits at infinity and walking past a window shows no parallax (parity Z-11).
 * Two surfaces draw it: the decks' star cards behind the viewports (`MI_Starfield`,
 * `MI_Ops_Starfield`), and a dome around the camera (`SM_Space_StarDome` with `MI_Space_Earth`)
 * for glass with nothing behind it. Each tick writes the frame to `MPC_Verse_Space`.
 */
UCLASS()
class VERSEDECKS_API AVerseSpaceView : public AActor
{
	GENERATED_BODY()

public:
	AVerseSpaceView();

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	/** Asset paths of the backdrop. */
	static const TCHAR* StarDomeMeshPath;
	static const TCHAR* EarthMaterialPath;
	static const TCHAR* StarsMaterialPath;
	static const TCHAR* CollectionPath;

	static constexpr double DomeRadiusCm = 300000.0;

	/** Loads the dome, both instances and the parameter collection; returns how many of the four were found. */
	int32 LoadBackdrop();

	/** Which way the deck's viewports look out (Unreal axes, level). */
	void SetOutward(const FVector& Direction);
	FVector GetOutward() const { return Outward; }

	/** The frame of the current tick (what the shader gets). */
	FVerseSpaceFrame Frame() const;

	FVerseSpaceLook Look;
	double ElapsedS = 0.0;

	/** Radians the Earth has turned since the view started. */
	double EarthTurnRad() const { return ElapsedS * Look.OrbitRadPerS(); }

	UPROPERTY(VisibleAnywhere, Category = "Verse|Space")
	TObjectPtr<USceneComponent> Root;

	/** The dome around the camera that draws space where glass has nothing behind it. */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Space")
	TObjectPtr<UStaticMeshComponent> Stars;

	/** Tests: a material the dome wears instead of the view (the tonemap calibration ramp). */
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> DomeOverride;

private:
	void PushFrame();

	FVector Outward = FVector(1.0, 0.0, 0.0);
	UPROPERTY(Transient)
	TObjectPtr<class UMaterialParameterCollection> Collection;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> EarthMaterial;
	UPROPERTY(Transient)
	TObjectPtr<UMaterialInterface> StarsMaterial;
};

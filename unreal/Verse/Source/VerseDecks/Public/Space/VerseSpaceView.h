#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseSpaceView.generated.h"

class UStaticMeshComponent;

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

/**
 * The space view: a backdrop at infinity that turns with the orbit. It follows the camera, so
 * walking past a window shows no parallax (parity Z-11). The Earth and star meshes are assigned
 * from the CC0 ledger textures by the space-view assets; without them the actor still keeps
 * time and answers `Verse.QA.Space.*`.
 */
UCLASS()
class VERSEDECKS_API AVerseSpaceView : public AActor
{
	GENERATED_BODY()

public:
	AVerseSpaceView();

	virtual void Tick(float DeltaSeconds) override;

	FVerseSpaceLook Look;
	double ElapsedS = 0.0;

	/** Radians the Earth has turned since the view started. */
	double EarthTurnRad() const { return ElapsedS * Look.OrbitRadPerS(); }

	UPROPERTY(VisibleAnywhere, Category = "Verse|Space")
	TObjectPtr<USceneComponent> Root;

	/** The Earth sphere (rotates about its axis with the orbit). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Space")
	TObjectPtr<UStaticMeshComponent> Earth;

	/** The star dome (fixed in space). */
	UPROPERTY(VisibleAnywhere, Category = "Verse|Space")
	TObjectPtr<UStaticMeshComponent> Stars;
};

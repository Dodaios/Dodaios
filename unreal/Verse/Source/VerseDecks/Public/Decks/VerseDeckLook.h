#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"

#include "VerseDeckLook.generated.h"

struct FVerseDeckManifest;
struct FVerseDeckSocket;
class UExponentialHeightFogComponent;
class ULocalLightComponent;

/**
 * Military-Industrial Noir per deck (WP12.8, contracts/art-pipeline.md 8): hard work lights at
 * 4300-6500 K with shadows, deep falloff, neutral grey haze, amber and red only as small practical
 * lamps. All lights are Movable and come from the deck's `light` sockets (art-pipeline 6.3).
 */
struct VERSEDECKS_API FVerseDeckLook
{
	FName Deck;
	/** Exponential height fog density and falloff. */
	double FogDensity = 0.02;
	double FogHeightFalloff = 0.2;
	/** Volumetric fog extinction scale (haze in the light shafts). */
	double VolumetricExtinction = 1.0;
	/** Neutral grey scattering (art-pipeline 8.2: never coloured fog). */
	FLinearColor FogAlbedo = FLinearColor(0.9f, 0.9f, 0.9f);
	/** Fixed manual exposure (art-pipeline 7, "Tone map"), EV100. */
	double ExposureEV100 = 6.0;
	/** Work-light temperature where a socket gives none, kelvin. */
	double WorkLightKelvin = 5600.0;
	/**
	 * Unreal yaw (degrees) the commander and the deck camera take on arrival, when the deck's
	 * arrival sockets face a wall in third person (their yaw faces the web deck's fixed camera).
	 * Unset: the socket's own heading.
	 */
	TOptional<double> ArrivalYawDeg;
	/**
	 * World point (cm, on the floor) the commander and the camera arrive at instead of the socket,
	 * when the socket stands in a closed room (the hangar's lift lobby has a ceiling over it).
	 * Unset: the socket's own location.
	 */
	TOptional<FVector> ArrivalLocationCm;
	/** Camera pitch (degrees, up positive) of the first third-person frame on arrival. */
	TOptional<double> ArrivalPitchDeg;

	static FVerseDeckLook For(FName Deck);
};

namespace Verse::DeckLook
{
	/** Lowest and highest work-light temperature (art-pipeline 8.2). */
	inline constexpr double MinKelvin = 4300.0;
	inline constexpr double MaxKelvin = 6500.0;
	/** Brightest single light a socket becomes, lumen. */
	inline constexpr double MaxLumen = 20000.0;

	/**
	 * Why an emissive or light colour (sRGB, 0..1) breaks the colour bans of art-pipeline 8.3, or an
	 * empty string: cyan, violet/purple/magenta, saturated green light, info blue in the world.
	 */
	VERSEDECKS_API FString BannedLightColour(const FLinearColor& Srgb);

	/** The rendered-pixel rule of art-pipeline 8.3 for screenshots: hue 160-330, saturation > 0.25, value > 0.08. */
	VERSEDECKS_API bool IsBannedPixel(const FColor& Pixel);

	/** Fog colour rule of art-pipeline 8.3: saturation at most 0.1. */
	VERSEDECKS_API bool IsNeutralFog(const FLinearColor& Albedo);

	/** `#rrggbb` -> sRGB colour; false on bad text. */
	VERSEDECKS_API bool ParseHex(const FString& Hex, FLinearColor& OutSrgb);

	/** What a light socket becomes: kelvin for work lights, a colour for practical lamps. */
	struct FLightSpec
	{
		FName Type;
		bool bUseTemperature = true;
		double Kelvin = 5600.0;
		FLinearColor Colour = FLinearColor::White;
		double Lumen = 0.0;
		double AttenuationCm = 0.0;
		double SourceSizeCm = 0.0;
		double BlinkHz = 0.0;
	};

	/** The light a socket asks for, clamped into the Noir rules. False for a socket that is not a light. */
	VERSEDECKS_API bool LightFor(const FVerseDeckSocket& Socket, const FVerseDeckLook& Look, FLightSpec& Out);
}

/** Spawns a deck's lights and haze from its manifest. One per loaded deck, owned by the deck subsystem. */
UCLASS()
class VERSEDECKS_API AVerseDeckLighting : public AActor
{
	GENERATED_BODY()

public:
	AVerseDeckLighting();

	/** Builds one Movable light per `light` socket plus the fog. Returns the number of lights made. */
	int32 Build(const FVerseDeckManifest& Manifest);

	virtual void Tick(float DeltaSeconds) override;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks")
	TObjectPtr<USceneComponent> Root;

	UPROPERTY(VisibleAnywhere, Category = "Verse|Decks")
	TObjectPtr<UExponentialHeightFogComponent> Fog;

	UPROPERTY(Transient)
	TArray<TObjectPtr<ULocalLightComponent>> Lights;

private:
	TArray<double> BlinkHz;
	TArray<float> BaseIntensity;
	double Clock = 0.0;
};

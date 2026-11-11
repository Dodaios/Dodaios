#include "Decks/VerseDeckLook.h"

#include "Components/ExponentialHeightFogComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/RectLightComponent.h"
#include "Components/SpotLightComponent.h"
#include "Decks/VerseDeckManifest.h"
#include "VerseLog.h"

FVerseDeckLook FVerseDeckLook::For(FName Deck)
{
	FVerseDeckLook Look;
	Look.Deck = Deck;
	const FString Id = Deck.ToString();
	if (Id == TEXT("bridge"))
	{
		Look.FogDensity = 0.015;
		Look.ExposureEV100 = 6.5;
		Look.WorkLightKelvin = 6200.0;
	}
	else if (Id == TEXT("ops"))
	{
		Look.FogDensity = 0.02;
		Look.ExposureEV100 = 6.0;
		Look.WorkLightKelvin = 5600.0;
	}
	else if (Id == TEXT("engineering"))
	{
		Look.FogDensity = 0.035;
		Look.FogHeightFalloff = 0.12;
		Look.VolumetricExtinction = 1.6;
		Look.ExposureEV100 = 5.5;
		Look.WorkLightKelvin = 4800.0;
	}
	else if (Id == TEXT("hangar"))
	{
		Look.FogDensity = 0.03;
		Look.FogHeightFalloff = 0.05;
		Look.VolumetricExtinction = 1.4;
		Look.ExposureEV100 = 7.0;
		Look.WorkLightKelvin = 5400.0;
		// The lift and the commander spawn face the lobby's back wall; west looks across the
		// arrivals apron into the hall.
		Look.ArrivalYawDeg = 180.0;
	}
	return Look;
}

namespace Verse::DeckLook
{
	namespace
	{
		void HueSatVal(const FLinearColor& C, double& H, double& S, double& V)
		{
			const double Max = FMath::Max3(C.R, C.G, C.B);
			const double Min = FMath::Min3(C.R, C.G, C.B);
			const double Delta = Max - Min;
			V = Max;
			S = Max <= 0.0 ? 0.0 : Delta / Max;
			if (Delta <= 1e-9)
			{
				H = 0.0;
				return;
			}
			if (Max == C.R)
			{
				H = 60.0 * FMath::Fmod((C.G - C.B) / Delta, 6.0);
			}
			else if (Max == C.G)
			{
				H = 60.0 * ((C.B - C.R) / Delta + 2.0);
			}
			else
			{
				H = 60.0 * ((C.R - C.G) / Delta + 4.0);
			}
			if (H < 0.0)
			{
				H += 360.0;
			}
		}
	}

	FString BannedLightColour(const FLinearColor& Srgb)
	{
		double H = 0.0;
		double S = 0.0;
		double V = 0.0;
		HueSatVal(Srgb, H, S, V);
		if (H >= 160.0 && H <= 210.0 && S > 0.35)
		{
			return TEXT("cyan");
		}
		if (H >= 250.0 && H <= 330.0 && S > 0.2)
		{
			return TEXT("violet");
		}
		if (H >= 90.0 && H < 160.0 && S > 0.5)
		{
			return TEXT("saturated green light");
		}
		if (H > 210.0 && H < 250.0 && S > 0.4)
		{
			return TEXT("info blue");
		}
		return FString();
	}

	bool IsBannedPixel(const FColor& Pixel)
	{
		double H = 0.0;
		double S = 0.0;
		double V = 0.0;
		HueSatVal(FLinearColor(Pixel.R / 255.f, Pixel.G / 255.f, Pixel.B / 255.f), H, S, V);
		return H >= 160.0 && H <= 330.0 && S > 0.25 && V > 0.08;
	}

	bool IsNeutralFog(const FLinearColor& Albedo)
	{
		double H = 0.0;
		double S = 0.0;
		double V = 0.0;
		HueSatVal(Albedo, H, S, V);
		return S <= 0.1;
	}

	bool ParseHex(const FString& Hex, FLinearColor& OutSrgb)
	{
		FString Digits = Hex;
		Digits.RemoveFromStart(TEXT("#"));
		if (Digits.Len() != 6)
		{
			return false;
		}
		for (const TCHAR Char : Digits)
		{
			if (!FChar::IsHexDigit(Char))
			{
				return false;
			}
		}
		const FColor Colour = FColor::FromHex(Digits);
		OutSrgb = FLinearColor(Colour.R / 255.f, Colour.G / 255.f, Colour.B / 255.f);
		return true;
	}

	bool LightFor(const FVerseDeckSocket& Socket, const FVerseDeckLook& Look, FLightSpec& Out)
	{
		if (Socket.Kind != FName(TEXT("light")))
		{
			return false;
		}
		Out = FLightSpec();
		Out.Type = Socket.LightType.IsNone() ? FName(TEXT("point")) : Socket.LightType;
		// One socket can stand for a whole fixture grid; a single light carries at most MaxLumen.
		Out.Lumen = FMath::Min(Socket.LightLumen, MaxLumen);
		Out.AttenuationCm = Socket.LightAttenuationCm;
		Out.SourceSizeCm = Socket.LightSourceSizeCm;
		const double Kelvin = Socket.LightKelvin > 0.0 ? Socket.LightKelvin : Look.WorkLightKelvin;
		Out.Kelvin = FMath::Clamp(Kelvin, MinKelvin, MaxKelvin);
		if (const FString* Blink = Socket.Props.Find(TEXT("blink_hz")))
		{
			Out.BlinkHz = FCString::Atod(**Blink);
		}
		else if (const FString* Pulse = Socket.Props.Find(TEXT("pulse_hz")))
		{
			Out.BlinkHz = FCString::Atod(**Pulse);
		}
		FLinearColor Colour;
		if (const FString* Hex = Socket.Props.Find(TEXT("colour")); Hex && ParseHex(*Hex, Colour))
		{
			if (BannedLightColour(Colour).IsEmpty())
			{
				// A practical lamp: its own colour (amber, red, work-light white), never a banned hue.
				Out.bUseTemperature = false;
				Out.Colour = Colour;
			}
			else
			{
				UE_LOG(LogVerseDecks, Warning, TEXT("light %s: colour %s is banned (%s); using a work light"),
					*Socket.Id.ToString(), **Hex, *BannedLightColour(Colour));
			}
		}
		return true;
	}
}

AVerseDeckLighting::AVerseDeckLighting()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Fog = CreateDefaultSubobject<UExponentialHeightFogComponent>(TEXT("Fog"));
	Fog->SetupAttachment(Root);
}

int32 AVerseDeckLighting::Build(const FVerseDeckManifest& Manifest)
{
	using namespace Verse::DeckLook;

	for (ULocalLightComponent* Light : Lights)
	{
		if (Light)
		{
			Light->DestroyComponent();
		}
	}
	Lights.Reset();
	BlinkHz.Reset();
	BaseIntensity.Reset();

	const FVerseDeckLook Look = FVerseDeckLook::For(Manifest.Deck);
	Fog->SetFogDensity(static_cast<float>(Look.FogDensity));
	Fog->SetFogHeightFalloff(static_cast<float>(Look.FogHeightFalloff));
	Fog->SetVolumetricFog(true);
	Fog->SetVolumetricFogAlbedo(Look.FogAlbedo.ToFColor(true));
	Fog->SetVolumetricFogExtinctionScale(static_cast<float>(Look.VolumetricExtinction));
	Fog->SetFogInscatteringColor(FLinearColor(0.02f, 0.02f, 0.022f));

	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		FLightSpec Spec;
		if (!LightFor(Socket, Look, Spec))
		{
			continue;
		}
		ULocalLightComponent* Light = nullptr;
		if (Spec.Type == FName(TEXT("rect")))
		{
			URectLightComponent* Rect = NewObject<URectLightComponent>(this);
			Rect->SetSourceWidth(static_cast<float>(FMath::Max(10.0, Spec.SourceSizeCm)));
			Rect->SetSourceHeight(static_cast<float>(FMath::Max(10.0, Spec.SourceSizeCm)));
			Light = Rect;
		}
		else if (Spec.Type == FName(TEXT("spot")))
		{
			Light = NewObject<USpotLightComponent>(this);
		}
		else
		{
			Light = NewObject<UPointLightComponent>(this);
		}
		Light->SetMobility(EComponentMobility::Movable);
		Light->SetupAttachment(Root);
		Light->SetRelativeTransform(Socket.Transform);
		// Rect lights face their local +X; ceiling fixtures point down.
		if (Spec.Type == FName(TEXT("rect")))
		{
			Light->SetRelativeRotation(FRotator(-90.0, 0.0, 0.0));
		}
		Light->SetIntensityUnits(ELightUnits::Lumens);
		Light->SetIntensity(static_cast<float>(Spec.Lumen));
		Light->SetAttenuationRadius(static_cast<float>(Spec.AttenuationCm));
		Light->SetCastShadows(true);
		Light->SetUseTemperature(Spec.bUseTemperature);
		Light->SetTemperature(static_cast<float>(Spec.Kelvin));
		Light->SetLightColor(Spec.bUseTemperature ? FLinearColor::White : Spec.Colour);
		Light->RegisterComponent();
		Lights.Add(Light);
		BlinkHz.Add(Spec.BlinkHz);
		BaseIntensity.Add(static_cast<float>(Spec.Lumen));
	}
	UE_LOG(LogVerseDecks, Log, TEXT("deck %s: %d lights, fog %.3f"), *Manifest.Deck.ToString(), Lights.Num(), Look.FogDensity);
	return Lights.Num();
}

void AVerseDeckLighting::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	Clock += DeltaSeconds;
	for (int32 Index = 0; Index < Lights.Num(); ++Index)
	{
		if (BlinkHz[Index] > 0.0 && Lights[Index])
		{
			const bool bOn = FMath::Fmod(Clock * BlinkHz[Index], 1.0) < 0.5;
			Lights[Index]->SetIntensity(bOn ? BaseIntensity[Index] : 0.f);
		}
	}
}

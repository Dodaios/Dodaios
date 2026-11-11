#include "Decks/VerseDeckLook.h"

#include "Components/ExponentialHeightFogComponent.h"
#include "Components/PostProcessComponent.h"
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
		Look.ExposureEV100 = 3.0;
		Look.WorkLightKelvin = 6200.0;
		Look.SpaceOutward = FVector(0.013350, -0.999911, 0.0);
	}
	else if (Id == TEXT("ops"))
	{
		Look.FogDensity = 0.02;
		Look.ExposureEV100 = 4.0;
		Look.WorkLightKelvin = 5600.0;
		Look.SpaceOutward = FVector(-0.377894, -0.925849, 0.0);
	}
	else if (Id == TEXT("engineering"))
	{
		Look.FogDensity = 0.035;
		Look.FogHeightFalloff = 0.12;
		Look.VolumetricExtinction = 1.6;
		Look.ExposureEV100 = 3.5;
		Look.WorkLightKelvin = 4800.0;
		Look.SpaceOutward = FVector(-0.990347, 0.138613, 0.0);
	}
	else if (Id == TEXT("hangar"))
	{
		Look.FogDensity = 0.03;
		Look.FogHeightFalloff = 0.05;
		Look.VolumetricExtinction = 1.4;
		Look.ExposureEV100 = 7.0;
		Look.WorkLightKelvin = 5400.0;
		// The lift and the commander spawn stand in the lift lobby, under its ceiling and facing
		// its back wall. The commander arrives on the apron just outside instead, facing the arena
		// centre (x 5000, y 2400): the cranes, the skylight shafts and the hall in frame.
		// North of the station rooms (arrivals and lift lobby both have ceilings from y 4600 on),
		// so the third-person camera behind the commander stays under the open hall roof; between
		// the cover columns at x 5300 and x 6500.
		Look.ArrivalLocationCm = FVector(6000.0, 4250.0, 0.0);
		Look.ArrivalYawDeg = -118.4;
		Look.ArrivalPitchDeg = 14.0;
		// A slight three-quarter stance: the gold-trimmed cape edge reads along the shoulder.
		Look.ArrivalBodyTurnDeg = 25.0;
		Look.SpaceOutward = FVector(-0.991941, 0.126699, 0.0);
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

namespace VerseDeckLookPrivate
{
	/** Lights with shadows among the fixture grids of one deck (the frame budget). */
	constexpr int32 MaxShadowedFixtures = 10;
	/** Fixtures one socket or one unlit room spreads at most, and the light budget of a deck. */
	constexpr int32 MaxFixturesPerSocket = 24;
	constexpr int32 MaxFixturesPerUnlitRoom = 12;
	constexpr int32 MaxDeckLights = 160;
	/** Lumens of one fixture of the default grid in a room no light socket covers. */
	constexpr double DefaultFixtureLumen = 3000.0;
	/** Fixture height above the floor of an unlit room when no deck light hangs high enough. */
	constexpr double DefaultCeilingCm = 380.0;
	/** Lumens of the glow in front of each screen socket. */
	constexpr double ScreenGlowLumen = 450.0;
}

TArray<FVector> AVerseDeckLighting::FixtureGrid(const FVerseDeckRoom& Room, int32 Count, double ZCm)
{
	FBox2D Bounds(ForceInit);
	for (const FVector2D& P : Room.PolygonCm)
	{
		Bounds += P;
	}
	double Area = 0.0;
	for (int32 I = 0, J = Room.PolygonCm.Num() - 1; I < Room.PolygonCm.Num(); J = I++)
	{
		Area += (Room.PolygonCm[J].X + Room.PolygonCm[I].X) * (Room.PolygonCm[J].Y - Room.PolygonCm[I].Y);
	}
	Area = FMath::Abs(Area) * 0.5;
	// At most one fixture per 3.5 m x 3.5 m and no more than 40 per socket: the light count stays
	// in budget while the room still reads as lit from many sources.
	const int32 Wanted = FMath::Clamp(FMath::Min(Count, int32(Area / (350.0 * 350.0))), 1, VerseDeckLookPrivate::MaxFixturesPerSocket);
	const double Step = FMath::Max(250.0, FMath::Sqrt(Area / Wanted));
	TArray<FVector> Points;
	for (double X = Bounds.Min.X + Step * 0.5; X < Bounds.Max.X; X += Step)
	{
		for (double Y = Bounds.Min.Y + Step * 0.5; Y < Bounds.Max.Y; Y += Step)
		{
			if (Room.ContainsPlan(FVector2D(X, Y)))
			{
				Points.Add(FVector(X, Y, ZCm));
			}
		}
	}
	return Points;
}

AVerseDeckLighting::AVerseDeckLighting()
{
	PrimaryActorTick.bCanEverTick = true;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	RootComponent = Root;
	Fog = CreateDefaultSubobject<UExponentialHeightFogComponent>(TEXT("Fog"));
	Fog->SetupAttachment(Root);
	Post = CreateDefaultSubobject<UPostProcessComponent>(TEXT("Post"));
	Post->SetupAttachment(Root);
	Post->bUnbound = true;
	Post->Priority = 0.f;  // the hangar arena's own volume (priority 10) wins while it stands
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

	FPostProcessSettings& P = Post->Settings;
	P.bOverride_AutoExposureMethod = true;
	P.AutoExposureMethod = AEM_Manual;
	P.bOverride_AutoExposureApplyPhysicalCameraExposure = true;
	P.AutoExposureApplyPhysicalCameraExposure = true;
	// EV100 = log2(N^2 / t) at ISO 100 and f/4: the shutter that gives the look's EV100.
	P.bOverride_CameraISO = true;
	P.CameraISO = 100.f;
	P.bOverride_DepthOfFieldFstop = true;
	P.DepthOfFieldFstop = 4.f;
	P.bOverride_CameraShutterSpeed = true;
	P.CameraShutterSpeed = FMath::Pow(2.f, static_cast<float>(Look.ExposureEV100)) / 16.f;
	P.bOverride_DepthOfFieldFocalDistance = true;
	P.DepthOfFieldFocalDistance = 0.f;
	P.bOverride_AutoExposureBias = true;
	P.AutoExposureBias = 0.f;
	P.bOverride_DynamicGlobalIlluminationMethod = true;
	P.DynamicGlobalIlluminationMethod = EDynamicGlobalIlluminationMethod::Lumen;
	P.bOverride_ReflectionMethod = true;
	P.ReflectionMethod = EReflectionMethod::Lumen;
	P.bOverride_BloomIntensity = true;
	P.BloomIntensity = 0.5f;
	P.bOverride_VignetteIntensity = true;
	P.VignetteIntensity = 0.3f;
	P.bOverride_FilmGrainIntensity = true;
	P.FilmGrainIntensity = 0.1f;
	P.bOverride_ColorContrast = true;
	P.ColorContrast = FVector4(1.1, 1.1, 1.1, 1.0);
	P.bOverride_ColorGainShadows = true;
	P.ColorGainShadows = FVector4(0.92, 0.97, 1.1, 1.0);
	P.bOverride_ColorGainHighlights = true;
	P.ColorGainHighlights = FVector4(1.06, 1.0, 0.9, 1.0);
	P.bOverride_AmbientOcclusionIntensity = true;
	P.AmbientOcclusionIntensity = 0.6f;

	using namespace VerseDeckLookPrivate;
	int32 ShadowedFixtures = 0;
	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		FLightSpec Spec;
		if (!LightFor(Socket, Look, Spec))
		{
			continue;
		}
		// A socket that stands for a fixture grid ("count" > 1, its room known): the fixtures spread
		// over the room's floor polygon at the socket's height, sharing the socket's lumens.
		const FString* CountProp = Socket.Props.Find(TEXT("count"));
		const int32 Count = CountProp ? FCString::Atoi(**CountProp) : 1;
		const FVerseDeckRoom* Room = Manifest.Rooms.FindByPredicate([&Socket](const FVerseDeckRoom& R) { return R.Id == Socket.Room; });
		if (Count > 1 && Room && Room->PolygonCm.Num() >= 3)
		{
			const TArray<FVector> Points = FixtureGrid(*Room, Count, Socket.Transform.GetLocation().Z);
			const double PerFixture = FMath::Min(Socket.LightLumen / FMath::Max(1, Points.Num()), MaxLumen);
			for (int32 I = 0; I < Points.Num() && Lights.Num() < MaxDeckLights; ++I)
			{
				URectLightComponent* Rect = NewObject<URectLightComponent>(this);
				Rect->SetSourceWidth(static_cast<float>(FMath::Max(60.0, Spec.SourceSizeCm)));
				Rect->SetSourceHeight(30.f);
				Rect->SetMobility(EComponentMobility::Movable);
				Rect->SetupAttachment(Root);
				Rect->SetRelativeLocationAndRotation(Points[I], FRotator(-90.0, 0.0, 0.0));
				Rect->SetIntensityUnits(ELightUnits::Lumens);
				Rect->SetIntensity(static_cast<float>(PerFixture));
				Rect->SetAttenuationRadius(static_cast<float>(FMath::Max(600.0, Spec.AttenuationCm)));
				Rect->SetBarnDoorAngle(60.f);
				Rect->SetBarnDoorLength(20.f);
				// A few shadowed fixtures give the room its contact shadows; the rest stay cheap.
				Rect->SetCastShadows(I % 6 == 0 && ShadowedFixtures++ < MaxShadowedFixtures);
				Rect->SetUseTemperature(Spec.bUseTemperature);
				Rect->SetTemperature(static_cast<float>(Spec.Kelvin));
				Rect->SetLightColor(Spec.bUseTemperature ? FLinearColor::White : Spec.Colour);
				Rect->RegisterComponent();
				Lights.Add(Rect);
				BlinkHz.Add(Spec.BlinkHz);
				BaseIntensity.Add(static_cast<float>(PerFixture));
			}
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
	// Every screen throws a faint glow onto its console and operator: the deck reads as working.
	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		if (Socket.Kind != FName(TEXT("screen")) || Lights.Num() >= MaxDeckLights)
		{
			continue;
		}
		FVector Normal = Socket.Transform.GetRotation().GetForwardVector();
		if (const FString* NormalProp = Socket.Props.Find(TEXT("normal")))
		{
			TArray<FString> Parts;
			NormalProp->Replace(TEXT("["), TEXT("")).Replace(TEXT("]"), TEXT("")).ParseIntoArray(Parts, TEXT(","));
			if (Parts.Num() == 3)
			{
				Normal = FVector(FCString::Atod(*Parts[0]), FCString::Atod(*Parts[1]), FCString::Atod(*Parts[2])).GetSafeNormal();
			}
		}
		UPointLightComponent* Glow = NewObject<UPointLightComponent>(this);
		Glow->SetMobility(EComponentMobility::Movable);
		Glow->SetupAttachment(Root);
		Glow->SetRelativeLocation(Socket.Transform.GetLocation() + Normal * 35.0);
		Glow->SetIntensityUnits(ELightUnits::Lumens);
		Glow->SetIntensity(static_cast<float>(ScreenGlowLumen));
		Glow->SetAttenuationRadius(260.f);
		Glow->SetSourceRadius(25.f);
		Glow->SetCastShadows(false);
		Glow->SetUseTemperature(true);
		Glow->SetTemperature(7000.f);
		Glow->SetVolumetricScatteringIntensity(0.f);
		Glow->RegisterComponent();
		Lights.Add(Glow);
		BlinkHz.Add(0.0);
		BaseIntensity.Add(static_cast<float>(ScreenGlowLumen));
	}
	// Rooms no light socket covers (the bridge's crew pits) get a default fixture grid at the height
	// of the deck's highest light, so no room of a deck renders black.
	double TopZ = 0.0;
	TSet<FName> LitRooms;
	for (const FVerseDeckSocket& Socket : Manifest.Sockets)
	{
		if (Socket.Kind == FName(TEXT("light")))
		{
			TopZ = FMath::Max(TopZ, Socket.Transform.GetLocation().Z);
			LitRooms.Add(Socket.Room);
		}
	}
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		if (LitRooms.Contains(Room.Id) || Room.PolygonCm.Num() < 3)
		{
			continue;
		}
		// Under the deck's highest light, or a standard ceiling when no light hangs high enough.
		const double FixtureZ = TopZ > Room.ZCm + 200.0 ? TopZ - 20.0 : Room.ZCm + DefaultCeilingCm;
		for (const FVector& Point : FixtureGrid(Room, MaxFixturesPerUnlitRoom, FixtureZ))
		{
			if (Lights.Num() >= MaxDeckLights)
			{
				break;
			}
			URectLightComponent* Rect = NewObject<URectLightComponent>(this);
			Rect->SetSourceWidth(90.f);
			Rect->SetSourceHeight(30.f);
			Rect->SetMobility(EComponentMobility::Movable);
			Rect->SetupAttachment(Root);
			Rect->SetRelativeLocationAndRotation(Point, FRotator(-90.0, 0.0, 0.0));
			Rect->SetIntensityUnits(ELightUnits::Lumens);
			Rect->SetIntensity(static_cast<float>(DefaultFixtureLumen));
			Rect->SetAttenuationRadius(static_cast<float>(FixtureZ - Room.ZCm + 400.0));
			Rect->SetCastShadows(false);
			Rect->SetUseTemperature(true);
			Rect->SetTemperature(static_cast<float>(Look.WorkLightKelvin));
			Rect->RegisterComponent();
			Lights.Add(Rect);
			BlinkHz.Add(0.0);
			BaseIntensity.Add(static_cast<float>(DefaultFixtureLumen));
		}
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

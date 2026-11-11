#include "Decks/VerseDeckLife.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "Components/PointLightComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Decks/VerseDeckManifest.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Materials/MaterialInterface.h"
#include "VerseLog.h"

namespace VerseDeckLifePrivate
{
	const TCHAR* const KitProps = TEXT("/Game/Verse/Kit/Props/");
	const TCHAR* const Readouts = TEXT("/Game/Verse/Materials/Instances/Props/");
	/** The kit's screen glass slot (`kit/props/command/_base.py` SCREEN). */
	const FName ScreenSlot(TEXT("M_Screen"));

	/** Gold guide light dashes: length, gap, inset from the room edge, all centimetres. */
	constexpr double GuideDashCm = 60.0;
	constexpr double GuidePitchCm = 160.0;
	constexpr double GuideInsetCm = 30.0;
	/** A dash sits on the room's floor: the trace must land this close to the room height. */
	constexpr double FloorToleranceCm = 12.0;
	/** Budget per deck, so a big deck never floods the frame with instances. */
	constexpr int32 MaxGuideDashes = 900;
	constexpr int32 MaxDeskProps = 260;
	/** Wall displays: one per this much wall, centred this high above the floor, capped per deck. */
	constexpr double WallDisplayPitchCm = 520.0;
	constexpr double WallDisplayCentreCm = 165.0;
	constexpr int32 MaxWallDisplays = 40;
	/** Table, desk and counter props: one per this many square metres of room, capped per room. */
	constexpr double SurfaceM2PerProp = 18.0;
	constexpr int32 MaxSurfacePropsPerRoom = 24;
	/** Holo globe turn rate, degrees per second. */
	constexpr double GlobeDegPerSecond = 9.0;

	template <typename T>
	T* Load(const FString& Path)
	{
		return LoadObject<T>(nullptr, *Path, nullptr, LOAD_NoWarn | LOAD_Quiet);
	}

	UStaticMesh* KitMesh(const TCHAR* Name)
	{
		return Load<UStaticMesh>(FString::Printf(TEXT("%s%s.%s"), KitProps, Name, Name));
	}

	UMaterialInterface* Readout(FName Layout)
	{
		const FString Name = FString::Printf(TEXT("MI_Readout_%s"), *Layout.ToString());
		return Load<UMaterialInterface>(FString::Printf(TEXT("%s%s.%s"), Readouts, *Name, *Name));
	}

	/** Stable small hash of a position, so the same console shows the same read-out every visit. */
	uint32 Spot(const FVector& P)
	{
		return HashCombine(GetTypeHash(FMath::RoundToInt(P.X / 10.0)), HashCombine(GetTypeHash(FMath::RoundToInt(P.Y / 10.0)), GetTypeHash(FMath::RoundToInt(P.Z / 10.0))));
	}

	double SignedArea(const TArray<FVector2D>& Poly)
	{
		double A = 0.0;
		for (int32 I = 0, J = Poly.Num() - 1; I < Poly.Num(); J = I++)
		{
			A += Poly[J].X * Poly[I].Y - Poly[I].X * Poly[J].Y;
		}
		return A * 0.5;
	}

	FVector ParseNormal(const FVerseDeckSocket& Socket)
	{
		if (const FString* Prop = Socket.Props.Find(TEXT("normal")))
		{
			TArray<FString> Parts;
			Prop->Replace(TEXT("["), TEXT("")).Replace(TEXT("]"), TEXT("")).ParseIntoArray(Parts, TEXT(","));
			if (Parts.Num() == 3)
			{
				return FVector(FCString::Atod(*Parts[0]), FCString::Atod(*Parts[1]), FCString::Atod(*Parts[2])).GetSafeNormal();
			}
		}
		return Socket.Transform.GetRotation().GetForwardVector();
	}

	double PropMetres(const FVerseDeckSocket& Socket, const TCHAR* Key, double Default)
	{
		const FString* Value = Socket.Props.Find(Key);
		return Value ? FCString::Atod(**Value) : Default;
	}
}

AVerseDeckLife::AVerseDeckLife()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.TickInterval = 0.0f;
	Root = CreateDefaultSubobject<USceneComponent>(TEXT("Root"));
	Root->SetMobility(EComponentMobility::Movable);
	RootComponent = Root;
}

TArray<FName> AVerseDeckLife::ReadoutsFor(FName Deck)
{
	const FString Id = Deck.ToString();
	if (Id == TEXT("engineering"))
	{
		return { TEXT("Reactor"), TEXT("Systems"), TEXT("Map"), TEXT("Reactor"), TEXT("Comms") };
	}
	if (Id == TEXT("ops"))
	{
		return { TEXT("Crew"), TEXT("Comms"), TEXT("Systems"), TEXT("Map") };
	}
	if (Id == TEXT("hangar"))
	{
		return { TEXT("Systems"), TEXT("Comms"), TEXT("Map") };
	}
	return { TEXT("Tactical"), TEXT("Nav"), TEXT("Systems"), TEXT("Comms"), TEXT("Crew"), TEXT("Map") };
}

int32 AVerseDeckLife::Build(const FVerseDeckManifest& Manifest)
{
	PlaceHolos(Manifest);
	PlaceGuides(Manifest);
	PlaceWallDisplays(Manifest);
	PlaceDeskProps(Manifest);
	PlaceSurfaceProps(Manifest);
	PlaceFloorProps(Manifest);
	// Last: the tablets and data pads placed above carry screen slots as well.
	ScreensLit = LightScreens(Manifest.Deck);
	UE_LOG(LogVerseDecks, Log, TEXT("deck %s life: %d screens, %d wall displays, %d holo globes, %d guide lights, %d desk props, %d floor props"),
		*Manifest.Deck.ToString(), ScreensLit, WallDisplays, HoloGlobes, GuideLights, DeskProps, FloorProps);
	return ScreensLit + WallDisplays + HoloGlobes + GuideLights + DeskProps + FloorProps;
}

int32 AVerseDeckLife::LightScreens(FName Deck)
{
	using namespace VerseDeckLifePrivate;
	UWorld* World = GetWorld();
	if (!World)
	{
		return 0;
	}
	TArray<UMaterialInterface*> Layouts;
	for (const FName Layout : ReadoutsFor(Deck))
	{
		if (UMaterialInterface* Material = Readout(Layout))
		{
			Layouts.Add(Material);
		}
	}
	if (Layouts.Num() == 0)
	{
		return 0;
	}
	int32 Lit = 0;
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		TArray<UStaticMeshComponent*> Meshes;
		It->GetComponents(Meshes);
		for (UStaticMeshComponent* Mesh : Meshes)
		{
			const UStaticMesh* Static = Mesh ? Mesh->GetStaticMesh() : nullptr;
			if (!Static)
			{
				continue;
			}
			const TArray<FStaticMaterial>& Slots = Static->GetStaticMaterials();
			for (int32 Index = 0; Index < Slots.Num(); ++Index)
			{
				if (Slots[Index].MaterialSlotName != ScreenSlot)
				{
					continue;
				}
				// An instanced component draws one material for all its instances: one layout.
				const FVector Where = Mesh->IsA<UInstancedStaticMeshComponent>() ? FVector(Index, 0, 0) : Mesh->GetComponentLocation();
				Mesh->SetMaterial(Index, Layouts[Spot(Where) % Layouts.Num()]);
				++Lit;
			}
		}
	}
	return Lit;
}

void AVerseDeckLife::PlaceHolos(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	UStaticMesh* Globe = KitMesh(TEXT("SM_Clutter_HoloGlobe"));
	if (!Globe)
	{
		return;
	}
	for (const FVerseDeckSocket* Socket : Manifest.SocketsOfKind(TEXT("holo")))
	{
		const double RadiusCm = PropMetres(*Socket, TEXT("radius"), 1.0) * 100.0;
		const double HeightCm = PropMetres(*Socket, TEXT("height"), 1.2) * 100.0;
		// The globe mesh is 1 m across with its foot at the origin; it floats a hand above the table.
		const double Diameter = FMath::Min(RadiusCm * 1.6, HeightCm * 0.9);
		const FVector Base = Socket->Transform.GetLocation() + FVector(0.0, 0.0, 18.0);
		UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(this);
		Mesh->SetMobility(EComponentMobility::Movable);
		Mesh->SetupAttachment(Root);
		Mesh->SetStaticMesh(Globe);
		Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
		Mesh->SetCastShadow(false);
		Mesh->SetRelativeLocation(Base);
		Mesh->SetRelativeScale3D(FVector(Diameter / 100.0));
		Mesh->RegisterComponent();
		Globes.Add(Mesh);
		UPointLightComponent* Glow = NewObject<UPointLightComponent>(this);
		Glow->SetMobility(EComponentMobility::Movable);
		Glow->SetupAttachment(Root);
		Glow->SetRelativeLocation(Base + FVector(0.0, 0.0, Diameter * 0.5));
		Glow->SetIntensityUnits(ELightUnits::Lumens);
		Glow->SetIntensity(4000.f);
		Glow->SetAttenuationRadius(static_cast<float>(RadiusCm * 2.5));
		Glow->SetSourceRadius(static_cast<float>(Diameter * 0.3));
		Glow->SetCastShadows(false);
		Glow->SetLightColor(FLinearColor(1.0f, 0.55f, 0.2f));
		Glow->RegisterComponent();
		++HoloGlobes;
	}
}

UInstancedStaticMeshComponent* AVerseDeckLife::Instances(const TCHAR* MeshName)
{
	const FName Key(MeshName);
	if (TObjectPtr<UInstancedStaticMeshComponent>* Found = InstanceSets.Find(Key))
	{
		return *Found;
	}
	UStaticMesh* Mesh = VerseDeckLifePrivate::KitMesh(MeshName);
	if (!Mesh)
	{
		InstanceSets.Add(Key, nullptr);
		return nullptr;
	}
	UInstancedStaticMeshComponent* Set = NewObject<UInstancedStaticMeshComponent>(this, Key);
	Set->SetMobility(EComponentMobility::Movable);
	Set->SetupAttachment(Root);
	Set->SetStaticMesh(Mesh);
	Set->SetCollisionEnabled(ECollisionEnabled::NoCollision);
	Set->SetCanEverAffectNavigation(false);
	Set->RegisterComponent();
	InstanceSets.Add(Key, Set);
	return Set;
}

bool AVerseDeckLife::TraceDown(const FVector& From, double Depth, FHitResult& Hit) const
{
	FCollisionQueryParams Params(TEXT("VerseDeckLife"), /*bTraceComplex*/ true, this);
	return GetWorld()->LineTraceSingleByChannel(Hit, From, From - FVector(0.0, 0.0, Depth), ECC_Visibility, Params);
}

void AVerseDeckLife::PlaceGuides(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	UInstancedStaticMeshComponent* Strips = Instances(TEXT("SM_Clutter_GuideStrip"));
	if (!Strips)
	{
		return;
	}
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		const TArray<FVector2D>& Poly = Room.PolygonCm;
		if (Poly.Num() < 3)
		{
			continue;
		}
		// Counter-clockwise polygons have the room on the left of each edge.
		const double Turn = SignedArea(Poly) >= 0.0 ? 1.0 : -1.0;
		for (int32 I = 0; I < Poly.Num(); ++I)
		{
			const FVector2D A = Poly[I];
			const FVector2D B = Poly[(I + 1) % Poly.Num()];
			const FVector2D Edge = B - A;
			const double Length = Edge.Size();
			if (Length < GuidePitchCm)
			{
				continue;
			}
			const FVector2D Dir = Edge / Length;
			const FVector2D Inward = FVector2D(-Dir.Y, Dir.X) * Turn;
			const double Yaw = FMath::RadiansToDegrees(FMath::Atan2(Dir.Y, Dir.X));
			for (double T = GuidePitchCm * 0.5; T + GuideDashCm * 0.5 < Length - GuidePitchCm * 0.25; T += GuidePitchCm)
			{
				if (GuideLights >= MaxGuideDashes)
				{
					return;
				}
				const FVector2D P = A + Dir * T + Inward * GuideInsetCm;
				FHitResult Hit;
				// Lands on the room's own floor; a wall, a console or a step in the way skips the dash.
				if (!TraceDown(FVector(P.X, P.Y, Room.ZCm + 60.0), 120.0, Hit) || Hit.ImpactNormal.Z < 0.95
					|| FMath::Abs(Hit.ImpactPoint.Z - Room.ZCm) > FloorToleranceCm)
				{
					continue;
				}
				// Open floor above the dash: a wall standing on the room edge hides it otherwise.
				FCollisionQueryParams Clear(TEXT("VerseDeckLifeGuide"), false, this);
				if (GetWorld()->OverlapAnyTestByChannel(Hit.ImpactPoint + FVector(0.0, 0.0, 14.0), FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(10.f), Clear))
				{
					continue;
				}
				const FTransform Dash(FRotator(0.0, Yaw, 0.0), Hit.ImpactPoint + FVector(0.0, 0.0, 0.2), FVector(GuideDashCm / 100.0, 1.0, 1.0));
				Strips->AddInstance(Dash, /*bWorldSpace*/ true);
				++GuideLights;
			}
		}
	}
}

void AVerseDeckLife::PlaceWallDisplays(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	UStaticMesh* Display = KitMesh(TEXT("SM_Clutter_WallDisplay"));
	if (!Display)
	{
		return;
	}
	FCollisionQueryParams Params(TEXT("VerseDeckLifeWall"), /*bTraceComplex*/ true, this);
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		const TArray<FVector2D>& Poly = Room.PolygonCm;
		if (Poly.Num() < 3)
		{
			continue;
		}
		const double Turn = SignedArea(Poly) >= 0.0 ? 1.0 : -1.0;
		for (int32 I = 0; I < Poly.Num(); ++I)
		{
			const FVector2D A = Poly[I];
			const FVector2D B = Poly[(I + 1) % Poly.Num()];
			const double Length = (B - A).Size();
			if (Length < WallDisplayPitchCm)
			{
				continue;
			}
			const FVector2D Dir = (B - A) / Length;
			const FVector2D In2 = FVector2D(-Dir.Y, Dir.X) * Turn;
			const FVector Inward(In2.X, In2.Y, 0.0);
			const FVector Along(Dir.X, Dir.Y, 0.0);
			const int32 Count = FMath::Max(1, int32(Length / WallDisplayPitchCm));
			const double Step = Length / Count;
			for (int32 K = 0; K < Count && WallDisplays < MaxWallDisplays; ++K)
			{
				const FVector2D P = A + Dir * (Step * (K + 0.5)) + In2 * 120.0;
				const FVector Eye(P.X, P.Y, Room.ZCm + WallDisplayCentreCm);
				// The wall behind: hit within reach, facing into the room, flat across the panel.
				FHitResult Hit;
				if (!GetWorld()->LineTraceSingleByChannel(Hit, Eye, Eye - Inward * 260.0, ECC_Visibility, Params)
					|| FVector::DotProduct(Hit.ImpactNormal, Inward) < 0.9)
				{
					continue;
				}
				bool bFlat = true;
				for (const FVector2D Offset : { FVector2D(-90, -50), FVector2D(90, -50), FVector2D(-90, 50), FVector2D(90, 50) })
				{
					FHitResult Corner;
					const FVector Start = Eye + Along * Offset.X + FVector(0.0, 0.0, Offset.Y);
					if (!GetWorld()->LineTraceSingleByChannel(Corner, Start, Start - Inward * 260.0, ECC_Visibility, Params)
						|| FMath::Abs(FVector::DotProduct(Corner.ImpactPoint - Hit.ImpactPoint, Inward)) > 4.0)
					{
						bFlat = false;
						break;
					}
				}
				// Nothing standing in front of the panel (a console, a locker).
				FCollisionQueryParams Clear(TEXT("VerseDeckLifeWallClear"), false, this);
				if (!bFlat || GetWorld()->OverlapAnyTestByChannel(Hit.ImpactPoint + Inward * 45.0, FQuat::Identity, ECC_Visibility, FCollisionShape::MakeBox(FVector(30.0, 30.0, 40.0)), Clear))
				{
					continue;
				}
				UStaticMeshComponent* Mesh = NewObject<UStaticMeshComponent>(this);
				Mesh->SetMobility(EComponentMobility::Movable);
				Mesh->SetupAttachment(Root);
				Mesh->SetStaticMesh(Display);
				Mesh->SetCollisionEnabled(ECollisionEnabled::NoCollision);
				// The panel faces its local +Y: turn it to face into the room, its back on the wall.
				const double Yaw = FMath::RadiansToDegrees(FMath::Atan2(Inward.Y, Inward.X)) - 90.0;
				Mesh->SetRelativeLocationAndRotation(Hit.ImpactPoint + Inward * 0.5, FRotator(0.0, Yaw, 0.0));
				Mesh->RegisterComponent();
				UPointLightComponent* Glow = NewObject<UPointLightComponent>(this);
				Glow->SetMobility(EComponentMobility::Movable);
				Glow->SetupAttachment(Root);
				Glow->SetRelativeLocation(Hit.ImpactPoint + Inward * 60.0);
				Glow->SetIntensityUnits(ELightUnits::Lumens);
				Glow->SetIntensity(700.f);
				Glow->SetAttenuationRadius(380.f);
				Glow->SetSourceRadius(40.f);
				Glow->SetCastShadows(false);
				Glow->SetLightColor(FLinearColor(1.0f, 0.62f, 0.3f));
				Glow->RegisterComponent();
				++WallDisplays;
			}
		}
	}
}

void AVerseDeckLife::PlaceDeskProps(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	const TArray<const TCHAR*> Kinds = DeskKinds(Manifest.Deck);
	FRandomStream Rng(GetTypeHash(Manifest.Deck));
	for (const FVerseDeckSocket* Socket : Manifest.SocketsOfKind(TEXT("screen")))
	{
		const FVector S = Socket->Transform.GetLocation();
		const FVector Normal = ParseNormal(*Socket);
		FVector Toward = FVector(Normal.X, Normal.Y, 0.0);
		// A screen that faces straight up or a wall screen high above any desk has no desk in front.
		if (Toward.SizeSquared() < 0.04 || S.Z > 180.0)
		{
			continue;
		}
		Toward.Normalize();
		const FVector Side(-Toward.Y, Toward.X, 0.0);
		int32 Placed = 0;
		const int32 Wanted = Rng.RandRange(1, 2);
		for (int32 Try = 0; Try < 8 && Placed < Wanted && DeskProps < MaxDeskProps; ++Try)
		{
			const double Along = Rng.FRandRange(15.0, 45.0);
			const double Across = (Rng.FRand() < 0.5 ? -1.0 : 1.0) * Rng.FRandRange(8.0, 36.0);
			const FVector Probe = S + Toward * Along + Side * Across;
			FHitResult Hit;
			if (!TraceDown(FVector(Probe.X, Probe.Y, S.Z + 30.0), 110.0, Hit) || Hit.ImpactNormal.Z < 0.97)
			{
				continue;
			}
			const double Top = Hit.ImpactPoint.Z;
			// A desk: well above the floor, below the screen's centre.
			const FVerseDeckRoom* DeskRoom = Manifest.FindRoom(Socket->Room);
			const double FloorZ = DeskRoom ? DeskRoom->ZCm : S.Z - 120.0;
			if (Top > S.Z - 4.0 || Top < S.Z - 75.0 || Top < FloorZ + 55.0)
			{
				continue;
			}
			if (!Free(Hit.ImpactPoint) || !Flat(Hit.ImpactPoint))
			{
				continue;
			}
			UInstancedStaticMeshComponent* Set = Instances(Kinds[Rng.RandRange(0, Kinds.Num() - 1)]);
			if (!Set)
			{
				continue;
			}
			const double Yaw = FMath::RadiansToDegrees(FMath::Atan2(Toward.Y, Toward.X)) + 90.0 + Rng.FRandRange(-25.0, 25.0);
			Set->AddInstance(FTransform(FRotator(0.0, Yaw, 0.0), Hit.ImpactPoint + FVector(0.0, 0.0, 0.1)), /*bWorldSpace*/ true);
			Taken.Add(Hit.ImpactPoint);
			++Placed;
			++DeskProps;
		}
	}
}

void AVerseDeckLife::PlaceSurfaceProps(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	const TArray<const TCHAR*> Kinds = DeskKinds(Manifest.Deck);
	FRandomStream Rng(GetTypeHash(Manifest.Deck) + 31);
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		if (Room.PolygonCm.Num() < 3)
		{
			continue;
		}
		const double AreaM2 = FMath::Abs(SignedArea(Room.PolygonCm)) / 10000.0;
		const int32 Wanted = FMath::Clamp(int32(AreaM2 / SurfaceM2PerProp), 2, MaxSurfacePropsPerRoom);
		const FBox2D Bounds(Room.PolygonCm);
		int32 Placed = 0;
		for (int32 Try = 0; Try < Wanted * 25 && Placed < Wanted && DeskProps < MaxDeskProps; ++Try)
		{
			const FVector2D P(Rng.FRandRange(Bounds.Min.X, Bounds.Max.X), Rng.FRandRange(Bounds.Min.Y, Bounds.Max.Y));
			if (!Room.ContainsPlan(P))
			{
				continue;
			}
			FHitResult Hit;
			if (!TraceDown(FVector(P.X, P.Y, Room.ZCm + 160.0), 160.0, Hit) || Hit.ImpactNormal.Z < 0.97)
			{
				continue;
			}
			// A table, desk or counter top: between seat height and a standing counter.
			const double Above = Hit.ImpactPoint.Z - Room.ZCm;
			if (Above < 65.0 || Above > 115.0 || !Free(Hit.ImpactPoint) || !Flat(Hit.ImpactPoint))
			{
				continue;
			}
			if (UInstancedStaticMeshComponent* Set = Instances(Kinds[Rng.RandRange(0, Kinds.Num() - 1)]))
			{
				Set->AddInstance(FTransform(FRotator(0.0, Rng.FRandRange(0.0, 360.0), 0.0), Hit.ImpactPoint + FVector(0.0, 0.0, 0.1)), true);
				Taken.Add(Hit.ImpactPoint);
				++Placed;
				++DeskProps;
			}
		}
	}
}

TArray<const TCHAR*> AVerseDeckLife::DeskKinds(FName Deck)
{
	const FString Id = Deck.ToString();
	if (Id == TEXT("engineering"))
	{
		return { TEXT("SM_Clutter_Toolkit"), TEXT("SM_Clutter_Tablet"), TEXT("SM_Clutter_Mug"), TEXT("SM_Clutter_DataPads") };
	}
	if (Id == TEXT("ops"))
	{
		return { TEXT("SM_Clutter_Mug"), TEXT("SM_Clutter_Tablet"), TEXT("SM_Clutter_DataPads"), TEXT("SM_Clutter_Mug") };
	}
	return { TEXT("SM_Clutter_Tablet"), TEXT("SM_Clutter_Mug"), TEXT("SM_Clutter_DataPads"), TEXT("SM_Clutter_Headset") };
}

bool AVerseDeckLife::Free(const FVector& Top) const
{
	for (const FVector& Other : Taken)
	{
		if (FVector::DistSquared(Other, Top) < 30.0 * 30.0)
		{
			return false;
		}
	}
	FCollisionQueryParams Clear(TEXT("VerseDeckLifeFree"), false, this);
	return !GetWorld()->OverlapAnyTestByChannel(Top + FVector(0.0, 0.0, 16.0), FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(12.f), Clear);
}

bool AVerseDeckLife::Flat(const FVector& Top) const
{
	for (const FVector2D Corner : { FVector2D(13, 13), FVector2D(-13, 13), FVector2D(13, -13), FVector2D(-13, -13) })
	{
		FHitResult Edge;
		if (!TraceDown(Top + FVector(Corner.X, Corner.Y, 30.0), 40.0, Edge) || FMath::Abs(Edge.ImpactPoint.Z - Top.Z) > 0.8)
		{
			return false;
		}
	}
	return true;
}

void AVerseDeckLife::PlaceFloorProps(const FVerseDeckManifest& Manifest)
{
	using namespace VerseDeckLifePrivate;
	const FString Id = Manifest.Deck.ToString();
	const int32 PerRoom = Id == TEXT("engineering") ? 5 : (Id == TEXT("bridge") ? 0 : 1);
	if (PerRoom == 0)
	{
		return;
	}
	FRandomStream Rng(GetTypeHash(Manifest.Deck) + 17);
	for (const FVerseDeckRoom& Room : Manifest.Rooms)
	{
		if (Room.PolygonCm.Num() < 3)
		{
			continue;
		}
		FBox2D Bounds(Room.PolygonCm);
		int32 Placed = 0;
		for (int32 Try = 0; Try < PerRoom * 12 && Placed < PerRoom; ++Try)
		{
			const FVector2D P(Rng.FRandRange(Bounds.Min.X + 100.0, Bounds.Max.X - 100.0), Rng.FRandRange(Bounds.Min.Y + 100.0, Bounds.Max.Y - 100.0));
			if (!Room.ContainsPlan(P))
			{
				continue;
			}
			FHitResult Hit;
			if (!TraceDown(FVector(P.X, P.Y, Room.ZCm + 60.0), 120.0, Hit) || Hit.ImpactNormal.Z < 0.97
				|| FMath::Abs(Hit.ImpactPoint.Z - Room.ZCm) > FloorToleranceCm)
			{
				continue;
			}
			// Beside something, never in the middle of a walkway: a prop within 1.2 m, nothing within 0.4 m.
			FCollisionQueryParams Params(TEXT("VerseDeckLifeClear"), false, this);
			const FVector Centre = Hit.ImpactPoint + FVector(0.0, 0.0, 45.0);
			if (GetWorld()->OverlapAnyTestByChannel(Centre, FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(40.f), Params)
				|| !GetWorld()->OverlapAnyTestByChannel(Centre, FQuat::Identity, ECC_Visibility, FCollisionShape::MakeSphere(120.f), Params))
			{
				continue;
			}
			const TCHAR* Kind = (Id == TEXT("engineering") && Rng.FRand() < 0.4) ? TEXT("SM_Clutter_Toolkit") : TEXT("SM_Clutter_CableCoil");
			if (UInstancedStaticMeshComponent* Set = Instances(Kind))
			{
				Set->AddInstance(FTransform(FRotator(0.0, Rng.FRandRange(0.0, 360.0), 0.0), Hit.ImpactPoint + FVector(0.0, 0.0, 0.1)), true);
				++Placed;
				++FloorProps;
			}
		}
	}
}

void AVerseDeckLife::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);
	for (UStaticMeshComponent* Globe : Globes)
	{
		if (Globe)
		{
			Globe->AddRelativeRotation(FRotator(0.0, VerseDeckLifePrivate::GlobeDegPerSecond * DeltaSeconds, 0.0));
		}
	}
}

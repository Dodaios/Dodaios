#include "Holes/VerseHoleRenderComponent.h"

#include "Components/DecalComponent.h"
#include "Components/MeshComponent.h"
#include "Engine/Canvas.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "Holes/VerseBoltHoleComponent.h"
#include "Holes/VerseHoleGlow.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Materials/MaterialInterface.h"
#include "Misc/App.h"
#include "Misc/CommandLine.h"
#include "Misc/Parse.h"
#include "VerseLog.h"

namespace
{
	/** -nullrhi runs draw nothing. Read from the command line: VerseDestruction does not link RHI. */
	bool UsesNullRhi()
	{
		static const bool bNullRhi = FParse::Param(FCommandLine::Get(), TEXT("nullrhi"));
		return bNullRhi;
	}

	/** Rim decal footprint per hole radius (the charred rim is wider than the opening). */
	constexpr float RimFootprint = 1.8f;
	const TCHAR* const DefaultRimDecalPath = TEXT("/Game/Verse/Destruction/_Holes/M_HoleRim_Decal.M_HoleRim_Decal");

	/** The two axes of the largest face of a box and the thickness axis. */
	void FaceAxes(const FBox& Box, int32& U, int32& V, int32& Depth)
	{
		const FVector Size = Box.GetSize();
		Depth = Size.X <= Size.Y && Size.X <= Size.Z ? 0 : (Size.Y <= Size.Z ? 1 : 2);
		U = Depth == 0 ? 1 : 0;
		V = Depth == 2 ? 1 : 2;
	}
}

UVerseHoleRenderComponent::UVerseHoleRenderComponent()
{
	PrimaryComponentTick.bCanEverTick = true;
	PrimaryComponentTick.bStartWithTickEnabled = false;
	PrimaryComponentTick.TickInterval = 1.f / 30.f;
	SetIsReplicatedByDefault(false);
	RimDecalMaterial = TSoftObjectPtr<UMaterialInterface>(FSoftObjectPath(DefaultRimDecalPath));
}

bool UVerseHoleRenderComponent::CanRender(const UWorld* World)
{
	return World && World->GetNetMode() != NM_DedicatedServer && FApp::CanEverRender() && !UsesNullRhi();
}

void UVerseHoleRenderComponent::SetHoleSource(UVerseBoltHoleComponent* InHoles)
{
	if (UVerseBoltHoleComponent* Old = HoleSource.Get())
	{
		Old->OnHolesChanged.Remove(HolesChangedHandle);
	}
	HoleSource = InHoles;
	if (InHoles)
	{
		HolesChangedHandle = InHoles->OnHolesChanged.AddUObject(this, &UVerseHoleRenderComponent::HandleHolesChanged);
	}
	HandleHolesChanged();
}

void UVerseHoleRenderComponent::RegisterPieceVisual(uint16 PieceIndex, UMeshComponent* Mesh, const FBox& LocalBounds, USceneComponent* Frame)
{
	FPieceVisual& Visual = Pieces.FindOrAdd(PieceIndex);
	Visual.Mesh = Mesh;
	Visual.Frame = Frame ? Frame : (Mesh && Mesh->GetOwner() ? Mesh->GetOwner()->GetRootComponent() : nullptr);
	Visual.LocalBounds = LocalBounds;
	HandleHolesChanged();
}

void UVerseHoleRenderComponent::SetServerTimeSource(TFunction<uint32()> InNow)
{
	NowMs = MoveTemp(InNow);
}

uint32 UVerseHoleRenderComponent::CurrentTimeMs() const
{
	if (NowMs)
	{
		return NowMs();
	}
	const UWorld* World = GetWorld();
	return World ? uint32(World->GetTimeSeconds() * 1000.0) : 0;
}

void UVerseHoleRenderComponent::HandleHolesChanged()
{
	bDirty = true;
	SetComponentTickEnabled(true);
}

void UVerseHoleRenderComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	SetHoleSource(nullptr);
	for (UDecalComponent* Decal : DecalPool)
	{
		if (Decal)
		{
			Decal->DestroyComponent();
		}
	}
	DecalPool.Reset();
	Masks.Reset();
	Super::EndPlay(Reason);
}

FVector2D UVerseHoleRenderComponent::HoleUV(const FBox& LocalBounds, const FVector& LocalPointCm)
{
	int32 U, V, Depth;
	FaceAxes(LocalBounds, U, V, Depth);
	const FVector Size = LocalBounds.GetSize();
	const FVector Rel = LocalPointCm - LocalBounds.Min;
	return FVector2D(Size[U] > 0.0 ? FMath::Clamp(Rel[U] / Size[U], 0.0, 1.0) : 0.5,
		Size[V] > 0.0 ? FMath::Clamp(1.0 - Rel[V] / Size[V], 0.0, 1.0) : 0.5);
}

float UVerseHoleRenderComponent::HoleRadiusPx(const FBox& LocalBounds, float RadiusCm, int32 InMaskSize)
{
	int32 U, V, Depth;
	FaceAxes(LocalBounds, U, V, Depth);
	const FVector Size = LocalBounds.GetSize();
	const double Longest = FMath::Max(Size[U], Size[V]);
	return Longest > 0.0 ? float(RadiusCm / Longest * InMaskSize) : 0.f;
}

UTextureRenderTarget2D* UVerseHoleRenderComponent::GetMask(uint16 PieceIndex) const
{
	const TObjectPtr<UTextureRenderTarget2D>* Found = Masks.Find(PieceIndex);
	return Found ? Found->Get() : nullptr;
}

void UVerseHoleRenderComponent::TickComponent(float DeltaTime, ELevelTick TickType, FActorComponentTickFunction* ThisTickFunction)
{
	Super::TickComponent(DeltaTime, TickType, ThisTickFunction);
	Sync();
	if (!bDirty && GlowingCount == 0)
	{
		SetComponentTickEnabled(false);
	}
}

void UVerseHoleRenderComponent::Sync()
{
	if (bDirty)
	{
		RebuildSlots();
		bDirty = false;
	}
	UpdateGlow();
}

UDecalComponent* UVerseHoleRenderComponent::AcquireDecal(int32 Index)
{
	if (DecalPool.IsValidIndex(Index) && DecalPool[Index])
	{
		return DecalPool[Index];
	}
	AActor* Owner = GetOwner();
	if (!Owner)
	{
		return nullptr;
	}
	UDecalComponent* Decal = NewObject<UDecalComponent>(Owner, NAME_None, RF_Transient);
	Decal->SetupAttachment(Owner->GetRootComponent());
	Decal->RegisterComponent();
	if (DecalPool.Num() <= Index)
	{
		DecalPool.SetNum(Index + 1);
	}
	DecalPool[Index] = Decal;
	return Decal;
}

void UVerseHoleRenderComponent::RebuildSlots()
{
	TArray<FVerseBoltHole> Records;
	if (const UVerseBoltHoleComponent* Source = HoleSource.Get())
	{
		Source->GetAllHoles(Records);
	}

	// A piece gets its mask on its first hole and keeps it (cleared) until the component goes.
	TSet<uint16> WithHoles;
	for (const FVerseBoltHole& Hole : Records)
	{
		WithHoles.Add(Hole.PieceIndex);
	}
	TSet<uint16> ToDraw = WithHoles;
	ToDraw.Append(MaskPieces);
	MaskPieces.Append(WithHoles);

	const bool bRender = CanRender(GetWorld());
	UMaterialInterface* RimMaterial = bRender ? RimDecalMaterial.LoadSynchronous() : nullptr;
	if (bRender && !RimMaterial && !bWarnedNoMaterial)
	{
		UE_LOG(LogVerseDestruction, Warning, TEXT("hole rim decal material %s missing; holes render as masks only"),
			*RimDecalMaterial.ToString());
		bWarnedNoMaterial = true;
	}

	TArray<FHoleSlot> NewSlots;
	NewSlots.Reserve(Records.Num());
	for (int32 Index = 0; Index < Records.Num(); ++Index)
	{
		FHoleSlot& Slot = NewSlots.AddDefaulted_GetRef();
		Slot.Hole = Records[Index];
		const FPieceVisual* Visual = Pieces.Find(Slot.Hole.PieceIndex);
		const USceneComponent* Frame = Visual ? Visual->Frame.Get() : nullptr;
		if (!RimMaterial || !Frame)
		{
			continue;
		}
		UDecalComponent* Decal = AcquireDecal(Index);
		if (!Decal)
		{
			continue;
		}
		const FTransform& PieceToWorld = Frame->GetComponentTransform();
		const FVector AxisWorld = PieceToWorld.TransformVectorNoScale(Slot.Hole.GetAxisDirection());
		const float RadiusCm = Slot.Hole.RadiusMm / 10.f;
		const float HalfDepth = float(Visual->LocalBounds.GetExtent().GetMin()) + 0.5f;
		Decal->SetWorldLocationAndRotation(PieceToWorld.TransformPosition(Slot.Hole.GetAxisPointCm()), FRotationMatrix::MakeFromX(AxisWorld).Rotator());
		Decal->DecalSize = FVector(HalfDepth, RadiusCm * RimFootprint, RadiusCm * RimFootprint);
		UMaterialInstanceDynamic* Mid = Cast<UMaterialInstanceDynamic>(Decal->GetDecalMaterial());
		if (!Mid || Mid->Parent != RimMaterial)
		{
			Mid = UMaterialInstanceDynamic::Create(RimMaterial, this);
			Decal->SetDecalMaterial(Mid);
		}
		Decal->SetVisibility(true);
		Decal->MarkRenderStateDirty();
		Slot.Decal = Decal;
		Slot.Material = Mid;
	}
	for (int32 Index = Records.Num(); Index < DecalPool.Num(); ++Index)
	{
		if (DecalPool[Index])
		{
			DecalPool[Index]->SetVisibility(false);
		}
	}
	HoleSlots = MoveTemp(NewSlots);
	RedrawMasks(ToDraw);
}

void UVerseHoleRenderComponent::RedrawMasks(const TSet<uint16>& PiecesToDraw)
{
	if (!CanRender(GetWorld()))
	{
		return;
	}
	for (const uint16 PieceIndex : PiecesToDraw)
	{
		const FPieceVisual* Visual = Pieces.Find(PieceIndex);
		if (!Visual)
		{
			continue;
		}
		UTextureRenderTarget2D* Mask = GetMask(PieceIndex);
		if (!Mask)
		{
			Mask = UKismetRenderingLibrary::CreateRenderTarget2D(this, MaskSize, MaskSize, RTF_R8, FLinearColor::White);
			Masks.Add(PieceIndex, Mask);
			if (UMeshComponent* Mesh = Visual->Mesh.Get())
			{
				for (int32 Slot = 0; Slot < Mesh->GetNumMaterials(); ++Slot)
				{
					if (UMaterialInstanceDynamic* Mid = Mesh->CreateDynamicMaterialInstance(Slot))
					{
						Mid->SetTextureParameterValue(MaskParameter, Mask);
					}
				}
			}
		}
		UKismetRenderingLibrary::ClearRenderTarget2D(this, Mask, FLinearColor::White);
		UCanvas* Canvas = nullptr;
		FVector2D Size;
		FDrawToRenderTargetContext Context;
		UKismetRenderingLibrary::BeginDrawCanvasToRenderTarget(this, Mask, Canvas, Size, Context);
		if (Canvas)
		{
			for (const FHoleSlot& Slot : HoleSlots)
			{
				if (Slot.Hole.PieceIndex != PieceIndex)
				{
					continue;
				}
				const FVector2D Uv = HoleUV(Visual->LocalBounds, Slot.Hole.GetAxisPointCm());
				const float Radius = HoleRadiusPx(Visual->LocalBounds, Slot.Hole.RadiusMm / 10.f, MaskSize);
				Canvas->K2_DrawPolygon(nullptr, Uv * Size, FVector2D(Radius, Radius), 24, FLinearColor::Black);
			}
		}
		UKismetRenderingLibrary::EndDrawCanvasToRenderTarget(this, Context);
	}
}

void UVerseHoleRenderComponent::UpdateGlow()
{
	const uint32 Now = CurrentTimeMs();
	TArray<uint32> Times;
	Times.Reserve(HoleSlots.Num());
	for (const FHoleSlot& Slot : HoleSlots)
	{
		Times.Add(Slot.Hole.ServerTimeMs);
	}
	const TArray<int32> Glowing = VerseHoleGlow::SelectGlowing(Times, Now, GlowingCap, GlowEndS);
	TBitArray<> IsGlowing(false, HoleSlots.Num());
	for (const int32 Index : Glowing)
	{
		IsGlowing[Index] = true;
	}
	GlowingCount = Glowing.Num();
	for (int32 Index = 0; Index < HoleSlots.Num(); ++Index)
	{
		FHoleSlot& Slot = HoleSlots[Index];
		const bool bWasGlowing = Slot.bGlowing;
		Slot.bGlowing = IsGlowing[Index];
		UMaterialInstanceDynamic* Mid = Slot.Material.Get();
		if (!Mid || (!Slot.bGlowing && !bWasGlowing))
		{
			continue;
		}
		const float AgeS = Now >= Slot.Hole.ServerTimeMs ? (Now - Slot.Hole.ServerTimeMs) / 1000.f : 0.f;
		const FVerseHoleGlowSample Sample = Slot.bGlowing ? VerseHoleGlow::Sample(AgeS, GlowTauS, GlowEndS) : FVerseHoleGlowSample();
		Mid->SetScalarParameterValue(GlowParameter, Sample.Intensity * VerseHoleGlow::PeakEmissive);
		Mid->SetVectorParameterValue(GlowColorParameter, Sample.bGlowing ? Sample.Color : VerseHoleGlow::CharredColor());
	}
}

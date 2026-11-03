#include "Holes/VerseHoleRenderComponent.h"

#include "Components/DecalComponent.h"
#include "Components/MeshComponent.h"
#include "Engine/Canvas.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "GameFramework/GameStateBase.h"
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
	MarkAllDirty();
}

void UVerseHoleRenderComponent::RegisterPieceVisual(uint16 PieceIndex, UMeshComponent* Mesh, const FBox& LocalBounds, USceneComponent* Frame)
{
	FPieceVisual& Visual = Pieces.FindOrAdd(PieceIndex);
	Visual.Mesh = Mesh;
	Visual.Frame = Frame ? Frame : (Mesh && Mesh->GetOwner() ? Mesh->GetOwner()->GetRootComponent() : nullptr);
	Visual.LocalBounds = LocalBounds;
	DirtyPieces.Add(PieceIndex);
	DirtyVisuals.Add(PieceIndex);
	bDirty = true;
	SetComponentTickEnabled(true);
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
	if (!World)
	{
		return 0;
	}
	// Hole records carry server time. A client world clock lags the server clock (a late joiner
	// by the whole match), so the glow ages against the replicated server clock.
	const AGameStateBase* GameState = World->GetGameState();
	const double Seconds = GameState ? GameState->GetServerWorldTimeSeconds() : World->GetTimeSeconds();
	return uint32(FMath::Max(0.0, Seconds) * 1000.0);
}

void UVerseHoleRenderComponent::HandleHolesChanged(TConstArrayView<uint16> InPieces, bool bAll)
{
	if (bAll)
	{
		bAllDirty = true;
	}
	DirtyPieces.Append(InPieces);
	bDirty = true;
	SetComponentTickEnabled(true);
}

void UVerseHoleRenderComponent::MarkAllDirty()
{
	HandleHolesChanged({}, true);
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
	const UVerseBoltHoleComponent* Source = HoleSource.Get();
	const TConstArrayView<FVerseBoltHoleSlot> Slots = Source ? Source->GetSlots() : TConstArrayView<FVerseBoltHoleSlot>();

	const bool bRender = CanRender(GetWorld());
	UMaterialInterface* RimMaterial = bRender ? RimDecalMaterial.LoadSynchronous() : nullptr;
	if (bRender && !RimMaterial && !bWarnedNoMaterial)
	{
		UE_LOG(LogVerseDestruction, Warning, TEXT("hole rim decal material %s missing; holes render as masks only"),
			*RimDecalMaterial.ToString());
		bWarnedNoMaterial = true;
	}

	// The hole component keeps every hole at a stable slot index, so a change touches only the
	// slots whose hole is new or gone; the decal of a slot follows the hole that lives in it.
	if (bAllDirty)
	{
		DirtyPieces.Append(MaskPieces);
		DirtyVisuals.Append(MaskPieces);
	}
	const int32 Count = FMath::Max(Slots.Num(), HoleSlots.Num());
	HoleSlots.SetNum(Count);
	LiveSlots = 0;
	for (int32 Index = 0; Index < Count; ++Index)
	{
		FHoleSlot& Slot = HoleSlots[Index];
		const bool bLive = Slots.IsValidIndex(Index) && Source->IsLiveSlot(Index);
		const uint32 Sequence = bLive ? Slots[Index].Sequence : 0;
		if (bLive)
		{
			++LiveSlots;
			if (bAllDirty)
			{
				DirtyPieces.Add(Slots[Index].Hole.PieceIndex);
			}
		}
		const bool bChanged = Slot.Sequence != Sequence;
		const bool bVisualChanged = bLive && (bAllDirty || DirtyVisuals.Contains(Slots[Index].Hole.PieceIndex));
		if (!bChanged && !bVisualChanged)
		{
			continue;
		}
		if (bChanged && Slot.Sequence != 0)
		{
			DirtyPieces.Add(Slot.Hole.PieceIndex);
		}
		Slot.Sequence = Sequence;
		Slot.bGlowing = false;
		if (!bLive)
		{
			Slot.Hole = FVerseBoltHole();
			if (UDecalComponent* Decal = Slot.Decal.Get())
			{
				Decal->SetVisibility(false);
			}
			continue;
		}
		Slot.Hole = Slots[Index].Hole;
		DirtyPieces.Add(Slot.Hole.PieceIndex);
		++SlotUpdates;
		PlaceDecal(Index, RimMaterial);
	}
	// After a reset the slot array is shorter: hide and drop the rest.
	for (int32 Index = Slots.Num(); Index < HoleSlots.Num(); ++Index)
	{
		if (UDecalComponent* Decal = HoleSlots[Index].Decal.Get())
		{
			Decal->SetVisibility(false);
		}
	}
	HoleSlots.SetNum(Slots.Num());

	// A piece gets its mask on its first hole and keeps it (cleared) until the component goes.
	TSet<uint16> ToDraw;
	for (const uint16 PieceIndex : DirtyPieces)
	{
		if (Source && Source->NumOnPiece(PieceIndex) > 0)
		{
			MaskPieces.Add(PieceIndex);
		}
		if (MaskPieces.Contains(PieceIndex))
		{
			ToDraw.Add(PieceIndex);
		}
	}
	DirtyPieces.Reset();
	DirtyVisuals.Reset();
	bAllDirty = false;
	MaskRedraws += ToDraw.Num();
	RedrawMasks(ToDraw);
}

void UVerseHoleRenderComponent::PlaceDecal(int32 Index, UMaterialInterface* RimMaterial)
{
	FHoleSlot& Slot = HoleSlots[Index];
	const FPieceVisual* Visual = Pieces.Find(Slot.Hole.PieceIndex);
	const USceneComponent* Frame = Visual ? Visual->Frame.Get() : nullptr;
	if (!RimMaterial || !Frame)
	{
		return;
	}
	UDecalComponent* Decal = AcquireDecal(Index);
	if (!Decal)
	{
		return;
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
			const UVerseBoltHoleComponent* Source = HoleSource.Get();
			const TConstArrayView<FVerseBoltHole> PieceHoles = Source ? Source->GetPieceHoles(PieceIndex) : TConstArrayView<FVerseBoltHole>();
			for (const FVerseBoltHole& Hole : PieceHoles)
			{
				const FVector2D Uv = HoleUV(Visual->LocalBounds, Hole.GetAxisPointCm());
				const float Radius = HoleRadiusPx(Visual->LocalBounds, Hole.RadiusMm / 10.f, MaskSize);
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
	TArray<int32> SlotOf;
	Times.Reserve(LiveSlots);
	SlotOf.Reserve(LiveSlots);
	for (int32 Index = 0; Index < HoleSlots.Num(); ++Index)
	{
		if (HoleSlots[Index].Sequence != 0)
		{
			Times.Add(HoleSlots[Index].Hole.ServerTimeMs);
			SlotOf.Add(Index);
		}
	}
	const TArray<int32> Glowing = VerseHoleGlow::SelectGlowing(Times, Now, GlowingCap, GlowEndS);
	TBitArray<> IsGlowing(false, HoleSlots.Num());
	for (const int32 Index : Glowing)
	{
		IsGlowing[SlotOf[Index]] = true;
	}
	GlowingCount = Glowing.Num();
	for (int32 Index = 0; Index < HoleSlots.Num(); ++Index)
	{
		FHoleSlot& Slot = HoleSlots[Index];
		const bool bWasGlowing = Slot.bGlowing;
		Slot.bGlowing = IsGlowing[Index];
		UMaterialInstanceDynamic* Mid = Slot.Material.Get();
		if (!Mid || Slot.Sequence == 0 || (!Slot.bGlowing && !bWasGlowing))
		{
			continue;
		}
		const float AgeS = VerseHoleGlow::AgeS(Slot.Hole.ServerTimeMs, Now);
		const FVerseHoleGlowSample Sample = Slot.bGlowing ? VerseHoleGlow::Sample(AgeS, GlowTauS, GlowEndS) : FVerseHoleGlowSample();
		Mid->SetScalarParameterValue(GlowParameter, Sample.Intensity * VerseHoleGlow::PeakEmissive);
		Mid->SetVectorParameterValue(GlowColorParameter, Sample.bGlowing ? Sample.Color : VerseHoleGlow::CharredColor());
	}
}

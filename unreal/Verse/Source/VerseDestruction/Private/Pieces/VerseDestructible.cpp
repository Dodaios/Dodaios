#include "Pieces/VerseDestructible.h"

#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "StaticMeshResources.h"
#include "Pieces/VerseDestructionManager.h"
#include "UObject/ObjectSaveContext.h"
#include "VerseCollision.h"

AVerseDestructible::AVerseDestructible()
{
	PrimaryActorTick.bCanEverTick = false;
	// The manager replicates the state; pieces themselves never replicate (One File Per Actor statics).
	bReplicates = false;

	RenderMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("RenderMesh"));
	RenderMesh->SetCollisionProfileName(VerseCollision::Profile::NoCollision);
	RenderMesh->SetCanEverAffectNavigation(false);
	RenderMesh->SetMobility(EComponentMobility::Movable);
	SetRootComponent(RenderMesh);

	ProxyMesh = CreateDefaultSubobject<UStaticMeshComponent>(TEXT("ProxyMesh"));
	ProxyMesh->SetupAttachment(RenderMesh);
	ProxyMesh->SetCollisionProfileName(VerseCollision::Profile::Destructible);
	ProxyMesh->SetHiddenInGame(true);
	ProxyMesh->SetCastShadow(false);
	ProxyMesh->SetMobility(EComponentMobility::Movable);
	ProxyMesh->SetCanEverAffectNavigation(true);
}

void AVerseDestructible::CaptureGuid()
{
#if WITH_EDITOR
	if (!PieceGuid.IsValid() && GetActorGuid().IsValid())
	{
		PieceGuid = GetActorGuid();
	}
#endif
}

void AVerseDestructible::PostLoad()
{
	Super::PostLoad();
	CaptureGuid();
	IntactRender = RenderMesh ? RenderMesh->GetStaticMesh() : nullptr;
}

void AVerseDestructible::CaptureProxyVertices()
{
#if WITH_EDITOR
	if (!IntactProxy || !IntactProxy->GetRenderData() || IntactProxy->GetRenderData()->LODResources.Num() == 0)
	{
		return;
	}
	// The proxy is never Nanite (art-pipeline 6.2), so LOD 0 render data is its source geometry.
	const FPositionVertexBuffer& Positions = IntactProxy->GetRenderData()->LODResources[0].VertexBuffers.PositionVertexBuffer;
	ProxyVertices.Reset();
	for (uint32 Vertex = 0; Vertex < Positions.GetNumVertices(); ++Vertex)
	{
		ProxyVertices.AddUnique(FVector(Positions.VertexPosition(Vertex)));
	}
#endif
}

#if WITH_EDITOR
void AVerseDestructible::PreSave(FObjectPreSaveContext SaveContext)
{
	CaptureGuid();
	CaptureProxyVertices();
	Super::PreSave(SaveContext);
}
#endif

void AVerseDestructible::BeginPlay()
{
	Super::BeginPlay();
	if (AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this))
	{
		Manager->RegisterPiece(*this);
	}
}

void AVerseDestructible::EndPlay(const EEndPlayReason::Type EndPlayReason)
{
	if (AVerseDestructionManager* Manager = AVerseDestructionManager::Get(this))
	{
		Manager->UnregisterPiece(*this);
	}
	Super::EndPlay(EndPlayReason);
}

void AVerseDestructible::OnConstruction(const FTransform& Transform)
{
	Super::OnConstruction(Transform);
	CaptureGuid();
	CaptureProxyVertices();
	if (ProxyMesh)
	{
		ProxyMesh->SetCollisionProfileName(PieceClass == EVersePieceClass::GlassPane ? VerseCollision::Profile::Glass
																					  : VerseCollision::Profile::Destructible);
		if (IntactProxy && ProxyMesh->GetStaticMesh() == nullptr)
		{
			ProxyMesh->SetStaticMesh(IntactProxy);
		}
	}
}

FVersePieceDef AVerseDestructible::MakeDef() const
{
	FVersePieceDef Def;
	Def.Guid = PieceGuid;
	Def.Class = PieceClass;
	Def.Material = Material;
	Def.Transform = GetActorTransform();
	Def.IntactBounds = IntactProxy ? IntactProxy->GetBoundingBox() : FallbackIntactBounds;
	for (int32 Index = 0; Index < HoledVariants.Num() && Index < 4; ++Index)
	{
		const FVersePieceVariant& Variant = HoledVariants[Index];
		Def.HoledBounds.Add(Variant.Proxy ? Variant.Proxy->GetBoundingBox() : Def.IntactBounds);
		Def.HoledCentroids.Add(Variant.OpeningCentroid);
	}
	for (int32 Index = 0; Index < BreachedVariants.Num() && Index < 4; ++Index)
	{
		const FVersePieceVariant& Variant = BreachedVariants[Index];
		Def.BreachedBounds.Add(Variant.Proxy ? Variant.Proxy->GetBoundingBox() : Def.IntactBounds);
		Def.BreachedCentroids.Add(Variant.OpeningCentroid);
	}
	Def.RemainsBounds = Remains.Proxy ? Remains.Proxy->GetBoundingBox() : FBox(ForceInit);
	Def.MantleLinks = MantleLinks;
	Def.DropLinks = DropLinks;
	// Authored data, identical in editor, cooked client and dedicated server (no render-data read here).
	Def.ProxyVertices = ProxyVertices;
	if (Def.ProxyVertices.Num() == 0 && Def.IntactBounds.IsValid)
	{
		const FBox& B = Def.IntactBounds;
		for (int32 Corner = 0; Corner < 8; ++Corner)
		{
			Def.ProxyVertices.Add(FVector((Corner & 1) ? B.Max.X : B.Min.X, (Corner & 2) ? B.Max.Y : B.Min.Y, (Corner & 4) ? B.Max.Z : B.Min.Z));
		}
	}
	return Def;
}

TArray<const FVersePieceDebrisSet*> AVerseDestructible::FindDebrisSets(EVersePieceState State, uint8 Variant) const
{
	TArray<const FVersePieceDebrisSet*> Out;
	for (const FVersePieceDebrisSet& Set : DebrisSets)
	{
		if (Set.State == State && (State == EVersePieceState::Destroyed || Set.Variant == Variant))
		{
			Out.Add(&Set);
		}
	}
	return Out;
}

const FVersePieceVariant* AVerseDestructible::FindVariant(EVersePieceState State, uint8 Variant) const
{
	const TArray<FVersePieceVariant>* List = nullptr;
	if (State == EVersePieceState::Holed)
	{
		List = &HoledVariants;
	}
	else if (State == EVersePieceState::Breached)
	{
		List = &BreachedVariants;
	}
	else if (State == EVersePieceState::Destroyed)
	{
		return &Remains;
	}
	if (!List || List->Num() == 0)
	{
		return nullptr;
	}
	return List->IsValidIndex(Variant) ? &(*List)[Variant] : &(*List)[0];
}

UStaticMesh* AVerseDestructible::GetPresentedProxy() const
{
	return ProxyMesh ? ProxyMesh->GetStaticMesh() : nullptr;
}

void AVerseDestructible::ApplyPresentation(EVersePieceState State, uint8 Variant, EVersePieceState RepairFrom)
{
	// While Repairing the gameplay proxy stays the pre-repair proxy until completion (destruction.md 7).
	const EVersePieceState ProxyState = State == EVersePieceState::Repairing ? RepairFrom : State;
	if (IntactRender == nullptr && RenderMesh)
	{
		IntactRender = RenderMesh->GetStaticMesh();
	}
	UStaticMesh* Proxy = IntactProxy;
	UStaticMesh* Render = IntactRender;
	bool bRenderVisible = true;
	if (ProxyState == EVersePieceState::Holed || ProxyState == EVersePieceState::Breached || ProxyState == EVersePieceState::Destroyed)
	{
		const FVersePieceVariant* Look = FindVariant(ProxyState, Variant);
		Proxy = Look ? Look->Proxy.Get() : (ProxyState == EVersePieceState::Destroyed ? nullptr : IntactProxy.Get());
		if (Look && Look->Render)
		{
			Render = Look->Render;
		}
		else if (ProxyState == EVersePieceState::Destroyed)
		{
			bRenderVisible = false;
		}
	}
	if (ProxyMesh)
	{
		if (ProxyMesh->GetStaticMesh() != Proxy)
		{
			// SetStaticMesh re-registers the component with the navigation system (old and new bounds dirty).
			ProxyMesh->SetStaticMesh(Proxy);
		}
		ProxyMesh->SetCollisionEnabled(Proxy ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);
	}
	if (RenderMesh)
	{
		if (Render && RenderMesh->GetStaticMesh() != Render)
		{
			RenderMesh->SetStaticMesh(Render);
		}
		RenderMesh->SetVisibility(bRenderVisible);
	}
	PresentedState = State;
	PresentedVariant = Variant;
}

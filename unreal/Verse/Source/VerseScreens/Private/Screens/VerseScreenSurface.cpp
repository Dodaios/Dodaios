#include "Screens/VerseScreenSurface.h"

#include "Components/MeshComponent.h"
#include "Engine/CanvasRenderTarget2D.h"
#include "Materials/MaterialInstanceDynamic.h"
#include "Misc/App.h"

bool UVerseScreenSurface::Init(UObject* WorldContext, int32 Width, int32 Height, FLinearColor Ground)
{
	SizeX = FMath::Clamp(Width, 16, 4096);
	SizeY = FMath::Clamp(Height, 16, 4096);
	if (!FApp::CanEverRender() || !WorldContext)
	{
		return false;
	}
	Target = UCanvasRenderTarget2D::CreateCanvasRenderTarget2D(WorldContext, UCanvasRenderTarget2D::StaticClass(), SizeX, SizeY);
	if (!Target)
	{
		return false;
	}
	Target->ClearColor = Ground;
	// Dirty-row drawing: what was painted stays until a row is drawn again.
	Target->SetShouldClearRenderTargetOnReceiveUpdate(false);
	Target->OnCanvasRenderTargetUpdate.AddDynamic(this, &UVerseScreenSurface::HandleUpdate);
	return true;
}

void UVerseScreenSurface::Paint(TFunctionRef<void(UCanvas*, int32, int32)> Painter)
{
	if (!Target)
	{
		return;
	}
	Pending = &Painter;
	Target->FastUpdateResource();
	Pending = nullptr;
}

void UVerseScreenSurface::HandleUpdate(UCanvas* Canvas, int32 InWidth, int32 InHeight)
{
	if (Pending && Canvas)
	{
		(*Pending)(Canvas, InWidth, InHeight);
		++Paints;
	}
}

void UVerseScreenSurface::Bind(UMeshComponent* Mesh, int32 MaterialIndex, FName TextureParameter, UMaterialInterface* InMaterial)
{
	if (!Mesh || !Target)
	{
		return;
	}
	UMaterialInterface* Base = InMaterial ? InMaterial : Mesh->GetMaterial(MaterialIndex);
	if (!Base)
	{
		return;
	}
	Material = UMaterialInstanceDynamic::Create(Base, this);
	Material->SetTextureParameterValue(TextureParameter, Target);
	Mesh->SetMaterial(MaterialIndex, Material);
}

UTexture* UVerseScreenSurface::GetTexture() const
{
	return Target;
}

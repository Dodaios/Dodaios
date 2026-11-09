#pragma once

#include "CoreMinimal.h"
#include "UObject/Object.h"

#include "VerseScreenSurface.generated.h"

class UCanvas;
class UCanvasRenderTarget2D;
class UMaterialInstanceDynamic;
class UMeshComponent;
class UTexture;

/**
 * One render target per monitor (WP16.2). Never cleared between paints, so a repaint draws only
 * the rows that changed. Without a renderer (-nullrhi) there is no target and Paint does nothing.
 */
UCLASS()
class VERSESCREENS_API UVerseScreenSurface : public UObject
{
	GENERATED_BODY()

public:
	/** Creates the target; false when the process cannot render. */
	bool Init(UObject* WorldContext, int32 Width, int32 Height, FLinearColor Ground);

	/** Runs Painter synchronously on the target's canvas. */
	void Paint(TFunctionRef<void(UCanvas*, int32, int32)> Painter);

	/** Shows the target on Mesh's material slot through a dynamic instance's texture parameter. */
	void Bind(UMeshComponent* Mesh, int32 MaterialIndex, FName TextureParameter, class UMaterialInterface* Material);

	UTexture* GetTexture() const;
	bool CanPaint() const { return Target != nullptr; }
	int32 Width() const { return SizeX; }
	int32 Height() const { return SizeY; }
	int32 PaintCount() const { return Paints; }

private:
	UFUNCTION()
	void HandleUpdate(UCanvas* Canvas, int32 InWidth, int32 InHeight);

	UPROPERTY(Transient)
	TObjectPtr<UCanvasRenderTarget2D> Target;

	UPROPERTY(Transient)
	TObjectPtr<UMaterialInstanceDynamic> Material;

	TFunctionRef<void(UCanvas*, int32, int32)>* Pending = nullptr;
	int32 SizeX = 0;
	int32 SizeY = 0;
	int32 Paints = 0;
};

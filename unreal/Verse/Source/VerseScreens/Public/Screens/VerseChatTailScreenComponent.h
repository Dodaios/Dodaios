#pragma once

#include "Components/SceneComponent.h"
#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Render/VerseTerminalPainter.h"

#include "VerseChatTailScreenComponent.generated.h"

class UMaterialInterface;
class UVerseScreenSurface;
class UVerseTerminalTheme;

/** One chat tail line (contracts/bridge-protocol.md 6). */
struct FVerseChatTailLine
{
	/** `user`, `agent`, `tool`, `notice`, `error`; anything else reads as `notice`. */
	FString Kind;
	FString Text;
};

/**
 * A console screen showing its officer's chat tail (WP16.4, parity E-01, E-02). The console
 * belongs to its officer wherever they are; without an owner it says so.
 */
UCLASS(ClassGroup = (Verse), meta = (BlueprintSpawnableComponent))
class VERSESCREENS_API UVerseChatTailScreenComponent : public USceneComponent
{
	GENERATED_BODY()

public:
	UVerseChatTailScreenComponent();

	/** The officer whose tail this console shows (society roster id); empty = no owner. */
	UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Console")
	FString AgentId;

	UPROPERTY(EditAnywhere, Category = "Console")
	FIntPoint Resolution = FIntPoint(768, 512);

	/** Text columns across the screen; lines longer than this are cut with an ellipsis. */
	UPROPERTY(EditAnywhere, Category = "Console")
	int32 Columns = 56;

	UPROPERTY(EditAnywhere, Category = "Console")
	TObjectPtr<UVerseTerminalTheme> Theme;

	UPROPERTY(EditAnywhere, Category = "Console")
	TObjectPtr<UMaterialInterface> ScreenMaterial;

	UPROPERTY(EditAnywhere, Category = "Console")
	FName ScreenParameter = TEXT("Screen");

	/** Applies a `chat_tails.update` data object for this console's agent; false when it is not for it or unchanged. */
	bool ApplyUpdate(const FJsonObject& Data);

	const TArray<FVerseChatTailLine>& Lines() const { return TailLines; }
	const FString& Version() const { return TailVersion; }
	bool HasTail() const { return bReceived; }

	/** Colour of a line kind (agent green, tool grey, notice amber, error red, user ink). */
	FColor KindColour(const FString& Kind) const;

	bool NeedsRedraw() const { return bDirty; }
	/** Builds and paints; returns the number of lines drawn. */
	int32 Redraw(FVerseTerminalDrawList& Scratch);

protected:
	virtual void BeginPlay() override;
	virtual void EndPlay(const EEndPlayReason::Type Reason) override;

private:
	UPROPERTY(Transient)
	TObjectPtr<UVerseScreenSurface> ScreenSurface;

	FVerseTerminalPalette Colours;
	TArray<FVerseChatTailLine> TailLines;
	/** Cut copies of the lines, kept alive for the draw list's views. */
	TArray<FString> Shown;
	FString TailVersion;
	bool bReceived = false;
	bool bDirty = true;
};

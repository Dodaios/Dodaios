#pragma once

#include "CoreMinimal.h"
#include "Engine/DataAsset.h"

#include "VerseTerminalTheme.generated.h"

class UFont;

/**
 * The IDE terminal theme as a DataAsset (contracts/bridge-protocol.md 5.4 "Palette"): the 16 base
 * colours are never sent over the bridge, so monitors use these. Defaults equal the web xterm
 * DARK_TERMINAL_THEME (frontend components/agentic/terminalThemes.ts), so a monitor matches the IDE.
 */
UCLASS(BlueprintType)
class VERSESCREENS_API UVerseTerminalTheme : public UPrimaryDataAsset
{
	GENERATED_BODY()

public:
	UVerseTerminalTheme();

	/** ANSI 0-15: black, red, green, yellow, blue, magenta, cyan, white, then the bright row. */
	UPROPERTY(EditAnywhere, Category = "Terminal")
	TArray<FColor> Ansi;

	UPROPERTY(EditAnywhere, Category = "Terminal")
	FColor Foreground;

	/** Opaque ground (the web theme's background with its alpha dropped). */
	UPROPERTY(EditAnywhere, Category = "Terminal")
	FColor Background;

	UPROPERTY(EditAnywhere, Category = "Terminal")
	FColor Cursor;

	/**
	 * Monospace font. The IDE draws JetBrains Mono (SIL OFL); any licence is allowed with a provenance row,
	 * so the default is the engine's own monospace face until the integration owner decides.
	 */
	UPROPERTY(EditAnywhere, Category = "Terminal")
	TSoftObjectPtr<UFont> Font;

	/** The IDE's terminal font size; a monitor scales from it (13 px reference, architecture 5.3). */
	UPROPERTY(EditAnywhere, Category = "Terminal")
	float ReferencePx = 13.f;

	/** Dim mixes fg toward the ground by this much (terminalCanvas.ts). */
	UPROPERTY(EditAnywhere, Category = "Terminal")
	float DimMix = 0.45f;

	static const UVerseTerminalTheme& Default();
};

/** The resolved 256-colour table of a theme and the run colour rules of the web painter. */
struct VERSESCREENS_API FVerseTerminalPalette
{
	FColor Table[256];
	FColor Ink;
	FColor Ground;
	FColor CursorColour;
	float DimMix = 0.45f;

	void Build(const UVerseTerminalTheme& Theme);

	/** Palette entry 0-255 (16 from the theme, the 6x6x6 cube, 24 greys). */
	FColor Index(int32 I) const { return Table[I & 0xFF]; }

	/**
	 * A run's drawn colours: bold brightens palette 0-7, inverse swaps (a default bg reads as the
	 * ground), dim mixes fg toward the bg. bHasBg is false when the ground shows through.
	 */
	void Resolve(uint32 Fg, uint32 Bg, uint16 Attrs, FColor& OutFg, FColor& OutBg, bool& bOutHasBg) const;
};

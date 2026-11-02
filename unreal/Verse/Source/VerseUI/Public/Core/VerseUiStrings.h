#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/**
 * Every user-visible string of the Verse UI (WP18.1, A18.4). Code names keys only; text comes
 * from the catalogue unreal/Verse/Data/ui/locales/strings.<lang>.json (5 locales) overlaid by the strings the
 * bridge sends in welcome.locale and settings.changed (bridge-protocol 3.2, 12), so a string
 * change needs no rebuild. Lookup order: bridge string, catalogue in the language, catalogue in
 * the fallback language, English, the key itself (a visible bug, logged once).
 */
class VERSEUI_API FVerseUiStrings
{
public:
	/** en, de, es, pt, zh: the 5 locales the web app bundles. */
	static const TArray<FString>& SupportedLanguages();

	/** <project>/Data/ui/locales */
	static FString DefaultCatalogueDir();

	/** Loads strings.<lang>.json of every supported language from Dir (replaces the catalogue). */
	bool LoadCatalogue(const FString& Dir, FString* OutError = nullptr);
	/** Merges one language file {lang, strings}. */
	bool LoadCatalogueJson(const FString& Json, FString* OutError = nullptr);

	/** Switches language; an unsupported code falls back to Fallback, then English. */
	void SetLanguage(const FString& Lang, const FString& Fallback = TEXT("en"));

	/** welcome.locale: {lang, fallback, strings}. Replaces earlier bridge strings. */
	void ApplyBridgeLocale(const TSharedPtr<FJsonObject>& Locale);

	/** settings.changed {lang?, strings?}: lang switches, strings merge over earlier ones. */
	void ApplySettingsChanged(const TSharedPtr<FJsonObject>& Data);

	FText Get(const FString& Key) const;

	/** Named-argument format, for example "{kills} kills". */
	FText Format(const FString& Key, const FFormatNamedArguments& Args) const;

	/** Raw catalogue text of Key in Lang, empty when missing (tests). */
	FString GetIn(const FString& Key, const FString& Lang) const;

	TArray<FString> GetKeys() const;
	const FString& GetLanguage() const { return Language; }
	int32 NumBridgeStrings() const { return BridgeStrings.Num(); }

private:
	FString Resolve(const FString& Key) const;

	/** key -> lang -> text */
	TMap<FString, TMap<FString, FString>> Catalogue;
	/** Bridge strings for the current language. */
	TMap<FString, FString> BridgeStrings;
	FString Language = TEXT("en");
	FString Fallback = TEXT("en");
	mutable TSet<FString> ReportedMissing;
};

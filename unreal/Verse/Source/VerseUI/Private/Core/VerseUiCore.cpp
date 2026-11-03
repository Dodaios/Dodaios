#include "Core/VerseUiLayout.h"
#include "Core/VerseUiStrings.h"
#include "Core/VerseUiTheme.h"
#include "Internationalization/Culture.h"
#include "Internationalization/Internationalization.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "VerseLog.h"

// ---------------------------------------------------------------------------------------------
// Theme

bool VerseUiTheme::IsForbiddenAccent(const FLinearColor& Colour)
{
	const FLinearColor Hsv = Colour.LinearRGBToHSV();
	const float Hue = Hsv.R;
	const float Saturation = Hsv.G;
	const float Value = Hsv.B;
	return Saturation > 0.25f && Value > 0.05f && Hue >= 170.f && Hue <= 300.f;
}

TArray<FLinearColor> VerseUiTheme::AllColours()
{
	return {Steel, SteelLight, Edge, Text, TextDim, Amber, Red, Gold, Blocked, Shadow};
}

// ---------------------------------------------------------------------------------------------
// Layout

FVerseUiLayout FVerseUiLayout::Compute(const FVector2D& Viewport, float SafeFraction, const FMargin& PlatformPadding, float UserTextScale)
{
	FVerseUiLayout Layout;
	Layout.Viewport = FVector2D(FMath::Max(1.0, Viewport.X), FMath::Max(1.0, Viewport.Y));
	Layout.Scale = FMath::Clamp(float(FMath::Min(Layout.Viewport.X / ReferenceWidth, Layout.Viewport.Y / ReferenceHeight)), 0.5f, 4.f);
	Layout.TextScale = Layout.Scale * FMath::Clamp(UserTextScale, 0.8f, 1.6f);

	const float Fraction = FMath::Clamp(SafeFraction, 0.f, 0.2f);
	const double Left = FMath::Max<double>(Layout.Viewport.X * Fraction, PlatformPadding.Left);
	const double Right = FMath::Max<double>(Layout.Viewport.X * Fraction, PlatformPadding.Right);
	const double Top = FMath::Max<double>(Layout.Viewport.Y * Fraction, PlatformPadding.Top);
	const double Bottom = FMath::Max<double>(Layout.Viewport.Y * Fraction, PlatformPadding.Bottom);
	Layout.SafeMin = FVector2D(Left, Top);
	Layout.SafeMax = FVector2D(Layout.Viewport.X - Right, Layout.Viewport.Y - Bottom);
	return Layout;
}

int32 FVerseUiLayout::FontSize(float ReferencePt) const
{
	return FMath::Max(6, FMath::RoundToInt(ReferencePt * TextScale));
}

FVector2D FVerseUiLayout::Place(EVerseUiAnchor Anchor, const FVector2D& Size, const FVector2D& Offset) const
{
	const FVector2D Inset = Offset * Scale;
	const FVector2D Safe = SafeSize();
	FVector2D P = SafeMin;
	switch (Anchor)
	{
	case EVerseUiAnchor::TopLeft: P = SafeMin + Inset; break;
	case EVerseUiAnchor::Top: P = FVector2D(SafeMin.X + (Safe.X - Size.X) * 0.5 + Inset.X, SafeMin.Y + Inset.Y); break;
	case EVerseUiAnchor::TopRight: P = FVector2D(SafeMax.X - Size.X - Inset.X, SafeMin.Y + Inset.Y); break;
	case EVerseUiAnchor::Left: P = FVector2D(SafeMin.X + Inset.X, SafeMin.Y + (Safe.Y - Size.Y) * 0.5 + Inset.Y); break;
	case EVerseUiAnchor::Centre: P = SafeMin + (Safe - Size) * 0.5 + Inset; break;
	case EVerseUiAnchor::Right: P = FVector2D(SafeMax.X - Size.X - Inset.X, SafeMin.Y + (Safe.Y - Size.Y) * 0.5 + Inset.Y); break;
	case EVerseUiAnchor::BottomLeft: P = FVector2D(SafeMin.X + Inset.X, SafeMax.Y - Size.Y - Inset.Y); break;
	case EVerseUiAnchor::Bottom: P = FVector2D(SafeMin.X + (Safe.X - Size.X) * 0.5 + Inset.X, SafeMax.Y - Size.Y - Inset.Y); break;
	case EVerseUiAnchor::BottomRight: P = SafeMax - Size - Inset; break;
	}
	P.X = FMath::Clamp(P.X, SafeMin.X, FMath::Max(SafeMin.X, SafeMax.X - Size.X));
	P.Y = FMath::Clamp(P.Y, SafeMin.Y, FMath::Max(SafeMin.Y, SafeMax.Y - Size.Y));
	return P;
}

// ---------------------------------------------------------------------------------------------
// Strings

const TArray<FString>& FVerseUiStrings::SupportedLanguages()
{
	static const TArray<FString> Languages = {TEXT("en"), TEXT("de"), TEXT("es"), TEXT("pt"), TEXT("zh")};
	return Languages;
}

FString FVerseUiStrings::DefaultCatalogueDir()
{
	return FPaths::Combine(FPaths::ProjectDir(), TEXT("Data"), TEXT("ui"));
}

bool FVerseUiStrings::LoadCatalogue(const FString& Dir, FString* OutError)
{
	Catalogue.Reset();
	bool bAll = true;
	for (const FString& Lang : SupportedLanguages())
	{
		const FString Path = FPaths::Combine(Dir, FString::Printf(TEXT("strings.%s.json"), *Lang));
		FString Json;
		if (!FFileHelper::LoadFileToString(Json, *Path) || !LoadCatalogueJson(Json, OutError))
		{
			if (OutError && OutError->IsEmpty())
			{
				*OutError = FString::Printf(TEXT("cannot read %s"), *Path);
			}
			bAll = false;
		}
	}
	return bAll;
}

bool FVerseUiStrings::LoadCatalogueJson(const FString& Json, FString* OutError)
{
	TSharedPtr<FJsonObject> Root;
	const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Json);
	if (!FJsonSerializer::Deserialize(Reader, Root) || !Root.IsValid())
	{
		if (OutError)
		{
			*OutError = TEXT("strings catalogue is not JSON");
		}
		return false;
	}
	const TSharedPtr<FJsonObject>* Table = nullptr;
	FString Lang;
	if (!Root->TryGetObjectField(TEXT("strings"), Table) || !Root->TryGetStringField(TEXT("lang"), Lang))
	{
		if (OutError)
		{
			*OutError = TEXT("strings file needs \"lang\" and a \"strings\" object");
		}
		return false;
	}
	for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*Table)->Values)
	{
		FString Text;
		if (Entry.Value.IsValid() && Entry.Value->TryGetString(Text))
		{
			Catalogue.FindOrAdd(Entry.Key).Add(Lang, Text);
		}
	}
	return true;
}

void FVerseUiStrings::SetLanguage(const FString& Lang, const FString& InFallback)
{
	const FString Short = Lang.Left(2).ToLower();
	const FString ShortFallback = InFallback.Left(2).ToLower();
	Fallback = SupportedLanguages().Contains(ShortFallback) ? ShortFallback : FString(TEXT("en"));
	Language = SupportedLanguages().Contains(Short) ? Short : Fallback;
}

void FVerseUiStrings::ApplyBridgeLocale(const TSharedPtr<FJsonObject>& Locale)
{
	if (!Locale.IsValid())
	{
		return;
	}
	FString Lang = Language;
	FString Fb = Fallback;
	Locale->TryGetStringField(TEXT("lang"), Lang);
	Locale->TryGetStringField(TEXT("fallback"), Fb);
	SetLanguage(Lang, Fb);
	BridgeStrings.Reset();
	const TSharedPtr<FJsonObject>* Table = nullptr;
	if (Locale->TryGetObjectField(TEXT("strings"), Table))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*Table)->Values)
		{
			FString Text;
			if (Entry.Value.IsValid() && Entry.Value->TryGetString(Text))
			{
				BridgeStrings.Add(Entry.Key, Text);
			}
		}
	}
}

void FVerseUiStrings::ApplySettingsChanged(const TSharedPtr<FJsonObject>& Data)
{
	if (!Data.IsValid())
	{
		return;
	}
	FString Lang;
	if (Data->TryGetStringField(TEXT("lang"), Lang))
	{
		const FString Before = Language;
		SetLanguage(Lang, Fallback);
		if (Before != Language)
		{
			// Bridge strings were for the old language; the new set follows in "strings".
			BridgeStrings.Reset();
		}
	}
	const TSharedPtr<FJsonObject>* Table = nullptr;
	if (Data->TryGetObjectField(TEXT("strings"), Table))
	{
		for (const TPair<FString, TSharedPtr<FJsonValue>>& Entry : (*Table)->Values)
		{
			FString Text;
			if (Entry.Value.IsValid() && Entry.Value->TryGetString(Text))
			{
				BridgeStrings.Add(Entry.Key, Text);
			}
		}
	}
}

FString FVerseUiStrings::Resolve(const FString& Key) const
{
	if (const FString* Bridge = BridgeStrings.Find(Key))
	{
		return *Bridge;
	}
	if (const TMap<FString, FString>* PerLang = Catalogue.Find(Key))
	{
		for (const FString* Lang : {&Language, &Fallback})
		{
			if (const FString* Text = PerLang->Find(*Lang))
			{
				return *Text;
			}
		}
		if (const FString* English = PerLang->Find(TEXT("en")))
		{
			return *English;
		}
	}
	if (!ReportedMissing.Contains(Key))
	{
		ReportedMissing.Add(Key);
		UE_LOG(LogVerseUI, Warning, TEXT("VerseUI: missing string %s"), *Key);
	}
	return Key;
}

FText FVerseUiStrings::Get(const FString& Key) const
{
	return FText::AsCultureInvariant(Resolve(Key));
}

FText FVerseUiStrings::Format(const FString& Key, const FFormatNamedArguments& Args) const
{
	return FText::Format(FTextFormat::FromString(Resolve(Key)), Args);
}

FString FVerseUiStrings::GetIn(const FString& Key, const FString& Lang) const
{
	if (const TMap<FString, FString>* PerLang = Catalogue.Find(Key))
	{
		if (const FString* Text = PerLang->Find(Lang))
		{
			return *Text;
		}
	}
	return FString();
}

FCulturePtr FVerseUiStrings::GetCulture() const
{
	if (!CachedCulture.IsValid() || CachedCultureLang != Language)
	{
		CachedCultureLang = Language;
		CachedCulture = FInternationalization::Get().GetCulture(Language);
		if (!CachedCulture.IsValid())
		{
			CachedCulture = FInternationalization::Get().GetCulture(TEXT("en"));
		}
	}
	return CachedCulture;
}

FText FVerseUiStrings::Number(double Value, int32 FractionDigits, bool bGrouping) const
{
	FNumberFormattingOptions Options;
	Options.UseGrouping = bGrouping;
	Options.MinimumFractionalDigits = FractionDigits;
	Options.MaximumFractionalDigits = FractionDigits;
	return FText::AsNumber(Value, &Options, GetCulture());
}

FText FVerseUiStrings::Percent(double Value, int32 FractionDigits) const
{
	FNumberFormattingOptions Options;
	Options.MinimumFractionalDigits = FractionDigits;
	Options.MaximumFractionalDigits = FractionDigits;
	return FText::AsPercent(Value, &Options, GetCulture());
}

TArray<FString> FVerseUiStrings::GetKeys() const
{
	TArray<FString> Keys;
	Catalogue.GetKeys(Keys);
	Keys.Sort();
	return Keys;
}

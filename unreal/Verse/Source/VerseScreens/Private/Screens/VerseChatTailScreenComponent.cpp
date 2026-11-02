#include "Screens/VerseChatTailScreenComponent.h"

#include "Components/MeshComponent.h"
#include "Engine/Font.h"
#include "GameFramework/Actor.h"
#include "Render/VerseTerminalTheme.h"
#include "Screens/VerseScreenSurface.h"
#include "Screens/VerseScreensSubsystem.h"
#include "Stations/VerseStationSubsystem.h"

namespace
{
	constexpr int32 MaxTailLines = 12;
}

UVerseChatTailScreenComponent::UVerseChatTailScreenComponent()
{
	PrimaryComponentTick.bCanEverTick = false;
	Colours.Build(UVerseTerminalTheme::Default());
}

bool UVerseChatTailScreenComponent::ApplyUpdate(const FJsonObject& Data)
{
	FString Agent;
	if (!Data.TryGetStringField(TEXT("agent_id"), Agent) || Agent != AgentId)
	{
		return false;
	}
	FString Version;
	Data.TryGetStringField(TEXT("version"), Version);
	if (bReceived && Version == TailVersion)
	{
		return false;
	}
	TArray<FVerseChatTailLine> Next;
	const TArray<TSharedPtr<FJsonValue>>* Lines = nullptr;
	if (Data.TryGetArrayField(TEXT("lines"), Lines))
	{
		for (const TSharedPtr<FJsonValue>& Value : *Lines)
		{
			const TSharedPtr<FJsonObject>* Obj = nullptr;
			if (!Value.IsValid() || !Value->TryGetObject(Obj))
			{
				continue;
			}
			FVerseChatTailLine& Line = Next.AddDefaulted_GetRef();
			(*Obj)->TryGetStringField(TEXT("kind"), Line.Kind);
			(*Obj)->TryGetStringField(TEXT("text"), Line.Text);
		}
	}
	// The relay sends at most 12; keep the newest should a longer one arrive.
	if (Next.Num() > MaxTailLines)
	{
		Next.RemoveAt(0, Next.Num() - MaxTailLines);
	}
	TailLines = MoveTemp(Next);
	TailVersion = Version;
	bReceived = true;
	bDirty = true;
	return true;
}

FColor UVerseChatTailScreenComponent::KindColour(const FString& Kind) const
{
	if (Kind == TEXT("user")) { return Colours.Ink; }
	if (Kind == TEXT("agent")) { return Colours.Index(2); }
	if (Kind == TEXT("tool")) { return Colours.Index(8); }
	if (Kind == TEXT("error")) { return Colours.Index(1); }
	return Colours.Index(3);
}

int32 UVerseChatTailScreenComponent::Redraw(FVerseTerminalDrawList& Scratch)
{
	Scratch.Reset();
	Shown.Reset();
	const UVerseStationSubsystem* Stations = UVerseStationSubsystem::Get(this);
	FVerseTerminalLayout L = FVerseTerminalLayout::Fit(Resolution.X, Resolution.Y, Columns, MaxTailLines, 2.f);
	if (AgentId.IsEmpty() || (bReceived && TailLines.Num() == 0))
	{
		// Parity E-02: a console without an owner (or an owner without a chat) says so.
		Shown.Add(Stations ? Stations->Localize(TEXT("verse.screen.vacant"), TEXT("VACANT")) : FString(TEXT("VACANT")));
		VerseTerminalPainter::BuildPage(Colours, Resolution.X, Resolution.Y, Shown[0], Colours.Index(8), Scratch);
		L.CellH = FMath::Max(8.f, float(Resolution.Y) / 8.f);
		L.CellW = L.CellH * 0.5f;
	}
	else
	{
		Scratch.Rects.Add({FVector2f(0.f, 0.f), FVector2f(float(Resolution.X), float(Resolution.Y)), Colours.Ground});
		// Newest line at the bottom, as the web console.
		const int32 First = FMath::Max(0, TailLines.Num() - L.VisibleRows);
		const int32 Top = L.VisibleRows - (TailLines.Num() - First);
		Shown.Reserve(TailLines.Num() - First);
		for (int32 I = First; I < TailLines.Num(); ++I)
		{
			FString Text = TailLines[I].Text;
			if (Text.Len() > Columns)
			{
				Text = Text.Left(FMath::Max(0, Columns - 1)) + TEXT("…");
			}
			Shown.Add(MoveTemp(Text));
		}
		for (int32 I = 0; I < Shown.Num(); ++I)
		{
			FVerseTerminalText& T = Scratch.Texts.AddDefaulted_GetRef();
			T.Row = Top + I;
			T.Pos = FVector2f(0.f, float(T.Row) * L.CellH);
			T.Cells = Shown[I].Len();
			T.Colour = KindColour(TailLines[First + I].Kind);
			T.Text = Shown[I];
		}
		Scratch.RowsDrawn = Shown.Num();
	}
	if (ScreenSurface && ScreenSurface->CanPaint())
	{
		UFont* Font = (Theme ? Theme.Get() : &UVerseTerminalTheme::Default())->Font.LoadSynchronous();
		ScreenSurface->Paint([&](UCanvas* Canvas, int32, int32) { VerseTerminalPainter::Submit(Canvas, Font, L, Scratch); });
	}
	bDirty = false;
	return Scratch.RowsDrawn;
}

void UVerseChatTailScreenComponent::BeginPlay()
{
	Super::BeginPlay();
	Colours.Build(Theme ? *Theme : UVerseTerminalTheme::Default());
	ScreenSurface = NewObject<UVerseScreenSurface>(this);
	if (ScreenSurface->Init(this, Resolution.X, Resolution.Y, FLinearColor(Colours.Ground)) && GetOwner())
	{
		ScreenSurface->Bind(GetOwner()->FindComponentByClass<UMeshComponent>(), 0, ScreenParameter, ScreenMaterial);
	}
	if (UVerseScreensSubsystem* Screens = UVerseScreensSubsystem::Get(this))
	{
		Screens->RegisterChatScreen(this);
	}
}

void UVerseChatTailScreenComponent::EndPlay(const EEndPlayReason::Type Reason)
{
	if (UVerseScreensSubsystem* Screens = UVerseScreensSubsystem::Get(this))
	{
		Screens->UnregisterChatScreen(this);
	}
	Super::EndPlay(Reason);
}

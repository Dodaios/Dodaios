#include "Camera/VerseDeckCamera.h"
#include "Decks/VerseDeckSubsystem.h"
#include "Dom/JsonObject.h"
#include "Qa/VerseQaRegistry.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Space/VerseSpaceView.h"

// Verse.QA.View.* and Verse.QA.Space.* (parity Q-05, Q-07): the deck camera and the space view,
// driven without a mouse. Registered by the deck subsystem while it lives.

namespace VerseDecksQa
{
	FString QaError(const FString& Message)
	{
		return FString::Printf(TEXT("{\"error\":\"%s\"}"), *Message.ReplaceCharWithEscapedChar());
	}

	bool Number(const TArray<FString>& Args, int32 Index, double& Out)
	{
		if (!Args.IsValidIndex(Index) || !Args[Index].IsNumeric())
		{
			return false;
		}
		Out = FCString::Atod(*Args[Index]);
		return FMath::IsFinite(Out);
	}
}

void UVerseDeckSubsystem::RegisterQa()
{
	using namespace VerseDecksQa;

	UVerseQaRegistry* Registry = UVerseQaRegistry::Get();
	if (Registry == nullptr)
	{
		return;
	}
	TWeakObjectPtr<UVerseDeckSubsystem> Weak(this);
	auto WithCamera = [Weak](TFunction<FString(AVerseDeckCamera&, const TArray<FString>&)> Body)
	{
		return [Weak, Body](const TArray<FString>& Args) -> FString
		{
			UVerseDeckSubsystem* Self = Weak.Get();
			AVerseDeckCamera* DeckCamera = Self ? Self->GetCamera() : nullptr;
			if (DeckCamera == nullptr)
			{
				return QaError(TEXT("no deck camera (no deck loaded)"));
			}
			return Body(*DeckCamera, Args);
		};
	};

	const TPair<FString, TPair<FString, FVerseQaHandler>> Commands[] = {
		{ TEXT("Verse.QA.View.Set"), { TEXT("Verse.QA.View.Set overview|third|first"), WithCamera([](AVerseDeckCamera& Cam, const TArray<FString>& Args) -> FString
			{
				const TOptional<EVerseDeckView> View = Args.Num() > 0 ? Verse::DeckView::FromName(Args[0]) : TOptional<EVerseDeckView>();
				if (!View.IsSet())
				{
					return QaError(TEXT("usage: Verse.QA.View.Set overview|third|first"));
				}
				Cam.SetView(View.GetValue());
				return Cam.StateJson();
			}) } },
		{ TEXT("Verse.QA.View.Look"), { TEXT("Verse.QA.View.Look <dx px> <dy px>"), WithCamera([](AVerseDeckCamera& Cam, const TArray<FString>& Args) -> FString
			{
				double Dx = 0.0;
				double Dy = 0.0;
				if (!Number(Args, 0, Dx) || !Number(Args, 1, Dy))
				{
					return QaError(TEXT("usage: Verse.QA.View.Look <dx> <dy>"));
				}
				Cam.Look(static_cast<float>(Dx), static_cast<float>(Dy), true);
				return Cam.StateJson();
			}) } },
		{ TEXT("Verse.QA.View.Zoom"), { TEXT("Verse.QA.View.Zoom <factor> (> 1 out)"), WithCamera([](AVerseDeckCamera& Cam, const TArray<FString>& Args) -> FString
			{
				double Factor = 0.0;
				if (!Number(Args, 0, Factor) || Factor <= 0.0)
				{
					return QaError(TEXT("usage: Verse.QA.View.Zoom <factor>"));
				}
				Cam.Zoom(static_cast<float>(Factor));
				return Cam.StateJson();
			}) } },
		{ TEXT("Verse.QA.View.State"), { TEXT("Verse.QA.View.State"), WithCamera([](AVerseDeckCamera& Cam, const TArray<FString>&) -> FString
			{
				return Cam.StateJson();
			}) } },
		{ TEXT("Verse.QA.Space.Set"), { TEXT("Verse.QA.Space.Set <field>=<number> ..."), [Weak](const TArray<FString>& Args) -> FString
			{
				UVerseDeckSubsystem* Self = Weak.Get();
				AVerseSpaceView* Space = Self ? Self->GetSpaceView() : nullptr;
				if (Space == nullptr)
				{
					return QaError(TEXT("no space view (no deck loaded)"));
				}
				for (const FString& Arg : Args)
				{
					FString Field;
					FString Value;
					if (!Arg.Split(TEXT("="), &Field, &Value) || !Value.IsNumeric() || !Space->Look.Set(Field, FCString::Atod(*Value)))
					{
						return QaError(FString::Printf(TEXT("bad field '%s'"), *Arg));
					}
				}
				return Space->Look.ToJson(Space->ElapsedS);
			} } },
		{ TEXT("Verse.QA.Space.State"), { TEXT("Verse.QA.Space.State"), [Weak](const TArray<FString>&) -> FString
			{
				UVerseDeckSubsystem* Self = Weak.Get();
				AVerseSpaceView* Space = Self ? Self->GetSpaceView() : nullptr;
				return Space ? Space->Look.ToJson(Space->ElapsedS) : QaError(TEXT("no space view (no deck loaded)"));
			} } },
	};
	for (const auto& Command : Commands)
	{
		if (Registry->Register(Command.Key, Command.Value.Key, Command.Value.Value))
		{
			QaCommands.Add(Command.Key);
		}
	}
}

void UVerseDeckSubsystem::UnregisterQa()
{
	if (UVerseQaRegistry* Registry = UVerseQaRegistry::Get())
	{
		for (const FString& Command : QaCommands)
		{
			Registry->Unregister(Command);
		}
	}
	QaCommands.Reset();
}

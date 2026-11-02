#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "Core/VerseUiPorts.h"
#include "Core/VerseUiSubsystem.h"
#include "CoreMinimal.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "Policies/CondensedJsonPrintPolicy.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Settings/VerseUiSettings.h"

// Fakes of the UI's ports (work-packages 0.3: implement the interface exactly, no extra
// methods on the interface; the recorded frames are plain members of the fake).

/**
 * The bridge as the app backend answers it (bridge-protocol 3.2, 14): settings.set is
 * validated and written into the app config, the next welcome carries the stored settings.
 */
class FFakeVerseUiBridgePort : public IVerseUiBridgePort
{
public:
	struct FFrame
	{
		FString Type;
		TSharedPtr<FJsonObject> Data;
	};

	virtual void SendSettingsSet(const TSharedRef<FJsonObject>& Data) override
	{
		Frames.Add({TEXT("settings.set"), Data});
		AppConfig.ApplyJson(Data);
	}

	virtual void SendReturnToApp(const FString& Reason) override
	{
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("reason"), Reason);
		Frames.Add({TEXT("focus.return_to_app"), Data});
	}

	int32 Count(const FString& Type) const
	{
		int32 N = 0;
		for (const FFrame& F : Frames)
		{
			N += F.Type == Type;
		}
		return N;
	}

	const FFrame* Last(const FString& Type) const
	{
		for (int32 I = Frames.Num() - 1; I >= 0; --I)
		{
			if (Frames[I].Type == Type)
			{
				return &Frames[I];
			}
		}
		return nullptr;
	}

	/** welcome.data the backend would send on the next connect. */
	TSharedRef<FJsonObject> MakeWelcome(const FString& Lang = TEXT("en")) const
	{
		TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("protocol"), TEXT("verse.bridge/1"));
		TSharedRef<FJsonObject> Locale = MakeShared<FJsonObject>();
		Locale->SetStringField(TEXT("lang"), Lang);
		Locale->SetStringField(TEXT("fallback"), TEXT("en"));
		Locale->SetObjectField(TEXT("strings"), MakeShared<FJsonObject>());
		Data->SetObjectField(TEXT("locale"), Locale);
		Data->SetObjectField(TEXT("settings"), AppConfig.ToJson());
		TArray<TSharedPtr<FJsonValue>> Decks;
		for (const TCHAR* D : {TEXT("bridge"), TEXT("ops"), TEXT("engineering"), TEXT("hangar")})
		{
			Decks.Add(MakeShared<FJsonValueString>(D));
		}
		Data->SetArrayField(TEXT("decks"), Decks);
		return Data;
	}

	static FString ToString(const TSharedPtr<FJsonObject>& Object)
	{
		FString Out;
		const TSharedRef<TJsonWriter<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>> Writer = TJsonWriterFactory<TCHAR, TCondensedJsonPrintPolicy<TCHAR>>::Create(&Out);
		FJsonSerializer::Serialize(Object.ToSharedRef(), Writer);
		return Out;
	}

	TArray<FFrame> Frames;
	/** The app config the backend keeps (verse.* keys). */
	FVerseAppSettings AppConfig;
};

class FFakeVerseUiGamePort : public IVerseUiGamePort
{
public:
	virtual void StartDuel(FName Tier) override
	{
		Started.Add(Tier);
		bDuel = true;
	}
	virtual void LeaveDuel() override
	{
		++Left;
		bDuel = false;
	}
	virtual void TravelToDeck(FName Deck) override { CurrentDeck = Deck; }
	virtual bool IsDuelRunning() const override { return bDuel; }
	virtual FName GetCurrentDeck() const override { return CurrentDeck; }

	TArray<FName> Started;
	int32 Left = 0;
	bool bDuel = false;
	FName CurrentDeck = TEXT("hangar");
};

/** A HUD source with every value set by the test. */
class FFakeVerseHudSource : public IVerseHudSource
{
public:
	virtual int32 GetLocalPlayerId() const override { return LocalId; }
	virtual double GetServerTime() const override { return ServerTime; }
	virtual void GetPawnState(FVerseHudPawnState& Out) const override { Out = Pawn; }
	virtual bool GetView(FVerseHudView& Out) const override
	{
		Out = View;
		return bHasView;
	}
	virtual bool GetPredictedBoltDirection(FVector& OutDirection, float& OutSpreadHalfAngleDeg) const override
	{
		OutDirection = BoltDirection.IsNearlyZero() ? View.Rotation.Vector() : BoltDirection;
		OutSpreadHalfAngleDeg = SpreadDeg;
		return bHasView;
	}
	virtual FText GetDisplayName(int32 PlayerId) const override
	{
		const FString* Name = Names.Find(PlayerId);
		return Name ? FText::AsCultureInvariant(*Name) : FText::GetEmpty();
	}
	virtual bool IsBot(int32 PlayerId) const override { return Bots.Contains(PlayerId); }
	virtual FName GetBotTier(int32 PlayerId) const override { return Bots.Contains(PlayerId) ? Tier : NAME_None; }
	virtual float GetBotEffectiveSkill(int32 PlayerId) const override { return Bots.Contains(PlayerId) ? Skill : -1.f; }
	virtual void GetPawnPoses(TArray<FVersePawnPose>& Out) const override { Out = Poses; }

	int32 LocalId = 1;
	double ServerTime = 100.0;
	FVerseHudPawnState Pawn;
	FVerseHudView View;
	bool bHasView = true;
	FVector BoltDirection = FVector::ZeroVector;
	float SpreadDeg = 0.f;
	TMap<int32, FString> Names;
	TSet<int32> Bots;
	FName Tier = TEXT("adaptive");
	float Skill = 0.62f;
	TArray<FVersePawnPose> Poses;
};

/** A game world with the UI subsystem wired to the fakes, destroyed at scope end. */
struct FVerseUiTestWorld
{
	UWorld* World = nullptr;
	UVerseUiSubsystem* Ui = nullptr;
	TSharedPtr<FFakeVerseUiBridgePort> Bridge;
	TSharedPtr<FFakeVerseUiGamePort> Game;
	TSharedPtr<FFakeVerseHudSource> Source;
	double Now = 1000.0;

	explicit FVerseUiTestWorld(TSharedPtr<FFakeVerseUiBridgePort> InBridge = nullptr)
	{
		World = UWorld::CreateWorld(EWorldType::Game, false, TEXT("VerseUiTestWorld"));
		FWorldContext& Context = GEngine->CreateNewWorldContext(EWorldType::Game);
		Context.SetCurrentWorld(World);
		Ui = World->GetSubsystem<UVerseUiSubsystem>();
		Bridge = InBridge.IsValid() ? InBridge : MakeShared<FFakeVerseUiBridgePort>();
		Game = MakeShared<FFakeVerseUiGamePort>();
		Source = MakeShared<FFakeVerseHudSource>();
		if (Ui)
		{
			Ui->SetBridgePort(Bridge);
			Ui->SetGamePort(Game);
			Ui->SetHudSource(Source);
			Ui->Clock = [this] { return Now; };
		}
	}

	~FVerseUiTestWorld()
	{
		if (World)
		{
			GEngine->DestroyWorldContext(World);
			World->DestroyWorld(false);
		}
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

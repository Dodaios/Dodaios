#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "HAL/PlatformTime.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Stations/VerseCommandLink.h"

/**
 * Stands in for the WP17 bridge client for the station views (work-packages.md 0.3): records every command, answers
 * them when the test says so, counts focus.return_to_app, serves locale strings.
 */
class FFakeVerseStationLink final : public IVerseCommandLink
{
public:
	struct FSent
	{
		FString Type;
		FString Id;
		TSharedRef<FJsonObject> Data;
		double At = 0.0;
	};

	TArray<FSent> Sent;
	TMap<FString, FVerseReplyHandler> Pending;
	TArray<FString> Returns;
	TMap<FString, FString> Strings;
	/** Answer every command at once with this reply data (ok:true, result:{}) when set. */
	TSharedPtr<FJsonObject> AutoReply;

	virtual FString SendCommand(const FString& Type, const TSharedRef<FJsonObject>& Data, FVerseReplyHandler OnReply) override
	{
		const FString Id = FString::Printf(TEXT("c-%d"), ++Counter);
		Sent.Add({Type, Id, Data, FPlatformTime::Seconds()});
		if (AutoReply.IsValid())
		{
			OnReply(FVerseCommandReply::FromReplyData(*AutoReply));
		}
		else
		{
			Pending.Add(Id, MoveTemp(OnReply));
		}
		return Id;
	}

	virtual void ReturnToApp(const FString& Reason) override { Returns.Add(Reason); }

	virtual FString Localize(const FString& Key, const FString& Fallback) const override
	{
		const FString* Found = Strings.Find(Key);
		return Found ? *Found : Fallback;
	}

	/** Answers request Id with a reply `data` object; false when nothing waits for it. */
	bool Answer(const FString& Id, const FJsonObject& ReplyData)
	{
		FVerseReplyHandler Handler;
		if (!Pending.RemoveAndCopyValue(Id, Handler))
		{
			return false;
		}
		Handler(FVerseCommandReply::FromReplyData(ReplyData));
		return true;
	}

	bool AnswerLast(const FJsonObject& ReplyData) { return Sent.Num() > 0 && Answer(Sent.Last().Id, ReplyData); }

	int32 Count(const FString& Type) const
	{
		int32 N = 0;
		for (const FSent& S : Sent)
		{
			N += S.Type == Type ? 1 : 0;
		}
		return N;
	}

	const FSent* Last(const FString& Type) const
	{
		for (int32 I = Sent.Num() - 1; I >= 0; --I)
		{
			if (Sent[I].Type == Type)
			{
				return &Sent[I];
			}
		}
		return nullptr;
	}

	static TSharedPtr<FJsonObject> Ok(TSharedPtr<FJsonObject> Result = nullptr)
	{
		TSharedPtr<FJsonObject> D = MakeShared<FJsonObject>();
		D->SetBoolField(TEXT("ok"), true);
		D->SetObjectField(TEXT("result"), Result.IsValid() ? Result : MakeShared<FJsonObject>());
		return D;
	}

	static TSharedPtr<FJsonObject> Error(const FString& Code)
	{
		TSharedPtr<FJsonObject> E = MakeShared<FJsonObject>();
		E->SetStringField(TEXT("code"), Code);
		E->SetStringField(TEXT("message"), TEXT("test"));
		TSharedPtr<FJsonObject> D = MakeShared<FJsonObject>();
		D->SetBoolField(TEXT("ok"), false);
		D->SetObjectField(TEXT("error"), E);
		return D;
	}

private:
	int32 Counter = 0;
};

/** Golden bridge data of G0.11 (unreal/Verse/Tests/Data/bridge/). */
namespace VerseStationGolden
{
	inline TSharedPtr<FJsonValue> Load(const FString& Relative)
	{
		FString Text;
		const FString Path = FPaths::Combine(FPaths::ProjectDir(), TEXT("Tests/Data/bridge"), Relative);
		if (!FFileHelper::LoadFileToString(Text, *Path))
		{
			return nullptr;
		}
		TSharedPtr<FJsonValue> Root;
		const TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(Text);
		return FJsonSerializer::Deserialize(Reader, Root) ? Root : nullptr;
	}

	inline TArray<uint8> Hex(const FString& HexText)
	{
		TArray<uint8> Out;
		auto Nibble = [](TCHAR C) -> uint8
		{
			return C >= TEXT('0') && C <= TEXT('9') ? uint8(C - TEXT('0')) : C >= TEXT('a') && C <= TEXT('f') ? uint8(10 + C - TEXT('a')) : uint8(10 + C - TEXT('A'));
		};
		for (int32 I = 0; I + 1 < HexText.Len(); I += 2)
		{
			Out.Add(uint8((Nibble(HexText[I]) << 4) | Nibble(HexText[I + 1])));
		}
		return Out;
	}
}

#endif // WITH_DEV_AUTOMATION_TESTS

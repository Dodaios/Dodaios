#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"

/** One `reply` to a command (contracts/bridge-protocol.md 2). */
struct FVerseCommandReply
{
	bool bOk = false;
	/** `result` on success (may be empty). */
	TSharedPtr<FJsonObject> Result;
	/** `bad_request`, `not_found`, `conflict`, `busy`, `unavailable`, `rate_limited`, `internal`. */
	FString ErrorCode;
	/** English, for logs only; Verse shows its own text keyed by the code. */
	FString ErrorMessage;

	static FVerseCommandReply FromReplyData(const FJsonObject& Data)
	{
		FVerseCommandReply R;
		Data.TryGetBoolField(TEXT("ok"), R.bOk);
		const TSharedPtr<FJsonObject>* Obj = nullptr;
		if (R.bOk)
		{
			if (Data.TryGetObjectField(TEXT("result"), Obj) && Obj)
			{
				R.Result = *Obj;
			}
		}
		else if (Data.TryGetObjectField(TEXT("error"), Obj) && Obj)
		{
			(*Obj)->TryGetStringField(TEXT("code"), R.ErrorCode);
			(*Obj)->TryGetStringField(TEXT("message"), R.ErrorMessage);
		}
		return R;
	}
};

using FVerseReplyHandler = TFunction<void(const FVerseCommandReply&)>;

/**
 * What stations, desk monitors and station views need from the verse.bridge/1 client: send a
 * command and get its one reply, hand the foreground back to the app, read a localized string.
 * The bridge client of WP17 implements it; until then tests use their own fakes and the game runs
 * without a link (commands are not sent, nothing is shown that needs one).
 */
class IVerseCommandLink
{
public:
	virtual ~IVerseCommandLink() = default;

	/**
	 * Sends `{type, id, ts, data}`; returns the request id. OnReply runs exactly once, on the game
	 * thread, with the reply or with `unavailable` when the link drops before it.
	 */
	virtual FString SendCommand(const FString& Type, const TSharedRef<FJsonObject>& Data, FVerseReplyHandler OnReply) = 0;

	/**
	 * `focus.return_to_app {reason}` (section 12): Verse lets the app take the foreground and hides.
	 * Reason is `station` for station views and desk takeover.
	 */
	virtual void ReturnToApp(const FString& Reason) = 0;

	/** `welcome.locale.strings[Key]`, or Fallback when the app sent none. */
	virtual FString Localize(const FString& Key, const FString& Fallback) const = 0;
};

#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Duel/VerseDuelResultCodec.h"
#include "Duel/VerseDuelResultSink.h"
#include "HAL/PlatformTime.h"

namespace VerseDuel
{
	/**
	 * Stands in for the WP17 bridge client: records every duel.result and answers it as told.
	 * With bAnswerAtOnce the reply comes back inside SendDuelResult (a local server); otherwise
	 * the callbacks wait in Held until the test calls Answer (a slow one, or a dead one).
	 */
	class FFakeDuelResultSink final : public IDuelResultSink
	{
	public:
		struct FSent
		{
			TSharedPtr<FJsonObject> Data;
			double AtSeconds = 0.0;
		};

		bool bReady = true;
		bool bAnswerAtOnce = true;
		ESendResult Answer = ESendResult::Stored;
		TArray<FSent> Sent;
		TArray<TFunction<void(ESendResult)>> Held;

		virtual bool IsReady() const override { return bReady; }

		virtual void SendDuelResult(const TSharedRef<FJsonObject>& Data, TFunction<void(ESendResult)> OnDone) override
		{
			FSent Entry;
			Entry.Data = FromJsonString(ToJsonString(Data));  // a deep copy
			Entry.AtSeconds = FPlatformTime::Seconds();
			Sent.Add(MoveTemp(Entry));
			if (bAnswerAtOnce)
			{
				OnDone(Answer);
			}
			else
			{
				Held.Add(MoveTemp(OnDone));
			}
		}

		/** Answer every held send with Result. */
		void AnswerHeld(ESendResult Result)
		{
			TArray<TFunction<void(ESendResult)>> Calls = MoveTemp(Held);
			Held.Reset();
			for (TFunction<void(ESendResult)>& Call : Calls)
			{
				Call(Result);
			}
		}
	};
}

#endif // WITH_DEV_AUTOMATION_TESTS

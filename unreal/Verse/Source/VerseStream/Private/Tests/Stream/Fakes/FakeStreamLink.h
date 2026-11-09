#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Stream/VerseStreamDriver.h"

/** IVerseStreamLink that records every `panel.stream_state` it would send. */
class FFakeStreamLink final : public IVerseStreamLink
{
public:
	struct FSent
	{
		EVersePanelStreamState State;
		FString Error;
	};

	TArray<FSent> Sent;

	virtual void SendStreamState(EVersePanelStreamState State, const FString& Error) override
	{
		Sent.Add({ State, Error });
	}

	bool Last(EVersePanelStreamState State, const FString& Error = FString()) const
	{
		return Sent.Num() > 0 && Sent.Last().State == State && Sent.Last().Error == Error;
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

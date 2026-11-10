#pragma once

#if WITH_DEV_AUTOMATION_TESTS

#include "CoreMinimal.h"
#include "Stream/VerseStreamDriver.h"

/** IVerseStreamDriver that records calls; Start answers at once or when Complete() is called. */
class FFakeStreamDriver final : public IVerseStreamDriver
{
public:
	bool bAvailable = true;
	bool bAnswerAtOnce = true;
	bool bStartSucceeds = true;
	FString StartError = TEXT("encoder_unavailable");

	TArray<FVerseStreamConfig> Starts;
	TArray<FIntPoint> Resizes;
	int32 Stops = 0;
	bool bStreaming = false;
	FOnStarted Pending;

	virtual bool IsAvailable() const override { return bAvailable; }

	virtual void Start(const FVerseStreamConfig& Config, FOnStarted OnStarted) override
	{
		Starts.Add(Config);
		if (bAnswerAtOnce)
		{
			Answer(MoveTemp(OnStarted));
		}
		else
		{
			Pending = MoveTemp(OnStarted);
		}
	}

	void Complete()
	{
		if (Pending)
		{
			FOnStarted Callback = MoveTemp(Pending);
			Pending = nullptr;
			Answer(MoveTemp(Callback));
		}
	}

	virtual void Stop() override
	{
		++Stops;
		bStreaming = false;
	}

	virtual void Resize(FIntPoint RenderSize) override { Resizes.Add(RenderSize); }
	virtual bool IsStreaming() const override { return bStreaming; }

private:
	void Answer(FOnStarted Callback)
	{
		const bool bOk = bAvailable && bStartSucceeds;
		bStreaming = bOk;
		Callback(bOk, bOk ? FString() : StartError);
	}
};

#endif // WITH_DEV_AUTOMATION_TESTS

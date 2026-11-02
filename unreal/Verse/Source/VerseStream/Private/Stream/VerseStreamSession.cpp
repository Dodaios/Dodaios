#include "Stream/VerseStreamSession.h"

#include "HAL/PlatformTime.h"
#include "VerseLog.h"

FVerseStreamSession::FVerseStreamSession(TSharedRef<IVerseStreamDriver> InDriver, TSharedRef<IVerseStreamLink> InLink,
	FSignalUrlProvider InSignalUrl, FClock InClock)
	: Driver(MoveTemp(InDriver))
	, Link(MoveTemp(InLink))
	, SignalUrl(MoveTemp(InSignalUrl))
	, Clock(MoveTemp(InClock))
{
}

double FVerseStreamSession::Now() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

void FVerseStreamSession::OnPanelVisibility(bool bVisible, const FVersePanelGeometry& Geometry)
{
	const bool bWasVisible = Arbiter.IsPanelVisible();
	Arbiter.SetPanelVisible(bVisible, Geometry);
	if (Arbiter.IsPanelVisible() && !bWasVisible && State == EVersePanelStreamState::Failed)
	{
		// A panel shown again gets a fresh attempt after a failure.
		State = EVersePanelStreamState::Stopped;
	}
	Reconcile();
}

void FVerseStreamSession::OnPanelResize(const FVersePanelGeometry& Geometry)
{
	if (Arbiter.SetPanelGeometry(Geometry) && Driver->IsStreaming())
	{
		Driver->Resize(Arbiter.GetGeometry().RenderSize());
	}
}

void FVerseStreamSession::OnFullViewVisible(bool bVisible)
{
	Arbiter.SetFullViewVisible(bVisible);
	Reconcile();
}

void FVerseStreamSession::Reconcile()
{
	const bool bWants = Arbiter.WantsStream();
	if (bWants != bInPanelState)
	{
		bInPanelState = bWants;
		if (OnPanelStateChanged)
		{
			OnPanelStateChanged(bWants);
		}
	}
	const bool bActive = State == EVersePanelStreamState::Starting || State == EVersePanelStreamState::Streaming;
	if (bWants && State == EVersePanelStreamState::Stopped)
	{
		StartStream();
	}
	else if (!bWants && bActive)
	{
		StopStream(Arbiter.BlockReason());
	}
	else if (!bWants && State == EVersePanelStreamState::Stopped && !Arbiter.BlockReason().IsEmpty())
	{
		// Full view opened before the panel ever streamed: the panel still learns why.
		Report(EVersePanelStreamState::Stopped, Arbiter.BlockReason());
	}
}

void FVerseStreamSession::StartStream()
{
	FVerseStreamConfig Config;
	Config.SignalUrl = SignalUrl ? SignalUrl() : FString();
	Config.RenderSize = Arbiter.GetGeometry().RenderSize();
	++StartCount;
	const uint32 MyGeneration = ++Generation;
	Report(EVersePanelStreamState::Starting, FString());
	Driver->Start(Config, [this, MyGeneration](bool bStarted, const FString& Error) {
		if (MyGeneration != Generation)
		{
			// Hidden while starting: the late start is undone at once.
			if (bStarted)
			{
				Driver->Stop();
			}
			return;
		}
		if (bStarted)
		{
			Report(EVersePanelStreamState::Streaming, FString());
		}
		else
		{
			UE_LOG(LogVerseStream, Warning, TEXT("Panel stream failed: %s"), *Error);
			Report(EVersePanelStreamState::Failed, Error.IsEmpty() ? FString(TEXT("internal")) : Error);
		}
	});
}

void FVerseStreamSession::StopStream(const FString& Reason)
{
	const double Started = Now();
	++Generation;
	++StopCount;
	Driver->Stop();
	LastStopLatency = Now() - Started;
	Report(EVersePanelStreamState::Stopped, Reason);
}

void FVerseStreamSession::Report(EVersePanelStreamState NewState, const FString& Error)
{
	if (bReported && NewState == State && Error == LastError)
	{
		return;
	}
	State = NewState;
	LastError = Error;
	bReported = true;
	Link->SendStreamState(NewState, Error);
}

FString VerseStream::SanitizeErrorCode(const FString& Error)
{
	FString Out;
	for (const TCHAR C : Error)
	{
		if (Out.Len() >= 64)
		{
			break;
		}
		const TCHAR L = FChar::ToLower(C);
		if ((L >= TEXT('a') && L <= TEXT('z')) || (L >= TEXT('0') && L <= TEXT('9')) || L == TEXT('_'))
		{
			Out.AppendChar(L);
		}
	}
	return Out;
}

FString VerseStream::StreamStateJson(EVersePanelStreamState State, const FString& Error)
{
	const FString Code = SanitizeErrorCode(Error);
	if (Code.IsEmpty())
	{
		return FString::Printf(TEXT("{\"state\":\"%s\"}"), StateName(State));
	}
	return FString::Printf(TEXT("{\"state\":\"%s\",\"error\":\"%s\"}"), StateName(State), *Code);
}

#include "Stream/VerseStreamArbiter.h"

const TCHAR* VerseStream::StateName(EVersePanelStreamState State)
{
	switch (State)
	{
	case EVersePanelStreamState::Starting:
		return TEXT("starting");
	case EVersePanelStreamState::Streaming:
		return TEXT("streaming");
	case EVersePanelStreamState::Failed:
		return TEXT("failed");
	case EVersePanelStreamState::Stopped:
	default:
		return TEXT("stopped");
	}
}

bool FVersePanelGeometry::IsValid() const
{
	return W > 0 && H > 0 && W <= 8192 && H <= 8192 && Dpr > 0.0f && Dpr <= 8.0f;
}

FIntPoint FVersePanelGeometry::RenderSize() const
{
	if (!IsValid())
	{
		return FIntPoint::ZeroValue;
	}
	double RW = double(W) * Dpr;
	double RH = double(H) * Dpr;
	const double Scale = FMath::Min3(1.0, double(VerseStream::MaxRenderW) / RW, double(VerseStream::MaxRenderH) / RH);
	RW *= Scale;
	RH *= Scale;
	// Hardware encoders want even sides.
	const int32 OutW = FMath::Max(VerseStream::MinRenderW, int32(FMath::FloorToDouble(RW / 2.0 + 1e-6)) * 2);
	const int32 OutH = FMath::Max(VerseStream::MinRenderH, int32(FMath::FloorToDouble(RH / 2.0 + 1e-6)) * 2);
	return FIntPoint(OutW, OutH);
}

void FVerseStreamArbiter::SetPanelVisible(bool bVisible, const FVersePanelGeometry& InGeometry)
{
	bPanelVisible = bVisible && InGeometry.IsValid();
	Geometry = bPanelVisible ? InGeometry : FVersePanelGeometry();
}

bool FVerseStreamArbiter::SetPanelGeometry(const FVersePanelGeometry& InGeometry)
{
	if (!bPanelVisible || !InGeometry.IsValid() || InGeometry == Geometry)
	{
		return false;
	}
	Geometry = InGeometry;
	return true;
}

void FVerseStreamArbiter::SetFullViewVisible(bool bVisible)
{
	bFullViewVisible = bVisible;
}

bool FVerseStreamArbiter::WantsStream() const
{
	return bPanelVisible && !bFullViewVisible && Geometry.IsValid();
}

FString FVerseStreamArbiter::BlockReason() const
{
	if (bPanelVisible && bFullViewVisible)
	{
		return VerseStream::ErrorFullViewOpen;
	}
	return FString();
}

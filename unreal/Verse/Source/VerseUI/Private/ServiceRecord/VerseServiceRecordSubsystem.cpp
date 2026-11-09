#include "ServiceRecord/VerseServiceRecordSubsystem.h"
#include "Dom/JsonObject.h"

#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "HAL/IConsoleManager.h"
#include "ServiceRecord/SVerseServiceRecord.h"
#include "VerseLog.h"
#include "Widgets/Layout/SBox.h"

namespace
{
	constexpr int32 RecordZOrder = 40;
	constexpr int32 NoticeZOrder = 45;

	FAutoConsoleCommandWithWorld ToggleCommand(
		TEXT("Verse.UI.ServiceRecord"),
		TEXT("Open or close the service record (commander rank, level, XP and duel record)."),
		FConsoleCommandWithWorldDelegate::CreateLambda([](UWorld* World)
		{
			UGameInstance* Instance = World ? World->GetGameInstance() : nullptr;
			if (UVerseServiceRecordSubsystem* Record = Instance ? Instance->GetSubsystem<UVerseServiceRecordSubsystem>() : nullptr)
			{
				Record->ToggleRecord();
			}
		}));
}

// ------------------------------------------------------------------ presenter

FVersePromotionPresenter::FVersePromotionPresenter(TSharedRef<FVerseServiceRecordModel> InModel,
	TFunction<bool(const FVersePromotion&)> InShow, TFunction<void()> InHide)
	: Model(InModel)
	, Show(MoveTemp(InShow))
	, Hide(MoveTemp(InHide))
{
}

void FVersePromotionPresenter::Tick(float DeltaSeconds)
{
	const FVersePromotion* Next = Model->PendingPromotion();
	if (bShowing)
	{
		// Told elsewhere while on screen (the web app showed it): take it down without telling.
		if (!Next || Next->Seq != ShowingSeq)
		{
			Hide();
			bShowing = false;
			return;
		}
		Elapsed += DeltaSeconds;
		if (Elapsed >= NoticeSeconds)
		{
			Hide();
			bShowing = false;
			Model->MarkPromotionShown();
		}
		return;
	}
	if (Next && Show(*Next))
	{
		bShowing = true;
		ShowingSeq = Next->Seq;
		Elapsed = 0.f;
	}
}

// ------------------------------------------------------------------ subsystem

void UVerseServiceRecordSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Model = MakeShared<FVerseServiceRecordModel>();
	TWeakObjectPtr<UVerseServiceRecordSubsystem> Weak(this);
	Presenter = MakeUnique<FVersePromotionPresenter>(Model.ToSharedRef(),
		[Weak](const FVersePromotion& Promotion) { return Weak.IsValid() && Weak->ShowNotice(Promotion); },
		[Weak]() { if (Weak.IsValid()) { Weak->HideNotice(); } });
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &UVerseServiceRecordSubsystem::Tick), 0.1f);
}

void UVerseServiceRecordSubsystem::Deinitialize()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	CloseRecord();
	HideNotice();
	Presenter.Reset();
	Super::Deinitialize();
}

bool UVerseServiceRecordSubsystem::HandleBridgeMessage(const FString& Type, const FJsonObject& Data)
{
	if (Type == TEXT("progression.snapshot"))
	{
		return Model->ApplySnapshot(Data);
	}
	if (Type == TEXT("progression.awarded"))
	{
		Model->ApplyAwarded(Data);
		return true;
	}
	return false;
}

void UVerseServiceRecordSubsystem::SetToldSender(TFunction<void(int64 Seq)> Sender)
{
	Model->SendTold = MoveTemp(Sender);
}

bool UVerseServiceRecordSubsystem::Tick(float DeltaSeconds)
{
	if (Presenter)
	{
		Presenter->Tick(DeltaSeconds);
	}
	return true;
}

void UVerseServiceRecordSubsystem::OpenRecord(EVerseRecordTab Tab)
{
	RecordTab = Tab;
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (RecordWidget.IsValid() || !Viewport)
	{
		return;
	}
	RecordWidget = SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Center)
		[
			SNew(SVerseServiceRecord, Model.ToSharedRef())
		];
	Viewport->AddViewportWidgetContent(RecordWidget.ToSharedRef(), RecordZOrder);
}

void UVerseServiceRecordSubsystem::CloseRecord()
{
	if (!RecordWidget.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
	{
		Viewport->RemoveViewportWidgetContent(RecordWidget.ToSharedRef());
	}
	RecordWidget.Reset();
}

void UVerseServiceRecordSubsystem::ToggleRecord()
{
	IsRecordOpen() ? CloseRecord() : OpenRecord();
}

bool UVerseServiceRecordSubsystem::ShowNotice(const FVersePromotion& Promotion)
{
	UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr;
	if (!Viewport)
	{
		return false;  // no screen: the promotion waits, and nothing is told
	}
	HideNotice();
	NoticeWidget = SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Top)
		.Padding(FMargin(0.f, 72.f, 0.f, 0.f))
		[
			SNew(SVersePromotionNotice, Promotion)
		];
	Viewport->AddViewportWidgetContent(NoticeWidget.ToSharedRef(), NoticeZOrder);
	UE_LOG(LogVerseUI, Log, TEXT("service record: promotion %lld to level %d on screen"), Promotion.Seq, Promotion.Level);
	return true;
}

void UVerseServiceRecordSubsystem::HideNotice()
{
	if (!NoticeWidget.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = GetGameInstance() ? GetGameInstance()->GetGameViewportClient() : nullptr)
	{
		Viewport->RemoveViewportWidgetContent(NoticeWidget.ToSharedRef());
	}
	NoticeWidget.Reset();
}

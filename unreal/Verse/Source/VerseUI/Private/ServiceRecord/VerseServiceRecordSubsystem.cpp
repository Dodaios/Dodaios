#include "ServiceRecord/VerseServiceRecordSubsystem.h"
#include "Dom/JsonObject.h"

#include "Core/VerseUiStrings.h"
#include "Engine/Engine.h"
#include "Engine/GameInstance.h"
#include "Engine/GameViewportClient.h"
#include "Framework/Application/SlateApplication.h"
#include "HAL/IConsoleManager.h"
#include "Misc/ConfigCacheIni.h"
#include "ServiceRecord/SVerseServiceRecord.h"
#include "ServiceRecord/VerseRecordPages.h"
#include "VerseLog.h"
#include "Widgets/Layout/SBox.h"

namespace
{
	constexpr int32 RecordZOrder = 40;
	constexpr int32 NoticeZOrder = 45;
	constexpr int32 QuietZOrder = 44;
	const TCHAR* ConfigSection = TEXT("Verse.ServiceRecord");

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

	UGameViewportClient* ViewportOf(const UGameInstance* Instance)
	{
		return Instance && FSlateApplication::IsInitialized() ? Instance->GetGameViewportClient() : nullptr;
	}
}

// ------------------------------------------------------------------ presenter

FVersePromotionPresenter::FVersePromotionPresenter(TSharedRef<FVerseServiceRecordModel> InModel,
	TFunction<bool(const FVersePromotion&)> InShow, TFunction<void()> InHide, TFunction<bool()> InIsOn)
	: Model(InModel)
	, Show(MoveTemp(InShow))
	, Hide(MoveTemp(InHide))
	, IsOn(MoveTemp(InIsOn))
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
		// Acknowledged, Escape or a click: it counts as shown now. Otherwise its time.
		const bool bClosedByPerson = IsOn && !IsOn();
		if (bClosedByPerson || Elapsed >= Duration)
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
		Duration = SecondsFor(*Next);
	}
}

// ------------------------------------------------------------------ subsystem

void UVerseServiceRecordSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	Model = MakeShared<FVerseServiceRecordModel>();

	// The uniform the commander wears and the bell are kept in the user settings file.
	Model->SaveUniformChoice = [](FName Choice)
	{
		if (GConfig)
		{
			GConfig->SetString(ConfigSection, TEXT("Uniform"), *Choice.ToString(), GGameUserSettingsIni);
			GConfig->Flush(false, GGameUserSettingsIni);
		}
	};
	Model->SaveBell = [](bool bOn)
	{
		if (GConfig)
		{
			GConfig->SetBool(ConfigSection, TEXT("Bell"), bOn, GGameUserSettingsIni);
			GConfig->Flush(false, GGameUserSettingsIni);
		}
	};
	if (GConfig)
	{
		FString Uniform;
		if (GConfig->GetString(ConfigSection, TEXT("Uniform"), Uniform, GGameUserSettingsIni))
		{
			Model->RestoreUniformChoice(FName(*Uniform));
		}
		bool bBell = true;
		if (GConfig->GetBool(ConfigSection, TEXT("Bell"), bBell, GGameUserSettingsIni))
		{
			Model->SetBellOn(bBell);
		}
	}
	// SetBellOn above wrote the value back once; harmless.

	TWeakObjectPtr<UVerseServiceRecordSubsystem> Weak(this);
	Presenter = MakeUnique<FVersePromotionPresenter>(Model.ToSharedRef(),
		[Weak](const FVersePromotion& Promotion) { return Weak.IsValid() && Weak->ShowNotice(Promotion); },
		[Weak]() { if (Weak.IsValid()) { Weak->HideNotice(); } },
		[Weak]() { return !Weak.IsValid() || Weak->IsPresentationOn(); });
	TickHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(this, &UVerseServiceRecordSubsystem::Tick), 0.05f);
}

void UVerseServiceRecordSubsystem::Deinitialize()
{
	FTSTicker::GetCoreTicker().RemoveTicker(TickHandle);
	CloseRecord();
	HideNotice();
	if (UGameViewportClient* Viewport = ViewportOf(GetGameInstance()))
	{
		if (QuietHolder.IsValid())
		{
			Viewport->RemoveViewportWidgetContent(QuietHolder.ToSharedRef());
		}
	}
	QuietHolder.Reset();
	QuietWidget.Reset();
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

void UVerseServiceRecordSubsystem::SetStringsProvider(TFunction<const FVerseUiStrings*()> Provider)
{
	StringsProvider = MoveTemp(Provider);
}

const FVerseUiStrings& UVerseServiceRecordSubsystem::Strings() const
{
	static const FVerseUiStrings Fallback = []
	{
		FVerseUiStrings Loaded;
		Loaded.LoadCatalogue(FVerseUiStrings::DefaultCatalogueDir());
		return Loaded;
	}();
	const FVerseUiStrings* Provided = StringsProvider ? StringsProvider() : nullptr;
	return Provided ? *Provided : Fallback;
}

FVerseStringsGetter UVerseServiceRecordSubsystem::StringsGetter() const
{
	TWeakObjectPtr<const UVerseServiceRecordSubsystem> Weak(this);
	return [Weak]() -> const FVerseUiStrings& { return Weak->Strings(); };
}

void UVerseServiceRecordSubsystem::SetOverlayVisible(TFunction<bool()> Visible)
{
	OverlayVisible = MoveTemp(Visible);
}

double UVerseServiceRecordSubsystem::Now() const
{
	return Clock ? Clock() : FPlatformTime::Seconds();
}

bool UVerseServiceRecordSubsystem::Tick(float DeltaSeconds)
{
	if (!bTickingByHand)
	{
		TickNotices(DeltaSeconds);
	}
	return true;
}

void UVerseServiceRecordSubsystem::TickNotices(float DeltaSeconds)
{
	if (Presenter)
	{
		Presenter->Tick(DeltaSeconds);
	}
	// Officers' level-ups and the drone's rank-less ones come as quiet lines while the Verse is on screen.
	if (IsOverlayVisible() && ViewportOf(GetGameInstance()))
	{
		FVerseQuietLine Line;
		while (Model->QuietLines().Num() > 0 && Model->PopQuietLine(Line))
		{
			const FString* Name = Model->GetCrewNames().Find(Line.SubjectId.Mid(Line.SubjectId.Find(TEXT(":")) + 1));
			FString Who = Line.Kind == EVerseSubjectKind::Pet
				? (Model->GetCompanionName().IsEmpty() ? Strings().Get(TEXT("verse.ranks.kind.pet")).ToString() : Model->GetCompanionName())
				: (Name ? *Name : Line.SubjectId.Mid(Line.SubjectId.Find(TEXT(":")) + 1));
			Quiet.Add(Line.Seq, QuietText(Line.RankId, Line.Level, Line.bPromoted, Who), Line.RankId, Now());
		}
	}
	Quiet.Tick(Now());
	LayoutQuietLines();
}

bool UVerseServiceRecordSubsystem::IsPresentationOn() const
{
	// A quiet line is on while it is in the stack (a click or its five seconds end it); the full notice until acknowledged.
	return QuietPromotionSeq != 0 ? Quiet.Contains(QuietPromotionSeq) : !bNoticeAcknowledged;
}

FText UVerseServiceRecordSubsystem::QuietText(FName RankId, int32 Level, bool bPromoted, const FString& Who) const
{
	const FVerseUiStrings& S = Strings();
	if (bPromoted)
	{
		return FVerseRecordPages::Fill(S, TEXT("verse.ranks.promo.toast_promoted"), {{TEXT("who"), Who}, {TEXT("rank"), FVerseRecordPages::RankName(S, RankId).ToString()}});
	}
	return FVerseRecordPages::Fill(S, TEXT("verse.ranks.promo.toast_level"), {{TEXT("who"), Who}, {TEXT("level"), FString::FromInt(Level)}});
}

void UVerseServiceRecordSubsystem::LayoutQuietLines()
{
	UGameViewportClient* Viewport = ViewportOf(GetGameInstance());
	if (!Viewport)
	{
		return;
	}
	if (Quiet.Entries().Num() == 0)
	{
		if (QuietHolder.IsValid())
		{
			Viewport->RemoveViewportWidgetContent(QuietHolder.ToSharedRef());
			QuietHolder.Reset();
			QuietWidget.Reset();
			QuietLaidOut = 0;
		}
		return;
	}
	if (!QuietHolder.IsValid())
	{
		SAssignNew(QuietWidget, SVerseQuietLines)
			.OnDismiss_Lambda([this](int64 Id) { Quiet.Dismiss(Id); });
		QuietHolder = SNew(SBox).HAlign(HAlign_Right).VAlign(VAlign_Bottom).Padding(FMargin(0.f, 0.f, 24.f, 24.f))[QuietWidget.ToSharedRef()];
		Viewport->AddViewportWidgetContent(QuietHolder.ToSharedRef(), QuietZOrder);
		QuietLaidOut = 0;
	}
	if (QuietLaidOut != Quiet.Revision() + 1)
	{
		QuietLaidOut = Quiet.Revision() + 1;
		QuietWidget->Show(Quiet.Entries());
	}
}

void UVerseServiceRecordSubsystem::OpenRecord(EVerseRecordTab Tab)
{
	RecordTab = Tab;
	UGameViewportClient* Viewport = ViewportOf(GetGameInstance());
	if (RecordWidget.IsValid())
	{
		StaticCastSharedPtr<SVerseServiceRecord>(RecordWidget)->SetTab(Tab);
		return;
	}
	if (!Viewport)
	{
		return;
	}
	TWeakObjectPtr<UVerseServiceRecordSubsystem> Weak(this);
	RecordWidget = SNew(SVerseServiceRecord, Model.ToSharedRef(), StringsGetter(), Tab)
		.OnClose_Lambda([Weak]() { if (Weak.IsValid()) { Weak->CloseRecord(); } });
	Viewport->AddViewportWidgetContent(RecordWidget.ToSharedRef(), RecordZOrder);
}

void UVerseServiceRecordSubsystem::CloseRecord()
{
	if (!RecordWidget.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = ViewportOf(GetGameInstance()))
	{
		Viewport->RemoveViewportWidgetContent(RecordWidget.ToSharedRef());
	}
	RecordWidget.Reset();
}

void UVerseServiceRecordSubsystem::ToggleRecord()
{
	IsRecordOpen() ? CloseRecord() : OpenRecord();
}

bool UVerseServiceRecordSubsystem::DismissNotice()
{
	if (!NoticeWidget.IsValid())
	{
		return false;
	}
	bNoticeAcknowledged = true;
	return true;
}

bool UVerseServiceRecordSubsystem::ShowNotice(const FVersePromotion& Promotion)
{
	UGameViewportClient* Viewport = ViewportOf(GetGameInstance());
	if (!Viewport || !IsOverlayVisible())
	{
		return false;  // no screen, or the Verse is not on it: the promotion waits, and nothing is told
	}
	HideNotice();
	bNoticeAcknowledged = false;
	QuietPromotionSeq = 0;
	if (!Promotion.IsFullNotice())
	{
		// A level without a new rank: a quiet line in the corner, five seconds or a click.
		const FString Who = Strings().Get(TEXT("verse.ranks.promo.you")).ToString();
		Quiet.Add(Promotion.Seq, QuietText(Promotion.RankId, Promotion.Level, false, Who), Promotion.RankId, Now());
		QuietPromotionSeq = Promotion.Seq;
		UE_LOG(LogVerseUI, Log, TEXT("service record: level %d as a quiet line"), Promotion.Level);
		return true;
	}
	TWeakObjectPtr<UVerseServiceRecordSubsystem> Weak(this);
	NoticeWidget = SNew(SBox)
		.HAlign(HAlign_Center)
		.VAlign(VAlign_Top)
		.Padding(FMargin(0.f, 72.f, 0.f, 0.f))
		[
			SNew(SVersePromotionNotice, Promotion, StringsGetter())
			.OnAcknowledge_Lambda([Weak]() { if (Weak.IsValid()) { Weak->DismissNotice(); } })
		];
	Viewport->AddViewportWidgetContent(NoticeWidget.ToSharedRef(), NoticeZOrder);
	UE_LOG(LogVerseUI, Log, TEXT("service record: promotion %lld to level %d on screen"), Promotion.Seq, Promotion.Level);
	return true;
}

void UVerseServiceRecordSubsystem::HideNotice()
{
	if (QuietPromotionSeq != 0)
	{
		Quiet.Dismiss(QuietPromotionSeq);
		QuietPromotionSeq = 0;
	}
	if (!NoticeWidget.IsValid())
	{
		return;
	}
	if (UGameViewportClient* Viewport = ViewportOf(GetGameInstance()))
	{
		Viewport->RemoveViewportWidgetContent(NoticeWidget.ToSharedRef());
	}
	NoticeWidget.Reset();
}

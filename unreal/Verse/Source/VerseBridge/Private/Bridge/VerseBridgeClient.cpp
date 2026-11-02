#include "Bridge/VerseBridgeClient.h"

#include "Bridge/VerseCellsCodec.h"
#include "HAL/PlatformMisc.h"
#include "HAL/PlatformProcess.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "VerseLog.h"

using namespace VerseBridgeJson;

namespace
{
	TSharedPtr<FJsonObject> StringArrayField(const TCHAR* Field, const TArray<FString>& Values)
	{
		TArray<TSharedPtr<FJsonValue>> A;
		for (const FString& V : Values)
		{
			A.Add(MakeShared<FJsonValueString>(V));
		}
		TSharedPtr<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetArrayField(Field, A);
		return O;
	}

	/** The backend's DATA_DIR sits next to the checkout (dodaios/core/instance.py); the
	 *  Unreal project is <checkout>/unreal/Verse, so the dev file is two levels up. */
	FString DevDiscoveryPath()
	{
		const FString DataDir = FPlatformMisc::GetEnvironmentVariable(TEXT("JARVIS_DATA_DIR"));
		if (!DataDir.IsEmpty())
		{
			return FPaths::Combine(DataDir, TEXT("verse"), TEXT("bridge.json"));
		}
		return FPaths::ConvertRelativePathToFull(FPaths::Combine(FPaths::ProjectDir(), TEXT(".."), TEXT(".."), TEXT("data"), TEXT("verse"), TEXT("bridge.json")));
	}
}

double FVerseBridgeClient::BackoffFor(int32 Attempt)
{
	static const double Steps[] = {0.25, 1.0, 2.0, 4.0};
	return Attempt < 1 ? 0.0 : Attempt <= 4 ? Steps[Attempt - 1] : 5.0;
}

bool FVerseBridgeClient::Discover(FDiscovery& Out, const FString& DevFileOverride)
{
	Out.Url = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_BRIDGE"));
	Out.Token = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_TOKEN"));
	if (!Out.Url.IsEmpty() && !Out.Token.IsEmpty())
	{
		return true;
	}
#if !UE_BUILD_SHIPPING
	// Editor or standalone run without a supervisor (contract 1, Dev discovery).
	FString Explicit = FPlatformMisc::GetEnvironmentVariable(TEXT("DODAIOS_VERSE_DISCOVERY"));
	const FString Path = !DevFileOverride.IsEmpty() ? DevFileOverride : !Explicit.IsEmpty() ? Explicit : DevDiscoveryPath();
	FString Text;
	if (FFileHelper::LoadFileToString(Text, *Path))
	{
		const TSharedPtr<FJsonObject> O = Read(Text);
		Out.Url = Str(O, TEXT("url"));
		Out.Token = Str(O, TEXT("token"));
		return !Out.Url.IsEmpty() && !Out.Token.IsEmpty();
	}
#endif
	return false;
}

FVerseBridgeClient::FVerseBridgeClient() = default;

FVerseBridgeClient::~FVerseBridgeClient()
{
	Stop();
}

void FVerseBridgeClient::Start(const FDiscovery& Discovery)
{
	Target = Discovery;
	Attempts = 0;
	State = EState::Waiting;
	NextAttemptAt = 0.0;
}

void FVerseBridgeClient::Stop()
{
	Socket.Close(1000);
	FailPending(TEXT("internal"));
	State = EState::Idle;
}

void FVerseBridgeClient::Connect(double Now)
{
	State = EState::Connecting;
	LastFrameAt = Now;
	if (!Socket.Connect(Target.Url))
	{
		State = EState::Idle;
		UE_LOG(LogVerseBridge, Error, TEXT("bridge: no usable bridge URL"));
	}
}

void FVerseBridgeClient::Tick(double Now)
{
	if (State == EState::Waiting && Now >= NextAttemptAt)
	{
		Connect(Now);
	}
	FVerseWsClient::FEvent E;
	while (Socket.Poll(E))
	{
		switch (E.Kind)
		{
		case FVerseWsClient::FEvent::EKind::Connected:
		{
			State = EState::Handshaking;
			LastFrameAt = Now;
			TSharedPtr<FJsonObject> Hello = MakeShared<FJsonObject>();
			Hello->SetStringField(TEXT("token"), Target.Token);
			Hello->SetArrayField(TEXT("protocols"), {MakeShared<FJsonValueString>(VerseBridge::Protocol)});
			TSharedPtr<FJsonObject> Build = MakeShared<FJsonObject>();
			Build->SetStringField(TEXT("version"), BuildVersion);
			Build->SetStringField(TEXT("changelist"), BuildChangelist.IsEmpty() ? TEXT("dev") : BuildChangelist);
#if UE_BUILD_SHIPPING
			Build->SetStringField(TEXT("config"), TEXT("Shipping"));
#elif UE_BUILD_DEVELOPMENT
			Build->SetStringField(TEXT("config"), TEXT("Development"));
#else
			Build->SetStringField(TEXT("config"), TEXT("Debug"));
#endif
			Build->SetStringField(TEXT("platform"), PLATFORM_WINDOWS ? TEXT("Win64") : TEXT("Linux"));
			Hello->SetObjectField(TEXT("build"), Build);
			Hello->SetNumberField(TEXT("pid"), double(FPlatformProcess::GetCurrentProcessId()));
			Hello->SetNumberField(TEXT("last_seq"), double(LastSeq));
			TSharedPtr<FJsonObject> Enc = MakeShared<FJsonObject>();
			TArray<TSharedPtr<FJsonValue>> Screens;
			if (!bPreferJsonScreens)
			{
				Screens.Add(MakeShared<FJsonValueString>(TEXT("cells.bin/1")));
			}
			Screens.Add(MakeShared<FJsonValueString>(TEXT("cells.json/1")));
			Enc->SetArrayField(TEXT("screens"), Screens);
			Hello->SetObjectField(TEXT("encodings"), Enc);
			TSharedPtr<FJsonObject> Caps = MakeShared<FJsonObject>();
			Caps->SetBoolField(TEXT("panel_stream"), true);
			Caps->SetBoolField(TEXT("duel"), true);
			Hello->SetObjectField(TEXT("capabilities"), Caps);
			SendNotice(TEXT("hello"), Hello);
			break;
		}
		case FVerseWsClient::FEvent::EKind::Text:
			HandleText(E.Text, Now);
			break;
		case FVerseWsClient::FEvent::EKind::Binary:
			HandleBinary(E.Bytes, Now);
			break;
		case FVerseWsClient::FEvent::EKind::Closed:
			HandleClosed(E.CloseCode, Now);
			break;
		}
	}
	if (State == EState::Linked)
	{
		if (Now - LastPingAt >= PingInterval)
		{
			LastPingAt = Now;
			SendNotice(TEXT("ping"), MakeShared<FJsonObject>());
		}
		if (Now - LastFrameAt >= DeadLink)
		{
			UE_LOG(LogVerseBridge, Warning, TEXT("bridge: no frame for %.1f s, reconnecting"), Now - LastFrameAt);
			Socket.Close(1001);
			Unlink(1006, Now);
		}
	}
	else if ((State == EState::Connecting || State == EState::Handshaking) && Now - LastFrameAt >= DeadLink)
	{
		Socket.Close(1001);
		Unlink(1006, Now);
	}
}

void FVerseBridgeClient::Unlink(int32 Code, double Now)
{
	const bool bWasLinked = State == EState::Linked;
	FailPending(TEXT("internal"));
	LastSeqOf.Reset();
	ResyncInFlight.Reset();
	Screens.Reset();
	if (Code == int32(VerseBridge::ECloseCode::Token) && bEverLinked)
	{
		State = EState::LaunchOver;
		UE_LOG(LogVerseBridge, Log, TEXT("bridge: token refused on reconnect, the launch is over"));
		OnLaunchOver.Broadcast();
		return;
	}
	if (Code == int32(VerseBridge::ECloseCode::Replaced))
	{
		// Another Verse took the link; this one must not fight for it.
		State = EState::Idle;
		OnUnlinked.Broadcast(Code);
		return;
	}
	++Attempts;
	State = EState::Waiting;
	NextAttemptAt = Now + BackoffFor(Attempts);
	if (bWasLinked)
	{
		OnUnlinked.Broadcast(Code);
	}
}

void FVerseBridgeClient::HandleClosed(int32 Code, double Now)
{
	UE_LOG(LogVerseBridge, Log, TEXT("bridge: closed with %d"), Code);
	Socket.Close(Code);
	Unlink(Code, Now);
}

void FVerseBridgeClient::SendFrame(const FVerseBridgeFrame& Frame)
{
	Socket.SendText(Frame.Encode());
}

FString FVerseBridgeClient::SendCommand(const FString& Type, TSharedPtr<FJsonObject> Data, FReply OnReply)
{
	const FString Id = FString::Printf(TEXT("c-%d"), NextId++);
	if (State != EState::Linked)
	{
		if (OnReply)
		{
			OnReply(false, nullptr, TEXT("unavailable"));
		}
		return Id;
	}
	Pending.Add(Id, MoveTemp(OnReply));
	SendFrame(FVerseBridgeFrame::Make(Type, Data, Id));
	return Id;
}

void FVerseBridgeClient::SendNotice(const FString& Type, TSharedPtr<FJsonObject> Data)
{
	SendFrame(FVerseBridgeFrame::Make(Type, Data));
}

void FVerseBridgeClient::Reply(const FString& Re, bool bOk, TSharedPtr<FJsonObject> Result, const FString& ErrorCode, const FString& Message)
{
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetBoolField(TEXT("ok"), bOk);
	if (bOk)
	{
		Data->SetObjectField(TEXT("result"), Result.IsValid() ? Result : MakeShared<FJsonObject>());
	}
	else
	{
		TSharedPtr<FJsonObject> Err = MakeShared<FJsonObject>();
		Err->SetStringField(TEXT("code"), ErrorCode.IsEmpty() ? TEXT("internal") : ErrorCode);
		Err->SetStringField(TEXT("message"), Message);
		Data->SetObjectField(TEXT("error"), Err);
	}
	FVerseBridgeFrame F = FVerseBridgeFrame::Make(TEXT("reply"), Data);
	F.Re = Re;
	SendFrame(F);
}

void FVerseBridgeClient::FailPending(const FString& Code)
{
	TMap<FString, FReply> Failed = MoveTemp(Pending);
	Pending.Reset();
	for (TPair<FString, FReply>& P : Failed)
	{
		if (P.Value)
		{
			P.Value(false, nullptr, Code);
		}
	}
}

void FVerseBridgeClient::Subscribe(const TArray<FString>& InTopics)
{
	for (const FString& T : InTopics)
	{
		Topics.AddUnique(T);
	}
	if (IsLinked())
	{
		SendCommand(TEXT("subscribe"), StringArrayField(TEXT("topics"), InTopics));
	}
}

void FVerseBridgeClient::WatchScreens(const TArray<TPair<FString, int32>>& PanesNearestFirst)
{
	ScreenWatch = PanesNearestFirst;
	if (!IsLinked())
	{
		return;
	}
	TArray<TSharedPtr<FJsonValue>> List;
	for (const TPair<FString, int32>& P : ScreenWatch)
	{
		TSharedPtr<FJsonObject> O = MakeShared<FJsonObject>();
		O->SetStringField(TEXT("pane_id"), P.Key);
		O->SetNumberField(TEXT("hz"), FMath::Clamp(P.Value, 1, 10));
		List.Add(MakeShared<FJsonValueObject>(O));
	}
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetArrayField(TEXT("panes"), List);
	SendCommand(TEXT("screens.watch"), Data, [this](bool bOk, const TSharedPtr<FJsonObject>& Result, const FString&)
	{
		if (bOk)
		{
			Screens.Bind(Result);
		}
	});
}

void FVerseBridgeClient::WatchChatTails(const TArray<FString>& AgentIds)
{
	ChatWatch = AgentIds;
	if (IsLinked())
	{
		SendCommand(TEXT("chat_tails.watch"), StringArrayField(TEXT("agents"), AgentIds));
	}
}

void FVerseBridgeClient::Resync(const FString& Topic, const FString& PaneId)
{
	const FString Slot = PaneId.IsEmpty() ? Topic : PaneId;
	if (ResyncInFlight.Contains(Slot))
	{
		return;
	}
	TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
	Data->SetStringField(TEXT("topic"), Topic);
	if (!PaneId.IsEmpty())
	{
		Data->SetStringField(TEXT("pane_id"), PaneId);
	}
	ResyncInFlight.Add(Slot, Topic);
	UE_LOG(LogVerseBridge, Log, TEXT("bridge: gap on %s, resync"), *Slot);
	SendCommand(TEXT("resync"), Data, [this, Slot](bool, const TSharedPtr<FJsonObject>&, const FString&) {});
}

bool FVerseBridgeClient::CheckBase(const FString& Slot, const FVerseBridgeFrame& Frame)
{
	const int64* Last = LastSeqOf.Find(Slot);
	if (!Frame.HasBase() || !Last || *Last != Frame.Base)
	{
		return false;
	}
	return true;
}

void FVerseBridgeClient::HandleText(const FString& Text, double Now)
{
	LastFrameAt = Now;
	FVerseBridgeFrame F;
	FString Error;
	if (!FVerseBridgeFrame::Parse(Text, F, &Error))
	{
		UE_LOG(LogVerseBridge, Warning, TEXT("bridge: malformed frame ignored (%s)"), *Error);
		return;
	}
	if (F.Seq >= 0)
	{
		LastSeq = FMath::Max(LastSeq, F.Seq);
	}
	if (State == EState::Handshaking)
	{
		if (F.Type != TEXT("welcome"))
		{
			return;
		}
		Welcome = F.Data;
		Settings.ApplyWelcome(F.Data);
		State = EState::Linked;
		bEverLinked = true;
		Attempts = 0;
		LastPingAt = Now;
		UE_LOG(LogVerseBridge, Log, TEXT("bridge: linked (session %s, app %s)"), *Str(F.Data, TEXT("session")), *Str(F.Data, TEXT("app_version")));
		// No replay: a fresh snapshot per resubscribed topic (contract 1, Reconnect).
		if (Topics.Num())
		{
			SendCommand(TEXT("subscribe"), StringArrayField(TEXT("topics"), Topics));
		}
		if (ScreenWatch.Num())
		{
			WatchScreens(ScreenWatch);
		}
		if (ChatWatch.Num())
		{
			WatchChatTails(ChatWatch);
		}
		OnLinked.Broadcast();
		OnFrame.Broadcast(F);
		return;
	}
	Dispatch(F);
}

void FVerseBridgeClient::Dispatch(const FVerseBridgeFrame& F)
{
	const FString& T = F.Type;
	if (T == TEXT("reply"))
	{
		FReply Callback;
		if (Pending.RemoveAndCopyValue(F.Re, Callback) && Callback)
		{
			const bool bOk = Bool(F.Data, TEXT("ok"));
			Callback(bOk, Obj(F.Data, TEXT("result")), Str(Obj(F.Data, TEXT("error")), TEXT("code")));
		}
		OnFrame.Broadcast(F);
		return;
	}
	if (!F.Id.IsEmpty() && T == TEXT("qa.exec"))
	{
		OnServerCommand.Broadcast(F);
		return;
	}
	auto Track = [this, &F](const FString& Topic, bool bDelta, TFunction<void()> Apply)
	{
		if (bDelta && !CheckBase(Topic, F))
		{
			Resync(Topic);
			return;
		}
		ResyncInFlight.Remove(Topic);
		LastSeqOf.Add(Topic, F.Seq);
		Apply();
	};
	if (T == TEXT("roster.snapshot"))
	{
		Track(TEXT("roster"), false, [&] { Roster.ApplySnapshot(F.Data); });
	}
	else if (T == TEXT("roster.delta"))
	{
		Track(TEXT("roster"), true, [&] { Roster.ApplyDelta(F.Data); });
	}
	else if (T == TEXT("groups.snapshot"))
	{
		Track(TEXT("groups"), false, [&] { Groups.ApplySnapshot(F.Data); });
	}
	else if (T == TEXT("groups.delta"))
	{
		Track(TEXT("groups"), true, [&] { Groups.ApplyDelta(F.Data); });
	}
	else if (T == TEXT("meetings.update"))
	{
		Groups.ApplyMeeting(F.Data);
	}
	else if (T == TEXT("progression.snapshot"))
	{
		Progression.ApplySnapshot(F.Data);
	}
	else if (T == TEXT("progression.awarded"))
	{
		Progression.ApplyAward(F.Data);
	}
	else if (T == TEXT("chat_tails.update"))
	{
		ChatTails.Apply(F.Data);
	}
	else if (T == TEXT("companion.snapshot") || T == TEXT("companion.update"))
	{
		Companion.Apply(F.Data);
	}
	else if (T == TEXT("settings.changed"))
	{
		Settings.ApplyChanged(F.Data);
	}
	else if (T == TEXT("screens.meta"))
	{
		Screens.ApplyMeta(F.Data);
	}
	else if (T == TEXT("screens.gone"))
	{
		Screens.ApplyGone(F.Data);
	}
	else if (T == TEXT("screens.frame"))
	{
		FVerseCellsFrame Cells;
		FString Error;
		if (FVerseCellsFrame::FromJson(F.Data, Cells, &Error))
		{
			Cells.Seq = uint32(F.Seq);
			Cells.Base = F.HasBase() ? uint32(F.Base) : 0;
			const FString PaneId = Str(F.Data, TEXT("pane_id"));
			if (Cells.bSnapshot)
			{
				Screens.ApplyMeta(F.Data);
			}
			if (!Screens.ApplyFrame(Cells, PaneId))
			{
				Resync(TEXT("screens"), PaneId);
			}
		}
		else
		{
			UE_LOG(LogVerseBridge, Warning, TEXT("bridge: bad screens.frame (%s)"), *Error);
		}
	}
	OnFrame.Broadcast(F);
}

void FVerseBridgeClient::HandleBinary(const TArray<uint8>& Bytes, double Now)
{
	LastFrameAt = Now;
	FVerseCellsFrame Cells;
	FString Error;
	if (!FVerseCellsFrame::Decode(Bytes, Cells, &Error))
	{
		UE_LOG(LogVerseBridge, Warning, TEXT("bridge: bad cells.bin/1 frame (%s)"), *Error);
		return;
	}
	LastSeq = FMath::Max<int64>(LastSeq, Cells.Seq);
	const FString PaneId = Screens.PaneForRef(Cells.Ref);
	if (!Screens.ApplyFrame(Cells) && !PaneId.IsEmpty())
	{
		Resync(TEXT("screens"), PaneId);
	}
}

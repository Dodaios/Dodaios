#include "Duel/VerseDuelReporter.h"

#include "Events/VerseEventHub.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"
#include "Misc/Guid.h"
#include "Misc/Paths.h"
#include "VerseLog.h"

namespace VerseDuel
{
	namespace
	{
		const TCHAR* const PendingExtension = TEXT(".json");

		/** A file name for a match id: safe characters plus a hash, so two ids never share a file. */
		FString FileStem(const FString& MatchId)
		{
			FString Safe;
			Safe.Reserve(MatchId.Len());
			for (const TCHAR Char : MatchId)
			{
				const bool bOk = FChar::IsAlnum(Char) && Char < 128;
				Safe.AppendChar(bOk || Char == TEXT('_') || Char == TEXT('-') ? Char : TEXT('_'));
			}
			return FString::Printf(TEXT("%s_%08x"), *Safe.Left(48), FCrc::StrCrc32(*MatchId));
		}
	}

	FString FDuelReporter::DefaultPendingDir()
	{
		return FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("Verse"), TEXT("Duel"), TEXT("Pending"));
	}

	FDuelReporter::FDuelReporter(FConfig InConfig)
		: Config(MoveTemp(InConfig))
	{
		if (Config.LaunchId.IsEmpty())
		{
			Config.LaunchId = FGuid::NewGuid().ToString(EGuidFormats::Digits);
		}
	}

	FDuelReporter::~FDuelReporter()
	{
		Unbind();
	}

	void FDuelReporter::SetSink(TSharedPtr<IDuelResultSink> InSink)
	{
		Sink = MoveTemp(InSink);
	}

	void FDuelReporter::Bind(UVerseEventHub& Hub)
	{
		Unbind();
		BoundHub = &Hub;
		SetEndedHandle = Hub.OnSetEnded.AddSP(AsShared(), &FDuelReporter::HandleSetEnded);
	}

	void FDuelReporter::Unbind()
	{
		if (UVerseEventHub* Hub = BoundHub.Get())
		{
			Hub->OnSetEnded.Remove(SetEndedHandle);
		}
		BoundHub.Reset();
		SetEndedHandle.Reset();
	}

	void FDuelReporter::UnbindFrom(const UVerseEventHub& Hub)
	{
		if (BoundHub.Get() == &Hub)
		{
			Unbind();
		}
	}

	FString FDuelReporter::PathFor(const FString& MatchId) const
	{
		return FPaths::Combine(Config.PendingDir, FileStem(MatchId) + PendingExtension);
	}

	void FDuelReporter::LoadPendingFromDisk()
	{
		if (bLoaded)
		{
			return;
		}
		bLoaded = true;
		TArray<FString> Files;
		IFileManager::Get().FindFiles(Files, *FPaths::Combine(Config.PendingDir, FString(TEXT("*")) + PendingExtension), true, false);
		Files.Sort();
		for (const FString& File : Files)
		{
			const FString Path = FPaths::Combine(Config.PendingDir, File);
			FString Text;
			TSharedPtr<FJsonObject> Root;
			if (FFileHelper::LoadFileToString(Text, *Path))
			{
				Root = FromJsonString(Text);
			}
			const TSharedPtr<FJsonObject>* Data = nullptr;
			FString MatchId;
			if (!Root.IsValid() || !Root->TryGetObjectField(TEXT("data"), Data) || !Data || !(*Data)->TryGetStringField(TEXT("match_id"), MatchId) || MatchId.IsEmpty())
			{
				UE_LOG(LogVerseBridge, Warning, TEXT("duel: dropping unreadable pending result %s"), *File);
				IFileManager::Get().Delete(*Path, false, true, true);
				continue;
			}
			if (Pending.ContainsByPredicate([&MatchId](const FPending& P) { return P.MatchId == MatchId; }))
			{
				continue;
			}
			FPending Entry;
			Entry.MatchId = MatchId;
			Entry.LaunchId = Root->GetStringField(TEXT("launch_id"));
			Entry.Data = *Data;
			Pending.Add(MoveTemp(Entry));
		}
	}

	bool FDuelReporter::Persist(const FPending& Entry) const
	{
		TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
		Root->SetStringField(TEXT("launch_id"), Entry.LaunchId);
		Root->SetObjectField(TEXT("data"), Entry.Data);
		const FString Path = PathFor(Entry.MatchId);
		const FString Temp = Path + TEXT(".tmp");
		IFileManager::Get().MakeDirectory(*Config.PendingDir, true);
		if (!FFileHelper::SaveStringToFile(ToJsonString(Root), *Temp, FFileHelper::EEncodingOptions::ForceUTF8WithoutBOM))
		{
			return false;
		}
		return IFileManager::Get().Move(*Path, *Temp, true, true);
	}

	void FDuelReporter::Forget(const FString& MatchId)
	{
		Pending.RemoveAll([&MatchId](const FPending& P) { return P.MatchId == MatchId; });
		IFileManager::Get().Delete(*PathFor(MatchId), false, true, true);
	}

	void FDuelReporter::HandleSetEnded(const FVerseSetSummary& Summary)
	{
		LoadPendingFromDisk();
		if (Summary.MatchId.IsEmpty())
		{
			UE_LOG(LogVerseBridge, Warning, TEXT("duel: a set ended without a match id; not reported"));
			return;
		}
		if (Stored.Contains(Summary.MatchId) || Pending.ContainsByPredicate([&Summary](const FPending& P) { return P.MatchId == Summary.MatchId; }))
		{
			return;
		}
		EEndReason Reason = DefaultEndReason(Summary);
		if (Summary.Outcome == EVerseSetOutcome::Unfinished && QuitReason.IsSet())
		{
			Reason = QuitReason.GetValue();
		}
		FPending Entry;
		Entry.MatchId = Summary.MatchId;
		Entry.LaunchId = Config.LaunchId;
		Entry.Data = EncodeResult(Summary, Reason, Config.Build);
		if (!Persist(Entry))
		{
			UE_LOG(LogVerseBridge, Warning, TEXT("duel: pending result %s not saved; a crash before its reply loses it"), *Entry.MatchId);
		}
		Pending.Add(MoveTemp(Entry));
		Send(Pending.Last());
	}

	void FDuelReporter::HandleWelcome()
	{
		LoadPendingFromDisk();
		// Send from a copy of the ids: a sink that answers at once changes the list.
		TArray<FString> Ids = PendingMatchIds();
		for (const FString& Id : Ids)
		{
			FPending* Entry = Pending.FindByPredicate([&Id](const FPending& P) { return P.MatchId == Id; });
			if (!Entry || Entry->bInFlight)
			{
				continue;
			}
			if (Entry->LaunchId != Config.LaunchId)
			{
				// A leftover of a launch that never got its reply: it is recovered now.
				Entry->Data->SetStringField(TEXT("end_reason"), EndReasonName(EEndReason::CrashRecovered));
				Entry->LaunchId = Config.LaunchId;
				Persist(*Entry);
			}
			Send(*Entry);
		}
	}

	void FDuelReporter::NotifyQuitting(EEndReason Reason)
	{
		QuitReason = Reason;
	}

	TArray<FString> FDuelReporter::PendingMatchIds() const
	{
		TArray<FString> Ids;
		for (const FPending& Entry : Pending)
		{
			Ids.Add(Entry.MatchId);
		}
		return Ids;
	}

	void FDuelReporter::Send(FPending& Entry)
	{
		if (!Sink.IsValid() || !Sink->IsReady() || Entry.bInFlight)
		{
			return;
		}
		Entry.bInFlight = true;
		++SentCount;
		const FString MatchId = Entry.MatchId;
		TWeakPtr<FDuelReporter> Weak = AsShared();
		Sink->SendDuelResult(Entry.Data.ToSharedRef(), [Weak, MatchId](ESendResult Result)
		{
			if (TSharedPtr<FDuelReporter> Self = Weak.Pin())
			{
				Self->OnSent(MatchId, Result);
			}
		});
	}

	void FDuelReporter::OnSent(const FString& MatchId, ESendResult Result)
	{
		switch (Result)
		{
		case ESendResult::Stored:
			Stored.Add(MatchId);
			Forget(MatchId);
			break;
		case ESendResult::Rejected:
			UE_LOG(LogVerseBridge, Warning, TEXT("duel: the server refused result %s (bad_request); dropped"), *MatchId);
			Forget(MatchId);
			break;
		default:
			if (FPending* Entry = Pending.FindByPredicate([&MatchId](const FPending& P) { return P.MatchId == MatchId; }))
			{
				Entry->bInFlight = false;
			}
			break;
		}
	}

	FDuelReporter& ProcessReporter()
	{
		static TSharedRef<FDuelReporter> Reporter = []()
		{
			FDuelReporter::FConfig Config;
			Config.PendingDir = FDuelReporter::DefaultPendingDir();
			Config.Build = FBuildStamp::Current();
			return MakeShared<FDuelReporter>(MoveTemp(Config));
		}();
		return *Reporter;
	}
}

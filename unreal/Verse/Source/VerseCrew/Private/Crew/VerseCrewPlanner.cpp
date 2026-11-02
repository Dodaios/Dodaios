#include "Crew/VerseCrewPlanner.h"

#include "Algo/StableSort.h"
#include "Crew/VerseCrewCollate.h"

namespace
{
	const FName PlannerDeckBridge(TEXT("bridge"));
	const FName PlannerDeckOps(TEXT("ops"));
	const FName PlannerDeckEngineering(TEXT("engineering"));

	struct FWeightedIdle
	{
		VerseCrewPlanner::FIdleVenue Venue;
		uint32 Weight;
	};

	// OFFICER_IDLE of planner.ts: mess 5, corridor 2, viewport 3.
	const FWeightedIdle* OfficerIdle(int32& OutCount)
	{
		static const FWeightedIdle Table[] = {
			{ { EVerseCrewVenue::Mess, PlannerDeckOps, EVerseCrewActivity::SitRest }, 5 },
			{ { EVerseCrewVenue::Corridor, PlannerDeckOps, EVerseCrewActivity::StandRest }, 2 },
			{ { EVerseCrewVenue::Viewport, PlannerDeckBridge, EVerseCrewActivity::StandRest }, 3 },
		};
		OutCount = UE_ARRAY_COUNT(Table);
		return Table;
	}

	bool SocketOrderLess(const FVerseCrewSocket& A, const FVerseCrewSocket& B)
	{
		if (A.Order != B.Order)
		{
			return A.Order < B.Order;
		}
		return VerseCrew::LocaleCompare(A.Id, B.Id) < 0;
	}

	void SortBySocketOrder(const FVerseCrewDeck& Deck, TArray<int32>& Indices)
	{
		Algo::StableSort(Indices, [&](int32 A, int32 B) { return SocketOrderLess(Deck.Sockets[A], Deck.Sockets[B]); });
	}

	template <typename TPredicate>
	TArray<int32> Of(const FVerseCrewDeck& Deck, EVerseCrewSocketKind Kind, TPredicate&& GroupTest)
	{
		TArray<int32> Out;
		for (int32 I = 0; I < Deck.Sockets.Num(); ++I)
		{
			if (Deck.Sockets[I].Kind == Kind && GroupTest(Deck.Sockets[I].Group))
			{
				Out.Add(I);
			}
		}
		SortBySocketOrder(Deck, Out);
		return Out;
	}

	bool AtConsole(EVerseCrewDuty Duty)
	{
		return Duty == EVerseCrewDuty::Working || Duty == EVerseCrewDuty::Waiting || Duty == EVerseCrewDuty::Error;
	}

	TArray<const FVerseCrewMember*> SortedByService(TArrayView<const FVerseCrewMember> Crew)
	{
		TArray<const FVerseCrewMember*> Out;
		Out.Reserve(Crew.Num());
		for (const FVerseCrewMember& M : Crew)
		{
			Out.Add(&M);
		}
		Algo::StableSort(Out, [](const FVerseCrewMember* A, const FVerseCrewMember* B) { return VerseCrewServiceOrderLess(*A, *B); });
		return Out;
	}
}

namespace VerseCrewPlanner
{
	FName HomeDeck(EVerseCrewRole Role)
	{
		return Role == EVerseCrewRole::Officer ? PlannerDeckBridge : PlannerDeckEngineering;
	}

	FIdleVenue IdleVenueOf(const FString& MemberId, int64 NowMs)
	{
		const int64 Offset = static_cast<int64>(VerseCrew::Hash32(MemberId + TEXT(":phase")) % static_cast<uint32>(IdleSlotMs));
		const int64 Sum = NowMs + Offset;
		// Math.floor for negative times as well.
		const int64 Slot = Sum >= 0 ? Sum / IdleSlotMs : -((-Sum + IdleSlotMs - 1) / IdleSlotMs);
		const uint32 Seed = VerseCrew::Hash32(FString::Printf(TEXT("%s:%lld"), *MemberId, Slot));
		int32 Count = 0;
		const FWeightedIdle* Table = OfficerIdle(Count);
		uint32 Total = 0;
		for (int32 I = 0; I < Count; ++I)
		{
			Total += Table[I].Weight;
		}
		uint32 X = Seed % Total;
		for (int32 I = 0; I < Count; ++I)
		{
			if (X < Table[I].Weight)
			{
				return Table[I].Venue;
			}
			X -= Table[I].Weight;
		}
		return Table[Count - 1].Venue;
	}

	FVerseCrewIntent IntentOf(const FVerseCrewMember& Member, EVerseCrewRoundPart Part, int64 NowMs, bool bMessCall)
	{
		auto Make = [](FName Deck, EVerseCrewVenue Venue, EVerseCrewActivity Activity, bool bFace) {
			FVerseCrewIntent Intent;
			Intent.Deck = Deck;
			Intent.Venue = Venue;
			Intent.Activity = Activity;
			Intent.bFaceCommander = bFace;
			return Intent;
		};
		if (Member.Role == EVerseCrewRole::Technician)
		{
			switch (Member.Duty)
			{
			case EVerseCrewDuty::Working: return Make(PlannerDeckEngineering, EVerseCrewVenue::Terminal, EVerseCrewActivity::SitType, false);
			case EVerseCrewDuty::Waiting: return Make(PlannerDeckEngineering, EVerseCrewVenue::Terminal, EVerseCrewActivity::StandWait, true);
			case EVerseCrewDuty::Error: return Make(PlannerDeckEngineering, EVerseCrewVenue::Terminal, EVerseCrewActivity::StandAlert, false);
			default: return Make(PlannerDeckEngineering, EVerseCrewVenue::Workshop, EVerseCrewActivity::StandRest, false);
			}
		}
		if (Member.Duty == EVerseCrewDuty::Paused)
		{
			return Make(PlannerDeckOps, EVerseCrewVenue::Bunk, EVerseCrewActivity::Sleep, false);
		}
		if (Part == EVerseCrewRoundPart::Speaker && Member.Duty != EVerseCrewDuty::Waiting)
		{
			return Make(PlannerDeckBridge, EVerseCrewVenue::Briefing, EVerseCrewActivity::Talk, false);
		}
		switch (Member.Duty)
		{
		case EVerseCrewDuty::Working: return Make(PlannerDeckBridge, EVerseCrewVenue::Console, EVerseCrewActivity::SitType, false);
		case EVerseCrewDuty::Waiting: return Make(PlannerDeckBridge, EVerseCrewVenue::Console, EVerseCrewActivity::StandWait, true);
		case EVerseCrewDuty::Error: return Make(PlannerDeckBridge, EVerseCrewVenue::Console, EVerseCrewActivity::StandAlert, false);
		default: break;
		}
		if (Part == EVerseCrewRoundPart::Listener)
		{
			return Make(PlannerDeckBridge, EVerseCrewVenue::Briefing, EVerseCrewActivity::Listen, false);
		}
		if (bMessCall)
		{
			return Make(PlannerDeckOps, EVerseCrewVenue::Mess, EVerseCrewActivity::SitRest, false);
		}
		const FIdleVenue Idle = IdleVenueOf(Member.Id, NowMs);
		return Make(Idle.Deck, Idle.Venue, Idle.Activity, false);
	}

	TArray<int32> ConsoleSeats(const FVerseCrewDeck& Deck)
	{
		TSet<FString> Screens;
		for (const FVerseCrewSocket& S : Deck.Sockets)
		{
			if (S.Kind == EVerseCrewSocketKind::Screen)
			{
				Screens.Add(S.Id);
			}
		}
		TArray<int32> Out;
		for (int32 I = 0; I < Deck.Sockets.Num(); ++I)
		{
			const FVerseCrewSocket& S = Deck.Sockets[I];
			if (S.Kind == EVerseCrewSocketKind::Seat && S.StationId.IsEmpty() && Screens.Contains(S.Id))
			{
				Out.Add(I);
			}
		}
		SortBySocketOrder(Deck, Out);
		return Out;
	}

	TArray<int32> TeamTableSeats(const FVerseCrewDeck& Deck)
	{
		FString Table;
		for (const FVerseCrewSocket& S : Deck.Sockets)
		{
			if (S.StationKind == TEXT("team") && !S.StationId.IsEmpty())
			{
				Table = S.StationId;
				break;
			}
		}
		TArray<int32> Out;
		if (Table.IsEmpty())
		{
			return Out;
		}
		for (int32 I = 0; I < Deck.Sockets.Num(); ++I)
		{
			const FVerseCrewSocket& S = Deck.Sockets[I];
			if (S.Kind == EVerseCrewSocketKind::Seat && S.StationId == Table)
			{
				Out.Add(I);
			}
		}
		SortBySocketOrder(Deck, Out);
		return Out;
	}

	TArray<int32> VenueSockets(const FVerseCrewDeck& Deck, EVerseCrewVenue Venue)
	{
		auto Is = [](const TCHAR* Name) { return [Name](const FString& G) { return G == Name; }; };
		auto Has = [](const TCHAR* Name) { return [Name](const FString& G) { return G.Contains(Name, ESearchCase::CaseSensitive); }; };
		auto Append = [](TArray<int32> A, const TArray<int32>& B) { A.Append(B); return A; };
		switch (Venue)
		{
		case EVerseCrewVenue::Console:
		case EVerseCrewVenue::Terminal:
			return ConsoleSeats(Deck);
		case EVerseCrewVenue::Briefing:
			return TeamTableSeats(Deck);
		case EVerseCrewVenue::Mess:
			return Append(Of(Deck, EVerseCrewSocketKind::Seat, Is(TEXT("mess"))), Of(Deck, EVerseCrewSocketKind::Stand, Is(TEXT("mess"))));
		case EVerseCrewVenue::Corridor:
			return Append(Of(Deck, EVerseCrewSocketKind::Stand, Is(TEXT("corridor"))), Of(Deck, EVerseCrewSocketKind::Waypoint, Has(TEXT("corridor"))));
		case EVerseCrewVenue::Viewport:
			return Append(Of(Deck, EVerseCrewSocketKind::Stand, Is(TEXT("viewport"))),
				Of(Deck, EVerseCrewSocketKind::Waypoint, [](const FString& G) {
					return G.Contains(TEXT("viewport"), ESearchCase::CaseSensitive) || G == TEXT("vp") || G.StartsWith(TEXT("vp_"), ESearchCase::CaseSensitive);
				}));
		case EVerseCrewVenue::Bunk:
			return Of(Deck, EVerseCrewSocketKind::Bunk, [](const FString&) { return true; });
		case EVerseCrewVenue::Workshop:
		default:
			return Append(Append(Of(Deck, EVerseCrewSocketKind::Stand, Is(TEXT("workshop"))), Of(Deck, EVerseCrewSocketKind::Stand, Is(TEXT("corridor")))),
				Of(Deck, EVerseCrewSocketKind::Waypoint, [](const FString& G) { return !G.StartsWith(TEXT("patrol"), ESearchCase::CaseSensitive); }));
		}
	}

	TMap<FString, FString> HomeSeats(const FVerseCrewDeck& Deck, TArrayView<const FVerseCrewMember> Crew, EVerseCrewRole Role,
		const TMap<FString, FString>& Previous)
	{
		const TArray<int32> Seats = VenueSockets(Deck, Role == EVerseCrewRole::Officer ? EVerseCrewVenue::Console : EVerseCrewVenue::Terminal);
		TSet<FString> Ids;
		for (const int32 I : Seats)
		{
			Ids.Add(Deck.Sockets[I].Id);
		}
		TArray<const FVerseCrewMember*> Members;
		for (const FVerseCrewMember* M : SortedByService(Crew))
		{
			if (M->Role == Role)
			{
				Members.Add(M);
			}
		}
		TMap<FString, FString> Out;
		TSet<FString> Taken;
		auto Keep = [&](const TArray<const FVerseCrewMember*>& Group) {
			for (const FVerseCrewMember* M : Group)
			{
				const FString* Kept = Previous.Find(M->Id);
				if (Kept && Ids.Contains(*Kept) && !Taken.Contains(*Kept))
				{
					Out.Add(M->Id, *Kept);
					Taken.Add(*Kept);
				}
			}
		};
		auto Fill = [&](const TArray<const FVerseCrewMember*>& Group, const TSet<FString>& Spare) {
			for (const FVerseCrewMember* M : Group)
			{
				if (Out.Contains(M->Id))
				{
					continue;
				}
				const FVerseCrewSocket* Seat = nullptr;
				for (const int32 I : Seats)
				{
					if (!Taken.Contains(Deck.Sockets[I].Id) && !Spare.Contains(Deck.Sockets[I].Id))
					{
						Seat = &Deck.Sockets[I];
						break;
					}
				}
				if (!Seat)
				{
					for (const int32 I : Seats)
					{
						if (!Taken.Contains(Deck.Sockets[I].Id))
						{
							Seat = &Deck.Sockets[I];
							break;
						}
					}
				}
				if (!Seat)
				{
					return;
				}
				Out.Add(M->Id, Seat->Id);
				Taken.Add(Seat->Id);
			}
		};
		TArray<const FVerseCrewMember*> OnDuty;
		TArray<const FVerseCrewMember*> OffDuty;
		for (const FVerseCrewMember* M : Members)
		{
			(AtConsole(M->Duty) ? OnDuty : OffDuty).Add(M);
		}
		TSet<FString> HeldOffDuty;
		for (const FVerseCrewMember* M : OffDuty)
		{
			if (const FString* Held = Previous.Find(M->Id))
			{
				if (!Held->IsEmpty())
				{
					HeldOffDuty.Add(*Held);
				}
			}
		}
		Keep(OnDuty);
		Fill(OnDuty, HeldOffDuty);
		Keep(OffDuty);
		Fill(OffDuty, TSet<FString>());
		return Out;
	}

	FVerseCrewDeckPlan PlaceOnDeck(const FVerseCrewPlanInput& Input)
	{
		FVerseCrewDeckPlan Plan;
		if (!Input.Deck)
		{
			return Plan;
		}
		const FVerseCrewDeck& Deck = *Input.Deck;
		static const TMap<FString, FString> Empty;
		const TMap<FString, FString>& Previous = Input.Previous ? *Input.Previous : Empty;

		TMap<FString, int32> SeatsById;
		for (const int32 I : ConsoleSeats(Deck))
		{
			SeatsById.Add(Deck.Sockets[I].Id, I);
		}
		TMap<FString, FString> PreviousSeats;
		if (Input.Homes)
		{
			PreviousSeats = *Input.Homes;
		}
		for (const TPair<FString, FString>& Pair : Previous)
		{
			if (Pair.Value.StartsWith(TEXT("seat:")))
			{
				PreviousSeats.Add(Pair.Key, Pair.Value.Mid(5));
			}
		}
		for (const EVerseCrewRole Role : { EVerseCrewRole::Officer, EVerseCrewRole::Technician })
		{
			if (HomeDeck(Role) == Deck.Id)
			{
				for (const TPair<FString, FString>& Home : HomeSeats(Deck, Input.Crew, Role, PreviousSeats))
				{
					Plan.Homes.Add(Home.Key, Home.Value);
				}
			}
		}
		TSet<FString> Taken;
		if (Input.Blocked)
		{
			Taken.Append(*Input.Blocked);
		}
		struct FHere
		{
			const FVerseCrewMember* Member;
			FVerseCrewIntent Intent;
		};
		TArray<FHere> Here;
		for (const FVerseCrewMember* M : SortedByService(Input.Crew))
		{
			EVerseCrewRoundPart Part = EVerseCrewRoundPart::None;
			if (Input.Rounds)
			{
				if (const EVerseCrewRoundPart* Found = Input.Rounds->Find(M->Id))
				{
					Part = *Found;
				}
			}
			const FVerseCrewIntent Intent = IntentOf(*M, Part, Input.NowMs, Input.bMessCall);
			if (Intent.Deck == Deck.Id)
			{
				Here.Add({ M, Intent });
			}
		}
		for (const TPair<FString, FString>& Home : Plan.Homes)
		{
			Taken.Add(TEXT("seat:") + Home.Value);
		}
		for (const FHere& H : Here)
		{
			if (H.Intent.Venue != EVerseCrewVenue::Console && H.Intent.Venue != EVerseCrewVenue::Terminal)
			{
				continue;
			}
			const FString* Home = Plan.Homes.Find(H.Member->Id);
			const int32* Seat = Home ? SeatsById.Find(*Home) : nullptr;
			if (Seat && !(Input.Blocked && Input.Blocked->Contains(Deck.Sockets[*Seat].Key())))
			{
				FVerseCrewPlacement P;
				P.Intent = H.Intent;
				P.SocketIndex = *Seat;
				P.SocketKey = Deck.Sockets[*Seat].Key();
				Plan.Placements.Add(H.Member->Id, P);
			}
		}
		for (const FHere& H : Here)
		{
			if (H.Intent.Venue == EVerseCrewVenue::Console || H.Intent.Venue == EVerseCrewVenue::Terminal)
			{
				continue;
			}
			TArray<int32> Free;
			for (const int32 I : VenueSockets(Deck, H.Intent.Venue))
			{
				if (!Taken.Contains(Deck.Sockets[I].Key()))
				{
					Free.Add(I);
				}
			}
			if (Free.Num() == 0)
			{
				continue;
			}
			int32 Choice = INDEX_NONE;
			if (const FString* Kept = Previous.Find(H.Member->Id))
			{
				for (const int32 I : Free)
				{
					if (Deck.Sockets[I].Key() == *Kept)
					{
						Choice = I;
						break;
					}
				}
			}
			if (Choice == INDEX_NONE)
			{
				Choice = H.Intent.Venue == EVerseCrewVenue::Briefing
					? Free[0]
					: Free[VerseCrew::Hash32(FString::Printf(TEXT("%s:%s"), *H.Member->Id, VerseCrew::VenueName(H.Intent.Venue))) % static_cast<uint32>(Free.Num())];
			}
			FVerseCrewPlacement P;
			P.Intent = H.Intent;
			P.SocketIndex = Choice;
			P.SocketKey = Deck.Sockets[Choice].Key();
			Plan.Placements.Add(H.Member->Id, P);
			Taken.Add(P.SocketKey);
		}
		return Plan;
	}
}

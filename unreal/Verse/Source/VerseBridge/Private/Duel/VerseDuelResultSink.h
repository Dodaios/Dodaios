#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Templates/Function.h"

// The seam between the duel reporter and the bridge client (WP17). The client implements it:
// IsReady once `welcome` arrived on the current connection, SendDuelResult as one `duel.result`
// command whose `reply` it hands back exactly once. Tests use FFakeDuelResultSink.

namespace VerseDuel
{
	/** How a sent result came back. */
	enum class ESendResult : uint8
	{
		/** `reply` with `ok: true`: the server stored it (or already had it). */
		Stored,
		/** `reply` with `ok: false` and `bad_request`: the server will never take it. */
		Rejected,
		/** No answer (link dropped, timeout, any other error code): try again on the next welcome. */
		Failed,
	};

	class IDuelResultSink
	{
	public:
		virtual ~IDuelResultSink() = default;

		/** True between `welcome` and the end of the connection. */
		virtual bool IsReady() const = 0;

		/** Sends one `duel.result` with `Data` as its payload; calls OnDone exactly once. */
		virtual void SendDuelResult(const TSharedRef<FJsonObject>& Data, TFunction<void(ESendResult)> OnDone) = 0;
	};
}

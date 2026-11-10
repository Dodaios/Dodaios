#pragma once

#include "CoreMinimal.h"

namespace VerseCrew
{
	/**
	 * String order of JavaScript's String.prototype.localeCompare for the ASCII ids the
	 * planner sorts (socket and member ids): punctuation before digits before letters, letters
	 * compared case-blind first, then lower case before upper case, then code units. The
	 * planner golden test checks it against the TypeScript output.
	 */
	VERSECREW_API int32 LocaleCompare(const FString& A, const FString& B);
}

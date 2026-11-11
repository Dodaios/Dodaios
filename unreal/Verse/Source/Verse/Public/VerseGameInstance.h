#pragma once

#include "CoreMinimal.h"
#include "Engine/GameInstance.h"

#include "VerseGameInstance.generated.h"

/** Project game instance (Config/DefaultEngine.ini GameInstanceClass). */
UCLASS()
class VERSE_API UVerseGameInstance : public UGameInstance
{
	GENERATED_BODY()

public:
	/** Outside the editor, the engine's on-screen debug lines stay off (`-ScreenMessages` keeps them). */
	virtual void Init() override;

	/**
	 * A duel asked for on another deck (the bar's Quick duel, the app's Quick duel): its tier,
	 * kept while the lift rides down; the hangar's duel subsystem starts it on arrival.
	 */
	FName PendingDuelTier;
};

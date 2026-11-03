#include "Duel/VerseDuelReporterSubsystem.h"

#include "Duel/VerseDuelReporter.h"
#include "Events/VerseEventHub.h"
#include "Engine/World.h"
#include "Misc/CoreMisc.h"
#include "Subsystems/SubsystemCollection.h"

bool UVerseDuelReporterSubsystem::DoesSupportWorldType(const EWorldType::Type WorldType) const
{
	// The duel runs in the game world (and in play-in-editor); editor and preview worlds never report.
	return WorldType == EWorldType::Game || WorldType == EWorldType::PIE;
}

void UVerseDuelReporterSubsystem::Initialize(FSubsystemCollectionBase& Collection)
{
	Super::Initialize(Collection);
	UVerseEventHub* Hub = Collection.InitializeDependency<UVerseEventHub>();
	// Automation worlds raise synthetic sets; they must never become pending results that a
	// real launch would send. The reporter's own tests drive FDuelReporter directly.
	if (Hub && !GIsAutomationTesting)
	{
		VerseDuel::ProcessReporter().Bind(*Hub);
	}
}

void UVerseDuelReporterSubsystem::Deinitialize()
{
	if (const UWorld* World = GetWorld())
	{
		if (const UVerseEventHub* Hub = World->GetSubsystem<UVerseEventHub>())
		{
			VerseDuel::ProcessReporter().UnbindFrom(*Hub);
		}
	}
	Super::Deinitialize();
}

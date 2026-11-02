using UnrealBuildTool;
using System.Collections.Generic;

// Game target. VerseHarness is a DeveloperTool module and is listed only in the
// Editor target (architecture.md 8.1, decision C7). There is no Server target:
// a binary engine install cannot build one, so the game runs as a listen server.
public class VerseTarget : TargetRules
{
	public VerseTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Game;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.Add("Verse");
	}
}

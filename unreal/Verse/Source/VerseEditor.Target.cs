using UnrealBuildTool;
using System.Collections.Generic;

// Editor target: the primary module plus VerseHarness (automation tests,
// Gauntlet controllers, capture). The Game target never carries the harness.
public class VerseEditorTarget : TargetRules
{
	public VerseEditorTarget(TargetInfo Target) : base(Target)
	{
		Type = TargetType.Editor;
		DefaultBuildSettings = BuildSettingsVersion.Latest;
		IncludeOrderVersion = EngineIncludeOrderVersion.Latest;
		ExtraModuleNames.AddRange(new string[] { "Verse", "VerseHarness" });
	}
}

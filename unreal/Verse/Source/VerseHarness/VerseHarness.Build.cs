using UnrealBuildTool;

// DeveloperTool module, Editor target only: may depend on every runtime module.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseHarness : ModuleRules
{
	public VerseHarness(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "Verse", "VerseCore", "VerseBridge", "VerseMovement", "VerseDestruction", "VerseCombat", "VerseGore", "VerseDecks", "VerseCrew", "VerseScreens", "VerseBot", "VerseUI", "VerseStream" });
	}
}

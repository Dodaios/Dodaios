using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseUI : ModuleRules
{
	public VerseUI(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge", "VerseCombat", "VerseCrew", "VerseDecks" });
		// Json, Slate: the service record reads progression frames and draws Slate widgets (WP21.7).
		PublicDependencyModuleNames.AddRange(new string[] { "Json", "Slate", "SlateCore" });
	}
}

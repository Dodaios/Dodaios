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
		// Json: station command data; Slate: the plain station overlay until WP18's UI root (WP16, request to the integration owner).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json", "Slate", "SlateCore" });
	}
}

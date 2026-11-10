using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseDecks : ModuleRules
{
	public VerseDecks(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge" });
		// Json: deck manifests from the zone placement files, QA state and the bridge world actions (WP12).
		PrivateDependencyModuleNames.AddRange(new string[] { "Json" });
		// InputCore, EnhancedInput: the deck commander's keys and mouse (stream S5: IMC_VerseDeck, parity K-09).
		PrivateDependencyModuleNames.AddRange(new string[] { "InputCore", "EnhancedInput" });
	}
}

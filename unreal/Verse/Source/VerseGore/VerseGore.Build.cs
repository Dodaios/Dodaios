using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseGore : ModuleRules
{
	public VerseGore(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore" });
		// Niagara: the blood bursts of WP05.2 (change request #1171 item 4).
		PrivateDependencyModuleNames.AddRange(new string[] { "Niagara" });
	}
}

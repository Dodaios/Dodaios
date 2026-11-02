using UnrealBuildTool;

// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseDestruction : ModuleRules
{
	public VerseDestruction(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore" });
		// Engine module (not a Verse edge): FFastArraySerializer of the piece state (destruction.md 3.3).
		PublicDependencyModuleNames.AddRange(new string[] { "NetCore" });
	}
}

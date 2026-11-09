using UnrealBuildTool;

// The commander's look and powers on the decks (stream S7): Arc Storm, the hoverboard, the Sovereign cloak.
// Verse dependencies are exactly the edges of architecture.md section 2.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class VerseAbilities : ModuleRules
{
	public VerseAbilities(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseMovement" });
		// AudioExtensions: Arc Storm's synthesised sound is a procedural sound wave.
		PrivateDependencyModuleNames.AddRange(new string[] { "AudioExtensions" });
	}
}

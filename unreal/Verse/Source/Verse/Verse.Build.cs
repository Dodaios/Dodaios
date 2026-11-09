using UnrealBuildTool;

// Primary game module: may depend on every runtime module except VerseHarness.
// A new Verse edge is a contract change; scripts/unreal/check_build_dag.py fails on any other.
public class Verse : ModuleRules
{
	public Verse(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine", "NetCore", "DeveloperSettings", "EngineSettings" });
		PublicDependencyModuleNames.AddRange(new string[] { "VerseCore", "VerseBridge", "VerseMovement", "VerseDestruction", "VerseCombat", "VerseGore", "VerseDecks", "VerseCrew", "VerseScreens", "VerseBot", "VerseUI", "VerseStream" });
		// GAS on the default pawn: its ability system component carries UVerseHealthSet (combat-state.md 2.1).
		PrivateDependencyModuleNames.AddRange(new string[] { "GameplayAbilities", "GameplayTags", "GameplayTasks" });
		// The duel autopilot walks nav paths; the duel subsystem writes its stats as JSON.
		PrivateDependencyModuleNames.AddRange(new string[] { "NavigationSystem", "Json", "InputCore" });
	}
}

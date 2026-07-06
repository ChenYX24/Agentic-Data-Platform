using UnrealBuildTool;

public class ADPPhysicsRuntime : ModuleRules
{
	public ADPPhysicsRuntime(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new[]
		{
			"Core",
			"CoreUObject",
			"Engine",
			"Json",
			"JsonUtilities",
			"PhysicsCore"
		});
	}
}

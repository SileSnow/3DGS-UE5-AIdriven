// Copyright Epic Games, Inc. All Rights Reserved.

using UnrealBuildTool;

public class DJI3DGS_UE : ModuleRules
{
	public DJI3DGS_UE(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] {
			"Core", "CoreUObject", "Engine", "InputCore", "EnhancedInput",
			"GaussianSplattingRuntime"
		});

		PrivateDependencyModuleNames.AddRange(new string[] {
			"Niagara", "RenderCore", "RHI", "Projects", "Json", "JsonUtilities", "ImageCore",
			"ApplicationCore", "Slate", "SlateCore"
		});
	}
}

#pragma once

#include "CoreMinimal.h"
#include "GaussianSplattingPointCloud.h"
#include "SplatPLYLoader.generated.h"

/** Result of a runtime PLY parse (standard 3DGS binary_little_endian 1.0 layout). */
USTRUCT()
struct DJI3DGS_UE_API FSplatPLYLoadResult
{
	GENERATED_BODY()

	UPROPERTY()
	TArray<FGaussianSplattingPoint> Points;

	UPROPERTY()
	int32 VertexCount = 0;

	UPROPERTY()
	int64 FileBytes = 0;

	UPROPERTY()
	float ParseMillis = 0.f;

	UPROPERTY()
	FString Error;

	UPROPERTY()
	FVector BoundsMin = FVector::ZeroVector;

	UPROPERTY()
	FVector BoundsMax = FVector::ZeroVector;

	UPROPERTY()
	FString Properties;
};

/**
 * Runtime loader for standard 3DGS PLY files (graphdeco-inria/gaussian-splatting layout).
 * Fields: x y z nx ny nz f_dc_0..2 [f_rest_0..44] opacity scale_0..2 rot_0..3
 *
 * Coordinate modes:
 *  - bUECoords = true  : values already in UE space/units (X fwd, Y right, Z up, cm)
 *  - bUECoords = false : values in COLMAP/graphdeco space/units (meters, Y down, Z fwd),
 *                        converted with the same mapping used by the Italink plugin: UE = (x, -z, -y) * 100
 */
class DJI3DGS_UE_API FSplatPLYLoader
{
public:
	static FSplatPLYLoadResult LoadFromFile(const FString& FilePath, bool bUECoords, float UniformScaleOverride = 0.f);
	static FSplatPLYLoadResult LoadFromMemory(const TArray<uint8>& Data, const FString& DebugName, bool bUECoords, float UniformScaleOverride = 0.f);
};

#pragma once

#include "CoreMinimal.h"
#include "GameFramework/Actor.h"
#include "SplatPLYLoader.h"
#include "SplatTestActor.generated.h"

class UCameraComponent;
class USceneCaptureComponent2D;
class UTextureRenderTarget2D;
class UNiagaraComponent;
class UGaussianSplattingPointCloud;

/**
 * Headless/benchmark viewer for a 3DGS PLY rendered through the ported Italink Niagara renderer.
 * Command line (all optional except -SplatPly):
 *   -SplatPly="C:/path/gaussians.ply"
 *   -SplatOutDir="C:/path/result_run"      output dir for metrics.json / screenshots / frames.csv
 *   -SplatUECoords=1|0                     PLY coordinates in UE space (default 1) or COLMAP meters (0)
 *   -SplatScale=1.0                        extra uniform scale applied to positions/scales
 *   -SplatWarmup=6.0 -SplatMeasure=8.0     seconds
 *   -SplatShots=2                          number of screenshots at the end of the measure window
 *   -SplatOrbitFrames=0                    if >0: capture an orbit animation of N PNG frames (for video)
 *   -SplatOrbitStep=0                      degrees per orbit frame (0 = 360/N)
 *   -SplatOrbitSpeed=12                    degrees / second
 *   -SplatSortIters=5                      CPU depth-sort benchmark iterations
 *   -SplatResX=1280 -SplatResY=720         screenshot resolution
 *   -SplatNoExit=1                         keep running after finishing (default exits)
 *   -SplatExposure=1.0                     exposure multiplier applied when saving HDR scene-color captures
 *   -SplatHDRCapture=1                     use SceneColorHDR + RGBA16f render target (default 1)
 *   -SplatNoNiagara=1                      skip the Niagara splat renderer (control-cube only test)
 *   -SplatDiagViews=1                      save extra captures at 2.2x/4x/8x/16x camera distance
 *   -SplatViewportShots=N                  save N main-viewport screenshots (works for debug points too)
 *   -SplatViewPresets=0                    disable the near/medium/top/orbit framing presets
 */
UCLASS()
class DJI3DGS_UE_API ASplatTestActor : public AActor
{
	GENERATED_BODY()

public:
	ASplatTestActor();

	virtual void BeginPlay() override;
	virtual void Tick(float DeltaSeconds) override;

	UPROPERTY(VisibleAnywhere, Category = "Splat")
	TObjectPtr<UCameraComponent> CameraComponent;

	UPROPERTY(VisibleAnywhere, Category = "Splat")
	TObjectPtr<USceneCaptureComponent2D> SceneCapture;

	UPROPERTY(VisibleAnywhere, Category = "Splat")
	TObjectPtr<UNiagaraComponent> SplatNiagara;

	UPROPERTY()
	TObjectPtr<UNiagaraSystem> NiagaraSystemRef;

protected:
	void ParseCommandLine();
	void LoadSplatScene();
	void SetupNiagaraRenderer();
	void SetupCapture();
	void DrawDebugSplatPoints();
	void UpdateCamera(float DeltaSeconds);
	void TakeScreenshots(int32 NumShots);
	void CaptureOrbitFrames();
	bool SaveCapturePng(const FString& Dir, const FString& FileName);
	void CaptureDiagonalViews();
	void RunCpuBenchmarks();
	void WriteMetrics(int32 ExitCode);
	void FinishRun(int32 ExitCode);
	void LogLine(const FString& InLine);

	UPROPERTY()
	TObjectPtr<USceneComponent> SceneRoot;

	UPROPERTY()
	TObjectPtr<UTextureRenderTarget2D> CaptureRT;

	UPROPERTY()
	TObjectPtr<UGaussianSplattingPointCloud> PointCloud;

	// --- configuration ---
	FString PlyPath;
	FString OutDir;
	bool bUECoords = true;
	float ScaleOverride = 0.f;
	float WarmupSeconds = 6.f;
	float MeasureSeconds = 8.f;
	int32 ShotCount = 2;
	int32 OrbitFrames = 0;
	int32 ViewportShots = 0;
	int32 ViewportShotsTaken = 0;
	float OrbitStepDeg = 0.f;
	float OrbitSpeedDeg = 12.f;
	int32 SortIterations = 5;
	int32 ResX = 1280;
	int32 ResY = 720;
	bool bExitAfterDone = true;
	float CameraDistanceOverride = 0.f;
	float ExposureScale = 1.0f;
	float SplatScaleMul = 1.0f;
	float SplatPosMul = 1.0f;
	bool bLinearHDRCapture = true;
	bool bNoNiagara = false;
	bool bDiagViews = false;
	bool bDebugPoints = false;
	bool bNiagaraLateActivated = false;

	// --- run state ---
	enum class EPhase : uint8 { Warmup, Measure, PostRun, ViewportShots, Done };
	EPhase Phase = EPhase::Warmup;
	double PhaseStartTime = 0.0;
	double RunStartTime = 0.0;
	double LoadStartTime = 0.0;
	double LoadMilliseconds = 0.0;
	double SetPointsMilliseconds = 0.0;
	double NiagaraSetupMilliseconds = 0.0;
	int32 SplatCount = 0;
	int64 PlyFileBytes = 0;
	int64 AssetBytes = 0;
	FVector BoundsMin = FVector::ZeroVector;
	FVector BoundsMax = FVector::ZeroVector;
	FVector BoundsCenter = FVector::ZeroVector;
	FVector RobustBoundsMin = FVector::ZeroVector;
	FVector RobustBoundsMax = FVector::ZeroVector;
	float BoundsRadius = 100.f;
	float CameraDistance = 300.f;
	float OrbitAngleDeg = 0.f;
	float ViewDistanceScale = 1.f;
	float ViewElevation = 0.35f;
	bool bViewPresets = true;
	bool bNiagaraAssetLoaded = false;
	bool bLoadFailed = false;
	FString LoadError;
	FString NiagaraAssetPath;

	TArray<float> FrameTimesMs;
	TArray<float> CpuFrontEndMs;
	TArray<float> CpuSortMs;
	int32 VisibleSplatCount = 0;
	int32 ScreenshotsSaved = 0;
	int32 OrbitFramesSaved = 0;
	double OrbitCaptureSeconds = 0.0;
	TArray<FString> ScreenshotFiles;
	FString RunId;
};

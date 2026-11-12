#include "SplatTestActor.h"

#include "Camera/CameraComponent.h"
#include "Components/SceneCaptureComponent2D.h"
#include "Engine/TextureRenderTarget2D.h"
#include "Engine/Engine.h"
#include "Engine/DirectionalLight.h"
#include "Engine/SkyLight.h"
#include "Engine/StaticMeshActor.h"
#include "Engine/StaticMesh.h"
#include "Components/StaticMeshComponent.h"
#include "Materials/MaterialInterface.h"
#include "UnrealClient.h"
#include "ImageUtils.h"
#include "RenderTargetPool.h"
#include "Components/TextRenderComponent.h"
#include "DrawDebugHelpers.h"
#include "Engine/TextRenderActor.h"
#include "Components/DirectionalLightComponent.h"
#include "Components/SkyLightComponent.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Kismet/KismetRenderingLibrary.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"
#include "Misc/Parse.h"
#include "Misc/CommandLine.h"
#include "HAL/FileManager.h"
#include "HAL/PlatformTime.h"
#include "HAL/PlatformMisc.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "NiagaraSystem.h"
#include "NiagaraTypes.h"
#include "NiagaraVariant.h"
#include "NiagaraDataInterfaceCurve.h"
#include "GaussianSplattingPointCloud.h"
#include "GaussianSplattingPointCloudDataInterface.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "Async/ParallelFor.h"

namespace
{
	FString GetCmdString(const TCHAR* Key)
	{
		FString Value;
		if (FParse::Value(FCommandLine::Get(), Key, Value))
		{
			Value.TrimStartAndEndInline();
			if (Value.Len() >= 2 && Value.StartsWith(TEXT("\"")) && Value.EndsWith(TEXT("\"")))
			{
				Value = Value.Mid(1, Value.Len() - 2);
			}
			Value = Value.Replace(TEXT("\\"), TEXT("/"));
			return Value;
		}
		return FString();
	}

	float GetCmdFloat(const TCHAR* Key, float DefaultValue)
	{
		float Value = DefaultValue;
		FParse::Value(FCommandLine::Get(), Key, Value);
		return Value;
	}

	int32 GetCmdInt(const TCHAR* Key, int32 DefaultValue)
	{
		int32 Value = DefaultValue;
		FParse::Value(FCommandLine::Get(), Key, Value);
		return Value;
	}
}

ASplatTestActor::ASplatTestActor()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;

	SceneRoot = CreateDefaultSubobject<USceneComponent>(TEXT("SceneRoot"));
	SetRootComponent(SceneRoot);

	CameraComponent = CreateDefaultSubobject<UCameraComponent>(TEXT("SplatCamera"));
	CameraComponent->SetupAttachment(SceneRoot);
	CameraComponent->SetFieldOfView(60.f);

	bNiagaraAssetLoaded = false;
	RunId = FDateTime::Now().ToString(TEXT("%Y%m%d_%H%M%S"));
}

void ASplatTestActor::LogLine(const FString& InLine)
{
	UE_LOG(LogTemp, Display, TEXT("[SPLAT] %s"), *InLine);
}

void ASplatTestActor::ParseCommandLine()
{
	PlyPath = GetCmdString(TEXT("SplatPly="));
	OutDir = GetCmdString(TEXT("SplatOutDir="));
	bUECoords = GetCmdInt(TEXT("SplatUECoords="), 1) != 0;
	ScaleOverride = GetCmdFloat(TEXT("SplatScale="), 0.f);
	WarmupSeconds = GetCmdFloat(TEXT("SplatWarmup="), 6.f);
	MeasureSeconds = GetCmdFloat(TEXT("SplatMeasure="), 8.f);
	ShotCount = GetCmdInt(TEXT("SplatShots="), 2);
	OrbitFrames = GetCmdInt(TEXT("SplatOrbitFrames="), 0);
	ViewportShots = GetCmdInt(TEXT("SplatViewportShots="), 0);
	bViewPresets = GetCmdInt(TEXT("SplatViewPresets="), 1) != 0;
	OrbitStepDeg = GetCmdFloat(TEXT("SplatOrbitStep="), 0.f);
	OrbitSpeedDeg = GetCmdFloat(TEXT("SplatOrbitSpeed="), 12.f);
	SortIterations = GetCmdInt(TEXT("SplatSortIters="), 5);
	ResX = GetCmdInt(TEXT("SplatResX="), 1280);
	ResY = GetCmdInt(TEXT("SplatResY="), 720);
	bExitAfterDone = GetCmdInt(TEXT("SplatNoExit="), 0) == 0;
	CameraDistanceOverride = GetCmdFloat(TEXT("SplatCameraDistance="), 0.f);
	ExposureScale = GetCmdFloat(TEXT("SplatExposure="), 1.0f);
	SplatScaleMul = GetCmdFloat(TEXT("SplatScaleMul="), 1.0f);
	SplatPosMul = GetCmdFloat(TEXT("SplatPosMul="), 1.0f);
	bLinearHDRCapture = GetCmdInt(TEXT("SplatHDRCapture="), 1) != 0;
	bNoNiagara = GetCmdInt(TEXT("SplatNoNiagara="), 0) != 0;
	bDiagViews = GetCmdInt(TEXT("SplatDiagViews="), 0) != 0;
	bDebugPoints = GetCmdInt(TEXT("SplatDebugPoints="), 0) != 0;

	if (OutDir.IsEmpty())
	{
		OutDir = FPaths::ProjectDir() / TEXT("Results") / RunId;
	}
	OutDir = FPaths::ConvertRelativePathToFull(OutDir);
	IFileManager::Get().MakeDirectory(*OutDir, true);

	LogLine(FString::Printf(TEXT("run=%s ply=%s out=%s ueCoords=%d scaleOverride=%.3f warmup=%.1f measure=%.1f shots=%d orbitFrames=%d res=%dx%d"),
		*RunId, *PlyPath, *OutDir, bUECoords ? 1 : 0, ScaleOverride, WarmupSeconds, MeasureSeconds, ShotCount, OrbitFrames, ResX, ResY));
}

void ASplatTestActor::BeginPlay()
{
	Super::BeginPlay();
	RunStartTime = FPlatformTime::Seconds();
	ParseCommandLine();
	PhaseStartTime = FPlatformTime::Seconds();

	if (PlyPath.IsEmpty() || !FPaths::FileExists(PlyPath))
	{
		LoadError = FString::Printf(TEXT("PLY file not found: %s"), *PlyPath);
		LogLine(FString::Printf(TEXT("ERROR %s"), *LoadError));
		bLoadFailed = true;
		FinishRun(2);
		return;
	}

	LoadSplatScene();
	if (bLoadFailed)
	{
		FinishRun(3);
		return;
	}
	SetupCapture();
	if (!bNoNiagara)
	{
		SetupNiagaraRenderer();
		if (bLoadFailed)
		{
			FinishRun(4);
			return;
		}
	}
	else
	{
		LogLine(TEXT("SplatNoNiagara=1: skipping Niagara splat renderer (control-cube only)"));
	}
	if (bDebugPoints)
	{
		DrawDebugSplatPoints();
	}

	// Spawn a light rig so the editor-style scene has something sensible even if the material is lit.
	if (UWorld* World = GetWorld())
	{
		FActorSpawnParameters SpawnParams;
		SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
		ADirectionalLight* Sun = World->SpawnActor<ADirectionalLight>(FVector(0, 0, 5000), FRotator(-60.f, 30.f, 0.f), SpawnParams);
		if (Sun && Sun->GetLightComponent())
		{
			Sun->GetLightComponent()->SetMobility(EComponentMobility::Movable);
			Sun->GetLightComponent()->SetIntensity(50000.0f);
		}
		ASkyLight* Sky = World->SpawnActor<ASkyLight>(FVector(0, 0, 2000), FRotator::ZeroRotator, SpawnParams);
		if (Sky && Sky->GetLightComponent())
		{
			Sky->GetLightComponent()->SetMobility(EComponentMobility::Movable);
			Sky->GetLightComponent()->SetIntensity(10.0f);
			Sky->GetLightComponent()->SetLowerHemisphereColor(FLinearColor(0.2f, 0.2f, 0.3f));
		}

		// Unlit text control: proves whether SceneCapture renders any unlit geometry at all.
		ATextRenderActor* TextActor = World->SpawnActor<ATextRenderActor>(BoundsCenter + FVector(0.f, 0.f, BoundsRadius * 0.6f), FRotator(0.f, 90.f, 0.f), SpawnParams);
		if (TextActor && TextActor->GetTextRender())
		{
			UTextRenderComponent* TextComp = TextActor->GetTextRender();
			TextComp->SetText(FText::FromString(TEXT("UE5 3DGS TEST")));
			TextComp->SetTextRenderColor(FColor(255, 80, 0));
			TextComp->SetWorldSize(150.f);
			TextComp->SetHorizontalAlignment(EHorizTextAligment::EHTA_Center);
			TextComp->SetVerticalAlignment(EVerticalTextAligment::EVRTA_TextCenter);
			LogLine(FString::Printf(TEXT("unlit text control spawned at %s"), *TextActor->GetActorLocation().ToString()));
		}

		// Debug control object: if this cube is invisible in the screenshot too, the problem is the
		// capture/camera/exposure path; if it is visible, the problem is the splat renderer.
		if (GetCmdInt(TEXT("SplatControlCube="), 1) != 0)
		{
			UStaticMesh* CubeMesh = LoadObject<UStaticMesh>(nullptr, TEXT("/Engine/BasicShapes/Cube.Cube"));
			if (CubeMesh)
			{
				AStaticMeshActor* CubeActor = World->SpawnActor<AStaticMeshActor>(FVector(BoundsCenter.X, BoundsCenter.Y, BoundsMax.Z + 300.f), FRotator(0.f, 30.f, 0.f), SpawnParams);
				if (CubeActor && CubeActor->GetStaticMeshComponent())
				{
					UStaticMeshComponent* CubeComp = CubeActor->GetStaticMeshComponent();
					CubeComp->SetMobility(EComponentMobility::Movable);
					CubeComp->SetStaticMesh(CubeMesh);
					CubeComp->SetWorldScale3D(FVector(3.f, 3.f, 3.f));
					if (UMaterialInterface* BasicMat = LoadObject<UMaterialInterface>(nullptr, TEXT("/Engine/BasicShapes/BasicShapeMaterial.BasicShapeMaterial")))
					{
						CubeComp->SetMaterial(0, BasicMat);
					}
					LogLine(FString::Printf(TEXT("control cube spawned at %s"), *CubeActor->GetActorLocation().ToString()));
				}
			}
			else
			{
				LogLine(TEXT("WARNING: control cube mesh /Engine/BasicShapes/Cube not found"));
			}
		}
	}

	UpdateCamera(0.f);
	LogLine(FString::Printf(TEXT("scene ready: splats=%d boundsCenter=%s radius=%.1f cameraDist=%.1f loadMs=%.1f setPointsMs=%.1f niagaraMs=%.1f"),
		SplatCount, *BoundsCenter.ToString(), BoundsRadius, CameraDistance, LoadMilliseconds, SetPointsMilliseconds, NiagaraSetupMilliseconds));
}

void ASplatTestActor::LoadSplatScene()
{
	LoadStartTime = FPlatformTime::Seconds();
	LogLine(FString::Printf(TEXT("loading PLY: %s (ueCoords=%d)"), *PlyPath, bUECoords ? 1 : 0));

	FSplatPLYLoadResult Result = FSplatPLYLoader::LoadFromFile(PlyPath, bUECoords, ScaleOverride);
	LoadMilliseconds = (FPlatformTime::Seconds() - LoadStartTime) * 1000.0;
	if (!Result.Error.IsEmpty())
	{
		LoadError = Result.Error;
		LogLine(FString::Printf(TEXT("ERROR PLY: %s"), *LoadError));
		bLoadFailed = true;
		return;
	}

	if (!FMath::IsNearlyEqual(SplatScaleMul, 1.0f) || !FMath::IsNearlyEqual(SplatPosMul, 1.0f))
	{
		for (FGaussianSplattingPoint& P : Result.Points)
		{
			P.Scale *= SplatScaleMul;
			P.Position *= SplatPosMul;
		}
		LogLine(FString::Printf(TEXT("renderer unit experiment: positionMul=%.4f scaleMul=%.4f"), SplatPosMul, SplatScaleMul));
	}
	SplatCount = Result.Points.Num();
	PlyFileBytes = Result.FileBytes;
	BoundsMin = Result.BoundsMin;
	BoundsMax = Result.BoundsMax;
	LogLine(FString::Printf(TEXT("parsed %d splats in %.1f ms (%.1f MB)"),
		SplatCount, LoadMilliseconds, PlyFileBytes / (1024.0 * 1024.0)));
	LogLine(FString::Printf(TEXT("parser bounds min=%s max=%s"), *Result.BoundsMin.ToString(), *Result.BoundsMax.ToString()));
	if (SplatCount > 0)
	{
		const FGaussianSplattingPoint& P0 = Result.Points[0];
		LogLine(FString::Printf(TEXT("point[0] pos=%s scale=%s color=%s"), *FVector(P0.Position).ToString(), *FVector(P0.Scale).ToString(), *P0.Color.ToString()));
		// Recompute bounds defensively from the point array (avoids relying on any single value).
		FVector Min(1.0e30, 1.0e30, 1.0e30);
		FVector Max(-1.0e30, -1.0e30, -1.0e30);
		for (const FGaussianSplattingPoint& P : Result.Points)
		{
			const FVector Pos(P.Position);
			if (!Pos.ContainsNaN())
			{
				Min = FVector::Min(Min, Pos);
				Max = FVector::Max(Max, Pos);
			}
		}
		if (Max.X >= Min.X && Max.Y >= Min.Y && Max.Z >= Min.Z)
		{
			BoundsMin = Min;
			BoundsMax = Max;
			LogLine(FString::Printf(TEXT("recomputed bounds min=%s max=%s"), *Min.ToString(), *Max.ToString()));
		}
	}

	const double SetPointsStart = FPlatformTime::Seconds();
	PointCloud = NewObject<UGaussianSplattingPointCloud>(this, TEXT("SplatPointCloud"));
	PointCloud->SetPoints(Result.Points, true);
	SetPointsMilliseconds = (FPlatformTime::Seconds() - SetPointsStart) * 1000.0;

	if (SplatCount > 0)
	{
		const int64 PointBytes = static_cast<int64>(SplatCount) * sizeof(FGaussianSplattingPoint);
		AssetBytes = PointBytes;
		LogLine(FString::Printf(TEXT("point cloud built in %.1f ms (cpu bytes ~%.1f MB)"), SetPointsMilliseconds, PointBytes / (1024.0 * 1024.0)));
	}

	// Robust framing: use 2%-98% quantiles so far-away outlier splats do not blow up the bounds.
	{
		TArray<float> Xs;
		TArray<float> Ys;
		TArray<float> Zs;
		Xs.Reserve(SplatCount);
		Ys.Reserve(SplatCount);
		Zs.Reserve(SplatCount);
		for (const FGaussianSplattingPoint& P : Result.Points)
		{
			Xs.Add(P.Position.X);
			Ys.Add(P.Position.Y);
			Zs.Add(P.Position.Z);
		}
		Xs.Sort();
		Ys.Sort();
		Zs.Sort();
		auto Quantile = [](const TArray<float>& Values, float T) {
			const int32 Index = FMath::Clamp(static_cast<int32>(T * (Values.Num() - 1)), 0, Values.Num() - 1);
			return Values[Index];
		};
		const float Low = 0.02f;
		const float High = 0.98f;
		RobustBoundsMin = FVector(Quantile(Xs, Low), Quantile(Ys, Low), Quantile(Zs, Low));
		RobustBoundsMax = FVector(Quantile(Xs, High), Quantile(Ys, High), Quantile(Zs, High));
		BoundsCenter = (RobustBoundsMin + RobustBoundsMax) * 0.5;
		BoundsRadius = FMath::Max(1.f, static_cast<float>((RobustBoundsMax - RobustBoundsMin).Size() * 0.5));
		LogLine(FString::Printf(TEXT("robust bounds (2%%-98%%): min=%s max=%s center=%s radius=%.1f"),
			*RobustBoundsMin.ToString(), *RobustBoundsMax.ToString(), *BoundsCenter.ToString(), BoundsRadius));
	}
	CameraDistance = CameraDistanceOverride > 0.f ? CameraDistanceOverride
		: (BoundsRadius > 4000.f ? FMath::Clamp(BoundsRadius * 2.2f, 12000.f, 16000.f) : FMath::Max(100.f, BoundsRadius * 2.2f));
}

void ASplatTestActor::SetupCapture()
{
	const double SetupStart = FPlatformTime::Seconds();
	CaptureRT = UKismetRenderingLibrary::CreateRenderTarget2D(this, ResX, ResY,
		bLinearHDRCapture ? ETextureRenderTargetFormat::RTF_RGBA16f : ETextureRenderTargetFormat::RTF_RGBA8,
		FLinearColor::Black, false);
	SceneCapture = NewObject<USceneCaptureComponent2D>(this, TEXT("SplatSceneCapture"));
	SceneCapture->SetupAttachment(SceneRoot);
	SceneCapture->RegisterComponent();
	SceneCapture->TextureTarget = CaptureRT;
	SceneCapture->CaptureSource = bLinearHDRCapture ? ESceneCaptureSource::SCS_SceneColorHDR : ESceneCaptureSource::SCS_FinalColorLDR;
	SceneCapture->bCaptureEveryFrame = false;
	SceneCapture->bCaptureOnMovement = false;
	SceneCapture->FOVAngle = 60.f;

	FPostProcessSettings& PP = SceneCapture->PostProcessSettings;
	PP.bOverride_AutoExposureMethod = true;
	PP.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
	PP.bOverride_AutoExposureBias = true;
	PP.AutoExposureBias = 1.f;

	LogLine(FString::Printf(TEXT("scene capture ready: %dx%d hdr=%d (%.1f ms)"),
		ResX, ResY, bLinearHDRCapture ? 1 : 0, (FPlatformTime::Seconds() - SetupStart) * 1000.0));
}

void ASplatTestActor::DrawDebugSplatPoints()
{
	if (!bDebugPoints || !PointCloud)
	{
		return;
	}
	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}
	const TArray<FGaussianSplattingPoint>& Points = PointCloud->GetPoints();
	const int32 MaxPoints = FMath::Min(Points.Num(), 300000);
	for (int32 i = 0; i < MaxPoints; ++i)
	{
		const FGaussianSplattingPoint& P = Points[i];
		// Interactive preview: small screen-space points so the campus outline stays readable
		// (the debug-draw point size is in screen pixels here; 25 px merged into a blob).
		const float Size = FMath::Clamp(FMath::Max3(P.Scale.X, P.Scale.Y, P.Scale.Z) * 0.25f, 1.2f, 3.0f);
		DrawDebugPoint(World, FVector(P.Position), Size, P.Color.ToFColor(true), true, -1.f, 0);
	}
	LogLine(FString::Printf(TEXT("debug splat points drawn: %d"), MaxPoints));
}

void ASplatTestActor::SetupNiagaraRenderer()
{
	const double SetupStart = FPlatformTime::Seconds();
	NiagaraAssetPath = TEXT("/GaussianSplattingForUnrealEngine/Niagara/NS_GaussianSplattingPointCloud.NS_GaussianSplattingPointCloud");
	UNiagaraSystem* NiagaraSystem = LoadObject<UNiagaraSystem>(nullptr, *NiagaraAssetPath);
	if (!NiagaraSystem)
	{
		LoadError = FString::Printf(TEXT("Cannot load Niagara asset: %s"), *NiagaraAssetPath);
		LogLine(FString::Printf(TEXT("ERROR %s"), *LoadError));
		bLoadFailed = true;
		return;
	}
	bNiagaraAssetLoaded = true;
	NiagaraSystemRef = NiagaraSystem;
	LogLine(FString::Printf(TEXT("niagara system: ready=%d emitters=%d needsCompile=%d"),
		NiagaraSystem->IsReadyToRun() ? 1 : 0, NiagaraSystem->GetNumEmitters(),
		NiagaraSystem->NeedsRequestCompile() ? 1 : 0));

	SplatNiagara = NewObject<UNiagaraComponent>(this, TEXT("SplatNiagara"));
	SplatNiagara->SetupAttachment(SceneRoot);
	SplatNiagara->RegisterComponent();
	SplatNiagara->SetAutoActivate(false);
	SplatNiagara->SetAsset(NiagaraSystem);
	SplatNiagara->SetSystemFixedBounds(FBox(BoundsMin, BoundsMax).ExpandBy(50.f));

	if (UNiagaraDataInterfaceGaussianSplattingPointCloud* ArrayDI =
		UNiagaraFunctionLibrary::GetDataInterface<UNiagaraDataInterfaceGaussianSplattingPointCloud>(SplatNiagara, "PointCloud"))
	{
		ArrayDI->SetPointCloud(PointCloud);
		UNiagaraDataInterfaceGaussianSplattingPointCloud* VariantDI =
			CastChecked<UNiagaraDataInterfaceGaussianSplattingPointCloud>(DuplicateObject(ArrayDI, SplatNiagara));
		VariantDI->SetPointCloud(PointCloud);
		SplatNiagara->SetParameterOverride(
			FNiagaraVariableBase(FNiagaraTypeDefinition(UNiagaraDataInterfaceGaussianSplattingPointCloud::StaticClass()), "PointCloud"),
			FNiagaraVariant(VariantDI));
		LogLine(TEXT("PointCloud data interface overridden"));
	}
	else
	{
		LogLine(TEXT("WARNING: PointCloud data interface not found on Niagara component"));
	}

	if (UNiagaraDataInterfaceCurve* CurveDI = UNiagaraFunctionLibrary::GetDataInterface<UNiagaraDataInterfaceCurve>(SplatNiagara, "FeatureCurve"))
	{
		CurveDI->Curve = PointCloud->CalcFeatureCurve();
		CurveDI->UpdateLUT();
		UNiagaraDataInterfaceCurve* VariantDI = CastChecked<UNiagaraDataInterfaceCurve>(DuplicateObject(CurveDI, SplatNiagara));
		VariantDI->Curve = CurveDI->Curve;
		SplatNiagara->SetParameterOverride(
			FNiagaraVariableBase(FNiagaraTypeDefinition(UNiagaraDataInterfaceCurve::StaticClass()), "FeatureCurve"),
			FNiagaraVariant(VariantDI));
	}

	// The offscreen capture target is created in SetupCapture() so it also works with -SplatNoNiagara=1.

	// Force a deterministic manual exposure so dark scenes are not crushed to black by auto exposure.
	auto ApplyManualExposure = [](FPostProcessSettings& PP)
	{
		PP.bOverride_AutoExposureMethod = true;
		PP.AutoExposureMethod = EAutoExposureMethod::AEM_Manual;
		PP.bOverride_AutoExposureMinBrightness = true;
		PP.AutoExposureMinBrightness = 1.f;
		PP.bOverride_AutoExposureMaxBrightness = true;
		PP.AutoExposureMaxBrightness = 1.f;
		PP.bOverride_AutoExposureBias = true;
		PP.AutoExposureBias = 1.f;
	};
	if (CameraComponent)
	{
		ApplyManualExposure(CameraComponent->PostProcessSettings);
	}

	SplatNiagara->SetRenderingEnabled(true);
	SplatNiagara->Activate(true);
	LogLine(FString::Printf(TEXT("niagara component: active=%d rendering=%d instanceCtrl=%d fixedBounds=%s"),
		SplatNiagara->IsActive() ? 1 : 0, SplatNiagara->GetRenderingEnabled() ? 1 : 0,
		SplatNiagara->GetSystemInstanceController().IsValid() ? 1 : 0,
		*SplatNiagara->GetSystemFixedBounds().ToString()));
	NiagaraSetupMilliseconds = (FPlatformTime::Seconds() - SetupStart) * 1000.0;
}

void ASplatTestActor::UpdateCamera(float DeltaSeconds)
{
	OrbitAngleDeg += OrbitSpeedDeg * DeltaSeconds;
	const float AngleRad = FMath::DegreesToRadians(OrbitAngleDeg);
	const FVector CamLoc = BoundsCenter
		+ FVector(FMath::Cos(AngleRad), FMath::Sin(AngleRad), 0.f) * (CameraDistance * ViewDistanceScale)
		+ FVector(0.f, 0.f, CameraDistance * ViewElevation);
	const FRotator CamRot = (BoundsCenter - CamLoc).Rotation();
	SetActorLocationAndRotation(CamLoc, CamRot);
}

void ASplatTestActor::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	const double Now = FPlatformTime::Seconds();
	switch (Phase)
	{
	case EPhase::Warmup:
		if (!bNiagaraLateActivated && SplatNiagara && NiagaraSystemRef && NiagaraSystemRef->IsReadyToRun())
		{
			SplatNiagara->Activate(true);
			SplatNiagara->ReinitializeSystem();
			bNiagaraLateActivated = true;
			LogLine(FString::Printf(TEXT("niagara late activation after compile: ready=1 active=%d instanceCtrl=%d"),
				SplatNiagara->IsActive() ? 1 : 0, SplatNiagara->GetSystemInstanceController().IsValid() ? 1 : 0));
		}
		UpdateCamera(DeltaSeconds);
		if (Now - PhaseStartTime >= WarmupSeconds)
		{
			Phase = EPhase::Measure;
			PhaseStartTime = Now;
			FrameTimesMs.Reset();
			if (NiagaraSystemRef)
			{
				LogLine(FString::Printf(TEXT("niagara state at measure start: ready=%d compActive=%d compRendering=%d"),
					NiagaraSystemRef->IsReadyToRun() ? 1 : 0,
					(SplatNiagara && SplatNiagara->IsActive()) ? 1 : 0,
					(SplatNiagara && SplatNiagara->GetRenderingEnabled()) ? 1 : 0));
			}
			const FString ViewportShot = OutDir / TEXT("viewport_measure_start.png");
			FScreenshotRequest::RequestScreenshot(ViewportShot, false, false);
			LogLine(FString::Printf(TEXT("warmup complete, measuring for %.1fs; requested viewport screenshot %s"),
				MeasureSeconds, *ViewportShot));
		}
		break;
	case EPhase::Measure:
		UpdateCamera(DeltaSeconds);
		FrameTimesMs.Add(DeltaSeconds * 1000.f);
		if (Now - PhaseStartTime >= MeasureSeconds)
		{
			Phase = EPhase::PostRun;
			LogLine(FString::Printf(TEXT("measure complete, %d frames"), FrameTimesMs.Num()));
		}
		break;
	case EPhase::PostRun:
		// one heavy frame: screenshots + CPU benchmarks
		TakeScreenshots(ShotCount);
		CaptureDiagonalViews();
		CaptureOrbitFrames();
		RunCpuBenchmarks();
		if (ViewportShots > 0)
		{
			Phase = EPhase::ViewportShots;
		}
		else
		{
			Phase = EPhase::Done;
			WriteMetrics(0);
			FinishRun(0);
		}
		break;
	case EPhase::ViewportShots:
		if (ViewportShotsTaken < ViewportShots)
		{
			if (bViewPresets && ViewportShots >= 4)
			{
				// near / medium / top-down / orbit-frame presets
				switch (ViewportShotsTaken)
				{
				case 0: OrbitAngleDeg = 0.f;   ViewDistanceScale = 0.9f;  ViewElevation = 0.15f; break;
				case 1: OrbitAngleDeg = 120.f; ViewDistanceScale = 1.0f;  ViewElevation = 0.35f; break;
				case 2: OrbitAngleDeg = 240.f; ViewDistanceScale = 0.75f; ViewElevation = 1.6f;  break;
				default: OrbitAngleDeg = 45.f; ViewDistanceScale = 1.0f;  ViewElevation = 0.35f; break;
				}
			}
			else
			{
				OrbitAngleDeg = 360.f * static_cast<float>(ViewportShotsTaken) / static_cast<float>(ViewportShots);
			}
			UpdateCamera(0.f);
			const FString ShotDir = OutDir / TEXT("screenshots");
			IFileManager::Get().MakeDirectory(*ShotDir, true);
			const FString FileName = FString::Printf(TEXT("view_%02d.png"), ViewportShotsTaken);
			FScreenshotRequest::RequestScreenshot(ShotDir / FileName, false, false);
			LogLine(FString::Printf(TEXT("requested viewport shot %s at orbit %.1f deg"), *FileName, OrbitAngleDeg));
			++ViewportShotsTaken;
		}
		else
		{
			Phase = EPhase::Done;
			WriteMetrics(0);
			FinishRun(0);
		}
		break;
	default:
		break;
	}
}

bool ASplatTestActor::SaveCapturePng(const FString& Dir, const FString& FileName)
{
	if (!CaptureRT)
	{
		return false;
	}
	FTextureRenderTargetResource* Resource = CaptureRT->GameThread_GetRenderTargetResource();
	if (!Resource)
	{
		LogLine(TEXT("ERROR: no render target resource for capture"));
		return false;
	}
	FlushRenderingCommands();
	TArray<FLinearColor> Pixels;
	if (!Resource->ReadLinearColorPixels(Pixels) || Pixels.Num() == 0)
	{
		LogLine(TEXT("ERROR: ReadLinearColorPixels failed"));
		return false;
	}
	const int32 W = CaptureRT->SizeX;
	const int32 H = CaptureRT->SizeY;
	if (Pixels.Num() != W * H)
	{
		LogLine(FString::Printf(TEXT("ERROR: pixel count mismatch %d vs %d"), Pixels.Num(), W * H));
		return false;
	}

	TArray<FColor> Colors;
	Colors.SetNumUninitialized(W * H);
	float MaxL = 0.f;
	double SumL = 0.0;
	int32 NonZero = 0;
	for (int32 i = 0; i < Pixels.Num(); ++i)
	{
		FLinearColor C = Pixels[i];
		C.R = FMath::Max(0.f, C.R * ExposureScale);
		C.G = FMath::Max(0.f, C.G * ExposureScale);
		C.B = FMath::Max(0.f, C.B * ExposureScale);
		MaxL = FMath::Max(MaxL, FMath::Max3(C.R, C.G, C.B));
		SumL += C.R + C.G + C.B;
		if (C.R + C.G + C.B > 1.e-5f)
		{
			++NonZero;
		}
		// Reinhard tonemap then sRGB encode, so very dim HDR scene color is still readable.
		C.R = C.R / (1.f + C.R);
		C.G = C.G / (1.f + C.G);
		C.B = C.B / (1.f + C.B);
		FColor OutColor = C.ToFColor(true);
		OutColor.A = 255;
		Colors[i] = OutColor;
	}

	TArray<uint8, FDefaultAllocator64> PngData;
	FImageUtils::PNGCompressImageArray(W, H, Colors, PngData);
	const FString FullPath = Dir / FileName;
	const bool bSaved = FFileHelper::SaveArrayToFile(PngData, *FullPath);
	LogLine(FString::Printf(TEXT("capture %s saved=%d linearMax=%.5f linearMean=%.6f nonzeroPx=%d/%d"),
		*FileName, bSaved ? 1 : 0, MaxL, SumL / FMath::Max(1, W * H * 3), NonZero, W * H));
	return bSaved;
}

void ASplatTestActor::TakeScreenshots(int32 NumShots)
{
	if (!SceneCapture || !CaptureRT)
	{
		LogLine(TEXT("WARNING: no scene capture, skipping screenshots"));
		return;
	}
	const FString ShotDir = OutDir / TEXT("screenshots");
	IFileManager::Get().MakeDirectory(*ShotDir, true);
	const float StartAngle = OrbitAngleDeg;
	for (int32 ShotIndex = 0; ShotIndex < NumShots; ++ShotIndex)
	{
		OrbitAngleDeg = StartAngle + 360.f * static_cast<float>(ShotIndex) / FMath::Max(1, NumShots);
		UpdateCamera(0.f);
		FlushRenderingCommands();
		SceneCapture->CaptureScene();
		FlushRenderingCommands();
		const FString FileName = FString::Printf(TEXT("orbit_%03d.png"), ShotIndex);
		SaveCapturePng(ShotDir, FileName);
		const FString FullPath = ShotDir / FileName;
		if (FPaths::FileExists(FullPath))
		{
			ScreenshotFiles.Add(FString::Printf(TEXT("screenshots/%s"), *FileName));
			ScreenshotsSaved++;
		}
		LogLine(FString::Printf(TEXT("screenshot %s"), *FullPath));
	}
}

void ASplatTestActor::CaptureDiagonalViews()
{
	if (!bDiagViews || !SceneCapture || !CaptureRT)
	{
		return;
	}
	const FString DiagDir = OutDir / TEXT("diag");
	IFileManager::Get().MakeDirectory(*DiagDir, true);
	const float SavedDistance = CameraDistance;
	const float BaseDistance = CameraDistance;
	const float Scales[] = { 1.f, 2.f, 4.f, 8.f };
	for (float S : Scales)
	{
		CameraDistance = BaseDistance * S;
		OrbitAngleDeg = 30.f;
		UpdateCamera(0.f);
		SceneCapture->CaptureScene();
		FlushRenderingCommands();
		const FString FileName = FString::Printf(TEXT("diag_dist_%.1fx.png"), S);
		SaveCapturePng(DiagDir, FileName);
		LogLine(FString::Printf(TEXT("diag view saved %s (cameraDistance=%.1f)"), *FileName, CameraDistance));
	}
	CameraDistance = SavedDistance;
	OrbitAngleDeg = 0.f;
	UpdateCamera(0.f);
}

void ASplatTestActor::CaptureOrbitFrames()
{
	if (OrbitFrames <= 0 || !SceneCapture || !CaptureRT)
	{
		return;
	}
	const FString OrbitDir = OutDir / TEXT("orbit");
	IFileManager::Get().MakeDirectory(*OrbitDir, true);
	const float Step = OrbitStepDeg > 0.f ? OrbitStepDeg : 360.f / static_cast<float>(FMath::Max(1, OrbitFrames));
	const double OrbitStart = FPlatformTime::Seconds();
	for (int32 FrameIndex = 0; FrameIndex < OrbitFrames; ++FrameIndex)
	{
		OrbitAngleDeg = Step * static_cast<float>(FrameIndex);
		UpdateCamera(0.f);
		SceneCapture->CaptureScene();
		FlushRenderingCommands();
		const FString FileName = FString::Printf(TEXT("orbit_%04d.png"), FrameIndex);
		SaveCapturePng(OrbitDir, FileName);
		if (FPaths::FileExists(OrbitDir / FileName))
		{
			OrbitFramesSaved++;
		}
	}
	OrbitCaptureSeconds = FPlatformTime::Seconds() - OrbitStart;
	LogLine(FString::Printf(TEXT("orbit frames: %d saved in %.1fs (step %.2f deg, %.1f fps capture)"),
		OrbitFramesSaved, OrbitCaptureSeconds, Step, OrbitFramesSaved > 0 ? OrbitFramesSaved / FMath::Max(0.001, OrbitCaptureSeconds) : 0.0));
}

void ASplatTestActor::RunCpuBenchmarks()
{
	if (!PointCloud)
	{
		return;
	}
	const TArray<FGaussianSplattingPoint>& Points = PointCloud->GetPoints();
	const int32 Num = Points.Num();
	if (Num == 0)
	{
		return;
	}

	APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0);
	FVector CamLoc = GetActorLocation();
	FRotator CamRot = GetActorRotation();
	if (PC)
	{
		PC->GetPlayerViewPoint(CamLoc, CamRot);
	}
	const FVector Forward = CamRot.Vector();
	const float Focal = (ResY * 0.5f) / FMath::Tan(FMath::DegreesToRadians(60.f * 0.5f));

	TArray<int32> Indices;
	TArray<float> Depths;
	Indices.SetNumUninitialized(Num);
	Depths.SetNumUninitialized(Num);

	const int32 Iterations = FMath::Max(1, SortIterations);
	VisibleSplatCount = 0;
	for (int32 Iter = 0; Iter < Iterations; ++Iter)
	{
		const double FrontStart = FPlatformTime::Seconds();
		int32 Visible = 0;
		for (int32 i = 0; i < Num; ++i)
		{
			const FVector P(Points[i].Position);
			const FVector Delta = P - CamLoc;
			const float Depth = static_cast<float>(Delta.Dot(Forward));
			Depths[i] = Depth;
			Indices[i] = i;
			if (Depth > 1.f)
			{
				const float MaxScale = FMath::Max3(Points[i].Scale.X, Points[i].Scale.Y, Points[i].Scale.Z);
				const float ScreenRadius = MaxScale / Depth * Focal;
				if (ScreenRadius > 0.5f)
				{
					++Visible;
				}
			}
		}
		const double FrontEndMs = (FPlatformTime::Seconds() - FrontStart) * 1000.0;

		const double SortStart = FPlatformTime::Seconds();
		Indices.Sort([&Depths](int32 A, int32 B) { return Depths[A] < Depths[B]; });
		const double SortMs = (FPlatformTime::Seconds() - SortStart) * 1000.0;

		CpuFrontEndMs.Add(static_cast<float>(FrontEndMs));
		CpuSortMs.Add(static_cast<float>(SortMs));
		VisibleSplatCount = Visible;
	}
	LogLine(FString::Printf(TEXT("cpu bench: %d iters, frontEnd=%.1fms sort=%.1fms visible=%d"),
		Iterations, CpuFrontEndMs.IsEmpty() ? 0.f : CpuFrontEndMs.Last(), CpuSortMs.IsEmpty() ? 0.f : CpuSortMs.Last(), VisibleSplatCount));
}

void ASplatTestActor::WriteMetrics(int32 ExitCode)
{
	auto Avg = [](const TArray<float>& Values) {
		if (Values.IsEmpty()) return 0.f;
		double Sum = 0.0;
		for (float V : Values) Sum += V;
		return static_cast<float>(Sum / Values.Num());
	};
	auto SortedPercentile = [](TArray<float> Values, float Percentile) {
		if (Values.IsEmpty()) return 0.f;
		Values.Sort();
		const int32 Index = FMath::Clamp(static_cast<int32>(Percentile * (Values.Num() - 1)), 0, Values.Num() - 1);
		return Values[Index];
	};

	const float AvgFrameMs = Avg(FrameTimesMs);
	const float AvgFps = AvgFrameMs > 0.f ? 1000.f / AvgFrameMs : 0.f;

	TSharedPtr<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("schema"), TEXT("dji_ue5_3dgs/ue5_metrics/v1"));
	Root->SetNumberField(TEXT("exitCode"), ExitCode);

	TSharedPtr<FJsonObject> Run = MakeShared<FJsonObject>();
	Run->SetStringField(TEXT("runId"), RunId);
	Run->SetStringField(TEXT("timestampUtc"), FDateTime::UtcNow().ToIso8601());
	Run->SetStringField(TEXT("project"), TEXT("DJI3DGS_UE"));
	Run->SetStringField(TEXT("engine"), TEXT("UE 5.8.4"));
	Run->SetStringField(TEXT("rendererPlugin"), TEXT("GaussianSplattingForUnrealEngine (Italink, MIT, ported to 5.8)"));
	Run->SetStringField(TEXT("gpu"), TEXT("RTX 5060 Laptop 8GB"));
	Root->SetObjectField(TEXT("run"), Run);

	TSharedPtr<FJsonObject> Ply = MakeShared<FJsonObject>();
	Ply->SetStringField(TEXT("path"), PlyPath);
	Ply->SetNumberField(TEXT("splatCount"), SplatCount);
	Ply->SetNumberField(TEXT("fileBytes"), static_cast<double>(PlyFileBytes));
	Ply->SetNumberField(TEXT("cpuPointBytes"), static_cast<double>(AssetBytes));
	Ply->SetNumberField(TEXT("parseMs"), LoadMilliseconds);
	Ply->SetNumberField(TEXT("setPointsMs"), SetPointsMilliseconds);
	Ply->SetBoolField(TEXT("ueCoords"), bUECoords);
	Ply->SetBoolField(TEXT("shDegree0Only"), true);
	Ply->SetStringField(TEXT("error"), LoadError);
	Root->SetObjectField(TEXT("ply"), Ply);

	TSharedPtr<FJsonObject> Scene = MakeShared<FJsonObject>();
	Scene->SetNumberField(TEXT("boundsRadius"), BoundsRadius);
	Scene->SetNumberField(TEXT("cameraDistance"), CameraDistance);
	Scene->SetNumberField(TEXT("robustRadius"), BoundsRadius);
	Scene->SetNumberField(TEXT("orbitSpeedDegPerSec"), OrbitSpeedDeg);
	Scene->SetNumberField(TEXT("niagaraSetupMs"), NiagaraSetupMilliseconds);
	Scene->SetBoolField(TEXT("niagaraAssetLoaded"), bNiagaraAssetLoaded);
	Scene->SetBoolField(TEXT("niagaraLateActivated"), bNiagaraLateActivated);
	Scene->SetStringField(TEXT("niagaraAsset"), NiagaraAssetPath);
	Root->SetObjectField(TEXT("scene"), Scene);

	TSharedPtr<FJsonObject> Measure = MakeShared<FJsonObject>();
	Measure->SetNumberField(TEXT("warmupSec"), WarmupSeconds);
	Measure->SetNumberField(TEXT("measureSec"), MeasureSeconds);
	Measure->SetNumberField(TEXT("frames"), FrameTimesMs.Num());
	Measure->SetNumberField(TEXT("avgFps"), AvgFps);
	Measure->SetNumberField(TEXT("avgFrameMs"), AvgFrameMs);
	Measure->SetNumberField(TEXT("p1FrameMs"), SortedPercentile(FrameTimesMs, 0.01f));
	Measure->SetNumberField(TEXT("p99FrameMs"), SortedPercentile(FrameTimesMs, 0.99f));
	Root->SetObjectField(TEXT("measure"), Measure);

	TSharedPtr<FJsonObject> Cpu = MakeShared<FJsonObject>();
	Cpu->SetNumberField(TEXT("frontEndMsAvg"), Avg(CpuFrontEndMs));
	Cpu->SetNumberField(TEXT("depthSortMsAvg"), Avg(CpuSortMs));
	Cpu->SetNumberField(TEXT("depthSortIterations"), CpuSortMs.Num());
	Cpu->SetNumberField(TEXT("visibleSplatsAfterScreenSizeCull"), VisibleSplatCount);
	Cpu->SetStringField(TEXT("note"), TEXT("CPU single-thread benchmark: transform+projection and index depth-sort, mirrors a CPU splat sort pass; Niagara renderer itself sorts on GPU (if enabled by the system)."));
	Root->SetObjectField(TEXT("cpu"), Cpu);

	TArray<TSharedPtr<FJsonValue>> Shots;
	for (const FString& File : ScreenshotFiles)
	{
		Shots.Add(MakeShared<FJsonValueString>(File));
	}
	Root->SetArrayField(TEXT("screenshots"), Shots);

	TSharedPtr<FJsonObject> Orbit = MakeShared<FJsonObject>();
	Orbit->SetNumberField(TEXT("framesRequested"), OrbitFrames);
	Orbit->SetNumberField(TEXT("framesSaved"), OrbitFramesSaved);
	Orbit->SetNumberField(TEXT("stepDeg"), OrbitFrames > 0 ? (OrbitStepDeg > 0.f ? OrbitStepDeg : 360.f / OrbitFrames) : 0.f);
	Orbit->SetNumberField(TEXT("captureSeconds"), OrbitCaptureSeconds);
	Orbit->SetStringField(TEXT("dir"), TEXT("orbit"));
	Root->SetObjectField(TEXT("orbit"), Orbit);

	const FString MetricsPath = OutDir / TEXT("metrics.json");
	FString OutJson;
	const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&OutJson);
	FJsonSerializer::Serialize(Root.ToSharedRef(), Writer);
	FFileHelper::SaveStringToFile(OutJson, *MetricsPath);

	// frame time csv as raw evidence
	FString Csv = TEXT("frame,delta_ms\n");
	for (int32 i = 0; i < FrameTimesMs.Num(); ++i)
	{
		Csv += FString::Printf(TEXT("%d,%.4f\n"), i, FrameTimesMs[i]);
	}
	FFileHelper::SaveStringToFile(Csv, *(OutDir / TEXT("frames.csv")));

	LogLine(FString::Printf(TEXT("metrics written: %s (avgFps=%.2f avgFrameMs=%.2f splats=%d)"), *MetricsPath, AvgFps, AvgFrameMs, SplatCount));
}

void ASplatTestActor::FinishRun(int32 ExitCode)
{
	Phase = EPhase::Done;
	if (bExitAfterDone)
	{
		LogLine(FString::Printf(TEXT("requesting exit code=%d"), ExitCode));
		FGenericPlatformMisc::RequestExitWithStatus(false, static_cast<uint8>(ExitCode));
	}
}

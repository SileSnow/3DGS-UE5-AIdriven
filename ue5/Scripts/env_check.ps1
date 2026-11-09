<#
.SYNOPSIS
    Pre-flight check for the UE 5.8 3DGS integration: engine, junction, project, plugin assets, built DLLs, GPU.
#>
$ErrorActionPreference = 'Continue'
Write-Host '=== UE 5.8 install ==='
$ue = 'C:/Program Files/Epic Games/UE_5.8'
Write-Host "engine root : $ue ($(Test-Path $ue))"
Write-Host "editor exe  : $(Test-Path "$ue/Engine/Binaries/Win64/UnrealEditor.exe")"
$version = Get-Content "$ue/Engine/Build/Build.version" -Raw | ConvertFrom-Json
Write-Host ("version     : " + $version.MajorVersion + "." + $version.MinorVersion + "." + $version.PatchVersion + " (" + $version.BranchName + ")")

Write-Host '=== ASCII junction ==='
Write-Host "C:\UEW      : $(Test-Path 'C:/UEW')"
Write-Host "uproject    : $(Test-Path 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/DJI3DGS_UE.uproject')"

Write-Host '=== built binaries ==='
Get-ChildItem 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/Binaries/Win64' -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  " + $_.Name + "  " + $_.Length + " B  " + $_.LastWriteTime) }
Get-ChildItem 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/Plugins/GaussianSplattingForUnrealEngine/Binaries/Win64' -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  " + $_.Name + "  " + $_.Length + " B  " + $_.LastWriteTime) }

Write-Host '=== plugin assets ==='
Get-ChildItem 'C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/Plugins/GaussianSplattingForUnrealEngine/Content' -Recurse -File -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  " + $_.FullName.Replace('C:/UEW/dji_ue5_3dgs/ue5/DJI3DGS_UE/Plugins/GaussianSplattingForUnrealEngine/', '')) }

Write-Host '=== test data ==='
Get-ChildItem 'C:/UEW/dji_ue5_3dgs/ue5/test_data' -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  " + $_.Name + "  " + [math]::Round($_.Length / 1MB, 1) + " MB") }

Write-Host '=== GPU ==='
& nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu --format=csv

Write-Host '=== running Unreal processes ==='
Get-Process -Name 'UnrealEditor', 'UnrealEditor-Cmd' -ErrorAction SilentlyContinue |
    ForEach-Object { Write-Host ("  pid=" + $_.Id + " " + $_.ProcessName + " mem=" + [math]::Round($_.WorkingSet64 / 1MB) + "MB started=" + $_.StartTime) }

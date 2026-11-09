#include "SplatPLYLoader.h"
#include "HAL/FileManager.h"
#include "Misc/FileHelper.h"

namespace
{
	constexpr float SH_C0 = 0.28209479177387814f;

	FORCEINLINE FLinearColor SplatSRGBToLinear(const FVector3f& In)
	{
		auto Conv = [](float C) { return C <= 0.04045f ? C / 12.92f : FMath::Pow((C + 0.055f) / 1.055f, 2.4f); };
		return FLinearColor(Conv(In.X), Conv(In.Y), Conv(In.Z), 1.f);
	}

	struct FHeaderParse
	{
		bool bValid = false;
		int32 VertexCount = 0;
		int64 DataOffset = 0;
		TArray<FString> VertexProperties;
		FString Error;
	};

	FHeaderParse ParseHeader(const TArray<uint8>& Data)
	{
		FHeaderParse Out;
		int64 Offset = 0;
		bool bInVertexElement = false;
		bool bSawPly = false;

		while (Offset < Data.Num())
		{
			const int64 LineStart = Offset;
			int64 LineEnd = LineStart;
			while (LineEnd < Data.Num() && Data[LineEnd] != '\n')
			{
				++LineEnd;
			}
			if (LineEnd >= Data.Num())
			{
				Out.Error = TEXT("Unexpected end of header");
				return Out;
			}
			int64 EffectiveEnd = LineEnd;
			if (EffectiveEnd > LineStart && Data[EffectiveEnd - 1] == '\r')
			{
				--EffectiveEnd;
			}
			const FString Line = FString(static_cast<int32>(EffectiveEnd - LineStart), reinterpret_cast<const ANSICHAR*>(Data.GetData() + LineStart));
			Offset = LineEnd + 1;

			if (Line == TEXT("end_header"))
			{
				Out.bValid = true;
				Out.DataOffset = Offset;
				return Out;
			}
			if (!bSawPly)
			{
				if (Line != TEXT("ply"))
				{
					Out.Error = TEXT("Not a PLY file (missing magic header)");
					return Out;
				}
				bSawPly = true;
				continue;
			}
			if (Line.StartsWith(TEXT("format ")))
			{
				if (Line != TEXT("format binary_little_endian 1.0"))
				{
					Out.Error = FString::Printf(TEXT("Unsupported PLY format line: %s"), *Line);
					return Out;
				}
				continue;
			}
			if (Line.StartsWith(TEXT("comment")) || Line.StartsWith(TEXT("obj_info")))
			{
				continue;
			}
			if (Line.StartsWith(TEXT("element ")))
			{
				TArray<FString> Tokens;
				Line.ParseIntoArrayWS(Tokens);
				if (Tokens.Num() >= 3)
				{
					bInVertexElement = Tokens[1].Equals(TEXT("vertex"));
					if (bInVertexElement)
					{
						Out.VertexCount = FCString::Atoi(*Tokens[2]);
					}
				}
				continue;
			}
			if (Line.StartsWith(TEXT("property ")))
			{
				TArray<FString> Tokens;
				Line.ParseIntoArrayWS(Tokens);
				if (Tokens.Num() >= 3 && bInVertexElement)
				{
					const FString& Type = Tokens[1];
					if (Type != TEXT("float") && Type != TEXT("float32"))
					{
						Out.Error = FString::Printf(TEXT("Unsupported vertex property type '%s' for '%s' (only float32 supported)"), *Type, *Tokens[2]);
						return Out;
					}
					Out.VertexProperties.Add(Tokens[2]);
				}
				continue;
			}
		}

		if (Out.Error.IsEmpty())
		{
			Out.Error = TEXT("Unexpected end of header (no end_header)");
		}
		return Out;
	}

	/** Reads the Index-th float32 inside one vertex row (fields are 4-byte packed). */
	FORCEINLINE float ReadFloat(const uint8* Row, int32 Index)
	{
		float Value = 0.f;
		FMemory::Memcpy(&Value, Row + static_cast<int64>(Index) * sizeof(float), sizeof(float));
		return Value;
	}
}

FSplatPLYLoadResult FSplatPLYLoader::LoadFromFile(const FString& FilePath, bool bUECoords, float UniformScaleOverride)
{
	TArray<uint8> Data;
	const double Start = FPlatformTime::Seconds();
	if (!FFileHelper::LoadFileToArray(Data, *FilePath))
	{
		FSplatPLYLoadResult Result;
		Result.Error = FString::Printf(TEXT("Cannot open PLY file: %s"), *FilePath);
		return Result;
	}
	FSplatPLYLoadResult Result = LoadFromMemory(Data, FilePath, bUECoords, UniformScaleOverride);
	Result.FileBytes = Data.Num();
	Result.ParseMillis = static_cast<float>((FPlatformTime::Seconds() - Start) * 1000.0);
	return Result;
}

FSplatPLYLoadResult FSplatPLYLoader::LoadFromMemory(const TArray<uint8>& Data, const FString& DebugName, bool bUECoords, float UniformScaleOverride)
{
	FSplatPLYLoadResult Result;
	Result.FileBytes = Data.Num();

	const FHeaderParse Header = ParseHeader(Data);
	if (!Header.bValid)
	{
		Result.Error = FString::Printf(TEXT("PLY header error (%s): %s"), *DebugName, *Header.Error);
		return Result;
	}
	Result.VertexCount = Header.VertexCount;
	Result.Properties = FString::Join(Header.VertexProperties, TEXT(","));
	if (Header.VertexCount <= 0)
	{
		Result.Error = FString::Printf(TEXT("PLY has no vertices (%s)"), *DebugName);
		return Result;
	}
	if (Header.VertexCount > 100 * 1024 * 1024)
	{
		Result.Error = FString::Printf(TEXT("PLY vertex count too large: %d"), Header.VertexCount);
		return Result;
	}

	const TArray<FString>& Props = Header.VertexProperties;
	auto IndexOf = [&Props](const TCHAR* Name) { return Props.IndexOfByKey(FString(Name)); };
	const int32 Ix = IndexOf(TEXT("x")), Iy = IndexOf(TEXT("y")), Iz = IndexOf(TEXT("z"));
	const int32 Is0 = IndexOf(TEXT("scale_0")), Is1 = IndexOf(TEXT("scale_1")), Is2 = IndexOf(TEXT("scale_2"));
	const int32 Ir0 = IndexOf(TEXT("rot_0")), Ir1 = IndexOf(TEXT("rot_1")), Ir2 = IndexOf(TEXT("rot_2")), Ir3 = IndexOf(TEXT("rot_3"));
	const int32 Io = IndexOf(TEXT("opacity"));
	const int32 Ic0 = IndexOf(TEXT("f_dc_0")), Ic1 = IndexOf(TEXT("f_dc_1")), Ic2 = IndexOf(TEXT("f_dc_2"));

	if (Ix < 0 || Iy < 0 || Iz < 0 || Is0 < 0 || Is1 < 0 || Is2 < 0 || Ir0 < 0 || Ir1 < 0 || Ir2 < 0 || Ir3 < 0 || Io < 0 || Ic0 < 0 || Ic1 < 0 || Ic2 < 0)
	{
		Result.Error = FString::Printf(TEXT("PLY missing required 3DGS properties (%s). Found: %s"), *DebugName, *Result.Properties);
		return Result;
	}

	const int32 PropCount = Props.Num();
	const int64 Stride = static_cast<int64>(PropCount) * sizeof(float);
	const int64 RequiredBytes = Header.DataOffset + Stride * Header.VertexCount;
	if (RequiredBytes > Data.Num())
	{
		Result.Error = FString::Printf(TEXT("PLY data truncated: need %lld bytes, file has %d"), RequiredBytes, Data.Num());
		return Result;
	}

	const float UnitScale = UniformScaleOverride > 0.f ? UniformScaleOverride : (bUECoords ? 1.f : 100.f);

	Result.Points.Reset(Header.VertexCount);
	Result.Points.SetNumUninitialized(Header.VertexCount);

	FVector Min(FLT_MAX, FLT_MAX, FLT_MAX);
	FVector Max(-FLT_MAX, -FLT_MAX, -FLT_MAX);

	const uint8* Base = Data.GetData() + Header.DataOffset;
	for (int32 i = 0; i < Header.VertexCount; ++i)
	{
		const uint8* Row = Base + Stride * i;
		const float X = ReadFloat(Row, Ix);
		const float Y = ReadFloat(Row, Iy);
		const float Z = ReadFloat(Row, Iz);
		const float S0 = FMath::Exp(ReadFloat(Row, Is0));
		const float S1 = FMath::Exp(ReadFloat(Row, Is1));
		const float S2 = FMath::Exp(ReadFloat(Row, Is2));
		const float R0 = ReadFloat(Row, Ir0);
		const float R1 = ReadFloat(Row, Ir1);
		const float R2 = ReadFloat(Row, Ir2);
		const float R3 = ReadFloat(Row, Ir3);
		const float OpacityLogit = ReadFloat(Row, Io);
		const float DC0 = ReadFloat(Row, Ic0);
		const float DC1 = ReadFloat(Row, Ic1);
		const float DC2 = ReadFloat(Row, Ic2);

		FVector3f Pos;
		FVector3f Scale;
		FQuat4f Quat(R1, R2, R3, R0);
		if (bUECoords)
		{
			Pos = FVector3f(X, Y, Z) * UnitScale;
			Scale = FVector3f(S0, S1, S2) * UnitScale;
		}
		else
		{
			Pos = FVector3f(X, -Z, -Y) * UnitScale;
			Scale = FVector3f(S0, S2, S1) * UnitScale;
			Quat = FQuat4f(R1, -R3, -R2, R0);
		}
		Quat.Normalize();

		const FVector3f RGB(
			FMath::Clamp(SH_C0 * DC0 + 0.5f, 0.f, 1.f),
			FMath::Clamp(SH_C0 * DC1 + 0.5f, 0.f, 1.f),
			FMath::Clamp(SH_C0 * DC2 + 0.5f, 0.f, 1.f));
		const FLinearColor Color = SplatSRGBToLinear(RGB);
		const float Alpha = 1.f / (1.f + FMath::Exp(-OpacityLogit));

		FGaussianSplattingPoint& P = Result.Points[i];
		P.Position = Pos;
		P.Quat = Quat;
		P.Scale = Scale;
		P.Color = FLinearColor(Color.R, Color.G, Color.B, Alpha);

		Min.X = FMath::Min(Min.X, (double)Pos.X); Min.Y = FMath::Min(Min.Y, (double)Pos.Y); Min.Z = FMath::Min(Min.Z, (double)Pos.Z);
		Max.X = FMath::Max(Max.X, (double)Pos.X); Max.Y = FMath::Max(Max.Y, (double)Pos.Y); Max.Z = FMath::Max(Max.Z, (double)Pos.Z);
	}

	Result.BoundsMin = Min;
	Result.BoundsMax = Max;

	// Debug dump: verify that the property index mapping reads the expected raw bytes.
	{
		FString RawDump;
		const uint8* Row0 = Data.GetData() + Header.DataOffset;
		for (int32 k = 0; k < FMath::Min(PropCount, 20); ++k)
		{
			RawDump += FString::Printf(TEXT("%d=%.6f "), k, ReadFloat(Row0, k));
		}
		UE_LOG(LogTemp, Display, TEXT("[SPLATLOAD] dataOffset=%lld propCount=%d stride=%lld Ix=%d Iy=%d Iz=%d Is0=%d Io=%d Ic0=%d"),
			Header.DataOffset, PropCount, Stride, Ix, Iy, Iz, Is0, Io, Ic0);
		UE_LOG(LogTemp, Display, TEXT("[SPLATLOAD] row0 raw: %s"), *RawDump);
		UE_LOG(LogTemp, Display, TEXT("[SPLATLOAD] point0 pos=%s scale=%s opacity=%.4f"),
			*FVector(Result.Points[0].Position).ToString(), *FVector(Result.Points[0].Scale).ToString(), Result.Points[0].Color.A);
		for (int32 pi = 0; pi < FMath::Min(10, Result.Points.Num()); ++pi)
		{
			const FGaussianSplattingPoint& DP = Result.Points[pi];
			UE_LOG(LogTemp, Display, TEXT("[SPLATLOAD] pt%d xyz=(%.4f,%.4f,%.4f) op=%.4f scale=(%.4f,%.4f,%.4f)"),
				pi, DP.Position.X, DP.Position.Y, DP.Position.Z, DP.Color.A, DP.Scale.X, DP.Scale.Y, DP.Scale.Z);
		}
	}
	return Result;
}
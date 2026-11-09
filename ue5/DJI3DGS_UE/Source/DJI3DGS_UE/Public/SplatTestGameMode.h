#pragma once

#include "CoreMinimal.h"
#include "GameFramework/GameModeBase.h"
#include "SplatTestGameMode.generated.h"

UCLASS()
class DJI3DGS_UE_API ASplatTestGameMode : public AGameModeBase
{
	GENERATED_BODY()

public:
	ASplatTestGameMode();
	virtual void StartPlay() override;
};

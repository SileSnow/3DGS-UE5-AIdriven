#include "SplatTestGameMode.h"
#include "SplatTestActor.h"
#include "GameFramework/PlayerController.h"
#include "Kismet/GameplayStatics.h"
#include "Engine/World.h"

ASplatTestGameMode::ASplatTestGameMode()
{
	DefaultPawnClass = nullptr;
	bStartPlayersAsSpectators = true;
}

void ASplatTestGameMode::StartPlay()
{
	Super::StartPlay();

	UWorld* World = GetWorld();
	if (!World)
	{
		return;
	}

	FActorSpawnParameters SpawnParams;
	SpawnParams.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	ASplatTestActor* Viewer = World->SpawnActor<ASplatTestActor>(ASplatTestActor::StaticClass(), FVector::ZeroVector, FRotator::ZeroRotator, SpawnParams);
	if (!Viewer)
	{
		UE_LOG(LogTemp, Error, TEXT("[SPLAT] Failed to spawn ASplatTestActor"));
		return;
	}

	if (APlayerController* PC = UGameplayStatics::GetPlayerController(this, 0))
	{
		PC->SetViewTarget(Viewer);
		PC->bShowMouseCursor = false;
	}
}

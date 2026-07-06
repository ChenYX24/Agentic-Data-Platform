#include "ADPPhysicsRuntimeLibrary.h"

#include "ADPPhysicsRuntimeDriver.h"
#include "Engine/Engine.h"
#include "Engine/World.h"

AADPPhysicsRuntimeDriver* UADPPhysicsRuntimeLibrary::SpawnPhysicsRuntimeDriver(UObject* WorldContextObject)
{
	UWorld* World = nullptr;
	if (GEngine != nullptr && WorldContextObject != nullptr)
	{
		World = GEngine->GetWorldFromContextObject(WorldContextObject, EGetWorldErrorMode::ReturnNull);
	}
	if (World == nullptr && WorldContextObject != nullptr)
	{
		World = WorldContextObject->GetWorld();
	}
	if (World == nullptr)
	{
		return nullptr;
	}

	FActorSpawnParameters Params;
	Params.SpawnCollisionHandlingOverride = ESpawnActorCollisionHandlingMethod::AlwaysSpawn;
	AADPPhysicsRuntimeDriver* Driver = World->SpawnActor<AADPPhysicsRuntimeDriver>(
		AADPPhysicsRuntimeDriver::StaticClass(),
		FVector::ZeroVector,
		FRotator::ZeroRotator,
		Params);
#if WITH_EDITOR
	if (Driver != nullptr)
	{
		Driver->SetActorLabel(TEXT("ADPPhysicsRuntimeDriver"));
	}
#endif
	return Driver;
}

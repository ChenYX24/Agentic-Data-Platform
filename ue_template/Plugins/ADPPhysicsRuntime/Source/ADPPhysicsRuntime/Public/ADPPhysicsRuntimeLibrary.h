#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "ADPPhysicsRuntimeLibrary.generated.h"

class AADPPhysicsRuntimeDriver;

UCLASS()
class ADPPHYSICSRUNTIME_API UADPPhysicsRuntimeLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	UFUNCTION(BlueprintCallable, Category = "ADP Physics", meta = (WorldContext = "WorldContextObject"))
	static AADPPhysicsRuntimeDriver* SpawnPhysicsRuntimeDriver(UObject* WorldContextObject);
};

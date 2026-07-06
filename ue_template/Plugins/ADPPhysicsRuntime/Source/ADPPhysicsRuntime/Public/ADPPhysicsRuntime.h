#pragma once

#include "Modules/ModuleManager.h"

class FADPPhysicsRuntimeModule : public IModuleInterface
{
public:
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;
};

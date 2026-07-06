#include "ADPPhysicsRuntimeDriver.h"

#include "Components/PrimitiveComponent.h"
#include "Engine/Engine.h"
#include "Engine/World.h"
#include "JsonObjectConverter.h"
#include "Misc/FileHelper.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

namespace
{
TArray<TSharedPtr<FJsonValue>> VectorToJsonArray(const FVector& Vector)
{
	TArray<TSharedPtr<FJsonValue>> Values;
	Values.Add(MakeShared<FJsonValueNumber>(Vector.X));
	Values.Add(MakeShared<FJsonValueNumber>(Vector.Y));
	Values.Add(MakeShared<FJsonValueNumber>(Vector.Z));
	return Values;
}

TArray<TSharedPtr<FJsonValue>> RotatorToJsonArray(const FRotator& Rotator)
{
	TArray<TSharedPtr<FJsonValue>> Values;
	Values.Add(MakeShared<FJsonValueNumber>(Rotator.Pitch));
	Values.Add(MakeShared<FJsonValueNumber>(Rotator.Yaw));
	Values.Add(MakeShared<FJsonValueNumber>(Rotator.Roll));
	return Values;
}
}

AADPPhysicsRuntimeDriver::AADPPhysicsRuntimeDriver()
{
	PrimaryActorTick.bCanEverTick = true;
	PrimaryActorTick.bStartWithTickEnabled = true;
}

void AADPPhysicsRuntimeDriver::Tick(float DeltaSeconds)
{
	Super::Tick(DeltaSeconds);

	if (!bCapturing || bManualSteppingEnabled || bTickingWorldFromDriver)
	{
		return;
	}

	ElapsedSeconds += DeltaSeconds;
	AccumulatedSeconds += DeltaSeconds;

	while (bCapturing && (NextFrameIndex == 0 || AccumulatedSeconds >= SampleIntervalSeconds))
	{
		CaptureFrame();
		++NextFrameIndex;
		AccumulatedSeconds = FMath::Max(0.0f, AccumulatedSeconds - SampleIntervalSeconds);

		if (NextFrameIndex >= MaxFrames)
		{
			StopCapture();
		}
	}
}

void AADPPhysicsRuntimeDriver::ResetDriver()
{
	BodyConfigs.Reset();
	CapturedFrames.Reset();
	OutputPath.Reset();
	ElapsedSeconds = 0.0f;
	AccumulatedSeconds = 0.0f;
	NextFrameIndex = 0;
	MaxFrames = 1;
	bCapturing = false;
	bCaptureComplete = false;
}

void AADPPhysicsRuntimeDriver::RegisterBody(
	FName BodyId,
	AActor* Actor,
	float MassKg,
	FVector InitialVelocityCmPerSec,
	FVector InitialImpulseKgCmPerSec,
	bool bEnableGravity,
	float LinearDamping,
	float AngularDamping,
	bool bSimulatePhysics)
{
	if (BodyId.IsNone() || Actor == nullptr)
	{
		return;
	}

	FADPDrivenBodyConfig Config;
	Config.BodyId = BodyId;
	Config.Actor = Actor;
	Config.bDynamic = true;
	Config.bSimulatePhysics = bSimulatePhysics;
	Config.bEnableGravity = bEnableGravity;
	Config.bCollisionEnabled = true;
	Config.MassKg = FMath::Max(0.001f, MassKg);
	Config.LinearDamping = FMath::Max(0.0f, LinearDamping);
	Config.AngularDamping = FMath::Max(0.0f, AngularDamping);
	Config.InitialVelocityCmPerSec = InitialVelocityCmPerSec;
	Config.InitialImpulseKgCmPerSec = InitialImpulseKgCmPerSec;
	BodyConfigs.Add(Config);
}

void AADPPhysicsRuntimeDriver::RegisterBodyMeters(
	FName BodyId,
	AActor* Actor,
	float MassKg,
	FVector InitialVelocityMetersPerSecond,
	FVector InitialImpulseNewtonSeconds,
	bool bEnableGravity,
	float LinearDamping,
	float AngularDamping,
	bool bSimulatePhysics)
{
	RegisterBody(
		BodyId,
		Actor,
		MassKg,
		InitialVelocityMetersPerSecond * 100.0f,
		InitialImpulseNewtonSeconds * 100.0f,
		bEnableGravity,
		LinearDamping,
		AngularDamping,
		bSimulatePhysics);
}

void AADPPhysicsRuntimeDriver::RegisterStaticBody(FName BodyId, AActor* Actor)
{
	if (BodyId.IsNone() || Actor == nullptr)
	{
		return;
	}

	FADPDrivenBodyConfig Config;
	Config.BodyId = BodyId;
	Config.Actor = Actor;
	Config.bDynamic = false;
	Config.bSimulatePhysics = false;
	Config.bEnableGravity = false;
	Config.bCollisionEnabled = true;
	BodyConfigs.Add(Config);
}

void AADPPhysicsRuntimeDriver::StartCapture(float InSampleIntervalSeconds, int32 InMaxFrames, const FString& InOutputPath)
{
	CapturedFrames.Reset();
	OutputPath = InOutputPath;
	SampleIntervalSeconds = FMath::Max(0.001f, InSampleIntervalSeconds);
	MaxFrames = FMath::Max(1, InMaxFrames);
	ElapsedSeconds = 0.0f;
	AccumulatedSeconds = SampleIntervalSeconds;
	NextFrameIndex = 0;
	bCaptureComplete = false;

	for (const FADPDrivenBodyConfig& Config : BodyConfigs)
	{
		ConfigureBody(Config);
	}

	bCapturing = true;
}

void AADPPhysicsRuntimeDriver::SetManualSteppingEnabled(bool bEnabled)
{
	bManualSteppingEnabled = bEnabled;
}

void AADPPhysicsRuntimeDriver::AdvanceCapture(float DeltaSeconds, bool bTickWorld)
{
	if (!bCapturing)
	{
		return;
	}

	const float ClampedDeltaSeconds = FMath::Max(0.0f, DeltaSeconds);
	if (bTickWorld)
	{
		UWorld* World = GetWorld();
		if (World != nullptr && !bTickingWorldFromDriver)
		{
			bTickingWorldFromDriver = true;
			World->Tick(ELevelTick::LEVELTICK_All, ClampedDeltaSeconds);
			bTickingWorldFromDriver = false;
		}
	}

	CaptureManualFrame(ClampedDeltaSeconds);
}

void AADPPhysicsRuntimeDriver::StopCapture()
{
	if (!bCapturing && bCaptureComplete)
	{
		return;
	}

	bCapturing = false;
	bCaptureComplete = true;
	if (!OutputPath.IsEmpty())
	{
		WriteCaptureJson(OutputPath);
	}
}

bool AADPPhysicsRuntimeDriver::WriteCaptureJson(const FString& Path) const
{
	if (Path.IsEmpty())
	{
		return false;
	}
	return FFileHelper::SaveStringToFile(BuildCaptureJson(), *Path);
}

FString AADPPhysicsRuntimeDriver::GetCaptureJson() const
{
	return BuildCaptureJson();
}

bool AADPPhysicsRuntimeDriver::IsCaptureComplete() const
{
	return bCaptureComplete;
}

void AADPPhysicsRuntimeDriver::CaptureManualFrame(float DeltaSeconds)
{
	if (!bCapturing)
	{
		return;
	}

	ElapsedSeconds += DeltaSeconds;
	CaptureFrame();
	++NextFrameIndex;
	if (NextFrameIndex >= MaxFrames)
	{
		StopCapture();
	}
}

void AADPPhysicsRuntimeDriver::ConfigureBody(const FADPDrivenBodyConfig& Config)
{
	UPrimitiveComponent* Primitive = FindPrimitiveComponent(Config.Actor.Get());
	if (Primitive == nullptr)
	{
		return;
	}

	Primitive->SetMobility(EComponentMobility::Movable);
	Primitive->SetCollisionEnabled(Config.bCollisionEnabled ? ECollisionEnabled::QueryAndPhysics : ECollisionEnabled::NoCollision);
	Primitive->SetCollisionProfileName(Config.bDynamic ? FName(TEXT("PhysicsActor")) : FName(TEXT("BlockAll")));
	Primitive->SetSimulatePhysics(Config.bDynamic && Config.bSimulatePhysics);
	Primitive->SetEnableGravity(Config.bDynamic && Config.bEnableGravity);

	if (Config.bDynamic && Config.MassKg > 0.0f)
	{
		Primitive->SetMassOverrideInKg(NAME_None, Config.MassKg, true);
	}

	Primitive->SetLinearDamping(Config.LinearDamping);
	Primitive->SetAngularDamping(Config.AngularDamping);

	if (Config.bDynamic && Config.bSimulatePhysics)
	{
		Primitive->WakeAllRigidBodies();
		Primitive->SetPhysicsLinearVelocity(Config.InitialVelocityCmPerSec, false, NAME_None);
		if (!Config.InitialImpulseKgCmPerSec.IsNearlyZero())
		{
			Primitive->AddImpulse(Config.InitialImpulseKgCmPerSec, NAME_None, false);
		}
	}
}

void AADPPhysicsRuntimeDriver::CaptureFrame()
{
	FADPFrameCapture Frame;
	Frame.FrameIndex = NextFrameIndex;
	Frame.TimeSeconds = ElapsedSeconds;

	for (const FADPDrivenBodyConfig& Config : BodyConfigs)
	{
		AActor* Actor = Config.Actor.Get();
		if (Actor == nullptr)
		{
			continue;
		}

		FADPTransformSample Transform;
		Transform.BodyId = Config.BodyId;
		Transform.FrameIndex = NextFrameIndex;
		Transform.TimeSeconds = ElapsedSeconds;
		Transform.LocationCm = Actor->GetActorLocation();
		Transform.RotationDegrees = Actor->GetActorRotation();

		UPrimitiveComponent* Primitive = FindPrimitiveComponent(Actor);
		if (Primitive != nullptr)
		{
			Transform.VelocityCmPerSec = Primitive->GetPhysicsLinearVelocity(NAME_None);
		}

		Frame.Transforms.Add(Transform);
	}

	for (int32 IndexA = 0; IndexA < BodyConfigs.Num(); ++IndexA)
	{
		for (int32 IndexB = IndexA + 1; IndexB < BodyConfigs.Num(); ++IndexB)
		{
			const FADPDrivenBodyConfig& A = BodyConfigs[IndexA];
			const FADPDrivenBodyConfig& B = BodyConfigs[IndexB];
			if (!A.bDynamic && !B.bDynamic)
			{
				continue;
			}

			FADPContactSample Contact;
			if (ComputeBoundsContact(A, B, Contact))
			{
				Frame.Contacts.Add(Contact);
			}
		}
	}

	CapturedFrames.Add(Frame);
}

UPrimitiveComponent* AADPPhysicsRuntimeDriver::FindPrimitiveComponent(AActor* Actor) const
{
	if (Actor == nullptr)
	{
		return nullptr;
	}
	return Actor->FindComponentByClass<UPrimitiveComponent>();
}

bool AADPPhysicsRuntimeDriver::ComputeBoundsContact(const FADPDrivenBodyConfig& A, const FADPDrivenBodyConfig& B, FADPContactSample& OutContact) const
{
	AActor* ActorA = A.Actor.Get();
	AActor* ActorB = B.Actor.Get();
	if (ActorA == nullptr || ActorB == nullptr)
	{
		return false;
	}

	FVector OriginA;
	FVector ExtentA;
	FVector OriginB;
	FVector ExtentB;
	ActorA->GetActorBounds(false, OriginA, ExtentA);
	ActorB->GetActorBounds(false, OriginB, ExtentB);

	const FVector AxisGaps(
		FMath::Abs(OriginA.X - OriginB.X) - (ExtentA.X + ExtentB.X),
		FMath::Abs(OriginA.Y - OriginB.Y) - (ExtentA.Y + ExtentB.Y),
		FMath::Abs(OriginA.Z - OriginB.Z) - (ExtentA.Z + ExtentB.Z));
	const float GapCm = FMath::Max3(AxisGaps.X, AxisGaps.Y, AxisGaps.Z);
	if (GapCm > ContactToleranceCm)
	{
		return false;
	}

	OutContact.FrameIndex = NextFrameIndex;
	OutContact.TimeSeconds = ElapsedSeconds;
	OutContact.BodyA = A.BodyId;
	OutContact.BodyB = B.BodyId;
	OutContact.GapCm = GapCm;
	OutContact.AxisGapsCm = AxisGaps;
	return true;
}

FString AADPPhysicsRuntimeDriver::BuildCaptureJson() const
{
	TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
	Root->SetStringField(TEXT("driver"), TEXT("ADPPhysicsRuntimeDriver"));
	Root->SetNumberField(TEXT("sample_interval_s"), SampleIntervalSeconds);
	Root->SetNumberField(TEXT("frame_count"), CapturedFrames.Num());
	Root->SetNumberField(TEXT("requested_max_frames"), MaxFrames);
	Root->SetNumberField(TEXT("contact_tolerance_cm"), ContactToleranceCm);
	Root->SetBoolField(TEXT("capture_complete"), bCaptureComplete);

	TArray<TSharedPtr<FJsonValue>> FramesJson;
	for (const FADPFrameCapture& Frame : CapturedFrames)
	{
		TSharedRef<FJsonObject> FrameObject = MakeShared<FJsonObject>();
		FrameObject->SetNumberField(TEXT("frame"), Frame.FrameIndex);
		FrameObject->SetNumberField(TEXT("time"), Frame.TimeSeconds);
		FrameObject->SetStringField(TEXT("source"), TEXT("adp_cpp_runtime_driver"));

		TSharedRef<FJsonObject> ObjectsObject = MakeShared<FJsonObject>();
		for (const FADPTransformSample& Transform : Frame.Transforms)
		{
			TSharedRef<FJsonObject> TransformObject = MakeShared<FJsonObject>();
			TransformObject->SetArrayField(TEXT("position_cm"), VectorToJsonArray(Transform.LocationCm));
			TransformObject->SetArrayField(TEXT("rotation_degrees"), RotatorToJsonArray(Transform.RotationDegrees));
			TransformObject->SetArrayField(TEXT("velocity_cm_s"), VectorToJsonArray(Transform.VelocityCmPerSec));
			TransformObject->SetStringField(TEXT("source"), TEXT("adp_cpp_runtime_driver"));
			ObjectsObject->SetObjectField(Transform.BodyId.ToString(), TransformObject);
		}
		FrameObject->SetObjectField(TEXT("objects"), ObjectsObject);

		TArray<TSharedPtr<FJsonValue>> ContactsJson;
		for (const FADPContactSample& Contact : Frame.Contacts)
		{
			TSharedRef<FJsonObject> ContactObject = MakeShared<FJsonObject>();
			ContactObject->SetNumberField(TEXT("frame"), Contact.FrameIndex);
			ContactObject->SetNumberField(TEXT("time"), Contact.TimeSeconds);
			TArray<TSharedPtr<FJsonValue>> Bodies;
			Bodies.Add(MakeShared<FJsonValueString>(Contact.BodyA.ToString()));
			Bodies.Add(MakeShared<FJsonValueString>(Contact.BodyB.ToString()));
			ContactObject->SetArrayField(TEXT("objects"), Bodies);
			ContactObject->SetStringField(TEXT("method"), TEXT("adp_cpp_runtime_bounds_overlap_or_near_contact"));
			ContactObject->SetNumberField(TEXT("gap_cm"), Contact.GapCm);
			TSharedRef<FJsonObject> AxisObject = MakeShared<FJsonObject>();
			AxisObject->SetNumberField(TEXT("x"), Contact.AxisGapsCm.X);
			AxisObject->SetNumberField(TEXT("y"), Contact.AxisGapsCm.Y);
			AxisObject->SetNumberField(TEXT("z"), Contact.AxisGapsCm.Z);
			ContactObject->SetObjectField(TEXT("axis_gaps_cm"), AxisObject);
			ContactsJson.Add(MakeShared<FJsonValueObject>(ContactObject));
		}
		FrameObject->SetArrayField(TEXT("contacts"), ContactsJson);
		FramesJson.Add(MakeShared<FJsonValueObject>(FrameObject));
	}
	Root->SetArrayField(TEXT("frames"), FramesJson);

	FString Output;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
	FJsonSerializer::Serialize(Root, Writer);
	return Output;
}

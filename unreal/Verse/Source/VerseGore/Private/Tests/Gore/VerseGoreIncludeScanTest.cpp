#include "Misc/AutomationTest.h"

#if WITH_DEV_AUTOMATION_TESTS

#include "HAL/FileManager.h"
#include "Internationalization/Regex.h"
#include "Misc/FileHelper.h"
#include "Misc/Paths.h"

#define VERSE_GORE_SCAN_FLAGS (EAutomationTestFlags_ApplicationContextMask | EAutomationTestFlags::EngineFilter)

// A5.2: Source/VerseGore/** includes no header of VerseCombat, VerseBot or VerseDestruction
// (combat-state.md 8, architecture.md 2). Gore talks to them only through Core's hub.
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FVerseGoreIncludeScanTest, "Verse.Gore.IncludeScan", VERSE_GORE_SCAN_FLAGS)
bool FVerseGoreIncludeScanTest::RunTest(const FString&)
{
	const FString SourceRoot = FPaths::ConvertRelativePathToFull(FPaths::GameSourceDir());
	const FString GoreRoot = FPaths::Combine(SourceRoot, TEXT("VerseGore"));
	if (!TestTrue(TEXT("VerseGore sources present"), FPaths::DirectoryExists(GoreRoot)))
	{
		return false;
	}

	// Every header the forbidden modules hold, as include paths relative to Public/ and Private/.
	TSet<FString> Forbidden;
	TSet<FString> ForbiddenNames;
	for (const TCHAR* Module : {TEXT("VerseCombat"), TEXT("VerseBot"), TEXT("VerseDestruction")})
	{
		const FString ModuleRoot = FPaths::Combine(SourceRoot, Module);
		TArray<FString> Headers;
		IFileManager::Get().FindFilesRecursive(Headers, *ModuleRoot, TEXT("*.h"), true, false);
		for (const FString& Header : Headers)
		{
			FString Relative = Header;
			for (const TCHAR* Sub : {TEXT("/Public/"), TEXT("/Private/"), TEXT("/Classes/")})
			{
				const int32 At = Relative.Find(Sub);
				if (At != INDEX_NONE)
				{
					Relative = Relative.Mid(At + FCString::Strlen(Sub));
					break;
				}
			}
			Forbidden.Add(Relative.ToLower());
		}
		ForbiddenNames.Add(FString(Module).ToLower());
	}
	TestTrue(TEXT("forbidden modules have headers to scan against"), Forbidden.Num() > 0);

	TArray<FString> Files;
	IFileManager::Get().FindFilesRecursive(Files, *GoreRoot, TEXT("*.*"), true, false);
	const FRegexPattern Include(TEXT("^\\s*#\\s*include\\s*[\"<]([^\">]+)[\">]"));
	int32 Scanned = 0, Includes = 0;
	for (const FString& File : Files)
	{
		if (!File.EndsWith(TEXT(".h")) && !File.EndsWith(TEXT(".cpp")) && !File.EndsWith(TEXT(".inl")))
		{
			continue;
		}
		TArray<FString> Lines;
		FFileHelper::LoadFileToStringArray(Lines, *File);
		++Scanned;
		for (const FString& Line : Lines)
		{
			FRegexMatcher Matcher(Include, Line);
			if (!Matcher.FindNext())
			{
				continue;
			}
			++Includes;
			const FString Path = Matcher.GetCaptureGroup(1).ToLower();
			FString FirstSegment;
			Path.Split(TEXT("/"), &FirstSegment, nullptr);
			const bool bByPath = Forbidden.Contains(Path);
			const bool bByModuleFolder = ForbiddenNames.Contains(FirstSegment);
			const bool bByModuleHeader = Path.StartsWith(TEXT("versecombat")) || Path.StartsWith(TEXT("versebot")) || Path.StartsWith(TEXT("versedestruction"));
			if (bByPath || bByModuleFolder || bByModuleHeader)
			{
				AddError(FString::Printf(TEXT("%s includes %s"), *FPaths::GetCleanFilename(File), *Path));
			}
		}
	}
	TestTrue(FString::Printf(TEXT("scanned %d files, %d includes"), Scanned, Includes), Scanned >= 8 && Includes > 20);

	// The build rules agree: no Combat, Bot or Destruction edge.
	FString BuildRules;
	FFileHelper::LoadFileToString(BuildRules, *FPaths::Combine(GoreRoot, TEXT("VerseGore.Build.cs")));
	for (const TCHAR* Module : {TEXT("\"VerseCombat\""), TEXT("\"VerseBot\""), TEXT("\"VerseDestruction\"")})
	{
		TestFalse(FString::Printf(TEXT("VerseGore.Build.cs names %s"), Module), BuildRules.Contains(Module));
	}
	return true;
}

#endif // WITH_DEV_AUTOMATION_TESTS

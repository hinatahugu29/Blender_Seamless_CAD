call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"
cl.exe /EHsc /I"..\..\occt-combined-release-no-pch\opencascade-8.0.0-vc14-64-combined\opencascade-8.0.0-vc14-64\inc" test_occ_trsf.cpp /link /LIBPATH:"..\..\occt-combined-release-no-pch\opencascade-8.0.0-vc14-64-combined\opencascade-8.0.0-vc14-64\win64\vc14\lib" TKMath.lib
.\test_occ_trsf.exe

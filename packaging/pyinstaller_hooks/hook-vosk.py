# Collects vosk's native libraries next to its package in the frozen bundle.
#
# vosk loads ``libvosk.dll`` (and on Windows its MinGW runtime DLLs) with
# ``cffi.dlopen`` from its own package folder, which no import analysis can see.
# Without this hook the frozen app shipped the Python module but no DLL: every
# ``import vosk`` failed after vosk had prepended its folder to PATH, so PATH
# filled up with copies of ``_internal\vosk`` and the app could no longer start
# any program (WinError 8, #1045 / #1071).

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs("vosk")
hiddenimports = ["vosk.vosk_cffi"]

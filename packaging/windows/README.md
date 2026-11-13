# Windows build

Builds the 64-bit Windows program and an installer (`MegaSpin-<version>-setup-x64.exe`).

Requirements: Windows 10/11 x64, Python 3.11 or newer, the MegaSpin dependencies
(`pip install -e .` in the `megaspin` folder), PyInstaller and Inno Setup 6.

```bat
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name MegaSpin ^
  --icon packaging\windows\megaspin.ico --paths src ^
  --collect-data megaspin --collect-submodules megaspin ^
  --distpath dist\windows --workpath build\pyinstaller\work --specpath build\pyinstaller ^
  packaging\windows\launch.py
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" packaging\windows\megaspin.iss
```

Result: `dist\windows\MegaSpin.exe` (portable folder) and `dist\windows\MegaSpin-0.1.0-beta1-setup-x64.exe`.

The icon (`megaspin.ico`) is generated from `megaspin.svg`, the same disc symbol as the in-app icon.

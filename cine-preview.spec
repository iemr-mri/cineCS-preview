# PyInstaller spec for cine-preview.
#
# Builds a single, self-contained Windows .exe that launches the PySide6 GUI.
#
# Build with:  .venv\Scripts\python.exe -m PyInstaller cine-preview.spec --noconfirm
# Output:      dist\cine-preview.exe

from PyInstaller.utils.hooks import collect_submodules

# scipy pulls in submodules dynamically; collect them explicitly.
hidden_imports = collect_submodules("scipy")

analysis = Analysis(
    ["src/cine_preview/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore", "PyQt5", "PyQt6"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="cine-preview",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

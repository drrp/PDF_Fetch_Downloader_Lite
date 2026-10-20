# PyInstaller build definition for the standalone Windows app.
#
#   pyinstaller --clean library-app.spec
#
# The result is a single LibraryApp.exe that starts the server and opens your
# browser. It is built on Windows, because PyInstaller cannot cross-compile: a
# build on Linux or macOS produces a binary for that system, not a .exe.

import os

from PyInstaller.utils.hooks import collect_all

here = os.path.abspath(os.getcwd())

datas = [("frontend", "frontend")]
binaries = []
hiddenimports = []

# The app's own modules. The launcher imports backend.main from inside a function,
# and PyInstaller does not reliably follow that, so they are named explicitly.
hiddenimports += [
    "backend",
    "backend.main",
    "backend.svk",
    "backend.archive",
    "backend.manasu",
    "backend.ttd",
]

# uvicorn loads its event loop and protocol implementations by name at runtime, so
# PyInstaller cannot see them by reading the imports. The scrapers' libraries are
# named for the same reason. collect_all pulls the code, data and binaries in.
for package in (
    "uvicorn", "fastapi", "starlette", "authlib", "anyio", "h11", "click",
    "gdown", "bs4", "pypdf", "requests", "psycopg2", "dotenv", "itsdangerous",
    "rjsmin", "rcssmin",
):
    try:
        collected = collect_all(package)
    except Exception:
        continue
    datas += collected[0]
    binaries += collected[1]
    hiddenimports += collected[2]

hiddenimports += [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

a = Analysis(
    ["run_app.py"],
    pathex=[here],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

# Passing the binaries and datas into EXE is what makes this a single-file build.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="LibraryApp",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    icon="app.ico" if os.path.exists("app.ico") else None,
)

# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

project_root = Path(SPECPATH)
features_dir = project_root / "src" / "scia" / "features"

qss_datas = [
    (
        str(project_root / "src" / "scia" / "shared" / "ui" / "styles.qss"),
        "scia/shared/ui",
    ),
]
for qss_file in features_dir.glob("*/styles.qss"):
    qss_datas.append((str(qss_file), f"scia/features/{qss_file.parent.name}"))

a = Analysis(
    [str(project_root / "src" / "scia" / "__main__.py")],
    pathex=[str(project_root / "src")],
    binaries=[],
    datas=qss_datas,
    hiddenimports=[
        "PySide6.QtSvg",
        "scia.shared.ui.resources_rc",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tests", "unittest", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SC.IA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SC.IA",
)

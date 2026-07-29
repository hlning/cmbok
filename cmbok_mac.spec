# -*- mode: python ; coding: utf-8 -*-
# macOS 打包配置：icon 用 .icns、关闭 upx（Mac 上易致签名/启动问题）、路径正斜杠、生成 .app bundle
# 用法（macOS 或 GitHub Actions macos runner）：pyinstaller cmbok_mac.spec
# 依赖：resource/images/logo.icns（由 build-mac.yml 用 iconutil 从 logo.png 生成）

a = Analysis(
    ['cmbok.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='cmbok',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['resource/images/logo.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='cmbok',
)
app = BUNDLE(
    coll,
    name='cmbok.app',
    icon='resource/images/logo.icns',
    bundle_identifier='com.cmbok.app',
)

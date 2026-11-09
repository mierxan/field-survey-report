# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('data/excel/First_Page.xlsx', 'data/excel'), ('data/excel/Cargo_Details.xlsx', 'data/excel'), ('data/excel/Containerized_Loading_Form.xlsx', 'data/excel'), ('data/excel/Incident_Report.xlsx', 'data/excel'), ('data/json/master_list.json', 'data/json'), ('logo.png', '.'), ('logo.ico', '.'), ('data/json/private/installer_defaults/db_config.json', 'data/json/private/installer_defaults'), ('data/json/private/auth_seed.json', 'data/json/private')]
binaries = []
hiddenimports = ['matplotlib.backends.backend_tkagg', 'win32com.client']
hiddenimports += collect_submodules('mysql.connector')
hiddenimports += collect_submodules('warehouse')
hiddenimports += collect_submodules('warehouse_ui')
tmp_ret = collect_all('ttkbootstrap')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['field_survey_report.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    name='FieldSurveyReport',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='FieldSurveyReport',
)

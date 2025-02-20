import os

from cx_Freeze import setup, Executable

# 找到 OpenSSL 的路径
openssl_dir = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python310\Lib\site-packages\PyQt5"  # 根据实际路径调整
# OpenSSL DLLs路径
openssl_dlls = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310', 'Lib', 'site-packages', 'PyQt5',
                 'Qt5', 'bin', 'libcrypto-1_1-x64.dll'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                 r'C:\Users\Administrator\AppData\Local\Programs\Python\Python310', 'Lib', 'site-packages', 'PyQt5',
                 'Qt5', 'bin', 'libssl-1_1-x64.dll'),
]

# 确定图标文件路径
icon_path = "resource/images/logo.ico"  # 替换为您的图标路径

# cx_Freeze 配置
setup(
    name="cmbok",
    version="0.1",
    options={
        "build_exe": {
            "excludes": ["attrs","autocommand","backports","bcrypt","cffi","cryptography","cssselect","curses","defusedxml","docutils","jaraco","lib2to3","more_itertools","numpy","numpy.libs","outcome","packaging","pkg_resources","platformdirs","pycparser","pydoc_data","pygments","setuptools","sortedcontainers","soupsieve","tkinter","tomli","tomllib","trio","typeguard","unittest","wheel","xml","xmlrpc","yaml","zipp",],  # 排除不必要的库
            "include_files": openssl_dlls,
        }
    },
    executables=[Executable("cmbok.py", base="Win32GUI", icon=icon_path)]
)

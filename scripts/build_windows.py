from pathlib import Path
import os
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
build_name = 'NightreignHelper-Auto-r3'
work = root / '.work'
for name in ('tmp', 'pyinstaller-config'):
    (work / name).mkdir(parents=True, exist_ok=True)
environment = dict(os.environ, TEMP=str(work/'tmp'), TMP=str(work/'tmp'),
                   PYINSTALLER_CONFIG_DIR=str(work/'pyinstaller-config'), PYGAME_HIDE_SUPPORT_PROMPT='1',
                   PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
           '--name', build_name, '--icon', str(root/'assets'/'icon.ico'),
           '--distpath', 'dist', '--workpath', '.work/build', '--specpath', '.work',
           '--add-data', str(root/'assets')+';assets', '--add-data', str(root/'data')+';data',
           '--add-data', str(root/'config.yaml')+';.', '--add-data', str(root/'pyproject.toml')+';.',
           '--hidden-import', 'src.app', '--exclude-module', 'PyQt5',
           '--exclude-module', 'PySide2', '--exclude-module', 'PySide6', 'launch.py']
with (work/'build.log').open('wb') as log:
    result = subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
if result.returncode:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(errors='replace')
    print((work/'build.log').read_text(encoding='utf-8', errors='replace')[-8000:])
    raise SystemExit(result.returncode)
for name in ('README.md', 'NOTICE.md', 'LICENSE', 'README-增强版.md', 'CHANGELOG-增强版.md', 'requirements-lock.txt'):
    shutil.copy2(root/name, root/'dist'/build_name/name)
print('Build complete: dist/' + build_name + '/' + build_name + '.exe')

"""Archive the verified distribution and complete corresponding source."""
from pathlib import Path
import hashlib
import zipfile

root = Path(__file__).resolve().parent.parent
build_name = 'NightreignHelper-Auto-r3'
distribution = root / 'dist' / build_name
release = root / 'release'
release.mkdir(exist_ok=True)
package = release / 'nightreign-helper-auto-0.10.6-r3-win64.zip'
source = release / 'nightreign-helper-auto-0.10.6-r3-source.zip'
if not package.exists():
    with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(distribution.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(distribution.parent).as_posix())
files = [root / name for name in ('launch.py', 'config.yaml', 'pyproject.toml', 'LICENSE',
                                  'requirements-lock.txt', 'manual.txt', 'build.bat')]
files.extend(sorted(root.glob('*.md')))
with zipfile.ZipFile(source, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
    for path in files:
        archive.write(path, 'nightreign-overlay-helper-plus/' + path.relative_to(root).as_posix())
    for folder in ('src', 'assets', 'data', 'scripts', 'tests', 'docs'):
        for path in sorted((root / folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                archive.write(path, 'nightreign-overlay-helper-plus/' + path.relative_to(root).as_posix())
lines = []
for path in (package, source, distribution / (build_name+'.exe')):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    lines.append(digest + '  ' + path.name)
    print(path.name, path.stat().st_size, digest)
(release / 'SHA256SUMS-r3.txt').write_text('\n'.join(lines) + '\n', encoding='ascii')
with zipfile.ZipFile(package) as archive:
    assert archive.testzip() is None
    assert build_name + '/' + build_name + '.exe' in archive.namelist()
with zipfile.ZipFile(source) as archive:
    assert archive.testzip() is None
    assert 'nightreign-overlay-helper-plus/src/automation.py' in archive.namelist()
    assert not any('/.venv/' in path or '/.work/' in path for path in archive.namelist())
print('Both release archives verified.')

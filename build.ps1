# Builds dist\Shiftdial\Shiftdial.exe (one folder, no console) with ffmpeg.exe next to it.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Get-Process Shiftdial -ErrorAction SilentlyContinue | Where-Object Path -like "$PSScriptRoot\dist\*") { throw "Shiftdial.exe is running and locks dist\Shiftdial. Quit it from the tray icon, then build again." }
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No .venv found. Create it first: py -3.12 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt" }

& $py -m pip install --quiet "pyinstaller==6.22.3"
if ($LASTEXITCODE -ne 0) { throw "pip install pyinstaller failed" }

# App icon: rendered from the same code as the tray icon.
New-Item -ItemType Directory -Force build | Out-Null
& $py -c "from PySide6.QtWidgets import QApplication; app = QApplication([]); from shiftdial.main import make_icon; make_icon(256).pixmap(256, 256).save('build/shiftdial.png')"
& $py -c "from PIL import Image; Image.open('build/shiftdial.png').save('build/shiftdial.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
if ($LASTEXITCODE -ne 0) { throw "icon render failed" }

& $py -m PyInstaller --noconfirm --clean --windowed --name Shiftdial `
    --icon build\shiftdial.ico --paths . --exclude-module tkinter `
    --exclude-module imageio_ffmpeg `
    shiftdial\main.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Bundle ffmpeg: the one imageio-ffmpeg ships (GPL build; see README "Licences").
$ffmpeg = & $py -c "import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())"
Copy-Item $ffmpeg dist\Shiftdial\ffmpeg.exe -Force

# Remove background: the IS-Net model (Apache-2.0). Downloaded once into models\ (gitignored), checked
# against a pinned hash, bundled into the app. The app itself never downloads anything.
$model = "models\isnet-general-use.onnx"
$modelSha = "60920E99C45464F2BA57BEE2AD08C919A52BBF852739E96947FBB4358C0D964A"
if (-not (Test-Path $model)) {
    New-Item -ItemType Directory -Force models | Out-Null
    Invoke-WebRequest "https://github.com/danielgatis/rembg/releases/download/v0.0.0/isnet-general-use.onnx" -OutFile "$model.part" -UseBasicParsing
    if ((Get-FileHash "$model.part" -Algorithm SHA256).Hash -ne $modelSha) { Remove-Item "$model.part"; throw "The downloaded model failed its SHA-256 check" }
    Move-Item "$model.part" $model
}
if ((Get-FileHash $model -Algorithm SHA256).Hash -ne $modelSha) { throw "$model doesn't match its pinned SHA-256; delete it and build again" }
New-Item -ItemType Directory -Force dist\Shiftdial\models | Out-Null
Copy-Item $model dist\Shiftdial\models\ -Force

$size = "{0:N0} MB" -f ((Get-ChildItem dist\Shiftdial -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "Built dist\Shiftdial\Shiftdial.exe ($size)"

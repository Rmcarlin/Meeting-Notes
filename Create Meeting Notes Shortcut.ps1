# Create the app launcher in this folder, including its custom Windows icon.
$ErrorActionPreference = 'Stop'
$appFolder = $PSScriptRoot
$launcher = Join-Path $appFolder 'Start Meeting Notes.cmd'
$icon = Join-Path $appFolder 'assets\meeting-notes.ico'
if (-not (Test-Path -LiteralPath $launcher) -or -not (Test-Path -LiteralPath $icon)) {
    throw 'The launcher or app icon is missing. Keep this script in the Meeting Notes folder.'
}
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut((Join-Path $appFolder 'Meeting Notes.lnk'))
$shortcut.TargetPath = $launcher
$shortcut.WorkingDirectory = $appFolder
$shortcut.IconLocation = "$icon,0"
$shortcut.Description = 'Record meetings, transcribe audio and save meeting notes locally.'
$shortcut.WindowStyle = 7
$shortcut.Save()
Write-Output "Created: $(Join-Path $appFolder 'Meeting Notes.lnk')"

"""OS notifications for an explicitly enabled independent host."""
import json
import shutil
import subprocess
import sys
from ..osenv import NO_WINDOW


def show(title, body):
    if sys.platform == 'win32':
        script = r'''
$ErrorActionPreference = 'Stop'
$message = [Console]::In.ReadToEnd() | ConvertFrom-Json
$appId = 'com.grom.aistudio'
$entry = 'HKCU:\Software\Classes\AppUserModelId\' + $appId
if (!(Test-Path -LiteralPath $entry)) { New-Item -Path $entry -Force | Out-Null }
New-ItemProperty -LiteralPath $entry -Name DisplayName -Value 'Grom AI Studio' -PropertyType String -Force | Out-Null
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml('<toast><visual><binding template="ToastGeneric"><text/><text/></binding></visual></toast>')
$nodes = $xml.GetElementsByTagName('text')
$nodes.Item(0).InnerText = [string]$message.title
$nodes.Item(1).InnerText = [string]$message.body
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
'''
        import base64
        command = ['powershell.exe','-NoProfile','-NonInteractive','-WindowStyle','Hidden','-EncodedCommand',base64.b64encode(script.encode('utf-16-le')).decode()]
        result = subprocess.run(command,input=json.dumps({'title':title,'body':body}),text=True,capture_output=True,timeout=15,creationflags=NO_WINDOW)
    elif sys.platform == 'darwin':
        # Message data is supplied as argv; it never becomes AppleScript source.
        result = subprocess.run(['osascript','-e','on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run',title,body],capture_output=True,text=True,timeout=15)
    else:
        program = shutil.which('notify-send')
        if not program: raise ValueError('Native notifications require notify-send on this desktop')
        result = subprocess.run([program,'--app-name=Grom AI Studio',title,body],capture_output=True,text=True,timeout=15)
    if result.returncode: raise ValueError('The OS did not display the notification')

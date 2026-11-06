Option Explicit
Dim files, shell, root, python, command
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
root = files.GetParentFolderName(WScript.ScriptFullName)
python = files.BuildPath(root, ".venv-analysis\Scripts\pythonw.exe")
If Not files.FileExists(python) Then
    python = files.BuildPath(root, ".venv-workstation\Scripts\pythonw.exe")
End If
If Not files.FileExists(python) Then
    MsgBox "SELBY's Python environment was not found. See SELBY_WORKSTATION_V05A3.md in the project root for setup.", vbExclamation, "SELBY"
    WScript.Quit 3
End If
shell.CurrentDirectory = root
command = Chr(34) & python & Chr(34) & " -B " & Chr(34) & files.BuildPath(root, "selby_desktop.pyw") & Chr(34)
shell.Run command, 1, False

; =============================================================================
; installer.nsi -- Video Dubbing full offline installer (Setup.exe)
;
; Ships as:  Setup.exe  +  app.7z   (keep them in the SAME folder)
; Setup.exe is small; it extracts the sibling app.7z (~20GB) into the chosen dir,
; repairs venv/pyvenv.cfg to the install path, and makes shortcuts + an uninstaller.
;
; No admin required: installs to a user-writable dir (the app runs asInvoker and
; writes data/ + repairs pyvenv.cfg under the install dir), per-user shortcuts and
; Add/Remove-Programs entry (HKCU). 7za.exe is embedded into Setup.exe.
; =============================================================================

Unicode true
!include "LogicLib.nsh"
!include "FileFunc.nsh"

!define APPNAME "Video Dubbing"
!define COMPANY "Video Dubbing"
!define EXENAME "Video Dubbing.exe"
!define ARPKEY  "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"

Name "${APPNAME}"
OutFile "Setup.exe"
RequestExecutionLevel user
InstallDir "$LOCALAPPDATA\VideoDubbing"
ShowInstDetails show
ShowUninstDetails show
BrandingText "${APPNAME} -- AI Video Dubbing"

Page directory
Page instfiles
UninstPage uninstConfirm
UninstPage instfiles

; ---------------------------------------------------------------------------
Section "Install"
  ; sanity: the payload must sit next to Setup.exe
  ${IfNot} ${FileExists} "$EXEDIR\app.7z"
    MessageBox MB_ICONSTOP "Khong tim thay app.7z trong cung thu muc voi Setup.exe.$\r$\nHay giu Setup.exe va app.7z cung mot thu muc."
    Abort
  ${EndIf}

  ; embedded extractor -> temp
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  File "7za.exe"

  CreateDirectory "$INSTDIR"
  DetailPrint "Dang giai nen ung dung (~20GB) -- co the mat vai phut..."
  nsExec::ExecToLog '"$PLUGINSDIR\7za.exe" x "$EXEDIR\app.7z" -o"$INSTDIR" -y -bsp1'
  Pop $0
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Giai nen that bai (7za code $0)."
    Abort
  ${EndIf}

  ; verify a key artifact landed
  ${IfNot} ${FileExists} "$INSTDIR\${EXENAME}"
    MessageBox MB_ICONSTOP "Sau giai nen khong thay ${EXENAME}. Goi cai dat co the bi loi."
    Abort
  ${EndIf}

  ; repair venv/pyvenv.cfg -> bundled python-runtime at the REAL install dir
  ${If} ${FileExists} "$INSTDIR\python-runtime\python.exe"
    Delete "$INSTDIR\venv\pyvenv.cfg"
    FileOpen $1 "$INSTDIR\venv\pyvenv.cfg" w
    FileWrite $1 "home = $INSTDIR\python-runtime$\r$\n"
    FileWrite $1 "include-system-site-packages = false$\r$\n"
    FileWrite $1 "version = 3.10.11$\r$\n"
    FileClose $1
    DetailPrint "Da lien ket venv voi python-runtime nhung."
  ${EndIf}

  ; shortcuts (per-user)
  CreateShortcut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\icon.ico"
  CreateDirectory "$SMPROGRAMS\${APPNAME}"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\${EXENAME}" "" "$INSTDIR\icon.ico"
  CreateShortcut "$SMPROGRAMS\${APPNAME}\Uninstall ${APPNAME}.lnk" "$INSTDIR\Uninstall.exe"

  ; uninstaller + Add/Remove Programs (per-user / HKCU)
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr   HKCU "${ARPKEY}" "DisplayName"     "${APPNAME}"
  WriteRegStr   HKCU "${ARPKEY}" "UninstallString" '"$INSTDIR\Uninstall.exe"'
  WriteRegStr   HKCU "${ARPKEY}" "DisplayIcon"     "$INSTDIR\icon.ico"
  WriteRegStr   HKCU "${ARPKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr   HKCU "${ARPKEY}" "Publisher"       "${COMPANY}"
  WriteRegStr   HKCU "${ARPKEY}" "DisplayVersion"  "1.0.0"
  WriteRegDWORD HKCU "${ARPKEY}" "NoModify" 1
  WriteRegDWORD HKCU "${ARPKEY}" "NoRepair" 1
  ; report installed size to ARP (KB)
  ${GetSize} "$INSTDIR" "/S=0K" $2 $3 $4
  IntFmt $2 "0x%08X" $2
  WriteRegDWORD HKCU "${ARPKEY}" "EstimatedSize" $2

  DetailPrint "Hoan tat. Mo bang shortcut '${APPNAME}' tren Desktop."
SectionEnd

; ---------------------------------------------------------------------------
Section "Uninstall"
  Delete "$DESKTOP\${APPNAME}.lnk"
  RMDir /r "$SMPROGRAMS\${APPNAME}"
  RMDir /r "$INSTDIR"
  DeleteRegKey HKCU "${ARPKEY}"
SectionEnd

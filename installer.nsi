!include "MUI2.nsh"
!include "LogicLib.nsh"

Name "XianyuTool"
OutFile "XianyuTool_Setup.exe"
InstallDir "$LOCALAPPDATA\XianyuTool"
InstallDirRegKey HKCU "Software\XianyuTool" "InstallDir"
RequestExecutionLevel User
ShowInstDetails show

VIProductVersion "1.3.6.0"
VIAddVersionKey /LANG=2052 "ProductName" "XianyuTool"
VIAddVersionKey /LANG=2052 "CompanyName" "Qiu-Difeng"
VIAddVersionKey /LANG=2052 "FileDescription" "XianyuTool Setup"
VIAddVersionKey /LANG=2052 "LegalCopyright" "MIT License"
VIAddVersionKey /LANG=2052 "FileVersion" "1.3.6.0"

!define MUI_ICON "xianyu_icon.ico"
!define MUI_UNICON "xianyu_icon.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_NOAUTOCLOSE
!define MUI_UNFINISHPAGE_NOAUTOCLOSE

!define MUI_FINISHPAGE_RUN "$INSTDIR\XianyuTool.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch XianyuTool"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "SimpChinese"

Section "Main" SecMain
    SectionIn RO
    SetOutPath "$INSTDIR"
    
    RMDir /r "$INSTDIR"
    CreateDirectory "$INSTDIR"
    
    File /r "dist\XianyuTool\*.*"
    
    WriteRegStr HKCU "Software\XianyuTool" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "DisplayName" "XianyuTool"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "UninstallString" '"$INSTDIR\uninstall.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "DisplayIcon" '"$INSTDIR\XianyuTool.exe"'
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "DisplayVersion" "1.3.6"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "Publisher" "Qiu-Difeng"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool" "InstallLocation" "$INSTDIR"
    
    CreateShortCut "$DESKTOP\XianyuTool.lnk" "$INSTDIR\XianyuTool.exe" "" "$INSTDIR\XianyuTool.exe" 0
    
    CreateDirectory "$SMPROGRAMS\XianyuTool"
    CreateShortCut "$SMPROGRAMS\XianyuTool\XianyuTool.lnk" "$INSTDIR\XianyuTool.exe" "" "$INSTDIR\XianyuTool.exe" 0
    CreateShortCut "$SMPROGRAMS\XianyuTool\Uninstall.lnk" "$INSTDIR\uninstall.exe" "" "$INSTDIR\uninstall.exe" 0
    
    CreateShortCut "$INSTDIR\Uninstall.lnk" "$INSTDIR\uninstall.exe" "" "$INSTDIR\uninstall.exe" 0
    
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    SetAutoClose true
SectionEnd

Section "Uninstall"
    Delete "$DESKTOP\XianyuTool.lnk"
    RMDir /r "$SMPROGRAMS\XianyuTool"
    RMDir /r "$INSTDIR"
    DeleteRegKey HKCU "Software\XianyuTool"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\XianyuTool"
    SetAutoClose true
SectionEnd

Function .onInstSuccess
    ; 单反斜杠：与第 48 行 InstallDir 的写法保持一致。
    ; NSIS 字符串不做转义，"Software\\XianyuTool" 会原样写成双反斜杠，
    ; 而程序侧 _get_local_version() 读的是 Software\XianyuTool\Version，
    ; 路径不一致会导致版本号永远读不到（每次启动都提示有新版本）。
    WriteRegStr HKCU "Software\XianyuTool" "Version" "1.3.6"
FunctionEnd





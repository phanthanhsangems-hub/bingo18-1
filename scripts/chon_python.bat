@echo off
REM P298b: chon Python cho app tren may nha -> dat bien PY. Goi bang:  call scripts\chon_python.bat
REM May nha co ca Python 3.14 (lenh "python") lan 3.11. Thu vien ghim trong requirements.txt
REM (scikit-learn 1.6.1, numpy 1.26.4...) chi co ban dung san den 3.12 -> 3.14 phai bien dich C++
REM va hong. Uu tien: py -3.11, roi thu muc cai dat mac dinh cua 3.11, cuoi cung moi la "python".
set PY=
py -3.11 -c "pass" >nul 2>&1
if not errorlevel 1 set PY=py -3.11
if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY set PY=python
exit /b 0

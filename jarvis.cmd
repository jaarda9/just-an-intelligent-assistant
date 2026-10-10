@echo off
rem Talk to the running JARVIS from any terminal. Add this folder to PATH to use 'jarvis' anywhere.
"%~dp0.venv\Scripts\python.exe" "%~dp0jarvis_cli.py" %*

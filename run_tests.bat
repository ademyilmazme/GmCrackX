@echo off
call C:\ProgramData\miniconda3\Scripts\activate.bat gmcrackx
python -m pytest tests/test_ansys_rst_reader.py -v %*

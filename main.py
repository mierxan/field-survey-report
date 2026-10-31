"""Start the Field Survey Report program.

PyCharm runs this file (main.py). The program itself is in
field_survey_report.py, which sits in the same folder.
"""
import runpy
from pathlib import Path

runpy.run_path(
    str(Path(__file__).resolve().with_name("field_survey_report.py")),
    run_name="__main__",
)

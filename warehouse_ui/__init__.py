"""The application shell (navigation sidebar + modules) and the warehouse
pages. field_survey_report.py builds its inspection form as before and then
calls install(ctx); the form becomes the "Inspection Reports" module."""

from .shell import install  # noqa: F401

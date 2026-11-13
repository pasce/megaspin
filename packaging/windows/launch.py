"""Entry point for the Windows executable (PyInstaller). Imports the package so relative imports work."""
from megaspin.__main__ import main

raise SystemExit(main())

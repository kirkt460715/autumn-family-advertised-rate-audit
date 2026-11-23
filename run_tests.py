#!/usr/bin/env python3
"""隔离模式下的测试入口，等价于 `python -m unittest discover -s tests -v`。"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

loader = unittest.TestLoader()
suite = loader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)

#!/usr/bin/env python3
"""隔离模式（python3 -I）下的复核入口。

用法：
    python3 -I run_audit.py --data data
    python3 -I run_audit.py --data data --json

-I 不读取 PYTHONPATH 也不把当前工作目录加入 sys.path；脚本模式会把本文件
所在目录（仓库根）置于 sys.path[0]，因此可以正常 import audit 包。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit.report import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())

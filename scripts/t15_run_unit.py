"""Run all T15 unit-test files (avoids CLI wrapper)."""
import os
import sys

sys.path.insert(0, os.getcwd())

import pytest

if __name__ == "__main__":
    code = pytest.main([
        "tests/test_t15_code_core.py",
        "tests/test_t15_code_runner.py",
        "tests/test_t15_code_security.py",
        "tests/test_t15_code_multiskill.py",
        "-q", "-p", "no:cacheprovider",
        "--basetemp=tests/.pytest_tmp",
    ])
    print("UNIT_EXIT", code)
    raise SystemExit(code)

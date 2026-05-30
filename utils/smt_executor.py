from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path

from core.exceptions import Z3ExecutionError


class SMTExecutor:
    """SMT-LIB V2代码执行器，通过Z3求解器执行"""

    def __init__(self, z3_path: str | None = None, timeout: int = 30) -> None:
        self.z3_path = z3_path or "z3"
        self.timeout = timeout

    def execute(self, code: str) -> tuple[bool, str, float]:
        """执行SMT-LIB V2代码

        Args:
            code: SMT-LIB V2代码内容

        Returns:
            (是否可执行, 执行输出, 耗时毫秒)
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".smt2", delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            start = time.perf_counter()
            result = subprocess.run(
                [self.z3_path, temp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000

            if result.returncode != 0:
                return False, result.stderr.strip() or result.stdout.strip(), elapsed_ms

            output = result.stdout.strip()
            return True, output, elapsed_ms

        except subprocess.TimeoutExpired:
            return False, f"执行超时（{self.timeout}s）", self.timeout * 1000.0
        except FileNotFoundError as e:
            raise Z3ExecutionError(
                f"Z3求解器未找到，请确保z3已安装并在PATH中: {e}"
            ) from e
        except Exception as e:
            raise Z3ExecutionError(f"执行SMT-LIB V2代码失败: {e}") from e
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def check_syntax(self, code: str) -> tuple[bool, list[str]]:
        """检查SMT-LIB V2代码的语法

        Args:
            code: SMT-LIB V2代码内容

        Returns:
            (语法是否正确, 错误信息列表)
        """
        is_executable, output, _ = self.execute(code)
        if is_executable:
            return True, []
        return False, [output]

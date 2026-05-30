from __future__ import annotations

from pathlib import Path

from core.schemas import EvaluationResult, OutputResult, SMTLibCode


def _write_text(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


class OutputModule:
    """输出模块：生成包含SMT-LIB V2代码和评估结果的最终输出文件"""

    def __init__(self, output_dir: str, run_id: str = "") -> None:
        self.output_dir = str(Path(output_dir) / run_id) if run_id else output_dir
        _ensure_dir(self.output_dir)

    def generate_output(
        self,
        code: SMTLibCode,
        evaluation: EvaluationResult,
        output_name: str = "output",
    ) -> OutputResult:
        """生成最终输出文件

        将评估结果以注释形式写入SMT-LIB V2代码文件末尾，提高可解释性
        """
        comment_lines = self._format_comments(code, evaluation)
        full_content = code.code + "\n\n" + comment_lines

        file_path = str(Path(self.output_dir) / f"{output_name}.smt2")
        _write_text(file_path, full_content)

        return OutputResult(
            code=code,
            evaluation=evaluation,
            file_path=file_path,
        )

    def _format_comments(self, code: SMTLibCode, evaluation: EvaluationResult) -> str:
        """将评估结果格式化为SMT注释"""
        lines = [
            "; ===== 评估结果 =====",
            f"; 总体结论: {'全部满足' if evaluation.all_satisfied else '存在不满足'}",
            f"; 满足: {evaluation.satisfied_count}/{evaluation.not_satisfied_count + evaluation.satisfied_count}",
            "; -------------------",
        ]

        for item in evaluation.items:
            status_str = "满足" if item.status == "satisfied" else "不满足"
            lines.append(f"; 约束 {item.constraint_id}: {status_str}")
            if item.reason:
                for r_line in item.reason.split("\n"):
                    lines.append(f";   {r_line.strip()}")

        lines.append("; ===== 评估结束 =====")
        return "\n".join(lines)

    def generate_error_output(
        self,
        error_message: str,
        output_name: str = "error",
    ) -> OutputResult:
        """生成错误输出"""
        code = SMTLibCode(code="; 代码生成失败")
        evaluation = EvaluationResult(
            items=[],
            all_satisfied=False,
            summary=f"错误: {error_message}",
        )
        return self.generate_output(code, evaluation, output_name)

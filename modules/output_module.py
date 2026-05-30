from __future__ import annotations

from pathlib import Path

from core.schemas import ConstraintsList, EvaluationResult, OutputResult, SMTLibCode


def _write_text(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content, encoding="utf-8")


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


class OutputModule:
    """输出模块：生成包含SMT-LIB V2代码和评估结果的最终输出文件"""

    def __init__(self, code_output_dir: str, run_id: str) -> None:
        self.code_dir = Path(code_output_dir) / run_id / "code"
        _ensure_dir(str(self.code_dir))

    def generate_output(
        self,
        code: SMTLibCode,
        evaluation: EvaluationResult,
        output_name: str = "output",
        constraints: ConstraintsList | None = None,
    ) -> OutputResult:
        """生成最终输出文件

        将评估结果以注释形式写入SMT-LIB V2代码文件末尾，提高可解释性
        """
        comment_lines = self._format_comments(code, evaluation, constraints)
        full_content = code.code + "\n\n" + comment_lines

        file_path = str(self.code_dir / f"{output_name}.smt2")
        _write_text(file_path, full_content)

        return OutputResult(
            code=code,
            evaluation=evaluation,
            file_path=file_path,
        )

    def _format_comments(
        self,
        code: SMTLibCode,
        evaluation: EvaluationResult,
        constraints: ConstraintsList | None = None,
    ) -> str:
        """将评估结果格式化为SMT注释，包含完整的约束描述"""
        lines = [
            "; ===== 约束定义 =====",
        ]

        # 按约束 ID 建立查找表
        constraint_map = {}
        if constraints:
            for c in constraints.constraints:
                constraint_map[c.id] = c.description

        for item in evaluation.items:
            cid = item.constraint_id
            desc = constraint_map.get(cid, "")
            lines.append(f";  {cid}: {desc}" if desc else f";  {cid}")

        lines.extend([
            "; ===== 评估结果 =====",
            f"; 总体结论: {'全部满足' if evaluation.all_satisfied else '存在不满足'}",
            f"; 满足: {evaluation.satisfied_count}/{evaluation.not_satisfied_count + evaluation.satisfied_count}",
            "; -------------------",
        ])

        for item in evaluation.items:
            status_str = "满足" if item.status == "satisfied" else "不满足"
            cid = item.constraint_id
            desc = constraint_map.get(cid, "")
            lines.append(f";  {cid} [{status_str}]: {desc}")
            if item.reason:
                for r_line in item.reason.split("\n"):
                    lines.append(f";    {r_line.strip()}")

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

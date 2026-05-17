from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from core.exceptions import ModuleError
from core.schemas import VerificationInput

logger = logging.getLogger(__name__)


class InputModule:
    """输入模块：加载验证指令和IAM配置，配对形成处理单元"""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = Path(data_dir)
        self.instruct_dir = self.data_dir / "instructs"
        self.account_dir = self.data_dir / "accounts"

        if not self.instruct_dir.exists():
            raise ModuleError(f"指令目录不存在: {self.instruct_dir}")
        if not self.account_dir.exists():
            raise ModuleError(f"账户配置目录不存在: {self.account_dir}")

    def load_all_pairs(self) -> list[VerificationInput]:
        """加载所有指令和配置，按编号配对

        配对规则：instruct_1_X.json ↔ account_1_X.json，按X的数字顺序一一对应
        如果某个账户文件缺失，则跳过对应的指令文件。
        """
        instruct_files = self._get_sorted_files(self.instruct_dir, "instruct_1_")
        account_index = {f.stem.replace("account_1_", ""): f
                         for f in self._get_sorted_files(self.account_dir, "account_1_")}

        pairs: list[VerificationInput] = []
        for inst_file in instruct_files:
            idx = inst_file.stem.replace("instruct_1_", "")
            acct_file = account_index.get(idx)
            if acct_file is None:
                logger.warning(f"账户文件缺失 (instruct={inst_file.name})，跳过")
                continue

            instruct_data = json.loads(inst_file.read_text(encoding="utf-8"))
            account_data = json.loads(acct_file.read_text(encoding="utf-8"))

            instruct_text = instruct_data["instruct"]
            account_id = account_data.get("account_id", "")
            instruct_id = inst_file.stem

            pairs.append(VerificationInput(
                instruction=instruct_text,
                account_data=account_data,
                instruct_id=instruct_id,
                account_id=account_id,
            ))

        if not pairs:
            raise ModuleError("没有找到任何有效的指令-配置配对")

        return pairs

    def load_single_pair(self, index: int) -> VerificationInput:
        """加载单个指定编号的配对（从1开始计数）"""
        instruct_path = self.instruct_dir / f"instruct_1_{index}.json"
        account_path = self.account_dir / f"account_1_{index}.json"

        if not instruct_path.exists():
            raise ModuleError(f"指令文件不存在: {instruct_path}")
        if not account_path.exists():
            raise ModuleError(f"账户文件不存在: {account_path}")

        instruct_data = json.loads(instruct_path.read_text(encoding="utf-8"))
        account_data = json.loads(account_path.read_text(encoding="utf-8"))

        return VerificationInput(
            instruction=instruct_data["instruct"],
            account_data=account_data,
            instruct_id=instruct_path.stem,
            account_id=account_data.get("account_id", ""),
        )

    def load_answers(self) -> list[bool]:
        """加载答案文件（正确结果标签）"""
        answer_path = self.data_dir / "answer_valid_permission.json"
        if not answer_path.exists():
            raise ModuleError(f"答案文件不存在: {answer_path}")
        return json.loads(answer_path.read_text(encoding="utf-8"))

    def _get_sorted_files(self, directory: Path, prefix: str) -> list[Path]:
        """获取目录下指定前缀的文件，按数字后缀排序"""
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)\.json$")
        files = []
        for f in directory.iterdir():
            m = pattern.match(f.name)
            if m:
                files.append((int(m.group(1)), f))
        files.sort(key=lambda x: x[0])
        return [f for _, f in files]

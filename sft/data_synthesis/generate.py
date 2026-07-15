#!/usr/bin/env python3
"""生成（验证指令 + IAM 配置）对，Python 负责 JSON 转义"""

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import runpy
from openai import OpenAI

PROMPT_DIR = Path(__file__).parent / "prompts"
OUTPUT_DIR = Path(__file__).parent / "output"

# 加载 .env
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

client = OpenAI(
    api_key=os.environ.get("DATASYNTH_API_KEY", ""),
    base_url=os.environ.get("DATASYNTH_API_URL", ""),
)
MODEL = os.environ.get("DATASYNTH_MODEL", "deepseek-v4-flash")

TOOL_PATH = Path(__file__).parent.parent.parent / "resources/scenarios/valid_permission/tools/generate_smt_from_policy/tool.py"
_tool_mod = runpy.run_path(str(TOOL_PATH))
gen_smt = _tool_mod["execute"]


def get_label(iam_config: dict) -> bool | None:
    try:
        constraints = json.dumps({"constraints": [{"id": "C1", "category": "policy_validity"}]})
        smt = gen_smt(json.dumps(iam_config, ensure_ascii=False), constraints)
        if smt.startswith("错误："):
            return None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".smt2", delete=False) as f:
            f.write(smt)
            fname = f.name
        out = subprocess.run(["z3", fname], capture_output=True, text=True, timeout=30)
        Path(fname).unlink(missing_ok=True)
        return any(l.startswith("sat") for l in out.stdout.strip().lower().split("\n"))
    except Exception:
        return None


def escape_policy(policy_dict: dict) -> str:
    """将策略 dict 转为转义后的 JSON 字符串"""
    return json.dumps(policy_dict, ensure_ascii=False)


def iam_config_from_parts(parts: dict) -> dict:
    """从 LLM 输出的部件构造完整的 iam_config"""
    cfg = {"account_id": "0123456789abcdef0123456789abcdef"}
    if "buckets" in parts:
        cfg["buckets"] = {
            "bucket_name": parts["buckets"].get("bucket_name", "synthetic-bucket"),
            "bucket_policy": escape_policy(parts["buckets"]["policy"]),
            "bucket_acl": '<?xml version="1.0" encoding="UTF-8"?>',
        }
    elif "agencies" in parts:
        a = parts["agencies"]
        cfg["agencies"] = {
            "agency_name": a.get("agency_name", "test-agency"),
            "agency_id": a.get("agency_id", "00000000-0000-0000-0000-000000000000"),
            "attached_policy_ids": [],
            "trust_policy": escape_policy(a["trust_policy"]),
        }
    return cfg


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--output", type=str, default="synthetic_dataset")
    args = parser.parse_args()

    out_dir = OUTPUT_DIR / args.output
    instruct_dir = out_dir / "instructs"
    account_dir = out_dir / "accounts"
    instruct_dir.mkdir(parents=True, exist_ok=True)
    account_dir.mkdir(parents=True, exist_ok=True)

    system = (PROMPT_DIR / "system.md").read_text()
    user = (PROMPT_DIR / "user.md").read_text().replace("{{ count }}", str(args.count))

    print(f"调用 LLM 生成 {args.count} 条...")
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.7,
        max_tokens=131072,
    )
    text = resp.choices[0].message.content or ""

    m = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'(\[[\s\S]*?\])', text)
        data = json.loads(m.group(1)) if m else []

    pairs = data if isinstance(data, list) else [data]
    pairs = [p for p in pairs if p.get("instruction") and p.get("config")][:args.count]

    answers = []
    for i, pair in enumerate(pairs):
        idx = i + 1
        iid = f"instruct_1_{idx}"
        config_parts = pair["config"]
        fmt = "agencies" if "agencies" in config_parts else "buckets"

        try:
            iam_cfg = iam_config_from_parts(config_parts)
        except Exception as e:
            print(f"  [{idx}] ⚠️  构造失败: {e}")
            answers.append(None)
            continue

        sub_scenario = "agency_trust_policy" if fmt == "agencies" else "bucket_policy"
        (instruct_dir / f"{iid}.json").write_text(json.dumps({
            "scenario": "valid_permission",
            "sub_scenario": sub_scenario,
            "instruct": pair["instruction"],
        }, indent=2, ensure_ascii=False), encoding="utf-8")

        (account_dir / f"account_1_{idx}.json").write_text(json.dumps(iam_cfg, indent=2, ensure_ascii=False), encoding="utf-8")

        label = get_label(iam_cfg)
        if label is None:
            print(f"  [{idx}] ⚠️  无法判断 label")
            answers.append(None)
        else:
            answers.append(label)
            print(f"  [{idx}] {'✓' if label else '✗'} {pair['instruction'][:60]}")

    (out_dir / "answer_valid_permission.json").write_text(json.dumps(answers, ensure_ascii=False), encoding="utf-8")

    print(f"\n完成: {len(pairs)} 条")
    t = sum(1 for a in answers if a)
    f = sum(1 for a in answers if a is False)
    n = sum(1 for a in answers if a is None)
    print(f"  True: {t}  False: {f}  未知: {n}")


if __name__ == "__main__":
    main()

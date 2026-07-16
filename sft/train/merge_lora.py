#!/usr/bin/env python3
"""合并 LoRA adapter 到基座模型，生成完整模型文件"""

import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModel, AutoTokenizer

BASE_MODEL = "Qwen/Qwen3.5-9B"
LORA_PATH = Path(__file__).parent / "output"  # LoRA adapter 目录
OUTPUT_DIR = Path("/root/autodl-fs/qwen9b-merged")


def merge(lora_folder: str):
    lora_dir = LORA_PATH / lora_folder / "lora_adapter"
    if not lora_dir.exists():
        print(f"找不到 LoRA: {lora_dir}")
        sys.exit(1)

    out_dir = OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"加载基座模型: {BASE_MODEL}")
    model = AutoModel.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    print(f"加载 LoRA adapter: {lora_dir}")
    model = PeftModel.from_pretrained(model, str(lora_dir))

    print("合并权重...")
    model = model.merge_and_unload()

    print(f"保存到: {out_dir}")
    model.save_pretrained(str(out_dir), safe_serialization=True)

    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    tokenizer.save_pretrained(str(out_dir))

    # 修正 config.json 以兼容 vLLM
    import json
    config_path = out_dir / "config.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
        config["model_type"] = "qwen3_5"
        config["architectures"] = ["Qwen3_5ForCausalLM"]
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False))
        print(f"config.json 已修正")

    # 复制 vLLM 需要的辅助配置文件
    from transformers.utils import cached_file
    import shutil
    for extra in ["preprocessor_config.json", "generation_config.json"]:
        try:
            cf = cached_file(BASE_MODEL, extra)
            if cf:
                shutil.copy2(cf, out_dir / extra)
                print(f"已复制: {extra}")
        except Exception as e:
            print(f"  跳过 {extra}: {e}")

    print(f"完成! 合并后的模型在: {out_dir}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--lora", required=True, help="LoRA 目录名，如 20260716_143025")
    parser.add_argument("--output", default=str(OUTPUT_DIR), help="输出目录")
    args = parser.parse_args()
    OUTPUT_DIR = Path(args.output)
    merge(args.lora)

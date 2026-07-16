#!/usr/bin/env python3
"""合并 LoRA adapter 到基座模型，生成完整模型文件"""

import sys
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

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
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

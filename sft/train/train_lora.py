#!/usr/bin/env python3
"""LoRA 微调 Qwen3.5-9B

从 YAML 读取配置，训练模型学会正确调用工具生成 SMT 代码。
"""

import json
import os
import random
import sys
from pathlib import Path

import torch
import wandb
import yaml
from datasets import Dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)

BASE_DIR = Path(__file__).parent


def load_config(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_traces(data_dir: Path) -> list[dict]:
    samples = []
    for fpath in sorted(data_dir.glob("*.json")):
        try:
            data = json.loads(fpath.read_text())
            msgs = data.get("messages", [])
            if not msgs:
                continue
            if not any(m.get("tool_calls") for m in msgs):
                continue
            samples.append({"messages": msgs})
        except Exception:
            continue
    return samples


def split_data(samples: list[dict], ratios: tuple[float, float, float]):
    random.shuffle(samples)
    n = len(samples)
    n1 = int(n * ratios[0])
    n2 = int(n * (ratios[0] + ratios[1]))
    return samples[:n1], samples[n1:n2], samples[n2:]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="config.yaml",
                        help="配置文件路径，相对于 sft/train/ 目录")
    args = parser.parse_args()

    config_path = BASE_DIR / args.config
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    cfg = load_config(str(config_path))
    run_name = cfg["wandb"]["run_name"] or f"lora_r{cfg['lora']['r']}_lr{cfg['training']['learning_rate']}"
    output_dir = BASE_DIR / cfg["output"]["dir"] / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["WANDB_PROJECT"] = cfg["wandb"]["project"]

    # 1. 数据
    data_dir = BASE_DIR / cfg["data"]["path"]
    print(f"加载数据: {data_dir}")
    samples = load_traces(data_dir)
    print(f"  共 {len(samples)} 条 trace")
    ratios = (cfg["data"]["train_ratio"], cfg["data"]["valid_ratio"], cfg["data"]["test_ratio"])
    train_data, valid_data, test_data = split_data(samples, ratios)
    print(f"  训练: {len(train_data)}  验证: {len(valid_data)}  测试: {len(test_data)}")

    # 2. Tokenizer
    model_name = cfg["model"]["name"]
    print(f"加载 tokenizer: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=cfg["model"]["trust_remote_code"],
        padding_side="right",
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # 3. 模型
    print(f"加载模型: {model_name}")
    dtype = torch.bfloat16 if cfg["model"]["torch_dtype"] == "bfloat16" else torch.float16
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=dtype,
        device_map=cfg["model"]["device_map"],
        trust_remote_code=cfg["model"]["trust_remote_code"],
    )

    # 4. LoRA
    lc = cfg["lora"]
    print("配置 LoRA...")
    lora_config = LoraConfig(
        r=lc["r"],
        lora_alpha=lc["alpha"],
        target_modules=lc["target_modules"],
        lora_dropout=lc["dropout"],
        bias=lc["bias"],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 5. 数据处理
    def tokenize_fn(examples):
        texts = [
            tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            for msgs in examples["messages"]
        ]
        tokenized = tokenizer(
            texts,
            truncation=True,
            max_length=cfg["model"]["max_length"],
            padding=False,
        )
        tokenized["labels"] = tokenized["input_ids"].copy()
        return tokenized

    train_dataset = Dataset.from_list(train_data).map(
        tokenize_fn, batched=True, remove_columns=["messages"]
    )
    valid_dataset = Dataset.from_list(valid_data).map(
        tokenize_fn, batched=True, remove_columns=["messages"]
    )
    test_dataset = Dataset.from_list(test_data).map(
        tokenize_fn, batched=True, remove_columns=["messages"]
    )

    # 6. 训练参数
    tc = cfg["training"]
    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=tc["batch_size"],
        per_device_eval_batch_size=tc["batch_size"],
        gradient_accumulation_steps=tc["grad_accumulation_steps"],
        gradient_checkpointing=tc["gradient_checkpointing"],
        bf16=tc["bf16"],
        optim=tc["optim"],
        learning_rate=tc["learning_rate"],
        lr_scheduler_type=tc.get("lr_scheduler_type", "linear"),
        warmup_ratio=tc.get("warmup_ratio", 0.0),
        num_train_epochs=tc["num_epochs"],
        logging_steps=tc["logging_steps"],
        eval_strategy="steps",
        eval_steps=tc["eval_steps"],
        save_strategy="steps",
        save_steps=tc["save_steps"],
        save_total_limit=tc["save_total_limit"],
        report_to="wandb",
        run_name=run_name,
        remove_unused_columns=tc["remove_unused_columns"],
        dataloader_num_workers=tc["dataloader_workers"],
    )

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        max_length=cfg["model"]["max_length"],
    )

    # 7. Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        data_collator=data_collator,
        tokenizer=tokenizer,
    )

    # 8. 训练
    print("\n开始训练...")
    trainer.train()

    # 9. 保存
    adapter_dir = output_dir / "lora_adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"LoRA adapter 保存到: {adapter_dir}")

    # 10. 测试评估
    print("\n测试集评估...")
    test_results = trainer.evaluate(test_dataset)
    print(f"测试集 loss: {test_results.get('eval_loss', 'N/A')}")
    wandb.log({"test/" + k: v for k, v in test_results.items()})

    print(f"\n完成! 结果: {output_dir}")
    wandb.finish()


if __name__ == "__main__":
    main()

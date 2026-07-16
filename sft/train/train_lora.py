#!/usr/bin/env python3
"""LoRA 微调 Qwen3.5-9B

从 YAML 读取配置，训练模型学会正确调用工具生成 SMT 代码。
"""

import json
import os
import random
import sys
from pathlib import Path

import gc
import torch
import wandb
import yaml
from datasets import Dataset
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    TrainerCallback,
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
    from datetime import datetime
    run_name = cfg["wandb"]["run_name"] or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = BASE_DIR / cfg["output"]["dir"] / run_name
    output_dir.mkdir(parents=True, exist_ok=True)

    os.environ["WANDB_PROJECT"] = cfg["wandb"]["project"]
    if cfg["wandb"].get("entity"):
        os.environ["WANDB_ENTITY"] = cfg["wandb"]["entity"]

    # 限制 CUDA 显存上限，防止缓存预留占用过多
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True,max_split_size_mb:128")
    if torch.cuda.is_available():
        torch.cuda.set_per_process_memory_fraction(0.80)  # 47GB × 0.65 ≈ 30GB
        print(f"  显存上限: {torch.cuda.get_device_properties(0).total_memory * 0.65 / 1e9:.0f}GB")

    # 固定随机种子
    seed = cfg.get("seed", 42)
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

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
    model_kwargs = dict(
        device_map=cfg["model"]["device_map"],
        trust_remote_code=cfg["model"]["trust_remote_code"],
        attn_implementation="flash_attention_2",
    )
    if cfg["model"].get("offload_folder"):
        model_kwargs["offload_folder"] = cfg["model"]["offload_folder"]
    if cfg["model"].get("load_in_4bit"):
        from transformers import BitsAndBytesConfig
        model_kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_quant_type="nf4",
        )
        model_kwargs["torch_dtype"] = torch.bfloat16
    else:
        dtype = torch.bfloat16 if cfg["model"]["torch_dtype"] == "bfloat16" else torch.float16
        model_kwargs["torch_dtype"] = dtype

    model = AutoModelForCausalLM.from_pretrained(model_name, **model_kwargs)
    if torch.cuda.is_available():
        print(f"  模型加载后显存: {torch.cuda.memory_allocated()/1e9:.1f} GB")

    # 4. LoRA
    lc = cfg["lora"]
    print("配置 4bit training...")
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)

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
    if torch.cuda.is_available():
        print(f"  LoRA配置后显存: {torch.cuda.memory_allocated()/1e9:.1f} GB")

    # 5. 数据处理（mask 非 assistant 部分的 label）
    def tokenize_fn(examples):
        all_input_ids = []
        all_labels = []
        for msgs in examples["messages"]:
            text = tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            encoded = tokenizer(text, truncation=True, max_length=cfg["model"]["max_length"])
            input_ids = encoded["input_ids"]
            labels = [-100] * len(input_ids)

            # 定位 assistant 回复的 token 范围，保留其 label
            assistant_token = "<|im_start|>assistant"
            assistant_ids = tokenizer.encode(assistant_token, add_special_tokens=False)
            as_len = len(assistant_ids)

            # 从后往前找每个 assistant 回复
            pos = 0
            while True:
                # 找 assistant token 序列
                start = -1
                for i in range(pos, len(input_ids) - as_len + 1):
                    if input_ids[i:i+as_len] == assistant_ids:
                        start = i
                        break
                if start == -1:
                    break
                # assistant 回复从 <|im_start|>assistant 开始到下一个 <|im_start|> 或结尾
                end = len(input_ids)
                for i in range(start + as_len, len(input_ids)):
                    if input_ids[i] == tokenizer.encode("<|im_start|>", add_special_tokens=False)[0]:
                        end = i
                        break
                # 保留 assistant 回复部分的 label（从 assistant token 开始）
                for i in range(start, end):
                    labels[i] = input_ids[i]
                pos = end

            all_input_ids.append(input_ids)
            all_labels.append(labels)

        return {"input_ids": all_input_ids, "labels": all_labels, "attention_mask": [[1]*len(ids) for ids in all_input_ids]}

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
        seed=seed,
        per_device_train_batch_size=tc["batch_size"],
        per_device_eval_batch_size=tc["batch_size"],
        gradient_accumulation_steps=tc["grad_accumulation_steps"],
        gradient_checkpointing=tc["gradient_checkpointing"],
        gradient_checkpointing_kwargs={"use_reentrant": False},
        bf16=tc["bf16"],
        optim=tc["optim"],
        learning_rate=float(tc["learning_rate"]),
        lr_scheduler_type=tc.get("lr_scheduler_type", "linear"),
        warmup_ratio=float(tc.get("warmup_ratio", 0.0)),
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

    # 7. Test evaluation callback
    test_eval_interval = tc.get("test_eval_steps", 0)

    class TestEvalCallback(TrainerCallback):
        def on_step_begin(self, args, state, control, **kwargs):
            if state.global_step % 1 == 0:
                a = torch.cuda.memory_allocated() / 1e9
                r = torch.cuda.memory_reserved() / 1e9
                print(f"  [step {state.global_step:>4d}] alloc={a:.1f}GB | reserved={r:.1f}GB")

        def on_step_end(self, args, state, control, **kwargs):
            if state.global_step <= 5 or state.global_step % 10 == 0:
                gc.collect()
                torch.cuda.empty_cache()
            if test_eval_interval and state.global_step % test_eval_interval == 0 and state.global_step > 0:
                m = trainer.evaluate(test_dataset)
                wandb.log({"test/loss": m.get("eval_loss")}, step=state.global_step)
                print(f"  [step {state.global_step}] test_loss: {m.get('eval_loss', 'N/A')}")

    # 8. Trainer
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=valid_dataset,
        data_collator=data_collator,
        callbacks=[TestEvalCallback()] if test_eval_interval else None,
    )

    # 8. 训练
    print("\n开始训练...")
    trainer.train()

    # 9. 保存
    adapter_dir = output_dir / "lora_adapter"
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    print(f"LoRA adapter 保存到: {adapter_dir}")

    print(f"\n完成! 结果: {output_dir}")
    wandb.finish()


if __name__ == "__main__":
    main()

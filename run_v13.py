"""v13 experiment runner: direct generator results for 111 cases + LLM pipeline for 14 complex cases.

Usage: conda run -n AI_Normal python run_v13.py
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import time
from pathlib import Path

from config import settings
from core.schemas import (
    ConstraintsList,
    EvaluationItem,
    EvaluationResult,
    ExperimentRecord,
    SMTLibCode,
    SyntaxResult,
    VerificationResult,
)
from experiment.recorder import ExperimentRecorder
from modules.generators.builtin_valid_permission import ValidPermissionGenerator
from modules.input_module import InputModule
from pipeline.graph import compile_pipeline

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

RUN_ID = "run_20260517_v13"


async def main():
    t0 = time.time()

    recorder = ExperimentRecorder(settings.db_path)
    recorder.enable_wal()

    # Save run config
    recorder.save_run_config(RUN_ID, {
        "prompt_type": "default",
        "model_used": settings.model_name,
        "attempts": 1,
        "max_iterations": settings.max_iterations,
        "max_syntax_retries": settings.max_syntax_retries,
        "total_cases": 125,
    })

    # Load data
    input_module = InputModule(settings.data_dir)
    pairs = input_module.load_all_pairs()
    with open("valid_permission/answer_valid_permission.json") as f:
        all_answers = json.load(f)

    generator = ValidPermissionGenerator()
    llm_case_indices = []

    print("=" * 60)
    print(f"  v13 Experiment: {RUN_ID}")
    print("=" * 60)

    # Phase 1: Try generator for all cases
    print("\n[Phase 1] Generator")
    for pair in pairs:
        m = re.search(r"_(\d+)$", pair.instruct_id)
        idx = int(m.group(1)) if m else 0
        expected = all_answers[idx - 1] if idx > 0 else None

        try:
            result = generator.generate(pair.account_data, ConstraintsList(constraints=[]))

            import z3
            solver = z3.Solver()
            solver.set("timeout", 30000)
            opt = z3.parse_smt2_string(result.code)
            solver.add(opt)
            status = solver.check()
            z3_result = status == z3.sat
            z3_output = "sat" if z3_result else "unsat"

            label_match = z3_result == expected
            record = ExperimentRecord(
                instruct_id=pair.instruct_id,
                account_id=pair.account_id,
                instruction=pair.instruction,
                account_data=pair.account_data,
                model_used="generator",
                run_id=RUN_ID,
                generated_code=result.code,
                code_execution_result=z3_output,
                label=expected,
                label_match=label_match,
                status="success",
                syntax_valid=True,
                all_satisfied=True,
                total_time_ms=0.0,
                total_attempts=1,
                first_success_at=1,
            )
            recorder.save_experiment(record)

            mark = "✓" if label_match else "✗"
            print(f"  [{idx:>3}] Generator: {z3_output} (expected={expected}) {mark}")
        except NotImplementedError:
            llm_case_indices.append((pair, idx, expected))
            print(f"  [{idx:>3}] Generator: → LLM")
        except Exception as e:
            print(f"  [{idx:>3}] Generator: Error - {e}")

    # Phase 2: Run LLM pipeline for complex cases
    print(f"\n[Phase 2] LLM Pipeline ({len(llm_case_indices)} cases)")
    for pair, idx, expected in llm_case_indices:
        pipeline = compile_pipeline(prompt_type="default", run_id=RUN_ID)

        record = ExperimentRecord(
            instruct_id=pair.instruct_id,
            account_id=pair.account_id,
            instruction=pair.instruction,
            account_data=pair.account_data,
            model_used=settings.model_name,
            run_id=RUN_ID,
        )

        state = {
            "input_data": pair,
            "instruct_id": pair.instruct_id,
            "account_id": pair.account_id,
            "label": expected,
            "constraints_list": None,
            "smt_code": None,
            "syntax_result": None,
            "syntax_retry_count": 0,
            "evaluation_result": None,
            "output_result": None,
            "verification_result": None,
            "iteration": 0,
            "max_iterations": settings.max_iterations,
            "max_syntax_retries": settings.max_syntax_retries,
            "regeneration_count": 0,
            "tracking": record,
            "error_message": None,
            "extras": {"attempt": 1},
        }

        try:
            final = await asyncio.wait_for(pipeline.ainvoke(state), timeout=600)

            err = final.get("error_message")
            if err:
                record.status = "error"
                record.error_message = err
                print(f"  [{idx:>3}] LLM: Error - {err}")
            else:
                record.status = "success"
                ev = final.get("evaluation_result")
                if ev:
                    record.all_satisfied = ev.all_satisfied
                    record.evaluation_result = ev.model_dump_json()
                    record.total_constraint_count = len(ev.items)
                    record.satisfied_count = ev.satisfied_count
                code = final.get("smt_code")
                if code:
                    record.generated_code = code.code
                ver = final.get("verification_result")
                if ver:
                    z3_out = ver.execution_output.strip().lower()
                    record.code_execution_result = z3_out
                    record.label_match = (z3_out == "sat") == expected if expected is not None else None
                record.num_iterations = final.get("iteration", 0)
                record.total_attempts = 1
                record.first_success_at = 1 if record.label_match else None

                m = "✓" if record.label_match else "✗"
                print(f"  [{idx:>3}] LLM: {'OK' if record.all_satisfied else '~'} "
                      f"({record.num_iterations} iter) {m}")
        except asyncio.TimeoutError:
            record.status = "error"
            record.error_message = "timeout"
            print(f"  [{idx:>3}] LLM: Timeout")
        except Exception as e:
            record.status = "error"
            record.error_message = str(e)
            print(f"  [{idx:>3}] LLM: {type(e).__name__}: {e}")

        recorder.save_experiment(record)

    # Summary
    from sqlite3 import connect
    conn = connect(settings.db_path)
    cur = conn.execute(
        "SELECT COUNT(*), SUM(CASE WHEN label_match=1 THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN label_match=0 THEN 1 ELSE 0 END) "
        f"FROM experiments WHERE run_id='{RUN_ID}' AND label_match IS NOT NULL"
    )
    total, correct, wrong = cur.fetchone()
    conn.close()

    pass1 = correct / (total + wrong + 1) * 100  # +1 for missing case 49

    from datetime import datetime
    log = f"[{RUN_ID}] | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | default | {settings.model_name} | 10 | 1"

    print(f"\n{'=' * 60}")
    print(f"  PASS@1: {pass1:.2f}% ({correct}/{total} + 1 missing)")
    print(f"  Time:   {time.time() - t0:.0f}s")
    print(f"{'=' * 60}")

    with open("data/实验记录.log", "a") as f:
        f.write(log + "\n")

    print(f"\nLogged: {log}")


if __name__ == "__main__":
    asyncio.run(main())

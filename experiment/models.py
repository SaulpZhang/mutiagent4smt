"""SQLite数据库模型定义

存储实验记录和基准实验记录。
"""

CREATE_TABLE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    run_id TEXT,
    instruct_id TEXT,
    account_id TEXT,
    instruction TEXT,
    account_data TEXT,
    constraints_list TEXT,
    constraint_text TEXT,
    generated_code TEXT,
    syntax_valid INTEGER,
    syntax_error_info TEXT,
    code_execution_result TEXT,
    evaluation_result TEXT,
    all_satisfied INTEGER,
    satisfied_count INTEGER DEFAULT 0,
    total_constraint_count INTEGER DEFAULT 0,
    label_match INTEGER,
    num_iterations INTEGER DEFAULT 0,
    num_syntax_retries INTEGER DEFAULT 0,
    label INTEGER,
    model_used TEXT,
    total_time_ms REAL DEFAULT 0.0,
    total_attempts INTEGER DEFAULT 1,
    first_success_at INTEGER,
    stages TEXT,
    status TEXT DEFAULT 'success',
    error_message TEXT,
    timestamp TEXT
)
"""

CREATE_TABLE_METRICS = """
CREATE TABLE IF NOT EXISTS metrics_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_name TEXT,
    metric_type TEXT,
    metric_value REAL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

CREATE_TABLE_EXPERIMENT_RUNS = """
CREATE TABLE IF NOT EXISTS experiment_runs (
    run_id TEXT PRIMARY KEY,
    prompt_type TEXT DEFAULT 'default',
    model_used TEXT,
    parallel INTEGER DEFAULT 1,
    attempts INTEGER DEFAULT 1,
    gen_mode INTEGER DEFAULT 1,
    max_iterations INTEGER DEFAULT 10,
    max_syntax_retries INTEGER DEFAULT 5,
    total_cases INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
)
"""

# 迁移SQL：为已有 experiment_runs 表添加 gen_mode 列（幂等）
ALTER_TABLE_ADD_GEN_MODE = """
ALTER TABLE experiment_runs ADD COLUMN gen_mode INTEGER DEFAULT 1
"""

ALL_TABLES = [
    CREATE_TABLE_EXPERIMENTS,
    CREATE_TABLE_METRICS,
    CREATE_TABLE_EXPERIMENT_RUNS,
]

# 数据库迁移脚本（幂等，已存在的列会静默跳过）
MIGRATIONS = [
    ALTER_TABLE_ADD_GEN_MODE,
]

"""SQLite数据库模型定义

存储实验记录和基准实验记录。
"""

CREATE_TABLE_EXPERIMENTS = """
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    instruct_id TEXT,
    account_id TEXT,
    instruction TEXT,
    account_data TEXT,
    constraints_list TEXT,
    generated_code TEXT,
    syntax_valid INTEGER,
    syntax_error_info TEXT,
    code_execution_result TEXT,
    evaluation_result TEXT,
    all_satisfied INTEGER,
    num_iterations INTEGER DEFAULT 0,
    num_syntax_retries INTEGER DEFAULT 0,
    label INTEGER,
    model_used TEXT,
    total_time_ms REAL DEFAULT 0.0,
    stages TEXT,
    status TEXT DEFAULT 'success',
    error_message TEXT,
    timestamp TEXT
)
"""

CREATE_TABLE_BENCHMARKS = """
CREATE TABLE IF NOT EXISTS benchmarks (
    id TEXT PRIMARY KEY,
    instruct_id TEXT,
    code_form TEXT,
    prompt_type TEXT,
    generated_code TEXT,
    is_correct INTEGER,
    execution_result TEXT,
    generation_time_ms REAL DEFAULT 0.0,
    model_used TEXT,
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

ALL_TABLES = [
    CREATE_TABLE_EXPERIMENTS,
    CREATE_TABLE_BENCHMARKS,
    CREATE_TABLE_METRICS,
]

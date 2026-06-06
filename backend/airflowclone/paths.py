from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DAGS_DIR = PROJECT_ROOT / "dags"
RUNS_DIR = PROJECT_ROOT / "runs"
DB_PATH = PROJECT_ROOT / "airflowclone.db"


def run_dir(run_id: str) -> Path:
    p = RUNS_DIR / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_output_path(run_id: str, task_id: str) -> Path:
    return run_dir(run_id) / f"{task_id}.json"


def task_log_path(run_id: str, task_id: str, attempt: int) -> Path:
    return run_dir(run_id) / f"{task_id}.{attempt}.log"

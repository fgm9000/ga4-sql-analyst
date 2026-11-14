"""Generate quality baseline metrics for the repository."""

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SUPPRESSION_PATTERN = re.compile(
    r"(#\s*noqa|#\s*type:\s*ignore|pragma:\s*no\s*cover|pyright:\s*ignore)"
)
SUPPRESSION_DIRS = ("src", "tests", "scripts", "evals", "spikes")
STRICT_MYPY_DIRS = ("scripts", "evals", "spikes")
PYTEST_COUNT = re.compile(r"(\d+) (passed|skipped|failed|errors?)\b")

Metrics = dict[str, int | float | str]


def measure_ruff(repo_root: Path) -> int:
    """Measure number of ruff lint problems."""
    cmd = [sys.executable, "-m", "ruff", "check", ".", "--output-format=json"]
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"ruff check failed with code {proc.returncode}:\n{proc.stderr}")
    try:
        data = json.loads(proc.stdout) if proc.stdout.strip() else []
        return len(data)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Failed to parse ruff output: {exc}") from exc


def _count_mypy_errors(cmd: list[str], repo_root: Path) -> int:
    """Run a mypy command and count its reported error lines."""
    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise RuntimeError(f"mypy failed with code {proc.returncode}:\n{proc.stderr}")
    error_lines = [line for line in proc.stdout.splitlines() if ": error:" in line]
    if proc.returncode == 1 and not error_lines:
        raise RuntimeError(f"mypy exited with code 1 but no error lines found:\n{proc.stdout}")
    return len(error_lines)


def measure_mypy(repo_root: Path) -> int:
    """Measure number of mypy errors: project config run plus strict run on tooling dirs."""
    project_errors = _count_mypy_errors([sys.executable, "-m", "mypy"], repo_root)

    strict_targets = [d for d in STRICT_MYPY_DIRS if (repo_root / d).exists()]
    strict_errors = 0
    if strict_targets:
        strict_errors = _count_mypy_errors(
            [sys.executable, "-m", "mypy", "--strict", *strict_targets], repo_root
        )

    return project_errors + strict_errors


def _parse_pytest_counts(stdout: str) -> tuple[int, int]:
    """Read passed/skipped counts from the final pytest summary line (no XML parsing)."""
    lines = [line for line in stdout.splitlines() if PYTEST_COUNT.search(line)]
    summary = lines[-1] if lines else ""
    counts = {kind: int(number) for number, kind in PYTEST_COUNT.findall(summary)}
    return counts.get("passed", 0), counts.get("skipped", 0)


def measure_tests_and_coverage(repo_root: Path) -> tuple[int, int, float]:
    """Measure tests passed, tests skipped, and coverage percent using pytest."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        cov_json_path = tmp_path / "coverage.json"
        cov_data_path = tmp_path / ".coverage"

        env = os.environ.copy()
        env["COVERAGE_FILE"] = str(cov_data_path)

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            "--cov=ga4_sql_analyst",
            f"--cov-report=json:{cov_json_path}",
            "-q",
        ]
        proc = subprocess.run(
            cmd,
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

        root_coverage = repo_root / ".coverage"
        if root_coverage.exists():
            root_coverage.unlink(missing_ok=True)

        if proc.returncode != 0:
            raise RuntimeError(
                f"pytest suite must be green, failed with code {proc.returncode}:\n"
                f"{proc.stdout}\n{proc.stderr}"
            )

        if not cov_json_path.exists():
            raise RuntimeError("coverage json report was not generated.")

        passed_count, skipped_count = _parse_pytest_counts(proc.stdout)

        cov_data = json.loads(cov_json_path.read_text(encoding="utf-8"))
        raw_pct = float(cov_data.get("totals", {}).get("percent_covered", 0.0))
        coverage_percent = round(raw_pct, 1)

        return passed_count, skipped_count, coverage_percent


def measure_suppressions(repo_root: Path) -> int:
    """Count suppression comments matched by SUPPRESSION_PATTERN in the scanned directories."""
    count = 0
    for target_dir in SUPPRESSION_DIRS:
        dir_path = repo_root / target_dir
        if not dir_path.exists():
            continue
        for py_path in dir_path.rglob("*.py"):
            text = py_path.read_text(encoding="utf-8", errors="ignore")
            count += len(SUPPRESSION_PATTERN.findall(text))
    return count


def measure_quality(repo_root: Path) -> Metrics:
    """Measure all 6 quality ratchet metrics."""
    ruff_problems = measure_ruff(repo_root)
    mypy_errors = measure_mypy(repo_root)
    tests_passed, tests_skipped, coverage_percent = measure_tests_and_coverage(repo_root)
    suppressions = measure_suppressions(repo_root)

    return {
        "ruff_problems": ruff_problems,
        "mypy_errors": mypy_errors,
        "tests_passed": tests_passed,
        "tests_skipped": tests_skipped,
        "coverage_percent": coverage_percent,
        "suppressions": suppressions,
    }


def main() -> None:
    """Measure quality metrics and record baseline to quality-baseline.json."""
    print("Measuring repository quality metrics...")
    metrics = measure_quality(REPO_ROOT)
    metrics["generated_at"] = date.today().isoformat()

    baseline_path = REPO_ROOT / "quality-baseline.json"
    baseline_path.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded quality baseline to {baseline_path}:")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()

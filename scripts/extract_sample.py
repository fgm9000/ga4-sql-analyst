"""Extract a deterministic user sample of the GA4 public dataset to Parquet for offline tests.

Usage: uv run python scripts/extract_sample.py --project fgm9000-portfolio
Requires Application Default Credentials. Runs one real query (billed to --project).
"""

import argparse
from pathlib import Path

import duckdb
from google.cloud import bigquery

DEFAULT_OUTPUT = Path("tests/fixtures/ga4_sample.parquet")
MAX_BYTES_BILLED = 5 * 1024**3

# 1% deterministic user sample (modulus 100) over the whole public dataset.
SAMPLE_QUERY = """
SELECT * FROM `bigquery-public-data.ga4_obfuscated_sample_ecommerce.events_*`
WHERE MOD(ABS(FARM_FINGERPRINT(user_pseudo_id)), 100) = 0
"""


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="GCP project billed for the query")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    client = bigquery.Client(project=args.project)
    job_config = bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
    job = client.query(SAMPLE_QUERY, job_config=job_config)
    table = job.result().to_arrow()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    duckdb.from_arrow(table).write_parquet(str(args.output), compression="zstd")
    size_mib = args.output.stat().st_size / 1024**2
    print(f"rows={table.num_rows} bytes_billed={job.total_bytes_billed} file_mib={size_mib:.1f}")


if __name__ == "__main__":
    main()

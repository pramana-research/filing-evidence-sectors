"""The data half of Filing-Evidence Sectors lives on Hugging Face; the code and the record live in git.

    python hf_data.py pull     # dataset, every model reply, server logs -> their paths here; then verify
    python hf_data.py push     # upload them (needs HF_TOKEN with write access to the org)

Hugging Face dataset `pramana-research/filing-evidence-sectors` mirrors this repo's paths:
    dataset/questions.jsonl, dataset/pages.jsonl      the frozen 10,000 questions (fingerprint: dataset/FROZEN.json)
    dataset/r1/pages.jsonl                            R1's Markdown-table pages (fingerprint: dataset/r1/FROZEN.json)
    results/<model>/<setup>/answers.jsonl             each request, raw reply (with reasoning), parsed answer, grade
    logs/sectors-serve-<model>.log                    the vLLM server log of each model's runs
    README.md                                         the dataset card (hf/README.md here)

`pull` also fetches v1's questions (from `pramana-research/filing-evidence`) into v1/dataset/, which only the
build and its validation read (every v1 datapoint is excluded, PROTOCOL §4.4). It then checks the questions and
pages against the fingerprint recorded in git, so what was frozen is provable from the git history alone,
whatever is on the Hub.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from huggingface_hub import HfApi, hf_hub_download, snapshot_download

HERE = Path(__file__).parent
REPO = os.environ.get("FES_HF_REPO", "pramana-research/filing-evidence-sectors")
V1_REPO = "pramana-research/filing-evidence"
PATTERNS = ["dataset/questions.jsonl", "dataset/pages.jsonl", "dataset/r1/pages.jsonl", "results/**/answers.jsonl", "logs/sectors-serve-*.log"]


def pull(revision: str | None = None) -> None:
    snapshot_download(REPO, repo_type="dataset", revision=revision, local_dir=HERE, allow_patterns=PATTERNS)
    hf_hub_download(V1_REPO, "dataset/questions.jsonl", repo_type="dataset", local_dir=HERE / "v1")
    for script in ("freeze.py", "build_r1.py"):
        if subprocess.run([sys.executable, str(HERE / script), "--check"]).returncode != 0:
            sys.exit(f"downloaded data does not match its frozen fingerprint ({script} --check)")
    n = len(list(HERE.glob("results/**/answers.jsonl")))
    print(f"pulled {REPO}: dataset verified against FROZEN.json, {n} answer files; v1 questions in v1/dataset/")


def push(message: str) -> None:
    api = HfApi()
    api.create_repo(REPO, repo_type="dataset", private=True, exist_ok=True)
    api.upload_file(path_or_fileobj=HERE / "hf" / "README.md", path_in_repo="README.md", repo_id=REPO,
                    repo_type="dataset", commit_message="dataset card")
    api.upload_folder(folder_path=HERE, repo_id=REPO, repo_type="dataset", allow_patterns=PATTERNS,
                      commit_message=message)
    print(f"pushed to https://huggingface.co/datasets/{REPO}")


if __name__ == "__main__":
    load_dotenv(HERE / ".env")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "pull":
        pull(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "push":
        push(sys.argv[2] if len(sys.argv) > 2 else "update data")
    else:
        sys.exit(__doc__)

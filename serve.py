"""Serve one benchmark model with vLLM, exactly as its profile says (models.yaml), and record the command.

    python serve.py qwen3-8b            # OpenAI-compatible API on :8000
    python serve.py qwen3-8b --print    # only print the command

The served model name is the profile name. The command, the pinned HF revision and the vLLM version are
written to results/serve/<profile>.json, which runner.py copies into every run's record (PROTOCOL §2, §6).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

HERE = Path(__file__).parent


def profile(name: str) -> tuple[dict, dict]:
    cfg = yaml.safe_load((HERE / "models.yaml").read_text())
    if name not in cfg["models"]:
        sys.exit(f"unknown profile {name!r}; known: {', '.join(cfg['models'])}")
    return cfg["models"][name], cfg["defaults"]


def revision(repo: str) -> str | None:
    """The commit of the locally cached snapshot (what vLLM will load), or None if not downloaded."""
    from huggingface_hub import snapshot_download

    try:
        path = snapshot_download(repo, local_files_only=True)
    except Exception:
        return None
    return Path(path).name


def command(name: str) -> list[str]:
    m, d = profile(name)
    rev = revision(m["repo"])
    cmd = [
        "vllm", "serve", m["repo"],
        "--served-model-name", name,
        "--host", "127.0.0.1", "--port", "8000",
        "--max-model-len", str(m.get("max_model_len", d["max_model_len"])),
        "--gpu-memory-utilization", str(m.get("gpu_memory_utilization", d["gpu_memory_utilization"])),
        "--api-key", os.environ.get("EVAL_API_KEY", "local"),
        "--seed", "0",
    ]  # fmt: skip
    if rev:
        cmd += ["--revision", rev]  # pin the snapshot that was load-checked
    return cmd + [str(a) for a in m.get("vllm_args", [])]


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")  # HF_TOKEN (gated models, faster downloads) and EVAL_API_KEY
    name = sys.argv[1]
    cmd = command(name)
    m, _ = profile(name)
    import vllm

    record = {
        "profile": name,
        "repo": m["repo"],
        "revision": revision(m["repo"]),
        "precision": m["precision"],
        "vllm": vllm.__version__,
        "command": [c if c != os.environ.get("EVAL_API_KEY", "local") else "<key>" for c in cmd],
        "started": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    # SERVE_RECORD_DIR: where the record goes (default results/serve)
    out = Path(os.environ.get("SERVE_RECORD_DIR") or HERE / "results" / "serve") / f"{name}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    print(" ".join(record["command"]))
    if "--print" in sys.argv:
        return
    out.write_text(json.dumps(record, indent=2) + "\n")
    os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")  # as in forge's serve script
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    main()

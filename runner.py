"""Run one model in one setup over the Filing-Evidence Sectors questions (PROTOCOL.md §7-§8) and record everything.

    python serve.py qwen3-8b &                 # vLLM on :8000
    python runner.py qwen3-8b C1 [--subset] [--limit 20]

Copied from Filing-Evidence v1 (runner.py) with the paths of this repo; the request, parsing and grading are
unchanged. The frozen 10,000 questions (dataset/) are verified against dataset/FROZEN.json first. Output, per
profile / setup, under results/:
    answers.jsonl   one line per question: every request and raw reply, the parsed answer, checks, outcome
    summary.json    metrics (checker.summarize) with 95% Wilson intervals
    run.json        model repo and revision, vLLM version and command, prompt hashes, dataset fingerprint,
                    git commit, times
Runs resume: questions already in answers.jsonl are skipped. With MLFLOW_TRACKING_URI set, each finished run
is logged to the `finance-probe` experiment (params, metrics, the three files as artifacts).

C2 reuses the C1 run's first answer when results/<profile>/C1 exists, so C1 and C2 differ only by the
retry (a fair paired comparison, and half the compute); otherwise it asks afresh.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

import httpx
import yaml

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "v1"))  # v1 modules, frozen copies
import checker  # noqa: E402

PROMPT = HERE / "prompts" / "v1.txt"
RETRY = HERE / "prompts" / "v1_retry.txt"
SETS = {"sectors": HERE / "dataset"}
# touched by `run.sh stop`: finish the in-flight questions, then exit
STOP = HERE / "results" / ".stop"


def load_set(name: str) -> tuple[list[dict], dict[str, str], str]:
    """The frozen questions and pages; refuses to run if they differ from dataset/FROZEN.json (PROTOCOL §13)."""
    import freeze  # this repo's freeze.py (same fingerprint as v1's)

    d = SETS[name]
    qs = [json.loads(line) for line in (d / "questions.jsonl").open()]
    pages = {p["id"]: p["text"] for p in map(json.loads, (d / "pages.jsonl").open())}
    frozen = json.loads((d / "FROZEN.json").read_text())["fingerprint"]
    if freeze.fingerprint() != frozen:
        sys.exit(f"dataset differs from {d / 'FROZEN.json'}: refusing to run")
    return qs, pages, frozen


def read_done(answers: Path) -> set[str]:
    """Ids already answered. A last line torn by a power cut is removed (that question is asked again)."""
    if not answers.exists():
        return set()
    raw = answers.read_bytes()
    lines = raw.split(b"\n")
    done, good = set(), 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            done.add(json.loads(line)["id"])
            good = sum(len(x) + 1 for x in lines[: i + 1])
        except (json.JSONDecodeError, KeyError):
            if any(x.strip() for x in lines[i + 1 :]):
                raise
            answers.write_bytes(raw[:good])
            print(f"repaired a torn last line in {answers}", file=sys.stderr)
            break
    return done


def render(template: str, q: dict, pages: dict[str, str]) -> str:
    body = "\n\n".join(
        f"=== PAGE {label} ===\n{pages[pid]}" for pid, label in zip(q["pages"], q["page_labels"], strict=True)
    )
    return template.replace("{pages}", body).replace("{question}", q["question"])


class Client:
    def __init__(self, base: str, served: str, prof: dict, defaults: dict, setup: str):
        mode = "C3" if setup == "C3" else "C1"
        self.base, self.served = base.rstrip("/"), served
        self.extra = (prof.get("request") or {}).get(mode) or {}
        self.system = (prof.get("system") or {}).get(mode)
        self.max_tokens = defaults["max_tokens"][setup]
        self.temperature = defaults["temperature"]
        self.http = httpx.Client(
            timeout=1800, headers={"Authorization": f"Bearer {os.environ.get('EVAL_API_KEY', 'local')}"}
        )

    def ask(self, messages: list[dict]) -> dict:
        msgs = ([{"role": "system", "content": self.system}] if self.system else []) + messages
        body = {"model": self.served, "messages": msgs, "temperature": self.temperature,
                "max_tokens": self.max_tokens, **self.extra}  # fmt: skip
        t0 = time.monotonic()
        r = self.http.post(f"{self.base}/chat/completions", json=body)
        r.raise_for_status()
        j = r.json()
        msg = j["choices"][0]["message"]
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        return {
            "content": msg.get("content") or "",
            "reasoning_chars": len(reasoning),
            "reasoning": reasoning,
            "finish_reason": j["choices"][0].get("finish_reason"),
            "prompt_tokens": j["usage"]["prompt_tokens"],
            "completion_tokens": j["usage"]["completion_tokens"],
            "seconds": round(time.monotonic() - t0, 3),
        }


def run_one(q, pages, client, template, retry_t, setup, reuse) -> dict:
    user = render(template, q, pages)
    messages = [{"role": "user", "content": user}]
    first = reuse or client.ask(messages)
    attempts = [first]
    g = checker.check(first["content"], q, pages)
    retried = False
    if setup == "C2" and g.failed_check:
        retried = True
        follow = messages + [
            {"role": "assistant", "content": first["content"]},
            {"role": "user", "content": checker.retry_message(g.failed_check, g.answer, q, retry_t)},
        ]
        second = client.ask(follow)
        attempts.append({**second, "retry_message": follow[-1]["content"]})
        g = checker.check(second["content"], q, pages)
    return {
        "id": q["id"],
        "slice": q["slice"],
        "subtype": q.get("subtype"),
        "ticker": q["ticker"],
        "form": q["form"],
        "setup": setup,
        "attempts": attempts,
        "reused_c1_answer": reuse is not None,
        "retried": retried,
        **checker.as_dict(g),
        "completion_tokens": sum(a["completion_tokens"] for a in attempts),
        "seconds": sum(a["seconds"] for a in attempts),
        "truncated": any(a["finish_reason"] == "length" for a in attempts),
    }


def git_commit() -> str:
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=HERE, text=True).strip()
        dirty = subprocess.call(["git", "diff", "--quiet", "HEAD", "--", str(HERE)], cwd=HERE) != 0
        return sha + ("-dirty" if dirty else "")
    except Exception:
        return "unknown"


def server_info(base: str, served: str) -> dict:
    h = {"Authorization": f"Bearer {os.environ.get('EVAL_API_KEY', 'local')}"}
    models = httpx.get(f"{base}/models", headers=h, timeout=30).json()
    ids = [m["id"] for m in models.get("data", [])]
    if served not in ids:
        sys.exit(f"server at {base} serves {ids}, not {served!r}; start it with serve.py {served}")
    try:
        version = httpx.get(base.rsplit("/v1", 1)[0] + "/version", timeout=30).json().get("version")
    except Exception:
        version = None
    return {"served_models": ids, "vllm_version": version}


def log_mlflow(out: Path, meta: dict, summary: dict) -> str | None:
    if not os.environ.get("MLFLOW_TRACKING_URI"):
        return None
    import mlflow

    mlflow.set_experiment("finance-probe")
    name = f"{meta['set']}/{meta['profile']}/{meta['setup']}"
    tags = {"kind": "probe", "benchmark": "filing-evidence", "model": meta["repo"], "set": meta["set"]}
    with mlflow.start_run(run_name=name, tags=tags) as run:
        mlflow.log_params({
            "profile": meta["profile"], "repo": meta["repo"], "revision": meta.get("revision"),
            "precision": meta.get("precision"), "setup": meta["setup"], "set": meta["set"],
            "prompt_sha256": meta["prompt_sha256"], "dataset_fingerprint": meta["dataset_fingerprint"],
            "git_commit": meta["git_commit"], "vllm": meta.get("vllm_version"),
        })  # fmt: skip
        m = {
            "accuracy": summary["accuracy"]["rate"],
            "confident_wrong_rate": summary["confident_wrong"]["rate"],
            "abstention_accuracy": summary["abstention_accuracy"]["rate"],
            "retry_rate": summary["retry_rate"]["rate"],
            "tokens_mean": summary["completion_tokens"]["mean"],
            "seconds_mean": summary["seconds"]["mean"],
            "n": summary["n"],
        }
        m.update({f"slice.{s}": v["rate"] for s, v in summary["by_slice"].items()})
        m.update({f"outcome.{k}": v for k, v in summary["outcomes"].items()})
        mlflow.log_metrics({k: v for k, v in m.items() if v == v})  # drop NaN
        for f in ("answers.jsonl", "summary.json", "run.json"):
            mlflow.log_artifact(str(out / f))
        return run.info.run_id


def regrade(out: Path, qs: list[dict], pages: dict[str, str]) -> int:
    """Re-grade stored replies with the current checker (e.g. after a taxonomy fix logged in §12). The final
    attempt's reply is graded; replies, retries and timings are untouched."""
    by_id = {q["id"]: q for q in qs}
    answers = out / "answers.jsonl"
    rows = [json.loads(line) for line in answers.open()]
    for r in rows:
        g = checker.check(r["attempts"][-1]["content"], by_id[r["id"]], pages)
        r.update(checker.as_dict(g))
    answers.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    summary = checker.summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(
        f"regraded {len(rows)}: outcomes {summary['outcomes']} categories "
        f"{ {k: v for k, v in summary['categories'].items() if v} }",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile")
    ap.add_argument("setup", choices=["C1", "C2", "C3"])
    ap.add_argument("--set", default="sectors", choices=list(SETS))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--limit", type=int, default=None, help="N evenly spaced questions (load checks)")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--regrade", action="store_true", help="re-grade stored replies; no model calls")
    ap.add_argument("--subset", action="store_true", help="sectors: only the 1,000-question subset (§8, §12)")
    ap.add_argument("--sample", type=int, default=None, help="N randomly chosen questions (pipeline check)")
    ap.add_argument("--out-name", default=None, help="results folder name (default: the setup)")
    args = ap.parse_args()

    from dotenv import load_dotenv

    load_dotenv(HERE / ".env")
    cfg = yaml.safe_load((HERE / "models.yaml").read_text())
    prof, defaults = cfg["models"][args.profile], cfg["defaults"]
    if args.setup == "C3" and (prof.get("request") or {}).get("C3") is None:
        print(f"{args.profile} has no reasoning mode: C3 is n/a (PROTOCOL §6)")
        return 0

    qs, pages, fingerprint = load_set(args.set)
    if args.limit:
        qs = qs[:: max(1, len(qs) // args.limit)][: args.limit]  # evenly spaced: every slice is covered
    if args.subset:
        keep_ids = set(json.loads((SETS[args.set] / "subsets.json").read_text())["c3_and_robustness"])
        qs = [q for q in qs if q["id"] in keep_ids]
    if args.sample:
        import random

        qs = sorted(random.Random(0).sample(qs, args.sample), key=lambda q: q["id"])
    out = HERE / "results" / args.profile / (args.out_name or args.setup)
    if args.limit and not args.out_name:
        out = out.with_name(f"{args.setup}-limit{args.limit}")
    out.mkdir(parents=True, exist_ok=True)
    answers = out / "answers.jsonl"
    done = read_done(answers)

    reuse = {}
    c1 = out.parent / "C1" / "answers.jsonl"
    if args.setup == "C2" and c1.exists():
        reuse = {r["id"]: r["attempts"][0] for r in map(json.loads, c1.open())}

    if args.regrade:
        return regrade(out, qs, pages)
    info = server_info(args.base_url, args.profile)
    serve_dir = HERE / "results" / "serve"
    serve_rec = serve_dir / f"{args.profile}.json"
    serve = json.loads(serve_rec.read_text()) if serve_rec.exists() else {}
    template, retry_t = PROMPT.read_text(), checker.load_retry_templates(RETRY)
    client = Client(args.base_url, args.profile, prof, defaults, args.setup)
    started = datetime.now(UTC).isoformat(timespec="seconds")

    todo = [q for q in qs if q["id"] not in done]
    print(
        f"{args.set}/{args.profile}/{args.setup}: {len(todo)} to run, {len(done)} already done",
        file=sys.stderr,
    )
    lock, n = Lock(), 0
    stopped = False
    with ThreadPoolExecutor(args.workers) as pool, answers.open("a") as fh:
        # questions are submitted a few at a time, so a stop request (results/.stop) only waits for the
        # in-flight ones; everything answered is already on disk, and a resumed run skips it
        pending, queue = set(), iter(todo)

        def submit_more():
            nonlocal stopped
            while len(pending) < args.workers * 2:
                if STOP.exists():
                    stopped = True
                    return
                q = next(queue, None)
                if q is None:
                    return
                pending.add(pool.submit(run_one, q, pages, client, template, retry_t, args.setup,
                                        reuse.get(q["id"])))  # fmt: skip

        submit_more()
        while pending:
            f = next(as_completed(pending))
            pending.discard(f)
            row = f.result()
            with lock:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                n += 1
                if n % 25 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)}", file=sys.stderr)
            submit_more()
    if stopped:
        print(f"stopped on request after {n} questions; resume with the same command", file=sys.stderr)
        return 3

    rows = [json.loads(line) for line in answers.open()]
    keep = {q["id"] for q in qs}
    rows = [r for r in rows if r["id"] in keep]
    summary = checker.summarize(rows)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    meta = {
        "set": args.set, "profile": args.profile, "setup": args.setup, "repo": prof["repo"],
        "company": prof.get("company"), "precision": prof.get("precision"), "revision": serve.get("revision"),
        "serve_command": serve.get("command"), "vllm_version": info["vllm_version"] or serve.get("vllm"),
        "request_extra": client.extra, "system": client.system, "max_tokens": client.max_tokens,
        "temperature": client.temperature, "prompt_sha256": hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
        "retry_sha256": hashlib.sha256(RETRY.read_bytes()).hexdigest(), "dataset_fingerprint": fingerprint,
        "questions": len(rows), "limit": args.limit, "git_commit": git_commit(), "started": started,
        "finished": datetime.now(UTC).isoformat(timespec="seconds"),
        "c2_reused_c1": bool(reuse),
    }  # fmt: skip
    (out / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    meta["mlflow_run_id"] = log_mlflow(out, meta, summary)
    (out / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    a, cw, ab = summary["accuracy"], summary["confident_wrong"], summary["abstention_accuracy"]
    print(
        f"accuracy {a['k']}/{a['n']}  confident-wrong {cw['k']}/{cw['n']}  abstention {ab['k']}/{ab['n']}  "
        f"outcomes {summary['outcomes']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Verify the Funkot CLI's offline mix and transition windows on Linux."""

import argparse
from array import array
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import struct
import subprocess
import sys
import tempfile


INPUTS = ["Cargo.toml", "Cargo.lock", "funkot-core", "funkot-cli"]
TRACKS = ["track_a_180_i16_o16.wav", "track_b_178_i32_o8.wav"]
NOT_RUN = ["real-track listening and beat alignment", "live playback and keys",
           "manual cache preservation", "labels and survey", "other codecs",
           "integer WAV", "C ABI", "Windows", "Android"]


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_wav(path):
    data = None
    fmt = None
    with path.open("rb") as stream:
        header = stream.read(12)
        if len(header) != 12 or header[:4] != b"RIFF" or header[8:] != b"WAVE":
            raise ValueError(f"Invalid WAV: {path.name}")
        if struct.unpack("<I", header[4:8])[0] + 8 != path.stat().st_size:
            raise ValueError(f"Incomplete WAV: {path.name}")
        while chunk := stream.read(8):
            tag, size = struct.unpack("<4sI", chunk)
            payload = stream.read(size)
            if len(payload) != size:
                raise ValueError(f"Truncated WAV chunk: {path.name}")
            if tag == b"fmt ":
                fmt = struct.unpack("<HHIIHH", payload[:16])
                if fmt[0] == 65534:
                    if len(payload) != 40 or payload[24:] != bytes.fromhex("0300000000001000800000aa00389b71") or struct.unpack("<H", payload[18:20])[0] != 32:
                        raise ValueError(f"Expected IEEE float WAV subtype: {path.name}")
                    fmt = (3, *fmt[1:])
            elif tag == b"data":
                data = payload
            if size % 2:
                stream.read(1)
    if fmt != (3, 2, 44100, 352800, 8, 32) or not data or len(data) % 8:
        raise ValueError(f"Expected nonempty stereo 44100 Hz float32 WAV: {path.name}")
    samples = array("f")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    if not all(math.isfinite(x) for x in samples) or not any(samples):
        raise ValueError(f"Nonfinite or silent WAV: {path.name}")
    summary = {"frames": len(samples) // 2, "seconds": len(samples) / 88200,
               "peak": max(abs(x) for x in samples),
               "over_samples": sum(abs(x) > 1 for x in samples),
               "data_sha256": hashlib.sha256(data).hexdigest(), "sha256": sha256(path)}
    return summary


def judge(scratch, cache_version):
    full = read_wav(scratch / "mix.wav")
    only = read_wav(scratch / "only.wav")
    clips = sorted((scratch / "mix_transitions").glob("*.wav"))
    if len(clips) != 1:
        raise ValueError("Expected exactly one transition clip for two tracks")
    clip = read_wav(clips[0])
    if full["seconds"] <= 60 or clip["seconds"] <= 0.5:
        raise ValueError("Mix or transition clip is too short")
    if not 0 < only["frames"] < full["frames"]:
        raise ValueError("Transition-only output must be shorter than the full mix")
    if only["data_sha256"] != clip["data_sha256"]:
        raise ValueError("Transition-only samples differ from the exported window")
    caches = sorted((scratch / "cache").glob("*.json"))
    if len(caches) != 2:
        raise ValueError("Expected exactly two analysis caches")
    analyses = []
    for name in TRACKS:
        track = scratch / "tracks" / name
        with track.open("rb") as stream:
            length = track.stat().st_size
            digest = hashlib.sha256(struct.pack("<Q", length))
            digest.update(stream.read(min(65536, length)))
            if length > 65536:
                stream.seek(length - min(65536, length))
                digest.update(stream.read(65536))
        path = scratch / "cache" / (digest.hexdigest() + ".json")
        analysis = json.loads(path.read_text())
        if analysis["version"] != cache_version or analysis["file_name"] != name:
            raise ValueError("Cache version or track identity differs")
        if analysis.get("needs_reanalysis", False) or analysis["total_frames"] <= 0:
            raise ValueError("Incomplete analysis cache")
        for key in ("intro_bpm", "outro_bpm"):
            if not math.isfinite(analysis[key]) or analysis[key] <= 0:
                raise ValueError("Invalid cached tempo")
        for key in ("intro_bars", "outro_bars"):
            if analysis[key] <= 0:
                raise ValueError("Invalid cached section length")
        analyses.append({"input_sha256": sha256(track), "cache_sha256": sha256(path),
                         "cache_name": path.name, "analysis": analysis})
    return {"mix": full, "transition_only": only, "clip": clip, "analyses": analyses}


def verify(args):
    repo = args.repo.resolve()
    target = args.target_dir.resolve()
    evidence_root = args.evidence_root.resolve()
    if evidence_root.is_relative_to(repo) or evidence_root.is_relative_to(target):
        raise ValueError("Evidence must be outside source and build cache")
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = Path(tempfile.mkdtemp(prefix="autodj-", dir=evidence_root))
    record = {"started_at": datetime.now(timezone.utc).isoformat(), "run_id": evidence.name,
              "agent": args.agent, "repo": str(repo), "target_dir": str(target),
              "feature": "offline playlist mix and transition-only window",
              "entry_point": "funkot-autodj -l --render", "commands": [],
              "feature_result": "not-run", "not_run": NOT_RUN, "cleanup": {"ok": False},
              "helper_sha256": sha256(Path(__file__)), "owned": {}, "artifacts": []}
    result_file = evidence / "result.json"
    scratch = None
    driving = False
    binary = None

    def save():
        result_file.write_text(json.dumps(record, indent=2) + "\n")

    def run(argv, cwd=repo):
        log = evidence / f"command-{len(record['commands'])}.log"
        entry = {"argv": [str(x) for x in argv], "cwd": str(cwd), "log": log.name}
        record["commands"].append(entry)
        save()
        with log.open("wb") as stream:
            process = subprocess.Popen(entry["argv"], cwd=cwd, stdout=stream,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            entry["process_group"] = process.pid
            save()
            try:
                entry["exit_code"] = process.wait()
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
        save()
        if entry["exit_code"]:
            raise RuntimeError(f"Command failed: {log.name}")
        return log.read_text()

    try:
        save()
        if not sys.platform.startswith("linux") or not all(shutil.which(x) for x in ("git", "cargo", "rustc")):
            raise RuntimeError("Requires Linux, Python 3.11+, Git, Cargo and Rust")
        if Path(run(["git", "rev-parse", "--show-toplevel"]).strip()).resolve() != repo:
            raise RuntimeError("Select the Funkot repository root")
        record["revision"] = run(["git", "rev-parse", "HEAD"]).strip()
        record["dirty"] = run(["git", "status", "--porcelain"]).splitlines()
        if run(["git", "status", "--porcelain", "--", *INPUTS]).strip():
            raise RuntimeError("Commit selected Cargo/source changes before verification")
        names = run(["git", "ls-files", "--", *INPUTS]).splitlines()
        for required in ("Cargo.lock", "funkot-cli/src/main.rs", "funkot-core/examples/gen_synth.rs"):
            if required not in names:
                raise RuntimeError(f"Missing source prerequisite: {required}")
        record["input_hashes"] = {name: sha256(repo / name) for name in names}
        record["runtime"] = {"python": sys.version, "cargo": run(["cargo", "--version"]).strip(),
                             "rustc": run(["rustc", "--version"]).strip()}
        source = (repo / "funkot-core/src/cache.rs").read_text()
        cache_version = int(re.search(r"pub const CACHE_VERSION: u32 = (\d+);", source)[1])
        record["expectations"] = {"tracks": TRACKS, "cache_entries": 2,
            "cache_version": cache_version, "wav": "stereo 44100 Hz float32, finite and nonzero",
            "mix_seconds": ">60", "transition_clips": 1, "clip_seconds": ">0.5",
            "transition_only": "shorter than full mix, same samples as exported clip"}
        save()
        if args.doctor_only:
            record["result"] = "not-run"
        else:
            run(["cargo", "build", "--locked", "--release", "--target-dir", target,
                 "-p", "funkot-cli", "--bin", "funkot-autodj"])
            run(["cargo", "build", "--locked", "--release", "--target-dir", target,
                 "-p", "funkot-core", "--example", "gen_synth", "--features", "testutil"])
            binary = target / "release/funkot-autodj"
            generator = target / "release/examples/gen_synth"
            record["executables"] = {str(p): sha256(p) for p in (binary, generator)}
            scratch = Path(tempfile.mkdtemp(prefix="autodj-scratch-"))
            record["owned"]["scratch"] = str(scratch)
            run([generator, scratch / "tracks"])
            playlist = "# Synthetic tracks; relative to this playlist\n\n" + "\n".join("tracks/" + name for name in TRACKS) + "\n"
            (scratch / "playlist.txt").write_text(playlist)
            (evidence / "playlist.txt").write_text(playlist)
            record["fixture_hashes"] = {p.name: sha256(p) for p in sorted((scratch / "tracks").glob("*.wav"))}
            driving = True
            common = [binary, "-l", scratch / "playlist.txt", "--cache-dir", scratch / "cache",
                      "--wav-format", "f32", "--sample-rate", "44100", "--jobs", "2",
                      "--render-speed", "0", "--no-loop", "--transition-clip-seconds", "60"]
            run([*common, "--render", scratch / "mix.wav"])
            run([*common, "--render", scratch / "only.wav", "--transitions-only"])
            record["observations"] = judge(scratch, cache_version)
            (evidence / "observations.json").write_text(json.dumps(record["observations"], indent=2) + "\n")
            if record["input_hashes"] != {name: sha256(repo / name) for name in names}:
                raise ValueError("Executed source changed during the run")
            record["feature_result"] = "pass"
            record["result"] = "pass"
    except (Exception, KeyboardInterrupt) as error:
        record["error"] = f"{type(error).__name__}: {error}"
        record["feature_result"] = "fail" if driving else "not-run"
        record["result"] = "fail" if driving else "blocked"
    finally:
        try:
            if scratch is not None:
                manifest = [{"path": str(p.relative_to(scratch)), "bytes": p.stat().st_size,
                             "sha256": sha256(p)} for p in sorted(scratch.rglob("*")) if p.is_file()]
                (evidence / "scratch-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
                receipts = sorted(scratch.rglob("*.owned"))
                if receipts and record["feature_result"] != "pass":
                    raise RuntimeError("Unaccepted native WAV generations retained at owned scratch path")
                record["owned"]["usage_ended"] = True
                save()
                for receipt in receipts:
                    claim = json.loads(receipt.read_text())
                    run([binary, "--artifact-complete", claim["output"],
                         "--generation", claim["generation"], "--artifact-receipt", receipt,
                         "--accepted-proof", str(evidence / "observations.json"),
                         "--released-proof", str(result_file)])
                    reclaimed = json.loads(receipt.read_text())
                    if reclaimed["state"] != "reclaimed" or Path(claim["output"]).exists():
                        raise RuntimeError("Native completion did not reclaim its WAV generation")
                    (evidence / (claim["generation"] + ".receipt.json")).write_bytes(receipt.read_bytes())
                shutil.rmtree(scratch)
            record["cleanup"] = {"ok": scratch is None or not scratch.exists(),
                                 "scratch_removed": scratch is None or not scratch.exists(),
                                 "shared_build_cache": "retained, not owned by this run"}
        except Exception as error:
            record["cleanup"] = {"ok": False, "error": str(error)}
        record["artifacts"] = [p.name for p in sorted(evidence.iterdir()) if p != result_file]
        save()
        record["cleanup"]["evidence_exists"] = all((evidence / p).is_file() for p in record["artifacts"]) and result_file.is_file()
        record["cleanup"]["ok"] &= record["cleanup"]["evidence_exists"]
        if not record["cleanup"]["ok"]:
            record["result"] = "fail"
        record["finished_at"] = datetime.now(timezone.utc).isoformat()
        save()
    return record, result_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Committed Funkot engine checkout")
    parser.add_argument("--target-dir", type=Path, required=True, help="Existing or explicitly selected Cargo build cache; retained")
    parser.add_argument("--evidence-root", type=Path, required=True, help="Persistent private evidence parent outside source/build cache")
    parser.add_argument("--agent", required=True, help="Actual driving agent")
    parser.add_argument("--doctor-only", action="store_true", help="Read-only source/runtime identification; feature is not-run")
    args = parser.parse_args()
    record, result_file = verify(args)
    print(json.dumps({"result": record["result"], "feature_result": record["feature_result"],
                      "cleanup": record["cleanup"], "record": str(result_file)}))
    return {"pass": 0, "fail": 1, "blocked": 2, "not-run": 3}[record["result"]]


if __name__ == "__main__":
    sys.exit(main())

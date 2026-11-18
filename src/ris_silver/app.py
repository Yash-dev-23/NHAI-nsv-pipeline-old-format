"""Stage order for one UPC. `plan` prints the contract. `run` stops at the first unported stage."""

from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ris_silver.context import RunContext
from ris_silver.domain.breach import irc_thresholds
from ris_silver.domain.spec import linear_specs, output_tables
from ris_silver.yaml_lite import load_yaml

STAGES = (
    "resolve_run",
    "load_reference",
    "load_facts",
    "correct_cracking",
    "build_canonical",
    "build_hierarchy",
    "build_potholes",
    "enrich",
    "build_chainage",
    "publish",
    "validate",
)

# Last stage whose body is ported. The next name in STAGES still raises.
PORTED_THROUGH = "validate"


@dataclass(frozen=True)
class StageGap(Exception):
    stage: str

    def __str__(self) -> str:
        return f"stage '{self.stage}' is not ported yet"


class PathsMissing(Exception):
    """Ingest can run, but this run has no bronze root or tracker path yet."""


def repo_config_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "pipeline.yaml"
        if candidate.is_file():
            return candidate.parent
    raise FileNotFoundError("config/pipeline.yaml not found from the package location")


def _expand_env_value(value: str, env: dict[str, str]) -> str:
    expanded = value.strip()
    if expanded and expanded[0] == expanded[-1] and expanded[0] in {'"', "'"}:
        expanded = expanded[1:-1]

    def resolve_template(text: str) -> str:
        def replace_var(match: re.Match[str]) -> str:
            token = match.group(0)
            if token.startswith("${") and token.endswith("}"):
                inner = token[2:-1]
                if ":-" in inner:
                    name, default = inner.split(":-", 1)
                    resolved = env.get(name)
                    if resolved is not None and resolved != "":
                        return resolved
                    return resolve_template(default)
                return env.get(inner, "")
            if token.startswith("$"):
                name = token[1:]
                return env.get(name, "")
            return token

        result = re.sub(r"\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", replace_var, text)
        return os.path.expanduser(result)

    result = expanded
    previous = None
    while result != previous:
        previous = result
        result = resolve_template(result)
    return result


def load_project_env(project_root: Path | None = None) -> Path:
    root = project_root or repo_config_dir().parent
    for candidate in (root / "pipeline.env", root / ".env"):
        if not candidate.is_file():
            continue
        parsed: dict[str, str] = {}
        for raw_line in candidate.read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            merged = os.environ.copy() | parsed
            parsed[key] = _expand_env_value(value, merged)
        for key, value in parsed.items():
            os.environ.setdefault(key, value)
    return root


def project_root_for(config_dir: Path | None = None) -> Path:
    env_root = os.environ.get("PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    folder = config_dir or repo_config_dir()
    return folder.parent.resolve()


def resolve_runtime_path(raw_value: str | None, *, project_root: Path, config_dir: Path | None = None) -> str:
    if raw_value is None:
        return ""
    value = str(raw_value).strip()
    if not value:
        return ""

    value = os.path.expanduser(os.path.expandvars(value))
    value = value.replace("${PROJECT_ROOT}", str(project_root)).replace("$PROJECT_ROOT", str(project_root))
    value = value.replace("${CONFIG_DIR}", str(config_dir or project_root)).replace("$CONFIG_DIR", str(config_dir or project_root))

    if value.startswith("s3://"):
        return value

    candidate = Path(value)
    if candidate.is_absolute():
        return str(candidate)

    if any(ch in value for ch in "*?[]"):
        matches = sorted(
            project_root.glob(value),
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )
        if matches:
            return str(matches[0])
        return str((project_root / value).resolve())

    return str((project_root / value).resolve())


def load_run(zone: str, phase: str, cycle: str, upc: str, config_dir: Path | None = None) -> RunContext:
    folder = config_dir or repo_config_dir()
    project_root = project_root_for(folder)
    load_project_env(project_root)
    project_root = project_root_for(folder)
    pipeline = load_yaml((folder / "pipeline.yaml").read_text())
    irc = load_yaml((folder / "standards" / "irc.yaml").read_text())
    paths = pipeline.get("paths", {})
    resolved_paths = {
        key: resolve_runtime_path(value, project_root=project_root, config_dir=folder)
        for key, value in paths.items()
    }
    if os.environ.get("BRONZE_S3_ROOT"):
        resolved_paths["bronze_root"] = os.environ["BRONZE_S3_ROOT"]
    elif os.environ.get("BRONZE_ROOT"):
        resolved_paths["bronze_root"] = os.environ["BRONZE_ROOT"]

    if os.environ.get("SILVER_S3_ROOT"):
        resolved_paths["silver_root"] = os.environ["SILVER_S3_ROOT"]
    elif os.environ.get("SILVER_ROOT"):
        resolved_paths["silver_root"] = os.environ["SILVER_ROOT"]

    if os.environ.get("TRACKER_S3"):
        resolved_paths["tracker"] = os.environ["TRACKER_S3"]
    elif os.environ.get("TRACKER_PATH"):
        resolved_paths["tracker"] = os.environ["TRACKER_PATH"]

    if os.environ.get("IMAGE_ROOT"):
        resolved_paths["image_root"] = os.environ["IMAGE_ROOT"]
    return RunContext(
        zone=zone,
        phase=str(phase),
        cycle=str(cycle),
        upc=upc,
        config_dir=folder,
        pipeline=pipeline,
        irc=irc,
        bronze_root=str(resolved_paths.get("bronze_root") or ""),
        silver_root=str(resolved_paths.get("silver_root") or ""),
        tracker_path=str(resolved_paths.get("tracker") or ""),
        image_root=str(resolved_paths.get("image_root") or ""),
    )


def specs_for(ctx: RunContext):
    intervals = ctx.pipeline["intervals"]
    return linear_specs(
        int(intervals["parent_m"]),
        int(intervals["child_100m"]),
        int(intervals["child_10m"]),
    )


def format_plan(ctx: RunContext) -> str:
    specs = specs_for(ctx)
    lines = [
        f"UPC {ctx.upc}  zone={ctx.zone}  phase={ctx.phase}  cycle={ctx.cycle}",
        f"IRC cuts: {irc_thresholds(ctx.irc)}",
        "Stages:",
    ]
    for name in STAGES:
        mark = "ready" if name == "resolve_run" or _stage_ready(name) else "pending"
        lines.append(f"  {mark:7}  {name}")
    lines.append("Tables:")
    for table in output_tables(specs):
        lines.append(f"  {table}")
    if ctx.bronze_root and ctx.tracker_path:
        lines.append(f"Bronze: {ctx.bronze_root}")
        lines.append(f"Tracker: {ctx.tracker_path}")
    else:
        lines.append("Bronze root and tracker are empty. Set paths.bronze_root and paths.tracker before run.")
    return "\n".join(lines)


def _stage_ready(name: str) -> bool:
    return STAGES.index(name) <= STAGES.index(PORTED_THROUGH)


def execute(ctx: RunContext) -> dict:
    """Load reference and facts, then stop at the next unported stage."""
    if not ctx.bronze_root or not ctx.tracker_path:
        raise PathsMissing("paths.bronze_root and paths.tracker are empty")
    from ris_silver.domain.chainage import build_chainage
    from ris_silver.domain.frames import build_canonical
    from ris_silver.domain.hierarchy import build_hierarchy
    from ris_silver.domain.ratings import enrich
    from ris_silver.ingest.calibration import run_correction
    from ris_silver.ingest.load import load_facts, load_reference
    from ris_silver.domain.images import upload_defect_images
    from ris_silver.io.writer import publish
    from ris_silver.quality.checks import validate

    load_reference(ctx)
    load_facts(ctx)
    run_correction(ctx)
    build_canonical(ctx)
    build_hierarchy(ctx)
    enrich(ctx)
    build_chainage(ctx)
    publish(ctx)
    upload_defect_images(ctx)
    validate(ctx)
    for name in STAGES:
        if name == "resolve_run":
            continue
        if not _stage_ready(name):
            raise StageGap(name)
    return {"partition": ctx.partition, "tables": output_tables(specs_for(ctx))}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ris_silver", description="DLM silver pipeline for one UPC")
    parser.add_argument("command", choices=("plan", "run"))
    parser.add_argument("--zone", default="B")
    parser.add_argument("--phase", default="2")
    parser.add_argument("--cycle", default="1")
    parser.add_argument("--upc", default="N_07024_01001_GJ")
    parser.add_argument("--config-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    ctx = load_run(args.zone, args.phase, args.cycle, args.upc, args.config_dir)
    if args.command == "plan":
        print(format_plan(ctx))
        return 0
    from ris_silver.quality.checks import ValidationFailed

    try:
        execute(ctx)
    except PathsMissing as missing:
        print(format_plan(ctx))
        print(f"\nStopped: {missing}.")
        return 2
    except ValidationFailed as failed:
        print(failed)
        return 1
    except StageGap as gap:
        facts = ctx.frames.get("facts") or {}
        print(
            "Loaded "
            f"roughness={_rows(facts.get('roughness'))} "
            f"cracking={_rows(facts.get('cracking'))} "
            f"rutting={_rows(facts.get('rutting'))} "
            f"ravelling={_rows(facts.get('ravelling'))} "
            f"potholes={_rows(facts.get('potholes'))} "
            f"source={facts.get('pothole_source')}"
        )
        correction = ctx.frames.get("correction") or {}
        canonical = ctx.frames.get("canonical") or {}
        if correction:
            print(
                f"Correction D2 {correction.get('calib_source')} @{correction.get('calib_m')}m, "
                f"rows changed {correction.get('rows_changed')}."
            )
        if canonical:
            print("Canonical rows: " + ", ".join(f"{name}={len(frame)}" for name, frame in canonical.items()))
        print(f"Stopped: {gap}. Next port is validate: checks V1 to V6. A failed check stops the run.")
        return 2
    return 0


def _rows(frame) -> int:
    if frame is None:
        return 0
    return len(frame)

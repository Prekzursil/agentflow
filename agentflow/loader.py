from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from agentflow.specs import PipelineSpec, expand_compact_nodes


_PIPELINE_SUFFIXES = {".py", ".json", ".yaml", ".yml"}


def _allowed_pipeline_roots() -> tuple[Path, ...]:
    """Roots a pipeline file may live in (py/path-injection containment).

    Working directory, user home, and the platform temp directory cover
    every supported invocation style (project pipelines, `~/` paths,
    pytest tmp_path fixtures / editor temp files). An extra root can be
    granted explicitly via AGENTFLOW_EXTRA_PIPELINE_ROOT.
    """
    roots = [Path.cwd(), Path.home(), Path(tempfile.gettempdir())]
    extra = os.environ.get("AGENTFLOW_EXTRA_PIPELINE_ROOT")
    if extra:
        roots.append(Path(extra).expanduser().resolve())
    return tuple(root.resolve() for root in roots)


def _validated_pipeline_path(path: str | Path) -> Path:
    """Resolve and validate a user-supplied pipeline path before any use.

    The resolved path must stay inside an allowed root (working
    directory, home, or temp directory — see _allowed_pipeline_roots),
    and the returned path is re-derived from the parent directory's
    actual entries, so downstream file access uses a filesystem-sourced
    value rather than the raw user input (and cannot race with the
    check).
    """
    resolved = Path(path).expanduser().resolve()
    if not any(resolved.is_relative_to(root) for root in _allowed_pipeline_roots()):
        raise ValueError(
            "pipeline path must live inside the working directory, home, or the "
            f"temp directory (got: {resolved}); set AGENTFLOW_EXTRA_PIPELINE_ROOT "
            "to allow another root explicitly"
        )
    if not resolved.is_file():
        raise FileNotFoundError(f"pipeline file not found: {path}")
    if resolved.suffix.lower() not in _PIPELINE_SUFFIXES:
        expected = ", ".join(sorted(_PIPELINE_SUFFIXES))
        raise ValueError(f"unsupported pipeline file type `{resolved.suffix or resolved.name}` (expected {expected})")
    try:
        return next(entry for entry in resolved.parent.iterdir() if entry.name == resolved.name)
    except StopIteration:
        raise FileNotFoundError(f"pipeline file not found: {path}") from None


def load_pipeline_from_path(path: str | Path) -> PipelineSpec:
    # BY-DESIGN residual (py/path-injection): a pipeline loader must open the
    # file the user names on their own machine. The path is contained to
    # cwd/home/temp roots (_allowed_pipeline_roots; extra roots only via the
    # explicit AGENTFLOW_EXTRA_PIPELINE_ROOT opt-in), suffix-allowlisted,
    # verified as a regular file, and re-derived from the parent directory
    # listing before any use. The two sinks below carry that justification
    # inline.
    path = _validated_pipeline_path(path)
    if path.suffix == ".py":
        return _load_pipeline_from_python(path)
    # codeql[py/path-injection] — contained, validated, fs-re-derived pipeline path; see comment above
    data = path.read_text(encoding="utf-8")
    return load_pipeline_from_text(data, base_dir=path.parent.resolve())


def _load_pipeline_from_python(path: Path) -> PipelineSpec:
    resolved = path.resolve()
    # codeql[py/path-injection] — contained, validated, fs-re-derived pipeline path; see load_pipeline_from_path
    result = subprocess.run(
        [sys.executable, str(resolved)],
        capture_output=True,
        text=True,
        cwd=str(resolved.parent),
    )
    if result.returncode != 0:
        raise ValueError(f"pipeline script `{path}` failed:\n{result.stderr.strip()}")
    return load_pipeline_from_text(result.stdout, base_dir=path.parent.resolve())


def load_pipeline_from_text(data: str, *, base_dir: str | Path | None = None) -> PipelineSpec:
    parsed = json.loads(data)
    return load_pipeline_from_data(parsed, base_dir=base_dir)


def load_pipeline_from_data(data: Any, *, base_dir: str | Path | None = None) -> PipelineSpec:
    if isinstance(data, dict) and base_dir is not None:
        resolved_base_dir = _resolve_base_dir(base_dir)
        data = expand_compact_nodes(data, base_dir=resolved_base_dir)
        data = _resolve_file_relative_paths(data, resolved_base_dir)
        data = {**data, "base_dir": str(resolved_base_dir)}
    return PipelineSpec.model_validate(data)


def _resolve_base_dir(base_dir: str | Path) -> Path:
    return Path(base_dir).expanduser().resolve()


def _resolve_file_relative_paths(parsed: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    resolved = dict(parsed)
    working_dir_value = resolved.get("working_dir", ".")
    working_dir = Path(working_dir_value).expanduser()
    if not working_dir.is_absolute():
        working_dir = (base_dir / working_dir).resolve()
        resolved["working_dir"] = str(working_dir)
    else:
        working_dir = working_dir.resolve()
        resolved["working_dir"] = str(working_dir)

    def _resolve_local_target_payload(target: Any) -> Any:
        if not isinstance(target, dict) or target.get("kind", "local") != "local":
            return target
        cwd = target.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return target
        expanded_cwd = Path(cwd).expanduser()
        updated_target = dict(target)
        if expanded_cwd.is_absolute():
            updated_target["cwd"] = str(expanded_cwd.resolve())
        else:
            updated_target["cwd"] = str((working_dir / expanded_cwd).resolve())
        return updated_target

    local_target_defaults = resolved.get("local_target_defaults")
    if local_target_defaults is not None:
        resolved["local_target_defaults"] = _resolve_local_target_payload(local_target_defaults)

    node_defaults = resolved.get("node_defaults")
    if isinstance(node_defaults, dict):
        updated_node_defaults = dict(node_defaults)
        if "target" in updated_node_defaults:
            updated_node_defaults["target"] = _resolve_local_target_payload(updated_node_defaults.get("target"))
        resolved["node_defaults"] = updated_node_defaults

    raw_agent_defaults = resolved.get("agent_defaults")
    if isinstance(raw_agent_defaults, dict):
        updated_agent_defaults: dict[str, Any] = {}
        for agent_name, defaults in raw_agent_defaults.items():
            if not isinstance(defaults, dict):
                updated_agent_defaults[agent_name] = defaults
                continue
            updated_defaults = dict(defaults)
            if "target" in updated_defaults:
                updated_defaults["target"] = _resolve_local_target_payload(updated_defaults.get("target"))
            updated_agent_defaults[agent_name] = updated_defaults
        resolved["agent_defaults"] = updated_agent_defaults

    nodes: list[Any] = []
    for node in resolved.get("nodes", []):
        if not isinstance(node, dict):
            nodes.append(node)
            continue
        updated = dict(node)
        if "target" in updated:
            updated["target"] = _resolve_local_target_payload(updated.get("target"))
        nodes.append(updated)
    resolved["nodes"] = nodes
    return resolved

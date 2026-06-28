from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import code_root, load_models, runtime_home


_MODEL_KEY_ALIASES: dict[str, str] = {
    "opencode-go/glm-5.2": "opencode_go_glm52",
    "opencode_go_glm52": "opencode-go/glm-5.2",
}


def model_spec(selected_model: str) -> dict[str, Any]:
    models = load_models().get("models", {})
    spec = models.get(selected_model)
    if spec is None:
        alias = _MODEL_KEY_ALIASES.get(selected_model)
        if alias and alias != selected_model:
            spec = models.get(alias)
    return dict(spec or {})


def env_for_model(selected_model: str) -> tuple[dict[str, str], str | None]:
    spec = model_spec(selected_model)
    profile = spec.get("env_profile")
    if not profile:
        return {}, None
    path = Path(profile)
    if not path.is_absolute():
        path = runtime_home() / path
    if not path.exists():
        example = path.with_name(path.name + ".example")
        packaged_example = code_root() / profile
        if packaged_example.suffix != ".example":
            packaged_example = packaged_example.with_name(packaged_example.name + ".example")
        if example.exists():
            path = example
        elif packaged_example.exists():
            path = packaged_example
        else:
            return {}, str(path)
    return parse_env_file(path), str(path)


def parse_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env[key] = value
    return env


def redacted_env_keys(env: dict[str, str]) -> list[str]:
    return sorted(env.keys())

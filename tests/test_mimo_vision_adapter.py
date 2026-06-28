import base64
import json
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator

from orchestrator.multimodal import decode_image_base64, load_image_inputs, observation_from_text
from orchestrator.scheduler import OrchestratorService, _worker_prompt
from orchestrator.workers.mimo_vision_adapter import MimoVisionAdapter, _build_payload


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
)
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"jpeg"


def test_decode_base64_png_and_jpeg():
    png_mime, png_raw = decode_image_base64(base64.b64encode(PNG_BYTES).decode("ascii"))
    jpg_mime, jpg_raw = decode_image_base64(
        "data:image/jpeg;base64," + base64.b64encode(JPEG_BYTES).decode("ascii")
    )

    assert png_mime == "image/png"
    assert png_raw.startswith(b"\x89PNG")
    assert jpg_mime == "image/jpeg"
    assert jpg_raw.startswith(b"\xff\xd8\xff")


def test_load_local_image_path(tmp_path):
    image = tmp_path / "screen.png"
    image.write_bytes(PNG_BYTES)

    loaded = load_image_inputs(image_paths=[str(image)])

    assert loaded[0].mime_type == "image/png"
    assert loaded[0].source == str(image.resolve())
    assert loaded[0].sha256


def test_observation_schema_validates_json_payload():
    image = load_image_inputs(image_base64=[base64.b64encode(PNG_BYTES).decode("ascii")])[0]
    observation = observation_from_text(
        "t1",
        [image],
        json.dumps(
            {
                "observations": ["button is clipped"],
                "ui_elements": [{"type": "button", "text": "Save"}],
                "defects": [{"severity": "medium", "description": "clipped"}],
                "implementation_hints": ["increase container width"],
                "confidence": 0.8,
            }
        ),
        "mimo-v2.5",
    ).to_dict()
    schema = json.loads(Path("schemas/vision_observation.json").read_text(encoding="utf-8"))

    Draft202012Validator(schema).validate(observation)
    assert observation["confidence"] == 0.8
    assert observation["image_refs"][0]["mime_type"] == "image/png"


def test_mimo_payload_uses_base64_image_url_not_claude_file():
    image = load_image_inputs(image_base64=[base64.b64encode(PNG_BYTES).decode("ascii")])[0]

    payload = _build_payload("mimo-v2.5", "analyze screenshot", [image])
    text = json.dumps(payload)

    assert "data:image/png;base64," in text
    assert "claude --file" not in text
    assert "--file" not in text


def test_adapter_dry_run_writes_observation(tmp_path):
    image = load_image_inputs(image_base64=[base64.b64encode(PNG_BYTES).decode("ascii")])[0]
    output = tmp_path / "vision_observation.json"

    observation = MimoVisionAdapter().analyze(
        task_id="t1",
        prompt="analyze",
        images=[image],
        output_path=output,
        dry_run=True,
    )

    assert output.exists()
    assert observation.task_id == "t1"
    assert observation.observations
    assert "claude --file" in observation.implementation_hints[0]


def test_worker_prompt_embeds_vision_observation_without_file_arg():
    prompt = _worker_prompt(
        {
            "user_goal": "fix layout",
            "worktree_path": "w",
            "risk_level": "medium",
            "test_commands": [],
            "build_commands": [],
            "forbidden_paths": [],
            "vision_observation": {
                "observations": ["Save button is clipped"],
                "implementation_hints": ["adjust flex container"],
            },
        },
        {"selected_worker": "claude_code", "selected_model": "deepseek_pro"},
    )

    assert "Vision Observation" in prompt
    assert "Save button is clipped" in prompt
    assert "`claude --file`" in prompt


def test_scheduler_writes_vision_observation_artifact(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "x@y"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=repo, check=True)
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    home = tmp_path / "home"
    home.mkdir()
    (home / "models.yaml").write_text(
        "models:\n  mimo_v25:\n    provider: mimo\n    adapter: claude_code\n"
        "    model: mimo-v2.5\n    worker: claude_code\n"
        "  deepseek_pro:\n    provider: deepseek\n    adapter: claude_code\n"
        "    model: deepseek-v4-pro\n    worker: claude_code\n",
        encoding="utf-8",
    )
    (home / "policies.yaml").write_text(
        Path("config/policies.yaml.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (home / "projects.yaml").write_text(
        "projects:\n  generic:\n    project_id: generic\n    name: Generic\n"
        f"    repo: {repo}\n    stack: [python]\n    test_commands: []\n    build_commands: []\n"
        "    forbidden_paths: []\n    default_worker: claude_code\n"
        "    default_model: deepseek_pro\n    allow_auto_pr: false\n    allow_remote_push: false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_ORCHESTRATOR_HOME", str(home))
    monkeypatch.setattr("orchestrator.scheduler._task_requires_diff", lambda task: False)

    service = OrchestratorService()
    result = service.submit_task(
        "generic",
        "Analyze UI screenshot layout issues",
        "low",
        True,
        False,
        dry_run=True,
        image_base64=[base64.b64encode(PNG_BYTES).decode("ascii")],
    )
    run_dir = Path(result["run_dir"])

    observation = json.loads((run_dir / "multimodal" / "vision_observation.json").read_text(encoding="utf-8"))
    task = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))

    assert observation["task_id"] == result["task_id"]
    assert observation["image_refs"][0]["mime_type"] == "image/png"
    assert task["vision_observation"]["observations"]
    assert service.get_task_status(result["task_id"])["status"] == "COMPLETED_WITH_PATCH"

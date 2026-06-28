from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from ..env_profiles import env_for_model, model_spec
from ..multimodal import ImageInput, VisionObservation, observation_from_text, write_observation


class MimoVisionAdapter:
    """Direct MiMo vision adapter.

    This adapter sends base64 image data to the MiMo-compatible chat API. It
    never shells out to Claude and never uses `claude --file`.
    """

    name = "mimo_vision"

    def analyze(
        self,
        *,
        task_id: str,
        prompt: str,
        images: list[ImageInput],
        output_path: Path,
        model_key: str = "mimo_v25",
        dry_run: bool = False,
        timeout: int = 120,
    ) -> VisionObservation:
        spec = model_spec(model_key)
        model = str(spec.get("model") or "mimo-v2.5")
        if dry_run:
            observation = VisionObservation(
                task_id=task_id,
                image_refs=[image.to_ref() for image in images],
                observations=["dry-run MiMo vision observation"],
                implementation_hints=["Pass this observation to the code worker; do not use claude --file."],
                confidence=0.5,
                model=model,
                created_at="",
            )
            write_observation(observation, output_path)
            return observation

        env, _profile_path = env_for_model(model_key)
        api_key = env.get("MIMO_API_KEY") or os.environ.get("MIMO_API_KEY")
        base_url = env.get("MIMO_BASE_URL") or os.environ.get("MIMO_BASE_URL") or "https://api.mimo.xiaomi.com/v1"
        api_model = env.get("MIMO_MULTIMODAL_MODEL") or model
        if not api_key:
            observation = VisionObservation(
                task_id=task_id,
                image_refs=[image.to_ref() for image in images],
                observations=[],
                implementation_hints=[],
                confidence=0.0,
                model=api_model,
                degraded=True,
                degradation_reason="MIMO_API_KEY is not configured",
                created_at="",
            )
            write_observation(observation, output_path)
            return observation

        payload = _build_payload(api_model, prompt, images)
        request = urllib.request.Request(
            url=f"{base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            observation = VisionObservation(
                task_id=task_id,
                image_refs=[image.to_ref() for image in images],
                model=api_model,
                degraded=True,
                degradation_reason=f"MiMo vision request failed: {exc}",
                created_at="",
            )
            write_observation(observation, output_path)
            return observation

        text = _extract_message_text(response_payload)
        observation = observation_from_text(task_id, images, text, api_model)
        write_observation(observation, output_path)
        return observation


def _build_payload(model: str, prompt: str, images: list[ImageInput]) -> dict[str, Any]:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Analyze the provided image(s) and return only JSON with keys: "
                "observations, ui_elements, defects, implementation_hints, confidence.\n\n"
                + prompt
            ),
        }
    ]
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": image.to_data_url()}})
    return {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0}


def _extract_message_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SUPPORTED_MIME_TYPES = {"image/png", "image/jpeg"}
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


@dataclass
class ImageInput:
    mime_type: str
    base64_data: str
    source: str = "inline"
    sha256: str = ""
    size_bytes: int = 0

    def to_data_url(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64_data}"

    def to_ref(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "mime_type": self.mime_type,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass
class VisionObservation:
    task_id: str
    image_refs: list[dict[str, Any]] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    ui_elements: list[dict[str, Any]] = field(default_factory=list)
    defects: list[dict[str, Any]] = field(default_factory=list)
    implementation_hints: list[str] = field(default_factory=list)
    confidence: float = 0.0
    model: str = ""
    provider: str = "mimo"
    degraded: bool = False
    degradation_reason: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["created_at"] = payload["created_at"] or _now()
        return payload


def load_image_inputs(
    image_paths: list[str] | None = None,
    image_base64: list[str] | None = None,
) -> list[ImageInput]:
    images: list[ImageInput] = []
    for path_text in image_paths or []:
        path = Path(path_text).expanduser().resolve()
        raw = path.read_bytes()
        mime_type = detect_image_mime(raw)
        images.append(_image_input(raw, mime_type, str(path)))
    for idx, encoded in enumerate(image_base64 or []):
        mime_type, raw = decode_image_base64(encoded)
        images.append(_image_input(raw, mime_type, f"inline:{idx}"))
    return images


def decode_image_base64(value: str) -> tuple[str, bytes]:
    text = value.strip()
    declared_mime: str | None = None
    if text.startswith("data:"):
        header, _, payload = text.partition(",")
        if not payload or ";base64" not in header:
            raise ValueError("image data URL must use base64 encoding")
        declared_mime = header.removeprefix("data:").split(";", 1)[0]
        text = payload
    try:
        raw = base64.b64decode(text, validate=True)
    except binascii.Error as exc:
        raise ValueError("invalid base64 image payload") from exc
    detected = detect_image_mime(raw)
    if declared_mime and declared_mime != detected:
        raise ValueError(f"declared MIME {declared_mime} does not match detected {detected}")
    return detected, raw


def detect_image_mime(raw: bytes) -> str:
    if raw.startswith(_PNG_MAGIC):
        return "image/png"
    if raw.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    raise ValueError("unsupported image type; expected PNG or JPEG")


def observation_from_text(
    task_id: str,
    images: list[ImageInput],
    text: str,
    model: str,
    degraded: bool = False,
    degradation_reason: str | None = None,
) -> VisionObservation:
    parsed = _extract_json_object(text)
    observation = VisionObservation(
        task_id=task_id,
        image_refs=[image.to_ref() for image in images],
        model=model,
        degraded=degraded,
        degradation_reason=degradation_reason,
        created_at=_now(),
    )
    if parsed:
        observation.observations = _string_list(parsed.get("observations"))
        observation.ui_elements = _dict_list(parsed.get("ui_elements"))
        observation.defects = _dict_list(parsed.get("defects"))
        observation.implementation_hints = _string_list(parsed.get("implementation_hints"))
        observation.confidence = _confidence(parsed.get("confidence"))
    else:
        observation.observations = [text.strip()] if text.strip() else []
        observation.confidence = 0.2 if text.strip() else 0.0
    return observation


def write_observation(observation: VisionObservation, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(observation.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path


def _image_input(raw: bytes, mime_type: str, source: str) -> ImageInput:
    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"unsupported image MIME type: {mime_type}")
    return ImageInput(
        mime_type=mime_type,
        base64_data=base64.b64encode(raw).decode("ascii"),
        source=source,
        sha256=hashlib.sha256(raw).hexdigest(),
        size_bytes=len(raw),
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

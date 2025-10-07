"""Built-in sprite assets for the Emotion Diary bot."""

from __future__ import annotations

from base64 import b64decode
from collections.abc import Mapping
from pathlib import Path

# Base64 encoded 1x1 PNG sprites. Using inline text avoids binary blobs in the
# repository while keeping the assets self-contained.
_SPRITE_DATA: Mapping[str, str] = {
    "sprite_happy_1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4f9cBAAT7Ah0bgsQIAAAAAElFTkSuQmCC",
    "sprite_happy_2.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4f4IBAASRAcjyuzl2AAAAAElFTkSuQmCC",
    "sprite_neutral_1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNYsGABAAPEAeGUtBWxAAAAAElFTkSuQmCC",
    "sprite_neutral_2.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNoaGgAAAMEAYFL09IQAAAAAElFTkSuQmCC",
    "sprite_sad_1.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNwaPgPAALDAcBv0mA2AAAAAElFTkSuQmCC",
    "sprite_sad_2.png": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGPQiNoHAAHuAUEESKSIAAAAAElFTkSuQmCC",
}


def ensure_builtin_assets(target_dir: Path | str | None = None) -> dict[str, Path]:
    """Materialise bundled sprites into *target_dir*.

    The project avoids shipping binary blobs in the Git repository by storing
    sprites as base64 encoded strings. This helper decodes the images into the
    requested directory, returning a mapping between sprite file names and the
    resulting paths.
    """
    if target_dir is None:
        target_dir = Path(__file__).resolve().parent
    else:
        target = Path(target_dir)
        if target.is_file():
            raise ValueError("target_dir must be a directory, not a file")
        target_dir = target

    target_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}
    for name, data in _SPRITE_DATA.items():
        destination = target_dir / name
        if not destination.exists() or destination.stat().st_size == 0:
            destination.write_bytes(b64decode(data))
        written[name] = destination
    return written


__all__ = ["ensure_builtin_assets"]

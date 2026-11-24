"""Publish and retain the assets referenced by the dated BikeResearch reports."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Callable, Iterator

MODEL_KEYS = ("glb_file", "preview_image", "manifest_file", "blender_script")
PHOTO_KEYS = ("calibrated_photo", "overlay_qa_image")
_NAME = re.compile(r"[a-zA-Z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{64}")
_REPORT_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
_FLAT_ASSET = re.compile(r"^[a-z0-9-]+(?:\.glb|_preview\.png|_qa_manifest\.json|_blender_rebuild\.py|_ref_calibrated\.jpg|_overlay_qa\.png)$")


def dated_deck(date_str: str) -> str:
    if not isinstance(date_str, str) or not _REPORT_DAY.fullmatch(date_str):
        raise ValueError(f"invalid report date: {date_str!r}")
    date.fromisoformat(date_str)
    return f"data/archive/{date_str}_briefing.pptx"


def _model_paths(model: dict) -> Iterator[tuple[dict, str, str]]:
    for key in MODEL_KEYS:
        yield model, key, model[key]
    photo = model.get("photo_calibration")
    if photo:
        for key in PHOTO_KEYS:
            yield photo, key, photo[key]


def _safe_model_path(value: str) -> PurePosixPath:
    part = PurePosixPath(value)
    pts = part.parts
    flat = len(pts) == 2
    archive = len(pts) == 4 and pts[1] == "archive" and _SHA.fullmatch(pts[2])
    if value != part.as_posix() or not (flat or archive) or pts[0] != "models" or not _NAME.fullmatch(part.name) or part.name in (".", ".."):
        raise ValueError(f"invalid model asset path: {value!r}")
    return part


def _package_key(files: dict[str, bytes]) -> str:
    hashes = {n: hashlib.sha256(raw).hexdigest() for n, raw in files.items()}
    return hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()


def _check_package(model: dict, files: dict[str, bytes]) -> None:
    glb = files[_safe_model_path(model["glb_file"]).name]
    if not glb.startswith(b"glTF") or len(glb) != model["glb_bytes"] or hashlib.sha256(glb).hexdigest() != model["glb_sha256"]:
        raise ValueError(f"GLB differs from report: {model['glb_file']}")
    manifest = json.loads(files[_safe_model_path(model["manifest_file"]).name])
    if manifest.get("glb_sha256") != model["glb_sha256"] or manifest.get("glb_bytes") != len(glb):
        raise ValueError(f"QA manifest does not describe the report GLB: {model['manifest_file']}")


def publish_model(model: dict, docs: Path, source: Callable[[str], Path]) -> dict:
    """Preserve all referenced companion bytes, keyed by their names and SHA-256s."""
    result = deepcopy(model)
    paths = list(_model_paths(result))
    files: dict[str, bytes] = {}
    for _, _, old_url in paths:
        name = _safe_model_path(old_url).name
        if name in files:
            raise ValueError(f"duplicate package member: {name}")
        raw = source(old_url).read_bytes()
        if not raw:
            raise ValueError(f"empty package member: {old_url}")
        files[name] = raw
    _check_package(result, files)
    package = _package_key(files)
    directory = docs / "models" / "archive" / package
    if directory.exists():
        if not directory.is_dir() or {f.name for f in directory.iterdir()} != files.keys():
            raise ValueError(f"invalid on-disk model package: {package}")
        for name, raw in files.items():
            if (directory / name).read_bytes() != raw:
                raise ValueError(f"modified immutable asset: {directory / name}")
    else:
        directory.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".package-", dir=directory.parent) as staging:
            stage = Path(staging) / "content"
            stage.mkdir()
            for name, raw in files.items():
                (stage / name).write_bytes(raw)
            stage.rename(directory)
    for record, key, old_url in paths:
        record[key] = f"models/archive/{package}/{_safe_model_path(old_url).name}"
    return result


def build_published_model(bike: dict, docs: Path, build: Callable[[dict, Path], dict]) -> dict:
    """Never let another build of the same slug overwrite a package in use."""
    with TemporaryDirectory(prefix="bike-model-") as staging:
        folder = Path(staging)
        model = build(bike, folder)
        return publish_model(model, docs, lambda v: folder / _safe_model_path(v).name)


def referenced_packages(docs: Path, reports: list[dict]) -> set[str]:
    """Answer only after *every* retained report has a valid deck and complete model."""
    live: set[str] = set()
    checked: dict[str, dict[str, bytes]] = {}
    for report in reports:
        deck = dated_deck(report["date"])
        if report.get("pptx_file") != deck or not (docs / deck).is_file():
            raise ValueError(f"missing dated deck or bad report link: {deck}")
        for bike in report.get("complete_bikes", []):
            model = bike["model_3d"]
            refs = [_safe_model_path(v) for _, _, v in _model_paths(model)]
            if any(len(p.parts) != 4 for p in refs) or len({p.parts[2] for p in refs}) != 1:
                raise ValueError(f"model references are not one immutable package: {bike.get('slug')}")
            package = refs[0].parts[2]
            files = checked.get(package)
            if files is None:
                files = {p.name: (docs / p).read_bytes() for p in refs}
                if _package_key(files) != package:
                    raise ValueError(f"model package checksum mismatch: {package}")
                checked[package] = files
            elif files.keys() != {p.name for p in refs}:
                raise ValueError(f"reports disagree about package members: {package}")
            _check_package(model, files)
            live.add(package)
    return live


def prune_models(docs: Path, reports: list[dict], *, remove_legacy_flat: bool = False) -> set[str]:
    live = referenced_packages(docs, reports)
    models = docs / "models"
    archive = models / "archive"
    if archive.is_dir():
        for pkg in archive.iterdir():
            if not pkg.is_symlink() and pkg.is_dir() and _SHA.fullmatch(pkg.name) and pkg.name not in live:
                shutil.rmtree(pkg)
    if remove_legacy_flat and models.is_dir():
        for old in models.iterdir():
            if old.is_file() and not old.is_symlink() and _FLAT_ASSET.fullmatch(old.name):
                old.unlink()
    return live

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pipeline.archive_assets import (
    build_published_model, dated_deck, prune_models, publish_model, referenced_packages,
)


def mock_builder(bike, directory):
    """Generate one concrete package without a network or the heavy 3D pipeline."""
    mode = bike["revision"]
    fl = {"glb_file": "sample.glb", "preview_image": "sample_preview.png",
          "manifest_file": "sample_qa_manifest.json", "blender_script": "sample_blender_rebuild.py"}
    files = {k: f"models/{v}" for k, v in fl.items()}
    glb = b"glTF fake test payload"
    meta = {"glb_bytes": len(glb), "glb_sha256": hashlib.sha256(glb).hexdigest()}
    payloads = {"glb_file": glb, "preview_image": b"preview:" + mode.encode(),
                "manifest_file": json.dumps(meta).encode(), "blender_script": b"# synthetic script"}
    for k, v in fl.items():
        (directory / v).write_bytes(payloads[k])
    optional = {}
    if bike.get("photo"):
        for k, name in (("calibrated_photo", "sample_ref_calibrated.jpg"),
                        ("overlay_qa_image", "sample_overlay_qa.png")):
            (directory / name).write_bytes(("calibration:" + name).encode())
            optional[k] = f"models/{name}"
    return {**files, **meta, "photo_calibration": optional or None}


class ArchiveAssets(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory(prefix="bikeresearch-tests-")
        self.addCleanup(self.test_dir.cleanup)
        self.docs = Path(self.test_dir.name)

    def model(self, revision, photo=False):
        return build_published_model(
            {"slug": "same-bike", "revision": revision, "photo": photo}, self.docs, mock_builder
        )

    def report(self, day, *models):
        deck = dated_deck(day)
        file = self.docs / deck
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(("dated deck:" + day).encode())
        return {"date": day, "pptx_file": deck, "complete_bikes":
                [{"slug": "same-bike", "model_3d": model} for model in models]}

    def package(self, model):
        return (self.docs / model["glb_file"]).parent

    def test_narrow_next_day_keeps_historical_assets_and_dated_deck(self):
        old = self.model("first", photo=True)
        a = self.report("2026-11-22", old)
        b = self.report("2026-11-23")  # No newly published models.
        self.assertEqual(len(prune_models(self.docs, [a, b])), 1)
        self.assertTrue((self.docs / old["photo_calibration"]["overlay_qa_image"]).is_file())
        self.assertEqual((self.docs / a["pptx_file"]).read_text(), "dated deck:2026-11-22")
        self.assertEqual((self.docs / b["pptx_file"]).read_text(), "dated deck:2026-11-23")
        self.assertNotEqual(dated_deck(a["date"]), dated_deck(b["date"]))
        prune_models(self.docs, [b])
        self.assertFalse(self.package(old).exists())

    def test_same_day_regeneration_uses_distinct_revision_even_if_glb_matches(self):
        original = self.model("first")
        previous = self.report("2026-11-22", original)
        today_original = self.report("2026-11-23", original)
        same_bytes = self.model("first")
        self.assertEqual(original["glb_file"], same_bytes["glb_file"])
        corrected = self.model("revised")  # Same GLB, different companion bytes.
        today_corrected = self.report("2026-11-23", corrected)
        self.assertEqual(original["glb_sha256"], corrected["glb_sha256"])
        self.assertNotEqual(original["glb_file"], corrected["glb_file"])
        self.assertEqual(today_original["pptx_file"], today_corrected["pptx_file"])
        prune_models(self.docs, [previous, today_corrected])
        self.assertEqual((self.docs / original["preview_image"]).read_bytes(), b"preview:first")
        self.assertEqual((self.docs / corrected["preview_image"]).read_bytes(), b"preview:revised")

    def test_corrupt_or_missing_ref_prevents_all_pruning(self):
        live, unreferenced = self.model("live"), self.model("historic")
        edition = self.report("2026-11-22", live)
        (self.docs / live["preview_image"]).write_bytes(b"mangled")
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            prune_models(self.docs, [edition])
        self.assertTrue(self.package(unreferenced).exists())

    def test_checks_date_and_package_paths(self):
        model = self.model("live")
        edition = self.report("2026-11-22", model)
        with self.assertRaises(ValueError):
            dated_deck("../../demo")
        bad_path = dict(model, glb_file="../secret.glb")
        with self.assertRaises(ValueError):
            publish_model(bad_path, self.docs, lambda p: self.docs / p)
        edition["pptx_file"] = "data/daily_briefing.pptx"
        with self.assertRaisesRegex(ValueError, "dated deck"):
            referenced_packages(self.docs, [edition])


if __name__ == "__main__":
    unittest.main()

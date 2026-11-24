import json
from pathlib import Path
import unittest

from pipeline.product_gate import is_complete_bike_article, subject_product
from pipeline.taxonomy import classify_article, detect_brands


DOCS = Path(__file__).resolve().parents[1] / "docs"
REPORT = DOCS / "data/archive/2026-11-24.json"


class ProductCoverageTests(unittest.TestCase):
    def test_corrected_published_edition(self):
        report = json.loads(REPORT.read_text())
        bikes = report["complete_bikes"]
        self.assertEqual(len(bikes), 5)
        self.assertEqual(report["new_bikes_count"], 1)
        self.assertEqual(report["summary"]["counts"]["complete_bikes"], 5)
        self.assertEqual(len(report["articles"]), 99)
        expected = {"Prize Purse": "race_event", "Wild card fortunes": "race_event",
                    "Video: Remy Metailler": "gear_tech"}
        for fragment, bucket in expected.items():
            with self.subTest(fragment=fragment):
                article = next(a for a in report["articles"] if fragment in a["title"])
                # Feed categories can contain positive lexical hints but mustn't
                # turn these event/video subjects into products.
                item = {**article, "categories": [*article["categories"], "Mountain Bikes", "eMTB"]}
                self.assertFalse(is_complete_bike_article(item))
                self.assertEqual(classify_article(item, False)["bucket"], bucket)
                self.assertEqual(article["classification"]["bucket"], bucket)
                self.assertIsNone(article["bike_slug"])
                self.assertNotIn("590,000", article["takeaway_zh"])
        storck = next(b for b in bikes if b["is_new"])
        self.assertEqual((storck["brand"], storck["model_name"]), ("Storck", "Aerfast.5 Pro"))
        self.assertNotIn("price", storck["specs"])
        self.assertEqual(storck["measured_ratio"], 0)
        self.assertTrue(all(v.startswith("inferred") for v in storck["geometry_provenance"].values()))
        self.assertIsNone(storck["model_3d"]["photo_calibration"])
        for bike in bikes:
            self.assertTrue(is_complete_bike_article(bike), bike["title"])

    def test_real_product_controls(self):
        for title in (
            "Orbea Wild M10 tested on steep trails",
            "Orbea Wild",
            "New 191.5W Storck Aerfast.5 Pro (Re)Claims World’s Fastest Aero Road Bike Title",
        ):
            self.assertTrue(is_complete_bike_article({"title": title, "categories": []}), title)
        self.assertEqual(subject_product("Orbea Wild M10 tested on steep trails"), ("Orbea", "Wild M10"))
        title = "Storck Aerfast.5 Pro vs Merida"
        self.assertEqual(subject_product(title), ("Storck", "Aerfast.5 Pro"))
        self.assertEqual(detect_brands("Merida and Storck compared", title=title)[0]["name"], "Storck")

    def test_news_negative_controls(self):
        for title in (
            "A Wild Day of Trail Riding",
            "The 2027 Sea Otter starts registration",
            " Video : Orbea Wild follows the race leaders",
            "Watch：Storck Aerfast.5 Pro at the race",
        ):
            self.assertFalse(is_complete_bike_article({"title": title, "categories": ["Mountain Bikes", "Wild"]}), title)


if __name__ == "__main__":
    unittest.main()

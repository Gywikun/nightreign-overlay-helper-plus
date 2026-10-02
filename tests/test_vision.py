import unittest
from types import SimpleNamespace
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from src.common import get_asset_path, get_data_path
from src.detector import DetectorManager
from src.detector.day_detector import DayDetectParam
from src.window_tracking import AutomaticLocator, map_signature


class FakeCapture:
    def __init__(self, image):
        self.image = image
        self.monitors = [{"left": 0, "top": 0, "width": image.width, "height": image.height}] * 2

    def grab(self, region):
        x, y, w, h = [int(region[key]) for key in ("left", "top", "width", "height")]
        cropped = self.image.crop((x, y, x+w, y+h)).convert("RGBA")
        return SimpleNamespace(size=cropped.size, bgra=cropped.tobytes("raw", "BGRA"))


class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manager = DetectorManager()
        cls.locator = AutomaticLocator(cls.manager)

    def frame(self, path):
        return np.array(Image.open(get_asset_path(path)).convert("RGB"))

    def test_day_banner_found_without_manual_region(self):
        frame = self.frame("detect_region_tutorial/2.jpg")
        region = self.locator.find_day_region(frame, "chs")
        self.assertIsNotNone(region)
        self.assertTrue(405 <= region[0] <= 430)
        self.assertTrue(265 <= region[1] <= 290)
        result = self.manager.day_detector.detect(FakeCapture(Image.fromarray(frame)), DayDetectParam(region, "chs"))
        self.assertTrue(result.start_day1)
        self.assertLess(result.score_day1, result.score_day2)

    def test_non_day_screen_not_falsely_located(self):
        self.assertIsNone(self.locator.find_day_region(self.frame("hp_detect_tutorial/2.jpg"), "chs"))

    def test_health_region_found_in_authors_reference(self):
        regions = self.locator.find_health_regions(self.frame("hp_detect_tutorial/2.jpg"))
        self.assertIn("hpcolor_detect_region", regions)
        self.assertTrue(78 <= regions["hpcolor_detect_region"][0] <= 95)
        self.assertTrue(17 <= regions["hpcolor_detect_region"][1] <= 30)

    def test_dark_screen_does_not_create_calibration(self):
        frame = np.zeros((540, 960, 3), dtype=np.uint8)
        self.assertEqual(self.locator.find_health_regions(frame), {})
        self.assertIsNone(self.locator.find_day_region(frame, "chs"))
        self.assertIsNone(self.locator.find_map_region(frame))

    def test_roundtable_map_is_not_treated_as_run_map(self):
        self.assertIsNone(self.locator.find_map_region(self.frame("map_detect_tutorial/2.jpg")))

    def test_map_region_located_from_validated_geometry(self):
        h, w, side = 1080, 1920, 756
        x, y = round(w-side-w*.045), (h-side)//2
        background = np.array(Image.open(get_data_path("maps/0.jpg")).convert("RGB").resize((side, side)))
        center = (round(side*.11), round(side*.89))
        cv2.circle(background, center, round(side*.0935), (255, 255, 255), 3)
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[y:y+side, x:x+side] = background
        region = self.locator.find_map_region(frame)
        self.assertIsNotNone(region)
        self.assertLess(abs(region[0]-x), 20)
        self.assertLess(abs(region[1]-y), 20)
        self.assertLess(abs(region[2]-side), 20)

    def test_signature_ignores_tiny_cursor_changes(self):
        from src.automation import signature_distance
        frame = np.full((750, 750, 3), 50, dtype=np.uint8)
        changed = frame.copy()
        changed[100:105, 100:105] = 255
        self.assertLess(signature_distance(map_signature(frame), map_signature(changed)), 3)


if __name__ == "__main__":
    unittest.main()

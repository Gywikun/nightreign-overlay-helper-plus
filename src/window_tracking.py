# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02; see NOTICE.md and LICENSE (GNU AGPL v3).
"""Locate the game and its HUD using screenshots only."""
import cv2
import numpy as np
from PIL import Image

from src.common import GAME_WINDOW_TITLE
from src.config import Config
from src.detector.day_detector import get_image_mask
from src.detector.utils import convert_hdr_to_sdr


REGION_NAMES = ("day1_detect_region", "hpcolor_detect_region", "map_region", "hpbar_region", "art_region")


def game_client_rect():
    try:
        import win32gui
        candidates = []
        def collect(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
                return
            if GAME_WINDOW_TITLE.casefold() not in win32gui.GetWindowText(hwnd).casefold():
                return
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            x, y = win32gui.ClientToScreen(hwnd, (left, top))
            if right - left >= 640 and bottom - top >= 360:
                candidates.append((hwnd, (x, y, right - left, bottom - top)))
        win32gui.EnumWindows(collect, None)
        if candidates:
            foreground = win32gui.GetForegroundWindow()
            candidates.sort(key=lambda item: (item[0] == foreground, item[1][2] * item[1][3]), reverse=True)
            return candidates[0][1]
    except Exception:
        pass
    return None


def map_signature(image):
    # Coarse luminance makes the update scheduler insensitive to small cursor moves.
    image = cv2.resize(image, (24, 24), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    return gray.reshape(-1).tolist()


class AutomaticLocator:
    def __init__(self, detectors):
        self.detectors = detectors

    def find_day_region(self, frame, language, hdr=False):
        h, w = frame.shape[:2]
        # DAY cues appear centrally, unlike the smaller persistent HUD text.
        x, y, cw, ch = int(w * .25), int(h * .35), int(w * .5), int(h * .32)
        image = Image.fromarray(frame[y:y+ch, x:x+cw])
        if hdr:
            image = convert_hdr_to_sdr(image)
        scale = 540 / h
        image = image.resize((round(cw * scale), round(ch * scale)))
        mask = get_image_mask(image, strict=True)
        template = self.detectors.day_detector.templates[language]
        best = None
        for day, template_mask in enumerate((template.day1_mask, template.day2_mask, template.day3_mask), 1):
            for factor in np.linspace(.7, 1.6, 31):
                th, tw = template_mask.shape
                resized = cv2.resize(template_mask, (max(1, round(tw * factor)), max(1, round(th * factor))))
                if resized.shape[0] > mask.shape[0] or resized.shape[1] > mask.shape[1]:
                    continue
                result = cv2.matchTemplate(mask, resized, cv2.TM_SQDIFF_NORMED)
                score, _, location, _ = cv2.minMaxLoc(result)
                if best is None or score < best[0]:
                    best = score, day, location, resized.shape
        if best is None or best[0] > .42:
            return None
        score, day, (mx, my), (mh, mw) = best
        ratio = (1, template.day2_w_ratio, template.day3_w_ratio)[day-1]
        day1_w = mw / ratio / scale
        cx = x + (mx + mw / 2) / scale
        return [round(cx - day1_w / 2), round(y + my / scale), round(day1_w), round(mh / scale)]

    def find_health_regions(self, frame, hdr=False):
        config = Config.get()
        h, w = frame.shape[:2]
        top, left = int(h * .015), int(w * .06)
        crop = frame[top:int(h * .13), left:int(w * .47)]
        hls = cv2.cvtColor(crop, cv2.COLOR_RGB2HLS)
        suffix = "_hdr" if hdr else ""
        masks = []
        for state in ("not_in_rain", "in_rain"):
            a = np.array(getattr(config, "lower_hls_" + state + suffix))
            b = np.array(getattr(config, "upper_hls_" + state + suffix))
            tolerance = np.array([config.h_tolerance, config.l_tolerance, config.s_tolerance])
            masks.append(cv2.inRange(hls, np.minimum(a, b) - tolerance, np.maximum(a, b) + tolerance))
        mask = cv2.bitwise_or(*masks)
        # Alternate brightness presets shift the HP hue beyond the default color.
        red = cv2.inRange(hls, (0, 35, 65), (22, 255, 255))
        purple = cv2.inRange(hls, (140, 35, 65), (179, 255, 255))
        mask = cv2.bitwise_or(mask, cv2.bitwise_or(red, purple))
        kernel = np.ones((1, max(3, round(w / 140))), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        candidates = []
        for bx, by, bw, bh, area in stats[1:]:
            if bw >= w * .03 and 2 <= bh <= h * .025 and bw / bh >= 5 and area >= bw * 1.2:
                candidates.append((by, -bw, bx, bw, bh))
        if not candidates:
            return {}
        by, _, bx, bw, bh = min(candidates)
        px, py = left + int(bx), top + int(by) + int(bh) // 2
        thickness = max(1, round(2 * h / 540))
        return {"hpcolor_detect_region": [px+3, py, max(4, min(round(w*.02), int(bw)//3)), 1],
                "hpbar_region": [px, py, max(5, int(bw)), thickness]}

    def find_map_region(self, frame):
        from src.detector.map_detector import (MATCH_EARTH_SHIFTING_SIZE, MATCH_EARTH_SHIFTING_REGION, MAP_BGS)
        h, w = frame.shape[:2]
        best, candidates = None, []
        backgrounds = []
        rx, ry, rw, rh = MATCH_EARTH_SHIFTING_REGION
        for background in MAP_BGS.values():
            resized = cv2.resize(background, MATCH_EARTH_SHIFTING_SIZE)
            backgrounds.append(resized[ry:ry+rh, rx:rx+rw].astype(np.int16))
        # The normal full-map panel is a square on the right side of the client.
        # Both the full-map circle and terrain match must agree before adoption.
        for side_ratio in (.69, .70, .72, .68, .74):
            side = round(h * side_ratio)
            for margin in (.045, .04, .05):
                x, y = round(w - side - w * margin), round((h - side) / 2)
                if x < 0 or y < 0:
                    continue
                crop = frame[y:y+side, x:x+side]
                full_error = self.detectors.map_detector._match_full_map(crop)
                if full_error > Config.get().full_map_error_threshold:
                    continue
                resized = cv2.resize(crop, MATCH_EARTH_SHIFTING_SIZE)[ry:ry+rh, rx:rx+rw].astype(np.int16)
                coarse_error = min(float(np.median(np.linalg.norm(resized - background, axis=2))) for background in backgrounds)
                candidates.append((coarse_error, full_error, [x, y, side, side]))
        # Fast coarse ranking limits expensive terrain validation to three regions.
        for _, full_error, region in sorted(candidates, key=lambda item: (item[0], item[1]))[:3]:
            x, y, side, _ = region
            terrain, terrain_error = self.detectors.map_detector._match_earth_shifting(frame[y:y+side, x:x+side])
            if terrain_error <= Config.get().earth_shifting_error_threshold:
                score = terrain_error + full_error
                if best is None or score < best[0]:
                    best = score, region
                if terrain_error <= 8:
                    break
        return best[1] if best else None

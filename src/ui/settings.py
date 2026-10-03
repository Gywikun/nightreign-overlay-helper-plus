# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02 and 2026-10-03; see NOTICE.md and LICENSE (GNU AGPL v3).
from PyQt6.QtCore import Qt, pyqtSignal, QPoint, QEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QSlider, QGroupBox, QCheckBox, QPushButton,
    QMessageBox, QApplication, QFrame, QComboBox, QToolTip,
    QDialog, QTextBrowser,
    QLineEdit, QScrollArea,
)
from PyQt6.QtGui import QPixmap, QIcon, QMouseEvent, QEnterEvent
import yaml
from dataclasses import dataclass, asdict
import os
import ctypes
import shutil
import re

from src.updater import Updater
from src.common import (
    APP_FULLNAME, APP_NAME, APP_VERSION,
    get_appdata_path, get_asset_path, get_desktop_path,
    ICON_PATH, load_yaml, save_yaml, resource_path,
)
from src.logger import info, warning, error, set_log_level, INFO, DEBUG
from src.config import Config
from src.ui.overlay import OverlayUIState, OverlayWidget
from src.ui.map_overlay import MapOverlayWidget, MapOverlayUIState
from src.ui.input import InputWorker, InputSettingWidget, InputSetting
from src.ui.capture_region import CaptureRegionWindow
from src.detector.rain_detector import RainDetector
from src.detector.utils import hls_to_rgb
from src.ui.bug_report import BugReportWindow
from src.ui.utils import process_region_to_adapt_scale, get_qt_screen_by_mss_region
from src.ui.enhancements import EnhancementDialog


BUTTON_STYLE = "padding: 4px; min-height: 20px;"

SETTINGS_SAVE_PATH = get_appdata_path("settings.yaml")
PRESET_SETTINGS_DIR = get_appdata_path("preset_settings")

COLOR_ALIGN_TUTORIAL_IMG_PATH = get_asset_path("color_align_tutorial/{i}.jpg")
HP_DETECT_TUTORIAL_IMG_PATH = get_asset_path("hp_detect_tutorial/{i}.jpg")
ART_DETECT_TUTORIAL_IMG_PATH = get_asset_path("art_detect_tutorial/{i}.jpg")


def info_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Information)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def warning_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Warning)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def error_box(message: str, parent=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.exec()

def comfirm_box(message: str, parent=None) -> bool:
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Question)
    msg.setWindowTitle(APP_FULLNAME)
    msg.setText(message)
    msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    result = msg.exec()
    return result == QMessageBox.StandardButton.Yes


class QuickTooltipLabel(QLabel):
    """快速显示tooltip的标签"""
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
    
    def enterEvent(self, event: QEnterEvent):
        # 鼠标进入时立即显示tooltip
        if self.toolTip():
            QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip(), self)
        super().enterEvent(event)
    
    def mousePressEvent(self, event: QMouseEvent):
        # 点击时也显示tooltip
        if event.button() == Qt.MouseButton.LeftButton and self.toolTip():
            QToolTip.showText(event.globalPosition().toPoint(), self.toolTip(), self)
        super().mousePressEvent(event)


class PresetDialog(QWidget):
    save_preset_signal = pyqtSignal(str)
    load_preset_signal = pyqtSignal(str)
    remove_preset_signal = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("预设设置")
        self.setMinimumSize(350, 400)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self._init_ui()

    def _init_ui(self):
        self.main_layout = QVBoxLayout(self)

        # --- 1. 保存预设部分 ---
        save_layout = QHBoxLayout()
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("输入新预设名称...")
        self.save_btn = QPushButton("保存预设")
        self.save_btn.clicked.connect(self._on_save_clicked)
        
        save_layout.addWidget(self.name_input)
        save_layout.addWidget(self.save_btn)
        self.main_layout.addLayout(save_layout)

        # 分割线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        self.main_layout.addWidget(line)

        # --- 2. 预设列表展示部分 ---
        self.main_layout.addWidget(QLabel("已有预设列表:"))
        
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidget(self.list_container)
        
        self.main_layout.addWidget(self.scroll_area)

    def set_preset_names(self, names: list[str]):
        """更新预设名称列表并重新渲染UI"""
        # 清空当前布局中的所有组件
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        # 重新填充
        for name in names:
            item_widget = QWidget()
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(5, 2, 5, 2)

            name_label = QLabel(name)
            load_btn = QPushButton("加载")
            load_btn.setFixedWidth(60)
            # 使用 lambda 捕获当前的 name
            load_btn.clicked.connect(lambda checked, n=name: self.load_preset_signal.emit(n))

            remove_btn = QPushButton("删除")
            remove_btn.setFixedWidth(60)
            remove_btn.setStyleSheet("color: red;")
            remove_btn.clicked.connect(lambda checked, n=name: self.remove_preset_signal.emit(n))

            item_layout.addWidget(name_label)
            item_layout.addWidget(load_btn)
            item_layout.addWidget(remove_btn)
            
            self.list_layout.addWidget(item_widget)

    def _is_valid_filename(self, filename: str) -> bool:
        """检查是否是合适的文件名 (Windows/Linux 通用规则)"""
        if not filename or filename.strip() == "":
            return False
        # 禁止包含 / \ : * ? " < > |
        invalid_chars = r'[\\/:*?"<>|]'
        if re.search(invalid_chars, filename):
            return False
        # 限制长度
        if len(filename) > 200:
            return False
        return True

    def _on_save_clicked(self):
        """保存按钮点击逻辑"""
        name = self.name_input.text().strip()
        if self._is_valid_filename(name):
            self.save_preset_signal.emit(name)
            self.name_input.clear()  # 发送后清空输入框
        else:
            warning_box("无效的预设名称！请避免使用特殊字符 / \\ : * ? \" < > | 并确保名称非空且不过长。", self)


class SettingsWindow(QWidget):
    update_overlay_ui_state_signal = pyqtSignal(OverlayUIState)
    update_map_overlay_ui_state_signal = pyqtSignal(MapOverlayUIState)
    update_preset_list_signal = pyqtSignal(list)


    def init_appearance_group(self):
        # 外观设置
        self.appearance_group = QGroupBox("计时器外观")
        self.appearance_layout = QVBoxLayout(self.appearance_group)

        size_layout = QHBoxLayout()
        size_layout.addWidget(QLabel("大小"))
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(5, 1000)
        self.size_slider.setValue(self.overlay.width())
        self.size_slider.valueChanged.connect(self.update_overlay_size)
        size_layout.addWidget(self.size_slider)
        self.appearance_layout.addLayout(size_layout)
        
        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(QLabel("透明度"))
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.setValue(int(self.overlay.windowOpacity() * 100))
        self.opacity_slider.valueChanged.connect(self.update_overlay_opacity)
        opacity_layout.addWidget(self.opacity_slider)
        self.appearance_layout.addLayout(opacity_layout)

        set_position_center_layout = QHBoxLayout()
        set_position_center_button = QPushButton("设置水平居中")
        set_position_center_button.setStyleSheet(BUTTON_STYLE)
        set_position_center_button.clicked.connect(self.update_overlay_position_center)
        set_position_center_layout.addWidget(set_position_center_button)
        self.appearance_layout.addLayout(set_position_center_layout)

        reset_position_layout = QHBoxLayout()
        reset_position_button = QPushButton("重置位置到主屏幕中心")
        reset_position_button.setStyleSheet(BUTTON_STYLE)
        reset_position_button.clicked.connect(self.reset_overlay_position)
        reset_position_layout.addWidget(reset_position_button)
        self.appearance_layout.addLayout(reset_position_layout)

        hide_text_layout = QHBoxLayout()
        self.hide_text_checkbox = QCheckBox("隐藏计时文字（保留地图状态）")
        self.hide_text_checkbox.stateChanged.connect(self.update_hide_text)
        hide_text_layout.addWidget(self.hide_text_checkbox)
        self.appearance_layout.addLayout(hide_text_layout)

        self.appearance_layout.addWidget(QLabel("提示：现在可以用鼠标左键拖动调整位置"))
        self.appearance_layout.addWidget(QLabel("⚠️请使用窗口化/无边框窗口化模式启动游戏"))
        self.appearance_layout.addWidget(QLabel("⚠️悬浮窗与部分AI补帧工具（小黄鸭）不兼容\n"
                                                 "同时使用可能出现卡顿"))

    def init_input_group(self):
        config = Config.get()

        # 输入设置
        self.input_group = QGroupBox("计时快捷键")
        self.input_layout = QVBoxLayout(self.input_group)

        day_input_layout = QHBoxLayout()
        day_input_layout.addWidget(QLabel("重置缩圈"))
        self.day_input_setting_widget = InputSettingWidget(self.input)
        self.day_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("advance_day"))
        day_input_layout.addWidget(self.day_input_setting_widget)
        self.input_layout.addLayout(day_input_layout)

        forward_day_input_layout = QHBoxLayout()
        forward_day_input_layout.addWidget(QLabel(f"快进缩圈{config.foward_day_seconds}秒"))
        self.forward_day_input_setting_widget = InputSettingWidget(self.input)
        self.forward_day_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("forward_day"))
        forward_day_input_layout.addWidget(self.forward_day_input_setting_widget)
        self.input_layout.addLayout(forward_day_input_layout)

        back_day_input_layout = QHBoxLayout()
        back_day_input_layout.addWidget(QLabel(f"倒退缩圈{config.back_day_seconds}秒"))
        self.back_day_input_setting_widget = InputSettingWidget(self.input)
        self.back_day_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("back_day"))
        back_day_input_layout.addWidget(self.back_day_input_setting_widget)
        self.input_layout.addLayout(back_day_input_layout)

        in_rain_input_layout = QHBoxLayout()
        in_rain_input_layout.addWidget(QLabel("开始雨中冒险"))
        self.in_rain_input_setting_widget = InputSettingWidget(self.input)
        self.in_rain_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("toggle_rain"))
        in_rain_input_layout.addWidget(self.in_rain_input_setting_widget)
        self.input_layout.addLayout(in_rain_input_layout)

        self.input_layout.addWidget(QLabel("点击按钮修改，支持键盘或手柄组合键"))

    def init_performance_group(self):
        config = Config.get()

        # 性能设置
        self.performance_group = QGroupBox("性能")
        self.performance_layout = QVBoxLayout(self.performance_group)

        detect_interval_layout = QHBoxLayout()
        detect_interval_layout.addWidget(QLabel("自动检测频率"))
        self.detect_interval_combobox = QComboBox()
        for k in config.detect_intervals.keys():
            self.detect_interval_combobox.addItem(k)
        self.detect_interval_combobox.setCurrentText("高")
        self.detect_interval_combobox.currentTextChanged.connect(self.update_detect_interval)
        detect_interval_layout.addWidget(self.detect_interval_combobox)
        self.performance_layout.addLayout(detect_interval_layout)

        only_show_when_game_foreground_layout = QHBoxLayout()
        self.only_show_when_game_foreground_checkbox = QCheckBox("仅在游戏时显示和检测")
        self.only_show_when_game_foreground_checkbox.setChecked(False)
        self.only_show_when_game_foreground_checkbox.stateChanged.connect(self.update_only_show_when_game_foreground)
        only_show_when_game_foreground_layout.addWidget(self.only_show_when_game_foreground_checkbox)
        self.performance_layout.addLayout(only_show_when_game_foreground_layout)

    def init_auto_timer_group(self):
        config = Config.get()

        # 自动计时设置
        self.auto_timer_group = QGroupBox("缩圈&雨中冒险倒计时")
        self.auto_timer_layout = QVBoxLayout(self.auto_timer_group)

        screenshot_region_help_layout = QHBoxLayout()
        help_button = QPushButton("查看自动计时帮助")
        help_button.setStyleSheet("padding: 6px;")
        help_button.clicked.connect(self.show_capture_day1_hpcolor_region_tutorial)
        screenshot_region_help_layout.addWidget(help_button)
        self.auto_timer_layout.addLayout(screenshot_region_help_layout)

        auto_timer_enable_layout = QHBoxLayout()
        dayx_detect_enable_layout = QHBoxLayout()
        self.dayx_detect_enable_checkbox = QCheckBox("缩圈自动计时")
        self.dayx_detect_enable_checkbox.stateChanged.connect(self.update_dayx_detect_enable)
        dayx_detect_enable_layout.addWidget(self.dayx_detect_enable_checkbox)
        dayx_detect_enable_layout.addStretch()
        auto_timer_enable_layout.addLayout(dayx_detect_enable_layout)
        in_rain_detect_enable_layout = QHBoxLayout()
        self.in_rain_detect_enable_checkbox = QCheckBox("雨中冒险自动计时")
        self.in_rain_detect_enable_checkbox.stateChanged.connect(self.update_in_rain_detect_enable)
        in_rain_detect_enable_layout.addWidget(self.in_rain_detect_enable_checkbox)
        in_rain_detect_enable_layout.addStretch()
        auto_timer_enable_layout.addLayout(in_rain_detect_enable_layout)
        self.auto_timer_layout.addLayout(auto_timer_enable_layout)

        screenshot_region_layout = QHBoxLayout()
        screenshot_region_layout.addWidget(QLabel("截取检测区域快捷键"))
        self.capture_dayx_hpcolor_region_input_widget = InputSettingWidget(self.input)
        self.capture_dayx_hpcolor_region_input_widget.input_triggered.connect(self.capture_day1_hpcolor_region)
        screenshot_region_layout.addWidget(self.capture_dayx_hpcolor_region_input_widget)
        self.auto_timer_layout.addLayout(screenshot_region_layout)

        self.dayx_detect_lang = "chs"
        lang_layout = QHBoxLayout()
        lang_layout.addWidget(QLabel("游戏语言"))
        self.lang_combobox = QComboBox()
        self.lang_combobox.addItems(config.dayx_detect_langs.values())
        self.lang_combobox.setCurrentText(config.dayx_detect_langs[self.dayx_detect_lang])
        self.lang_combobox.currentTextChanged.connect(self.update_detect_lang)
        lang_layout.addWidget(self.lang_combobox)
        self.auto_timer_layout.addLayout(lang_layout)

        self.day1_detect_region = None
        self.day1_detect_region_label = QLabel("缩圈检测区域：未设置")
        self.auto_timer_layout.addWidget(self.day1_detect_region_label)

        self.hpcolor_detect_region = None
        self.hpcolor_detect_region_label = QLabel("雨中冒险检测区域：未设置")
        self.auto_timer_layout.addWidget(self.hpcolor_detect_region_label)

        hp_color_help_layout = QHBoxLayout()
        hp_color_help_button = QPushButton("查看校准血条颜色帮助")
        hp_color_help_button.setStyleSheet(BUTTON_STYLE)
        hp_color_help_button.clicked.connect(self.show_capture_hp_color_help)
        hp_color_help_layout.addWidget(hp_color_help_button)
        self.auto_timer_layout.addLayout(hp_color_help_layout)

        align_to_detect_hp_color_layout = QHBoxLayout()
        align_to_detect_hp_color_layout.addWidget(QLabel("校准血条颜色快捷键"))
        self.align_to_detect_hp_color_input_widget = InputSettingWidget(self.input)
        self.align_to_detect_hp_color_input_widget.input_triggered.connect(self.capture_hp_color)
        align_to_detect_hp_color_layout.addWidget(self.align_to_detect_hp_color_input_widget)
        self.auto_timer_layout.addLayout(align_to_detect_hp_color_layout)
        
        self.not_in_rain_hls = None
        self.in_rain_hls = None
        self.not_in_rain_hls_hdr = None
        self.in_rain_hls_hdr = None
        hp_color_layout = QHBoxLayout()
        hp_color_layout.addWidget(QLabel("正常血条颜色:"))
        self.not_in_rain_label = QLabel("默认")
        hp_color_layout.addWidget(self.not_in_rain_label)
        hp_color_layout.addStretch()
        hp_color_layout.addWidget(QLabel("雨中血条颜色:"))
        self.in_rain_label = QLabel("默认")
        hp_color_layout.addWidget(self.in_rain_label)
        self.auto_timer_layout.addLayout(hp_color_layout)

        clear_to_detect_hp_layout = QHBoxLayout()
        clear_to_detect_hp_color = QPushButton("重置血条颜色设置")
        clear_to_detect_hp_color.setStyleSheet("padding: 6px;")
        clear_to_detect_hp_color.clicked.connect(self.clear_hp_color)
        clear_to_detect_hp_layout.addWidget(clear_to_detect_hp_color)
        clear_to_detect_hp_layout.addStretch()
        self.auto_timer_layout.addLayout(clear_to_detect_hp_layout)

    def init_map_detect_group(self):
        config = Config.get()

        # 地图识别设置
        self.map_detect_group = QGroupBox("地图识别")
        self.map_detect_layout = QVBoxLayout(self.map_detect_group)

        map_detect_help_layout = QHBoxLayout()
        map_help_button = QPushButton("查看地图识别帮助")
        map_help_button.setStyleSheet(BUTTON_STYLE)
        map_help_button.clicked.connect(self.show_capture_map_region_tutorial)
        map_detect_help_layout.addWidget(map_help_button)
        self.map_detect_layout.addLayout(map_detect_help_layout)

        map_detect_enable_layout = QHBoxLayout()
        self.map_detect_enable_checkbox = QCheckBox("启用地图识别")
        self.map_detect_enable_checkbox.stateChanged.connect(self.update_map_detect_enable)
        map_detect_enable_layout.addWidget(self.map_detect_enable_checkbox)
        map_detect_enable_layout.addStretch()
        self.map_detect_layout.addLayout(map_detect_enable_layout)

        capture_map_region_input_setting_layout = QHBoxLayout()
        capture_map_region_input_setting_layout.addWidget(QLabel("截取地图区域快捷键"))
        self.capture_map_region_input_widget = InputSettingWidget(self.input)
        self.capture_map_region_input_widget.input_triggered.connect(self.capture_map_region)
        capture_map_region_input_setting_layout.addWidget(self.capture_map_region_input_widget)
        self.map_detect_layout.addLayout(capture_map_region_input_setting_layout)

        self.map_region = None
        self.map_region_label = QLabel("当前地图区域: 未设置")
        self.map_detect_layout.addWidget(self.map_region_label)

        set_to_detect_map_input_setting_layout = QHBoxLayout()
        set_to_detect_map_input_setting_layout.addWidget(QLabel("识别地图快捷键"))
        self.set_to_detect_map_input_setting_widget = InputSettingWidget(self.input)
        self.set_to_detect_map_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("refresh_map"))
        set_to_detect_map_input_setting_layout.addWidget(self.set_to_detect_map_input_setting_widget)
        self.map_detect_layout.addLayout(set_to_detect_map_input_setting_layout)

        show_map_overlay_input_setting_layout = QHBoxLayout()
        show_map_overlay_input_setting_layout.addWidget(QLabel("显示/隐藏信息快捷键"))
        self.show_map_overlay_input_setting_widget = InputSettingWidget(self.input)
        self.show_map_overlay_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("toggle_map"))
        show_map_overlay_input_setting_layout.addWidget(self.show_map_overlay_input_setting_widget)
        self.map_detect_layout.addLayout(show_map_overlay_input_setting_layout)

        map_pattern_return_topk_setting_layout = QHBoxLayout()
        map_pattern_return_topk_setting_layout.addWidget(QLabel("识别结果返回数量"))
        self.map_pattern_return_topk_combobox = QComboBox()
        for i in range(config.min_map_pattern_match_topk, config.max_map_pattern_match_topk + 1):
            self.map_pattern_return_topk_combobox.addItem(str(i))
        self.map_pattern_return_topk_combobox.setCurrentText(str(config.default_map_pattern_match_topk))
        self.map_pattern_return_topk_combobox.currentTextChanged.connect(self.update_map_pattern_return_topk)
        map_pattern_return_topk_help_label = QuickTooltipLabel("?")
        map_pattern_return_topk_help_label.setStyleSheet("color: gray; font-weight: bold;")
        map_pattern_return_topk_help_label.setToolTip("""
设置每次地图识别时返回的最佳结果数量
由于大空洞某些地图地表建筑相似度较高，难以定位到唯一地图结果，
因此需要在多个候选地图中选择正确的地图
如果识别地图时程序闪退，或者内存占用过大，可以尝试减小此数值
""".strip())
        map_pattern_return_topk_setting_layout.addWidget(self.map_pattern_return_topk_combobox)
        map_pattern_return_topk_setting_layout.addWidget(map_pattern_return_topk_help_label)
        self.map_detect_layout.addLayout(map_pattern_return_topk_setting_layout)

        map_pattern_next_input_setting_layout = QHBoxLayout()
        map_pattern_next_input_setting_layout.addWidget(QLabel("下一个识别结果快捷键"))
        self.map_pattern_next_input_setting_widget = InputSettingWidget(self.input)
        self.map_pattern_next_input_setting_widget.input_triggered.connect(self.map_overlay.next_overlay_image)
        map_pattern_next_input_setting_layout.addWidget(self.map_pattern_next_input_setting_widget)
        self.map_detect_layout.addLayout(map_pattern_next_input_setting_layout)

        map_pattern_last_input_setting_layout = QHBoxLayout()
        map_pattern_last_input_setting_layout.addWidget(QLabel("上一个识别结果快捷键"))
        self.map_pattern_last_input_setting_widget = InputSettingWidget(self.input)
        self.map_pattern_last_input_setting_widget.input_triggered.connect(self.map_overlay.last_overlay_image)
        map_pattern_last_input_setting_layout.addWidget(self.map_pattern_last_input_setting_widget)
        self.map_detect_layout.addLayout(map_pattern_last_input_setting_layout)

        crystal_layout_next_input_setting_layout = QHBoxLayout()
        crystal_layout_next_input_setting_layout.addWidget(QLabel("下一个水晶布局快捷键"))
        self.crystal_layout_next_input_setting_widget = InputSettingWidget(self.input)
        self.crystal_layout_next_input_setting_widget.input_triggered.connect(self.map_overlay.next_crystal_layout)
        crystal_layout_next_input_setting_layout.addWidget(self.crystal_layout_next_input_setting_widget)
        self.map_detect_layout.addLayout(crystal_layout_next_input_setting_layout)

        crystal_layout_last_input_setting_layout = QHBoxLayout()
        crystal_layout_last_input_setting_layout.addWidget(QLabel("上一个水晶布局快捷键"))
        self.crystal_layout_last_input_setting_widget = InputSettingWidget(self.input)
        self.crystal_layout_last_input_setting_widget.input_triggered.connect(self.map_overlay.last_crystal_layout)
        crystal_layout_last_input_setting_layout.addWidget(self.crystal_layout_last_input_setting_widget)
        self.map_detect_layout.addLayout(crystal_layout_last_input_setting_layout)

    def init_other_group(self):
        # 其他设置
        self.other_group = QGroupBox("其他")
        self.other_layout = QVBoxLayout(self.other_group)

        open_preset_dialog_button = QPushButton("管理预设")
        open_preset_dialog_button.setStyleSheet(BUTTON_STYLE)
        open_preset_dialog_button.clicked.connect(self.open_preset_dialog)
        self.other_layout.addWidget(open_preset_dialog_button)

        debug_layout = QHBoxLayout()
        self.other_layout.addLayout(debug_layout)

        bug_report_button = QPushButton("BUG反馈")
        bug_report_button.setStyleSheet(BUTTON_STYLE)
        bug_report_button.clicked.connect(self.open_bug_report_window)
        debug_layout.addWidget(bug_report_button)

        debug_log_layout = QHBoxLayout()
        self.debug_log_checkbox = QCheckBox("开启调试日志")
        self.debug_log_checkbox.setChecked(False)
        self.debug_log_checkbox.stateChanged.connect(self.update_debug_log)
        debug_log_layout.addWidget(self.debug_log_checkbox)
        debug_layout.addLayout(debug_log_layout)

        # HDR图像处理选项
        hdr_processing_layout = QHBoxLayout()
        self.hdr_processing_checkbox = QCheckBox("启用HDR图像处理")
        self.hdr_processing_checkbox.setChecked(False)
        self.hdr_processing_checkbox.stateChanged.connect(self.update_hdr_processing)
        hdr_processing_layout.addWidget(self.hdr_processing_checkbox)
        hdr_processing_help_label = QuickTooltipLabel("?")
        hdr_processing_help_label.setStyleSheet("color: gray; font-weight: bold;")
        hdr_processing_help_label.setToolTip(
            "在HDR显示模式下启用此选项可提高识别准确性\n"
            "程序会自动对不同检测模块应用最佳的图像处理方式：\n"
            "• 缩圈倒计时：HDR到SDR转换\n"
            "• 地图识别：图像归一化(CLAHE)\n"
            "• 血条/雨中检测：保持原始图像\n"
            "如果遇到识别问题，可以尝试关闭此选项"
        )
        hdr_processing_layout.addWidget(hdr_processing_help_label)
        hdr_processing_layout.addStretch()
        self.other_layout.addLayout(hdr_processing_layout)

        open_log_and_abouts_layout = QHBoxLayout()
        self.other_layout.addLayout(open_log_and_abouts_layout)

        open_log_button = QPushButton("打开日志位置")
        open_log_button.setStyleSheet(BUTTON_STYLE)
        open_log_button.clicked.connect(self.open_log_directory)
        open_log_and_abouts_layout.addWidget(open_log_button)

        abouts_button = QPushButton("关于")
        abouts_button.setStyleSheet(BUTTON_STYLE)
        abouts_button.clicked.connect(self.open_about_dialog)
        open_log_and_abouts_layout.addWidget(abouts_button)

    def init_hp_detect_group(self):
        # HP检测设置
        self.hp_detect_group = QGroupBox("血条比例标记")
        self.hp_detect_layout = QVBoxLayout(self.hp_detect_group)
        
        hp_detect_help_layout = QHBoxLayout()
        hp_help_button = QPushButton("查看血条比例标记帮助")
        hp_help_button.setStyleSheet(BUTTON_STYLE)
        hp_help_button.clicked.connect(self.show_capture_hpbar_region_tutorial)
        hp_detect_help_layout.addWidget(hp_help_button)
        self.hp_detect_layout.addLayout(hp_detect_help_layout)

        hp_detect_enable_layout = QHBoxLayout()
        self.hp_detect_enable_checkbox = QCheckBox("启用血条比例标记")
        self.hp_detect_enable_checkbox.stateChanged.connect(self.update_hp_detect_enable)
        hp_detect_enable_layout.addWidget(self.hp_detect_enable_checkbox)
        hp_detect_enable_layout.addStretch()
        self.hp_detect_layout.addLayout(hp_detect_enable_layout)

        hp_detect_keep_last_valid_layout = QHBoxLayout()
        self.hp_detect_keep_last_valid_checkbox = QCheckBox("检测失败时保持上次结果")
        self.hp_detect_keep_last_valid_checkbox.setChecked(False)
        self.hp_detect_keep_last_valid_checkbox.stateChanged.connect(self.update_hp_detect_keep_last_valid)
        hp_detect_keep_last_valid_layout.addWidget(self.hp_detect_keep_last_valid_checkbox)
        hp_detect_keep_last_valid_help_label = QuickTooltipLabel("?")
        hp_detect_keep_last_valid_help_label.setStyleSheet("color: gray; font-weight: bold;")
        hp_detect_keep_last_valid_help_label.setToolTip(
            "开启后，当血条检测暂时失败时，会继续显示上一次的有效结果\n"
            "可以减少标记的抖动和闪烁，提高稳定性"
        )
        hp_detect_keep_last_valid_layout.addWidget(hp_detect_keep_last_valid_help_label)
        hp_detect_keep_last_valid_layout.addStretch()
        self.hp_detect_layout.addLayout(hp_detect_keep_last_valid_layout)

        self.hpbar_region = None
        capture_hpbar_region_input_setting_layout = QHBoxLayout()
        capture_hpbar_region_input_setting_layout.addWidget(QLabel("截取血条区域快捷键"))
        self.capture_hpbar_region_input_widget = InputSettingWidget(self.input)
        self.capture_hpbar_region_input_widget.input_triggered.connect(self.capture_hpbar_region)
        capture_hpbar_region_input_setting_layout.addWidget(self.capture_hpbar_region_input_widget)
        self.hp_detect_layout.addLayout(capture_hpbar_region_input_setting_layout)

        self.hpbar_region_label = QLabel("当前血条区域: 未设置")
        self.hp_detect_layout.addWidget(self.hpbar_region_label)

    def init_art_timer_group(self):
        # 绝招计时器设置
        self.art_timer_group = QGroupBox("绝招倒计时")
        self.art_timer_layout = QVBoxLayout(self.art_timer_group)

        art_detect_help_layout = QHBoxLayout()
        art_help_button = QPushButton("查看绝招倒计时帮助")
        art_help_button.setStyleSheet(BUTTON_STYLE)
        art_help_button.clicked.connect(self.show_capture_art_region_tutorial)
        art_detect_help_layout.addWidget(art_help_button)
        self.art_timer_layout.addLayout(art_detect_help_layout)

        art_detect_enable_layout = QHBoxLayout()
        self.art_detect_enable_checkbox = QCheckBox("启用绝招倒计时")
        self.art_detect_enable_checkbox.stateChanged.connect(self.update_art_detect_enable)
        art_detect_enable_layout.addWidget(self.art_detect_enable_checkbox)
        art_detect_enable_layout.addStretch()
        self.art_timer_layout.addLayout(art_detect_enable_layout)

        self.art_region = None
        capture_art_region_input_setting_layout = QHBoxLayout()
        capture_art_region_input_setting_layout.addWidget(QLabel("截取绝招图标区域快捷键"))
        self.capture_art_region_input_widget = InputSettingWidget(self.input)
        self.capture_art_region_input_widget.input_triggered.connect(self.capture_art_region)
        capture_art_region_input_setting_layout.addWidget(self.capture_art_region_input_widget)
        self.art_timer_layout.addLayout(capture_art_region_input_setting_layout)

        use_art_input_setting_layout = QHBoxLayout()
        use_art_input_setting_layout.addWidget(QLabel("绝招快捷键"))
        self.use_art_input_setting_widget = InputSettingWidget(self.input)
        self.use_art_input_setting_widget.input_triggered.connect(lambda: self.updater.submit_command("use_art"))
        use_art_input_setting_layout.addWidget(self.use_art_input_setting_widget)
        self.art_timer_layout.addLayout(use_art_input_setting_layout)

        self.art_region_label = QLabel("当前绝招图标区域: 未设置")
        self.art_timer_layout.addWidget(self.art_region_label)

    def init_layouts(self):
        # Layouts  
        layouts = [QVBoxLayout() for _ in range(3)]

        layouts[0].addWidget(self.appearance_group)
        layouts[0].addWidget(self.input_group)
        layouts[0].addWidget(self.other_group)

        layouts[1].addWidget(self.performance_group)
        layouts[1].addWidget(self.auto_timer_group)
        layouts[1].addWidget(self.art_timer_group)

        layouts[2].addWidget(self.map_detect_group)
        layouts[2].addWidget(self.hp_detect_group)

        self.layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("自动增强"))
        for label, tab in (("自动运行", 0), ("检测自检", 1), ("关键提醒", 2), ("计时纠正", 3)):
            button = QPushButton(label)
            button.clicked.connect(lambda checked, index=tab: self.show_enhancements(index))
            toolbar.addWidget(button)
        self.layout.addLayout(toolbar)
        columns = QHBoxLayout()
        for l in layouts:
            l.addStretch()
            columns.addLayout(l)
        self.layout.addLayout(columns)

    def init_preset_dialog(self):
        self.preset_dialog = PresetDialog()
        self.preset_dialog.save_preset_signal.connect(self.save_preset)
        self.preset_dialog.load_preset_signal.connect(self.load_preset)
        self.preset_dialog.remove_preset_signal.connect(self.remove_preset)
        self.update_preset_list_signal.connect(self.preset_dialog.set_preset_names)
        self.update_preset_list()


    def load_settings(self):
        self._loading_settings = True
        try:
            def load_checkbox_state(checkbox: QCheckBox, state: bool):
                checkbox.setChecked(not state)
                checkbox.setChecked(state)
            def load_slider_value(slider: QSlider, value: int):
                slider.setValue(value - 1)
                slider.setValue(value)
            def load_combobox_value(combobox: QComboBox, value: str):
                combobox.setCurrentText(None)
                combobox.setCurrentText(value)

            info("------------------------")
            info("Start to load settings")
            config = Config.get()
            if os.path.exists(SETTINGS_SAVE_PATH):
                data = load_yaml(SETTINGS_SAVE_PATH)
                info(f"Loaded settings from {SETTINGS_SAVE_PATH}")
            else:
                data = {}
                warning(f"Settings file not found: {SETTINGS_SAVE_PATH}, using defaults")
            # 外观
            load_slider_value(self.size_slider, data.get("size", 200))
            load_slider_value(self.opacity_slider, data.get("opacity", 60))
            self.update_overlay_ui_state_signal.emit(OverlayUIState(
                x=data.get("x"),
                y=data.get("y"),
            ))
            load_checkbox_state(self.hide_text_checkbox, data.get("hide_text", False))
            # 快捷键
            self.day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("day_input_setting")))
            self.forward_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("forward_day_input_setting")))
            self.back_day_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("back_day_input_setting")))
            self.in_rain_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("in_rain_input_setting")))
            # 性能
            load_checkbox_state(self.only_show_when_game_foreground_checkbox, data.get("only_show_when_game_foreground", True))
            load_combobox_value(self.detect_interval_combobox, data.get("detect_interval", "高"))
            # 自动计时
            load_checkbox_state(self.dayx_detect_enable_checkbox, data.get("dayx_detect_enabled", True))
            load_checkbox_state(self.in_rain_detect_enable_checkbox, data.get("in_rain_detect_enabled", True))
            self.capture_dayx_hpcolor_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_dayx_hpbar_region_input_setting")))
            self.dayx_detect_lang = data.get("dayx_detect_lang", "chs")
            load_combobox_value(self.lang_combobox, config.dayx_detect_langs[self.dayx_detect_lang])
            self.day1_detect_region = data.get("day1_detect_region", None)
            self.hpcolor_detect_region = data.get("hp_bar_detect_region", None)
            self.update_day1_hpcolor_regions()
            self.align_to_detect_hp_color_input_widget.set_setting(InputSetting.load_from_dict(data.get("align_to_detect_hp_color_input_setting")))
            self.not_in_rain_hls = data.get("not_in_rain_hls", None)
            self.in_rain_hls = data.get("in_rain_hls", None)
            self.not_in_rain_hls_hdr = data.get("not_in_rain_hls_hdr", None)
            self.in_rain_hls_hdr = data.get("in_rain_hls_hdr", None)
            self.update_hp_color()
            # 地图识别
            load_checkbox_state(self.map_detect_enable_checkbox, data.get("map_detect_enabled", True))
            self.capture_map_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_map_region_input_setting")))
            self.map_region = data.get("map_region", None)
            self.update_map_region()
            self.set_to_detect_map_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("set_to_detect_map_input_setting")))
            self.show_map_overlay_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("show_map_overlay_input_setting")))
            load_combobox_value(self.map_pattern_return_topk_combobox, str(data.get("map_pattern_return_topk", config.default_map_pattern_match_topk)))
            self.map_pattern_next_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("next_map_pattern_input_setting")))
            self.map_pattern_last_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("last_map_pattern_input_setting")))
            self.crystal_layout_next_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("next_crystal_layout_input_setting")))
            self.crystal_layout_last_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("last_crystal_layout_input_setting")))
            # 血条比例标记
            load_checkbox_state(self.hp_detect_enable_checkbox, data.get("hp_detect_enabled", True))
            load_checkbox_state(self.hp_detect_keep_last_valid_checkbox, data.get("hp_detect_keep_last_valid", False))
            self.capture_hpbar_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_hpbar_region_input_setting")))
            self.hpbar_region = data.get("hpbar_region", None)
            self.update_hpbar_region()
            # 绝招计时器
            load_checkbox_state(self.art_detect_enable_checkbox, data.get("art_detect_enabled", True))
            self.capture_art_region_input_widget.set_setting(InputSetting.load_from_dict(data.get("capture_art_region_input_setting")))
            self.use_art_input_setting_widget.set_setting(InputSetting.load_from_dict(data.get("use_art_input_setting")))
            self.art_region = data.get("art_region", None)
            self.update_art_region()
            # 其他
            load_checkbox_state(self.debug_log_checkbox, data.get("debug_log_enabled", False))
            # HDR图像处理
            load_checkbox_state(self.hdr_processing_checkbox, data.get("hdr_processing_enabled", False))

            info("Settings loaded successfully")
        except Exception as e:
            error(f"Failed to load settings: {e}")
        self._loading_settings = False
        info("------------------------")

    def save_settings(self):
        try:
            data = {
                # 外观
                "size": self.size_slider.value(),
                "opacity": self.opacity_slider.value(),
                "x": self.overlay.x(),
                "y": self.overlay.y(),
                "hide_text": self.hide_text_checkbox.isChecked(),
                # 快捷键
                "day_input_setting": asdict(self.day_input_setting_widget.get_setting()),
                "forward_day_input_setting": asdict(self.forward_day_input_setting_widget.get_setting()),
                "back_day_input_setting": asdict(self.back_day_input_setting_widget.get_setting()),
                "in_rain_input_setting": asdict(self.in_rain_input_setting_widget.get_setting()),
                # 性能
                "only_show_when_game_foreground": self.only_show_when_game_foreground_checkbox.isChecked(),
                "detect_interval": self.detect_interval_combobox.currentText(),
                # 自动计时
                "dayx_detect_enabled": self.dayx_detect_enable_checkbox.isChecked(),
                "in_rain_detect_enabled": self.in_rain_detect_enable_checkbox.isChecked(),
                "capture_dayx_hpbar_region_input_setting": asdict(self.capture_dayx_hpcolor_region_input_widget.get_setting()),
                "dayx_detect_lang": self.dayx_detect_lang,
                "day1_detect_region": self.day1_detect_region,
                "hp_bar_detect_region": self.hpcolor_detect_region,
                "align_to_detect_hp_color_input_setting": asdict(self.align_to_detect_hp_color_input_widget.get_setting()),
                "not_in_rain_hls": self.not_in_rain_hls,
                "in_rain_hls": self.in_rain_hls,
                "not_in_rain_hls_hdr": self.not_in_rain_hls_hdr,
                "in_rain_hls_hdr": self.in_rain_hls_hdr,
                # 地图识别
                "map_detect_enabled": self.map_detect_enable_checkbox.isChecked(),
                "capture_map_region_input_setting": asdict(self.capture_map_region_input_widget.get_setting()),
                "map_region": self.map_region,
                "set_to_detect_map_input_setting": asdict(self.set_to_detect_map_input_setting_widget.get_setting()),
                "show_map_overlay_input_setting": asdict(self.show_map_overlay_input_setting_widget.get_setting()),
                "map_pattern_return_topk": int(self.map_pattern_return_topk_combobox.currentText()),
                "next_map_pattern_input_setting": asdict(self.map_pattern_next_input_setting_widget.get_setting()),
                "last_map_pattern_input_setting": asdict(self.map_pattern_last_input_setting_widget.get_setting()),
                "next_crystal_layout_input_setting": asdict(self.crystal_layout_next_input_setting_widget.get_setting()),
                "last_crystal_layout_input_setting": asdict(self.crystal_layout_last_input_setting_widget.get_setting()),
                # 血条比例标记
                "hp_detect_enabled": self.hp_detect_enable_checkbox.isChecked(),
                "hp_detect_keep_last_valid": self.hp_detect_keep_last_valid_checkbox.isChecked(),
                "capture_hpbar_region_input_setting": asdict(self.capture_hpbar_region_input_widget.get_setting()),
                "hpbar_region": self.hpbar_region,
                # 绝招计时器
                "art_detect_enabled": self.art_detect_enable_checkbox.isChecked(),
                "capture_art_region_input_setting": asdict(self.capture_art_region_input_widget.get_setting()),
                "use_art_input_setting": asdict(self.use_art_input_setting_widget.get_setting()),
                "art_region": self.art_region,
                # 其他
                "debug_log_enabled": self.debug_log_checkbox.isChecked(),
                "hdr_processing_enabled": self.hdr_processing_checkbox.isChecked(),
            }
            save_yaml(SETTINGS_SAVE_PATH, data)
            info(f"Saved settings to {SETTINGS_SAVE_PATH}")
        except Exception as e:
            error(f"Failed to save settings: {e}")


    def showEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=True,
            is_setting_opened=True,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=True,
        ))
        self.updater.is_setting_opened = True
        # self.load_settings()
        super().showEvent(event)
        info("Settings window opened")

    def closeEvent(self, event):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(
            draggable=False,
            is_setting_opened=False,
        ))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(
            is_setting_opened=False,
        ))
        self.updater.is_setting_opened = False
        self.save_settings()
        super().closeEvent(event)
        info("Settings window closed")


    def __init__(self, overlay: OverlayWidget, map_overlay: MapOverlayWidget, updater: Updater, input: InputWorker):
        super().__init__()
        config = Config.get()
        self.overlay = overlay
        self.map_overlay = map_overlay
        self.update_overlay_ui_state_signal.connect(overlay.update_ui_state)
        self.update_map_overlay_ui_state_signal.connect(map_overlay.update_ui_state)
        self.updater = updater
        self.input = input

        self.setWindowIcon(QIcon(ICON_PATH))
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f'{APP_NAME}.{APP_VERSION}')
        except Exception as e:
            warning(f"Failed to set AppUserModelID: {e}")

        self.setWindowTitle(f"{APP_FULLNAME} - 设置")
        self.setMinimumSize(350, 200)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)

        self.init_appearance_group()
        self.init_input_group()
        self.init_performance_group()                                        
        self.init_auto_timer_group()
        self.init_map_detect_group()
        self.init_other_group()
        self.init_hp_detect_group()
        self.init_art_timer_group()

        self.init_layouts()

        self.init_preset_dialog()

        # 加载设置
        self.load_settings()
        self.enhancement_dialog = EnhancementDialog(self)
        self.updater.regions_changed_signal.connect(self.accept_automatic_regions)
        self.updater.colors_changed_signal.connect(self.accept_automatic_colors)

    def accept_automatic_colors(self, colors):
        for name, value in colors.items():
            setattr(self, name, value)
        self.update_hp_color()
        self.save_settings()

    def show_enhancements(self, tab=0):
        self.enhancement_dialog.tabs.setCurrentIndex(tab)
        self.enhancement_dialog.show()
        self.enhancement_dialog.raise_()
        self.enhancement_dialog.activateWindow()

    def accept_automatic_regions(self, regions):
        labels = {"day1_detect_region": self.day1_detect_region_label,
                  "hpcolor_detect_region": self.hpcolor_detect_region_label,
                  "map_region": self.map_region_label,
                  "hpbar_region": self.hpbar_region_label,
                  "art_region": self.art_region_label}
        for name, region in regions.items():
            if name in labels:
                setattr(self, name, list(region))
                labels[name].setText("已自动定位: " + str(region))


    # =========================== Preset =========================== #

    def load_preset(self, preset_name: str):
        info(f"Loading preset settings '{preset_name}'")

        if not comfirm_box(f"是否加载预设设置：\"{preset_name}\"？\n当前设置将被覆盖。", self.preset_dialog):
            info(f"Loading preset settings '{preset_name}' canceled by user")
            return

        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if not os.path.exists(preset_path):
            warning(f"Preset settings file not found: {preset_path}")
            error_box(f"预设配置文件未找到：{preset_path}", self.preset_dialog)
        
        # overide current settings with preset
        current_path = SETTINGS_SAVE_PATH
        if os.path.exists(current_path + '.bak'):
            os.remove(current_path + '.bak')
        os.rename(current_path, current_path + ".bak")
        try:
            shutil.copyfile(preset_path, current_path)
            self.load_settings()
            self.updater.submit_command("anchor_regions")
            info(f"Loaded preset settings '{preset_name}' from {preset_path}")
            info_box(f"成功加载预设设置：{preset_name}", self.preset_dialog)
        except Exception as e:
            os.rename(current_path + ".bak", current_path)
            error(f"Failed to load preset settings '{preset_name}': {e}")
            error_box(f"加载预设设置失败：{e}\n已还原到之前的设置。", self.preset_dialog)
        
        self.update_preset_list()
        
    def save_preset(self, preset_name: str):
        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if os.path.exists(preset_path):
            if not comfirm_box(f"预设设置 \"{preset_name}\"已存在，是否覆盖？", self.preset_dialog):
                info(f"Saving preset settings '{preset_name}' canceled by user")
                return
        try:
            os.makedirs(PRESET_SETTINGS_DIR, exist_ok=True)
            self.save_settings()
            shutil.copyfile(SETTINGS_SAVE_PATH, preset_path)
            info(f"Saved preset settings '{preset_name}' to {preset_path}")
            # info_box(f"成功保存预设设置：\"{preset_name}\"", self.preset_dialog)

        except Exception as e:
            error(f"Failed to save preset settings '{preset_name}': {e}")
            error_box(f"保存预设设置失败：{e}", self.preset_dialog)

        self.update_preset_list()

    def remove_preset(self, preset_name: str):
        preset_path = os.path.join(PRESET_SETTINGS_DIR, f"{preset_name}.yaml")
        if not os.path.exists(preset_path):
            warning(f"Preset settings file not found: {preset_path}")
            error_box(f"预设配置文件未找到：{preset_path}", self.preset_dialog)
            return
        if not comfirm_box(f"是否删除预设设置：\"{preset_name}\"？", self.preset_dialog):
            info(f"Removing preset settings '{preset_name}' canceled by user")
            return
        try:
            os.remove(preset_path)
            info(f"Removed preset settings '{preset_name}'")
            # info_box(f"成功删除预设设置：\"{preset_name}\"", self.preset_dialog)

        except Exception as e:
            error(f"Failed to remove preset settings '{preset_name}': {e}")
            error_box(f"删除预设设置失败：{e}", self.preset_dialog)

        self.update_preset_list()

    def open_preset_dialog(self):
        self.preset_dialog.show()
        self.preset_dialog.activateWindow()

    def update_preset_list(self):
        try:
            preset_names = []
            if os.path.exists(PRESET_SETTINGS_DIR):
                for file in os.listdir(PRESET_SETTINGS_DIR):
                    if file.endswith(".yaml"):
                        preset_names.append(os.path.splitext(file)[0])
            self.update_preset_list_signal.emit(preset_names)
        except Exception as e:
            error(f"Failed to update preset list: {e}")

    # =========================== Overlay Appearance =========================== #

    def update_overlay_size(self, value):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(scale=value / 100.0))
        info(f"Overlay size changed to {value}")

    def update_overlay_opacity(self, value):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(opacity=value / 100.0))
        info(f"Overlay opacity changed to {value}")

    def update_overlay_position_center(self):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(set_x_to_center=True))
        info("Overlay position set to center")

    def update_hide_text(self, state):
        self.update_overlay_ui_state_signal.emit(OverlayUIState(hide_text=state))
        info(f"Overlay hide text set to {state}")

    def reset_overlay_position(self):
        screen_size = QApplication.primaryScreen().geometry().size()
        sw, sh = screen_size.width(), screen_size.height()
        ow, oh = self.overlay.width(), self.overlay.height()
        self.overlay.move(int((sw - ow) / 2), int((sh - oh) / 2))
        info("Overlay position reset to main screen center")

    # =========================== DayX In Rain Detect =========================== #

    def update_dayx_detect_enable(self, state):
        enabled = self.dayx_detect_enable_checkbox.isChecked()
        self.updater.dayx_detect_enabled = enabled
        info(f"DayX detect enabled: {enabled}")

    def update_detect_lang(self):
        config = Config.get()
        lang_name = self.lang_combobox.currentText()
        for k, v in config.dayx_detect_langs.items():
            if v == lang_name:
                self.dayx_detect_lang = k
                break
        self.updater.dayx_detect_lang = self.dayx_detect_lang
        info(f"DayX detect lang changed to {self.dayx_detect_lang}")

    def capture_day1_hpcolor_region(self):
        COLOR_HPCOLOR = "#a84747"
        COLOR_DAY_I = "#686435"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_HPCOLOR, 'text': '点我并框出 血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_DAY_I, 'text': '点我并框出 DAY I 图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Day1 hpcolor region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("detect_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPCOLOR:
                    self.hpcolor_detect_region = list(item['rect'])
                elif item['color'] == COLOR_DAY_I:
                    self.day1_detect_region = list(item['rect'])
            self.update_day1_hpcolor_regions()
            self.save_settings()

    def show_capture_day1_hpcolor_region_tutorial(self):
        return self.show_automation_help('自动计时帮助', """
<h3>默认自动定位与计时</h3>
<ol>
<li>在开局前启动助手，游戏使用窗口化或无边框窗口化。</li>
<li>在“自动运行”保留自动定位和窗口跟随；主设置勾选“缩圈自动计时”，游戏语言与实际一致。</li>
<li>关闭设置并切回游戏。DAY 提示正常出现后尝试自动开始计时；通常不用手动截图或绑定校准快捷键。</li>
</ol>
<h3>自动失败时再备用校准</h3>
<p>托盘 → “自动运行与检测自检” → “检测自检”。DAY 提示平时不出现，等待是正常情况。</p>
<p>仍未定位时，在对应模块点击“备用：2 秒后截屏框选”，2 秒内切回游戏展示 DAY/血条。
按截屏提示框选并保存：血条只框最左侧一小段纯色内部；DAY 提示边界贴合图标。</p>
<p>开局漏检时，在“计时纠正”选择真实当天、当前阶段和该阶段已过秒数。
真实新局才使用“开始新局：清理旧地图和计时，开始第一天”。</p>
<p>雨中血条颜色会尝试自动取样；低血量、HDR、特殊 UI 比例可能仍需校准。
窗口跟随会尝试适配移动和分辨率变化，预览不正确时再调整区域。</p>
""")

    def show_automation_help(self, title, content):
        dialog = QDialog(self)
        dialog.setWindowTitle(f'{APP_FULLNAME} · {title}')
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(content + '<p><a href="https://github.com/Gywikun/nightreign-overlay-helper-plus/blob/auto-enhancements/docs/使用指南.md">打开完整图文使用指南</a></p>')
        layout.addWidget(browser)
        close_button = QPushButton('关闭')
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        dialog.exec()
        return dialog

    def update_day1_hpcolor_regions(self):
        self.updater.day1_detect_region = self.day1_detect_region
        self.updater.hpcolor_detect_region = self.hpcolor_detect_region
        if not getattr(self, "_loading_settings", False):
            self.updater.submit_command("anchor_regions")
        info(f"Updated detect regions: day1={self.day1_detect_region}, hpcolor={self.hpcolor_detect_region}")
        if self.day1_detect_region is None:
            self.day1_detect_region_label.setText("❌未设置缩圈检测区域")
        else:
            self.day1_detect_region_label.setText(f"✔️已设置缩圈检测区域: {self.day1_detect_region}")
        if self.hpcolor_detect_region is None:
            self.hpcolor_detect_region_label.setText("❌未设置雨中冒险检测区域")
        else:
            self.hpcolor_detect_region_label.setText(f"✔️已设置雨中冒险检测区域: {self.hpcolor_detect_region}")
 
    # ===========================  Hp Color Align =========================== #

    def update_in_rain_detect_enable(self, state):
        enabled = self.in_rain_detect_enable_checkbox.isChecked()
        self.updater.in_rain_detect_enabled = enabled
        info(f"In Rain detect enabled: {enabled}")

    def capture_hp_color(self):
        COLOR_NOT_IN_RAIN = "#b83232"
        COLOR_IN_RAIN = "#c03184"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.8, 0.1), 'size': 32, 'color': COLOR_NOT_IN_RAIN, 'text': '点我并框出 正常颜色血条 的区域'},
                {'pos': (0.8, 0.2), 'size': 32, 'color': COLOR_IN_RAIN,     'text': '点我并框出 雨中颜色血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.8, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.8, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("align hp color setting canceled")
            return
        else:
            for item in region_result:
                if item['color'] == COLOR_NOT_IN_RAIN:
                    hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
                    # 根据HDR处理是否开启来决定修改哪个配置项
                    if self.updater.hdr_processing_enabled:
                        self.not_in_rain_hls_hdr = hls
                    else:
                        self.not_in_rain_hls = hls
                elif item['color'] == COLOR_IN_RAIN:
                    hls = RainDetector.get_to_detect_hp_hls(window.screenshot_pixmap, item['rect'])
                    # 根据HDR处理是否开启来决定修改哪个配置项
                    if self.updater.hdr_processing_enabled:
                        self.in_rain_hls_hdr = hls
                    else:
                        self.in_rain_hls = hls
            self.update_hp_color()
            self.save_settings()

    def clear_hp_color(self):
        # 根据HDR模式显示不同的确认信息
        mode_text = "HDR模式" if self.updater.hdr_processing_enabled else "普通模式"
        reply = QMessageBox.question(self, '确认', f'确定要重置{mode_text}下的血条颜色设置为默认吗？', 
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            # 根据HDR模式仅重置对应的配置
            if self.updater.hdr_processing_enabled:
                self.not_in_rain_hls_hdr = None
                self.in_rain_hls_hdr = None
            else:
                self.not_in_rain_hls = None
                self.in_rain_hls = None
            self.update_hp_color()

    def show_capture_hp_color_help(self):
        tutorial_imgs = [QPixmap(str(COLOR_ALIGN_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 4)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("校准血条颜色帮助")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("ℹ️ 如果你设置完检测区域后能正常计时，则不需要进行校准"))
        layout.addWidget(QLabel("雨中冒险自动计时原理为检测血条颜色，有可能因为色差而失效，则需要使用校准步骤："))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"校准血条颜色快捷键\""))
        layout.addWidget(QLabel("2. 开始一局单人游戏，在画面中有血条时按下设置的快捷键\n"
                                "画面定格并显示出按钮"))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("3. 如果画面中有正常血条，则点击\"点我框选 正常颜色血条 的区域\"按钮\n"
                                "然后拖动鼠标框出血条中的纯色部分，点击保存按钮"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("4. 以相同的步骤对在雨里的血条也框选一次（推荐单人去roll在圈外的出生点）"))
        layout.addWidget(QLabel("5. 设置界面看到两个颜色显示已设置即可，重置按钮可以退回到程序内置的默认颜色"))
        layout.addWidget(img_widgets[2])

        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hp_color(self):
        self.updater.not_in_rain_hls = self.not_in_rain_hls
        self.updater.in_rain_hls = self.in_rain_hls
        self.updater.not_in_rain_hls_hdr = self.not_in_rain_hls_hdr
        self.updater.in_rain_hls_hdr = self.in_rain_hls_hdr
        info(f"Updated hp color: not_in_rain_hls={self.not_in_rain_hls}, in_rain_hls={self.in_rain_hls}, not_in_rain_hls_hdr={self.not_in_rain_hls_hdr}, in_rain_hls_hdr={self.in_rain_hls_hdr}")
        
        # 根据HDR模式显示不同的配置状态
        if self.updater.hdr_processing_enabled:
            # HDR模式：显示HDR配置状态
            if self.not_in_rain_hls_hdr is None:
                self.not_in_rain_label.setText(f"HDR:默认")
                self.not_in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.not_in_rain_label.setText(f"HDR:已设置")
                self.not_in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.not_in_rain_hls_hdr)}; color: white")
            if self.in_rain_hls_hdr is None:
                self.in_rain_label.setText(f"HDR:默认")
                self.in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.in_rain_label.setText(f"HDR:已设置")
                self.in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.in_rain_hls_hdr)}; color: white")
        else:
            # 非HDR模式：显示普通配置状态
            if self.not_in_rain_hls is None:
                self.not_in_rain_label.setText(f"默认")
                self.not_in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.not_in_rain_label.setText(f"已设置")
                self.not_in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.not_in_rain_hls)}; color: white")
            if self.in_rain_hls is None:
                self.in_rain_label.setText(f"默认")
                self.in_rain_label.setStyleSheet(f"background-color: #fff; color: black")
            else:
                self.in_rain_label.setText(f"已设置")
                self.in_rain_label.setStyleSheet(f"background-color: rgb{hls_to_rgb(self.in_rain_hls)}; color: white")

    # =========================== Map Detect =========================== #

    def update_map_detect_enable(self, state):
        enabled = self.map_detect_enable_checkbox.isChecked()
        self.updater.map_detect_enabled = enabled
        info(f"Map detect enabled: {enabled}")

    def show_capture_map_region_tutorial(self):
        return self.show_automation_help('地图识别帮助', """
<h3>先自动识别，失败时再校准</h3>
<ol>
<li>主设置开启“启用地图识别”，自动页保留自动定位和地图自动刷新。</li>
<li>关闭设置，切回游戏，打开完整地图并缩放到最小，保持画面稳定。</li>
<li>蓝色表示扫描中；首次没有缓存时，等“扫描完成”或“候选接近，显示共同信息”后再关图。</li>
</ol>
<h3>同一局复用缓存，按需要更新</h3>
<p>再次开图先显示缓存；“重新开图时强制刷新”默认关闭。
持续开图默认每 20 秒请求更新，也可能因画面明显变化、第二天开始或人工请求更新。
关图时间不计入开图刷新周期；后台刷新保留旧标注，通过检查后才替换。</p>
<p>绿色表示本次完成或沿用缓存，黄色可能是候选接近或本次失败保留旧信息，请同时看状态文字和更新时间。
新局、确认地形切换会清理旧信息；退出程序后缓存不保留。</p>
<h3>异常与备用操作</h3>
<p>“立即请求重新识别（备用）”会显示请求反馈。点击后关闭设置、切回完整地图；请求不等于完成，仍需画面稳定并满足扫描间隔。</p>
<p>自动定位长期失败：进入“检测自检”的完整地图模块，点“备用：2 秒后截屏框选”，
2 秒内切回完整地图，框边与地图边框贴合后保存。快捷键默认未绑定，只在需要时自行设置。</p>
<p>首次扫描中关图、缩放或切出游戏可能使本次结果不采用；两次扫描至少间隔 5 秒，超过 15 秒的结果不采用。
有缓存时保留旧信息，关图或切出游戏时标注隐藏，回到完整地图后再显示。</p>
<p>当前不支持局部地图随缩放跟踪。地图数据沿用 v0.10.5，不在线更新；完成状态不保证每个预测准确。</p>
<p>地图信息包含剧透，请与队友确认适合使用。资源来自原项目及 Fuwish 的地图数据，详细来源见 NOTICE 和上游说明。</p>
""")
    def capture_map_region(self):
        COLOR_MAP_REGION = "#4384b9"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_MAP_REGION, 'text': '点我并框出 地图 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Map region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("map_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_MAP_REGION:
                    # 保持正方形
                    x, y, w, h = item['rect']
                    self.map_region = list((x, y, min(w, h), min(w, h)))
                self.update_map_region()
            self.save_settings()

    def update_map_region(self):
        map_region = self.map_region
        if map_region is not None:
            old_map_region = map_region.copy()
            try:
                screen = get_qt_screen_by_mss_region(map_region)
                scale = screen.devicePixelRatio()
                map_region = process_region_to_adapt_scale(map_region, scale)
                info(f"Map region adapted to screen scale {scale}: {old_map_region} -> {map_region}")
            except ValueError:
                # A disconnected monitor must not abort loading every other setting.
                warning("Saved map region is off screen; waiting for automatic relocation.")
                map_region = None
                self.map_region = None
        if self.updater.map_region != map_region:
            self.updater.set_to_detect_map_pattern_once()
        self.updater.map_region = map_region
        if not getattr(self, "_loading_settings", False):
            self.updater.submit_command("anchor_regions")
        info(f"Updated map region: map_region={map_region}")
        if map_region is None:
            self.map_region_label.setText("❌未设置地图区域")
        else:
            self.map_region_label.setText(f"✔️已设置地图区域: {map_region}")

    def update_map_pattern_return_topk(self, text: str):
        self.updater.map_pattern_return_topk = int(text)
        info(f"Map pattern return topk changed to {text}")

    # =========================== Performance =========================== #

    def update_detect_interval(self, text: str):
        config = Config.get()
        detect_interval = config.detect_intervals.get(text, 0.2)
        self.updater.detect_interval = detect_interval
        info(f"Detect interval changed to {detect_interval} seconds ({text})")

    def update_only_show_when_game_foreground(self, state):
        enabled = self.only_show_when_game_foreground_checkbox.isChecked()
        self.update_overlay_ui_state_signal.emit(OverlayUIState(only_show_when_game_foreground=enabled))
        self.update_map_overlay_ui_state_signal.emit(MapOverlayUIState(only_show_when_game_foreground=enabled))
        self.updater.only_detect_when_game_foreground = enabled
        info(f"Overlay only show when game foreground: {enabled}")

    # =========================== HP Detect =========================== #
        
    def update_hp_detect_enable(self, state):
        self.updater.hp_detect_enabled = self.hp_detect_enable_checkbox.isChecked()
        info(f"HP detect enabled: {self.updater.hp_detect_enabled}")

    def update_hp_detect_keep_last_valid(self, state):
        enabled = self.hp_detect_keep_last_valid_checkbox.isChecked()
        self.updater.hp_detect_keep_last_valid = enabled
        info(f"HP detect keep last valid: {enabled}")

    def capture_hpbar_region(self):
        COLOR_HPBAR_REGION = "#eb3b3b"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.1), 'size': 32, 'color': COLOR_HPBAR_REGION, 'text': '点我并框出 血条 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Hpbar region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("hpbar_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_HPBAR_REGION:
                    self.hpbar_region = list(item['rect'])
                self.update_hpbar_region()
            self.save_settings()

    def show_capture_hpbar_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(HP_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 5)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("血条比例标记")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于在血条上显示：40%（血量偏低触发词条）\n"
                                "85%（非满血时触发的负面词条）和100%（满血）三个标记"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取血条区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有血条的游戏画面下按下设置的快捷键，并框选血条的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：\n"
                                "【高度】和血条完全相同\n"
                                "【左侧边】和血条贴合\n"
                                "【长度】无所谓"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\"即可"))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 之后游玩时，在血条的上方就会悬浮显示三个标记\n"))
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_hpbar_region(self):
        self.updater.hpbar_region = self.hpbar_region
        if not getattr(self, "_loading_settings", False):
            self.updater.submit_command("anchor_regions")
        info(f"Updated hpbar region: hpbar_region={self.hpbar_region}")
        if self.hpbar_region is None:
            self.hpbar_region_label.setText("❌未设置血条区域")
        else:
            self.hpbar_region_label.setText(f"✔️已设置血条区域: {self.hpbar_region}")

    # =========================== Art Detect =========================== #

    def update_art_detect_enable(self, state):
        self.updater.art_detect_enabled = self.art_detect_enable_checkbox.isChecked()
        info(f"Art detect enabled: {self.updater.art_detect_enabled}")
    
    def capture_art_region(self):
        COLOR_ART_REGION = "#3235eb"
        SCREENSHOT_WINDOW_CONFIG = {
            'annotation_buttons': [
                {'pos': (0.5, 0.5), 'size': 32, 'color': COLOR_ART_REGION, 'text': '点我并框出 绝招图标 的区域'},
            ],
            'control_buttons': {
                'cancel':   {'pos': (0.3, 0.5), 'size': 50, 'color': "#b3b3b3", 'text': '取消'},
                'save':     {'pos': (0.3, 0.6), 'size': 50, 'color': "#ffffff", 'text': '保存'},
            }
        }
        window = CaptureRegionWindow(SCREENSHOT_WINDOW_CONFIG, self.input)
        region_result = window.capture_and_show()
        if region_result is None:
            warning("Art region setting canceled")
            return
        else:
            if screenshot := window.screenshot_at_saving:
                save_path = get_appdata_path("art_region_screenshot.jpg")
                screenshot.save(save_path)
            for item in region_result:
                if item['color'] == COLOR_ART_REGION:
                    self.art_region = list(item['rect'])
                self.update_art_region()
            self.save_settings()

    def show_capture_art_region_tutorial(self):
        tutorial_imgs = [QPixmap(str(ART_DETECT_TUTORIAL_IMG_PATH).format(i=i)) for i in range(1, 6)]
        img_widgets: list[QLabel] = []
        for img in tutorial_imgs:
            img_widget = QLabel()
            img = img.scaledToHeight(min(100, img.height()), Qt.TransformationMode.SmoothTransformation)
            img_widget.setPixmap(img)
            img_widget.setStyleSheet("border: 1px solid #ccc;")
            img_widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_widgets.append(img_widget)
        msg = QMessageBox(self)
        msg.setMaximumWidth(400)
        msg.setWindowTitle("绝招倒计时")
        layout: QVBoxLayout = QVBoxLayout()
        layout.addWidget(QLabel("该功能用于显示绝招效果的倒计时，支持的角色：女爵、隐士、执行者、复仇者、学者\n"
                                "只能显示自己使用的绝招效果的倒计时"))
        layout.addWidget(QLabel("1. 首先在设置界面调整\"截取绝招图标区域快捷键\""))
        layout.addWidget(img_widgets[0])
        layout.addWidget(QLabel("2. 在任意有绝招图标的游戏画面下按下设置的快捷键，并框选绝招图标的区域"))
        layout.addWidget(img_widgets[1])
        layout.addWidget(QLabel("⚠️ 框选的要求：框和绝招图标的圆的边缘贴合"))
        layout.addWidget(img_widgets[2])
        layout.addWidget(QLabel("3. 回到设置界面看到\"已设置\""))
        layout.addWidget(img_widgets[3])
        layout.addWidget(QLabel("4. 然后设置\"绝招快捷键\"为你的游戏中使用绝招的按键即可"))
        layout.addWidget(img_widgets[4])
        msg.layout().addLayout(layout, 0, 0)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()

    def update_art_region(self):
        self.updater.art_region = self.art_region
        if not getattr(self, "_loading_settings", False):
            self.updater.submit_command("anchor_regions")
        info(f"Updated art region: art_region={self.art_region}")
        if self.art_region is None:
            self.art_region_label.setText("❌未设置绝招图标区域")
        else:
            self.art_region_label.setText(f"✔️已设置绝招图标区域: {self.art_region}")

    # =========================== Other =========================== #
    
    def open_log_directory(self):
        log_dir = get_appdata_path("")
        os.startfile(log_dir)

    def open_about_dialog(self):
        about_path = resource_path("manual.txt")
        with open(about_path, "r", encoding="utf-8") as f:
            about_text = f.read()
        msg = QMessageBox(self)
        msg.setWindowTitle(f"{APP_FULLNAME} · 关于")
        msg.setText(f"{APP_FULLNAME}\n基于 NeuraXmy/nightreign-overlay-helper v0.10.5 的非官方增强版。\n原作者：NeuraXmy；完整原版说明见详情。")
        msg.setDetailedText(about_text)
        msg.setStandardButtons(QMessageBox.StandardButton.Ok)
        msg.exec()
    
    def open_bug_report_window(self):
        w = BugReportWindow(
            log_dir=get_appdata_path(""),
            export_dir=get_desktop_path(),
            mail_address=Config.get().bug_report_email,
            parent=self,
        )
        w.show()

    def update_debug_log(self, state):
        enabled = self.debug_log_checkbox.isChecked()
        set_log_level(INFO if not enabled else DEBUG)
        info(f"Debug log enabled: {enabled}")

    def update_hdr_processing(self, state):
        enabled = self.hdr_processing_checkbox.isChecked()
        self.updater.hdr_processing_enabled = enabled
        info(f"HDR image processing enabled: {enabled}")
        # HDR模式切换时更新血条颜色显示
        self.update_hp_color()

# Based on NeuraXmy/nightreign-overlay-helper v0.10.5.
# Added/modified 2026-10-02 and 2026-10-03; see NOTICE.md and LICENSE (GNU AGPL v3).
from dataclasses import asdict
from src.common import APP_FULLNAME
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import (QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
                            QLabel, QPushButton, QCheckBox, QSpinBox, QSlider,
                            QTabWidget, QScrollArea, QGroupBox, QComboBox, QDoubleSpinBox)


REGION_LABELS = {"day1_detect_region": "DAY 提示", "hpcolor_detect_region": "雨中血条颜色",
                 "map_region": "完整地图", "hpbar_region": "血条比例", "art_region": "绝招图标"}


class EnhancementDialog(QDialog):
    def __init__(self, settings):
        super().__init__(settings)
        self.settings = settings
        self.updater = settings.updater
        self.last_snapshot = {}
        self.loading = True
        self.controls = {}
        self.setWindowTitle(f"{APP_FULLNAME} · 自动运行、检测自检与计时纠正")
        self.resize(840, 650)
        self.setMinimumSize(660, 430)
        root = QVBoxLayout(self)
        intro = QLabel("打开游戏后自动定位；打开完整地图后自动识别和更新。设置会自动保存。")
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.window_label = QLabel("正在等待游戏窗口…")
        self.window_label.setWordWrap(True)
        root.addWidget(self.window_label)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.build_automation_tab()
        self.build_diagnostics_tab()
        self.build_alert_tab()
        self.build_timer_tab()
        footer = QLabel("首次定位需要对应画面出现；无法自动定位时，可在“检测自检”中使用备用框选。")
        footer.setWordWrap(True)
        root.addWidget(footer)
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        root.addWidget(close_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.load_controls()
        self.updater.diagnostics_signal.connect(self.update_diagnostics)

    def page(self, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        page = QWidget()
        layout = QVBoxLayout(page)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return layout

    def checkbox(self, key, text, layout):
        widget = QCheckBox(text)
        self.controls[key] = widget
        widget.toggled.connect(self.save_controls)
        layout.addWidget(widget)
        return widget

    def spinner(self, key, lower, upper):
        widget = QSpinBox()
        widget.setRange(lower, upper)
        widget.setSuffix(" 秒")
        self.controls[key] = widget
        widget.valueChanged.connect(self.save_controls)
        return widget

    def build_automation_tab(self):
        layout = self.page("自动运行")
        self.checkbox("automatic_regions", "自动定位 DAY 提示、血条和完整地图区域", layout)
        self.checkbox("follow_window", "检测区域跟随游戏窗口移动和分辨率变化", layout)
        group = QGroupBox("地图自动更新")
        group_layout = QVBoxLayout(group)
        self.checkbox("automatic_map", "启用地图自动刷新", group_layout)
        self.checkbox("refresh_on_open", "重新开图时强制刷新（通常无需开启）", group_layout)
        self.checkbox("refresh_on_change", "地图画面明显变化时刷新", group_layout)
        self.checkbox("consensus_when_ambiguous", "候选相近时自动显示共同信息，减少手动选择", group_layout)
        form = QFormLayout()
        form.addRow("地图保持打开时的刷新周期", self.spinner("map_refresh_seconds", 5, 300))
        group_layout.addLayout(form)
        note = QLabel("同一局重新开图直接显示缓存；关闭地图的时间不计入定时刷新。\n后台刷新时保留上次标注，新结果通过检查后替换。新局或确认切换地形时清理旧信息。")
        note.setWordWrap(True)
        group_layout.addWidget(note)
        feedback_note = QLabel("蓝色：首次扫描或后台更新；绿色：已识别或复用缓存；黄色：候选接近或仍显示上次信息。\n没有缓存时需等待首次扫描；有缓存时更新失败也会保留旧信息，并显示更新时间。")
        feedback_note.setWordWrap(True)
        group_layout.addWidget(feedback_note)
        layout.addWidget(group)
        self.map_label = QLabel("地图：等待游戏")
        self.map_label.setWordWrap(True)
        layout.addWidget(self.map_label)
        refresh = QPushButton("立即请求重新识别（备用）")
        refresh.clicked.connect(self.request_map_refresh)
        layout.addWidget(refresh)
        self.refresh_request_label = QLabel('')
        self.refresh_request_label.setWordWrap(True)
        layout.addWidget(self.refresh_request_label)
        layout.addStretch()

    def request_map_refresh(self):
        self.refresh_request_label.setText('重新识别请求已提交：请关闭设置并切回完整地图，等待画面稳定和扫描间隔。')
        self.updater.submit_command('refresh_map')

    def build_diagnostics_tab(self):
        layout = self.page("检测自检")
        note = QLabel("状态与预览来自后台真实截图检测。DAY 提示只在当天开始时出现，平时显示等待是正常情况。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status_labels, self.preview_labels = {}, {}
        capture_methods = {"day1_detect_region": self.settings.capture_day1_hpcolor_region,
                           "hpcolor_detect_region": self.settings.capture_day1_hpcolor_region,
                           "map_region": self.settings.capture_map_region,
                           "hpbar_region": self.settings.capture_hpbar_region,
                           "art_region": self.settings.capture_art_region}
        for name, text in REGION_LABELS.items():
            group = QGroupBox(text)
            group_layout = QVBoxLayout(group)
            status = QLabel("等待自动定位")
            status.setWordWrap(True)
            self.status_labels[name] = status
            group_layout.addWidget(status)
            preview = QLabel("暂无当前游戏画面预览")
            preview.setMinimumHeight(22)
            self.preview_labels[name] = preview
            group_layout.addWidget(preview)
            button = QPushButton("备用：2 秒后截屏框选")
            button.clicked.connect(lambda checked, callback=capture_methods[name]: self.start_capture(callback))
            group_layout.addWidget(button)
            layout.addWidget(group)
        layout.addStretch()

    def build_alert_tab(self):
        layout = self.page("关键提醒")
        self.checkbox("notifications", "启用游戏中的关键节点提示", layout)
        self.checkbox("sound", "播放提示音", layout)
        volume = QSlider(Qt.Orientation.Horizontal)
        volume.setRange(0, 100)
        self.controls["volume"] = volume
        volume.valueChanged.connect(self.save_controls)
        row = QHBoxLayout()
        row.addWidget(QLabel("提示音音量"))
        row.addWidget(volume)
        layout.addLayout(row)
        duration = QDoubleSpinBox()
        duration.setDecimals(1)
        duration.setRange(.5, 5.0)
        duration.setSingleStep(.1)
        duration.setSuffix(" 秒")
        self.controls["popup_seconds"] = duration
        duration.valueChanged.connect(self.save_controls)
        duration_form = QFormLayout()
        duration_form.addRow("弹出提示停留时间", duration)
        layout.addLayout(duration_form)
        test = QPushButton("试听提示音")
        test.clicked.connect(lambda: getattr(self.settings, "notification_presenter", None) and self.settings.notification_presenter.play_sound())
        layout.addWidget(test)
        self.checkbox("circle_alerts", "缩圈开始前提醒", layout)
        form = QFormLayout()
        form.addRow("提前提醒", self.spinner("circle_early_seconds", 1, 120))
        form.addRow("临近提醒", self.spinner("circle_late_seconds", 1, 120))
        layout.addLayout(form)
        self.checkbox("rain_alerts", "雨中冒险临近设定时限时提醒", layout)
        form = QFormLayout()
        form.addRow("距离雨中时限", self.spinner("rain_seconds", 1, 120))
        layout.addLayout(form)
        self.checkbox("art_alerts", "绝招效果即将结束时提醒", layout)
        form = QFormLayout()
        form.addRow("剩余效果时间", self.spinner("art_seconds", 1, 120))
        layout.addLayout(form)
        note = QLabel("使用约 0.2 秒的柔和短提示音，默认低音量；文字提示保持原来的 3.5 秒，可调整。\n缓存复用和普通后台刷新不反复弹出或响铃。切出游戏后继续计时，并停止声音和弹窗。")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()

    def build_timer_tab(self):
        layout = self.page("计时纠正")
        note = QLabel("自动识别 DAY 提示后会开始计时。只有漏检或需要修正时，才使用下面的入口。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.timer_label = QLabel("尚未开始")
        layout.addWidget(self.timer_label)
        self.day_box = QComboBox()
        for index in (1, 2, 3):
            self.day_box.addItem(f"第 {index} 天", index)
        self.phase_box = QComboBox()
        for text in ("第一次缩圈前", "第一次缩圈中", "第二次缩圈前", "第二次缩圈中", "夜晚 BOSS 战"):
            self.phase_box.addItem(text)
        self.elapsed_box = QSpinBox()
        self.elapsed_box.setRange(0, 7200)
        self.elapsed_box.setSuffix(" 秒")
        self.day_box.currentIndexChanged.connect(self.update_phase_choices)
        self.phase_box.currentIndexChanged.connect(self.update_elapsed_range)
        form = QFormLayout()
        form.addRow("当天", self.day_box)
        form.addRow("当前阶段", self.phase_box)
        form.addRow("该阶段已过时间", self.elapsed_box)
        layout.addLayout(form)
        read = QPushButton("读取当前计时到输入框")
        read.clicked.connect(self.read_current_timer)
        layout.addWidget(read)
        apply = QPushButton("应用计时修正")
        apply.clicked.connect(lambda: self.updater.submit_command("correct_timer", {"day": self.day_box.currentData(), "phase": self.phase_box.currentIndex(), "elapsed": self.elapsed_box.value()}))
        layout.addWidget(apply)
        new = QPushButton("开始新局：清理旧地图和计时，开始第一天")
        new.clicked.connect(lambda: self.updater.submit_command("new_round"))
        layout.addWidget(new)
        layout.addStretch()
        self.update_elapsed_range()

    def update_phase_choices(self):
        third = self.day_box.currentData() == 3
        self.phase_box.setEnabled(not third)
        if third:
            self.phase_box.setCurrentIndex(4)
        self.update_elapsed_range()

    def update_elapsed_range(self):
        from src.config import Config
        phase = self.phase_box.currentIndex()
        maximum = Config.get().day_period_seconds[phase] - 1 if phase < 4 else 7200
        self.elapsed_box.setMaximum(maximum)

    def read_current_timer(self):
        day, phase, elapsed = self.last_snapshot.get("timer", (None, None, 0))
        if day:
            self.day_box.setCurrentIndex(day - 1)
            self.phase_box.setCurrentIndex(phase or 0)
            self.elapsed_box.setValue(round(elapsed))

    def load_controls(self):
        self.loading = True
        options = asdict(self.updater.automation_options)
        for key, widget in self.controls.items():
            if isinstance(widget, QCheckBox):
                widget.setChecked(options[key])
            else:
                widget.setValue(options[key])
        self.loading = False

    def save_controls(self):
        if self.loading:
            return
        values = {key: widget.isChecked() if isinstance(widget, QCheckBox) else widget.value()
                  for key, widget in self.controls.items()}
        self.updater.submit_command("options", values)

    def start_capture(self, callback):
        self.hide()
        self.settings.hide()
        def capture():
            callback()
            self.updater.submit_command("anchor_regions")
            self.settings.show()
            self.show()
        QTimer.singleShot(2000, capture)

    def update_diagnostics(self, snapshot):
        self.last_snapshot = snapshot
        window = snapshot.get("window")
        self.window_label.setText(f"已找到游戏窗口：{window[2]} × {window[3]} · {'游戏在前台' if snapshot.get('foreground') else '切出游戏，等待返回'}" if window else "等待启动 ELDEN RING NIGHTREIGN")
        self.map_label.setText("地图：" + snapshot.get("map", "等待"))
        self.refresh_request_label.setText(snapshot.get('refresh_request', ''))
        state_keys = {"day1_detect_region": "day", "hpcolor_detect_region": "rain", "map_region": "map", "hpbar_region": "hp", "art_region": "art"}
        for name, label in self.status_labels.items():
            region = snapshot.get("regions", {}).get(name)
            state = snapshot.get(state_keys[name], "等待检测")
            label.setText(("已定位：" + str(region) if region else "尚未定位，等待对应画面或使用备用框选") + "\n" + state)
            data = snapshot.get("previews", {}).get(name)
            if data and self.isVisible():
                width, height, pixels = data
                image = QImage(pixels, width, height, width * 3, QImage.Format.Format_RGB888).copy()
                self.preview_labels[name].setPixmap(QPixmap.fromImage(image))
            elif not data:
                self.preview_labels[name].clear()
                self.preview_labels[name].setText("暂无当前游戏画面预览")
        day, phase, elapsed = snapshot.get("timer", (None, None, 0))
        self.timer_label.setText(f"当前：第 {day} 天 · 阶段 {phase + 1} · 已过 {int(elapsed)} 秒" if day is not None and phase is not None else "当前：尚未开始")

    def showEvent(self, event):
        self.updater.submit_command("diagnostics")
        self.load_controls()
        super().showEvent(event)

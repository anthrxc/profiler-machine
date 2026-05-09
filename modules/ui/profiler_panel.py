# modules/ui/profiler_panel.py
# Docked right panel showing person infocards.

import random
import time
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont

from modules.profiler.infocard import render_card_with_face_data, pil_to_qpixmap

PANEL_W = 650
CARD_W  = 650
CARD_H  = 200


class InfoCard(QLabel):
    def __init__(self):
        super().__init__()
        self.setFixedSize(CARD_W, CARD_H)
        self.setStyleSheet("background-color: transparent;")


class ProfilerPanel(QWidget):
    def __init__(self, feed_manager, db):
        super().__init__()
        self.feed_manager = feed_manager
        self.db = db

        # 'off'    — panel open but showing nothing
        # 'all'    — showing all detected faces
        # 'single' — showing one specific SSN
        self._mode = 'off'
        self._single_ssn = None

        self._crime_chances = {}
        self._last_crime_update = 0
        self._card_widgets = {}

        self.setFixedWidth(PANEL_W)
        self.setStyleSheet("background-color: #0a0a0a; border-left: 1px solid #1a1a1a;")
        self._init_ui()

        self._refresh_timer = QTimer()
        self._refresh_timer.timeout.connect(self._refresh)
        self._refresh_timer.start(500)

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 10, 0, 10)
        layout.setSpacing(6)
        self.setLayout(layout)

        header = QLabel("  PROFILER")
        header.setFont(QFont("Courier New", 10))
        header.setStyleSheet("color: #ffffff;")
        layout.addWidget(header)

        divider = QLabel("  " + "─" * 60)
        divider.setFont(QFont("Courier New", 8))
        divider.setStyleSheet("color: #333333;")
        layout.addWidget(divider)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("""
            QScrollArea { border: none; background-color: #0a0a0a; }
            QScrollBar:vertical { background: #111111; width: 6px; }
            QScrollBar::handle:vertical { background: #333333; border-radius: 3px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
        """)

        self._cards_container = QWidget()
        self._cards_container.setStyleSheet("background-color: #0a0a0a;")
        self._cards_layout = QVBoxLayout()
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(8)
        self._cards_layout.addStretch()
        self._cards_container.setLayout(self._cards_layout)
        self._scroll.setWidget(self._cards_container)
        layout.addWidget(self._scroll)

        self._status = QLabel("  STANDBY")
        self._status.setFont(QFont("Courier New", 8))
        self._status.setStyleSheet("color: #444444;")
        layout.addWidget(self._status)

    # -------------------------------------------------------------------------
    # Mode control
    # -------------------------------------------------------------------------

    def start(self):
        """Show all detected faces."""
        self._mode = 'all'
        self._single_ssn = None

    def stop(self):
        """Clear panel, show nothing."""
        self._mode = 'off'
        self._single_ssn = None
        self._clear_cards()
        self._status.setText("  STANDBY")

    def show_single(self, ssn):
        """Show one specific person regardless of start/stop state."""
        self._single_ssn = ssn
        self._mode = 'single'

    def clear_single(self):
        """Return to whatever mode was active before show_single."""
        self._single_ssn = None
        self._mode = 'all'

    # -------------------------------------------------------------------------
    # Crime chance
    # -------------------------------------------------------------------------

    def _update_crime_chances(self, visible_by_feed):
        now = time.time()
        if now - self._last_crime_update < 2.0:
            return
        self._last_crime_update = now
        new_chances = {}
        for feed_id, ssns in visible_by_feed.items():
            designations = set()
            for ssn in ssns:
                person = self.db.get_by_ssn(ssn)
                if person:
                    designations.add(person[3])
            has_victim = 'victim' in designations
            has_perp = 'perpetrator' in designations
            if has_victim and has_perp:
                new_chances[feed_id] = random.randint(80, 95)
            elif has_victim or has_perp:
                new_chances[feed_id] = random.randint(10, 25)
            else:
                new_chances[feed_id] = None
        self._crime_chances = new_chances

    def _get_crime_chance_for_ssn(self, ssn, visible_by_feed):
        for feed_id, ssns in visible_by_feed.items():
            if ssn in ssns:
                return self._crime_chances.get(feed_id)
        return None

    # -------------------------------------------------------------------------
    # Refresh
    # -------------------------------------------------------------------------

    def _refresh(self):
        if self._mode == 'off':
            return

        designator = self.feed_manager._designator
        with designator._lock:
            # _latest_results is {feed_id: [result dicts]}
            all_results = []
            visible_by_feed = {}
            for fid, feed_results in designator._latest_results.items():
                visible_by_feed[fid] = []
                for r in feed_results:
                    all_results.append(r)
                    if r.get('ssn'):
                        visible_by_feed[fid].append(r['ssn'])

        self._update_crime_chances(visible_by_feed)

        if self._mode == 'single' and self._single_ssn:
            ssns_to_show = [self._single_ssn]
        elif self._mode == 'all':
            ssns_to_show = [r['ssn'] for r in all_results if r.get('ssn')]
        else:
            return

        if not ssns_to_show:
            self._clear_cards()
            self._status.setText("  No faces detected." if self._mode == 'all' else f"  {self._single_ssn} not in frame.")
            return

        self._status.setText(f"  {len(ssns_to_show)} profile(s) active.")
        self._render_cards(ssns_to_show, all_results, visible_by_feed)

    def _clear_cards(self):
        for widget in self._card_widgets.values():
            self._cards_layout.removeWidget(widget)
            widget.deleteLater()
        self._card_widgets.clear()

    def _render_cards(self, ssns_to_show, results, visible_by_feed):
        to_remove = [ssn for ssn in self._card_widgets if ssn not in ssns_to_show]
        for ssn in to_remove:
            widget = self._card_widgets.pop(ssn)
            self._cards_layout.removeWidget(widget)
            widget.deleteLater()

        face_data = {r['ssn']: r for r in results if r.get('ssn')}

        # Snapshot the tracked SSN for this render pass
        tracked_ssn = self.feed_manager._designator.get_tracked_ssn()

        for ssn in ssns_to_show:
            person = self.db.get_by_ssn(ssn)
            if not person:
                continue
            fd = face_data.get(ssn, {})
            face_age = fd.get('face_age')
            face_sex = fd.get('face_sex')
            crime_chance = self._get_crime_chance_for_ssn(ssn, visible_by_feed)
            is_tracked = (ssn == tracked_ssn)

            try:
                card_img = render_card_with_face_data(person, face_age, face_sex, crime_chance, is_tracked=is_tracked)
                pixmap = pil_to_qpixmap(card_img)
            except Exception as e:
                print(f"[ProfilerPanel] Card render error for {ssn}: {e}")
                continue

            if ssn not in self._card_widgets:
                label = InfoCard()
                self._card_widgets[ssn] = label
                self._cards_layout.insertWidget(self._cards_layout.count() - 1, label)

            self._card_widgets[ssn].setPixmap(pixmap)
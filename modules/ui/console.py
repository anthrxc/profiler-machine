# modules/ui/console.py
# Floating command console window with terminal aesthetic.

import os
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from modules.profiler.recognition import DESIGNATIONS, IMAGES_DIR

WINDOW_W, WINDOW_H = 600, 120
TITLE_BAR_H = 28


class Console(QWidget):
    command_submitted = pyqtSignal(str)

    def __init__(self, main_window, feed_manager, db):
        super().__init__()
        self.main_window = main_window
        self.feed_manager = feed_manager
        self.db = db
        self._drag_pos = None
        self._active_user_ssn = None  # SSN of currently authenticated user
        self._awaiting_name_for_ssn = None  # SSN waiting for name input

        self._init_ui()
        self.hide()

    def _init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(WINDOW_W, WINDOW_H)
        self.setStyleSheet("background-color: #000000;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        # Title bar
        title_bar = QWidget()
        title_bar.setFixedHeight(TITLE_BAR_H)
        title_bar.setStyleSheet("background-color: #111111;")
        title_bar.mousePressEvent = self._title_mouse_press
        title_bar.mouseMoveEvent = self._title_mouse_move
        title_bar.mouseReleaseEvent = self._title_mouse_release

        tb_layout = QHBoxLayout()
        tb_layout.setContentsMargins(10, 0, 10, 0)
        title_bar.setLayout(tb_layout)

        title = QLabel("PROFILER MACHINE // CONSOLE")
        title.setFont(QFont("Courier New", 9))
        title.setStyleSheet("color: #aaaaaa;")
        tb_layout.addWidget(title)

        tb_layout.addStretch()

        btn_close = QPushButton("✕")
        btn_close.setFont(QFont("Courier New", 9))
        btn_close.setFixedSize(28, 20)
        btn_close.setStyleSheet("""
            QPushButton { background-color: #1a1a1a; color: #aaaaaa; border: none; }
            QPushButton:hover { background-color: #cc0000; color: #ffffff; }
        """)
        btn_close.clicked.connect(self.hide)
        tb_layout.addWidget(btn_close)

        layout.addWidget(title_bar)

        # Status line
        self._status = QLabel("")
        self._status.setFont(QFont("Courier New", 9))
        self._status.setStyleSheet("color: #aaaaaa; padding: 4px 12px 0px 12px;")
        layout.addWidget(self._status)

        # Input row
        input_row = QWidget()
        input_row.setStyleSheet("background-color: #000000;")
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(12, 6, 12, 12)
        input_layout.setSpacing(6)
        input_row.setLayout(input_layout)

        self._prompt_label = QLabel(">")
        self._prompt_label.setFont(QFont("Courier New", 11))
        self._prompt_label.setStyleSheet("color: #ffffff;")
        input_layout.addWidget(self._prompt_label)

        self._input = QLineEdit()
        self._input.setFont(QFont("Courier New", 11))
        self._input.setStyleSheet("""
            QLineEdit {
                background-color: #000000;
                color: #ffffff;
                border: none;
                selection-background-color: #333333;
            }
        """)
        self._input.returnPressed.connect(self._on_submit)
        input_layout.addWidget(self._input)

        layout.addWidget(input_row)

    # -------------------------------------------------------------------------
    # Dragging
    # -------------------------------------------------------------------------

    def _title_mouse_press(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()

    def _title_mouse_move(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPos() - self._drag_pos)

    def _title_mouse_release(self, event):
        self._drag_pos = None

    # -------------------------------------------------------------------------
    # Visibility
    # -------------------------------------------------------------------------

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self._input.setFocus()

    # -------------------------------------------------------------------------
    # Auth helpers
    # -------------------------------------------------------------------------

    def _is_root(self):
        if self._active_user_ssn is None:
            return False
        person = self.db.get_by_ssn(self._active_user_ssn)
        return person and person[3] == 'root'

    def _is_admin_or_root(self):
        if self._active_user_ssn is None:
            return False
        person = self.db.get_by_ssn(self._active_user_ssn)
        return person and person[3] in ('root', 'admin')

    # -------------------------------------------------------------------------
    # Command handling
    # -------------------------------------------------------------------------

    def _set_status(self, message, ok=True):
        color = "#aaaaaa" if ok else "#ff4444"
        self._status.setStyleSheet(f"color: {color}; padding: 4px 12px 0px 12px;")
        self._status.setText(message)

    def _get_user_designation(self):
        """Return current user's designation, or None if not logged in."""
        if self._active_user_ssn is None:
            return None
        person = self.db.get_by_ssn(self._active_user_ssn)
        return person[3] if person else None

    def _show_help_overview(self):
        """Print overview of available commands filtered by user designation."""
        designation = self._get_user_designation()
        print("\n" + "="*70)
        print("PROFILER MACHINE — COMMAND REFERENCE")
        if designation:
            print(f"Logged in as: {designation.upper()}")
        else:
            print("Not logged in")
        print("="*70)

        # Always available commands
        print("\n[ALWAYS AVAILABLE]")
        print("  quit              Exit the application")
        print("  fullscreen        Toggle fullscreen display")
        print("  help [command]    Show this help, or details on a specific command")

        # Admin/root only commands
        if self._is_admin_or_root():
            print("\n[ADMIN/ROOT ONLY]")
            print("  feed              Manage video feeds (add/remove/focus/grid/list)")
            print("  profiler          Manage person database (login/list/info/enroll/update)")
            print("  reload            Hot-reload modules/assets without restarting")

        # Unauthenticated users can still log in
        if designation is None:
            print("\n[UNAUTHENTICATED]")
            print("  profiler login    Authenticate with your SSN for access")

        print("\nType 'help <command>' for detailed syntax and examples.")
        print("="*70 + "\n")

    def _show_help_for_command(self, cmd):
        """Print detailed help for a specific command."""
        cmd = cmd.lower()
        designation = self._get_user_designation()

        help_texts = {
            "quit": (
                "QUIT — Exit the application\n"
                "  Syntax: quit\n"
                "  Closes Profiler Machine and all active video feeds."
            ),
            "fullscreen": (
                "FULLSCREEN — Toggle fullscreen mode\n"
                "  Syntax: fullscreen\n"
                "  Toggles the main display between windowed and fullscreen."
            ),
            "help": (
                "HELP — Show command reference\n"
                "  Syntax: help [command]\n"
                "  Examples:\n"
                "    help              Show all available commands\n"
                "    help feed         Show detailed help for 'feed' command\n"
                "    help profiler     Show detailed help for 'profiler' command"
            ),
            "reload": (
                "RELOAD — Hot-reload all safe modules and assets (admin/root only)\n"
                "  Syntax: reload\n"
                "  Reloads: overlays (PNGs), infocard, heuristics, antispoof (module + model)\n"
                "  Also scans modules/ for newly-added .py files (reported but not auto-imported)."
            ),
            "feed": (
                "FEED — Manage video input feeds (admin/root only)\n"
                "  Syntax: feed <subcommand> [args]\n"
                "  Subcommands:\n"
                "    feed add <source> [fliph] [flipv]   Add feed (source: device index or URL)\n"
                "    feed remove <feed_id>               Remove a feed by ID\n"
                "    feed focus <feed_id>                Show single feed in fullscreen\n"
                "    feed grid                           Return to grid view of all feeds\n"
                "    feed list                           List all active feeds with flip state\n"
                "    feed flip <feed_id> <h|v|both|none> Set flip for a feed\n"
                "  Flip examples:\n"
                "    feed add 0 fliph        Add webcam mirrored horizontally\n"
                "    feed add 0 fliph flipv  Add webcam mirrored on both axes\n"
                "    feed flip 0 h           Toggle horizontal flip on feed 0\n"
                "    feed flip 0 none        Remove all flips from feed 0"
            ),
            "profiler": (
                "PROFILER — Manage person database (admin/root only)\n"
                "  Syntax: profiler <subcommand> [args]\n"
                "  Subcommands:\n"
                "    profiler login <ssn>              Log in as a person\n"
                "    profiler list                     List all enrolled persons\n"
                "    profiler info <ssn>               Show details for a person\n"
                "    profiler enroll <image_file>      Enroll a new person from image\n"
                "    profiler update <ssn> <field> <value>\n"
                "                                      Update person (field: name/designation/notes)"
            ),
        }

        if cmd in help_texts:
            print(f"\n{help_texts[cmd]}\n")
            self._set_status(f"Help shown for '{cmd}'. See terminal.")
        else:
            self._set_status(f"No help available for '{cmd}'. Try 'help' for overview.", ok=False)

    def _on_submit(self):
        text = self._input.text().strip()
        print(f"[DEBUG] _on_submit called with: {text}")
        self._input.clear()
        if not text:
            return

        # Check if awaiting a name input
        if self._awaiting_name_for_ssn:
            ssn = self._awaiting_name_for_ssn
            self._awaiting_name_for_ssn = None
            self._prompt_label.setText(">")
            if text.lower() == 'skip':
                self._set_status(f"Name skipped for {ssn}.")
            else:
                self.db.update_person(ssn, 'name', text)
                self._set_status(f"Name set to '{text}' for {ssn}.")
            return

        self._handle_command(text)

    def _handle_command(self, cmd):
        print(f"[DEBUG] Command: {cmd}")

        parts = cmd.strip().split()
        primary = parts[0].lower()
        args = parts[1:]

        if primary == "quit":
            self._set_status("SHUTTING DOWN...")
            self.main_window.close()

        elif primary == "help" or primary == "?":
            if args:
                self._show_help_for_command(args[0].lower())
            else:
                self._show_help_overview()

        elif primary == "fullscreen":
            self.main_window.toggle_fullscreen()
            self._set_status("Toggled fullscreen.")

        elif primary == "feed":
            if not self._is_admin_or_root():
                self._set_status("Access denied. Admin or root required for feed commands.", ok=False)
                return
            if not args:
                self._set_status("Usage: feed [add/remove/focus/grid/list]", ok=False)
                return
            self._handle_feed(args)

        elif primary == "profiler":
            if not self._is_admin_or_root():
                self._set_status("Access denied. Admin or root required for profiler commands.", ok=False)
                return
            if not args:
                self._set_status("Usage: profiler [enroll/update/list/info/login]", ok=False)
                return
            self._handle_profiler(args)

        elif primary == "reload":
            if not self._is_root():
                self._set_status("Access denied. Root required for reload.", ok=False)
                return
            self._handle_reload(args)

        else:
            self._set_status(f"Unknown command: '{primary}'", ok=False)

    def _handle_feed(self, args):
        sub = args[0].lower()
        rest = args[1:]

        if sub == "list":
            feeds = self.feed_manager.list_feeds_with_config()
            if feeds:
                print("\n--- ACTIVE FEEDS ---")
                for fid, source, flip_h, flip_v in feeds:
                    flags = []
                    if flip_h:
                        flags.append("fliph")
                    if flip_v:
                        flags.append("flipv")
                    flag_str = f"  [{', '.join(flags)}]" if flags else ""
                    print(f"  Feed {fid}: {source}{flag_str}")
                print()
                self._set_status(f"{len(feeds)} active feed(s). See terminal.")
            else:
                self._set_status("No active feeds.")

        elif sub == "add":
            if not rest:
                self._set_status("Usage: feed add <source> [fliph] [flipv]", ok=False)
                return
            source = rest[0]
            if source.isdigit():
                source = int(source)
            flags = [f.lower() for f in rest[1:]]
            flip_h = 'fliph' in flags
            flip_v = 'flipv' in flags
            try:
                fid = self.feed_manager.add_feed(source, flip_h=flip_h, flip_v=flip_v)
                flag_parts = []
                if flip_h:
                    flag_parts.append("fliph")
                if flip_v:
                    flag_parts.append("flipv")
                flag_info = f" [{', '.join(flag_parts)}]" if flag_parts else ""
                self._set_status(f"Feed {fid} added: {source}{flag_info}")
            except Exception as e:
                self._set_status(f"Failed to add feed: {e}", ok=False)

        elif sub == "remove":
            if not rest or not rest[0].isdigit():
                self._set_status("Usage: feed remove [feed ID]", ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.remove_feed(fid)
            self._set_status(f"Feed {fid} removed.")

        elif sub == "focus":
            if not rest or not rest[0].isdigit():
                self._set_status("Usage: feed focus [feed ID]", ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.focus_feed(fid)
            self._set_status(f"Focused feed {fid}.")

        elif sub == "grid":
            self.feed_manager.focus_feed(None)
            self._set_status("Returned to grid view.")

        elif sub == "flip":
            if len(rest) < 2:
                self._set_status("Usage: feed flip <feed_id> <h|v|both|reset>", ok=False)
                return
            if not rest[0].isdigit():
                self._set_status("Usage: feed flip <feed_id> <h|v|both|reset>", ok=False)
                return
            fid   = int(rest[0])
            mode  = rest[1].lower()
            flip_map = {
                'h':    (True,  None),
                'v':    (None,  True),
                'both': (True,  True),
                'reset': (False, False),
            }
            if mode not in flip_map:
                self._set_status("Flip mode must be: h, v, both, or reset", ok=False)
                return
            fh, fv = flip_map[mode]
            success = self.feed_manager.flip_feed(fid, flip_h=fh, flip_v=fv)
            if success:
                self._set_status(f"Feed {fid} flip set to: {mode}")
            else:
                self._set_status(f"Feed {fid} not found.", ok=False)

        else:
            self._set_status(f"Unknown feed command: '{sub}'", ok=False)

    def _handle_profiler(self, args):
        sub = args[0].lower()
        rest = args[1:]

        if sub == "login":
            # Login by SSN
            if not rest:
                self._set_status("Usage: profiler login [SSN]", ok=False)
                return
            ssn = rest[0]
            person = self.db.get_by_ssn(ssn)
            if not person:
                self._set_status(f"No person found with ID: {ssn}", ok=False)
                return
            self._active_user_ssn = ssn
            name = person[2] or "UNKNOWN"
            designation = person[3].upper()
            self._set_status(f"Logged in as {name} [{designation}] ({ssn})")

        elif sub == "enroll":
            if not rest:
                self._set_status("Usage: profiler enroll <imagename>", ok=False)
                return
            filename = rest[0]
            path = os.path.join(IMAGES_DIR, filename)
            if not os.path.exists(path):
                self._set_status(f"Image not found: {path}", ok=False)
                return
            ssn, success, error = self.db.enroll_from_image(
                self.feed_manager.app, path, designation='irrelevant'
            )
            if success:
                os.remove(path)
                self._set_status(f"Enrolled → {ssn}. Enter name (or 'skip'):")
                self._awaiting_name_for_ssn = ssn
                self._prompt_label.setText("name >")
            else:
                self._set_status(f"Enrollment failed: {error}", ok=False)

        elif sub == "list":
            persons = self.db.get_all()
            if not persons:
                self._set_status("No persons on record.")
                return
            # Show first person in status, print rest to terminal
            print("\n--- PERSONS ON RECORD ---")
            for p in persons:
                _, ssn, name, designation, notes, last_ts, last_feed = p
                print(f"  {ssn}  {(name or 'UNKNOWN'):<20}  {designation.upper():<12}  last seen: {last_ts or 'never'}   {notes or ''}")
            print("-------------------------\n")
            self._set_status(f"{len(persons)} person(s) on record. See terminal for full list.")

        elif sub == "info":
            if not rest:
                self._set_status("Usage: profiler info <SSN>", ok=False)
                return
            ssn = rest[0]
            person = self.db.get_by_ssn(ssn)
            if not person:
                self._set_status(f"No person found: {ssn}", ok=False)
                return
            _, ssn, name, designation, notes, last_ts, last_feed = person
            print(f"\n--- {ssn} ---")
            print(f"  Name:        {name or 'UNKNOWN'}")
            print(f"  Designation: {designation.upper()}")
            print(f"  Notes:       {notes or '—'}")
            print(f"  Last seen:   {last_ts or 'never'} (feed {last_feed})")
            print()
            self._set_status(f"{ssn} — {name or 'UNKNOWN'} [{designation.upper()}]. See terminal.")

        elif sub == "update":
            # profiler update <ssn> <field> <value>
            if len(rest) < 3:
                self._set_status("Usage: profiler update <SSN> <name|designation|notes> <value>", ok=False)
                return
            ssn, field, value = rest[0], rest[1].lower(), ' '.join(rest[2:])

            # Only root can change designation to admin
            if field == 'designation':
                if value == 'admin' and not self._is_root():
                    self._set_status("Only root can assign admin designation.", ok=False)
                    return
                if value not in DESIGNATIONS:
                    self._set_status(f"Invalid designation. Options: {', '.join(DESIGNATIONS)}", ok=False)
                    return

            success = self.db.update_person(ssn, field, value)
            if success:
                self._set_status(f"Updated {field} for {ssn}.")
            else:
                self._set_status(f"Update failed for {ssn}.", ok=False)

        else:
            self._set_status(f"Unknown profiler command: '{sub}'", ok=False)

    def _handle_reload(self, args):
        """Hot-reload overlays, infocard, heuristics, antispoof."""
        all_ok, report = self.feed_manager.reload_all()
        new_mods = self.feed_manager.scan_new_modules()

        print("\n--- HOT RELOAD ---")
        for line in report:
            print(f"  {line}")
        if new_mods:
            print("  New modules detected (not imported):")
            for m in new_mods[:5]:
                print(f"    {m}")
            if len(new_mods) > 5:
                print(f"    ... and {len(new_mods) - 5} more")
        print()

        status = "Reload complete." if all_ok else "Some reloads failed. See terminal."
        self._set_status(status, ok=all_ok)
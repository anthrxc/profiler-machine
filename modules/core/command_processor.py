# modules/core/command_processor.py
# Headless command execution — no Qt dependency.
# Used by the internal web API to run commands and return output as text.

import os
from modules.profiler.recognition import DESIGNATIONS, IMAGES_DIR


class CommandProcessor:
    """Execute PROFM console commands and return output as a dict.

    This mirrors the logic in modules/ui/console.py but has no Qt dependency
    and accumulates output in memory rather than printing to the terminal.

    Usage:
        cp = CommandProcessor(feed_manager, db)
        result = cp.execute('profiler list', active_user_ssn='123-45-6789')
        # result == {'output': '...', 'ok': True}
    """

    def __init__(self, feed_manager, db):
        self.feed_manager = feed_manager
        self.db = db

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def execute(self, command_text, active_user_ssn=None):
        """Execute a command string.  Returns {'output': str, 'ok': bool}."""
        self._lines = []
        self._ok = True
        self._active_user_ssn = active_user_ssn

        parts = command_text.strip().split()
        if not parts:
            return self._result()

        primary = parts[0].lower()
        args    = parts[1:]

        if primary in ('help', '?'):
            self._handle_help(args)

        elif primary == 'feed':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            elif not args:
                self._out('Usage: feed [add|remove|focus|grid|list|flip]', ok=False)
            else:
                self._handle_feed(args)

        elif primary == 'profiler':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            elif not args:
                self._out('Usage: profiler [list|info|enroll|update]', ok=False)
            else:
                self._handle_profiler(args)

        elif primary == 'reload':
            if not self._is_root():
                self._out('Access denied. Root required.', ok=False)
            else:
                self._handle_reload()

        elif primary in ('shutdown', 'fullscreen'):
            self._out(f"'{primary}' is not available from the web interface.", ok=False)

        else:
            self._out(f"Unknown command: '{primary}'", ok=False)

        return self._result()

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _result(self):
        return {'output': '\n'.join(self._lines), 'ok': self._ok}

    def _out(self, text, ok=True):
        self._lines.append(text)
        if not ok:
            self._ok = False

    def _is_root(self):
        if not self._active_user_ssn:
            return False
        p = self.db.get_by_ssn(self._active_user_ssn)
        return bool(p and p[3] == 'root')

    def _is_admin_or_root(self):
        if not self._active_user_ssn:
            return False
        p = self.db.get_by_ssn(self._active_user_ssn)
        return bool(p and p[3] in ('root', 'admin'))

    def _get_designation(self):
        if not self._active_user_ssn:
            return None
        p = self.db.get_by_ssn(self._active_user_ssn)
        return p[3] if p else None

    # -------------------------------------------------------------------------
    # Help
    # -------------------------------------------------------------------------

    def _handle_help(self, args):
        if args:
            self._show_help_topic(args[0].lower())
            return

        desg = self._get_designation()
        self._out('=' * 60)
        self._out('PROFILER MACHINE — COMMAND REFERENCE')
        self._out(f'Logged in as: {desg.upper()}' if desg else 'Not logged in')
        self._out('=' * 60)
        self._out('')
        self._out('[ALWAYS AVAILABLE]')
        self._out('  help [command]    Show this help')

        if self._is_admin_or_root():
            self._out('')
            self._out('[ADMIN/ROOT ONLY]')
            self._out('  feed              Manage video feeds')
            self._out('  profiler          Manage person database')
            if self._is_root():
                self._out('  reload            Hot-reload modules/assets (root only)')

        self._out('')
        self._out("Type 'help <command>' for details.")
        self._out('=' * 60)

    def _show_help_topic(self, cmd):
        topics = {
            'help': (
                'HELP — Show command reference\n'
                '  Syntax: help [command]'
            ),
            'feed': (
                'FEED — Manage video feeds (admin/root only)\n'
                '  feed list\n'
                '  feed add <source> [fliph] [flipv]\n'
                '  feed remove <id>\n'
                '  feed focus <id>\n'
                '  feed grid\n'
                '  feed flip <id> <h|v|both|reset>'
            ),
            'profiler': (
                'PROFILER — Manage persons (admin/root only)\n'
                '  profiler list\n'
                '  profiler info <ssn>\n'
                '  profiler enroll <filename>   (file in database/enroll/)\n'
                '  profiler update <ssn> <name|designation|notes> <value>'
            ),
            'reload': (
                'RELOAD — Hot-reload overlays, heuristics, antispoof (root only)\n'
                '  Syntax: reload'
            ),
        }
        text = topics.get(cmd)
        if text:
            self._out(text)
        else:
            self._out(f"No help available for '{cmd}'.", ok=False)

    # -------------------------------------------------------------------------
    # Feed commands
    # -------------------------------------------------------------------------

    def _handle_feed(self, args):
        sub  = args[0].lower()
        rest = args[1:]

        if sub == 'list':
            feeds = self.feed_manager.list_feeds_with_config()
            if not feeds:
                self._out('No active feeds.')
                return
            self._out('--- ACTIVE FEEDS ---')
            for fid, source, flip_h, flip_v, status in feeds:
                flags = []
                if flip_h: flags.append('fliph')
                if flip_v: flags.append('flipv')
                flag_str = f'  [{", ".join(flags)}]' if flags else ''
                self._out(f'  Feed {fid}: {source}  [{status}]{flag_str}')
            self._out(f'{len(feeds)} active feed(s).')

        elif sub == 'add':
            if not rest:
                self._out('Usage: feed add <source> [fliph] [flipv]', ok=False)
                return
            source = rest[0]
            if source.isdigit():
                source = int(source)
            flags  = [f.lower() for f in rest[1:]]
            flip_h = 'fliph' in flags
            flip_v = 'flipv' in flags
            try:
                fid = self.feed_manager.add_feed(source, flip_h=flip_h, flip_v=flip_v)
                self._out(f'Feed {fid} added: {source}')
            except Exception as e:
                self._out(f'Failed to add feed: {e}', ok=False)

        elif sub == 'remove':
            if not rest or not rest[0].isdigit():
                self._out('Usage: feed remove <id>', ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.remove_feed(fid)
            self._out(f'Feed {fid} removed.')

        elif sub == 'focus':
            if not rest or not rest[0].isdigit():
                self._out('Usage: feed focus <id>', ok=False)
                return
            fid = int(rest[0])
            self.feed_manager.focus_feed(fid)
            self._out(f'Focused feed {fid}.')

        elif sub == 'grid':
            self.feed_manager.focus_feed(None)
            self._out('Returned to grid view.')

        elif sub == 'flip':
            if len(rest) < 2 or not rest[0].isdigit():
                self._out('Usage: feed flip <id> <h|v|both|reset>', ok=False)
                return
            fid  = int(rest[0])
            mode = rest[1].lower()
            flip_map = {
                'h':    (True,  None),
                'v':    (None,  True),
                'both': (True,  True),
                'reset': (False, False),
            }
            if mode not in flip_map:
                self._out('Flip mode must be: h, v, both, or reset', ok=False)
                return
            fh, fv = flip_map[mode]
            ok = self.feed_manager.flip_feed(fid, flip_h=fh, flip_v=fv)
            if ok:
                self._out(f'Feed {fid} flip set to: {mode}')
            else:
                self._out(f'Feed {fid} not found.', ok=False)

        else:
            self._out(f"Unknown feed subcommand: '{sub}'", ok=False)

    # -------------------------------------------------------------------------
    # Profiler commands
    # -------------------------------------------------------------------------

    def _handle_profiler(self, args):
        sub  = args[0].lower()
        rest = args[1:]

        if sub == 'list':
            persons = self.db.get_all()
            if not persons:
                self._out('No persons on record.')
                return
            self._out('--- PERSONS ON RECORD ---')
            for p in persons:
                _, ssn, name, designation, notes, last_ts, last_feed = p
                self._out(
                    f'  {ssn}  {(name or "UNKNOWN"):<20}  '
                    f'{designation.upper():<12}  '
                    f'last seen: {last_ts or "never"}'
                )
            self._out(f'{len(persons)} person(s) on record.')

        elif sub == 'info':
            if not rest:
                self._out('Usage: profiler info <SSN>', ok=False)
                return
            person = self.db.get_by_ssn(rest[0])
            if not person:
                self._out(f'No person found: {rest[0]}', ok=False)
                return
            _, ssn, name, designation, notes, last_ts, last_feed = person
            self._out(f'--- {ssn} ---')
            self._out(f'  Name:        {name or "UNKNOWN"}')
            self._out(f'  Designation: {designation.upper()}')
            self._out(f'  Notes:       {notes or "—"}')
            self._out(f'  Last seen:   {last_ts or "never"} (feed {last_feed})')

        elif sub == 'enroll':
            if not rest:
                self._out('Usage: profiler enroll <filename>', ok=False)
                return
            path = os.path.join(IMAGES_DIR, rest[0])
            if not os.path.exists(path):
                self._out(f'Image not found: {path}', ok=False)
                return
            ssn, success, error = self.db.enroll_from_image(
                self.feed_manager.app, path, designation='irrelevant'
            )
            if success:
                os.remove(path)
                self._out(
                    f'Enrolled → {ssn}. '
                    f'Use: profiler update {ssn} name <name>'
                )
            else:
                self._out(f'Enrollment failed: {error}', ok=False)

        elif sub == 'update':
            if len(rest) < 3:
                self._out(
                    'Usage: profiler update <SSN> '
                    '<name|designation|notes> <value>',
                    ok=False
                )
                return
            ssn   = rest[0]
            field = rest[1].lower()
            value = ' '.join(rest[2:])

            if field == 'designation':
                if value == 'admin' and not self._is_root():
                    self._out('Only root can assign admin designation.', ok=False)
                    return
                if value not in DESIGNATIONS:
                    self._out(
                        f'Invalid designation. '
                        f'Options: {", ".join(DESIGNATIONS)}',
                        ok=False
                    )
                    return

            ok = self.db.update_person(ssn, field, value)
            if ok:
                self._out(f'Updated {field} for {ssn}.')
            else:
                self._out(f'Update failed for {ssn}.', ok=False)

        else:
            self._out(f"Unknown profiler subcommand: '{sub}'", ok=False)

    # -------------------------------------------------------------------------
    # Reload
    # -------------------------------------------------------------------------

    def _handle_reload(self):
        all_ok, report = self.feed_manager.reload_all()
        new_mods = self.feed_manager.scan_new_modules()
        self._out('--- HOT RELOAD ---')
        for line in report:
            self._out(f'  {line}')
        if new_mods:
            self._out('  New modules detected (not auto-imported):')
            for m in new_mods[:5]:
                self._out(f'    {m}')
            if len(new_mods) > 5:
                self._out(f'    ... and {len(new_mods) - 5} more')
        self._out('Reload complete.' if all_ok else 'Some reloads failed.', ok=all_ok)
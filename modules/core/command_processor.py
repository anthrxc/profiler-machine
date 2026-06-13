# modules/core/command_processor.py
# Headless command execution — no Qt dependency.
# Used by the internal web API to run commands and return output as text.
#
# This processor exposes the subset of desktop console commands that are
# meaningful from the mobile web interface. Commands that drive desktop-only
# Qt UI (panels, fullscreen, log viewer) or that would terminate the server
# the client is talking to (restart) are intentionally not available here.

import os
from modules.profiler.recognition import DESIGNATIONS

# Desktop-only primary commands. Recognised so the user gets a clear message
# instead of "Unknown command", but not executable from the web interface.
DESKTOP_ONLY = {'quit', 'fullscreen', 'logs', 'feed', 'reload', 'restart'}

# profiler subcommands that exist on desktop but are not exposed on mobile.
PROFILER_DESKTOP_ONLY = {'login', 'toggle', 'start', 'stop', 'show', 'enroll'}


class CommandProcessor:
    """Execute PROFM console commands and return output as a dict.

    Mirrors the relevant logic in modules/ui/main_window.py but has no Qt
    dependency and accumulates output in memory rather than printing.

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

        elif primary in DESKTOP_ONLY:
            self._out(f"'{primary}' is not available from the web interface.", ok=False)

        elif primary == 'track':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            else:
                self._handle_track(args)

        elif primary == 'untrack':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            else:
                self._handle_untrack()

        elif primary == 'overlay':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            else:
                self._handle_overlay(args)

        elif primary == 'alert':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            elif not args:
                self._out('Usage: alert [add|remove|list|mute|unmute]', ok=False)
            else:
                self._handle_alert(args)

        elif primary == 'profiler':
            if not self._is_admin_or_root():
                self._out('Access denied. Admin or root required.', ok=False)
            elif not args:
                self._out('Usage: profiler [list|info|update|remove|neutralize]', ok=False)
            else:
                self._handle_profiler(args)

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

    @property
    def _designator(self):
        return self.feed_manager._designator

    # -------------------------------------------------------------------------
    # Help  (mobile-specific reference)
    # -------------------------------------------------------------------------

    def _handle_help(self, args):
        if args:
            self._show_help_topic(args[0].lower())
            return

        desg = self._get_designation()
        self._out('=' * 60)
        self._out('PROFILER MACHINE — MOBILE COMMAND REFERENCE')
        self._out(f'Logged in as: {desg.upper()}' if desg else 'Not logged in')
        self._out('=' * 60)
        self._out('')
        self._out('  help [command]            Show this reference')

        if self._is_admin_or_root():
            self._out('')
            self._out('[ADMIN/ROOT]')
            self._out('  track <SSN>               Track subject across all feeds')
            self._out('  untrack                   Clear active tracking target')
            self._out('  overlay <role>            Force debug overlay role')
            self._out('  alert add/remove/list/mute/unmute   Manage alert rules')
            self._out('  profiler list             List all enrolled persons')
            self._out('  profiler info <SSN>       Show details for a person')
            self._out('  profiler update <SSN> <field> <value>   Edit a person')

        if self._is_root():
            self._out('')
            self._out('[ROOT]')
            self._out('  profiler remove <SSN>     Delete a person')
            self._out('  profiler neutralize <SSN> [note]   Reset to IRRELEVANT')
            self._out('  profiler update <SSN> designation <value>')

        self._out('')
        self._out("Type 'help <command>' for details.")
        self._out('=' * 60)

    def _show_help_topic(self, cmd):
        topics = {
            'help': (
                'HELP — Show command reference\n'
                '  help [command]'
            ),
            'track': (
                'TRACK — Track a subject across all feeds\n'
                '  track <SSN>'
            ),
            'untrack': (
                'UNTRACK — Clear the active tracking target\n'
                '  untrack'
            ),
            'overlay': (
                'OVERLAY — Force a debug overlay role\n'
                '  overlay <role>\n'
                f'  Roles: {", ".join(DESIGNATIONS)}'
            ),
            'alert': (
                'ALERT — Manage alert rules\n'
                '  alert add designation <role>\n'
                '  alert add co-presence <role_a> <role_b>\n'
                '  alert add ssn <SSN>\n'
                '  alert remove <rule_id>\n'
                '  alert list\n'
                '  alert mute [rule_id]\n'
                '  alert unmute [rule_id]'
            ),
            'profiler': (
                'PROFILER — Manage persons\n'
                '  profiler list\n'
                '  profiler info <SSN>\n'
                '  profiler update <SSN> <name|designation|notes> <value>\n'
                '  profiler remove <SSN>            (root)\n'
                '  profiler neutralize <SSN> [note] (root)'
            ),
        }
        text = topics.get(cmd)
        if text:
            self._out(text)
        else:
            self._out(f"No help available for '{cmd}'.", ok=False)

    # -------------------------------------------------------------------------
    # Track / untrack
    # -------------------------------------------------------------------------

    def _handle_track(self, args):
        if not args:
            self._out('Usage: track <SSN>', ok=False)
            return
        ssn = args[0]
        person = self.db.get_by_ssn(ssn)
        if not person:
            self._out(f'No person found: {ssn}', ok=False)
            return
        self._designator.set_tracked_ssn(ssn)
        name = person[2] or ssn
        self._out(f'Now tracking {name} [{ssn}] across all feeds.')

    def _handle_untrack(self):
        current = self._designator.get_tracked_ssn()
        self._designator.clear_tracked_ssn()
        if current:
            self._out(f'Tracking cleared for {current}.')
        else:
            self._out('No active tracking target.')

    # -------------------------------------------------------------------------
    # Overlay
    # -------------------------------------------------------------------------

    def _handle_overlay(self, args):
        if not args:
            self._out(f'Roles: {", ".join(DESIGNATIONS)}', ok=False)
            return
        role = args[0].lower()
        success = self._designator.set_debug_role(role)
        if success:
            self._out(f'Debug overlay: {role}')
        else:
            self._out(f"Unknown role: '{role}'", ok=False)

    # -------------------------------------------------------------------------
    # Alert
    # -------------------------------------------------------------------------

    def _handle_alert(self, args):
        from modules.profiler.alerts import parse_condition

        engine = self.feed_manager._alert_engine
        sub    = args[0].lower()
        rest   = args[1:]

        if sub == 'add':
            if not rest:
                self._out(
                    'Usage: alert add <designation <role>> | '
                    '<co-presence <role_a> <role_b>> | <ssn <SSN>>',
                    ok=False
                )
                return
            try:
                cond = parse_condition(rest)
                rule = engine.add_rule(cond, created_by=self._active_user_ssn)
                self._out(f'Alert rule {rule.rule_id} added: {rule.condition.describe()}')
            except ValueError as e:
                self._out(str(e), ok=False)

        elif sub == 'remove':
            if not rest or not rest[0].isdigit():
                self._out('Usage: alert remove <rule ID>', ok=False)
                return
            rid = int(rest[0])
            if engine.remove_rule(rid):
                self._out(f'Alert rule {rid} removed.')
            else:
                self._out(f'No alert rule with ID {rid}.', ok=False)

        elif sub == 'list':
            rules = engine.list_rules()
            if not rules:
                self._out('No alert rules defined.')
                return
            self._out(f'{len(rules)} rule(s):')
            for r in rules:
                mute_tag = '  [MUTED]' if r.muted else ''
                self._out(f'  [{r.rule_id}]  {r.condition.describe()}{mute_tag}')

        elif sub == 'mute':
            if not rest:
                engine.mute_all()
                self._out('All alerts muted.')
                return
            if not rest[0].isdigit():
                self._out('Usage: alert mute [rule ID]', ok=False)
                return
            rid = int(rest[0])
            if engine.mute_rule(rid):
                self._out(f'Alert rule {rid} muted.')
            else:
                self._out(f'No alert rule with ID {rid}.', ok=False)

        elif sub == 'unmute':
            if not rest:
                engine.unmute_all()
                self._out('All alerts unmuted.')
                return
            if not rest[0].isdigit():
                self._out('Usage: alert unmute [rule ID]', ok=False)
                return
            rid = int(rest[0])
            if engine.unmute_rule(rid):
                self._out(f'Alert rule {rid} unmuted.')
            else:
                self._out(f'No alert rule with ID {rid}.', ok=False)

        else:
            self._out(f"Unknown alert subcommand: '{sub}'", ok=False)

    # -------------------------------------------------------------------------
    # Profiler
    # -------------------------------------------------------------------------

    def _handle_profiler(self, args):
        sub  = args[0].lower()
        rest = args[1:]

        if sub in PROFILER_DESKTOP_ONLY:
            self._out(f"'profiler {sub}' is not available from the web interface.", ok=False)
            return

        if sub == 'list':
            persons = self.db.get_all()
            if not persons:
                self._out('No persons on record.')
                return
            self._out(f'{len(persons)} person(s) on record:')
            for p in persons:
                _, ssn, name, designation, notes, last_ts, last_feed = p
                self._out(
                    f'  {ssn}  {(name or "UNKNOWN"):<20}  '
                    f'{designation.upper():<12}  '
                    f'last seen: {last_ts or "never"}'
                )

        elif sub == 'info':
            if not rest:
                self._out('Usage: profiler info <SSN>', ok=False)
                return
            person = self.db.get_by_ssn(rest[0])
            if not person:
                self._out(f'No person found: {rest[0]}', ok=False)
                return
            _, ssn, name, designation, notes, last_ts, last_feed = person
            self._out(f'ID:          {ssn}')
            self._out(f'Name:        {name or "UNKNOWN"}')
            self._out(f'Designation: {designation.upper()}')
            self._out(f'Notes:       {notes or "—"}')
            self._out(f'Last seen:   {last_ts or "never"} (feed {last_feed})')

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
                if not self._is_root():
                    self._out('Only root can change designations.', ok=False)
                    return
                if value not in DESIGNATIONS:
                    self._out(
                        f'Invalid designation. Options: {", ".join(DESIGNATIONS)}',
                        ok=False
                    )
                    return

            if self.db.update_person(ssn, field, value):
                self._out(f'Updated {field} for {ssn}.')
            else:
                self._out(f'Update failed for {ssn}.', ok=False)

        elif sub == 'remove':
            if not self._is_root():
                self._out('Access denied — root authentication required.', ok=False)
                return
            if not rest:
                self._out('Usage: profiler remove <SSN>', ok=False)
                return
            ssn = rest[0]
            if ssn == '000-00-0000':
                self._out('Cannot remove root user.', ok=False)
                return
            if self.db.remove_person(ssn):
                self._out(f'Removed {ssn}.')
            else:
                self._out(f'No person found: {ssn}', ok=False)

        elif sub == 'neutralize':
            if not self._is_root():
                self._out('Access denied — root authentication required.', ok=False)
                return
            if not rest:
                self._out('Usage: profiler neutralize <SSN> [note]', ok=False)
                return
            ssn  = rest[0]
            note = ' '.join(rest[1:]) or None
            person = self.db.get_by_ssn(ssn)
            if not person:
                self._out(f'No person found: {ssn}', ok=False)
                return
            prev_desig = person[3]
            if prev_desig not in ('threat', 'victim', 'perpetrator'):
                self._out(
                    f'{ssn} is already {prev_desig.upper()} — no neutralization needed.',
                    ok=False
                )
                return
            self.db.neutralize_subject(ssn, prev_desig,
                                       operator_ssn=self._active_user_ssn, note=note)
            self._designator.reset_neutralization_monitor(ssn)
            name = person[2] or ssn
            self._out(f'Neutralized {name} ({ssn}) — {prev_desig.upper()} → IRRELEVANT.')

        else:
            self._out(f"Unknown profiler subcommand: '{sub}'", ok=False)
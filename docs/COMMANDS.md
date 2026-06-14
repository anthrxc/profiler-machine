# PROFM Command Reference

Commands are entered via the desktop console or the web interface CONSOLE tab.
Some commands are desktop-only. Access level is shown per command.

**Designations:** `irrelevant` · `admin` · `root` · `threat` · `victim` · `perpetrator`

---

## Authentication

Authentication is required before any command other than `help`, `quit`, `fullscreen`, and `logs`.

```
profiler login <SSN>
```

Authenticates the operator. The SSN must belong to a `root` or `admin` person who is currently visible in an active feed. Runs an anti-spoofing liveness check before granting access.

```
profiler login <SSN>    # switch to a different authenticated user
```

---

## Global Commands

Available to all users regardless of authentication state.

| Command | Description |
|---|---|
| `help` | Show role-aware command reference |
| `help <command>` | Show usage for a specific command |
| `quit` | Shut down Profiler Machine *(desktop only)* |
| `fullscreen` | Toggle fullscreen display *(desktop only)* |
| `logs` | Toggle the log viewer window *(desktop only)* |

---

## Tracking

*Requires: admin or root*

```
track <SSN>
```
Locks tracking onto the specified subject across all active feeds.

```
untrack
```
Clears the active tracking target.

---

## Feed Management

*Requires: admin or root · Desktop only*

```
feed list
```
Lists all active feeds with their source, flip flags, and status.

```
feed add <source> [fliph] [flipv]
```
Adds a new feed. `source` can be a device index (e.g. `0`) or a URL (RTSP, MJPEG). Optional flags `fliph` and `flipv` mirror the image horizontally or vertically. If the added feed requires authentication to access it (or the program fails to fetch a vaild frame on first attempt), you will be prompted for authentication. If you are sure that no authentication is required, you can either click `CANCEL`or `SKIP` (program will retry either way).

```
feed remove <feed_id>
```
Removes a feed by ID.

```
feed focus <feed_id>
```
Expands a single feed to fill the display.

```
feed grid
```
Returns to the multi-feed grid view.

```
feed flip <feed_id> <h|v|both|none>
```
Changes the flip orientation of an existing feed.

---

## Alert Rules

*Requires: admin or root*

```
alert list
```
Lists all defined alert rules with their IDs and mute state.

```
alert add designation <role>
```
Triggers an alert whenever a person with the specified designation is detected.

```
alert add co-presence <role_a> <role_b>
```
Triggers an alert when persons of both specified designations are detected simultaneously.

```
alert add ssn <SSN>
```
Triggers an alert when the specified person is detected.

```
alert remove <rule_id>
```
Deletes an alert rule by ID.

```
alert mute [rule_id]
```
Mutes a specific alert rule. Omit `rule_id` to mute all rules.

```
alert unmute [rule_id]
```
Unmutes a specific alert rule. Omit `rule_id` to unmute all rules.

---

## Profiler

### Panel Control *(desktop only)*

*Requires: admin or root*

```
profiler toggle
```
Opens or closes the profiler panel.

```
profiler start
```
Starts the profiler panel and displays all currently detected faces.

```
profiler stop
```
Stops the profiler panel.

```
profiler show <SSN>
```
Opens the profiler panel focused on a specific person.

### Enrollment *(desktop only)*

*Requires: admin or root*

```
profiler enroll <filename>
```
Enrolls a person from an image file placed in `database/enroll/`. After enrollment, prompts for a name (type `skip` to leave unnamed). Deletes the source image on success. If an image file has been placed prior to launching the program, the person on the image will be automatically enrolled (this will be shown in the console where you launched the app from)

### Database

*Requires: admin or root*

```
profiler list
```
Lists all enrolled persons with SSN, name, designation, and last-seen timestamp.

```
profiler info <SSN>
```
Shows full details for a person: SSN, name, designation, notes, and last-seen feed.

```
profiler update <SSN> name <value>
```
Updates the person's display name.

```
profiler update <SSN> notes <value>
```
Updates the person's notes field.

```
profiler update <SSN> designation <value>
```
Changes the person's designation.
Valid values: `irrelevant`, `victim`, `perpetrator`, `threat`, **root only:** `admin`, `root`

*Requires: admin or root*

```
profiler remove <SSN>
```
Permanently deletes a person and all associated data. Cannot remove SSN `000-00-0000` (root).

```
profiler neutralize <SSN> [note]
```
Resets a `threat`, `perpetrator`, or `victim` to `irrelevant` and logs the action to the neutralization log. Optional `note` is recorded with the entry.

---

## Restart

*Requires: root · Desktop only*

```
restart
```
Saves the current session (active user, tracked target, focused feed, active sources) to `config/session.json` and restarts the process. On restore, the session is resumed and the warmup screen displays "SYSTEM RESTORE".

---

## Web Interface Availability

Commands marked *desktop only* are not available from the web CONSOLE tab. Attempting them returns a clear error message rather than silently failing.

| Available on web | Desktop only |
|---|---|
| `help` | `quit` |
| `track` / `untrack` | `fullscreen` |
| `overlay` | `logs` |
| `alert` (all subcommands) | `restart` |
| `profiler list / info / update / remove / neutralize` | `feed` (all subcommands) |
| | `profiler login / toggle / start / stop / show / enroll` |
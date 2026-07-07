from datetime import datetime, date, timedelta
import rumps
import os
import os.path
import webbrowser
import pytz
import os
import json
import requests
import calendar
import re
import warnings
from countdown_window import CountdownWindow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from appdirs import user_data_dir
from bs4 import BeautifulSoup
import logging
import urllib.request
import AppKit
import threading
import plistlib
import socket
import pathlib as _pathlib

# Prevent the whole app from freezing after macOS sleep/wake: stale half-open
# sockets make blocking network calls (Google API .execute(), urlopen) hang
# forever on the main thread. A default timeout makes them fail fast instead.
socket.setdefaulttimeout(15)


def _get_bundle_version() -> str:
    try:
        exe = _pathlib.Path(__import__("sys").executable).resolve()
        for parent in exe.parents:
            plist = parent / "Info.plist"
            if plist.exists():
                with open(plist, "rb") as f:
                    data = plistlib.load(f)
                return data.get("CFBundleShortVersionString", "dev")
    except Exception:
        pass
    return "dev"


__version__ = _get_bundle_version()


# Suppress PyObjC pointer warnings
warnings.filterwarnings(
    "ignore", category=RuntimeWarning, message="PyObjCPointer created:.*"
)


logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def str_truncate(string, width):
    if len(string) > width:
        string = string[: width - 3] + "..."
    return string


def _parse_hex_color(hex_color):
    """Return (r, g, b) floats 0-1 from a hex string, or None on failure."""
    if not hex_color or not hex_color.startswith("#") or len(hex_color) < 7:
        return None
    try:
        return (
            int(hex_color[1:3], 16) / 255,
            int(hex_color[3:5], 16) / 255,
            int(hex_color[5:7], 16) / 255,
        )
    except ValueError:
        return None


def _make_color_dot_image(hex_color, size=13):
    """Create a circular NSImage filled with the exact hex color."""
    rgb = _parse_hex_color(hex_color)
    if rgb is None:
        return None
    r, g, b = rgb
    color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
    image = AppKit.NSImage.alloc().initWithSize_((size, size))
    image.lockFocus()
    color.set()
    path = AppKit.NSBezierPath.alloc().init()
    path.appendBezierPathWithOvalInRect_(((0, 0), (size, size)))
    path.fill()
    image.unlockFocus()
    return image


def _make_color_swatch_view(hex_color, size=12):
    """Create a small circular NSView with the exact hex color (for settings UI)."""
    rgb = _parse_hex_color(hex_color)
    if rgb is None:
        return None
    r, g, b = rgb
    view = AppKit.NSView.alloc().initWithFrame_(((0, 0), (size, size)))
    view.setWantsLayer_(True)
    view.layer().setBackgroundColor_(
        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0).CGColor()
    )
    view.layer().setCornerRadius_(size / 2)
    return view


class _SettingsActionHandler(AppKit.NSObject):
    """Thin NSObject that forwards button actions to SettingsWindowController."""

    def init(self):
        self = super().init()
        if self is None:
            return None
        self.controller = None
        return self

    def addNotificationRow_(self, sender):
        self.controller.add_notification_row(5, False)

    def removeNotificationRow_(self, sender):
        self.controller.remove_notification_row(sender.tag())

    def browseApp_(self, sender):
        self.controller.browse_app()

    def save_(self, sender):
        self.controller.save()

    def cancel_(self, sender):
        self.controller.cancel()


class SettingsWindowController:
    """Native macOS settings window with form controls."""

    def __init__(self, settings, on_save, available_calendars=None):
        self._on_save = on_save
        self._settings = dict(settings)
        self._notification_rows = []
        self._calendar_checkboxes = []  # list of (cal_id, NSButton)
        self._available_calendars = available_calendars  # list of {id, name} or None
        self._handler = _SettingsActionHandler.alloc().init()
        self._handler.controller = self
        self._build_window()

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _label(self, text, frame, *, bold=False, small=False, secondary=False):
        v = AppKit.NSTextField.alloc().initWithFrame_(frame)
        v.setStringValue_(text)
        v.setBezeled_(False)
        v.setDrawsBackground_(False)
        v.setEditable_(False)
        v.setSelectable_(False)
        size = 11 if small else 13
        v.setFont_(AppKit.NSFont.boldSystemFontOfSize_(size) if bold else AppKit.NSFont.systemFontOfSize_(size))
        if secondary:
            v.setTextColor_(AppKit.NSColor.secondaryLabelColor())
        return v

    def _field(self, text, frame):
        v = AppKit.NSTextField.alloc().initWithFrame_(frame)
        v.setStringValue_(text)
        v.setEditable_(True)
        v.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        return v

    def _checkbox(self, title, checked, frame):
        v = AppKit.NSButton.alloc().initWithFrame_(frame)
        v.setButtonType_(AppKit.NSSwitchButton)
        v.setTitle_(title)
        v.setState_(AppKit.NSControlStateValueOn if checked else AppKit.NSControlStateValueOff)
        v.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        return v

    def _separator(self, y):
        box = AppKit.NSBox.alloc().initWithFrame_(((0, y), (self._W, 1)))
        box.setBoxType_(AppKit.NSBoxSeparator)
        return box

    def _section_header(self, text, y):
        m = self._margin
        v = self._label(text.upper(), ((m, y), (self._W - 2 * m, 15)), bold=True, small=True, secondary=True)
        self._cv.addSubview_(v)

    # ------------------------------------------------------------------
    # Window construction
    # ------------------------------------------------------------------

    def _build_window(self):
        W = 460
        margin = 20
        field_h = 22
        cb_h = 22
        row_gap = 6       # gap between items in a section
        sec_gap = 10      # space above section header (after separator)
        sep_gap = 12      # space above separator

        notif_count = len(self._settings.get("notifications", []))
        # Fixed height contribution from each section
        fixed_h = (
            14                          # top padding
            + 15 + 6                    # GENERAL header
            + cb_h + row_gap            # Launch at login
            + cb_h + row_gap            # Show countdown
            + sep_gap + 1 + sec_gap     # separator
            + 15 + 6                    # CALENDAR header
            + 120 + row_gap             # scroll view (fixed height) or fallback field
            + sep_gap + 1 + sec_gap     # separator
            + 15 + 6                    # MEETINGS header
            + cb_h + row_gap            # Open links
            + field_h + row_gap         # Meeting app row
            + sep_gap + 1 + sec_gap     # separator
            + 15 + 6                    # NOTIFICATIONS header
            + notif_count * 28          # rows
            + 30                        # add button
            + 1 + 14                    # bottom separator + padding
            + 36                        # button bar
        )
        H = max(fixed_h, 420)

        self._window = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((200, 200), (W, H)),
            AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self._window.setTitle_("Vince Settings")
        self._window.center()
        cv = self._window.contentView()
        self._cv = cv
        self._W = W
        self._margin = margin

        y = H - 14  # top padding

        # ── GENERAL ──────────────────────────────────────────────────
        y -= 15
        self._section_header("General", y)
        y -= 6

        y -= cb_h
        self._login_cb = self._checkbox(
            "Launch at login",
            self._settings.get("launch_at_login", True),
            ((margin, y), (W - 2 * margin, cb_h)),
        )
        cv.addSubview_(self._login_cb)
        y -= row_gap

        y -= cb_h
        self._bar_cb = self._checkbox(
            "Show countdown in menu bar",
            self._settings.get("show_menu_bar", True),
            ((margin, y), (W - 2 * margin, cb_h)),
        )
        cv.addSubview_(self._bar_cb)
        y -= sep_gap

        cv.addSubview_(self._separator(y))
        y -= 1 + sec_gap

        # ── CALENDAR ─────────────────────────────────────────────────
        y -= 15
        self._section_header("Calendar", y)
        y -= 6

        selected_ids = set(self._settings.get("calendars", ["primary"]))
        self._calendar_checkboxes = []
        scroll_h = 120
        if self._available_calendars:
            # Scrollable list of checkboxes
            scroll_w = W - 2 * margin
            inner_w = scroll_w - 16  # leave room for scrollbar
            doc_h = max(len(self._available_calendars) * (cb_h + row_gap), scroll_h)
            doc_view = AppKit.NSView.alloc().initWithFrame_(((0, 0), (inner_w, doc_h)))
            dot_size = 12
            dot_gap = 6
            cb_x = 4 + dot_size + dot_gap
            cy = doc_h  # build top-to-bottom in flipped coords (y=0 is bottom in AppKit)
            for cal in self._available_calendars:
                cy -= cb_h
                is_checked = cal["id"] in selected_ids
                # Colored dot
                swatch = _make_color_swatch_view(cal.get("color", ""), dot_size)
                if swatch:
                    dot_y = cy + (cb_h - dot_size) // 2
                    swatch.setFrame_(((4, dot_y), (dot_size, dot_size)))
                    doc_view.addSubview_(swatch)
                # Checkbox with plain name (dot provides the color)
                label = cal.get("name", cal["id"])
                cb = self._checkbox(label, is_checked, ((cb_x, cy), (inner_w - cb_x, cb_h)))
                doc_view.addSubview_(cb)
                self._calendar_checkboxes.append((cal["id"], cb))
                cy -= row_gap
            y -= scroll_h
            scroll = AppKit.NSScrollView.alloc().initWithFrame_(((margin, y), (scroll_w, scroll_h)))
            scroll.setHasVerticalScroller_(True)
            scroll.setHasHorizontalScroller_(False)
            scroll.setBorderType_(AppKit.NSBezelBorder)
            scroll.setAutohidesScrollers_(True)
            scroll.setDocumentView_(doc_view)
            # Scroll to top so first calendar is visible
            doc_view.scrollPoint_(AppKit.NSMakePoint(0, doc_h))
            cv.addSubview_(scroll)
            y -= row_gap
        else:
            # Fallback: text field when calendars could not be fetched
            y -= field_h
            cal_str = ", ".join(self._settings.get("calendars", ["primary"]))
            self._cal_field = self._field(cal_str, ((margin, y), (W - 2 * margin, field_h)))
            cv.addSubview_(self._cal_field)
            y -= row_gap
        y -= sep_gap

        cv.addSubview_(self._separator(y))
        y -= 1 + sec_gap

        # ── MEETINGS ─────────────────────────────────────────────────
        y -= 15
        self._section_header("Meetings", y)
        y -= 6

        y -= cb_h
        self._link_cb = self._checkbox(
            "Open meeting links automatically",
            self._settings.get("link_opening_enabled", True),
            ((margin, y), (W - 2 * margin, cb_h)),
        )
        cv.addSubview_(self._link_cb)
        y -= row_gap

        # Meeting app row: label + field + Browse button
        y -= field_h
        lbl_w = 100
        browse_w = 76
        field_w = W - 2 * margin - lbl_w - 8 - browse_w - 6
        cv.addSubview_(self._label("Meeting app:", ((margin, y + 3), (lbl_w, 16))))
        self._app_field = self._field(
            self._settings.get("app_meet", ""),
            ((margin + lbl_w + 8, y), (field_w, field_h)),
        )
        cv.addSubview_(self._app_field)
        browse_btn = AppKit.NSButton.alloc().initWithFrame_(
            ((margin + lbl_w + 8 + field_w + 6, y), (browse_w, field_h))
        )
        browse_btn.setTitle_("Browse…")
        browse_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        browse_btn.setTarget_(self._handler)
        browse_btn.setAction_("browseApp:")
        cv.addSubview_(browse_btn)
        y -= row_gap + sep_gap

        cv.addSubview_(self._separator(y))
        y -= 1 + sec_gap

        # ── NOTIFICATIONS ─────────────────────────────────────────────
        y -= 15
        self._section_header("Notifications", y)
        y -= 6

        self._notif_y_base = y
        for notif in self._settings.get("notifications", []):
            self._add_row_views(notif["time_left"], notif["sound"])

        self._add_btn = AppKit.NSButton.alloc().initWithFrame_(((margin, 0), (150, 22)))
        self._add_btn.setTitle_("+ Add Notification")
        self._add_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self._add_btn.setTarget_(self._handler)
        self._add_btn.setAction_("addNotificationRow:")
        cv.addSubview_(self._add_btn)

        self._relayout()

        # ── Bottom bar ────────────────────────────────────────────────
        cv.addSubview_(self._separator(36))

        cancel_btn = AppKit.NSButton.alloc().initWithFrame_(((W - 210, 8), (96, 28)))
        cancel_btn.setTitle_("Cancel")
        cancel_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        cancel_btn.setTarget_(self._handler)
        cancel_btn.setAction_("cancel:")
        cv.addSubview_(cancel_btn)

        save_btn = AppKit.NSButton.alloc().initWithFrame_(((W - 108, 8), (96, 28)))
        save_btn.setTitle_("Save")
        save_btn.setBezelStyle_(AppKit.NSBezelStyleRounded)
        save_btn.setKeyEquivalent_("\r")
        save_btn.setTarget_(self._handler)
        save_btn.setAction_("save:")
        cv.addSubview_(save_btn)

    # ------------------------------------------------------------------
    # Notification rows
    # ------------------------------------------------------------------

    def _add_row_views(self, time_left, sound):
        margin = self._margin
        idx = len(self._notification_rows)
        mins_lbl = self._label("mins before, play sound:", ((margin + 58, 0), (160, 22)), secondary=True)
        row = {
            "time_field": self._field(str(time_left), ((margin, 0), (46, 22))),
            "mins_lbl": mins_lbl,
            "sound_cb": self._checkbox("", sound, ((margin + 224, 0), (24, 22))),
            "remove_btn": AppKit.NSButton.alloc().initWithFrame_(((margin + 254, 0), (22, 22))),
        }
        row["remove_btn"].setTitle_("×")
        row["remove_btn"].setBezelStyle_(AppKit.NSBezelStyleCircular)
        row["remove_btn"].setTarget_(self._handler)
        row["remove_btn"].setAction_("removeNotificationRow:")
        row["remove_btn"].setTag_(idx)
        for v in row.values():
            self._cv.addSubview_(v)
        self._notification_rows.append(row)

    def _relayout(self):
        y = self._notif_y_base - 2
        for row in self._notification_rows:
            y -= 28
            for v in row.values():
                f = v.frame()
                v.setFrame_(((f[0][0], y), f[1]))
        y -= 32
        f = self._add_btn.frame()
        self._add_btn.setFrame_(((f[0][0], y), f[1]))

    def add_notification_row(self, time_left, sound):
        self._add_row_views(time_left, sound)
        self._relayout()

    def remove_notification_row(self, tag):
        if tag >= len(self._notification_rows):
            return
        row = self._notification_rows[tag]
        for v in row.values():
            v.removeFromSuperview()
        self._notification_rows.pop(tag)
        for i, r in enumerate(self._notification_rows):
            r["remove_btn"].setTag_(i)
        self._relayout()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def browse_app(self):
        panel = AppKit.NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(False)
        panel.setAllowsMultipleSelection_(False)
        panel.setAllowedFileTypes_(["app"])
        panel.setDirectoryURL_(AppKit.NSURL.fileURLWithPath_("/Applications"))
        result = panel.runModal()
        if result == AppKit.NSModalResponseOK:
            path = panel.URLs()[0].path()
            self._app_field.setStringValue_(path)

    def save(self):
        if self._calendar_checkboxes:
            calendars = [
                cal_id for cal_id, cb in self._calendar_checkboxes
                if cb.state() == AppKit.NSControlStateValueOn
            ]
        else:
            calendars = [c.strip() for c in self._cal_field.stringValue().split(",") if c.strip()]
        notifications = []
        for row in self._notification_rows:
            try:
                t = int(row["time_field"].stringValue())
            except ValueError:
                rumps.notification(title="Invalid settings", subtitle="", message="Notification time must be an integer", sound=True)
                return
            notifications.append({
                "time_left": t,
                "sound": row["sound_cb"].state() == AppKit.NSControlStateValueOn,
            })
        new_settings = {
            "calendars": calendars or ["primary"],
            "link_opening_enabled": self._link_cb.state() == AppKit.NSControlStateValueOn,
            "show_menu_bar": self._bar_cb.state() == AppKit.NSControlStateValueOn,
            "launch_at_login": self._login_cb.state() == AppKit.NSControlStateValueOn,
            "app_meet": self._app_field.stringValue(),
            "notifications": notifications,
        }
        self._window.orderOut_(None)
        AppKit.NSApp.stopModal()
        self._on_save(new_settings)

    def cancel(self):
        self._window.orderOut_(None)
        AppKit.NSApp.stopModal()

    def show(self):
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        AppKit.NSApp.runModalForWindow_(self._window)


def _make_settings_controller(settings, on_save, available_calendars=None):
    return SettingsWindowController(settings, on_save, available_calendars)


class Vince(rumps.App):
    def __init__(self, demo=False):
        super(Vince, self).__init__("Vince", icon="menu-icon.png", template=True)
        self.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        self.flow = None
        self.app_name = "Vince"
        self.demo = demo
        self.settings = self.load_settings()
        self.current_events = []
        self.menu_items = []  # populated by load_events; init empty so timers don't crash before first load
        self.creds = None
        self._calendar_colors = {}   # cal_id -> hex color string
        self._event_color_defs = {}  # colorId str -> hex color string
        self.countdown_windows = {}  # Format: {id: {'window': CountdownWindow, 'closed': bool}}
        self._check_for_update()
        # macOS suspends timers while asleep; without this, events stay stale
        # until the next periodic timer fires (up to 7.5 min after waking).
        AppKit.NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self, "onWake:", AppKit.NSWorkspaceDidWakeNotification, None
        )

    def onWake_(self, notification):
        logging.debug("System woke from sleep, forcing event reload")
        if self.creds and self._has_internet():
            self.load_events()
            self.build_menu()

    def _check_for_update(self):
        def _worker():
            import time
            time.sleep(30)
            try:
                resp = requests.get(
                    "https://api.github.com/repos/esseti/vince/releases/latest",
                    timeout=10,
                    headers={"Accept": "application/vnd.github+json"},
                )
                if resp.status_code != 200:
                    return
                latest = resp.json().get("tag_name", "")
                if not latest or latest == __version__:
                    return

                def _parse(v):
                    try:
                        return tuple(int(x) for x in v.lstrip("v").split("."))
                    except Exception:
                        return (0,)

                if _parse(latest) > _parse(__version__):
                    rumps.notification(
                        title="Vince update available",
                        subtitle=f"Version {latest} is out",
                        message=f"You have {__version__}. Download at github.com/esseti/vince",
                        sound=False,
                    )
            except Exception as e:
                logging.debug(f"Update check failed: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def _has_internet(self):
        try:
            urllib.request.urlopen("https://www.google.com")
            return True
        except urllib.error.URLError:
            return False

    @rumps.timer(5)
    def _load(self, _):
        if self.creds:
            return
        if not self._has_internet():
            logging.debug(f"Waiting for internet ... ")
            self.title = "Waiting for internet ...  "
            quit_btn = rumps.MenuItem("Quit")
            quit_btn.set_callback(self.quit)
            self.menu.clear()
            self.menu.add(quit_btn)
            return

        data_dir = user_data_dir(self.app_name)
        file_path = os.path.join(data_dir, "token.json")
        creds = None
        # handles google login at startup. not the best, but works
        token_path = str(file_path)
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "credentials.json", self.scopes
                    )
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "credentials.json", self.scopes
                )
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(token_path, "w") as token:
                token.write(creds.to_json())
        self.creds = creds
        self.load_events()
        self.build_menu()

    @rumps.timer(90 * 5)
    def timely_load_events(self, _):
        if not self.creds:
            return
        if not self._has_internet():
            logging.debug("No internet, skipping scheduled reload")
            return
        self.load_events()

    # In demo mode popups fire 5 s before start instead of 60 s
    DEMO_POPUP_THRESHOLD_SECONDS = 5

    def _fake_events(self):
        now = datetime.now(pytz.utc)
        # Each event starts just after the popup threshold so the popup fires quickly
        gap = self.DEMO_POPUP_THRESHOLD_SECONDS + 2
        s1 = now + timedelta(seconds=gap)
        e1 = s1 + timedelta(seconds=40)
        s2 = e1 + timedelta(seconds=10)
        e2 = s2 + timedelta(seconds=40)
        s3 = e2 + timedelta(seconds=10)
        e3 = s3 + timedelta(seconds=40)
        def ev(i, s, e):
            return {"id": f"demo_{i}", "start": s, "end": e, "summary": f"Demo event {i}", "url": "", "attendees": [], "urls": [], "eventType": "default", "visibility": "default", "attendee_response": "accepted"}
        return [ev(1, s1, e1), ev(2, s2, e2), ev(3, s3, e3)]

    def load_events(self):
        if self.demo:
            self.menu_items = self._fake_events()
            return
        # gets all todays' event from calendar
        try:
            service = build("calendar", "v3", credentials=self.creds)
            # Refresh calendar and event color definitions if not yet populated
            if not self._calendar_colors:
                try:
                    cal_list = service.calendarList().list().execute()
                    for item in cal_list.get("items", []):
                        self._calendar_colors[item["id"]] = item.get("backgroundColor", "")
                except Exception as e:
                    logging.debug(f"Could not fetch calendar colors: {e}")
            if not self._event_color_defs:
                try:
                    color_defs = service.colors().get().execute()
                    for cid, cdata in color_defs.get("event", {}).items():
                        self._event_color_defs[cid] = cdata.get("background", "")
                except Exception as e:
                    logging.debug(f"Could not fetch event color definitions: {e}")
            # Get today's date and format it
            today = datetime.combine(date.today(), datetime.min.time())
            # Retrieve events for today

            d_events = []
            for calendar in self.settings.get("calendars", ["primary"]):
                try:
                    events_result = (
                        service.events()
                        .list(
                            calendarId=calendar,
                            timeMin=today.strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                            timeMax=(
                                datetime.combine(date.today(), datetime.min.time())
                                + timedelta(days=1)
                            ).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
                            singleEvents=True,
                            orderBy="startTime",
                            showDeleted=False,
                        )
                        .execute()
                    )

                    events = events_result.get("items", [])
                except Exception as e:
                    logging.debug(e)
                    events = None
                if events:
                    for event in events:
                        try:
                            id = event["id"]
                            start = event["start"].get(
                                "dateTime", event["start"].get("date")
                            )
                            end = event["end"].get(
                                "dateTime", event["start"].get("date")
                            )
                            start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S%z")
                            end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S%z")
                        except:
                            # most probably a daily event
                            continue
                        add_event = True
                        # skip declined events.
                        response_status = ""
                        if attendees := event.get("attendees", []):
                            for attendee in attendees:
                                if attendee.get("self", False):
                                    response_status = attendee.get("responseStatus", "")
                                    if attendee["responseStatus"] == "declined":
                                        add_event = False
                        if "#NOVINCE" in event.get("description", ""):
                            add_event = False
                        if add_event:
                            event_url = event.get("hangoutLink", "")
                            description = event.get("description", "")
                            urls = self.extract_urls(description)
                            if not event_url:
                                if urls:
                                    event_url = urls[0]
                            else:
                                urls.append(event_url)
                            logging.debug(
                                f"{event['summary']} | {event.get('description', '')}  | {event_url}"
                            )

                            d_event = dict(
                                id=id,
                                start=start,
                                end=end,
                                summary=event["summary"],
                                url=event_url,
                                attendees=attendees,
                                urls=urls,
                                eventType=event["eventType"],
                                visibility=event.get("visibility", "default"),
                                attendee_response=response_status,
                                calendar_id=calendar,
                                color_id=event.get("colorId", ""),
                            )
                            d_events.append(d_event)
            # Add an event that ends in 5 minutes and 5 seconds

            if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
                d_events.extend(self._fake_events())

            d_events = sorted(d_events, key=lambda d: d["start"])

            self.menu_items = d_events
        except HttpError as err:
            logging.debug(err)
        except Exception as e:
            # network hiccup (e.g. right after sleep/wake) - keep old menu_items,
            # next timer tick or wake notification retries.
            logging.debug(f"load_events failed, will retry: {e}")

    def extract_urls(self, text):
        # # Regular expression pattern to match URLs
        # url_pattern = r"(https?://\S+|meet\.\S+)"

        # # Find all occurrences of the pattern in the text
        # urls = re.findall(url_pattern, text)
        soup = BeautifulSoup(text, "html.parser")

        urls = []
        for link in soup.find_all("a"):
            urls.append(link.get("href"))
        if not urls:
            for link in re.findall(r"(?P<url>https?://[^\s]+)", text):
                urls.append(link)
        return urls

    def build_menu(self):
        # creates the menu,
        self.menu.clear()
        # add the refresh button, just in case

        # Create a menu item for each item in the list
        current_datetime = datetime.now(pytz.utc)
        current_is_now = False
        previous_is_now = False
        for item in self.menu_items:
            previous_is_now = current_is_now
            current_is_now = False
            extra = ""
            if not item["attendees"] or len(item["attendees"]) <= 1:
                extra = "👤"
            if not item["url"]:
                extra += " ⛓️‍💥"

            cal_id = item.get("calendar_id", "")
            color_id = item.get("color_id", "")
            if color_id and color_id in self._event_color_defs:
                cal_color = self._event_color_defs[color_id]
            else:
                cal_color = self._calendar_colors.get(cal_id, "")
            cal_name = ""

            # if it's coming it tells how much time left
            if item["start"] > current_datetime + timedelta(minutes=1):
                hours, minutes = self._time_left(item["start"], current_datetime)
                icon = "⏰"
                if item.get("attendee_response", "") == "tentative":
                    icon = "❓"
                menu_item = rumps.MenuItem(
                    title=f"{icon} {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d}) {item['summary']}{cal_name}"
                )
            elif item["end"] < current_datetime:
                hours, minutes = self._time_left(
                    current_datetime, item["end"], end_time=True
                )
                menu_item = rumps.MenuItem(
                    title=f"☑️ {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d} ago) {item['summary']}{cal_name}"
                )
            else:
                # if it's current, does not print time
                current_is_now = True
                menu_item = rumps.MenuItem(
                    title=f"⭐️ {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}](now) {item['summary']}{cal_name}"
                )
            # Set exact calendar color as dot image on the menu item
            dot = _make_color_dot_image(cal_color)
            if dot:
                menu_item._menuitem.setImage_(dot)
            if item["url"]:
                menu_item.urls = item["urls"]
                menu_item.set_callback(self.open_browser)
            else:
                menu_item.set_callback(self.show_alert)

            if previous_is_now and not current_is_now:
                # last item of now
                self.menu.add(rumps.separator)
            if not previous_is_now and current_is_now:
                # first item of now
                self.menu.add(rumps.separator)

            self.menu.add(menu_item)
        # add the quit button
        self.menu.add(rumps.separator)
        settings_item = rumps.MenuItem("Settings", callback=self.open_settings_window)
        self.menu.add(settings_item)
        refresh_btn = rumps.MenuItem("Refresh")
        refresh_btn.set_callback(self.refresh_menu)
        self.menu.add(refresh_btn)
        force_btn = rumps.MenuItem("Force popup")
        force_btn.set_callback(self.force_popup)
        self.menu.add(force_btn)
        quit_btn = rumps.MenuItem("Quit")
        quit_btn.set_callback(self.quit)
        self.menu.add(quit_btn)

    def _open_browser(self, urls):
        for url in urls:
            if app_meet := self.settings.get("app_meet", ""):
                if url.startswith("https://meet.google.com"):
                    cmd = rf'open -a "{app_meet}" '
                    self._copy_link([url])
                    logging.debug(cmd)
                    os.system(cmd)
                    continue

            webbrowser.open(url)

    def _copy_link(self, urls):
        for url in urls:
            if url.startswith("https://meet.google.com"):
                # copy the url to clipboard
                pb = AppKit.NSPasteboard.generalPasteboard()
                pb.clearContents()
                pb.setString_forType_(url, AppKit.NSPasteboardTypeString)
        return

    def show_alert(self, sender):
        rumps.alert("no link for this event")

    def open_browser(self, sender):
        event = AppKit.NSApplication.sharedApplication().currentEvent()
        logging.info(event.type())
        if event.type() == 1:
            logging.info("left click")
            if self.settings["link_opening_enabled"]:
                self._open_browser(sender.urls)

        elif event.type() == 3:
            logging.info("right click")
            self._copy_link(sender.urls)

    @rumps.clicked("Refresh Menu")
    def refresh_menu(self, _):
        self.load_events()
        self.build_menu()
        self.update_exiting_events(None)

    @rumps.timer(61)
    def update_exiting_events(self, _):
        if not self.creds:
            return
        # every 60 seconds remove the events that are past.

        # res = []
        # for el in self.menu_items:
        #     if el['end'] >= current_datetime:
        #         res.append(el)
        self.menu_items = self.menu_items
        self.build_menu()

    def _time_left(
        self, event_time, current_datetime, show_seconds=False, end_time=False
    ):
        # calcualtes time left between two datetimes, retunrs horus,minutes and optinaly seconds

        time_left = event_time - current_datetime
        time_left_str = str(time_left).split(".")[0]
        time_left_str = time_left_str.split(",")[0]  # Remove microseconds if present
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        time_left_str = f"{hours:02d}:{minutes:02d}"  # :{seconds:02d}
        if not show_seconds:
            if not end_time:
                minutes += 1
                if minutes == 60:
                    hours += 1
                    minutes = 0
            return hours, minutes
        else:
            return hours, minutes, seconds

    def _get_current_events(self):
        # all the events that are happening now.

        current_datetime = datetime.now(pytz.utc)
        res = []
        if self.menu_items:
            for item in self.menu_items:
                if (
                    item["start"] <= current_datetime
                    and item["end"] >= current_datetime
                ):
                    res.append(item)

        return res

    def _get_next_events(self):
        # returns all the events that are not running,
        # if they are at the same time, then shows
        # all therwise only 1.
        current_datetime = datetime.now(pytz.utc)
        res = []
        start_time = None
        if self.menu_items:
            for item in self.menu_items:
                if item["start"] >= current_datetime:
                    if not start_time:
                        start_time = item["start"]
                        res.append(item)
                    else:
                        if start_time == item["start"]:
                            res.append(item)
                        else:
                            return res
        return res

    @rumps.timer(1)
    def update_bar_str(self, _):
        MAX_LENGHT = 200
        if not self.creds:
            return
        if self.settings["show_menu_bar"]:
            if self.menu_items:
                current_datetime = datetime.now(pytz.utc)
                current_events = self._get_current_events()
                next_events = self._get_next_events()
                title = ""
                len_current_events = len(current_events)
                i_current_events = 0
                for event in current_events:
                    prefix = ""
                    if event.get("attendee_response", "") == "tentative":
                        prefix = "❓ "
                    hours, minutes, seconds = self._time_left(event["end"], current_datetime, True)
                    summary = prefix + event["summary"]
                    if hours > 0 or minutes > 15:
                        title += f" {str_truncate(summary, 20)}: {hours:02d}:{minutes:02d}"
                    else:
                        title += f" {str_truncate(summary, 20)}: {hours:02d}:{minutes:02d}:{seconds:02d}"
                    i_current_events += 1
                    if i_current_events < len_current_events:
                        title += ", "
                if current_events != self.current_events:
                    if not current_events:
                        self.dnd(None)
                    else:
                        self.dnd(sorted(current_events, key=lambda x: x["end"])[0])
                    self.current_events = current_events
                len_next_events = len(next_events)
                i_next_events = 0
                if len_next_events:
                    title += " ["
                for event in next_events:
                    if not event or len(event["attendees"]) <= 1:
                        title += " 👤"
                    if event.get("attendee_response", "") == "tentative":
                        title += "❓ "
                    hours, minutes = self._time_left(event["start"], current_datetime)
                    title += f"{str_truncate(event['summary'], 20)}: in {hours:02d}:{minutes:02d}"
                    i_next_events += 1
                    if i_next_events < len_next_events:
                        title += ", "
                if len_next_events:
                    title += "]"
                self.title = "..." if len(title) > MAX_LENGHT else title
            else:
                self.title = ""
        else:
            self.title = ""

    def _str_event_menu_current(self, element):
        # create the items in the menu. util function
        current_datetime = datetime.now(pytz.utc)
        if element["start"] > current_datetime:
            hours, minutes = self._time_left(element["start"], current_datetime)
            time_left_str = f" in {hours:02d}:{minutes:02d}"
        else:
            if element["start"] < current_datetime:
                hours, minutes = self._time_left(element["end"], current_datetime)
                time_left_str = f" {hours:02d}:{minutes:02d} left"
        return f"{element['summary'][:20]} {time_left_str}"

    def _str_event_menu_next(self, element):
        # same but for upcoming eents.
        current_datetime = datetime.now(pytz.utc)
        if element:
            hours, minutes = self._time_left(element["start"], current_datetime)
            title = f" [{element['summary'][:20]} in {hours:02d}:{minutes:02d}]"
            return title
        else:
            return ""

    @rumps.timer(1)
    def send_notification(self, _):
        if not self.creds and not self.demo:
            return
        if self.settings["notifications"]:
            if self.menu_items:
                current_datetime = datetime.now(pytz.utc)
                current_events = self._get_current_events()
                for event in current_events:
                    hours, minutes, seconds = self._time_left(
                        event["end"], current_datetime, True
                    )
                    # send a notification 5 min before the end that event it's almost over
                    notifications = self.settings["notifications"]
                    for notification in notifications:
                        minute_notification = notification["time_left"]
                        if (
                            hours == 0
                            and minutes == minute_notification
                            and seconds == 0
                        ):
                            rumps.notification(
                                title=f"{minute_notification} minutes left",
                                subtitle=f"Just {minute_notification}",
                                message=f"I said {minute_notification} mins left",
                                sound=notification["sound"],
                            )
                        # and when it's over
                    if hours == 0 and minutes == 0 and seconds == 0:
                        rumps.notification(
                            title=f"{event['summary']}",
                            subtitle="It's over",
                            message="It's over",
                            sound=True,
                        )

    @rumps.timer(1)
    def popup_for_upcoming(self, _):
        current_datetime = datetime.now(pytz.utc)
        for event in self.menu_items:
            hours, minutes, seconds = self._time_left(
                event["start"], current_datetime, show_seconds=True
            )
            total_seconds = hours * 3600 + minutes * 60 + seconds
            if self.demo:
                trigger = total_seconds == self.DEMO_POPUP_THRESHOLD_SECONDS
            else:
                trigger = hours == 0 and minutes == 1 and seconds == 0
            if trigger:
                self.countdown_windows[event["id"]] = {
                    "window": CountdownWindow(event, parent=self),
                    "closed": False,
                }
                self.countdown_windows[event["id"]]["window"].start_countdown()
                self.countdown_windows[event["id"]]["window"].show()

    def force_popup(self, _):
        current_events = self._get_current_events()
        for event in current_events:
            if event["id"] in self.countdown_windows:
                self.countdown_windows[event["id"]]["window"].close()
            self.countdown_windows[event["id"]] = {
                "window": CountdownWindow(event, parent=self),
                "closed": False,
            }
            self.countdown_windows[event["id"]]["window"].start_countdown()
            self.countdown_windows[event["id"]]["closed"] = False
            self.countdown_windows[event["id"]]["window"].show()

    # def arrange_countdown_windows(self):
    #     windows = sorted(
    #         [w["window"] for w in self.countdown_windows.values()],
    #         key=lambda x: x.event["id"],
    #     )
    #     screen = AppKit.NSScreen.mainScreen()
    #     screen_frame = screen.frame()
    #     window_height = 50.0
    #     vertical_spacing = window_height + 15.0
    #     y_position = screen_frame.size.height - vertical_spacing

    #     for window in windows:
    #         if window.window.isVisible():
    #             frame = window.window.frame()
    #             frame.origin.y = y_position
    #             y_position -= vertical_spacing
    #             window.window.setFrame_display_(frame, True)

    # @rumps.timer(1)
    # def update_window_positions(self, _):
    #     self.arrange_countdown_windows()

    # for window in self.countdown_windows.values():

    @rumps.timer(1)
    def send_and_open_link(self, _):
        if not self.creds:
            return
        if self.settings["link_opening_enabled"]:
            # 1 min beofre the meeting it opens the browser with the link
            # you can't miss it.
            if self.menu_items:
                current_datetime = datetime.now(pytz.utc)
                next_events = self._get_next_events()
                for event in next_events:
                    hours, minutes, seconds = self._time_left(
                        event["start"], current_datetime, show_seconds=True
                    )
                    if hours == 0 and minutes == 1 and seconds == 0:
                        rumps.notification(
                            title="It's meeting time",
                            subtitle=f"For {event['summary']}",
                            message=f"For {event['summary']}",
                            sound=True,
                        )
                        if self.settings["link_opening_enabled"]:
                            if event.get("attendee_response", "") == "tentative":
                                continue
                            if event["urls"]:
                                self._open_browser(event["urls"])

    @rumps.clicked("Quit")
    def quit(self, _):
        logging.debug("over")
        rumps.quit_application()

    def _convert_minutes_to_epoch(self, mins):
        future = datetime.utcnow() + timedelta(minutes=mins + 1)
        epoch = calendar.timegm(future.timetuple())
        return epoch

    def dnd(self, event, reset=False):
        current_datetime = datetime.now(pytz.utc)
        # no DND if there's no attenedees (means the event is mine?)
        if not event or len(event["attendees"]) <= 1:
            # reset DND
            pars = "off"
        else:
            minutes = (event["end"] - current_datetime).seconds // 60
            # set DND for minutes, note that this is already 1 min before.
            pars = minutes + 1
        try:
            logging.info(f'shortcuts run "Calm Notifications" -i {pars}')
            os.system(f'shortcuts run "Calm Notifications" -i {pars}')
        except Exception:
            logging.exception("Problemi with running shorcut.")

    # ------------------------------------------------------------------
    # Launch at login helpers
    # ------------------------------------------------------------------

    _LAUNCH_AGENT_LABEL = "com.stefanotranquillini.vince"

    def _launch_agent_path(self):
        agents_dir = os.path.expanduser("~/Library/LaunchAgents")
        return os.path.join(agents_dir, f"{self._LAUNCH_AGENT_LABEL}.plist")

    def _app_executable(self):
        import sys
        exe = os.path.abspath(sys.executable)
        # When running as py2app bundle: .../Vince.app/Contents/MacOS/vince
        # We want to launch the .app bundle itself via 'open'
        parts = exe.split(os.sep)
        for i, p in enumerate(parts):
            if p.endswith(".app"):
                return os.sep + os.path.join(*parts[: i + 1])
        return exe  # fallback: running from source

    def _is_launch_at_login(self):
        return os.path.exists(self._launch_agent_path())

    def _set_launch_at_login(self, enabled):
        plist_path = self._launch_agent_path()
        agents_dir = os.path.dirname(plist_path)
        if enabled:
            os.makedirs(agents_dir, exist_ok=True)
            app_path = self._app_executable()
            if app_path.endswith(".app"):
                program_args = ["/usr/bin/open", "-a", app_path]
            else:
                import sys
                program_args = [sys.executable, app_path]
            plist = {
                "Label": self._LAUNCH_AGENT_LABEL,
                "ProgramArguments": program_args,
                "RunAtLoad": True,
                "KeepAlive": False,
            }
            with open(plist_path, "wb") as f:
                plistlib.dump(plist, f)
            os.system(f"launchctl load '{plist_path}'")
        else:
            if os.path.exists(plist_path):
                os.system(f"launchctl unload '{plist_path}'")
                os.remove(plist_path)

    # ------------------------------------------------------------------

    def load_settings(self):
        data_dir = user_data_dir(self.app_name)
        settings_path = os.path.join(data_dir, "settings.json")
        is_first_launch = not os.path.exists(settings_path)
        default_settings = {
            "calendars": ["primary"],
            "link_opening_enabled": True,
            "show_menu_bar": True,
            "app_meet": "",
            "launch_at_login": True,
            "notifications": [
                {"time_left": 5, "sound": False},
                {"time_left": 3, "sound": False},
                {"time_left": 1, "sound": False},
            ],
        }
        try:
            with open(settings_path, "r") as settings_file:
                settings = json.load(settings_file)
                settings = {**default_settings, **settings}
        except (FileNotFoundError, json.JSONDecodeError):
            settings = default_settings
        if is_first_launch:
            self._set_launch_at_login(True)
        return settings

    def save_settings(self):
        data_dir = user_data_dir(self.app_name)
        settings_path = os.path.join(data_dir, "settings.json")
        with open(settings_path, "w") as settings_file:
            json.dump(self.settings, settings_file, indent=4)

    def _fetch_available_calendars(self):
        if not self.creds:
            return None
        try:
            service = build("calendar", "v3", credentials=self.creds)
            result = service.calendarList().list().execute()
            calendars = []
            for item in result.get("items", []):
                cal = {
                    "id": item["id"],
                    "name": item.get("summary", item["id"]),
                    "color": item.get("backgroundColor", ""),
                }
                calendars.append(cal)
                self._calendar_colors[item["id"]] = item.get("backgroundColor", "")
            return calendars or None
        except Exception as e:
            logging.debug(f"Could not fetch calendar list: {e}")
            return None

    def _event_color(self, event):
        """Return the effective hex color for an event (event-level override or calendar color)."""
        color_id = event.get("color_id", "")
        if color_id and color_id in self._event_color_defs:
            return self._event_color_defs[color_id]
        return self._calendar_colors.get(event.get("calendar_id", ""), "")

    def open_settings_window(self, _):
        available_calendars = self._fetch_available_calendars()
        self._settings_controller = _make_settings_controller(self.settings, self._on_settings_save, available_calendars)
        self._settings_controller.show()

    def _on_settings_save(self, new_settings):
        old_launch = self.settings.get("launch_at_login", True)
        new_launch = new_settings.get("launch_at_login", True)
        self.settings = new_settings
        self.save_settings()
        if old_launch != new_launch:
            self._set_launch_at_login(new_launch)
        rumps.notification(
            title="Saved settings",
            subtitle="",
            message="Settings saved successfully",
            sound=True,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug", action="store_true", help="Set logger to debug level"
    )
    parser.add_argument(
        "--demo", action="store_true", help="Use fake events instead of real calendar data"
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    app = Vince(demo=args.demo)
    app.run()

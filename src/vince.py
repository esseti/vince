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
import random
import string
import re
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def str_truncate(string, width):
    if len(string) > width:
        string = string[: width - 3] + "..."
    return string


class Vince(rumps.App):
    def __init__(self):
        super(Vince, self).__init__("Vince", icon="menu-icon.png", template=True)
        self.scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
        self.flow = None
        # this is to get the library folder
        self.app_name = "Vince"
        self.settings = self.load_settings()
        self.current_events = []
        self.creds = None
        self.countdown_windows = {}  # Format: {id: {'window': CountdownWindow, 'closed': bool}}

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
        self.load_events()

    def load_events(self):
        # d_events=[]
        # now = datetime.now(pytz.utc)
        # i=1
        # d_event = dict(id=1, start=now+timedelta(seconds=15), end=now+timedelta(seconds=30), summary=f"Event {i}", url="URL {i}", eventType='',visibility='default')
        # d_events.append(d_event)
        # i=2
        # d_event = dict(id=1, start=now+timedelta(seconds=65), end=now+timedelta(seconds=185+60), summary=f"Event {i}", url="http://{i}.com", eventType='',visibility='default')
        # d_events.append(d_event)
        # self.menu_items = d_events
        # gets all todays' event from calendar
        try:
            service = build("calendar", "v3", credentials=self.creds)
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

                        if attendees := event.get("attendees", []):
                            for attendee in attendees:
                                if attendee.get("self", False):
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
                            )
                            d_events.append(d_event)
            # Add an event that ends in 5 minutes and 5 seconds

            if logging.getLogger().getEffectiveLevel() == logging.DEBUG:
                now = datetime.now(pytz.utc)
                end_time = now + timedelta(minutes=0, seconds=10)
                d_events.append(
                    {
                        "id": "upcoming_end_event_1",
                        "start": now,
                        "end": end_time,
                        "summary": "Event ending soon",
                        "url": "",
                        "attendees": [],
                        "urls": [],
                        "eventType": "default",
                        "visibility": "default",
                    }
                )
                start_time = end_time + timedelta(seconds=10)
                end_time = start_time + timedelta(seconds=60)
                d_events.append(
                    {
                        "id": "upcoming_end_event_2",
                        "start": start_time,
                        "end": end_time,
                        "summary": "Event ending soon 2",
                        "url": "",
                        "attendees": [],
                        "urls": [],
                        "eventType": "default",
                        "visibility": "default",
                    }
                )
                start_time = end_time + timedelta(seconds=60)
                end_time = start_time + timedelta(seconds=60)
                d_events.append(
                    {
                        "id": "upcoming_end_event_3",
                        "start": start_time,
                        "end": end_time,
                        "summary": "Event ending soon3",
                        "url": "",
                        "attendees": [],
                        "urls": [],
                        "eventType": "default",
                        "visibility": "default",
                    }
                )

            # Update settings for notifications
            self.settings["notifications"] = [
                {"time_left": 1, "sound": True},
                {"time_left": 0, "sound": True},
            ]

            d_events = sorted(d_events, key=lambda d: d["start"])

            self.menu_items = d_events
        except HttpError as err:
            logging.debug(err)

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
            # if there's a meet link it adds the link and the "clicking option"
            # otherwise the item cannot be clicked. and it look disable.

            # if it's coming it tells how much time left
            if item["start"] > current_datetime + timedelta(minutes=1):
                hours, minutes = self._time_left(item["start"], current_datetime)
                menu_item = rumps.MenuItem(
                    title=f"⏰ {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d}) {item['summary']}"
                )
            elif item["end"] < current_datetime:
                hours, minutes = self._time_left(
                    current_datetime, item["end"], end_time=True
                )

                menu_item = rumps.MenuItem(
                    title=f"☑️ {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d} ago) {item['summary']}"
                )
            else:
                # if it's current, does not print time
                current_is_now = True
                menu_item = rumps.MenuItem(
                    title=f"⭐️ {extra} [{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}](now) {item['summary']}"
                )
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
                    cmd = rf"open -a {app_meet} "
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
            # updates the bar
            if self.menu_items:
                current_datetime = datetime.now(pytz.utc)
                current_events = self._get_current_events()
                next_events = self._get_next_events()
                title = ""
                len_current_events = len(current_events)
                i_current_events = 0
                # first all the current, with time left
                for event in current_events:
                    hours, minutes, seconds = self._time_left(
                        event["end"], current_datetime, True
                    )
                    summary = event["summary"]
                    # if not event or len(event["attendees"]) <= 1:
                    #     summary = "👤"
                    if hours > 0 or minutes > 15:
                        title += (
                            f" {str_truncate(summary, 20)}: {hours:02d}:{minutes:02d}"
                        )
                    else:
                        title += f" {str_truncate(summary, 20)}: {hours:02d}:{minutes:02d}:{seconds:02d}"
                    i_current_events += 1
                    # separated with comma if more than one
                    if i_current_events < len_current_events:
                        title += ", "
                if current_events != self.current_events:
                    if not current_events:
                        self.dnd(None)
                        self.slack_meeting(None)
                    else:
                        event = sorted(current_events, key=lambda x: x["end"])[0]
                        self.slack_meeting(event)
                        self.dnd(event)

                    self.current_events = current_events
                    # get the shortest one and update with taht data
                len_next_events = len(next_events)
                i_next_events = 0
                # and upcoming with thime left before the start
                if len_next_events:
                    title += " ["
                for event in next_events:
                    if not event or len(event["attendees"]) <= 1:
                        title += " 👤"
                    hours, minutes = self._time_left(event["start"], current_datetime)
                    title += f"{str_truncate(event['summary'], 20)}: in {hours:02d}:{minutes:02d}"
                    i_next_events += 1
                    if i_next_events < len_next_events:
                        title += ", "
                if len_next_events:
                    title += "]"
                if len(title) > MAX_LENGHT:
                    self.title = f"..."
                else:
                    self.title = title
            else:
                self.title = f""
        else:
            self.title = f""

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
        if not self.creds:
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
            if hours == 0 and minutes == 1 and seconds == 0:
                self.countdown_windows[event["id"]] = {
                    "window": CountdownWindow(event, parent=self),
                    "closed": False,
                }
                self.countdown_windows[event["id"]]["window"].start_countdown()
                self.countdown_windows[event["id"]]["window"].show()

    def force_popup(self, _):
        current_events = self._get_current_events()
        for event in current_events:
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

    def slack_meeting(self, event, reset=False):
        slack_token = self.settings.get("slack_oauth_token", "")
        if not slack_token:
            return
        auth = {"Authorization": "Bearer %s" % slack_token}
        # if reset:
        #     data = {"num_minutes": 0}
        #     res = requests.get('https://slack.com/api/dnd.setSnooze', params=data,
        #                        headers=auth)
        # else:
        current_datetime = datetime.now(pytz.utc)
        if not event:
            data = {"profile": {"status_text": "", "status_emoji": ""}}
            epoch = self._convert_minutes_to_epoch(0)
            data["profile"]["status_expiration"] = epoch
            res = requests.post(
                "https://slack.com/api/users.profile.set", json=data, headers=auth
            )
            data = {"num_minutes": 0}
            res = requests.get(
                "https://slack.com/api/dnd.setSnooze", params=data, headers=auth
            )
        else:
            minutes = (event["end"] - current_datetime).seconds // 60
            if event["eventType"] == "outOfOffice":
                status_emoji = ":no_entry_sign:"
            elif event["eventType"] == "focusTime":
                status_emoji = ":person_in_lotus_position:"
            elif event["summary"].lower() in ["lunch"]:
                status_emoji = ":chef-brb:"
            else:
                status_emoji = ":date:"

            if event["visibility"] in ["default", "public"]:
                status_text = f"{event['summary']} [{event['start'].strftime('%H:%M')}-{event['end'].strftime('%H:%M')}]"
            else:
                status_text = f"Meeting [{event['start'].strftime('%H:%M')}-{event['end'].strftime('%H:%M')}]"
            data = {
                "profile": {"status_text": status_text, "status_emoji": status_emoji}
            }
            epoch = self._convert_minutes_to_epoch(minutes)
            data["profile"]["status_expiration"] = epoch
            res = requests.post(
                "https://slack.com/api/users.profile.set", json=data, headers=auth
            )
            data = {"num_minutes": minutes}
            res = requests.get(
                "https://slack.com/api/dnd.setSnooze", params=data, headers=auth
            )

    def load_settings(self):
        data_dir = user_data_dir(self.app_name)
        settings_path = os.path.join(data_dir, "settings.json")
        default_settings = {
            "calendars": ["primary"],
            "link_opening_enabled": True,
            "show_menu_bar": True,
            "app_meet": "",
            "notifications": [
                {"time_left": 5, "sound": False},
                {"time_left": 3, "sound": False},
                {"time_left": 1, "sound": False},
            ],
        }
        try:
            with open(settings_path, "r") as settings_file:
                settings = json.load(settings_file)
                # Merge loaded settings with default settings
                settings = {**default_settings, **settings}
        except (FileNotFoundError, json.JSONDecodeError):
            settings = default_settings
        return settings

    def save_settings(self):
        data_dir = user_data_dir(self.app_name)
        settings_path = os.path.join(data_dir, "settings.json")
        with open(settings_path, "w") as settings_file:
            json.dump(self.settings, settings_file, indent=4)

    def slack_oauth(self):
        client_id = "3091729876.2525836761175"
        scopes = "user_scope=dnd:write,users.profile:write,users:write"
        state = "".join(random.choices(string.ascii_uppercase + string.digits, k=15))
        url = (
            "https://slack.com/oauth/v2/authorize?client_id="
            + client_id
            + "&scope=&"
            + scopes
            + "&state="
            + state
        )
        rumps.alert(
            "Proceed in the browers and copy the string `xoxo--..` and past them in the settings at `slack_oauth_token`"
        )
        webbrowser.open(url)
        self.open_settings_window(None)

    def open_settings_window(self, _):
        window = rumps.Window(
            title="Vince Settings",
            dimensions=(300, 200),
            ok="Save settings",
            cancel=True,
        )
        window.message = "Configure your settings:"
        window.default_text = json.dumps(self.settings, indent=2)
        window.add_button("Slack Setup")
        res = window.run()
        if res.clicked == 2:
            self.slack_oauth()
        try:
            self.settings = json.loads(res.text)
            self.save_settings()
            rumps.notification(
                title="Saved settings",
                subtitle="",
                message="Saved settings",
                sound=True,
            )
        except:
            rumps.notification(
                title="Cannot save the settings",
                subtitle="",
                message="There was an error",
                sound=True,
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug", action="store_true", help="Set logger to debug level"
    )
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    app = Vince()
    app.run()

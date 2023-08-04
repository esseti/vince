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
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from appdirs import user_data_dir


from datetime import datetime, date, timedelta


def str_truncate(string, width):
    if len(string) > width:
        string = string[:width-3] + '...'
    return string


class Vince(rumps.App):
    def __init__(self):
        super(Vince, self).__init__(
            "Vince", icon="menu-icon.png", template=True)
        self.scopes = ['https://www.googleapis.com/auth/calendar.readonly']
        self.flow = None
        # this is to get the library folder
        self.app_name = "Vince"
        self.settings = self.load_settings()
        self.current_events = []

        data_dir = user_data_dir(self.app_name)
        file_path = os.path.join(data_dir, "token.json")
        creds = None
        # handles google login at startup. not the best, but works
        token_path = str(file_path)
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(
                token_path, self.scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        'credentials.json', self.scopes)
                    creds = flow.run_local_server(port=0)
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', self.scopes)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(token_path, 'w') as token:
                token.write(creds.to_json())
        self.creds = creds
        self.load_events()
        self.build_menu()

    def load_events(self):
        # gets all todays' event from calendar
        try:
            service = build('calendar', 'v3', credentials=self.creds)
            # Get today's date and format it
            today = datetime.combine(date.today(), datetime.min.time())
            # Retrieve events for today
            events_result = service.events().list(
                calendarId='primary',
                timeMin=today.strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                timeMax=(datetime.combine(date.today(), datetime.min.time(
                )) + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                singleEvents=True,
                orderBy='startTime',
                showDeleted=False,
            ).execute()

            events = events_result.get('items', [])
            d_events = []
            if events:
                for event in events:
                    try:
                        id = event['id']
                        start = event['start'].get(
                            'dateTime', event['start'].get('date'))
                        end = event['end'].get(
                            'dateTime', event['start'].get('date'))
                        start = datetime.strptime(start, "%Y-%m-%dT%H:%M:%S%z")
                        end = datetime.strptime(end, "%Y-%m-%dT%H:%M:%S%z")
                    except:
                        # most probably a daily event
                        continue
                    add_event = True
                    # skip declined events.

                    if attendees := event.get('attendees', []):
                        for attendee in attendees:
                            if attendee.get('self', False):
                                if attendee['responseStatus'] == 'declined':
                                    add_event = False
                    if add_event:
                        event_url = event.get(
                            'hangoutLink', '')
                        if not event_url:
                            description = event.get("description","")
                            urls = self.extract_urls(description)
                            if urls:
                                event_url = urls[0]
                        d_event = dict(id=id, start=start, end=end, summary=event["summary"], url=event_url, eventType=event['eventType'],visibility=event.get('visibility','default'))
                        d_events.append(d_event)
            self.menu_items = d_events
        except HttpError as err:
            print(err)

    def extract_urls(self, text):
        # Regular expression pattern to match URLs
        url_pattern = r"(https?://\S+|meet\.\S+)"
        
        # Find all occurrences of the pattern in the text
        urls = re.findall(url_pattern, text)
        
        return urls

    def build_menu(self):
        # creates the menu,
        self.menu.clear()
        # add the refresh button, just in case

        # Create a menu item for each item in the list
        current_datetime = datetime.now(pytz.utc)
        for item in self.menu_items:
            # if it's coming it tells how much time left
            if item['start'] > current_datetime:
                hours, minutes = self._time_left(
                    item['start'], current_datetime)
                menu_item = rumps.MenuItem(
                    title=f"[{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d}) {item['summary']}")
            else:
                # if it's current, does not print time
                menu_item = rumps.MenuItem(
                    title=f"[{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}](now) {item['summary']}")
            if item['url']:
                # if there's a meet link it adds the link and the "clicking option"
                # otherwise the item cannot be clicked. and it look disable.
                menu_item.url = item['url']
                menu_item.set_callback(self.open_browser)
            self.menu.add(menu_item)
        # add the quit button
        settings_item = rumps.MenuItem(
            "Settings", callback=self.open_settings_window)
        self.menu.add(settings_item)
        refresh_btn = rumps.MenuItem("Refresh")
        refresh_btn.set_callback(self.refresh_menu)
        self.menu.add(refresh_btn)
        quit_btn = rumps.MenuItem("Quit")
        quit_btn.set_callback(self.quit)
        self.menu.add(quit_btn)

    def open_browser(self, sender):
        if self.settings['link_opening_enabled']:
            webbrowser.open(sender.url)

    @rumps.clicked("Refresh Menu")
    def refresh_menu(self, _):
        self.load_events()
        self.build_menu()
        self.update_exiting_events(None)

    @rumps.timer(60)
    def update_exiting_events(self, _):
        # every 60 seconds remove the events that are past.
        current_datetime = datetime.now(pytz.utc)
        res = []
        for el in self.menu_items:
            if el['end'] >= current_datetime:

                res.append(el)
        self.menu_items = res
        self.build_menu()

    def _time_left(self, event_time, current_datetime, show_seconds=False):
        # calcualtes time left between two datetimes, retunrs horus,minutes and optinaly seconds

        time_left = event_time - current_datetime
        time_left_str = str(time_left).split(".")[0]
        time_left_str = time_left_str.split(",")[0] # Remove microseconds if present
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        time_left_str = f"{hours:02d}:{minutes:02d}" # :{seconds:02d}
        if not show_seconds:
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
                if item['start'] <= current_datetime and item['end'] >= current_datetime:
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
                if item['start'] >= current_datetime:
                    if not start_time:
                        start_time = item['start']
                        res.append(item)
                    else:
                        if start_time == item['start']:
                            res.append(item)
                        else:
                            return res
        return res

    @rumps.timer(1)
    def update_bar_str(self, _):
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
                    event['end'], current_datetime, True)
                title += f" {str_truncate(event['summary'],20)}: {hours:02d}:{minutes:02d}:{seconds:02d} left"
                i_current_events += 1
                # separated with comma if more than one
                if i_current_events < len_current_events:
                    title += ", "
            if current_events != self.current_events:
                if not current_events:
                    self.slack_meeting(None)
                else:
                    event = sorted(current_events, key=lambda x: x["end"])[0]
                    self.slack_meeting(event)

                self.current_events = current_events
                # get the shortest one and update with taht data
            len_next_events = len(next_events)
            i_next_events = 0
            # and upcoming with thime left before the start
            if len_next_events:
                title += " ["
            for event in next_events:
                hours, minutes = self._time_left(
                    event['start'], current_datetime)
                title += f"{str_truncate(event['summary'],20)}: in {hours:02d}:{minutes:02d}"
                i_next_events += 1
                if i_next_events < len_next_events:
                    title += ", "
            if len_next_events:
                title += "]"
            self.title = title
        else:
            self.title = f"-"

    def _str_event_menu_current(self, element):
        # create the items in the menu. util function
        current_datetime = datetime.now(pytz.utc)
        if element['start'] > current_datetime:
            hours, minutes = self._time_left(
                element['start'], current_datetime)
            time_left_str = f" in {hours:02d}:{minutes:02d}"
        else:
            if element['start'] < current_datetime:
                hours, minutes = self._time_left(
                    element['end'], current_datetime)
                time_left_str = f" {hours:02d}:{minutes:02d} left"
        return f"{element['summary'][:20]} {time_left_str}"

    def _str_event_menu_next(self, element):
        # same but for upcoming eents.
        current_datetime = datetime.now(pytz.utc)
        if element:
            hours, minutes = self._time_left(
                element['start'], current_datetime)
            title += f" [{element['summary'][:20]} in {hours:02d}:{minutes:02d}]"
            return title
        else:
            return ""

    @rumps.timer(1)
    def send_notification_(self, _):
        if not self.settings['notification_enabled']:
            return
        if self.menu_items:
            current_datetime = datetime.now(pytz.utc)
            if current_datetime.second == 0:
                current_events = self._get_current_events()
                for event in current_events:
                    hours, minutes = self._time_left(
                        event['end'], current_datetime)
                    # send a notification 5 min before the end that event it's almost over
                    minutes_notifications = self.settings['notification_time_left']
                    for minute_notification in minutes_notifications:
                        if hours == 0 and minutes == minute_notification:
                            rumps.notification(
                                title=f"{minute_notification} minutes left",
                                subtitle=f"Just {minute_notification}",
                                message=f"I said {minute_notification} mins left",
                                sound=True
                            )
                    # and when it's over
                    if hours == 0 and minutes == 0:
                        rumps.notification(
                            title="It's over",
                            subtitle="It's over",
                            message="It's over",
                            sound=True
                        )

    @rumps.timer(1)
    def send_and_open_link(self, _):
        if not self.settings['notification_enabled']:
            return
        # 1 min beofre the meeting it opens the browser with the link
        # you can't miss it.
        if self.menu_items:
            current_datetime = datetime.now(pytz.utc)
            if current_datetime.second == 0:
                next_events = self._get_next_events()
                for event in next_events:
                    hours, minutes = self._time_left(
                        event['start'], current_datetime)
                    
                    if hours == 0 and minutes == 1:
                        rumps.notification(
                            title="It's meeting time",
                            subtitle=f"{event['summary']}",
                            message=f"{event['summary']}",
                            sound=True
                        )
                        if event['url']:
                            webbrowser.open(event['url'])

    @rumps.clicked("Quit")
    def quit(self, _):
        print('over')
        rumps.quit_application()

    def _convert_minutes_to_epoch(self, mins):
        future = datetime.utcnow() + timedelta(minutes=mins+1)
        epoch = calendar.timegm(future.timetuple())
        return epoch

    def slack_meeting(self, event, reset=False):
        auth = {
            'Authorization': 'Bearer %s' % self.settings['slack_oauth_token']}
        # if reset:
        #     data = {"num_minutes": 0}
        #     res = requests.get('https://slack.com/api/dnd.setSnooze', params=data,
        #                        headers=auth)
        # else:
        current_datetime = datetime.now(pytz.utc)
        if not event:
            data = {
                "profile": {
                    "status_text": "",
                    "status_emoji": ""
                }
            }
            epoch = self._convert_minutes_to_epoch(0)
            data['profile']["status_expiration"] = epoch
            res = requests.post('https://slack.com/api/users.profile.set', json=data,
                                headers=auth)
            data = {"num_minutes": 0}
            res = requests.get('https://slack.com/api/dnd.setSnooze', params=data,
                               headers=auth)
        else:
            minutes = (event['end']-current_datetime).seconds // 60
            if event['eventType'] == 'outOfOffice':
                status_emoji = ":no_entry_sign:"
            elif event['eventType'] == 'focusTime':
                status_emoji = ":person_in_lotus_position:"
            elif event['summary'].lower() in ['lunch']:
                status_emoji = ":chef-brb:"
            else:
                status_emoji = ":date:"
            
            if event['visibility'] in ['default','public']:
                status_text = f"{event['summary']} [{event['start'].strftime('%H:%M')}-{event['end'].strftime('%H:%M')}]"
            else:
                status_text = f"Meeting [{event['start'].strftime('%H:%M')}-{event['end'].strftime('%H:%M')}]"
            data = {
                "profile": {
                    "status_text": status_text,
                    "status_emoji": status_emoji
                }
            }
            epoch = self._convert_minutes_to_epoch(minutes)
            data['profile']["status_expiration"] = epoch
            res = requests.post('https://slack.com/api/users.profile.set', json=data,
                                headers=auth)
            data = {"num_minutes": minutes}
            res = requests.get('https://slack.com/api/dnd.setSnooze', params=data,
                               headers=auth)

    def load_settings(self):
        data_dir = user_data_dir(self.app_name)
        settings_path = os.path.join(data_dir, "settings.json")
        default_settings = {
            "link_opening_enabled": True,
            "notification_enabled": True,
            "notification_time_left":[5],
            "slack_status_enabled": False,
            "slack_oauth_token": "",
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
        client_id = '3091729876.2525836761175'
        scopes = "user_scope=dnd:write,users.profile:write,users:write"
        state = ''.join(random.choices(
            string.ascii_uppercase + string.digits, k=15))
        url = "https://slack.com/oauth/v2/authorize?client_id=" + \
            client_id+"&scope=&"+scopes+"&state="+state
        rumps.alert(
            "Proceed in the browers and copy the string `xoxo--..` and past them in the settings at `slack_oauth_token`")
        webbrowser.open(url)
        self.open_settings_window(None)

    def open_settings_window(self, _):
        window = rumps.Window(title="Vince Settings", dimensions=(
            300, 200), ok='Save settings', cancel=True)
        window.message = "Configure your settings:"
        window.default_text = json.dumps(self.settings, indent=2)
        window.add_button('Slack Setup')
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
                sound=True
            )
        except:
            rumps.notification(
                title="Cannot save the settings",
                subtitle="",
                message="There was an error",
                sound=True
            )


if __name__ == "__main__":
    app = Vince()
    app.run()

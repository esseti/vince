import rumps
import os
import os.path
import webbrowser
import pytz 
import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from appdirs import user_data_dir


from datetime import datetime, date, timedelta

class Vince(rumps.App):
    def __init__(self):
        super(Vince, self).__init__("Vince")
        self.scopes =['https://www.googleapis.com/auth/calendar.readonly']
        self.flow = None

        # this is to get the library folder
        app_name = "Vince" 
        data_dir = user_data_dir(app_name)
        file_path = os.path.join(data_dir, "token.json")
  
        creds = None
        # handles google login at startup. not the best, but works     
        token_path = str(file_path)
        if os.path.exists(token_path):
            creds = Credentials.from_authorized_user_file(token_path, self.scopes)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
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
                timeMax=(datetime.combine(date.today(), datetime.min.time()) + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S.%fZ'),
                singleEvents=True,
                orderBy='startTime',
                showDeleted=False,
            ).execute()

            events = events_result.get('items', [])
            d_events = []
            if events:
                for event in events:
                    start = event['start'].get('dateTime', event['start'].get('date'))
                    end =  event['end'].get('dateTime', event['start'].get('date'))
                    start = datetime.strptime(start,"%Y-%m-%dT%H:%M:%S%z")
                    end = datetime.strptime(end,"%Y-%m-%dT%H:%M:%S%z")
                    d_event = dict(start=start,end=end,summary=event["summary"],url=event.get('hangoutLink',''))
                    d_events.append(d_event)
            self.menu_items = d_events
        except HttpError as err:
            print(err)

    def build_menu(self):
        # creates the menu, 
        self.menu.clear() 
        # add the refresh button, just in case
        refresh_btn = rumps.MenuItem("Refresh")
        refresh_btn.set_callback(self.refresh_menu)
        self.menu.add(refresh_btn)
        # Create a menu item for each item in the list
        current_datetime = datetime.now(pytz.utc)
        for item in self.menu_items:
            # if it's coming it tells how much time left
            if item['start']>current_datetime:
                hours, minutes = self._time_left(item['start'], current_datetime)
                menu_item = rumps.MenuItem(title=f"[{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}]({hours:02d}:{minutes:02d}) {item['summary']}")
            else:
                # if it's current, does not print time
                menu_item = rumps.MenuItem(title=f"[{item['start'].strftime('%H:%M')}-{item['end'].strftime('%H:%M')}] {item['summary']}")
            if item['url']:
                # if there's a meet link it adds the link and the "clicking option"
                # otherwise the item cannot be clicked. and it look disable.
                menu_item.url = item['url'] 
                menu_item.set_callback(self.open_browser)  
            self.menu.add(menu_item)
        # add the quit button
        quit_btn = rumps.MenuItem("Quit")
        quit_btn.set_callback(self.quit)
        self.menu.add(quit_btn)
    
    def open_browser(self, sender):
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

    def _time_left(self, event_time, current_datetime, show_seconds = False):
        #calcualtes time left between two datetimes, retunrs horus,minutes and optinaly seconds

        time_left = event_time - current_datetime
        time_left_str = str(time_left).split(".")[0]
        time_left_str = time_left_str.split(",")[0]  # Remove microseconds if present
        hours, remainder = divmod(time_left.seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        time_left_str = f"{hours:02d}:{minutes:02d}" #:{seconds:02d}
        if not show_seconds:
            return hours, minutes
        else:
            return hours, minutes, seconds
    
    def _get_current_events(self):
        # all the events that are happening now.

        current_datetime = datetime.now(pytz.utc)
        res =[]
        if self.menu_items:
            for item in self.menu_items:
                if item['start']<=current_datetime and item['end']>=current_datetime:
                    res.append(item)

        return res

    def _get_next_events(self):
        #returns all the events that are not running, 
        # if they are at the same time, then shows 
        # all therwise only 1.
        current_datetime = datetime.now(pytz.utc)
        res =[]
        start_time = None
        if self.menu_items:
            for item in self.menu_items:
                if item['start']>=current_datetime:
                    if not start_time:
                        start_time = item['start']
                        res.append(item)
                    else:
                        if start_time == item['start']:
                            res.append()
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
                hours, minutes, seconds = self._time_left(event['end'], current_datetime, True)
                title +=f" {event['summary'][:20]}: {hours:02d}:{minutes:02d}:{seconds:02d} left"
                i_current_events +=1
                # separated with comma if more than one
                if i_current_events < len_current_events:
                    title+=", "
          
            len_next_events = len(next_events)
            i_next_events = 0
            # then a pipe, if there's current and upcoming
            if len_current_events and len_next_events:
                title += " | "
            # and upcoming with thime left before the start
            for event in next_events:
                hours, minutes = self._time_left(event['start'], current_datetime)
                title +=f"{event['summary']}: in {hours:02d}:{minutes:02d}"
                i_next_events +=1
                if i_next_events < len_next_events:
                    title+=", "
            self.title = title
        else:
            self.title = f"-"
        
    
    def _str_event_menu_current(self, element):
        # create the items in the menu. util function
        current_datetime = datetime.now(pytz.utc)
        if element['start']> current_datetime:
            hours, minutes = self._time_left(element['start'], current_datetime)
            time_left_str =f" in {hours:02d}:{minutes:02d}"
        else:
            if element['start']< current_datetime:
                hours, minutes = self._time_left(element['end'], current_datetime)
                time_left_str = f" {hours:02d}:{minutes:02d} left"
        return f"{element['summary'][:20]} {time_left_str}"

    def _str_event_menu_next(self,element):
        #same but for upcoming eents.
        current_datetime = datetime.now(pytz.utc)
        if element:
            hours, minutes = self._time_left(element['start'], current_datetime)
            title += f" [{element['summary'][:20]} in {hours:02d}:{minutes:02d}]"
            return title
        else:
            return ""

    @rumps.timer(60) 
    def send_notification_(self, _):
        
        if self.menu_items:
            current_datetime = datetime.now(pytz.utc)
            current_events = self._get_current_events()
            for event in current_events:
                hours, minutes= self._time_left(event['end'],current_datetime)
                # send a notification 5 min before the end that event it's almost over
                if hours == 0 and minutes == 5:
                    rumps.notification(
                    title="5 minutes left",
                    subtitle="Just 5",
                    message="I said 5 mins left",
                    sound=True
                )
                # and when it's over
                if hours == 0 and  minutes == 0:
                    rumps.notification(
                    title="It's over",
                    subtitle="It's over",
                    message="It's over",
                    sound=True
                )

    @rumps.timer(60) 
    def send_open_1_min(self, _):
        # 1 min beofre the meeting it opens the browser with the link
        # you can't miss it. 
        if self.menu_items:
            current_datetime = datetime.now(pytz.utc)
            next_events = self._get_next_events()
            for event in next_events:
                horus, minutes= self._time_left(event['start'],current_datetime)
                if horus==0 and minutes == 1:
                    if event['url']:
                        rumps.notification(
                            title="It's meeting time",
                            subtitle=f"{event['summary']}",
                            message=f"{event['summary']}",
                            sound=True
                        )
                        webbrowser.open(event['url'])

    
    @rumps.clicked("Quit")
    def quit(self,_):
        print('over')
        rumps.quit_application()

if __name__ == "__main__":
    app = Vince()
    app.run()

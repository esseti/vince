[1.2.0] 2024-06-05
- Added support for chrome meet app to open the meet app link (pedro request).
    To enable this feature, follow these steps:
    1. Locate the Google Meet app on your system. It's typically found at this path: `/Users/YOUR_USER/Applications/Chrome\ Apps.localized/Google\ Meet.app`.
    2. Copy this path and replace any single backslash `\` with a double backslash `\\`. The modified path should look like this: `/Users/YOUR_USER/Applications/Chrome\\ Apps.localized/Google\\ Meet.app`.
    3. Paste this modified path into the settings under the `app_meet` field.
    4. Once done, any Google Meet link will trigger the app to open.

    Please note a known limitation: The app does not automatically open the meeting link. You will need to manually enter the meeting ID or select the meeting from your event list on the right side of the app.

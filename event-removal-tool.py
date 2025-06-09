from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
import os
from datetime import datetime, timezone

# Calendar API scope
SCOPES = ['https://www.googleapis.com/auth/calendar']
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")

# Load credentials and return a Google Calendar service object
def google_calendar_service():
    creds = None
    TOKEN_PATH = os.getenv('GOOGLE_TOKEN_PATH')
    
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(os.getenv("GOOGLE_CREDENTIALS_PATH"), SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())
    
    return build('calendar', 'v3', credentials=creds)

# Fetch all events from a calendar (with pagination)
def get_all_events(service, calendar_id):
    events = []
    page_token = None

    while True:
        response = service.events().list(calendarId=calendar_id, pageToken=page_token).execute()
        events.extend(response.get('items', []))
        page_token = response.get('nextPageToken')
        if not page_token:
            break

    return events

# Clear all events from a calendar
def clear_calendar(calendar_id='primary'):
    service = google_calendar_service()
    events = get_all_events(service, calendar_id)

    print(f"Found {len(events)} events. Starting deletion...")

    deleted = 0
    for event in events:
        try:
            service.events().delete(calendarId=calendar_id, eventId=event['id']).execute()
            print(f"Deleted event: {event.get('summary', 'No Title')}")
            deleted += 1
        except Exception as e:
            print(f"Failed to delete event {event.get('summary', 'No Title')}: {e}")

    print(f"✅ Finished. Successfully deleted {deleted} events from calendar '{calendar_id}'.")

# Run it
if __name__ == "__main__":
    # Replace with your calendar ID or use 'primary'
    clear_calendar(calendar_id)

import requests
import datetime
import os
import time
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from google.oauth2 import service_account
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/calendar']
calendar_id = os.getenv("GOOGLE_CALENDAR_ID")

GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS_PATH")
Token_Path = os.getenv("GOOGLE_TOKEN_PATH")
ACCOUNT_TYPE = os.getenv("GOOGLE_ACCOUNT_TYPE", "service_account").lower()

def google_calendar_service():
    creds = None
    if ACCOUNT_TYPE == "service_account":
        # Fallback to service account
        try:
            creds = service_account.Credentials.from_service_account_file(
                GOOGLE_CREDENTIALS, scopes=SCOPES
            )
            print("✅ Service account credentials loaded from", GOOGLE_CREDENTIALS)
            return build('calendar', 'v3', credentials=creds)
        except Exception as e:
            print("❌ Failed to load service account credentials:", e)
    else:
        # Try user token
        if os.path.exists(Token_Path):
            try:
                creds = Credentials.from_authorized_user_file(Token_Path, SCOPES)
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                    print("🔄 Access token refreshed.")
                if creds and creds.valid:
                    print("✅ Token loaded successfully from user credentials at", Token_Path)
                    return build('calendar', 'v3', credentials=creds)
                else:
                    print("❌ Token is invalid or expired without refresh token.")
            except Exception as e:
                print("❌ Failed to load user token:", e)

        # Final fallback — prompt user login
        print("🔓 Prompting for manual authentication...")
        flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_CREDENTIALS, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(Token_Path, 'w') as token:
            token.write(creds.to_json())
        print("✅ Token saved to", Token_Path)

        return build('calendar', 'v3', credentials=creds)


def find_event_by_id(service, calendar_id, event_id):
    now = datetime.datetime.utcnow().isoformat() + 'Z'
    events_result = service.events().list(calendarId=calendar_id, maxResults=1000, singleEvents=True).execute()
    events = events_result.get('items', [])

    for event in events:
        if event.get('description') == event_id:
            return event
    return None

def add_or_update_event(service, calendar_id, title, start, end, class_id, activity_id):
    # Extract the event ID from the title
    event_id = f"{class_id},{activity_id}"

    existing_event = find_event_by_id(service, calendar_id, event_id)
    # print(existing_event)

    if existing_event:
        existing_start = existing_event['start']['dateTime']
        existing_end = existing_event['end']['dateTime']

        if existing_start != start or existing_end != end:
            existing_event['start']['dateTime'] = start
            existing_event['end']['dateTime'] = end
            updated_event = service.events().update(calendarId=calendar_id, eventId=existing_event['id'], body=existing_event).execute()
            print(f"✅ Updated: {title}")
        else:
            print(f"✅ Already exists and up-to-date: {title}")
    else:
        event = {
            'summary': title,
            'description': event_id,  # Use the event ID for tracking
            'start': {'dateTime': start, 'timeZone': 'Asia/Bangkok'},
            'end': {'dateTime': end, 'timeZone': 'Asia/Bangkok'},
        }
        service.events().insert(calendarId=calendar_id, body=event).execute()
        print(f"➕ Created: {title}")

def load_class_info():
    """Load class information from environment variables."""
    class_info_str = os.getenv("CLASS_INFO")
    class_names = {}

    if class_info_str:
        class_info_parts = class_info_str.split(',')
        # Process pairs of id and name
        for i in range(0, len(class_info_parts), 2):
            if i + 1 < len(class_info_parts):
                try:
                    class_id = int(class_info_parts[i])
                    class_name = class_info_parts[i + 1]
                    class_names[class_id] = class_name
                except ValueError:
                    print(f"❌ Invalid class ID format: {class_info_parts[i]}")
    else:
        print("❌ CLASS_INFO not found in environment variables")
        exit(1)

    print(f"📋 Loaded {len(class_names)} classes from environment variables")
    return class_names

def get_headers():
    """Load headers from environment variables."""
    return {
        "x-csrf-token": os.getenv("CSRF_TOKEN"),
        "x-requested-with": "XMLHttpRequest",
        "accept": "application/json",
        "cookie": os.getenv("COOKIE")
    }

def get_student_id():
    """Get student ID from environment variables."""
    student_id = os.getenv("STUDENT_ID")
    if not student_id:
        print("❌ STUDENT_ID not found in environment variables")
        exit(1)
    return student_id

def get_activities_url():
    """Get activities URL from environment variables."""
    activities_url = os.getenv("ACTIVITIES_URL")
    if not activities_url:
        print("❌ ACTIVITIES_URL not found in environment variables")
        exit(1)
    return activities_url

def fetch_activities(class_id, student_id, headers, activities_url):
    """Fetch activities for a specific class."""
    print(f"\n📦 Fetching activities for class_id: {class_id}")
    
    params = {
        "class_id": str(class_id),
        "student_id": student_id,
        "filter_groups[0][filters][0][key]": "class_id",
        "filter_groups[0][filters][0][value]": str(class_id),
        "sort[]": ["sequence", "id"],
        "select[]": [
            "activities:id,user_id,class_id,adv_starred,group_type,type,peer_assessment,is_allow_repeat,title,description,start_date,due_date,edit_group_mode,created_at",
            "user:id,firstname_en,lastname_en,firstname_th,lastname_th"
        ],
        "includes[]": ["user:sideload", "fileactivities:ids", "questions:ids"]
    }
        
    response = requests.get(
        activities_url,
        headers=headers,
        params=params
    )

    if response.status_code == 200:
        return response.json().get("activities", [])
    else:
        print(f"❌ Failed to fetch activities: {response.status_code}")
        return []

def process_activities(activities, class_id, class_name, calendar_service, calendar_id):
    """Process activities and add/update calendar events."""
    for activity in activities:
        title = activity.get("title", "Untitled")
        activity_id = activity.get("id", "Unknown ID")
        
        title = f"{class_name} - {title}"
        start_date = activity.get("start_date")
        due_date = activity.get("due_date") or None

        if start_date and due_date:
            start = datetime.datetime.strptime(start_date, "%Y-%m-%d %H:%M:%S").isoformat()
            end = datetime.datetime.strptime(due_date, "%Y-%m-%d %H:%M:%S").isoformat()

            add_or_update_event(calendar_service, calendar_id, title, start, end, class_id, activity_id)

def get_activities():
    # Load data from environment variables
    headers = get_headers()
    class_names = load_class_info()
    class_ids = list(class_names.keys())
    student_id = get_student_id()
    activities_url = get_activities_url()
    
    # Initialize Google Calendar service
    calendar_service = google_calendar_service()

    # Process each class
    for class_id in class_ids:
        activities = fetch_activities(class_id, student_id, headers, activities_url)
        class_name = class_names.get(class_id, "Unknown Class")
        process_activities(activities, class_id, class_name, calendar_service, calendar_id)
        time.sleep(5)

if __name__ == "__main__":
    get_activities()

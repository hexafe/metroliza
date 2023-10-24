from datetime import datetime

current_time = datetime.now()
formatted_time = current_time.strftime("%y%m%d.%H%M")

# VERSION_DATE = formatted_time
VERSION_DATE = "231024"

release_notes = f"""
    <h2>Version {VERSION_DATE}:</h2>
    - Export: changed default chart type to line,<br>
    - Export: added conditional formating if NOK% > 0,<br>
    - Added release notes (you can see it right now :)),<br>
    """
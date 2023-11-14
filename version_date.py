from datetime import datetime

current_time = datetime.now()
formatted_time = current_time.strftime("%y%m%d.%H%M")

# VERSION_DATE = formatted_time
VERSION_DATE = "231114"

release_notes = f"""
    <br><b>Current Version 231114:</b><br>
    - Export: added USL, LSL, mean annotations to histogram<br>

    <br><b>Version 231111:</b><br>
    - Export: added selection of sorting mesurements by Date or Sample #<br>
    - WIP: added option to generate summary sheet with plots (scatter plot, histogram and basic statistics)<br>
    - Minor bugfixes<br>
    
    <br><b>Version 231025:</b><br>
    - Export: added list of selected headers to filtering window<br>
    - Export: added option to hide columns with OK results<br>

    <br><b>Version 231024:</b><br>
    - Export: changed default chart type to line<br>
    - Export: added conditional formating if NOK% > 0<br>
    - Added release notes (you can see it right now :))<br>
    """
    
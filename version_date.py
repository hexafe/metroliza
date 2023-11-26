from datetime import datetime

current_time = datetime.now()
formatted_time = current_time.strftime("%y%m%d.%H%M")

# VERSION_DATE = formatted_time
VERSION_DATE = "231126"

release_notes = f"""
    <br><b>Current Version 231126:</b><br>
    - Added tooltips with basic information when hovering the mouse cursor<br>
    - Code refactoring/optimization<br>
    - Export: added grouping of samples<br>

    <br><b>Version 231122:</b><br>
    - Improved logging<br>

    <br><b>Version 231121:</b><br>
    - Added logging<br>

    <br><b>Version 231120:</b><br>
    - Bugfix: crash when exporting without specifying min samplesize for violin plot in some cases<br>

    <br><b>Version 231115:</b><br>
    - Export: added option to choose min samplesize to determine if violin or scatter plot should be used<br>
    
    <br><b>Version 231114:</b><br>
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
    
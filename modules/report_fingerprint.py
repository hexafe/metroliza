
def build_report_fingerprint(report):
    """Build a dedupe fingerprint from DB row or parser-like object."""
    report_id = report.get('ID')
    if report_id is not None:
        return f"id:{report_id}"

    parts = [
        report.get('REFERENCE') or '',
        report.get('FILELOC') or '',
        report.get('FILENAME') or '',
        report.get('DATE') or '',
        report.get('SAMPLE_NUMBER') or '',
    ]
    return "|".join(str(part) for part in parts)


def build_parser_fingerprint(cmm_report):
    return build_report_fingerprint({
        'REFERENCE': cmm_report.pdf_reference,
        'FILELOC': cmm_report.pdf_file_path,
        'FILENAME': cmm_report.pdf_file_name,
        'DATE': cmm_report.pdf_date,
        'SAMPLE_NUMBER': cmm_report.pdf_sample_number,
    })

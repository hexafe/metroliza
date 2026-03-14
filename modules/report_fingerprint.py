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


def _get_attr(obj, primary, fallback):
    return getattr(obj, primary, getattr(obj, fallback, ''))


def build_parser_fingerprint(report_parser):
    return build_report_fingerprint(
        {
            'REFERENCE': _get_attr(report_parser, 'reference', 'pdf_reference'),
            'FILELOC': _get_attr(report_parser, 'file_path', 'pdf_file_path'),
            'FILENAME': _get_attr(report_parser, 'file_name', 'pdf_file_name'),
            'DATE': _get_attr(report_parser, 'date', 'pdf_date'),
            'SAMPLE_NUMBER': _get_attr(report_parser, 'sample_number', 'pdf_sample_number'),
        }
    )

"""Early streaming cancellation must not trigger a full-snapshot fallback."""

from contextlib import closing
import sqlite3
from unittest.mock import Mock

import pandas as pd
import pytest

from metroliza.exporting import export_data_thread
from metroliza.exporting.contracts import AppPaths, ExportOptions, ExportRequest
from metroliza.exporting.execution import ExportOutcomeKind
from metroliza.exporting.export_backends import ExcelExportBackend
from metroliza.exporting.export_outcomes import ExportRunStatus


@pytest.mark.parametrize('rows', [[], [('text',), (1,)]], ids=['empty', 'unsupported'])
def test_stream_measurements_sheet_fallback_requires_no_cancellation(
    rows, tmp_path, monkeypatch, qapplication_session,
):
    print(f'Export source: {export_data_thread.__file__}')
    monkeypatch.setenv('METROLIZA_EXPORT_BULK_WRITE', '1')
    with closing(sqlite3.connect(':memory:')) as connection:
        connection.execute('CREATE TABLE snapshot (VALUE)')
        connection.executemany('INSERT INTO snapshot VALUES (?)', rows)
        for cancel in (False, True):
            # The cancelled run always has rows available, even for the empty control.
            if cancel and not rows:
                connection.execute('INSERT INTO snapshot VALUES (1)')
            target = tmp_path / ('cancelled.xlsx' if cancel else 'control.xlsx')
            if cancel:
                target.write_bytes(b'previous complete export')
            thread = export_data_thread.ExportDataThread(ExportRequest(
                paths=AppPaths(db_file='unused.db', excel_file=str(target)),
                options=ExportOptions(generate_summary_sheet=False),
            ))
            backend = ExcelExportBackend()
            thread._active_backend = backend
            thread._db_connection = connection
            thread._snapshot_table_name = 'snapshot'
            thread._active_export_query = 'SELECT VALUE FROM snapshot'
            monkeypatch.setattr(thread, 'add_measurements_horizontal_sheet', Mock())
            monkeypatch.setattr(thread, '_run_group_analysis_outputs', Mock())
            fallback = Mock(return_value=pd.DataFrame(rows, columns=['VALUE']))
            monkeypatch.setattr(thread, '_build_export_filtered_dataframe', fallback)
            write_dataframe = Mock(wraps=thread.write_data_to_excel)
            monkeypatch.setattr(thread, 'write_data_to_excel', write_dataframe)
            cancelled_signals = []
            thread.canceled.connect(lambda: cancelled_signals.append(True))
            streamed_chunks = []
            stream_results = []
            original_stream = backend.write_streamed_rows

            def write_streamed_rows(writer, sheet_name, columns, row_chunks):
                # Streaming has begun, but the real iterator has not fetched yet.
                if cancel:
                    thread.stop_exporting()

                def observed_chunks():
                    for chunk in row_chunks:
                        streamed_chunks.append(chunk)
                        yield chunk

                result = original_stream(writer, sheet_name, columns, observed_chunks())
                stream_results.append(result)
                return result

            monkeypatch.setattr(backend, 'write_streamed_rows', write_streamed_rows)
            outcome = backend.run(thread)

            assert stream_results == [None]
            if cancel:
                fallback.assert_not_called()
                write_dataframe.assert_not_called()
                assert streamed_chunks == []
                assert outcome.kind is ExportOutcomeKind.CANCELED
                assert thread.export_run_result.status is ExportRunStatus.CANCELLED
                assert cancelled_signals == [True]
                assert target.read_bytes() == b'previous complete export'
                assert not list(tmp_path.glob('.cancelled.tmp-*.xlsx'))
            else:
                fallback.assert_called_once_with()
                write_dataframe.assert_called_once()
                assert write_dataframe.call_args.args[0] is fallback.return_value
                assert write_dataframe.call_args.args[1] == 'MEASUREMENTS'
                assert outcome.kind is ExportOutcomeKind.COMPLETED
                assert not thread.export_canceled
                assert cancelled_signals == []
                assert target.is_file()

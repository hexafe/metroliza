import pytest

from metroliza.industrial.oznak_adapter import _validate_raw_select_sql


@pytest.mark.parametrize(
    ("sql_text", "expected"),
    [
        ("SELECT event_id, reference FROM events", "SELECT event_id, reference FROM events"),
        (
            """
            WITH visible_events AS (
                SELECT event_id, reference
                FROM events
                WHERE status = 'queued'
            )
            SELECT event_id, reference
            FROM visible_events
            """,
            """
            WITH visible_events AS (
                SELECT event_id, reference
                FROM events
                WHERE status = 'queued'
            )
            SELECT event_id, reference
            FROM visible_events
            """.strip(),
        ),
        ("SELECT event_id, reference FROM events;", "SELECT event_id, reference FROM events"),
        (
            """
            SELECT event_id, ';' AS literal_semicolon
            FROM events
            WHERE note = 'operator entered ; during audit'
            -- comment with ;
            /* block comment with ; */
            """,
            """
            SELECT event_id, ';' AS literal_semicolon
            FROM events
            WHERE note = 'operator entered ; during audit'
            -- comment with ;
            /* block comment with ; */
            """.strip(),
        ),
    ],
)
def test_validate_raw_select_sql_accepts_single_read_only_selects(sql_text, expected):
    assert _validate_raw_select_sql(sql_text) == expected


@pytest.mark.parametrize(
    "sql_text",
    [
        "SELECT event_id FROM events; SELECT event_id FROM archived_events",
        "SELECT event_id FROM events; -- second statement hidden by trailing comment",
        "SELECT event_id FROM events /* comment */ ; /* trailing comment */",
    ],
)
def test_validate_raw_select_sql_rejects_semicolon_outside_literals_or_comments(sql_text):
    with pytest.raises(ValueError, match="one read-only statement"):
        _validate_raw_select_sql(sql_text)


@pytest.mark.parametrize(
    "sql_text",
    [
        "INSERT INTO events (event_id) VALUES (1)",
        "UPDATE events SET status = 'done'",
        "DELETE FROM events WHERE event_id = 1",
        "DROP TABLE events",
        "MERGE INTO events USING incoming ON events.event_id = incoming.event_id",
        "EXEC refresh_events",
        "CALL refresh_events()",
    ],
)
def test_validate_raw_select_sql_rejects_write_or_execution_statements(sql_text):
    with pytest.raises(ValueError):
        _validate_raw_select_sql(sql_text)


@pytest.mark.parametrize(
    "sql_text",
    [
        "SELECT event_id INTO scratch_events FROM events",
        """
        WITH visible_events AS (
            SELECT event_id
            FROM events
        )
        SELECT event_id INTO scratch_events FROM visible_events
        """,
        "SELECT event_id FROM events FOR UPDATE",
    ],
)
def test_validate_raw_select_sql_rejects_select_side_effect_forms(sql_text):
    with pytest.raises(ValueError):
        _validate_raw_select_sql(sql_text)

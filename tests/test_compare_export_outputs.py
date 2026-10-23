"""Strict artifact comparison and discriminating negative controls."""

from contextlib import closing
import sqlite3
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

import pytest

from scripts.compare_export_outputs import compare_outputs, main


CORE = (b'<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        b'xmlns:dcterms="http://purl.org/dc/terms/"><dcterms:created>TIME</dcterms:created>'
        b'<dcterms:modified>TIME</dcterms:modified><cp:revision>1</cp:revision></cp:coreProperties>')


def _xlsx(path, *, timestamp=b"2026-01-01T00:00:00Z", value=b"data", reverse=False, missing=False):
    members = [("docProps/core.xml", CORE.replace(b"TIME", timestamp)), ("xl/sharedStrings.xml", value)]
    if missing:
        members.pop()
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        for name, data in reversed(members) if reverse else members:
            archive.writestr(name, data)


@pytest.mark.parametrize("change", ["same", "time", "value", "missing", "order", "core", "path"])
def test_xlsx_contract(tmp_path, change):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    _xlsx(a, value=b"/synthetic/a.sqlite" if change == "path" else b"data")
    _xlsx(b, timestamp=b"2026-02-03T01:02:03Z" if change == "time" else b"2026-01-01T00:00:00Z",
          value=b"different" if change == "value" else b"/synthetic/b.sqlite" if change == "path" else b"data",
          missing=change == "missing", reverse=change == "order")
    if change == "core":
        with ZipFile(b, "w") as archive:
            archive.writestr("docProps/core.xml", CORE.replace(b"TIME", b"2026-01-01T00:00:00Z").replace(
                b"<cp:revision>1", b"<cp:revision>2"))
            archive.writestr("xl/sharedStrings.xml", b"data")
    difference = compare_outputs(a, b)
    assert (difference is None) == (change in {"same", "time"})


def test_html_generated_timestamp_only(tmp_path):
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    content = ('<script>{"generated_at":"2026-01-01T00:00:00Z"}</script>'
               '<dt>Generated at</dt><dd><time datetime="2026-01-01T00:00:00Z">2026-01-01T00:00:00Z</time></dd>'
               '<td>2025-01-01T12:00:00Z</td>')
    a.write_text(content)
    b.write_text(content.replace("2026-01-01T00:00:00Z", "2026-02-03T01:02:03Z"))
    assert compare_outputs(a, b) is None
    b.write_text(content.replace("2025-01-01T12:00:00Z", "2025-01-02T12:00:00Z"))
    assert compare_outputs(a, b)


def test_sqlite_primary_key_order_and_value_differences(tmp_path):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    for path, rows in ((a, [(2, "b"), (1, "a")]), (b, [(1, "a"), (2, "b")])):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY, value TEXT)")
            connection.executemany("INSERT INTO data VALUES (?, ?)", rows)
            connection.commit()
    assert compare_outputs(a, b, sqlite=True) is None
    with closing(sqlite3.connect(b)) as connection:
        connection.execute("UPDATE data SET value='changed' WHERE id=2")
        connection.commit()
    assert "row 1" in compare_outputs(a, b, sqlite=True)


@pytest.mark.parametrize("wal_state", ["closed", "committed_same", "committed_different"])
def test_sqlite_comparison_preserves_source_family_and_committed_wal(tmp_path, wal_state):
    from contextlib import ExitStack
    import hashlib
    import shutil

    def inventory():
        return {str(path.relative_to(tmp_path)): hashlib.sha256(path.read_bytes()).hexdigest()
                for root in roots for path in root.iterdir()}

    roots = [tmp_path / side for side in ("a", "b")]
    paths = []
    with ExitStack() as stack:
        for index, root in enumerate(roots):
            root.mkdir()
            path = root / "data.sqlite"
            paths.append(path)
            connection = stack.enter_context(closing(sqlite3.connect(path)))
            assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
            connection.execute("PRAGMA wal_autocheckpoint=0")
            connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY, value TEXT)")
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            value = "changed" if index == 1 and wal_state == "committed_different" else "same"
            connection.execute("INSERT INTO data VALUES (1, ?)", (value,))
            connection.commit()
            if wal_state == "closed":
                connection.close()
                assert not path.with_name(path.name + "-wal").exists()
            else:
                assert path.with_name(path.name + "-wal").stat().st_size > 0
                # The main file alone lacks the committed row, so the oracle must read the WAL.
                main_only = tmp_path / f"main-only-{index}.sqlite"
                shutil.copyfile(path, main_only)
                with closing(sqlite3.connect(main_only)) as checkpointed:
                    assert checkpointed.execute("SELECT * FROM data").fetchall() == []
        before = inventory()
        difference = compare_outputs(*paths, sqlite=True)
        assert bool(difference) == (wal_state == "committed_different")
        assert inventory() == before


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sqlite_family_copy_does_not_hide_extra_sidecar_filenames(tmp_path, suffix):
    roots = [tmp_path / side for side in ("a", "b")]
    for root in roots:
        root.mkdir()
        with closing(sqlite3.connect(root / "data.sqlite")) as connection:
            connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY)")
            connection.commit()
    (roots[0] / ("data.sqlite" + suffix)).write_bytes(b"")
    assert compare_outputs(*roots, sqlite=True) == "output file names differ"


def test_sqlite_family_change_during_copy_fails_closed(tmp_path, monkeypatch):
    from scripts import compare_export_outputs as comparator

    path = tmp_path / "data.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY)")
        connection.commit()
    original = comparator.shutil.copyfile

    def changing_copy(source, destination):
        result = original(source, destination)
        path.with_name(path.name + "-wal").write_bytes(b"new concurrent WAL")
        return result

    monkeypatch.setattr(comparator.shutil, "copyfile", changing_copy)
    with pytest.raises(ValueError, match="input family changed during copy"):
        compare_outputs(path, path, sqlite=True)


def test_cli_fails_closed_for_errors_missing_and_empty(tmp_path, capsys):
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    assert main([str(a), str(b)]) == 2
    a.write_bytes(b"invalid")
    b.write_bytes(b"invalid")
    assert main([str(a), str(b)]) == 2
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    assert main([str(left), str(right)]) == 2
    (left / "data.txt").write_text("same")
    assert main([str(left), str(right)]) == 1
    (right / "data.txt").write_text("same")
    assert main([str(left), str(right)]) == 0
    assert "outputs equal" in capsys.readouterr().out


def test_sqlite_catalog_identifiers_cannot_change_query_structure(tmp_path):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    for path in (a, b):
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('CREATE TABLE "odd""; DROP TABLE guard; --" '
                               '("key"" name" INTEGER PRIMARY KEY, "value with space" TEXT)')
            connection.execute('INSERT INTO "odd""; DROP TABLE guard; --" VALUES (1, ?)', ("exact",))
            connection.execute("CREATE TABLE guard(id INTEGER PRIMARY KEY)")
            connection.execute("INSERT INTO guard VALUES (42)")
            connection.commit()
    assert compare_outputs(a, b, sqlite=True) is None
    with closing(sqlite3.connect(b)) as connection:
        connection.execute('UPDATE "odd""; DROP TABLE guard; --" SET "value with space"=?', ("changed",))
        connection.commit()
    assert "row 0 differs" in compare_outputs(a, b, sqlite=True)
    for path in (a, b):
        with closing(sqlite3.connect(path)) as connection:
            assert connection.execute("SELECT * FROM guard").fetchall() == [(42,)]


def _dashboard_pair(tmp_path, stem="export_dashboard"):
    outputs = []
    for side, token in (("a", "a" * 32), ("b", "b" * 32)):
        root = tmp_path / side
        root.mkdir()
        directory = root / (f"{stem}_assets.generation-" + token)
        directory.mkdir()
        (directory / "chart.png").write_bytes(b"exact PNG bytes")
        (directory / "plotly.js").write_bytes(b"exact bundled JavaScript bytes")
        html = root / f"{stem}.html"
        html.write_text(f'<script src="{directory.name}/plotly.js" defer></script>'
                        f'<button data-image-src="{directory.name}/chart.png">'
                        f'<img src="{directory.name}/chart.png"></button>')
        outputs.append((root, html, directory))
    return outputs


@pytest.mark.parametrize("stem", ["export_dashboard", "export"])
def test_paired_dashboard_generations_compare_with_exact_assets(tmp_path, stem):
    a, b = _dashboard_pair(tmp_path, stem)
    assert compare_outputs(a[0], b[0]) is None
    assert compare_outputs(a[1], b[1]) is None


@pytest.mark.parametrize("attribute", ["data.src", ".src", "other:src", "data-src", "src.extra"])
@pytest.mark.parametrize("genuine_src", [False, True])
@pytest.mark.parametrize("stem", ["export_dashboard", "export"])
def test_unsupported_attribute_names_remain_literal(tmp_path, attribute, genuine_src, stem):
    a, b = _dashboard_pair(tmp_path, stem)
    for _root, document, generation in (a, b):
        reference = f'{generation.name}/plotly.js'
        accepted = f' src="{reference}"' if genuine_src else ""
        document.write_text(f'<script{accepted} {attribute}="{reference}"></script>')
    assert compare_outputs(a[0], b[0])
    assert compare_outputs(a[1], b[1])


@pytest.mark.parametrize("object_type", ["index", "view", "trigger"])
def test_sqlite_removed_integrity_schema_object_is_a_difference(tmp_path, object_type):
    a, b = tmp_path / "a.sqlite", tmp_path / "b.sqlite"
    for path in (a, b):
        with closing(sqlite3.connect(path)) as connection:
            connection.executescript("""
                CREATE TABLE data(id INTEGER PRIMARY KEY, value TEXT);
                CREATE UNIQUE INDEX unique_value ON data(value);
                CREATE VIEW data_view AS SELECT value FROM data;
                CREATE TRIGGER guard_value BEFORE INSERT ON data
                    WHEN NEW.value IS NULL BEGIN SELECT RAISE(ABORT, 'missing'); END;
                INSERT INTO data VALUES (1, 'same');
            """)
            connection.commit()
    assert compare_outputs(a, b, sqlite=True) is None
    statements = {"index": "DROP INDEX unique_value", "view": "DROP VIEW data_view",
                  "trigger": "DROP TRIGGER guard_value"}
    with closing(sqlite3.connect(b)) as connection:
        connection.execute(statements[object_type])
        connection.commit()
    assert compare_outputs(a, b, sqlite=True)


@pytest.mark.parametrize("change", [
    "text", "other_attribute", "script", "comment", "wrong_tag", "link", "asset_bytes", "asset_token",
    "missing_asset", "extra_asset", "renamed_asset", "extra_generation", "both_extra_generations",
    "alternate_generation", "both_alternate_generations",
    "missing_generation", "both_missing_generations", "moved_generation", "wrong_reference", "empty_assets",
])
@pytest.mark.parametrize("stem", ["export_dashboard", "export"])
def test_dashboard_generation_exception_is_location_and_content_bound(tmp_path, change, stem):
    import shutil

    a, b = _dashboard_pair(tmp_path, stem)
    if change in {"text", "other_attribute", "script", "comment", "wrong_tag", "link"}:
        templates = {"text": "<p>{}</p>", "other_attribute": '<div data-note="{}"></div>',
                     "script": '<script>const diagnostic="{}";</script>', "comment": "<!-- {} -->",
                     "wrong_tag": '<div src="{}/chart.png"></div>', "link": '<a href="{}/chart.png">asset</a>'}
        for _root, document, generation in (a, b):
            document.write_text(document.read_text() + templates[change].format(generation.name))
    elif change == "asset_bytes":
        (b[2] / "chart.png").write_bytes(b"changed PNG pixels")
    elif change == "asset_token":
        for _root, _document, generation in (a, b):
            (generation / "chart.png").write_text(generation.name)
    elif change == "missing_asset":
        (b[2] / "chart.png").unlink()
    elif change == "extra_asset":
        (b[2] / "extra.png").write_bytes(b"extra")
    elif change == "renamed_asset":
        (b[2] / "chart.png").rename(b[2] / "renamed.png")
        b[1].write_text(b[1].read_text().replace("chart.png", "renamed.png"))
    elif change in {"extra_generation", "both_extra_generations",
                    "alternate_generation", "both_alternate_generations"}:
        both = change in {"both_extra_generations", "both_alternate_generations"}
        extra_stem = ("export" if stem == "export_dashboard" else "export_dashboard") if (
            change in {"alternate_generation", "both_alternate_generations"}
        ) else stem
        for root, _document, _generation in ((a, b) if both else (b,)):
            extra = root / (f"{extra_stem}_assets.generation-" + "c" * 32)
            extra.mkdir()
            (extra / "chart.png").write_bytes(b"extra")
    elif change in {"missing_generation", "both_missing_generations"}:
        for _root, _document, generation in ((a, b) if change == "both_missing_generations" else (b,)):
            shutil.rmtree(generation)
    elif change == "moved_generation":
        (b[0] / "nested").mkdir()
        b[2].rename(b[0] / "nested" / b[2].name)
        b[1].write_text(b[1].read_text().replace(b[2].name, "nested/" + b[2].name))
    elif change == "wrong_reference":
        b[1].write_text(b[1].read_text().replace(b[2].name, f"{stem}_assets.generation-" + "d" * 32))
    else:
        for _root, _document, generation in (a, b):
            for path in generation.iterdir():
                path.unlink()
    assert main([str(a[0]), str(b[0])]) != 0


@pytest.mark.parametrize("stem", ["export_dashboard", "export"])
def test_html_file_comparison_also_checks_asset_bytes(tmp_path, stem):
    a, b = _dashboard_pair(tmp_path, stem)
    (b[2] / "chart.png").write_bytes(b"different")
    assert compare_outputs(a[1], b[1])


@pytest.mark.parametrize("stem", ["export_dashboard", "export"])
def test_generation_pattern_elsewhere_is_compared_literally(tmp_path, stem):
    a, b = _dashboard_pair(tmp_path, stem)
    suffix = '<p>generation-' + "c" * 32 + '</p><div data-note="generation-' + "c" * 32 + '"></div>'
    for _root, document, _generation in (a, b):
        document.write_text(document.read_text() + suffix)
    assert compare_outputs(a[0], b[0]) is None
    b[1].write_text(b[1].read_text().replace("c" * 32, "d" * 32))
    assert compare_outputs(a[0], b[0])


def test_dashboard_asset_base_name_remains_literal_across_paired_generations(tmp_path):
    a, b = _dashboard_pair(tmp_path)
    other = b[2].with_name(b[2].name.replace("export_dashboard_assets", "export_assets"))
    b[2].rename(other)
    b[1].write_text(b[1].read_text().replace(b[2].name, other.name))
    assert main([str(a[0]), str(b[0])]) != 0
    assert main([str(a[1]), str(b[1])]) != 0


@pytest.mark.parametrize("kind", ["xlsx", "html", "html_only", "sqlite"])
@pytest.mark.parametrize("temp_scope", [False, True])
def test_independently_generated_baseline_controls_use_the_same_oracle(tmp_path, kind, capsys, temp_scope):
    if kind in {"html", "html_only"}:
        left, right = _dashboard_pair(tmp_path, "export" if kind == "html_only" else "export_dashboard")
        paths = (left[0], right[0])
    elif kind == "xlsx":
        paths = (tmp_path / "a.xlsx", tmp_path / "b.xlsx")
        _xlsx(paths[0], timestamp=b"2026-01-01T00:00:00Z")
        _xlsx(paths[1], timestamp=b"2026-02-01T00:00:00Z")
    else:
        paths = (tmp_path / "a.sqlite", tmp_path / "b.sqlite")
        for path in paths:
            with closing(sqlite3.connect(path)) as connection:
                connection.execute("CREATE TABLE data(id INTEGER PRIMARY KEY, value TEXT)")
                connection.execute("INSERT INTO data VALUES (1, 'independent')")
                connection.commit()
    arguments = [str(path) for path in paths] + ["--baseline-control", "--sqlite"]
    if temp_scope:
        arguments += ["--csv-summary-temp-root", "/recorded/temp"]
    assert main(arguments) == 0
    assert "baseline control: outputs equal" in capsys.readouterr().out
    if kind in {"html", "html_only"}:
        (right[2] / "chart.png").write_bytes(b"different")
    elif kind == "xlsx":
        _xlsx(paths[1], value=b"different")
    else:
        with closing(sqlite3.connect(paths[1])) as connection:
            connection.execute("UPDATE data SET value='different'")
            connection.commit()
    assert main(arguments) == 1


SHEET_NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'


def _csv_summary_members(root, nonce='a1b2c3d4', *, separator='/'):
    from html import escape

    context = {'row_count': 3, 'source_file_count': 1,
               'sqlite_path': f'{root}{separator}metroliza_csv_summary_{nonce}.sqlite'}
    strings = ['severity', 'code', 'message', 'context', 'info',
               'tabular_sqlite_store_created', 'Loaded rows.', repr(context)]
    shared = (f'<sst xmlns="{SHEET_NS}" count="8" uniqueCount="8">' + ''.join(
        '<si><t>' + escape(text, quote=False) + '</t></si>' for text in strings) + '</sst>')
    rows = ''.join(f'<row r="{row}">' + ''.join(
        f'<c r="{column}{row}" t="s"><v>{index}</v></c>'
        for column, index in zip('ABCD', indices)) + '</row>'
        for row, indices in ((1, range(4)), (3, range(4, 8))))
    return {
        'xl/workbook.xml': (f'<workbook xmlns="{SHEET_NS}" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Diagnostics" sheetId="1" r:id="rId1"/></sheets></workbook>').encode(),
        'xl/_rels/workbook.xml.rels': (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/>'
            '</Relationships>').encode(),
        'xl/worksheets/sheet1.xml': f'<worksheet xmlns="{SHEET_NS}"><sheetData>{rows}</sheetData></worksheet>'.encode(),
        'xl/worksheets/sheet2.xml': f'<worksheet xmlns="{SHEET_NS}"><sheetData/></worksheet>'.encode(),
        'xl/sharedStrings.xml': shared.encode(),
        'xl/charts/chart1.xml': b'<chart>literal</chart>',
        'docProps/core.xml': CORE.replace(b'TIME', b'2026-01-01T00:00:00Z'),
    }


def _write_csv_summary(path, members):
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.mark.parametrize('change', ['same', 'nonce', 'root', 'context', 'chart'])
def test_csv_summary_default_remains_literal(tmp_path, change):
    left, right = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    a = _csv_summary_members('/recorded/temp')
    b = _csv_summary_members('/different/temp' if change == 'root' else '/recorded/temp',
                             'd4c3b2a1' if change == 'nonce' else 'a1b2c3d4')
    if change == 'context':
        b['xl/sharedStrings.xml'] = b['xl/sharedStrings.xml'].replace(b"'row_count': 3", b"'row_count': 4")
    if change == 'chart':
        b['xl/charts/chart1.xml'] = b'<chart>changed</chart>'
    _write_csv_summary(left, a)
    _write_csv_summary(right, b)
    assert (compare_outputs(left, right) is None) == (change == 'same')


def test_csv_summary_temp_scope_is_opt_in_and_directory_cli_propagates(tmp_path, capsys):
    roots = [tmp_path / side for side in ('a', 'b')]
    for root, nonce in zip(roots, ('a1b2c3d4', 'd4c3b2a1')):
        root.mkdir()
        _write_csv_summary(root / 'summary.xlsx', _csv_summary_members('/recorded/temp', nonce))
    assert compare_outputs(*roots)
    assert compare_outputs(*roots, csv_summary_temp_root=tmp_path)
    assert compare_outputs(*roots, csv_summary_temp_root='/recorded/temp') is None
    assert main([str(root) for root in roots] + ['--csv-summary-temp-root', '/recorded/temp']) == 0
    assert 'outputs equal' in capsys.readouterr().out


@pytest.mark.parametrize('change', [
    'wrong_code', 'wrong_sheet', 'wrong_header', 'duplicate_header', 'duplicate_code', 'duplicate_sheet',
    'duplicate_relationship', 'duplicate_cell', 'rich', 'inline', 'reuse_same_sheet', 'reuse_other_sheet',
    'row_count', 'source_count', 'extra_field', 'field_type', 'duplicate_field', 'count', 'index',
    'sheet_bytes', 'other_entry', 'other_diagnostic', 'chart', 'core', 'root', 'prefix', 'suffix', 'nonce_short', 'nonce_long',
    'nonce_upper', 'nonce_punctuation', 'two_tokens', 'order', 'renamed', 'outside_worksheet_target',
])
def test_csv_summary_exception_rejects_outside_named_scope(tmp_path, change):
    a = _csv_summary_members('/recorded/temp')
    b = _csv_summary_members('/recorded/temp', 'd4c3b2a1')
    sst, sheet = 'xl/sharedStrings.xml', 'xl/worksheets/sheet1.xml'
    scope_changes = {
        'wrong_code': (sst, b'tabular_sqlite_store_created', b'other_diagnostic'),
        'wrong_sheet': ('xl/workbook.xml', b'name="Diagnostics"', b'name="Other"'),
        'wrong_header': (sst, b'<t>code</t>', b'<t>Code</t>'),
        'duplicate_header': (sheet, b'</row>', b'<c r="E1" t="s"><v>1</v></c></row>'),
        'duplicate_code': (sheet, b'</sheetData>', b'<row r="4"><c r="B4" t="s"><v>5</v></c>'
                           b'<c r="D4" t="s"><v>7</v></c></row></sheetData>'),
        'duplicate_sheet': ('xl/workbook.xml', b'</sheets>', b'<sheet name="Diagnostics" '
                            b'sheetId="2" r:id="rId1"/></sheets>'),
        'duplicate_relationship': ('xl/_rels/workbook.xml.rels', b'</Relationships>',
            b'<Relationship Id="rId1" Target="worksheets/sheet2.xml"/></Relationships>'),
        'duplicate_cell': (sheet, b'</sheetData>', b'<row r="3"><c r="D3" t="s"><v>7</v></c></row></sheetData>'),
        'rich': (sst, b'<si><t>{', b'<si><r><t>{'),
        'inline': (sheet, b'<c r="D3" t="s"><v>7</v></c>', b'<c r="D3" t="inlineStr"><is><t>context</t></is></c>'),
        'reuse_same_sheet': (sheet, b'</sheetData>', b'<row r="4"><c r="D4" t="s"><v>7</v></c></row></sheetData>'),
        'reuse_other_sheet': ('xl/worksheets/sheet2.xml', b'<sheetData/>',
                             b'<sheetData><row r="1"><c r="A1" t="s"><v>7</v></c></row></sheetData>'),
        'extra_field': (sst, b"'row_count': 3", b"'extra': 1, 'row_count': 3"),
        'field_type': (sst, b"'row_count': 3", b"'row_count': True"),
        'duplicate_field': (sst, b"'row_count': 3", b"'row_count': 3, 'row_count': 3"),
        'prefix': (sst, b'metroliza_csv_summary_', b'other_csv_summary_'),
        'suffix': (sst, b'.sqlite', b'.db'),
    }
    if change in scope_changes:
        name, old, new = scope_changes[change]
        for members in (a, b):
            members[name] = members[name].replace(old, new, 1)
            if change == 'rich':
                members[sst] = members[sst].replace(b"}</t></si>", b"}</t></r></si>", 1)
    differences = {
        'row_count': (sst, b"'row_count': 3", b"'row_count': 4"),
        'source_count': (sst, b"'source_file_count': 1", b"'source_file_count': 2"),
        'count': (sst, b'count="8"', b'count="9"'),
        'index': (sheet, b'<v>7</v>', b'<v>6</v>'),
        'sheet_bytes': (sheet, b'<sheetData>', b'<sheetData >'),
        'root': (sst, b'/recorded/temp/', b'/recorded/sibling/'),
        'nonce_short': (sst, b'd4c3b2a1', b'd4c3b2a'),
        'nonce_long': (sst, b'd4c3b2a1', b'd4c3b2a10'),
        'nonce_upper': (sst, b'd4c3b2a1', b'D4c3b2a1'),
        'nonce_punctuation': (sst, b'd4c3b2a1', b'd4c3-2a1'),
        'two_tokens': (sst, b'd4c3b2a1.sqlite', b'd4c3b2a1.sqlite/metroliza_csv_summary_abcdefgh.sqlite'),
    }
    if change in differences:
        name, old, new = differences[change]
        b[name] = b[name].replace(old, new, 1)
    if change == 'other_entry':
        for members, nonce in ((a, b'a1b2c3d4'), (b, b'd4c3b2a1')):
            members[sst] = members[sst].replace(b'</sst>', b'<si><t>metroliza_csv_summary_' + nonce + b'.sqlite</t></si></sst>')
    if change == 'other_diagnostic':
        for members in (a, b):
            entry = members[sst][members[sst].index(b'<si><t>{'):-len(b'</sst>')]
            members[sst] = members[sst].replace(b'</sst>', entry + b'<si><t>other_code</t></si></sst>')
            members[sheet] = members[sheet].replace(b'</sheetData>', b'<row r="4"><c r="B4" t="s"><v>9</v></c><c r="D4" t="s"><v>8</v></c></row></sheetData>')
    if change in {'chart', 'core'}:
        name = 'xl/charts/chart1.xml' if change == 'chart' else 'docProps/core.xml'
        ending = b'</chart>' if change == 'chart' else b'</cp:coreProperties>'
        a[name] = a[name].replace(ending, b'metroliza_csv_summary_a1b2c3d4.sqlite' + ending)
        b[name] = b[name].replace(ending, b'metroliza_csv_summary_d4c3b2a1.sqlite' + ending)
    if change == 'order':
        b = dict(reversed(list(b.items())))
    if change == 'renamed':
        b['xl/charts/other.xml'] = b.pop('xl/charts/chart1.xml')
    if change == 'outside_worksheet_target':
        for members in (a, b):
            members['xl/workbook.xml'] = members['xl/workbook.xml'].replace(b'</sheets>', b'<sheet name="Other" sheetId="2" r:id="rId2"/></sheets>')
            name = 'xl/_rels/workbook.xml.rels'
            members[name] = members[name].replace(b'</Relationships>', b'<Relationship Id="rId2" Target="custom/sheet2.xml" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"/></Relationships>')
            members['xl/custom/sheet2.xml'] = members.pop('xl/worksheets/sheet2.xml').replace(b'<sheetData/>', b'<sheetData><row r="1"><c r="A1" t="s"><v>7</v></c></row></sheetData>')
    paths = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    for path, members in zip(paths, (a, b)):
        _write_csv_summary(path, members)
    assert compare_outputs(*paths, csv_summary_temp_root='/recorded/temp')


def test_csv_summary_scope_keeps_unchanged_matching_benign_string_literal(tmp_path):
    paths = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    for path, nonce in zip(paths, ('a1b2c3d4', 'd4c3b2a1')):
        members = _csv_summary_members('/recorded/temp', nonce)
        name = 'xl/sharedStrings.xml'
        members[name] = members[name].replace(b'<si><t>Loaded rows.',
            b'<si><t>metroliza_csv_summary_a1b2c3d4.sqlite</t></si><si><t>Loaded rows.')
        members[name] = members[name].replace(b'count="8"', b'count="9"').replace(b'uniqueCount="8"', b'uniqueCount="9"')
        name = 'xl/worksheets/sheet1.xml'
        members[name] = members[name].replace(b'<v>6</v>', b'<v>7</v>').replace(b'<v>7</v></c></row>', b'<v>8</v></c><c r="E3" t="s"><v>6</v></c></row>')
        _write_csv_summary(path, members)
    assert compare_outputs(*paths, csv_summary_temp_root='/recorded/temp') is None
    assert compare_outputs(*paths)


def test_csv_summary_opt_in_preserves_unchanged_unsupported_strings_and_crc_failure(tmp_path):

    a, b = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    members = _csv_summary_members('/unrecorded/temp')
    _write_csv_summary(a, members)
    _write_csv_summary(b, members)
    assert compare_outputs(a, b, csv_summary_temp_root='/recorded/temp') is None
    raw = bytearray(b.read_bytes())
    entry = raw.rfind(b'xl/sharedStrings.xml') - 46
    assert raw[entry:entry + 4] == b'PK\x01\x02'
    raw[entry + 16] ^= 1  # Corrupt the recorded CRC, leaving compressed data intact.
    b.write_bytes(raw)
    with pytest.raises(BadZipFile, match='Bad CRC'):
        compare_outputs(a, b, csv_summary_temp_root='/unrecorded/temp')
    assert main([str(a), str(b), '--csv-summary-temp-root', '/unrecorded/temp']) == 2


def test_csv_summary_opt_in_rejects_duplicate_zip_member(tmp_path):
    a, b = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    for path, nonce in ((a, 'a1b2c3d4'), (b, 'd4c3b2a1')):
        _write_csv_summary(path, _csv_summary_members('/recorded/temp', nonce))
    with ZipFile(b, 'a') as archive, pytest.warns(UserWarning, match='Duplicate name'):
        archive.writestr('xl/sharedStrings.xml', b'duplicate')
    assert main([str(a), str(b), '--csv-summary-temp-root', '/recorded/temp']) == 2


@pytest.mark.parametrize('root,separator', [('/recorded/temp', '/'), ('C:/recorded/temp', '/'),
    (r'C:\recorded\temp', '\\'), (r'\\server\share\temp', '\\')])
def test_recorded_temp_root_is_lexical_across_hosts(tmp_path, root, separator):
    paths = tmp_path / 'a.xlsx', tmp_path / 'b.xlsx'
    for path, nonce in zip(paths, ('a1b2c3d4', 'd4c3b2a1')):
        _write_csv_summary(path, _csv_summary_members(root, nonce, separator=separator))
    assert compare_outputs(*paths, csv_summary_temp_root=root) is None
    assert compare_outputs(*paths, csv_summary_temp_root=root + separator + 'other')
    assert main([str(path) for path in paths] + ['--csv-summary-temp-root', root]) == 0
    for ambiguous in ('relative', 'C:', r'\recorded\temp', r'C:\mixed/root'):
        assert compare_outputs(*paths, csv_summary_temp_root=ambiguous)


def test_recorded_temp_root_accepts_explicit_host_path_object(tmp_path):
    from os import sep
    root, paths = tmp_path / 'recorded', (tmp_path / 'a.xlsx', tmp_path / 'b.xlsx')
    for path, nonce in zip(paths, ('a1b2c3d4', 'd4c3b2a1')):
        _write_csv_summary(path, _csv_summary_members(root, nonce, separator=sep))
    assert compare_outputs(*paths, csv_summary_temp_root=root) is None

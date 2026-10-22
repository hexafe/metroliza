"""Strict artifact comparison and discriminating negative controls."""

from contextlib import closing
import sqlite3
from zipfile import ZIP_DEFLATED, ZipFile

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


def _dashboard_pair(tmp_path):
    outputs = []
    for side, token in (("a", "a" * 32), ("b", "b" * 32)):
        root = tmp_path / side
        root.mkdir()
        directory = root / ("export_dashboard_assets.generation-" + token)
        directory.mkdir()
        (directory / "chart.png").write_bytes(b"exact PNG bytes")
        (directory / "plotly.js").write_bytes(b"exact bundled JavaScript bytes")
        html = root / "export_dashboard.html"
        html.write_text(f'<script src="{directory.name}/plotly.js" defer></script>'
                        f'<button data-image-src="{directory.name}/chart.png">'
                        f'<img src="{directory.name}/chart.png"></button>')
        outputs.append((root, html, directory))
    return outputs


def test_paired_dashboard_generations_compare_with_exact_assets(tmp_path):
    a, b = _dashboard_pair(tmp_path)
    assert compare_outputs(a[0], b[0]) is None
    assert compare_outputs(a[1], b[1]) is None


@pytest.mark.parametrize("attribute", ["data.src", ".src", "other:src", "data-src", "src.extra"])
@pytest.mark.parametrize("genuine_src", [False, True])
def test_unsupported_attribute_names_remain_literal(tmp_path, attribute, genuine_src):
    a, b = _dashboard_pair(tmp_path)
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
    "missing_generation", "both_missing_generations", "moved_generation", "wrong_reference", "empty_assets",
])
def test_dashboard_generation_exception_is_location_and_content_bound(tmp_path, change):
    import shutil

    a, b = _dashboard_pair(tmp_path)
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
    elif change in {"extra_generation", "both_extra_generations"}:
        for root, _document, _generation in ((a, b) if change == "both_extra_generations" else (b,)):
            extra = root / ("export_dashboard_assets.generation-" + "c" * 32)
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
        b[1].write_text(b[1].read_text().replace(b[2].name, "export_dashboard_assets.generation-" + "d" * 32))
    else:
        for _root, _document, generation in (a, b):
            for path in generation.iterdir():
                path.unlink()
    assert main([str(a[0]), str(b[0])]) != 0


def test_html_file_comparison_also_checks_asset_bytes(tmp_path):
    a, b = _dashboard_pair(tmp_path)
    (b[2] / "chart.png").write_bytes(b"different")
    assert compare_outputs(a[1], b[1])


def test_generation_pattern_elsewhere_is_compared_literally(tmp_path):
    a, b = _dashboard_pair(tmp_path)
    suffix = '<p>generation-' + "c" * 32 + '</p><div data-note="generation-' + "c" * 32 + '"></div>'
    for _root, document, _generation in (a, b):
        document.write_text(document.read_text() + suffix)
    assert compare_outputs(a[0], b[0]) is None
    b[1].write_text(b[1].read_text().replace("c" * 32, "d" * 32))
    assert compare_outputs(a[0], b[0])


@pytest.mark.parametrize("kind", ["xlsx", "html", "sqlite"])
def test_independently_generated_baseline_controls_use_the_same_oracle(tmp_path, kind, capsys):
    if kind == "html":
        left, right = _dashboard_pair(tmp_path)
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
    assert main(arguments) == 0
    assert "baseline control: outputs equal" in capsys.readouterr().out
    if kind == "html":
        (right[2] / "chart.png").write_bytes(b"different")
    elif kind == "xlsx":
        _xlsx(paths[1], value=b"different")
    else:
        with closing(sqlite3.connect(paths[1])) as connection:
            connection.execute("UPDATE data SET value='different'")
            connection.commit()
    assert main(arguments) == 1

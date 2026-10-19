# Performance Boost STEP2 — macierz modułów, okien i flow

Status: aktywny dokument audytu (STEP2). Właściciel: koordynator audytu wydajności.
Raport główny: [`performance-boost-step2.md`](performance-boost-step2.md).
Baza kodu: `78d5d775756e4b64530ce8fb04f175a2e3f461f1` (head PR #1142, 2026.09 RC1, build 261020 + launcher spawn repair).

Inwentaryzacja powstała z kodu (punkty wejścia, `connect()`, QAction, okna, workery, timery, CLI,
crate'y Rust), a nie z dokumentacji; różnice z dokumentacją są w sekcji „Kod a dokumentacja".
Czasy pochodzą z `scripts/benchmark_ui_flows.py` (Linux, źródła, Qt offscreen, dane syntetyczne)
albo z `scripts/measure_windows_first_run_timeline.py` (Windows, hostowany runner CI, prawdziwe EXE).

**Status:** `POMIAR` = sprawdzone pomiarowo; `STAT` = sprawdzone statycznie (kod, ścieżka i wywołania
przeczytane, bez pomiaru); `BLOK` = zablokowane (powód w wierszu); `N/D` = nie dotyczy (uzasadnienie).
**Loading:** `kaczucha-op.` = `create_delayed_worker_progress_dialog` (próg 1000 ms od `show()`),
`kaczucha-nat.` = `create_worker_progress_dialog` bez opóźnienia, `tekst` = etykieta/chip/status bar,
`brak` = brak informacji zwrotnej.

## Licznik pokrycia

| Grupa | Pozycji | POMIAR | STAT | BLOK | N/D |
|---|---:|---:|---:|---:|---:|
| Flow UI rdzenia (SHELL/IMP/DB/FLT/GRP/EXP/TOOL) | 35 | 13 | 18 | 0 | 4 |
| Flow UI danych (CSV/VIS/IND/RT; CSV-02 i CSV-03 w jednym wierszu) | 23 | 6 | 14 | 2 | 1 |
| Start na Windows (scenariusze START-W1…W7) | 7 | 7 | 0 | 0 | 0 |
| Entrypointy, spec-y, build (START-01…24) | 24 | 0 | 24 | 0 | 0 |
| Kod natywny (NAT) | 7 | 1 | 6 | 0 | 0 |
| Praca w tle i integracje (BG-01…11, INT-01…07) | 18 | 1 | 12 | 3 | 2 |
| **Razem pozycji produktowych** | **114** | **28** | **74** | **5** | **7** |

Dodatkowo skatalogowano 67 skryptów CLI (`scripts/`, narzędzia deweloperskie i CI; żaden nie jest
funkcją produktu, `pyproject.toml` nie ma wpisów konsolowych), 45 flag środowiskowych, 27 miejsc
współbieżności i 11 fabryk/zakresów połączeń SQLite (mapa w raporcie głównym, §6).

## Flow UI rdzenia

| ID | Flow (wejście) | Model wykonania | Loading | Status i wynik |
|---|---|---|---|---|
| SHELL-START | start aplikacji, okno główne, rozgrzewka modułów (`main_window.py:236-330`) | GUI: konstrukcja okna; rozgrzewka 8 importów kolejno w wątku GUI | Qt splash do pierwszego malowania; potem tylko status bar | POMIAR: okno 0,52 s; po pierwszym malowaniu GUI blokowane łącznie 1,56 s, najdłużej 0,64 s (mediana 5). PoC wątku tła: 0,17 s / 0,43 s |
| SHELL-NAV | nawigacja Home/Reports/Tools (`main_window.py:449-598`) | GUI; pierwsze wejście w Reports buduje ReportsWorkspace | brak | STAT: jednorazowa budowa; `QSettings.sync()` 2× na zmianę strony |
| SHELL-THEME | menu motywu (`main_window.py:376-396`) | GUI: pełny restyle wszystkich okien | brak | POMIAR: 0,58 s zamrożenia GUI (50 raportów w tabeli); rośnie z liczbą okien i wierszy |
| SHELL-DB | wybór/zmiana bazy (`main_window.py:1510-1561`) | GUI: odzysk staging realtime, schemat przemysłowy, polityki okien | brak | STAT: DDL i UPDATE/DELETE w wątku GUI przy pierwszym wyborze ścieżki |
| SHELL-CLOSE | zamknięcie (`main_window.py:827-946`) | kooperacyjne zatrzymanie workerów; `wait()` loadera Modify DB w GUI | tekst | STAT: nieograniczony `wait()` w `ModifyDB.done` |
| IMP-SRC | „Browse folder/archive" | GUI, trywialne | n/d | N/D: tylko wybór ścieżki |
| IMP-MODE | tryb metadanych | GUI, trywialne | n/d | N/D: tylko unieważnia przegląd |
| IMP-SCAN | „Review reports" (`parsing_dialog.py:817-939`, `preflight.py:955`) | QThread, ściśle szeregowo per plik | kaczucha-op. (timer od `show()` po starcie wątku) | POMIAR: 1500 PDF: skan 38 s + odczyt metadanych 50 s (≈104 s w UI); kaczucha 4/10 klatek przy 50 PDF (burza repolish) |
| IMP-REVIEW | tabela przeglądu: filtr, zaznaczenia, edycje | GUI, model/proxy w Pythonie | brak | STAT: filtr per wiersz bez debounce, O(N) przy każdym zaznaczeniu |
| IMP-META | automatyczny szybki odczyt metadanych i OCR | QThread szeregowo, ponowny hash i otwarcie PDF | tekst (licznik w tabeli) | POMIAR: część IMP-SCAN; bez kaczuchy przez 50 s na 1500 raportów |
| IMP-RUN | „Import N selected reports" (`parse_reports_thread.py:1897`) | GUI: budowa planu ×3; QThread + pula prepare (3 procesy, źródła) + jeden zapisujący | kaczucha-op. | POMIAR: 1500 raportów 68,3 s (45,5 ms/raport), CPU 99 s + 87 s w workerach, RSS 397 MB, zastój startowy 249 ms |
| IMP-ENRICH | „Enrich existing database metadata…" (`metadata_enrichment_thread.py`) | QThread szeregowo per raport (OCR) | tekst + pasek w oknie głównym | STAT: OCR w EXE uruchamia proces na każde wywołanie (RISK-02) |
| DB-OPEN | „Modify Database" (`modify_db.py:135-571`) | GUI: zapytania + 6609 `QTableWidgetItem` | brak | POMIAR: 0,90–0,96 s zamrożenia (okno widoczne od 0,42 s bez treści) |
| DB-RECORDS | zakładki rekordów i filtr (`modify_db_records.py`) | QThread ładowania, filtr w GUI | baner zajętości | POMIAR: 216k wierszy w 12,6 s; filtr 0,52 s z zastojem 0,28 s |
| DB-EDIT | edycje, rename, undo | GUI | n/d | STAT: `collect_modifications` przechodzi wszystkie tabele |
| DB-APPLY | „Apply changes" (`report_edit_service.py:59-104`) | GUI: transakcja na każdy rekord (N+1) | brak | POMIAR: 1 edycja 0,11 s; N edycji = N transakcji w wątku GUI |
| FLT-OPEN | Export → Filter „Edit…" (`filter_dialog.py:894-966`) | QThread DISTINCT (cache LRU 8), wypełnianie list w GUI | tekst | POMIAR: 5,56 s do kompletu wartości; 0,49 s zamrożenia przy otwarciu |
| FLT-REF | wybór referencji → nagłówki | QThread + kopiowanie w GUI | tekst | STAT |
| FLT-APPLY | wyszukiwanie, wyrażenie, Apply | GUI | n/d | STAT: tanie poza dużymi zaznaczeniami |
| GRP-OPEN | Export → Grouping „Edit…" (`data_grouping.py:148-716`) | GUI: pandas `groupby.agg` z lambdą Pythona | brak | POMIAR: 5,82 s pełnego zamrożenia (1500 raportów) |
| GRP-EDIT | tworzenie/zmiana/usuwanie grup | GUI: pełne `populate_list_widgets` po każdej zmianie | brak | STAT |
| GRP-APPLY | Use grouping | GUI: głęboka kopia DataFrame | brak | STAT |
| GRP-MAP | „Match Characteristic Names" (`characteristic_mapping_service.py:166-219`) | GUI: 1 + M zapytań (N+1), każde skanuje widok pomiarów | brak | POMIAR: **764 s zamrożenia** (M = 2664 metryk); PoC jednego zapytania: 2,31 s, wynik identyczny |
| GRP-MAPEDIT | edycja aliasów, podgląd wpływu | GUI: skan widoku przy zmianie pola | brak | STAT |
| EXP-OPEN | „Export Workbook" | GUI: budowa okna, odczyt konfiguracji | brak | POMIAR: 0,38 s |
| EXP-CFG | presety i opcje | GUI, zapis JSON | n/d | STAT |
| EXP-RUN | „Export" (`export_dialog.py:1318`, `export_data_thread.py`) | GUI: import modułu eksportu przy 1. kliknięciu; QThread + pula renderu (2 procesy, per referencja) | kaczucha-op. | POMIAR: 1. kliknięcie blokuje GUI 6,8 s, kaczucha od 7,8 s; Extended plots 50 raportów/216 grup: 552 s, RSS 944 MB; Main plots 1500 raportów: §3 raportu |
| EXP-RESULT | wynik eksportu, otwarcie folderu | GUI, QMessageBox | n/d | STAT |
| EXP-VIS | → VIS-01 | — | — | STAT (patrz VIS-01) |
| TOOL-PLUGIN | Parser profiles | GUI: walidacja/diagnoza z pełnym parsowaniem próbki | brak | STAT |
| TOOL-INCIDENT | Diagnostic incidents | GUI: dekodowanie zapisanych incydentów | brak | STAT: ograniczone `MAX_REPORTS` |
| TOOL-HELP | podręczniki | otwiera URL w przeglądarce | n/d | N/D: brak pracy lokalnej |
| TOOL-ABOUT | About | GUI, drugi dekoder GIF | n/d | STAT |
| TOOL-NOTES | Release notes | GUI `setHtml` | n/d | STAT |
| TOOL-BOM | BOM Manager | brak punktu wejścia | n/d | N/D: nieosiągalne z UI (kod przestarzały) |

## Flow UI danych

| ID | Flow (wejście) | Model wykonania | Loading | Status i wynik |
|---|---|---|---|---|
| CSV-01 | otwarcie CSV Summary | GUI, tanie | brak | STAT |
| CSV-02/03 | wybór pliku → wczytanie (`tabular_analytics_service.py:1709`) | QThread: pętla Pythona po wierszach do SQLite; wynik nakładany w GUI | kaczucha-op. | POMIAR: CSV 100k × 11 kolumn: 24,7 s; kaczucha 167/235 klatek, przerwa 0,40 s |
| CSV-04 | arkusz, kolumna czasu, ID | GUI | brak | STAT |
| CSV-05 | wybór metryk, limity | GUI; `_sync_ui_state` przy każdym przełączniku | brak | STAT: COUNT ×2 i pętle po grupach przy każdym kliknięciu |
| CSV-06 | filtr wierszy | QThread podglądu wartości + COUNT/MIN/MAX w GUI | kaczucha-op. (bez zwalniania) | STAT |
| CSV-07 | grupowanie ręczne | GUI SQL; async tylko ≥250k wierszy | kaczucha-op. warunkowa | STAT |
| CSV-08 | opcje interaktywności | GUI, tanie | n/d | N/D |
| CSV-09 | „Create analytics" (`industrial_analytics_workflow.py:278-591`) | GUI: walidacja ×3; QThread: etapy szeregowo | kaczucha-op. | POMIAR: 100k wierszy: **228 s**, CPU 346 s, RSS 642 MB, dashboard 12,6 MB; zastoje GUI 1,9 s / 1,3 s pod koniec |
| VIS-01 | Dashboard visual options (QWebEngine) | GUI: podgląd `setHtml` po każdej zmianie | brak | STAT: nie mierzono QWebEngine w trybie offscreen |
| IND-01 | otwarcie Industrial Data (`industrial_data_dialog.py:71`) | GUI: import pakietu `oznak` dla etykiety statusu, COUNT-y | brak | POMIAR: 2,9 s zamrożenia (1,8 s to import `oznak`+SQLAlchemy) |
| IND-02 | cache: Temp/Open/Save as/Initialize | GUI: kopiowanie pliku cache | brak | STAT |
| IND-03 | źródła produkcyjne (profile) | GUI: YAML + upsert, podwójny reload | brak | STAT |
| IND-04 | pobieranie do cache (Oznak) | QThread per źródło, źródła szeregowo | tekst (chip) | BLOK: wymaga źródła produkcyjnego Oznak; brak w środowisku |
| IND-05 | Industrial → „CSV Summary…" (`industrial_tabular_bridge.py:104`) | GUI: odświeżenie metadanych/facetów EAV + 4× COUNT | brak | POMIAR: **43,6 s zamrożenia** (50k rekordów × 20 metryk) |
| IND-06 | powiązania produkcji | GUI: 2 zapytania z LIKE na każdy znak w polu szukania | brak | STAT |
| IND-07 | eksport cache → workbook | QThread strumieniowo | kaczucha-nat., pasek stoi na 0 | STAT: miganie przy krótkich eksportach |
| RT-01 | otwarcie Realtime Monitor | GUI: import modułu (poza rozgrzewką), stan bazy | brak | POMIAR: 1,48 s zamrożenia (0,98 s importu) |
| RT-02 | konfiguracja źródeł | GUI upsert | tekst | STAT |
| RT-03 | Start / Poll / Stop | QThread na cykl; detektory szeregowo po każdej paczce | tekst | BLOK: wymaga źródła produkcyjnego (replay CSV nieuruchomiony) |
| RT-04 | zapis/otwarcie dashboardu | QThread, debounce 250 ms | tekst | STAT: HTML przepisywany co cykl także bez zmian |
| RT-05 | przegląd zdarzeń | GUI SQL po każdym wyniku polla | tekst | STAT |
| RT-06 | zamknięcie, rebind, sesja tymczasowa | GUI: kopiowanie cache przy zapisie | tekst | STAT |

## Start, procesy i dystrybucja Windows

| ID | Pozycja | Status i wynik |
|---|---|---|
| START-W1 | pierwsze uruchomienie EXE (pusty cache) | POMIAR (Windows CI, 2+2 próby): kod launchera rusza po 2,4–3,3 s (system/AV na świeżym pliku 334 MB); obecnie 1. okno po 2,0–3,0 s, potem 1,9 s pustki, okno główne 6,7–7,8 s; PoC: splash 50 ms po starcie kodu, zero pustki |
| START-W2 | drugie uruchomienie (weryfikacja SHA-256 + flush 2156 plików) | POMIAR: weryfikacja 2,6–7,0 s; obecnie okno postępu bez postępu i 0,9–1,2 s pustki; PoC: pasek „Checking Metroliza files…" |
| START-W3 | kolejne uruchomienia (warm) | POMIAR: obecnie 0,9–1,2 s bez żadnego okna, okno główne 1,2–1,5 s, fokus nie trafia do okna w 4/6 prób; PoC: splash 65–103 ms, fokus zawsze |
| START-W4 | pierwsze uruchomienie nowej wersji (stary cache obok) | POMIAR: obecnie 1,7–1,9 s pustki; PoC: brak pustki |
| START-W5 | odbudowa uszkodzonego cache | POMIAR: PoC i obecny naprawiają; 1 z 2 prób obecnego launchera skończyła się kodem 102 „cannot replace a runtime still in use" |
| START-W6 | supervisor `metroliza.exe` → aplikacja | POMIAR: ≈0,85 s przy każdym starcie (dwa procesy PyInstaller + hash ≈94 MB komponentów) |
| START-W7 | aplikacja: PyQt, okno, `show()` | POMIAR: ≈0,35 s warm; `show()` ≈0,2 s |
| START-01…24 | entrypointy, spec-y PyInstaller, skrypty build, łańcuch procesów | STAT (inwentaryzacja B, sekcja 1) |

## Kod natywny

| ID | Crate | Status i wynik |
|---|---|---|
| NAT-01 | `cmm_parser` (parse + zapis SQLite) | STAT: w EXE `auto` = Python (wymaga `METROLIZA_ENABLE_NATIVE_IN_FROZEN=1`); trzyma GIL |
| NAT-02 | `comparison_stats_bootstrap` | STAT: jw.; #1120 pkt 10 (30 s fallbacku Pythona) nadal otwarte |
| NAT-03 | `distribution_fit_ad` (rayon) | STAT: jedyny zwalniający GIL; globalna pula rayon = wszystkie rdzenie |
| NAT-04 | `group_stats_coercion` | STAT |
| NAT-05 | `chart_renderer` | STAT: nie renderuje natywnie — woła z powrotem Pythona; domyślnie wyłączony |
| NAT-06 | `packaging/launcher` | POMIAR (Windows CI) — patrz START-W1…W5; PoC splasha |
| NAT-07 | polityka wyboru backendu | STAT: `auto` w źródłach = natywny, w EXE = Python |

## Praca w tle i integracje

| ID | Pozycja | Status |
|---|---|---|
| BG-01 | instrumentacja startu (`METROLIZA_STARTUP_PROFILE`, otwarcie pliku na zdarzenie) | STAT |
| BG-02 | rozgrzewka modułów | POMIAR (SHELL-START) |
| BG-03/04 | łańcuch nadzoru, magazyn incydentów (≈3 zapisy z fsync na uruchomienie) | STAT |
| BG-05 | logowanie do 2 plików | STAT |
| BG-06 | sprawdzanie licencji (domyślnie wyłączone) | N/D |
| BG-07 | cykl życia workera OCR | STAT (patrz INT-02) |
| BG-08 | wzbogacanie metadanych (OCR) | STAT |
| BG-09 | realtime: timer 60 s, wątek polla, zapis dashboardu | BLOK: bez źródła |
| BG-10/11 | QThread-y dialogów, sprzątanie | STAT |
| INT-01 | licencja (domyślnie wyłączona) | N/D: domyślnie nieaktywna |
| INT-02 | worker OCR w EXE: proces na każde wywołanie | STAT (RISK-02); BLOK pomiaru Windows z prawdziwym OCR |
| INT-03 | Google Drive/Sheets | BLOK: wymaga konta i sieci |
| INT-04 | Oznak/SQLAlchemy | BLOK: wymaga źródła |
| INT-05 | LLM/profile parserów (lokalnie) | STAT |
| INT-06/07 | pomoc online, release notes | STAT |

## Kod a dokumentacja

- `architecture.md` §8: „auto wybiera natywny tylko z allowlisty" — kod nie ma allowlisty dla 4 z 5 mostów; w EXE `auto` = Python.
- Katalog #955 „lokalne podręczniki": pomoc otwiera GitHub, podręczniki nie są pakowane.
- Brak w `architecture.md`: łańcuch launcher → supervisor → aplikacja, kontrakt naprawy (kod 75), worker obliczeniowy i pule spawn, izolowany worker OCR, domyślna ścieżka wykresów `hexafe_plotstats`, szybkie ścieżki XLSX, instrumentacja startu.
- Kod kwalifikacyjny (`app/windows_candidate_*.py`, ≈4000 linii) jest w paczce (włączany tylko flagami).

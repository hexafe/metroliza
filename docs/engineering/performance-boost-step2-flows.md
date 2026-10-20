# Performance Boost STEP2 — macierz modułów, okien i flow

Status: aktywny dokument audytu (STEP2). Właściciel: koordynator audytu wydajności.
Raport główny: [`performance-boost-step2.md`](performance-boost-step2.md).
Baza kodu: `78d5d775756e4b64530ce8fb04f175a2e3f461f1` (head PR #1142, 2026.09 RC1, build 261020 + launcher spawn repair).

Inwentaryzacja powstała z kodu (punkty wejścia, `connect()`, QAction, okna, workery, timery, CLI,
crate'y Rust), a nie z dokumentacji; różnice z dokumentacją są w sekcji „Kod a dokumentacja".
Czasy pochodzą z `scripts/benchmark_ui_flows.py` (Linux, źródła, Qt offscreen, dane syntetyczne)
albo z `scripts/measure_windows_first_run_timeline.py` (Windows, hostowany runner CI, prawdziwe EXE).
Mediana [min–max]; n=3 (Linux) i n=7/14 (Windows), jeśli nie zaznaczono inaczej. Czasy Linux: przebieg
2026-10-20 05:54–06:17 w profilu energii `balanced`; wcześniejszy przebieg w `power-saver` (2,8–4,7×
wolniejszy) jest w JSON jako `linux_power_saver`. Surowe agregaty:
[`performance-boost-step2-measurements.json`](performance-boost-step2-measurements.json).

**Status:** `POMIAR` = sprawdzone pomiarowo; `STAT` = sprawdzone statycznie (kod, ścieżka i wywołania
przeczytane, bez pomiaru); `BLOK` = zablokowane (powód w wierszu); `N/D` = nie dotyczy (uzasadnienie).
**Loading:** `kaczucha-op.` = `create_delayed_worker_progress_dialog` (próg 1000 ms od `show()`),
`kaczucha-nat.` = `create_worker_progress_dialog` bez opóźnienia, `tekst` = etykieta/chip/status bar,
`brak` = brak informacji zwrotnej.

## Licznik pokrycia

| Grupa | Pozycji | POMIAR | STAT | BLOK | N/D |
|---|---:|---:|---:|---:|---:|
| Flow UI rdzenia (SHELL/IMP/DB/FLT/GRP/EXP/TOOL) | 35 | 14 | 17 | 0 | 4 |
| Flow UI danych (CSV/VIS/IND/RT; CSV-02 i CSV-03 w jednym wierszu) | 25 | 6 | 16 | 2 | 1 |
| Start na Windows (scenariusze START-W1…W7) | 7 | 7 | 0 | 0 | 0 |
| Entrypointy, spec-y, build (START-01…24) | 24 | 0 | 24 | 0 | 0 |
| Kod natywny (NAT) | 7 | 1 | 6 | 0 | 0 |
| Praca w tle i integracje (BG-01…11, INT-01…07) | 18 | 1 | 12 | 3 | 2 |
| **Razem pozycji produktowych** | **116** | **29** | **75** | **5** | **7** |

Dodatkowo skatalogowano 67 skryptów CLI (`scripts/`, narzędzia deweloperskie i CI; żaden nie jest
funkcją produktu, `pyproject.toml` nie ma wpisów konsolowych), 45 flag środowiskowych, 27 miejsc
współbieżności i 11 fabryk/zakresów połączeń SQLite (mapa w raporcie głównym, §6).

## Flow UI rdzenia

| ID | Flow (wejście) | Model wykonania | Loading | Status i wynik |
|---|---|---|---|---|
| SHELL-START | start aplikacji, okno główne, rozgrzewka modułów (`main_window.py:236-330`) | GUI: konstrukcja okna; rozgrzewka 8 importów kolejno w wątku GUI | Qt splash do pierwszego malowania; potem tylko status bar | POMIAR (n=5): okno 0,14 s; po pierwszym malowaniu GUI blokowane łącznie 0,40 s, najdłużej 0,18 s. PoC wątku tła: najdłużej 0,04 s, łącznie 0,07 s, gotowość +9% |
| SHELL-NAV | nawigacja Home/Reports/Tools (`main_window.py:449-598`) | GUI; pierwsze wejście w Reports buduje ReportsWorkspace | brak | STAT: jednorazowa budowa; `QSettings.sync()` 2× na zmianę strony |
| SHELL-THEME | menu motywu (`main_window.py:376-396`) | GUI: pełny restyle wszystkich okien | brak | POMIAR: 0,20 s [0,19–0,22] zamrożenia GUI (1500 raportów w tabeli); rośnie z liczbą okien i wierszy |
| SHELL-DB | wybór/zmiana bazy (`main_window.py:1510-1561`) | GUI: odzysk staging realtime, schemat przemysłowy, polityki okien | brak | STAT: DDL i UPDATE/DELETE w wątku GUI przy pierwszym wyborze ścieżki |
| SHELL-CLOSE | zamknięcie (`main_window.py:827-946`) | kooperacyjne zatrzymanie workerów; `wait()` loadera Modify DB w GUI | tekst | STAT: nieograniczony `wait()` w `ModifyDB.done` |
| IMP-SRC | „Browse folder/archive" | GUI, trywialne | n/d | N/D: tylko wybór ścieżki |
| IMP-MODE | tryb metadanych | GUI, trywialne | n/d | N/D: tylko unieważnia przegląd |
| IMP-SCAN | „Review reports" (`parsing_dialog.py:817-939`, `preflight.py:955`) | QThread, ściśle szeregowo per plik | kaczucha-op. (timer od `show()` po starcie wątku) | POMIAR: 1500 PDF: 25,6 s [22,3–25,8] w UI; sam kod: skan 8,0 s + odczyt metadanych 11,2 s; kaczucha od 1,08 s, 84–86% klatek, przerwy do 164 ms, ≈150 klatek po ukryciu (sygnał i restyle na plik). PoC puli: 6,6 s (4) / 5,3 s (8), wynik identyczny |
| IMP-REVIEW | wypełnienie tabeli po Review; filtr, zaznaczenia, edycje | GUI, model/proxy w Pythonie | brak (kaczucha zamknięta przed `set_review`) | POMIAR: wypełnienie 1500 wierszy 0,26 s [0,18–0,29] zamrożenia GUI po zamknięciu kaczuchy; STAT: filtr per wiersz bez debounce, O(N) przy każdym zaznaczeniu |
| IMP-META | automatyczny szybki odczyt metadanych i OCR | QThread szeregowo, ponowny hash i otwarcie PDF | tekst (licznik w tabeli) | POMIAR: część IMP-SCAN; ≈14 s w UI (kod: 11,2 s) na 1500 raportów bez animowanego wskaźnika |
| IMP-RUN | „Import N selected reports" (`parse_reports_thread.py:1897`) | GUI: budowa planu ×3; QThread + pula prepare (3 procesy, źródła) + jeden zapisujący | kaczucha-op. | POMIAR: 1500 raportów 12,9 s [12,8–12,9] (8,6 ms/raport), RSS 398 MB, najdłuższy zastój 0,07 s; kaczucha od 1,06 s, ≈100% klatek. Profil (power-saver, proporcje): ≈17% sprawdzanie gotowości schematu (2× na raport), ≈6–8% odświeżanie rejestru parserów, ≈28% budowa wierszy |
| IMP-ENRICH | „Enrich existing database metadata…" (`metadata_enrichment_thread.py`) | QThread szeregowo per raport (OCR) | tekst + pasek w oknie głównym | STAT: OCR w EXE uruchamia proces na każde wywołanie (RISK-02) |
| DB-OPEN | „Modify Database" (`modify_db.py:135-571`) | GUI: zapytania + 6609 `QTableWidgetItem` | brak | POMIAR: 0,18 s [0,18–0,22] zamrożenia (okno widoczne od 0,09 s bez treści); Windows niezmierzony |
| DB-RECORDS | zakładki rekordów i filtr (`modify_db_records.py`) | QThread ładowania, filtr w GUI | baner zajętości | POMIAR: 216k wierszy + 1 znak filtra: 2,67 s [2,57–2,89], najdłuższy zastój 0,08 s |
| DB-EDIT | edycje, rename, undo | GUI | n/d | STAT: `collect_modifications` przechodzi wszystkie tabele |
| DB-APPLY | „Apply changes" (`report_edit_service.py:59-104`) | GUI: transakcja na każdy rekord (N+1) | brak | POMIAR: 1 edycja 0,04 s; N edycji = N transakcji w wątku GUI |
| FLT-OPEN | Export → Filter „Edit…" (`filter_dialog.py:894-966`) | QThread DISTINCT (cache LRU 8), wypełnianie list w GUI | tekst | POMIAR: 1,19 s [1,18–1,37] do kompletu wartości; 0,12 s zamrożenia przy otwarciu |
| FLT-REF | wybór referencji → nagłówki | QThread + kopiowanie w GUI | tekst | STAT |
| FLT-APPLY | wyszukiwanie, wyrażenie, Apply | GUI | n/d | STAT: tanie poza dużymi zaznaczeniami |
| GRP-OPEN | Export → Grouping „Edit…" (`data_grouping.py:148-716`) | GUI: pandas `groupby.agg` z lambdą Pythona | brak | POMIAR: 1,23 s [1,20–1,26] pełnego zamrożenia (1500 raportów) |
| GRP-EDIT | tworzenie/zmiana/usuwanie grup | GUI: pełne `populate_list_widgets` po każdej zmianie | brak | STAT |
| GRP-APPLY | Use grouping | GUI: głęboka kopia DataFrame | brak | STAT |
| GRP-MAP | „Match Characteristic Names" (`characteristic_mapping_service.py:166-219`) | GUI: 1 + M zapytań (N+1), każde skanuje widok pomiarów | brak | POMIAR: **163 s zamrożenia** (M = 2664 metryk); n=1; PoC jednego zapytania: 0,44 s [0,44–0,55], mała baza w pełni identyczna, duża: próbka 30 metryk identyczna |
| GRP-MAPEDIT | edycja aliasów, podgląd wpływu | GUI: skan widoku przy zmianie pola | brak | STAT |
| EXP-OPEN | „Export Workbook" | GUI: budowa okna, odczyt konfiguracji | brak | POMIAR: 0,11 s [0,09–0,12] |
| EXP-CFG | presety i opcje | GUI, zapis JSON | n/d | STAT |
| EXP-RUN | „Export" (`export_dialog.py:1318`, `export_data_thread.py`) | GUI: import modułu eksportu przy 1. kliknięciu; QThread + pula renderu (2 procesy, per referencja) | kaczucha-op. | POMIAR: Main plots 1500: 28,6 s [27,9–29,3], RSS 763 MB; 1. kliknięcie blokuje GUI 1,72 s [1,65–1,74], kaczucha od 2,67 s. Extended 50 raportów/216 grup (n=1): 130,3 s, RSS 962 MB, 1. klik 1,65 s. Z dashboardem HTML render zawsze szeregowo (48 grup przy 4 workerach: 50,7 s vs 25,3 s bez dashboardu) |
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
| CSV-02/03 | wybór pliku → wczytanie (`tabular_analytics_service.py:1709`) | QThread: pętla Pythona po wierszach do SQLite; wynik nakładany w GUI | kaczucha-op. | POMIAR: CSV 100k × 11 kolumn: 4,93 s [4,88–5,04]; kaczucha od 1,18 s, 53–60% klatek, przerwy do 0,73 s; zamykana przed nałożeniem wyniku |
| CSV-04 | arkusz, kolumna czasu, ID | GUI | brak | STAT |
| CSV-05 | wybór metryk, limity | GUI; `_sync_ui_state` przy każdym przełączniku | brak | STAT: COUNT ×2 i pętle po grupach przy każdym kliknięciu |
| CSV-06 | filtr wierszy | QThread podglądu wartości + COUNT/MIN/MAX w GUI | kaczucha-op. (bez zwalniania) | STAT |
| CSV-07 | grupowanie ręczne | GUI SQL; async tylko ≥250k wierszy | kaczucha-op. warunkowa | STAT |
| CSV-08 | opcje interaktywności | GUI, tanie | n/d | N/D |
| CSV-09 | „Create analytics" (`industrial_analytics_workflow.py:278-591`) | GUI: walidacja ×3; QThread: etapy szeregowo | kaczucha-op. | POMIAR: 100k wierszy: **50,3 s** [49,9–51,2], RSS 640 MB, dashboard 12,6 MB; najdłuższy zastój 0,43 s, przerwa animacji do 0,61 s pod koniec. Profil: fity rozkładów scipy (MLE, Nelder–Mead) na pełnych danych, powtórzone dla histogramu i tabeli |
| VIS-01 | Dashboard visual options (QWebEngine) | GUI: podgląd `setHtml` po każdej zmianie | brak | STAT: nie mierzono QWebEngine w trybie offscreen |
| IND-01 | otwarcie Industrial Data (`industrial_data_dialog.py:71`) | GUI: import pakietu `oznak` dla etykiety statusu, COUNT-y | brak | POMIAR: 0,78 s [0,75–0,83] zamrożenia (profil w power-saver: 1,8 s z 2,9 s to import `oznak`+SQLAlchemy) |
| IND-02 | cache: Temp/Open/Save as/Initialize | GUI: kopiowanie pliku cache | brak | STAT |
| IND-03 | źródła produkcyjne (profile) | GUI: YAML + upsert, podwójny reload | brak | STAT |
| IND-04 | pobieranie do cache (Oznak) | QThread per źródło, źródła szeregowo | tekst (chip) | BLOK: wymaga źródła produkcyjnego Oznak; brak w środowisku |
| IND-05 | Industrial → „CSV Summary…" (`industrial_tabular_bridge.py:104`) | GUI: odświeżenie metadanych/facetów EAV + 4× COUNT | brak | POMIAR: **10,0 s** [9,6–10,9] zamrożenia (50k rekordów × 20 metryk) |
| IND-06 | powiązania produkcji | GUI: 2 zapytania z LIKE na każdy znak w polu szukania | brak | STAT |
| IND-07 | eksport cache → workbook; tryb live bez cache (`industrial_export_dialog.py:71`, `IndustrialLiveExportThread`) | QThread strumieniowo | kaczucha-nat., pasek stoi na 0 | STAT: miganie przy krótkich eksportach; tryb live: BLOK pomiaru (wymaga źródła Oznak) |
| IND-08 | podokna filtra i grupowania Industrial (`IndustrialFilterDialog` z IND-04/IND-07, `IndustrialGroupingDialog` z IND-07) | GUI: „Load references" = `ensure_report_schema` + `SELECT DISTINCT` referencji w wątku GUI; grouping = stała lista pól | brak | STAT: tanie przy 1500 raportach; `ensure_report_schema` otwiera transakcję zapisu w GUI (ryzyko blokady przy aktywnym imporcie) |
| IND-09 | filtr produkcyjny w CSV Summary (`IndustrialAnalyticsFilterDialog`, `industrial_analytics_dialog.py:1708`) | GUI: pola tekstowe; po Apply reset metryk i `_sync_ui_state` | brak | STAT: koszt po Apply niezmierzony osobno |
| RT-01 | otwarcie Realtime Monitor | GUI: import modułu (poza rozgrzewką), stan bazy | brak | POMIAR: 0,31 s [0,30–0,36] zamrożenia (profil n=1 w power-saver: ≈1 s z 1,17 s to import modułu) |
| RT-02 | konfiguracja źródeł | GUI upsert | tekst | STAT |
| RT-03 | Start / Poll / Stop | QThread na cykl; detektory szeregowo po każdej paczce | tekst | BLOK: wymaga źródła produkcyjnego (replay CSV nieuruchomiony) |
| RT-04 | zapis/otwarcie dashboardu | QThread, debounce 250 ms | tekst | STAT: HTML przepisywany co cykl także bez zmian |
| RT-05 | przegląd zdarzeń | GUI SQL po każdym wyniku polla | tekst | STAT |
| RT-06 | zamknięcie, rebind, sesja tymczasowa | GUI: kopiowanie cache przy zapisie | tekst | STAT |

## Start, procesy i dystrybucja Windows

| ID | Pozycja | Status i wynik |
|---|---|---|
| START-W1 | pierwsze uruchomienie EXE (pusty cache) | POMIAR (Windows CI, 7+7 prób): kod launchera PoC rusza po 3,2 s [2,4–3,7] (system/AV na świeżym pliku 334 MB); obecnie 1. okno (postęp) po 2,6 s [1,9–3,6], potem 1,95 s [1,6–3,9] pustki, okno główne 8,2 s [5,9–10,2]; PoC: splash ≈0,1 s po starcie kodu, zero pustki, okno główne 8,1 s; PoC bez okna splasha: 7,4 s bez żadnego okna (n=2) |
| START-W2 | drugie uruchomienie (weryfikacja SHA-256 + flush 2156 plików) | POMIAR: natychmiast po 1. starcie weryfikacja 3,4 s [2,4–7,0] obecnie, 5,8 s [4,2–6,2] w PoC (n=7); po 20 s pauzy 0,39/0,43 s vs 0,45/2,24 s (n=2) — dominują niezapisane strony z 1. startu; obecnie okno postępu bez postępu i ≈1 s pustki; PoC: pasek „Checking Metroliza files…", zero pustki |
| START-W3 | kolejne uruchomienia (warm) | POMIAR (n=14): obecnie 1,07 s [0,95–1,38] bez żadnego okna, okno główne 1,34 s [1,22–1,63], fokus 6/14; PoC: splash 66 ms [44–89], okno główne 1,30 s, fokus 12/12 (2 próby bez rejestracji okna przez próbnik) |
| START-W4 | pierwsze uruchomienie nowej wersji (stary cache obok) | POMIAR (n=7): obecnie 2,1 s [1,6–4,4] pustki; PoC: brak pustki |
| START-W5 | odbudowa uszkodzonego cache | POMIAR (n=7): PoC i obecny naprawiają; 1 z 7 prób obecnego launchera skończyła się kodem 102 „cannot replace a runtime still in use"; 1 próba PoC: odbudowa 17,9 s (pozostałe ≈3,6 s), splash przez cały czas |
| START-W6 | supervisor `metroliza.exe` → aplikacja | POMIAR (n=8): ≈0,65–0,9 s przy każdym starcie — start procesu ≈0,43 s, importy i hash ≈94 MB komponentów ≈0,15–0,3 s, start procesu aplikacji ≈0,25–0,3 s |
| START-W7 | aplikacja: PyQt, okno, `show()` | POMIAR: ≈0,31–0,36 s warm; `show()` ≈0,2 s |
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

# Metroliza — Performance Boost STEP2: audyt, pomiary, PoC i plan wdrożenia

- **Status:** audyt zakończony; PoC na gałęzi `perf/step2-audit` (draft PR); nic nie zostało zmergowane.
- **Właściciel:** koordynator audytu wydajności (Claude Opus 5.5, Claude Code). Decyzje produktowe: PO.
- **Data:** 2026-10-20 (czasy w tekście: UTC+2, Warszawa, chyba że zaznaczono UTC).
- **Baza audytu:** `78d5d775756e4b64530ce8fb04f175a2e3f461f1` = aktualny head PR #1142
  (`integrate/2026.09-rc1-build-261018`), czyli 2026.09 RC1 build 261020 + naprawa spawn w launcherze.
- **Testowany EXE:** `metroliza_2026.09rc1_261020_launcher.exe`, SHA-256 `9b8cb752…5e266`,
  zbudowany z `e4a739b8` (provenance `dirty: false`, CI 39286831429). Pomiary Windows w tym
  raporcie pochodzą z EXE budowanych przez CI z gałęzi PoC (ten sam onedir pakowany starym i nowym
  launcherem), a nie z ręcznie testowanego pliku.
- **Macierz modułów/okien/flow:** [`performance-boost-step2-flows.md`](performance-boost-step2-flows.md).
- **Tracker:** Issue „Performance Boost STEP2" (nowe; powiązane z #1120, #952, #918, #1101).

## 1. Podsumowanie dla PO

### 1.1 Największe zmierzone straty czasu

Pomiary od kliknięcia do użytecznego wyniku. Dane syntetyczne (bez danych klientów). „Linux" =
źródła, Qt offscreen, ta sama maszyna (Xeon W-10855M, 6 rdzeni / 12 wątków); „Windows" = EXE na
hostowanym runnerze CI (4 vCPU, Defender włączony). n = liczba prób.

| # | Gdzie użytkownik czeka | Zmierzony czas | Co się dzieje w tym czasie | Najlepszy zmierzony wariant |
|---:|---|---:|---|---|
| 1 | Reports → „Match Characteristic Names" (1500 raportów, 2664 metryk) | **764 s zamrożenia GUI** (n=1) | 1 + 2664 zapytań, każde skanuje cały widok pomiarów (N+1), w wątku GUI | jedno zapytanie z funkcją okna: **2,3 s**, wynik identyczny (PoC) |
| 2 | Export „Extended plots" (50 raportów, 216 grup) | **552 s**, RSS 944 MB (n=1) | ok. 2,5 s/grupę: render matplotlib (tekst, PNG), pula 2 procesów odtwarzana per referencja | 48 grup: 220 s szeregowo → 96 s przy 4, 88 s przy 8 procesach, wynik identyczny |
| 3 | CSV Summary → „Create analytics" (100k wierszy) | **228 s**, RSS 642 MB (n=1) | etapy szeregowo w jednym wątku; na końcu zastoje GUI 1,9 s / 1,3 s | do rozbicia w PR (sekcja 8) |
| 4 | Reports → „Review reports" (1500 PDF) | **≈104 s** w UI (88 s w samym kodzie) | skan i odczyt metadanych ściśle szeregowo, 3 hashe i 2 otwarcia PDF na plik | pula 8 procesów: **23,7 s (3,7×)**, 4 procesy 30,2 s, wynik identyczny (PoC) |
| 5 | Import 1500 raportów | **68 s** (45 ms/raport), RSS 397 MB (n=1) | pula prepare 3 procesy + jeden zapisujący | sekcja 6 |
| 6 | Industrial Data → „CSV Summary…" (cache 50k rekordów × 20 metryk) | **43,6 s zamrożenia GUI** (n=1) | przeliczenie metadanych i facetów EAV + 4× ten sam COUNT (4,6 s każdy) w wątku GUI | do wdrożenia (sekcja 8) |
| 7 | Start aplikacji z cache (Windows) | **0,9–1,4 s bez żadnego okna**, okno główne 1,2–1,6 s (n=12) | launcher → supervisor (0,43 s startu procesu + 0,2 s hash/importy) → aplikacja | PoC: splash po **44–129 ms**, okno główne bez zmian |
| 8 | Pierwszy start / nowa wersja (Windows) | okno postępu, potem **1,7–1,9 s pustego ekranu**, okno 6,7–9,3 s (n=8) | rozpakowanie 538 MB, start supervisora i aplikacji z nowo zapisanych DLL | PoC: kaczucha bez przerwy od 50 ms po starcie kodu do okna głównego |
| 9 | Export → Grouping „Edit…" (1500 raportów) | **5,8 s zamrożenia GUI** (n=1) | pandas `groupby.agg` z lambdą Pythona dla 36 000 grup | wektoryzacja (sekcja 8) |
| 10 | Export → Filter „Edit…" (216k wierszy) | 5,6 s do kompletu wartości (n=1) | DISTINCT-y w workerze, wypełnianie 13 list w GUI | sekcja 8 |
| 11 | Pierwsze kliknięcie „Export" w sesji | **6,8 s zamrożenia GUI** przed pokazaniem kaczuchy (n=1) | import modułu eksportu (matplotlib, numpy, …) w wątku GUI | import w tle / w rozgrzewce |
| 12 | Okno główne tuż po starcie (Linux) | GUI blokowane łącznie 1,56 s, najdłużej 0,64 s (n=5) | rozgrzewka 8 modułów w wątku GUI po pierwszym malowaniu | PoC wątku tła: 0,43 s / 0,17 s (n=5) |

Pozostałe zmierzone: Industrial Data open 2,9 s (1,8 s to import pakietu `oznak`), Realtime open
1,5 s, Modify DB open 0,9 s (okno widoczne puste od 0,42 s), rekordy Modify DB 216k w 12,6 s,
wczytanie CSV 100k w 24,7 s, przełączenie motywu 0,58 s zamrożenia. Pełna tabela: §4.

### 1.2 Kaczucha: co jest nie tak

- Kaczucha jest podpięta w **8 z 58 flow UI**. **13 zmierzonych operacji >1 s nie ma żadnego
  wskaźnika** (§7). Najdłuższe: Characteristic Mapping (764 s), Industrial → CSV Summary (43,6 s),
  Grouping (5,8 s), Industrial Data (2,9 s), Realtime (1,5 s).
- Tam, gdzie jest, ma cztery wady wspólnego mechanizmu (`worker_progress_dialog.py`):
  1. próg 1 s liczy się od `show()`, a nie od kliknięcia; praca przed `show()` (plan importu,
     import modułu eksportu) nie jest liczona;
  2. animacja i opóźnione pokazanie działają w wątku GUI, więc nie ruszą, gdy GUI jest zajęte —
     pierwszy eksport pokazuje kaczuchę po 7,8 s; przy skanie 50 PDF namalowała 4 z 10 klatek;
  3. `QMovie` startuje przy tworzeniu (także gdy dialog nigdy się nie pokaże) i działa dalej po
     zamknięciu (24 klatki w tle przy jednym skanie); dialog nie jest zwalniany (żywy po zakończeniu);
  4. część flow zamyka kaczuchę przed końcowym nakładaniem wyniku w GUI (CSV-03).
- Start aplikacji: obecny Qt splash pojawia się dopiero po imporcie PyQt i w trakcie budowy okna
  głównego stoi (na Windows zmiana w 0–1 z 1–4 klatek). Szczegóły: §5.

### 1.3 Wyniki PoC

| PoC | Wynik | Zgodność | Decyzja |
|---|---|---|---|
| Natywny splash z kaczuchą w launcherze + przekazanie do aplikacji (Windows) | splash 44–129 ms po starcie launchera; brak pustych okresów; brak podwójnego splasha; fokus w oknie głównym 100%; animacja zmienia się w 95–97% klatek | ten sam onedir, okno główne w tym samym czasie (warm) | **PRZYJĘTY** (do produkcyjnego PR, z warunkiem w §5.6) |
| Characteristic Mapping jednym zapytaniem | 654–764 s → 2,3 s | identyczny wynik (mała baza: pełne porównanie; duża: próbka 30 metryk) | **PRZYJĘTY** |
| Review reports w puli procesów | 87,8 s → 30,2 s (4) / 23,7 s (8) | identyczne wpisy i odczyty metadanych | **PRZYJĘTY** |
| Rozgrzewka w wątku tła | najdłuższy zastój 636 → 171 ms; blokada 1562 → 431 ms | te same moduły, ten sam czas gotowości | **PRZYJĘTY** (z testem bezpieczeństwa importów) |
| Więcej procesów renderu Extended plots | 48 grup: 220 s (1) → 96 s (4) → 88 s (8) | identyczny XLSX (hash treści) | **PRZYJĘTY** jako kierunek: liczba procesów z budżetu zasobów + jedna pula na eksport |
| `PRAGMA cache_size`/`mmap_size` dla zapytań odczytu | −30%…+11%, w granicach szumu | — | **ODRZUCONY** |
| BLAS=1 w procesach renderu | pomiar nieważny (błąd harnessu, §3.4); nie powtórzono | — | **NIEROZSTRZYGNIĘTY** |

### 1.4 Rekomendowana pierwsza partia (PR-y 1–4, §9)

1. **Splash i responsywność startu** — natywny splash z kaczuchą, przekazanie do aplikacji,
   rozgrzewka poza GUI (PO zgłoszenie „brak splasha przy pierwszym uruchomieniu").
2. **Wspólny mechanizm „operacji z kaczuchą"** — próg od kliknięcia, praca przygotowawcza poza GUI,
   leniwe tworzenie, zwalnianie, throttling postępu; podpięcie do wszystkich 13 brakujących flow.
3. **Szybkie duże zyski bez zmiany architektury** — Characteristic Mapping (1 zapytanie),
   Grouping (wektoryzacja), Industrial → CSV Summary (bez powtórnych COUNT-ów, facet-y w SQL, worker),
   Industrial Data (status `oznak` bez importu), import modułu eksportu poza GUI.
4. **Review reports w puli procesów** (skan + metadane w jednym przebiegu na plik).

## 2. Baza audytu i stan repozytorium (2026-10-19/20)

- `develop` = `784e44b2` (bez zmian od RC1). Gałąź referencyjna #1142 jest **604 commity przed**
  `develop` i zawiera go (`develop` jest przodkiem).
- **#1109** (`integrate/2026.09-rc1-into-develop` → `develop`): OPEN, head `82f8f576`, CLEAN.
- **#1142** (`integrate/2026.09-rc1-build-261018` → `develop`): OPEN, head **`78d5d775`**,
  MERGEABLE/BLOCKED. Opis PR (plan v5) wskazuje head `15ddbeb7` — jest **nieaktualny**: po nim weszły
  `ff851c3d` (BUG-001/002 CSV Summary, #1145), `f4cac9a6` (etykieta 261020), `e4a739b8` (PyMuPDF <2)
  i `78d5d775` (naprawa spawn launchera).
- Audyt STEP2 dotyczy więc `78d5d775`, a nie `develop` (inaczej proponowałby ponownie wdrożone już
  optymalizacje #1121/#1129–#1133/#1137/#1138).
- **Baza przyszłych PR-ów STEP2:** gałąź referencyjna #1142 do czasu landowania #1109 i #1142;
  potem `develop`. Draft PR PoC celuje w `integrate/2026.09-rc1-build-261018`, żeby diff pokazywał
  tylko STEP2; po landowaniu trzeba go przestawić na `develop`.
- Stan obszarów regresji wskazanych w poleceniu (na `78d5d775`):
  - **granice stron (#1143):** naprawione dla nowych importów (`d87c5801`); dane RC1 nadal czekają na
    decyzję PO; harness STEP2 nie zmienia parsowania;
  - **metadane workerów:** prepare workers otrzymują i odsyłają zatwierdzony override (`c476b7f2`);
    PoC puli „Review" używa tych samych funkcji per plik i daje identyczne odczyty;
  - **checkpointy WAL (#1137):** kadencja ≥25 commitów / ≥2 s, ponawianie przy busy; import 1500
    raportów przeszedł z identycznymi wierszami (fixture wszystkich scenariuszy DB).

## 3. Metoda, środowisko i procedura odtworzenia

### 3.1 Narzędzia (w repo, gałąź PoC)

- `scripts/benchmark_ui_flows.py` — steruje prawdziwymi oknami tak jak użytkownik (handlery
  przycisków w wątku GUI), każdy scenariusz w osobnym procesie, prywatny `HOME`, Qt offscreen.
  Mierzy: czas do pierwszej informacji zwrotnej (pierwsze nowe okno), czas do wyniku (warunek
  scenariusza), zastoje GUI (QTimer 5 ms — przerwa między tyknięciami = czas, w którym okno nie
  mogło się odmalować ani przyjąć wejścia), kaczuchę (koszt utworzenia, `show()`, faktyczne
  pokazanie, klatki animacji w czasie widoczności, klatki w tle, czy dialog żyje po zakończeniu),
  peak RSS całego drzewa procesów, CPU własne i dzieci. `--profile N` profiluje wątek GUI,
  `--profile-thread modul:Klasa` profiluje `run()` QThreada.
- `scripts/measure_windows_first_run_timeline.py` + job CI `windows-first-run-timeline`
  (`run_windows_first_run_timeline=1`) — buduje onedir raz i pakuje go launcherem bazowym
  (`78d5d775`) i PoC; scenariusze cold / verified / warm ×2 / warmup / corrupt / new_version,
  rundy naprzemienne; próbkowanie okien co 20 ms, zrzuty ekranu co 200 ms, znaczniki launchera,
  supervisora i aplikacji na wspólnym zegarze.
- Instrumentacja opcjonalna (domyślnie wyłączona): `METROLIZA_STARTUP_STALL_PROBE=1`,
  `METROLIZA_STARTUP_EXIT_AFTER_WARMUP=1`, `METROLIZA_WARMUP_IN_THREAD=1` (PoC), znaczniki
  `timing event=… epoch_ms=…` w logu launchera.

### 3.2 Dane (wyłącznie syntetyczne)

- 1500 PDF CMM (≈150 pomiarów, 37 referencji; generator z audytu #1120), import do bazy 90,8 MB /
  216 000 wierszy pomiarów, 2664 metryk (nagłówek × oś); 50 PDF (7200 wierszy, 216 grup Extended);
  30 PDF (960 wierszy, 48 grup Extended); CSV 100 000 × 11 kolumn (9,1 MB); cache przemysłowy
  50 000 rekordów × 20 metryk (1 000 000 wartości EAV) w kopii bazy 1500.
- Brak danych klientów, sekretów i profili ujawniających treść raportów.

### 3.3 Środowisko

- Linux: Xeon W-10855M (6C/12T), 62 GB RAM, kernel 7.2.5; Python 3.11.16, PyQt6/Qt 6.6.1,
  PyMuPDF 1.28.2, pandas 3.0.6, numpy 2.4.6, matplotlib 3.11.2, SQLite 3.53.1, XlsxWriter 3.2.9
  (venv deweloperski; `requirements.txt` ma zakresy wersji, CI instaluje najnowsze zgodne).
  Dane na tmpfs (zimny dysk niemierzony). Obciążenie tła zapisane przy każdej próbie (loadavg 3–5;
  przez pierwsze ~2 h audytu na maszynie działała gra — wtedy wykonywano tylko analizę statyczną).
- Windows: hostowany runner GitHub (windows-latest, 4 vCPU, Defender), EXE zbudowane w CI z gałęzi
  PoC. To nie jest czysty laptop z antywirusem użytkownika (#1101 A5).

### 3.4 Zastrzeżenia do pomiarów

- Wyniki n=1 pochodzą z przebiegu „smoke" każdego scenariusza; gdzie dostępne są mediany z 3 prób,
  podano je w §4 z rozrzutem.
- Unieważnione przeze mnie i powtórzone: (a) pierwszy pomiar skalowania Extended plots i test BLAS=1 —
  skrypty pomocnicze nie miały strażnika `__main__`, więc workery spawn ponownie uruchamiały cały
  eksport (ok. 40 min nieważnych pomiarów); powtórzono ze strażnikiem; test BLAS=1 nie został
  powtórzony; (b) pierwszy przebieg osi czasu Windows bez logów (ścieżki względne) — powtórzony.
- Profilery (cProfile) wydłużają czasy 1,3–2×; liczby z profili służą tylko do proporcji.

### 3.5 Odtworzenie

```bash
# Linux, w worktree PoC (synthetic data only)
python scripts/benchmark_ui_flows.py prepare --data-dir DATA        # CSV + cache (po imporcie 1500)
python scripts/benchmark_ui_flows.py run --scenario reports_import --data-dir DATA \
    --pdf-set pdf_1500 --keep-db DATA/db_1500.sqlite --out import.json
python scripts/benchmark_ui_flows.py suite --data-dir DATA --runs 3 --out-dir OUT
# Windows (CI)
gh workflow run ci.yml --ref perf/step2-audit -f run_windows_first_run_timeline=1
```

## 4. Tabela pomiarów

Mediana i rozrzut z 3 prób, gdzie podano; inaczej n=1. Czasy od akcji użytkownika.
„Pierwsza informacja" = pierwsze nowe okno (dialog lub kaczucha). „Zastój" = najdłuższa przerwa
pętli zdarzeń GUI.

| Flow | Scenariusz (dane) | Wynik [s] | Pierwsza informacja [s] | Najdłuższy zastój GUI [s] | Peak RSS [MB] | CPU [s] (proces + dzieci) | n |
|---|---|---:|---:|---:|---:|---:|---:|
| IMP-SCAN+META | Review 50 PDF | 4,53 | 1,13 (kaczucha) | 0,38 | 159 | 5,1 | 1 |
| IMP-SCAN+META | Review 1500 PDF (UI, setup importu) | ≈104 | — | — | — | — | 1 |
| IMP-RUN | import 50 PDF | 4,77 | 1,07 (kaczucha) | 0,11 | 166 | 6,8 | 1 |
| IMP-RUN | import 1500 PDF | 68,3 | 1,20 (kaczucha) | 0,25 | 397 | 99 + 87 | 1 |
| DB-OPEN | Modify DB, baza 1500 | 0,96 | 0,42 (puste okno) | 0,96 | 123 | 1,6 | 1 |
| DB-RECORDS | zakładka pomiarów 216k + 1 znak filtra | 13,1 (wiersze 12,6) | baner | 0,39 | 273 | 18,1 | 1 |
| DB-APPLY | 1 zmiana nazwy | 0,11 | — | 0,11 | 123 | — | 1 |
| EXP-OPEN | okno eksportu | 0,38 | 0,36 | 0,38 | 118 | 0,5 | 1 |
| FLT-OPEN | filtr, 216k wierszy | 5,56 | 0,49 | 0,49 | 130 | 8,2 | 1 |
| GRP-OPEN | grouping, 1500 raportów | 5,82 | 5,82 | **5,82** | 173 | — | 1 |
| GRP-MAP | dopasowanie nazw, 2664 metryk | **764,3** | 764,3 | **764,3** | 134 | — | 1 |
| SHELL-THEME | motyw ciemny, tabela 50 | 0,58 | — | 0,58 | 160 | 0,8 | 1 |
| CSV-02/03 | wczytanie CSV 100k | 24,7 | 1,12 (kaczucha) | 0,40 | 218 | 28,1 | 1 |
| CSV-09 | Create analytics 100k | **228,1** | 0,99 (kaczucha) | 1,91 | 642 | 346 | 1 |
| IND-01 | Industrial Data, cache 50k | 2,92 | 2,91 | **2,92** | 185 | 4,3 | 1 |
| IND-05 | Industrial → CSV Summary | **43,6** | 43,6 | **43,6** | 208 | 62 | 1 |
| RT-01 | Realtime, pierwsze otwarcie | 1,48 | 1,46 | **1,48** | 138 | 2,6 | 1 |
| EXP-RUN | Extended plots, 50 raportów / 216 grup, 2 procesy | **551,9** | 7,76 (kaczucha) | **6,82** (1. klik) | 944 | 335 + 1312 | 1 |
| EXP-RUN (PoC) | Extended plots, 48 grup, procesy 1 / 2 / 4 / 8 | 220 / ‹2› / 96 / 88 | — | — | — | 304 / ‹2› / 27+359 / 27+555 | 1 |
| SHELL-START | start (Linux), okno → gotowość | 0,52 → 1,86 | splash | 0,64 (rozgrzewka) | — | — | 5 |
| SHELL-START (PoC) | rozgrzewka w wątku | 0,56 → 2,02 | splash | 0,17 | — | — | 5 |

Windows (EXE, hostowany runner, ms od utworzenia procesu; mediana [min–max]):

| Scenariusz | Wariant | Kod launchera rusza | Pierwsze okno | Pusty ekran po 1. oknie | Okno główne | Fokus w oknie głównym | n |
|---|---|---:|---:|---:|---:|---|---:|
| cold | obecny | — | 2460 [2045–2968] (okno postępu) | 1925 [1709–1948] | 7964 [6671–9273] | 4/4 | 4 |
| cold | PoC | 3191 [2212–3829] | 3249 [2257–3883] (splash) | **0** | 8185 [7687–9262] | 4/4 | 4 |
| verified | obecny | — | 123 [97–155] | 935–1209 | 4592 [3965–8763] | 1/4 | 4 |
| verified | PoC | 14 | 89 [73–166] | **0** | 7235 [6402–7391] | 4/4 | 4 |
| warm | obecny | — | 1100 [913–1378] (Qt splash) | 0 | 1347 [1199–1629] | 4/12 | 12 |
| warm | PoC | 15 | 75 [44–103] | **0** | 1347 [1148–1427] | 11/11 | 12 |
| new_version | obecny | — | 2436 [2266–3507] | 1879 [1709–4206] | 6955 [6561–8292] | 4/4 | 4 |
| new_version | PoC | 2223 [2177–8935] | 2257 [2202–3775] | **0** | 6934 [6314–13869] | 4/4 | 4 |

(Dane: runy 39318835183 i 39322360692 po 2 rundy; run 39332127323 z 3 rundami po poprawce
odświeżania splasha — §5.6. „verified" PoC jest wolniejszy w medianie — wyjaśnienie w §5.6.)

## 5. Pierwsze uruchomienie i wczesny splash (zgłoszenie PO)

### 5.1 Odtworzenie

Odtworzone na Windows (hostowany runner, Defender, EXE z CI): pierwsze uruchomienie z pustym
cache, drugie uruchomienie, kolejne, pierwsze uruchomienie nowej wersji przy starym cache,
odbudowa uszkodzonego cache (obcięty `_internal/python311.dll`). Próbkowanie okien co 20 ms
i zrzuty ekranu co 200 ms (filmstripy w artefakcie CI `windows-first-run-timeline`).

### 5.2 Oś czasu obecnego launchera (pierwsze uruchomienie, mediana z 4)

| Od – do [ms od podwójnego kliknięcia] | Co widzi użytkownik | Co się dzieje |
|---|---|---|
| 0 – ≈2000…3000 | **nic** | system i antywirus skanują nowy plik EXE 334 MB, zanim wykona się jakikolwiek kod launchera |
| ≈2000 – ≈4000 | szare okno „Preparing Metroliza for first use…" z paskiem | rozpakowanie 538 MB / 2156 plików (LZ4, 4 wątki) |
| ≈4000 – ≈6000 | **nic (1,7–1,9 s)** | start `metroliza.exe` (supervisor, PyInstaller) z nowo zapisanych DLL, hash ≈94 MB komponentów, start `metroliza_application.exe`, import PyQt |
| ≈6000 – ≈6700 | Qt splash z kaczuchą — **kaczucha stoi** | import i budowa okna głównego w wątku GUI blokują `QMovie` |
| ≈6700 | okno główne | — |

Drugie uruchomienie: okno postępu pokazuje „Preparing… for first use" z pustym paskiem przez całą
weryfikację (SHA-256 + flush 2156 plików, 2,6–7,0 s), potem 0,9–1,2 s pustki. Kolejne uruchomienia:
**0,9–1,4 s bez żadnego okna**, potem krótko Qt splash; w 8 z 12 prób okno główne nie dostało fokusu.

### 5.3 Rozbicie startu z cache (PoC, Windows, n=8)

| Etap | Czas |
|---|---:|
| launcher: payload, blokada instancji, splash, kontrola rozmiarów 2156 plików | ≈0,12 s |
| start procesu supervisora (bootloader PyInstaller + interpreter) | ≈0,43 s |
| importy supervisora + hash komponentów pakietu (≈94 MB) | ≈0,1 + 0,1 s |
| start procesu aplikacji (Popen + bootloader + interpreter) | ≈0,27 s |
| aplikacja: PyQt, okno główne, `show()` | ≈0,33 s |

Warstwa supervisora to ≈0,65–0,9 s z ≈1,3 s ciepłego startu — największa pojedyncza pozycja.

### 5.4 Projekt i PoC: splash w launcherze

- **Gdzie:** natywny launcher (Rust, Win32/GDI), od razu po kontroli pojedynczej instancji —
  przed rozwiązaniem katalogu cache, kontrolą „warm", weryfikacją i rozpakowaniem. Nie zależy od
  Pythona, Qt ani rozpakowanego runtime.
- **Animacja:** istniejący asset kaczuchy (`encoded_loading_gif`) zapisany w launcherze jako GIF
  (test pilnuje identyczności z assetem aplikacji), dekodowany raz do klatek i animowany na
  własnym wątku z własną pętlą komunikatów — tańczy niezależnie od rozpakowywania, hashowania,
  startu supervisora i od zajętego wątku GUI aplikacji.
- **Etap i postęp:** „Preparing Metroliza for first use…" z postępem rozpakowania, „Checking
  Metroliza files…" z postępem weryfikacji (dotąd pasek stał), „Repairing Metroliza…", potem etapy
  aplikacji („Starting Metroliza interface…", „Loading main window…") wysyłane przez `WM_COPYDATA`.
- **Przekazanie bez przerwy i bez dwóch splashy:** launcher przekazuje uchwyt okna w
  `METROLIZA_LAUNCHER_SPLASH_HWND`; aplikacja sprawdza klasę okna, nie tworzy własnego Qt splasha,
  po pierwszym malowaniu okna głównego wysyła `MSG_HANDOFF` z uchwytem okna głównego; launcher,
  który ma prawo do pierwszego planu, przenosi fokus na okno główne i zamyka splash. Supervisor
  zamyka splash przed własnym komunikatem błędu; launcher zamyka go przed swoim błędem, po wyjściu
  aplikacji i po 120 s bez przekazania.
- **DPI:** proces launchera per-monitor-v2 (dynamicznie, starsze systemy startują), rozmiar ze
  skalą systemu.

### 5.5 Wynik PoC (Windows)

- Splash widoczny **44–129 ms** od utworzenia procesu przy starcie z cache i ≈50 ms od startu kodu
  przy pierwszym uruchomieniu (wcześniej nic nie da się pokazać — patrz §5.2, pierwszy wiersz).
- **Zero pustych okresów** po pierwszym oknie we wszystkich scenariuszach (obecnie 0,9–4,2 s).
- **Zero nakładających się splashy**; fokus w oknie głównym we wszystkich próbach PoC.
- Animacja: zrzuty co 200 ms różnią się w obszarze kaczuchy w 95–97% par (obecny Qt splash: 0–25%).
- Okno główne przy starcie z cache: bez zmian (1347 vs 1347 ms mediana).
- Odbudowa uszkodzonego cache: PoC 2/2; obecny launcher 1 z 2 prób zakończył kodem 102
  „cannot replace a runtime still in use" (osobne ryzyko niezawodności, §10).

### 5.6 Warunki przed produkcyjnym PR

- **Drugie uruchomienie (verified):** mediana okna głównego PoC 7,2 s vs 4,6 s obecnie (n=4, obecny
  wariant dwumodalny 2,6–7,0 s). Pierwsza wersja PoC odświeżała całe okno co 50 ms i tworzyła fonty
  przy każdym malowaniu; poprawiono (10 Hz, fonty raz) i zmierzono ponownie w 3 rundach
  (run 39332127323) — wynik w §4. Kryterium odbioru: weryfikacja PoC nie wolniejsza niż obecna
  (mediana z ≥6 prób), narzut splasha <1% CPU.
- Testy jednostkowe launchera (Linux) i `cargo check` dla Windows przechodzą; kwalifikacja
  `qualify_windows_launcher.py` i `qualify_windows_portable_onefile.py` wymaga uruchomienia z nowym
  launcherem (nie uruchomiono).
- Opóźnienie przed startem kodu (2,2–3,9 s na świeżym pliku) zależy od rozmiaru EXE i skanera.
  Zmniejsza je tylko mniejszy payload (np. cv2 75 MB, dwie kopie OpenBLAS po 20 MB) lub reputacja
  podpisu — osobna decyzja (#1097/#1101, brak certyfikatu).

## 6. Mapa batchingu i współbieżności

**etap → batching → model wykonania → workery → ograniczenia → zmierzony zysk → decyzja**

| Etap | Batching dziś | Model dziś | Workery dziś | Ograniczenia | Zmierzony zysk | Decyzja |
|---|---|---|---|---|---|---|
| Review: inspekcja pliku (hash, probe parsera) | brak, plik po pliku | QThread szeregowo | 1 | PyMuPDF nie w wielu wątkach → procesy; generacja rejestru parserów per proces | 38 s → 11,6 s (4) / 9,4 s (8) | **równolegle w procesach**, paczki ≈24 pliki, kolejność wyników deterministyczna |
| Review: szybki odczyt metadanych | brak | QThread szeregowo, ponowny hash i PDF | 1 | jw.; odczyty nakładane na tabelę w GUI | 50 s → 18,5 s (4) / 14 s (8) | **równolegle**, docelowo jeden przebieg na plik (inspekcja + metadane) |
| Import: filtr planu (ponowna weryfikacja plików) | brak | szeregowo przed pulą | 1 | musi wykryć zmianę pliku | niezmierzone osobno | połączyć z prepare w puli |
| Import: prepare (parse) | okno 3×workery | pula spawn | min(3, cpu−1), EXE: 0 | spawn na Windows (#1138: 0,73–1,98×) | #1132 | zostawić; próg i liczba z budżetu (§6.1) |
| Import: zapis SQLite | commit per raport, checkpoint co ≥25 commitów/2 s | jeden pisarz | 1 | jeden pisarz na plik, WAL | #1137 | **szeregowo — właściwe** (SQLite: jeden pisarz) |
| Characteristic Mapping: metryki | N+1 zapytań | GUI | — | — | 764 s → 2,3 s | jedno zapytanie + worker + kaczucha |
| Grouping: budowa grup | pandas `agg` z lambdą | GUI | — | — | — (do pomiaru w PR) | wektoryzacja + worker |
| Filter: DISTINCT (14 list) | cache LRU | QThread, zapytania kolejno | 1 | odczyty SQLite mogą iść równolegle na osobnych połączeniach | — | 2–4 połączenia tylko do odczytu, wypełnianie list partiami |
| Export Main plots: zapis XLSX | bulk + stream (#1131) | QThread | 1 | XlsxWriter jednowątkowy | #1131 | zostawić |
| Export Extended: render grup | kolejka 2×workery | pula spawn **odtwarzana per referencja**, 1. grupa szeregowo, próg 8/40 grup per referencja | 2 (max 4) | wynik odrzucany przy zmianie przełączników gęstości | 220 → 96 s (4) → 88 s (8) | **jedna pula na eksport**, workery z budżetu, próg na cały eksport |
| Export z dashboardem HTML: render | brak | **zawsze szeregowo** (`serial_output_mode`) | 1 | dashboard zbiera wyniki w procesie głównym | — | równoległy render + zbieranie w kolejności |
| CSV Summary: wczytanie | 50 000 wierszy na `executemany` | QThread, pętla Pythona | 1 | parsowanie CSV w Pythonie | — | szybszy parser (np. moduł `csv` → `executemany` partiami już jest; rozważyć wczytanie kolumnowe/Arrow) |
| CSV Summary: analityka | etapy szeregowo | QThread + wątki statystyk (#1133) | ≤ rdzenie | workbook i dashboard niezależne po kohortach | — | dashboard i workbook równolegle; profil w PR |
| Industrial → CSV Summary | — | GUI | — | EAV, facety | — | worker + SQL `INSERT…SELECT`, cache COUNT |
| Realtime: cykl polla | paczki 500, limit 5000/cykl | QThread na cykl, źródła szeregowo | 1 | źródło zewnętrzne | niezmierzone (brak źródła) | źródła równolegle po zmierzeniu |
| Start: rozpakowanie / weryfikacja | pliki od największych | wątki Rust | clamp(cpu, 2, 8) | dysk, AV | — | zostawić; weryfikację rozważyć w tle (decyzja §9) |
| Start: rozgrzewka modułów | moduł po module | **wątek GUI** | — | importy pod GIL | zastój 636 → 171 ms | **wątek tła** |

### 6.1 Wspólny budżet zasobów (propozycja)

- **CPU:** jeden „budżet rdzeni" dla aplikacji = `max(1, rdzenie_fizyczne − 1)`; pule (prepare,
  render, review) pobierają z niego tokeny; równoległe operacje (import + eksport) dzielą budżet,
  a GUI zawsze ma jeden rdzeń. Dziś każda pula liczy osobno (prepare do 3, render 2, ONNX
  `min(4, cpu−1)`, rayon wszystkie rdzenie, BLAS w każdym procesie wszystkie rdzenie).
- **BLAS/OpenMP/ONNX/rayon w workerach:** w initializerze puli ustawić 1 wątek (`OMP_NUM_THREADS`,
  `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, ONNX intra-op) i `RAYON_NUM_THREADS`; w procesie
  głównym limit = budżet. Zmierzyć w PR (test BLAS=1 z tego audytu jest nieważny).
- **RAM:** limit kolejki = 2× workery (już), plus próg pamięci na proces renderu (≈280 MB RSS na
  worker zmierzone) — liczba workerów = min(budżet CPU, wolna_RAM / 300 MB).
- **I/O:** jeden pisarz SQLite na plik; odczyty równoległe tylko na osobnych połączeniach
  `query_only`.
- **Próg opłacalności:** pula dopiero, gdy praca > koszt startu (spawn + import ≈0,4–0,8 s/proces na
  Windows); progi liczone na cały eksport/import, nie per referencję.

### 6.2 Kontrakty współbieżności (zweryfikowane w kodzie)

- **Qt:** widgety tylko w wątku GUI; workery to QThread z sygnałami (połączenia kolejkowane);
  postęp importu deduplikowany do całych procentów, skanu — **nie** (2 sygnały na plik i
  restyle przycisków na każdy); `ExportDataThread` woła `QCoreApplication.processEvents()` z wątku
  workera (do usunięcia).
- **GIL:** CPython 3.11 z GIL; jedyny kod natywny zwalniający GIL to `distribution_fit_ad` (rayon);
  pozostałe crate'y trzymają GIL → dla CPU tylko procesy.
- **PyMuPDF:** kod nie uruchamia go w dwóch wątkach (kolejkowanie metadanych za skanem); PoC puli
  procesów (każdy proces ma własne dokumenty) dał identyczne wyniki.
- **Matplotlib:** backend Agg; render w procesach (pula) lub w workerze; brak rysowania w GUI.
- **SQLite:** WAL + `synchronous=NORMAL`, `busy_timeout` 5 s, jeden pisarz importu z kadencją
  checkpointów; połączenia nie są współdzielone między wątkami (brak `check_same_thread=False`);
  `ensure_report_schema` (≈32 ms, transakcja zapisu) wołane w GUI przy otwieraniu okien — ryzyko
  blokady przy aktywnym imporcie.
- **Blokujące oczekiwania w GUI:** `ModifyDB` zamykanie: `wait(3000)` + nieograniczony `wait()`;
  w pozostałych flow brak `join()/wait()/result()` w GUI podczas pracy.

## 7. Kaczucha: pełna lista luk (operacje >1 s)

Rodzaje luk: **BRAK** wskaźnika; **SPÓŹN.** (pokazuje się później niż ≈1 s od kliknięcia);
**STOI** (animacja zamrożona przez zajęte GUI); **LIFECYCLE** (zły cykl życia).

| Flow | Operacja | Czas | Obecny loading | Luka | Przyczyna | Miejsce poprawki | Kryterium odbioru |
|---|---|---:|---|---|---|---|---|
| GRP-MAP | otwarcie dopasowania nazw | 764 s | brak | BRAK, STOI | N+1 w wątku GUI | `characteristic_mapping_service.py:166`, dialog `:590` | ładowanie w workerze; kaczucha ≤1,1 s od kliknięcia; animacja ≥90% klatek |
| IND-05 | Industrial → CSV Summary | 43,6 s | brak | BRAK, STOI | bridge + 4× COUNT w GUI | `industrial_data_dialog.py:883`, `industrial_tabular_bridge.py:104`, `industrial_analytics_dialog.py:2267` | jw. |
| GRP-OPEN | otwarcie grouping | 5,8 s | brak | BRAK, STOI | pandas w GUI | `data_grouping.py:148-716`, `data_grouping_service.py:116` | jw. |
| FLT-OPEN | ładowanie wartości filtra | 5,6 s | tekst | BRAK (tekst zamiast kaczuchy) | — | `filter_dialog.py:894-966` | kaczucha nieblokująca w dialogu od 1 s |
| DB-RECORDS | ładowanie rekordów 216k | 12,6 s | baner | BRAK (baner bez animacji) | — | `modify_db.py:641-760` | kaczucha nieblokująca |
| IND-01 | otwarcie Industrial Data | 2,9 s | brak | BRAK, STOI | import `oznak`, COUNT-y w GUI | `industrial_data_dialog.py:678-718` | otwarcie <0,5 s lub worker + kaczucha |
| RT-01 | pierwsze otwarcie Realtime | 1,5 s | brak | BRAK, STOI | import modułu i stan bazy w GUI | `main_window.py:1160`, rozgrzewka | rozgrzewka w tle obejmuje moduł; otwarcie <0,5 s |
| DB-OPEN | otwarcie Modify DB | 0,9 s (Linux; Windows wolniej) | brak; puste okno | BRAK, STOI | wypełnianie tabel w GUI | `modify_db.py:490-571` | puste okno nie dłużej niż 100 ms; dane w workerze |
| IMP-META | szybki odczyt metadanych (1500) | ≈50 s | licznik w tabeli | BRAK (dla operacji w tle) | — | `parsing_dialog.py:977-1040` | nieblokująca kaczucha w pasku statusu Reports |
| IMP-SCAN | Review reports | 2–38 s | kaczucha-op. | SPÓŹN., STOI | timer od `show()` po starcie wątku; restyle przy każdym pliku | `parsing_dialog.py:841-875`, `ui_foundation.py:680` | kaczucha ≤1,1 s od kliknięcia; ≥90% klatek |
| IMP-RUN | import | 4,8–68 s | kaczucha-op. | SPÓŹN. (plan ×3 w GUI przed timerem); etykieta 15% nieaktualna | — | `parsing_dialog.py:1127-1226` | jw.; etykieta etapu „Checking selected files" |
| EXP-RUN | 1. eksport w sesji | 6,8 s + eksport | kaczucha-op. od 7,8 s | SPÓŹN., STOI | import modułu eksportu w GUI przed `show()` | `export_dialog.py:98-102, 1318-1393` | kaczucha ≤1,1 s także przy 1. kliknięciu |
| EXP-RUN (dashboard) | eksport HTML | — | kaczucha-op. | ApplicationModal blokuje inne okna | — | `export_dialog.py:1368` | NonModal jak w Reports |
| CSV-03 | wczytanie CSV | 24,7 s | kaczucha-op. | STOI (przerwa 0,40 s); zamknięta przed nałożeniem wyniku | `_close_worker_progress` przed `_apply_tabular_load_result` | `industrial_analytics_dialog.py:2457-2489` | kaczucha do końca nakładania wyniku |
| CSV-09 | Create analytics | 228 s | kaczucha-op. | STOI na końcu (1,9 s, 1,3 s) | składanie wyniku w GUI | `industrial_analytics_dialog.py:2618` + workflow | zastój <100 ms |
| CSV-06 | podgląd wartości | — | kaczucha-op. tworzona na każde zaznaczenie | LIFECYCLE (dialog i QMovie nie zwalniane) | — | `tabular_analytics_filter_dialog.py:787-793` | dialog zwalniany, QMovie zatrzymany |
| IND-07 | eksport cache | — | kaczucha-nat. | miganie przy krótkich; pasek stoi na 0 | brak opóźnienia i postępu | `industrial_export_dialog.py:457-488` | wspólny mechanizm z progiem 1 s; postęp per paczka |
| IND-04 | pobieranie Oznak | sieć | tekst | BRAK | — | `industrial_sync_dialog.py:1052-1298` | nieblokująca kaczucha + postęp paczek (nie zmierzono: brak źródła) |
| SHELL-START | start aplikacji | 1,2–9 s (Windows) | Qt splash od ≈1 s (warm) | BRAK (0,9–1,9 s pustki), STOI | splash dopiero po PyQt, w wątku GUI | launcher (PoC) | PoC: splash ≤150 ms, 0 ms pustki |
| SHELL-START | gotowość po pierwszym malowaniu | 1,3–3,3 s | status bar | STOI GUI (0,64 s) | rozgrzewka w GUI | `main_window.py:263-291` | zastój <200 ms (PoC 171 ms) |
| Wszystkie z kaczuchą | — | — | — | LIFECYCLE | `QMovie.start()` przy tworzeniu, brak `deleteLater` | `worker_progress_dialog.py:57, 103-128` | movie tylko gdy widoczny; dialog zwolniony po zakończeniu |
| SHELL-THEME, GRP-EDIT, GRP-MAPEDIT, DB-APPLY (wiele zmian), VIS-01, TOOL-PLUGIN | — | czas niezweryfikowany (>0,5 s przy małych danych) | brak | BRAK (gdy >1 s) | praca w GUI | jw. w macierzy | pomiar w PR; przy >1 s — worker + kaczucha |

Realtime: ciągły monitoring ma chip stanu (właściwe — to nie jest skończona operacja); skończone
etapy (pierwsze otwarcie, przebudowa po zmianie bazy) potrzebują kaczuchy.

## 8. Ranking optymalizacji

Zysk = zmierzony (Z) albo szacowany (S, z udziałem hotspotu w całym flow). Pewność: W/Ś/N.

| # | Optymalizacja | Przyczyna | Wpływ na użytkownika | Zysk | Pewność | Koszt | Ryzyko | Zależności | Sprawdzenie |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | Characteristic Mapping: jedno zapytanie + worker | N+1 | 12,7 min → ≈3 s, bez zawieszenia | Z: 330× | W | S (1 dzień) | niskie | — | test równoważności (pełny na małej, próbka na dużej) |
| 2 | Natywny splash + przekazanie | brak okna przed Pythonem/Qt | widoczny start zawsze <150 ms; brak pustki | Z | W | Ś (PoC gotowy) | średnie (Win32) | kwalifikacja launchera | job `windows-first-run-timeline`, ≥6 prób |
| 3 | Review reports w puli procesów, 1 przebieg na plik | szeregowo + powtórzone hashe/PDF | 104 s → ≈30 s (1500) | Z: 2,9–3,7× | W | Ś | średnie (rejestr parserów w procesach) | budżet CPU | identyczne wpisy i odczyty |
| 4 | Industrial → CSV Summary: COUNT raz, facety w SQL, worker | 4× COUNT, pętle Pythona po 1M wartości | 43,6 s zamrożenia → kilka s w tle | S: ≥4× | Ś | Ś | średnie | — | zgodność facetów i metadanych |
| 5 | Extended plots: jedna pula na eksport, workery z budżetu, równoległy dashboard | pula per referencja, max 2/4, dashboard szeregowo | 552 s → ≈200 s (S, 4 workery) | Z (48 grup): 2,3–2,5× | Ś | Ś | średnie (pamięć ≈280 MB/worker) | budżet RAM | hash treści XLSX/HTML |
| 6 | Grouping: wektoryzacja + worker | lambda per grupa | 5,8 s → <1 s (S) | S | Ś | M | niskie | — | identyczne grupy |
| 7 | Wspólny mechanizm kaczuchy | timer od `show()`, GUI blokowane, lifecycle | kaczucha zawsze ≈1 s od kliknięcia | Z (pomiar luk) | W | Ś | niskie | 1–6 | harness: `visible_ms` ≤1100, klatki ≥90% |
| 8 | Rozgrzewka w tle + moduł eksportu i realtime w rozgrzewce | importy w GUI | zastój 0,64 → 0,17 s; 1. eksport bez 6,8 s blokady | Z | W | M | niskie (importy z obiektami Qt) | — | stall probe; test importu w wątku |
| 9 | Industrial Data: status `oznak` bez importu | import 1,8 s | 2,9 → ≈1 s | Z (profil) | W | M | niskie | — | profil |
| 10 | Wyłączyć automatyczne obniżanie gęstości wykresów albo uczynić je decyzją użytkownika | `_apply_bottleneck_optimizations` | wynik nie zależy od szybkości maszyny | — (jakość) | W | M | niskie | decyzja PO | test deterministyczności |
| 11 | Supervisor: krótszy start (bez drugiego pełnego hasha przy ciepłym, zweryfikowanym cache) | 2 procesy PyInstaller + hash | −0,1…−0,6 s na każdy start | S | Ś | Ś–D | średnie (integralność) | decyzja PO | oś czasu Windows |
| 12 | Weryfikacja drugiego startu w tle | 2,6–7 s blokady | −2,6…−7 s przy 2. starcie | S | N | Ś | wysokie (trwałość) | decyzja PO | test przerwania zasilania |
| 13 | Modify DB: model/view i ładowanie w workerze dla tabel normalizacji | 6609 itemów w GUI | 0,9 s → <0,2 s | S | Ś | M | niskie | — | golden #1121 |
| 14 | Import: filtr planu w puli; plan bez potrójnej walidacji w GUI | szeregowo przed pulą; GUI 249 ms | −5…10% importu; brak zastoju | S | Ś | Ś | średnie | 3 | identyczne wiersze |
| 15 | OCR w EXE: trwały worker zamiast procesu na wywołanie | spawn + model na raport | tryb Complete: duży (niezmierzony) | S | N | D | średnie | Windows | pomiar z prawdziwym OCR |
| 16 | Kod natywny w EXE (`auto` = Python) | polityka frozen | statystyki porównawcze: #1120 pkt 10 | S | N | D | średnie | #908, parytet | benchmarki natywne w EXE |
| 17 | Budżet wątków BLAS/ONNX/rayon w workerach | nadsubskrypcja | do zmierzenia | S | N | M | niskie | 5 | test BLAS=1 ponownie |
| 18 | `ensure_report_schema` szybka ścieżka (wersja schematu) | DDL + transakcja przy każdym otwarciu | −30 ms/okno; brak blokady pisarza | Z (32 ms) | W | M | niskie | — | migracje |
| 19 | CSV Summary: profil i równoległy dashboard/workbook | etapy szeregowo | 228 s → ? | S | N | Ś | średnie | 7 | profil w PR |
| 20 | Motyw: odświeżanie tylko aktywnych okien, bez `findChildren` per okno | pełny restyle | 0,58 s → ? | S | N | M | niskie | — | pomiar |

## 9. Plan PR-ów

**Baza wszystkich PR-ów:** gałąź referencyjna #1142 (`integrate/2026.09-rc1-build-261018`) do czasu
landowania #1109 i #1142, potem `develop`. **Baseline:** `scripts/benchmark_ui_flows.py` (Linux, te same dane
syntetyczne, mediana z 3) i `windows-first-run-timeline` (Windows) na bazie PR-a; pomiar „po" na tej samej
maszynie i w tym samym stanie cache. Każdy PR zachowuje semantykę danych; zmiana jakości/zakresu wymaga
osobnej decyzji (partia E).

### Partia A — splash i responsywność

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| A1 Splash launchera | `packaging/launcher/**` (splash, Progress, log), `app/launcher_splash.py`, `app/startup_splash.py`, supervisor (zamknięcie przed komunikatem), THIRD_PARTY_NOTICES (`gif`) | warm: 1,1 s bez okna → splash ≤150 ms; cold: 1,9–3,9 s pustki → 0; fokus 3/8 → 100% | maszyna stanów cache bez zmian (cold/verified/warm/repair, kod 75); błąd launchera: splash zamknięty przed MessageBoxem; brak splasha dla drugiej instancji; weryfikacja nie wolniejsza (§5.6) | kaczucha od ≤100 ms po starcie kodu do okna głównego; jeden splash; etap i postęp | `cargo test`, `qualify_windows_launcher.py`, `qualify_windows_portable_onefile.py`, `test_launcher_splash.py`, job osi czasu (≥6 prób) |
| A2 Rozgrzewka poza GUI | `ui/main_window.py` (wątek tła), lista modułów + eksport i realtime | zastój po 1. malowaniu 0,64 s → <0,2 s; 1. eksport 6,8 s blokady → 0 | żaden moduł nie tworzy obiektów Qt przy imporcie (test importu w wątku); błędy importu jak dziś | status bar „Loading tools…" bez zamrożenia | stall probe, `test_main_window_*`, test importu w wątku |
| A3 Wspólna operacja z kaczuchą | `ui/worker_progress_dialog.py` + 13 flow z §7 | `visible_ms` 1,07–7,76 s od kliknięcia → ≤1,1 s; klatki 40–97% → ≥90%; dialogi żywe po końcu → zwolnione | anulowanie, błąd, zamknięcie okna, ponowienie i spóźnione sygnały nie zostawiają dialogu; brak migania <1 s | próg od kliknięcia, etap, postęp lub tryb nieokreślony, throttling 20 Hz, wariant nieblokujący | harness (kryteria z kolumny), testy cyklu życia dialogu |

### Partia B — szybkie duże zyski

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| B1 Characteristic Mapping | `reports/characteristic_mapping_service.py` (jedno zapytanie), dialog w workerze | 764 s → <5 s (1500 raportów) | identyczna lista metryk, liczności i próbki referencji (porządek `LOWER(reference), reference`) na schemacie bieżącym i legacy | kaczucha przy otwarciu | test równoważności z PoC, testy serwisu |
| B2 Industrial → CSV Summary | `industrial_tabular_bridge.py`, `industrial_analytics_dialog.py` (`_sync_ui_state`) | 43,6 s zamrożenia → otwarcie <1 s + praca w tle ≤10 s | identyczne metadane pól, facety i liczności; COUNT liczony raz na zmianę filtra | kaczucha z etapem „Preparing cached data" | testy bridge, `test_industrial_*`, harness `industrial_bridge` |
| B3 Grouping | `tabular/data_grouping_service.py`, `ui/data_grouping.py` | 5,8 s → <1 s | identyczne grupy, klucze, kolejność i zapisany stan | kaczucha, jeśli >1 s | testy grouping, harness `grouping_open` |
| B4 Industrial Data | `ui/industrial_data_dialog.py`, `oznak_adapter.get_oznak_adapter_status` | 2,9 s → <1 s | ten sam tekst statusu (dostępność pakietu bez importu; pełny import przy pierwszym użyciu) | — | testy dialogu |
| B5 Modify DB | tabele normalizacji jako model/view + ładowanie w workerze | 0,96 s (puste okno 0,54 s) → okno z treścią <0,3 s | golden #1121, zmiany i undo jak dziś | baner/kaczucha | `test_modify_db*`, harness |

### Partia C — batcher, pipeline, współbieżność

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| C1 Budżet zasobów | nowy moduł `shared/compute_budget.py`; pule prepare/render/review; env wątków w initializerach | brak → jedna liczba workerów z budżetu; BLAS/ONNX/rayon=1 w workerach | wyniki identyczne przy 1/2/4/8; GUI <100 ms zastoju przy pełnym CPU | — | testy pul, pomiar 1/2/4/8 |
| C2 Review w puli | `parsing/preflight.py`, `parsing/metadata_review.py`, `ui/parsing_dialog.py` | 1500 PDF: 104 s → ≤35 s (4 workery) | identyczne wpisy preflight (z deduplikacją w kolejności), odczyty i zatwierdzone override'y; wykrycie zmiany pliku jak dziś; generacja rejestru parserów zgodna | postęp per paczka, wyniki strumieniowo do tabeli | PoC `poc_review_parallel.py` jako test, `test_parsing_dialog_*`, #1143 regresje stron |
| C3 Extended plots | `exporting/export_summary_render_pool.py`, `export_data_thread.py` | 48 grup: 149 s (2) → ≤100 s (4); 216 grup: 552 s → ≤250 s; dashboard dziś szeregowo → równolegle | identyczny XLSX/HTML (hash treści); kolejność zapisu; brak odrzucania wyników przy zmianie przełączników; anulowanie | postęp per grupa | `scale_export.py` jako test, `test_export_*`, #1130 parytet PNG |
| C4 Import | `parse_reports_thread.py` (filtr planu w puli), `parsing_dialog.py` (plan raz) | zastój startu 249 ms → <50 ms; −5…10% czasu (S) | identyczne wiersze DB, wykrycie zmiany pliku, kolejność commitów | etykieta etapu zamiast stałych 15% | `test_import_*`, #1132/#1137 testy |

### Partia D — głębsze hotspoty

| PR | Zakres | Baseline → cel | Warunki poprawności | Regresja |
|---|---|---|---|---|
| D1 Render wykresów | matplotlib: cache fontów, jeden `draw` na wykres, kompresja PNG | 2,5–6,8 s/grupę → −30% (S) | parytet PNG/obrazów wg #1126 | `test_export_*`, porównanie obrazów |
| D2 CSV Summary | profil 228 s; dashboard i workbook równolegle; wczytanie CSV | 228 s / 24,7 s → do ustalenia z profilu | statystyki identyczne (#1133) | `benchmark_csv_pipeline.py`, testy CSV |
| D3 OCR w EXE | trwały worker OCR zamiast procesu na wywołanie | niezmierzone (Windows + OCR) | identyczne wyniki OCR, izolacja Job object | kwalifikacja OCR Windows |
| D4 Kod natywny w EXE | `METROLIZA_ENABLE_NATIVE_IN_FROZEN` / promocja per most | #1120 pkt 10 | parytet Python/native (#908) | testy parytetu, benchmarki |

### Partia E — zmiany strukturalne wymagające decyzji PO

| PR | Decyzja | Szacowany zysk | Ryzyko |
|---|---|---|---|
| E1 Gęstość wykresów | czy automatyczne „reduced" zależne od szybkości maszyny zostaje, staje się opcją, czy znika | determinizm wyniku; brak odrzucania pracy workerów | jakość vs czas |
| E2 Supervisor | pominąć drugi hash przy zweryfikowanym ciepłym cache / scalić rolę z launcherem | −0,1…−0,6 s na każdy start | integralność, nadzór awarii |
| E3 Weryfikacja 2. startu w tle | start aplikacji przed końcem SHA-256 + flush | −2,6…−7 s przy 2. starcie | trwałość po utracie zasilania |
| E4 Mniejszy payload | cv2 (75 MB), dwie kopie OpenBLAS (2× 20 MB), inne | krótszy skan AV i rozpakowanie (proporcjonalnie do bajtów) | funkcje OCR, zależności |

## 10. Obszary nieweryfikowane

| Obszar | Czego brakuje |
|---|---|
| Czysty laptop Windows z antywirusem użytkownika (#1101 A5) | fizyczny sprzęt; tu tylko hostowany runner |
| Realne raporty klientów, realny OCR (tryb Complete), PDF wielostronicowe z prawdziwymi układami | dane klienta (poufne) i środowisko z OCR na Windows |
| Industrial Data: pobieranie Oznak (IND-04), realtime z prawdziwym źródłem (RT-03), Google Sheets | źródło produkcyjne, konto Google |
| QWebEngine (VIS-01) | środowisko z GPU/okienkowe |
| Zimny dysk / dysk sieciowy | dane były na tmpfs |
| Kwalifikacja launchera PoC (`qualify_windows_launcher.py`, portable) | nie uruchomiono z PoC |
| Test BLAS=1 w workerach | pomiar unieważniony, nie powtórzono |
| Wersje bibliotek w EXE vs venv deweloperski | `requirements.txt` ma zakresy; CI instaluje najnowsze zgodne |
| Odbudowa cache: „cannot replace a runtime still in use" (1 z 2 prób obecnego launchera) | powtarzalność i przyczyna (proces, AV czy Restart Manager) |
| Scenariusze n=1 w §4 | brak powtórzeń dla części flow (seria 3-krotna opisana w §4) |

## 11. Modele i delegacja (faktycznie użyte)

- Koordynator: **Claude Opus 5.5** (`claude-opus-5-5`), effort **max** (ustawiony przez użytkownika).
- Inwentaryzacja (tylko odczyt, równolegle maks. 2): 3 × **Claude Sonnet 5.5** (`bounded_worker`,
  effort high): A1 rdzeń UI, A2 dane UI, B nie-UI i mapa współbieżności. Trzeci przerwał na limicie
  sesji i został wznowiony.
- Niezależna weryfikacja kompletności i propozycji: §12.
- GPT (Codex) nie był użyty do implementacji: tygodniowy limit Codex był wykorzystany w 79%
  (obserwacja 2026-10-19 17:52 UTC, reset 2026-10-25); zachowano go dla innych prac.

## 12. Niezależna weryfikacja

(Wynik przeglądu niezależnego — uzupełniony po jego zakończeniu.)

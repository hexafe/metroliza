# Metroliza — Performance Boost STEP2: audyt, pomiary, PoC i plan wdrożenia

- **Status:** audyt zakończony; PoC na gałęzi `perf/step2-audit` (draft PR #1149). Pakiet wdrożeniowy P01–P14
  na gałęzi `perf/step2-boost` (2026-10-21); porównanie przed STEP1 / po STEP1 / po STEP2: §4.2; build testowy
  2026.09 RC1 261021 dla PO. Nic nie zostało zmergowane.
  Pomiary Linux w profilu energii `balanced` (2026-10-20/21); porównanie z poprzednią wersją (build 261019) w
  tym samym profilu: §4.1.
- **Właściciel:** koordynator audytu wydajności (Claude Opus 5.5, Claude Code). Decyzje produktowe: PO.
- **Data:** 2026-10-20 (czasy: Warszawa, UTC+2, jeśli nie zaznaczono UTC); liczby z Linuksa pochodzą z
  przebiegu 05:54–06:17 w profilu energii `balanced` (§3.3).
- **Baza audytu:** `78d5d775756e4b64530ce8fb04f175a2e3f461f1` = head PR #1142
  (`integrate/2026.09-rc1-build-261018`): 2026.09 RC1 build 261020 + naprawa spawn w launcherze.
- **Testowany EXE PO:** `metroliza_2026.09rc1_261020_launcher.exe`, SHA-256 `9b8cb752…5e266`, z `e4a739b8`
  (provenance `dirty: false`, CI 39286831429). Pomiary Windows w raporcie pochodzą z EXE budowanych w CI z
  gałęzi PoC: ten sam onedir pakowany starym (`78d5d775`) i nowym launcherem.
- **Dokumenty:** macierz [`performance-boost-step2-flows.md`](performance-boost-step2-flows.md);
  liczby (mediany, rozrzut, n, obciążenie, runy CI): [`performance-boost-step2-measurements.json`](performance-boost-step2-measurements.json).
- **Tracker:** Issue #1148 „Performance Boost STEP2" (powiązane z #1120, #952, #918, #1101); draft PR #1149.

## 1. Podsumowanie dla PO

### 1.1 Największe zmierzone straty czasu

Od kliknięcia do użytecznego wyniku. Dane syntetyczne (bez danych klientów). „Linux" = źródła, Qt
offscreen, Xeon W-10855M (6 rdzeni / 12 wątków); „Windows" = EXE na hostowanym runnerze CI (4 vCPU,
Defender). Mediana [min–max], n = liczba prób.

> **Czasy z Linuksa:** profil energii `balanced` (2026-10-20 05:54–06:17; 1 wątek do 4,7–4,8 GHz, wszystkie
> wątki 4,0–4,1 GHz). Względem poprzedniej wersji (2026.09 RC1 build 261019), zmierzonej w tym samym profilu
> na przemian z obecną, nie ma regresji (§4.1). Pomiarów Windows (start) to nie dotyczy. §3.3.

| # | Gdzie użytkownik czeka | Zmierzony czas | Przyczyna | Najlepszy zmierzony wariant |
|---:|---|---:|---|---|
| 1 | Reports → „Match Characteristic Names" (1500 raportów, 2664 metryk) | **163 s zamrożenia GUI** (n=1) | 1 + 2664 zapytań, każde skanuje widok pomiarów, w wątku GUI | jedno zapytanie (funkcja okna): **0,44 s** [0,44–0,55] (n=3); próbka 30 metryk identyczna, mała baza w pełni identyczna |
| 2 | Export „Extended plots" (50 raportów, 216 grup) | **130 s**, RSS 962 MB (n=1) | ≈1,0 s renderu na grupę w jednym procesie (układ tekstu i fonty matplotlib, kompresja PNG, dopasowania scipy); pula 2 procesów tworzona od nowa dla każdej referencji; z dashboardem HTML render zawsze szeregowo | 48 grup: 49,7 s (1 proces) → 35,3 s (2, dziś) → 25,3 s (4) → 24,8 s (8), ta sama treść XLSX; z dashboardem przy 4: **50,7 s szeregowo** |
| 3 | CSV Summary → „Create analytics" (100k wierszy) | **50,3 s** [49,9–51,2] (n=3), RSS 640 MB | dopasowania rozkładów scipy (MLE, Nelder–Mead) na pełnych danych, liczone osobno dla histogramu i tabeli statystyk; konwersje liczb w pętli Pythona | plan D2 (§9) |
| 4 | Export „Main plots" (1500 raportów, 216k wierszy) | **28,6 s** [27,9–29,3] (n=3), RSS 763 MB | eksport + przy 1. kliknięciu 1,7 s importu modułu w GUI | plan A2/D1 |
| 5 | Reports → „Review reports" (1500 PDF) | **25,6 s** [22,3–25,8] (n=3) | skan i odczyt metadanych ściśle szeregowo (sam kod: 19,2 s); reszta to GUI: sygnał i restyle na każdy plik, 0,26 s zamrożenia przy wypełnianiu tabeli | pula procesów (sam kod): **6,6 s przy 4, 5,3 s przy 8**, wynik identyczny; zysk w UI wymaga też strumieniowania i throttlingu |
| 6 | Import 1500 raportów | **12,9 s** [12,8–12,9] (n=3), RSS 398 MB | jeden zapisujący; ≈13% to sprawdzanie gotowości schematu 2× na raport, ≈8% odświeżanie rejestru parserów na raport (profil) | plan C4 |
| 7 | Industrial Data → „CSV Summary…" (cache 50k × 20 metryk) | **10,0 s zamrożenia GUI** [9,6–10,9] (n=3) | przeliczanie metadanych i facetów EAV + 4 identyczne COUNT-y w wątku GUI | plan B2 |
| 8 | Start aplikacji z cache (Windows) | **1068 ms bez żadnego okna** [954–1378] (n=14); okno główne 1341 ms | launcher → supervisor (≈0,4 s startu procesu + ≈0,2 s importów i hasha) → aplikacja | PoC: splash po **66 ms** [44–89]; okno główne 1298 ms; fokus 12/12 (dziś 6/14) |
| 9 | Pierwszy start / nowa wersja (Windows) | po oknie postępu **1954 ms pustki** [1599–3877] (n=7); nowa wersja 2081 ms [1643–4428] | rozpakowanie 538 MB, potem start supervisora i aplikacji z nowo zapisanych DLL | PoC: 0 ms pustki; pierwsze okno nie wcześniej (opóźnienie przed kodem launchera, §5.5) |
| 10 | Export → Grouping „Edit…" (1500 raportów) | **1,23 s zamrożenia GUI** [1,20–1,26] (n=3) | pandas `groupby.agg` z lambdą Pythona dla 36 000 grup | plan B3 |
| 11 | Export → Filter „Edit…" (216k wierszy) | 1,19 s [1,18–1,37] (n=3) do kompletu wartości | DISTINCT-y w workerze, wypełnianie 13 list w GUI | plan A3 |
| 12 | Pierwsze kliknięcie „Export" w sesji | **1,72 s zamrożenia GUI** [1,65–1,74] (n=3), kaczucha od 2,67 s | import modułu eksportu (matplotlib, numpy, …) w wątku GUI przed `show()` | plan A2 |
| 13 | Okno główne tuż po starcie (Linux) | GUI blokowane łącznie 402 ms, najdłużej 180 ms (n=5) | rozgrzewka 8 modułów w wątku GUI po pierwszym malowaniu | PoC wątku: 74 ms / 40 ms (n=5); gotowość o 9% później |

Pozostałe (n=3): Industrial Data open 0,78 s (48% profilowanego otwarcia to import pakietu `oznak`
dla etykiety statusu), Realtime open 0,31 s, Modify DB open 0,18 s, przełączenie motywu 0,20 s,
Export open 0,11 s — te zamrażają GUI przez cały czas; rekordy Modify DB 216k 2,67 s i wczytanie CSV 100k
4,93 s idą w wątku (najdłuższy zastój 0,08 s i 0,49 s).

### 1.2 Kaczucha: co jest nie tak

- Kaczucha jest podpięta w **8 z 60 flow UI** (8 wywołań fabryki). **7 zmierzonych operacji >1 s nie ma
  żadnego animowanego wskaźnika** (§7): Characteristic Mapping 163 s, szybki odczyt metadanych po Review
  ≈14 s (tylko licznik), Industrial → CSV Summary 10,0 s, rekordy Modify DB 2,67 s (baner bez animacji),
  Grouping 1,23 s, Filter 1,19 s (tekst), start na Windows (1,1 s bez okna przy starcie z cache, 2 s pustki
  przy pierwszym). Trzy kolejne zamrażają GUI, ale trwają poniżej 1 s: Industrial Data 0,78 s,
  Realtime 0,31 s, wypełnienie tabeli po Review 0,26 s (kaczucha już zamknięta); na docelowym laptopie
  niezmierzone.
- Tam, gdzie jest, wspólny mechanizm (`worker_progress_dialog.py`) ma cztery wady:
  1. próg 1 s liczy się od `show()`, nie od kliknięcia — pierwszy eksport: `show()` po 1,72 s, kaczucha po 2,67 s;
  2. pokazanie i animacja zależą od wątku GUI — skan 1500: 84–86% klatek, przerwy do 164 ms; wczytanie CSV:
     53–60%, do 729 ms; Create analytics: przerwa do 0,61 s; import ≈100% (dobrze);
  3. `QMovie` startuje przy tworzeniu dialogu (wszystkie wywołania) i tam, gdzie nie jest zatrzymywany,
     działa po ukryciu (skan: ok. 150 klatek w tle); dialog nie jest zwalniany w Reports (skan, import) i w
     podglądzie wartości CSV-06; w Export i CSV-03/07/09 jest zwalniany;
  4. zamknięcie przed nałożeniem wyniku w GUI: CSV-03 i Review (0,26 s zamrożenia po zamknięciu kaczuchy).
- Start: obecny Qt splash pojawia się dopiero po imporcie PyQt i stoi w trakcie budowy okna — na Windows
  tylko 17 z 58 par zrzutów (co 200 ms, 40 prób) różniło się w obszarze kaczuchy, bezruch do 1,28 s
  (PoC: 1087 z 1088 par).

### 1.3 Wyniki PoC

| PoC | Wynik | Zgodność | Decyzja |
|---|---|---|---|
| Natywny splash z kaczuchą w launcherze + przekazanie do aplikacji (Windows) | splash 44–166 ms przy starcie z cache (≈100 ms od startu kodu przy pierwszym); 0 ms pustki we wszystkich scenariuszach; brak podwójnego splasha; fokus w oknie głównym we wszystkich próbach z zarejestrowanym oknem głównym; animacja: 1087 z 1088 par zrzutów różnych | ten sam onedir; okno główne w tym samym czasie przy starcie z cache | **PRZYJĘTY WARUNKOWO** — warunki w §5.6 (fallback okna postępu, naprawa po kodzie 75, kwalifikacja, ≥6 prób drugiego startu na czystym laptopie) |
| Characteristic Mapping jednym zapytaniem | 148 s (szacunek) / 163 s (UI) → 0,44 s | mała baza: pełna identyczność; duża: 30 metryk identycznych | **PRZYJĘTY** |
| Review reports w puli procesów | sam kod: 19,2 s → 6,6 s (4) / 5,3 s (8) | identyczne wpisy i odczyty metadanych | **PRZYJĘTY** (pełny zysk w UI wymaga też C2: strumieniowanie, throttling; skalowanie 2,9× przy 4 i 3,6× przy 8 procesach) |
| Rozgrzewka w wątku tła | najdłuższy zastój 180 → 40 ms; blokada 402 → 74 ms | te same moduły; gotowość +9% | **PRZYJĘTY WARUNKOWO** (warunki A2, §9) |
| Więcej procesów renderu Extended plots | 48 grup: 49,7 → 35,3 → 25,3 → 24,8 s (1/2/4/8) | identyczny XLSX przy automatycznej gęstości „reduced" (aktywnej we wszystkich próbach) | **PRZYJĘTY jako kierunek** (C3; zależy od decyzji E1); 4 procesy: 1,4× względem dzisiejszych 2, 8 procesów już bez zysku (1,02×) na tej maszynie (6 rdzeni) |
| `PRAGMA cache_size`/`mmap_size` dla zapytań odczytu | −19%…+22% (4 zapytania, n=5) | — | **ODRZUCONY** (wynik niespójny, w obie strony) |
| BLAS=1 w procesach renderu (48 grup, 4 procesy; zmienne dla całego drzewa procesów) | 25,0 / 25,5 s → 22,0 / 22,6 s (−12%, n=2 naprzemiennie); CPU procesów potomnych 129–134 s → 70–71 s (−47%) | ta sama treść XLSX (hash) | **PRZYJĘTY jako część C1** (1 wątek BLAS w workerach; potwierdzić w EXE na Windows) |

### 1.4 Rekomendowana pierwsza partia

1. **A1 splash launchera** (zgłoszenie PO) z warunkami z §5.6, razem z **A2 rozgrzewką poza GUI**.
2. **A3 wspólny mechanizm operacji z kaczuchą** i podpięcie 7 brakujących operacji (oraz 3 krótszych
   zamrożeń z §7).
3. **B1–B4 szybkie duże zyski bez zmiany architektury:** Characteristic Mapping, Industrial → CSV Summary,
   Grouping, Industrial Data.
4. **C2 Review w puli procesów** i **C4 import** (cache gotowości schematu, rejestr raz na import).
5. Decyzje PO dla partii E (gęstość wykresów, supervisor, weryfikacja drugiego startu, payload).

## 2. Baza audytu i stan repozytorium (2026-10-19/20)

- `develop` = `784e44b2`. Gałąź referencyjna #1142 jest **604 commity przed** `develop` i go zawiera.
- **#1109** (`integrate/2026.09-rc1-into-develop` → `develop`): OPEN, head `82f8f576`, CLEAN.
- **#1142** (`integrate/2026.09-rc1-build-261018` → `develop`): OPEN, head **`78d5d775`**, MERGEABLE/BLOCKED.
  Opis PR (plan v5) wskazuje head `15ddbeb7` — **nieaktualny**: później weszły `ff851c3d` (BUG-001/002 CSV
  Summary, #1145), `f4cac9a6` (etykieta 261020), `e4a739b8` (PyMuPDF <2) i `78d5d775` (naprawa spawn).
- Audyt dotyczy `78d5d775`, nie `develop` — inaczej proponowałby wdrożone już #1121/#1129–#1133/#1137/#1138.
- **Baza przyszłych PR-ów:** gałąź referencyjna #1142 do czasu landowania #1109 i #1142, potem `develop`.
  Draft PR PoC celuje w `integrate/2026.09-rc1-build-261018` (diff tylko STEP2); po landowaniu — `develop`.
- Obszary regresji z polecenia (stan na `78d5d775`): granice stron #1143 — naprawione dla nowych importów
  (`d87c5801`), dane RC1 czekają na decyzję PO; metadane workerów — override przekazywany i odsyłany
  (`c476b7f2`), PoC puli Review daje identyczne odczyty; checkpointy WAL #1137 — import 1500 raportów
  zakończony poprawnie w 4 próbach (216 000 wierszy w bazie fixture); trwałości po przerwaniu nie testowano.

### 2.1 Status poprzednich ustaleń (Issues nadal OPEN do landowania #1109/#1142)

Wszystkie wymienione PR-y są w bazie `78d5d775` i żaden nie jest jeszcze w `develop` (sprawdzone
`git merge-base --is-ancestor`, 2026-10-20).

| Issue | Zmiana w bazie | Co pokazał STEP2 | Co zostaje → PR STEP2 |
|---|---|---|---|
| #1120 audyt STEP1 (top 10) | tracker | STEP2 jest następcą; pkt 10 (kod natywny w EXE) otwarty | D4 |
| #1124 domyślny eksport 70 s / 1,7 GB | #1131 (bulk + stream XLSX) | Main plots 1500 raportów (z wykresami): 28,6 s, RSS 763 MB — inny preset niż w #1124, czasy nieporównywalne | 1,7 s blokady GUI przy 1. kliknięciu → A2 |
| #1125 import: 7 hashy, 2 otwarcia PDF | #1132 (jeden hash, pula prepare) | import 1500: 12,9 s; nowe źródła kosztu: gotowość schematu ≈17%, rejestr parserów ≈6–8% | C4 |
| #1126 Extended 2,5 s/grupę | #1130 (jeden przebieg układu, ograniczony render grup) | ≈1,0 s/grupę w 1 procesie; pula 2 procesów per referencja; z dashboardem szeregowo | C3 (po E1), D1 |
| #1127 filtr: 14 DISTINCT w GUI | #1129 (indeksy, cache, worker) | 0,12 s zamrożenia przy otwarciu, 1,2 s do kompletu wartości bez kaczuchy | A3, równoległe DISTINCT |
| #1128 eksport CSV Summary 97 s / 1 GB | #1133 (bulk XLSX, statystyki w wątkach) | benchmark z #1128 (100k × 8): obecna wersja 81,8 i 72,9 s, build 261019 85,3 i 86,2 s (n=2, na przemian, ten sam profil) — bez regresji. UI „Create analytics" 100k × 11: 50,3 s, względem 261019 bez zmian (§4.1) | D2 |
| #1134 workery w EXE | #1138 (worker obliczeniowy dla pul) | prepare importu w EXE: opt-in (0 workerów domyślnie); na Windows nie mierzono eksportu ani importu | C1 |
| #1136 zapis importu na Windows | #1137 (jedno połączenie, checkpoint co ≥25 commitów/2 s) | Linux: import poprawny, 12,9 s; Windows: niezmierzone w STEP2 | pomiar w C4 |
| #1143 dane RC1 wielostronicowe | `d87c5801` (nowe importy) | PoC puli Review: identyczne odczyty | decyzja PO dla danych RC1 |

## 3. Metoda, środowisko i procedura odtworzenia

### 3.1 Narzędzia (gałąź PoC)

- `scripts/benchmark_ui_flows.py` — prawdziwe okna i handlery przycisków w wątku GUI, każdy scenariusz
  w osobnym procesie, prywatny `HOME`, Qt offscreen. Mierzy czas do pierwszej informacji zwrotnej
  (pierwsze nowe okno), czas do wyniku, zastoje GUI (QTimer 5 ms: przerwa między tyknięciami = czas bez
  odmalowania i bez wejścia), kaczuchę (koszt utworzenia, `show()`, faktyczne pokazanie, klatki w czasie
  widoczności i w tle, czy dialog żyje po zakończeniu), peak RSS drzewa procesów, CPU własne i dzieci.
  `--profile N` profiluje wątek GUI, `--profile-thread modul:Klasa` profiluje `run()` QThreada.
- `scripts/measure_windows_first_run_timeline.py` + job CI `windows-first-run-timeline`
  (`run_windows_first_run_timeline=1`) — onedir budowany raz i pakowany launcherem bazowym i PoC;
  scenariusze cold / verified / warm ×2 / warmup / corrupt / new_version w rundach naprzemiennych;
  okna co 20 ms, zrzuty co 200 ms, znaczniki launchera, supervisora i aplikacji na wspólnym zegarze;
  opcje `--settle-seconds` i wariant z `METROLIZA_LAUNCHER_SPLASH=0`.
- Instrumentacja opcjonalna (domyślnie wyłączona): `METROLIZA_STARTUP_STALL_PROBE=1`,
  `METROLIZA_STARTUP_EXIT_AFTER_WARMUP=1`, `METROLIZA_WARMUP_IN_THREAD=1` (PoC), znaczniki
  `timing event=… epoch_ms=…` w logu launchera i `supervisor_*` w profilu startu.

### 3.2 Dane (wyłącznie syntetyczne)

1500 PDF CMM (≈150 pomiarów, 37 referencji) → baza 90,8 MB / 216 000 wierszy / 2664 metryk; 50 PDF
(7200 wierszy, 216 grup Extended); 30 PDF (960 wierszy, 48 grup); CSV 100 000 × 11 kolumn (9,1 MB);
cache przemysłowy 50 000 rekordów × 20 metryk (1 000 000 wartości EAV) w kopii bazy 1500.

### 3.3 Środowisko

- Linux: Xeon W-10855M (6C/12T), 62 GB RAM, zasilanie sieciowe. **Liczby w raporcie: profil `balanced`**
  (power-profiles-daemon; ACPI `balanced`, governor `powersave` z EPP `balance_performance`, turbo
  włączone), ustawiony przez użytkownika przed przebiegiem 2026-10-20 05:54–06:17. Sonda przed i po
  przebiegu: 1 wątek 4,7–4,8 GHz, 12 wątków 4,0–4,1 GHz, pakiet do 100 °C przy pełnym obciążeniu; w trakcie
  265 próbek co 5 s: profil bez zmian, najszybszy rdzeń mediana 3,7 GHz [2,0–4,8], temperatura mediana
  77 °C. Porównanie z poprzednią wersją (§4.1): ten sam profil, 06:43–07:20. Wcześniejszy przebieg w innym
  profilu energii odrzucono — liczby w historii Issue/PR sprzed 2026-10-20 05:54 są nieaktualne.
  Python 3.11.16, PyQt6/Qt 6.6.1, PyMuPDF 1.28.2, pandas 3.0.6,
  numpy 2.4.6, matplotlib 3.11.2, SQLite 3.53.1, XlsxWriter 3.2.9 (venv deweloperski; `requirements.txt`
  ma zakresy, CI instaluje najnowsze zgodne). Dane na tmpfs (zimny dysk niemierzony). loadavg zapisany przy
  każdej próbie (scenariusze UI: 1,5–3,1). Przez pierwsze ~2 h na maszynie działała gra — wtedy tylko analiza statyczna.
- Windows: hostowany runner GitHub (windows-latest, 4 vCPU, Defender). To nie jest czysty laptop (#1101 A5).

### 3.4 Zastrzeżenia

- n=1 tam, gdzie zaznaczono; pozostałe mediany z 3 prób (Linux) lub 7/14 (Windows).
- Unieważnione i powtórzone: (a) pierwszy pomiar skalowania Extended plots i test BLAS=1 — skrypty bez
  strażnika `__main__`, więc workery spawn uruchamiały cały eksport ponownie (≈40 min nieważnych
  pomiarów); skalowanie powtórzone (`scale3`: 1/2/4; `scale2`: 8 — oba ze strażnikiem), BLAS=1 powtórzony
  poprawnie (§1.3);
  (b) pierwszy przebieg osi czasu Windows bez logów (ścieżki względne); (c) w pierwszej serii 3-krotnej
  po jednej próbie Industrial skończyło się SIGSEGV przy niszczeniu obiektów Qt po zakończeniu pomiaru (stos
  faulthandlera: powrót z `run_scenario`); harness trzyma teraz obiekty do `os._exit`, powtórka 6/6 bez
  błędu — artefakt harnessu, nie przepływ produktu; w obecnym przebiegu 45 z 45 prób scenariuszy UI
  bez błędu, w porównaniu wersji 94 z 94.
- Profile (cProfile) wydłużają czasy 1,3–2×; liczby z profili tylko jako proporcje. Profile wykonano
  w profilu `balanced` (2026-10-20); narzut profilera ≈1,8× (import: 22,7 s z profilerem, 12,9 s bez).
- Profil energii (§3.3): baseline, PoC i poprzednia wersja mierzone w tym samym profilu `balanced`. Progi
  „>1 s" dotyczą tej maszyny; docelowego laptopa nie mierzono.
- Windows: w 3 próbach próbnik okien nie zarejestrował okna głównego (PoC warm ×2, obecny verified po
  20 s ×1), choć profil aplikacji ma `main_window_show_called`, a harness zamknął aplikację ≈0,5 s
  później — to przeoczenia próbnika; czasy okna głównego i fokus liczone z pozostałych prób.

### 3.5 Odtworzenie

```bash
# Linux, worktree PoC, dane syntetyczne
python scripts/benchmark_ui_flows.py run --scenario reports_import --data-dir DATA \
    --pdf-set pdf_1500 --keep-db DATA/db_1500.sqlite --out import.json
python scripts/benchmark_ui_flows.py prepare --data-dir DATA        # CSV + cache przemysłowy
python scripts/benchmark_ui_flows.py suite --data-dir DATA --runs 3 --out-dir OUT
# Windows (CI)
gh workflow run ci.yml --ref perf/step2-audit -f run_windows_first_run_timeline=1
```

## 4. Tabela pomiarów

Linux, profil `balanced`, od akcji użytkownika; mediana [min–max] z 3 prób, jeśli nie zaznaczono n.

| Flow | Scenariusz | Wynik [s] | Pierwsza informacja [s] | Najdłuższy zastój GUI [s] | Peak RSS [MB] | n |
|---|---|---:|---:|---:|---:|---:|
| IMP-SCAN+META | Review 1500 PDF | 25,6 [22,3–25,8] | 1,08 (kaczucha) | 0,26 [0,18–0,29] (wypełnianie tabeli) | 174 | 3 |
| IMP-RUN | import 1500 PDF | 12,9 [12,8–12,9] | 1,06 (kaczucha) | 0,07 | 398 | 3 |
| DB-OPEN | Modify DB, baza 1500 | 0,18 [0,18–0,22] | 0,09 (puste okno) | 0,18 | 123 | 3 |
| DB-RECORDS | pomiary 216k + 1 znak filtra | 2,67 [2,57–2,89] | baner | 0,08 | 273 | 3 |
| DB-APPLY | 1 zmiana nazwy | 0,04 | — | 0,04 | 123 | 3 |
| EXP-OPEN | okno eksportu | 0,11 [0,09–0,12] | 0,10 | 0,11 | 119 | 3 |
| FLT-OPEN | filtr, 216k | 1,19 [1,18–1,37] | 0,12 | 0,12 | 131 | 3 |
| GRP-OPEN | grouping, 1500 | 1,23 [1,20–1,26] | 1,23 | **1,23** | 174 | 3 |
| GRP-MAP | dopasowanie nazw, 2664 metryk | **163,0** | 163,0 | **163,0** | 134 | 1 |
| EXP-RUN | Main plots, 1500 raportów | **28,6** [27,9–29,3] | 2,67 (kaczucha) | **1,72** (1. klik) | 763 | 3 |
| EXP-RUN | Extended, 50 raportów / 216 grup, 2 procesy | **130,3** | 2,60 | 1,65 (1. klik) | 962 | 1 |
| SHELL-THEME | motyw ciemny, tabela 1500 | 0,20 [0,19–0,22] | — | 0,20 | 173 | 3 |
| CSV-02/03 | wczytanie CSV 100k | 4,93 [4,88–5,04] | 1,18 (kaczucha) | 0,49 | 217 | 3 |
| CSV-09 | Create analytics 100k | **50,3** [49,9–51,2] | 1,01 (kaczucha) | 0,43 | 640 | 3 |
| IND-01 | Industrial Data, cache 50k | 0,78 [0,75–0,83] | 0,77 | **0,78** | 185 | 3 |
| IND-05 | Industrial → CSV Summary | **10,0** [9,6–10,9] | 10,0 | **10,0** | 208 | 3 |
| RT-01 | Realtime, pierwsze otwarcie | 0,31 [0,30–0,36] | 0,30 | **0,31** | 139 | 3 |
| SHELL-START | start, okno → gotowość | 0,14 → 0,50 | splash | 0,18 (rozgrzewka) | — | 5 |

PoC (Linux, `balanced`): Characteristic Mapping 0,44 s [0,44–0,55] (n=3); Review szeregowo / w puli 2/4/8
procesów: 19,2 / 11,7 / 6,6 / 5,3 s (n=1, sam kod); Extended 48 grup 1/2/4/8 procesów: 49,7 / 35,3 / 25,3 /
24,8 s (n=1 każdy, CPU 149 / 13+133 / 13+132 / 13+181 s); Extended 48 grup + dashboard HTML przy 4
procesach: 50,7 s, tryb `serial_output_mode`; BLAS=1 przy 4 procesach: 22,0 i 22,6 s wobec 25,0 i 25,5 s,
CPU procesów potomnych 70–71 s wobec 129–134 s, ta sama treść XLSX; rozgrzewka w wątku: zastój 40 ms,
gotowość 0,40 s po malowaniu (n=5).

### 4.1 Porównanie z poprzednią wersją (2026.09 RC1 build 261019)

Poprzednia wersja: build 261019 (`15ddbeb7`, ostatnia referencja #1142 przed bazą audytu); obecna: baza
audytu `78d5d775` (261020 + naprawa spawn launchera). Ta sama maszyna, profil `balanced`, te same dane i
harness, czyste worktree obu wersji; wersje na przemian w każdym scenariuszu, kolejność odwrócona w każdej
serii (2026-10-20 06:43–07:20). Kod różni się w CSV Summary i analityce tabelarycznej, Industrial Data i
bridge'u, komunikacie sesji realtime i grupowaniu eksportu (#1145) oraz w launcherze (tylko Windows) i pinie
PyMuPDF (ten sam venv, więc bez wpływu na ten pomiar). Kod startu jest identyczny.

| Flow | 261019 [s] | obecna `78d5d775` [s] | Zmiana mediany | n |
|---|---:|---:|---:|---:|
| Review 1500 PDF (IMP-SCAN+META) | 22,0 [21,7–33,1] | 24,2 [22,5–33,2] | +10,1% | 3 + 3 |
| Import 1500 PDF (IMP-RUN) | 13,1 [13,1–15,5] | 13,6 [12,6–14,2] | +3,4% | 3 + 3 |
| Modify DB open (DB-OPEN) | 0,20 [0,18–0,25] | 0,18 [0,18–0,20] | −10,1% | 3 + 3 |
| Modify DB rekordy 216k (DB-RECORDS) | 2,56 [2,43–2,90] | 2,58 [2,46–2,76] | +0,7% | 3 + 3 |
| Modify DB, 1 zmiana (DB-APPLY) | 0,04 [0,04–0,05] | 0,04 [0,03–0,04] | −1,8% | 3 + 3 |
| Okno eksportu (EXP-OPEN) | 0,12 [0,09–0,12] | 0,12 [0,10–0,12] | −3,8% | 3 + 3 |
| Filter 216k (FLT-OPEN) | 1,29 [1,19–1,56] | 1,19 [1,19–1,24] | −8,1% | 3 + 3 |
| Grouping 1500 (GRP-OPEN) | 1,25 [1,20–1,61] | 1,31 [1,22–1,37] | +4,6% | 3 + 3 |
| Main plots 1500 (EXP-RUN) | 29,3 [29,0–30,7] | 29,1 [29,1–30,1] | −0,7% | 3 + 3 |
| Motyw ciemny (SHELL-THEME) | 0,21 [0,20–0,22] | 0,20 [0,19–0,20] | −8,0% | 3 + 3 |
| Wczytanie CSV 100k (CSV-02/03) | 5,25 [5,06–5,73] | 5,11 [5,07–5,12] | −2,6% | 3 + 3 |
| Create analytics 100k (CSV-09) | 50,9 [50,7–51,7] | 51,6 [51,2–51,8] | +1,4% | 3 + 3 |
| Industrial Data (IND-01) | 0,78 [0,75–0,82] | 0,76 [0,69–0,87] | −2,2% | 3 + 3 |
| Industrial → CSV Summary (IND-05) | 10,4 [9,66–10,7] | 10,2 [9,96–11,1] | −2,1% | 3 + 3 |
| Realtime (RT-01) | 0,31 [0,30–0,37] | 0,33 [0,33–0,40] | +5,9% | 3 + 3 |
| Characteristic Mapping (GRP-MAP) | 163,2 | 164,7 | +0,9% | 1 + 1 |
| Extended 216 grup (EXP-RUN) | 132,1 | 133,0 | +0,6% | 1 + 1 |

W żadnym scenariuszu zakresy obu wersji się nie rozdzielają; różnice median do ±10% przy n=3 mieszczą się
w szumie (Review: jedna seria trwała ≈33 s w obu wersjach). Benchmark z #1128 (100k × 8, kolejność
261019 → obecna → obecna → 261019): 261019 85,3 i 86,2 s, obecna 81,8 i 72,9 s — obecna szybsza o
≈10% (n=2, do potwierdzenia). Rozmiary wyników (XLSX Main plots i Extended, dashboard CSV Summary) są w obu
wersjach takie same (różnica 1 B to znacznik czasu w XLSX). **Wniosek:** obecna wersja nie jest wolniejsza
od 261019 w żadnym zmierzonym scenariuszu. Startu i Windows nie porównywano (kod startu bez zmian).

Windows (EXE, hostowany runner; ms od utworzenia procesu; mediana [min–max]; runy 39318835183,
39322360692, 39332127323 — drugie uruchomienie natychmiast po pierwszym):

| Scenariusz | Wariant | Kod launchera rusza | Pierwsze okno | Pustka po 1. oknie | Okno główne | Fokus | n |
|---|---|---:|---:|---:|---:|---|---:|
| cold | obecny | — | 2636 [1934–3609] (okno postępu) | 1954 [1599–3877] | 8162 [5903–10157] | 6/7 | 7 |
| cold | PoC | 3208 [2390–3729] | 3313 [2421–3883] (splash) | **0** | 8115 [6864–9960] | 7/7 | 7 |
| warm | obecny | — | 1068 [954–1378] (Qt splash) | 0 | 1341 [1218–1629] | 6/14 | 14 |
| warm | PoC | 15 | **66** [44–89] | **0** | 1298 [1148–1489] (n=12) | 12/12 | 14 |
| new_version | obecny | — | 2436 [2099–3507] | 2081 [1643–4428] | 7491 [6561–10517] | 6/7 | 7 |
| new_version | PoC | 2468 [2177–3740] | 2601 [2202–3775] | **0** | 7734 [6084–13869] | 7/7 | 7 |
| corrupt | obecny | — | 86 [64–106] | 1700 [0–1866] | 5776 [5381–6341] | 6/6 | 7 (1 błąd: kod 102) |
| corrupt | PoC | 15 | 79 [71–99] | **0** | 5982 [5499–19702] | 7/7 | 7 |
| verified (od razu) | obecny | — | 136 [97–155] | 1051 [935–1232] | 4906 [3965–8763] | 1/7 | 7 |
| verified (od razu) | PoC | 15 | 92 [66–166] | **0** | 7161 [5620–7739] | 7/7 | 7 |
| verified (po 20 s) | obecny | — | 116 [95–137] | 981 [923–1039] | 1841 (n=1) | 1/1 | 2 |
| verified (po 20 s) | PoC | 14 | 130 [121–139] | **0** | 2720 [1768–3673] | 2/2 | 2 |
| verified (po 20 s) | PoC bez okna | 14 | 2316 [1551–3080] (Qt splash) | 0 | 2580 [1823–3337] | 0/2 | 2 |

Run A/B 39349370988 (pauza 20 s przed drugim startem): weryfikacja SHA-256 + flush — obecny 394 i
426 ms, PoC 450 i 2235 ms; wariant bez okna nie loguje etapu weryfikacji. Jedna próba PoC corrupt
(run 39332127323): odbudowa runtime 17,9 s (pozostałe ≈3,6 s), splash widoczny przez cały czas —
przyczyna po stronie runnera niezbadana; obecny launcher nie loguje etapów, więc nie da się porównać.

### 4.2 Wyniki pakietu STEP2: przed STEP1, po STEP1, po STEP2 (2026-10-21)

Pakiet wdrożeniowy: gałąź `perf/step2-boost` (P01–P14 i poprawki z przeglądów R1–R4, plan:
[`performance-boost-step2-implementation.md`](performance-boost-step2-implementation.md)). Trzy wersje na tym
samym laptopie, w profilu `balanced` (przed i po pomiarze: `balanced`, zasilanie sieciowe), na tych samych
danych syntetycznych i z tym samym plikiem harnessu skopiowanym do każdego drzewa (SHA-256 `a71e7496…`);
czyste worktree ze skompilowanym bajtkodem, kolejność wersji rotowana w każdym scenariuszu i w każdej rundzie,
mediana [min–max] z 3 prób (długie scenariusze n=1). Run 2026-10-21 04:17–05:56.

- **przed STEP1** = `fb72a42e` — commit zmierzony w audycie #1120 (2026-10-17);
- **po STEP1** = `15ddbeb7` — 2026.09 RC1 build 261019;
- **po STEP2** = `a176139d` (head pakietu w chwili pomiaru); wiersze Review/import ponownie zmierzone na
  `a58b693f` po poprawce P07b (niżej).
- Harness instaluje politykę GC (§4.3) tylko w drzewach, które ją mają; każda wersja działa więc tak jak jej
  produkt. **N/A** = funkcja albo mierzony etap nie istniały w tej wersji (Review przed importem, osobne
  wczytanie rekordów Modify DB), nie zero.

| Flow | Scenariusz | przed STEP1 [s] | po STEP1 [s] | po STEP2 [s] | STEP2 vs 261019 | łącznie |
|---|---|---:|---:|---:|---:|---:|
| IMP-SCAN | Review 1500 PDF | N/A | 22,40 [21,64–22,86] | **8,40** [8,16–8,42] | **−62%** | — |
| IMP-RUN | import 1500 PDF po Review | N/A | 12,89 [12,77–13,39] | **9,4–9,8** (P07b, n=2) | ok. −25% | — |
| DB-OPEN | Modify DB, baza 1500 | 19,25 | 0,19 | 0,18 | bez zmian | **−99%** |
| DB-RECORDS | rekordy 216k | N/A | 2,44 | 2,39 + animowana kaczucha | bez zmian | — |
| DB-APPLY | 1 zmiana nazwy | 8,95 | 0,05 | 0,05 | bez zmian | **−99%** |
| FLT-OPEN | filtr, 216k | 1,56 | 1,19 | 1,29 ¹ | brak potw. zmiany | −17% |
| GRP-OPEN | grouping, 1500 | 1,26 | 1,50 | **0,62** | **−58%** | −51% |
| GRP-MAP | dopasowanie nazw, 2664 metryk (n=1) | 170,0 | 163,3 | **0,8** | **−99,5%** | −99,5% |
| EXP-RUN | Main plots, 1500 raportów | 58,47 | 28,83 | 27,68 | −4% | **−53%** |
| EXP-RUN | Extended, 216 grup (n=1) ² | 409,0 | 134,6 | **68,8** | **−49%** | −83% |
| SHELL-THEME | motyw, tabela 1500 | N/A | 0,21 | 0,17 | −17% | — |
| CSV-03 | wczytanie CSV 100k | 4,96 | 4,94 | 4,71 | −5% | −5% |
| CSV-09 | Create analytics 100k | 51,44 | 52,02 | **35,39** | **−32%** | −31% |
| IND-01 | Industrial Data, cache 50k | 1,58 | 0,85 | **0,33** | **−62%** | −79% |
| IND-05 | Industrial → CSV Summary | 10,27 | 10,51 | **5,73** | **−45%** | −44% |
| RT-01 | Realtime, pierwsze otwarcie | 1,19 | 0,38 | 0,40 | w szumie | −66% |
| EXP-OPEN | okno eksportu | 0,12 | 0,13 | 0,12 | bez zmian | — |
| — | `benchmark_paths` CSV Summary 100k×8 (n=2) | 93,4 | 65,6 | 64,9 | bez zmian | −31% |

¹ Ponowny pomiar naprzemienny (n=4, ta sama sesja): 261019 1,34 [1,24–1,39] s, po STEP2 1,38 [1,28–1,52] s,
po STEP2 bez polityki GC 1,32 [1,30–1,37] s — zakresy się nakładają; różnicy z głównej tabeli nie potwierdzono.
² Linux, źródła: do 4 procesów renderujących (domyślne źródłowe 4). W Windows EXE limit renderu to nadal 2
procesy — tam zysk jest mniejszy (niezmierzony).

**Responsywność (najdłuższy zastój GUI [s], mediany):** dopasowanie nazw 170,0 → 163,3 → **0,08**;
Industrial → CSV Summary 10,26 → 10,51 → **0,10**; Grouping 1,26 → 1,50 → **0,20**; Industrial Data 1,58 → 0,85
→ **0,33**; Modify DB 19,25 → 0,19 → 0,18; Review — → 0,24 → **0,12**. Start (P11, n=5, ta sama miara po obu
stronach): najdłuższy zastój po pierwszym malowaniu 201 → **50 ms**; pierwszy klik Export po rozgrzewce:
zastój 1,40 → **0,12 s**. Harness `export_run` klika eksport przed końcem rozgrzewki, więc w tabeli wyżej
zastój pierwszego eksportu (~1,8 s) pozostaje we wszystkich wersjach.
**Kaczucha (P12, harness):** Review — widoczna 1,00 s od kliknięcia (było 1,02–1,08), klatki 95 → 100%,
klatki w tle 62 → 0, okno zwalniane; import 1,05–1,15 → 1,01 s; wczytanie CSV 65 → 66–70% klatek.
**Koszt zasobów (szczyt RSS drzewa procesów):** Review 174 → 460 MB (procesy puli); Extended 956 → 1369 MB
(4 procesy na Linuksie); pozostałe bez istotnej zmiany.

**Regresja wykryta w tym porównaniu i naprawiona (P07b):** na `a176139d` import po Review trwał 18,3 s
(261019: 12,9 s). Profil wątku importu: po Review w puli procesów cache sond parserów w procesie głównym był
pusty, więc filtr planu importu sondował od nowa wszystkie 1500 PDF (18,1 s, w tym odczyt tekstu PDF i
parsowanie bloków). Przy Review w procesie (`METROLIZA_REVIEW_WORKERS=0`) import trwał 10,4–11,1 s. Poprawka
`a58b693f`: procesy robocze zwracają wyniki sond, proces główny zasiewa nimi swój cache tylko przy zgodnej
generacji i odcisku rejestru oraz niezmienionym pliku (digest). Wynik: 18,8–19,5 → **9,4–9,8 s**, Review bez
zmian (8,3 → 8,5 s), zrzut logiczny bazy identyczny (1500 raportów / 216 000 pomiarów). Pomiar uzupełniający
w jednej sesji, naprzemiennie, ale przy wyższym obciążeniu laptopa (loadavg 3,6–5,6): Review 29,8 → 8,7 s,
import 16,0 → 13,2 s.

Surowe wyniki: [`performance-boost-step2-measurements.json`](performance-boost-step2-measurements.json),
klucz `linux.three_version_comparison`.

### 4.3 Stabilność: przyczyna losowych crashy (P14)

W trakcie pakietu testy Qt losowo kończyły się SIGSEGV (lokalnie i w CI, run 39499366212: crash w
`processEvents()`), a podproces kwalifikacji „fresh reopen” na Windows padał co kilka przebiegów. Przyczyna,
odtworzona deterministycznie (3/3): **automatyczny cykliczny GC Pythona uruchamia się w tym wątku, który
akurat alokuje** — także w wątkach roboczych (eksport, import, CSV, ładowanie w tle, rozgrzewka). Zbiera tam
wrappery obiektów Qt trzymane tylko przez cykle referencji (np. lambda podpięta do sygnału, która przechwytuje
okno); PyQt odkłada usunięcie obiektu C++ do jego wątku, a wątek GUI wykonuje je później na zwolnionym już
stanie Pythona. Gdy zbieranie odbywa się w wątku GUI, wszystkie obiekty usuwają się poprawnie (20/20).

Poprawka: polityka `metroliza.app.gc_policy` wyłącza automatyczny GC i zbiera pokoleniami na timerze w wątku
GUI (500 ms; najdłuższa zbiórka zmierzona w ciężkich scenariuszach: 42 ms). Instalują ją `launch_ui` i każdy
`get_or_create_qapplication()` (także ścieżki kwalifikacji Windows); tryb smoke startu i procesy robocze spawn
zostają przy domyślnym GC; testy używają tej samej polityki. Dowody: podproces fresh reopen 2/12 i 3/11
crashy → **0/12** (baza 78d5d775: 0/8); zestaw 10 plików Qt pod obciążeniem 2/5 → **0/3**; CI na `3e5fe523`
i `a176139d` w pełni zielone; 20 startów i zamknięć aplikacji bez błędu. **Na Windows problem nie jest w pełni
rozwiązany:** test fresh reopen padł ponownie w runie 39545859603 (`a0d37690`, już z polityką GC) po zielonych
39529010183 i 39532176909; przyczyna na Windows nieustalona. Ograniczenie: dowody z Linuksa (offscreen) i z
Windows CI; spakowany EXE na czystej maszynie — w teście PO (build 261021).

### 4.4 Czego nie osiągnięto i co zostaje otwarte

- **D1 render wykresów (P10):** −5% na wykres zamiast −30%; zysk Extended daje głównie pula procesów (P08).
- **Zimny pierwszy eksport** kliknięty przed końcem rozgrzewki (~1,7 s po pokazaniu okna) nadal ma przestój
  ~1,8 s; po rozgrzewce 0,12 s.
- **Płynność kaczuchy przy wczytywaniu CSV:** 66–70% klatek (praca obliczeniowa w tle konkuruje o GIL).
- **Modify DB:** asynchroniczne otwarcie i cache tekstu liczb wycofane (zmiana kontraktu synchronicznego
  otwarcia; zysk 1,8%); zostało animowane ładowanie rekordów.
- **Koszt pamięci** Review w puli (+~290 MB chwilowo) i Extended przy 4 procesach (Linux).
- **Decyzje PO (partia E)** i D3/D4 — bez zmian, odłożone.
- **Windows:** CI (Windows core smoke, smoke pakowania) zielone; pełna akceptacja kandydata Windows w CI nie
  była uruchamiana (wymaga osobnej zgody); EXE testowy 261021 dla PO.
- Uwagi P3 z przeglądu delta R4 (utwardzenie, w tym cykl aplikacja ↔ polityka GC) poprawiane po buildzie 261021;
  nie były już niezależnie przeglądane (budżet przeglądu partii R4 wykorzystany).

## 5. Pierwsze uruchomienie i wczesny splash (zgłoszenie PO)

### 5.1 Odtworzenie

Odtworzone na Windows (hostowany runner, Defender, EXE z CI): pierwsze uruchomienie z pustym cache,
drugie, kolejne, pierwsze uruchomienie nowej wersji przy starym cache, odbudowa uszkodzonego cache
(obcięty `_internal/python311.dll`). Okna co 20 ms, zrzuty ekranu co 200 ms; filmstripy w artefakcie CI
`windows-first-run-timeline` (katalogi `runs/*/frames`).

### 5.2 Oś czasu obecnego launchera (pierwsze uruchomienie, mediany z 7)

| Od – do [ms od podwójnego kliknięcia] | Co widzi użytkownik | Co się dzieje |
|---|---|---|
| 0 – ≈2600 | **nic** | system i antywirus sprawdzają nowy plik EXE 334 MB, zanim wykona się kod launchera |
| ≈2600 – ≈4600 | szare okno „Preparing Metroliza for first use…" z paskiem | rozpakowanie 538 MB / 2156 plików (LZ4, wątki) |
| ≈4600 – ≈6600 | **nic (1954 ms [1599–3877])** | start `metroliza.exe` (supervisor) z nowych DLL, hash ≈94 MB komponentów, start aplikacji, import PyQt |
| ≈6600 – ≈8200 | Qt splash z kaczuchą — **kaczucha zwykle stoi** (29% par zrzutów zmienionych) | import i budowa okna głównego w wątku GUI |
| ≈8200 | okno główne | — |

Drugie uruchomienie: okno „Preparing… for first use" z pustym paskiem przez całą weryfikację
(SHA-256 + flush 2156 plików), potem ≈1 s pustki. Kolejne uruchomienia: **≈1,1 s bez żadnego okna**;
okno główne dostało fokus w 6 z 14 prób.

### 5.3 Rozbicie startu z cache (PoC, Windows, run 39322360692, n=8)

| Etap | Czas |
|---|---:|
| launcher: payload, blokada instancji, splash, kontrola rozmiarów 2156 plików | ≈0,12 s |
| start procesu supervisora (bootloader PyInstaller + interpreter) | ≈0,43 s |
| importy supervisora + hash komponentów pakietu (≈94 MB) | ≈0,04–0,2 s + ≈0,1 s |
| start procesu aplikacji (Popen + bootloader + interpreter) | ≈0,25–0,30 s |
| aplikacja: PyQt, okno główne, `show()` | ≈0,31–0,36 s |

Warstwa supervisora to ≈0,65–0,9 s z ≈1,3 s ciepłego startu — największa pojedyncza pozycja (decyzja E2).

### 5.4 Projekt i PoC: splash w launcherze

- **Gdzie:** natywny launcher (Rust, Win32/GDI), zaraz po kontroli pojedynczej instancji — przed
  rozwiązaniem katalogu cache, kontrolą „warm", weryfikacją i rozpakowaniem. Nie zależy od Pythona, Qt
  ani rozpakowanego runtime.
- **Animacja:** istniejący asset kaczuchy (`encoded_loading_gif`) zapisany w launcherze jako GIF (test
  pilnuje identyczności), dekodowany raz do klatek i animowany na własnym wątku z własną pętlą komunikatów
  (10 Hz, zgodnie z klatkami GIF) — niezależnie od rozpakowywania, hashowania, startu supervisora i od
  zajętego wątku GUI aplikacji.
- **Etap i postęp:** „Preparing Metroliza for first use…" z postępem rozpakowania, „Checking Metroliza
  files…" z postępem weryfikacji (dotąd pasek stał), potem etapy aplikacji przez `WM_COPYDATA`.
- **Przekazanie:** launcher przekazuje uchwyt w `METROLIZA_LAUNCHER_SPLASH_HWND`; aplikacja sprawdza klasę
  okna, nie tworzy własnego Qt splasha, po pierwszym malowaniu okna głównego wysyła `MSG_HANDOFF` z jego
  uchwytem; launcher (ma prawo do pierwszego planu) przenosi fokus i zamyka splash. Zamknięcie także:
  przed komunikatem supervisora, przed błędem launchera, przy błędzie/smoke aplikacji, po wyjściu
  aplikacji i po 120 s (w A1: 120 s od końca rozpakowania/weryfikacji, nigdy w ich trakcie).
- **DPI:** system-aware (rozmiar ze skalą systemu); per-monitor wymaga obsługi `WM_DPICHANGED` —
  w A1 odłożone.

### 5.5 Wynik PoC

- Splash widoczny **44–166 ms** od utworzenia procesu przy starcie z cache i ≈100–130 ms od startu kodu
  przy pierwszym uruchomieniu.
- **Zero pustych okresów** po pierwszym oknie we wszystkich scenariuszach (obecnie 1,0–3,9 s).
- **Zero nakładających się splashy**; fokus w oknie głównym we wszystkich próbach, w których próbnik
  zarejestrował okno główne (obecnie 6/14 przy starcie z cache, 1/7 przy drugim).
- Animacja: 1087 z 1088 par zrzutów różni się w obszarze kaczuchy (54 próby); obecny Qt splash 17 z 58
  par (40 prób), bezruch do 1,28 s.
- Okno główne: bez zmian przy starcie z cache (1298 vs 1341 ms) i przy pierwszym (8115 vs 8162 ms).
- Wariant PoC z wyłączonym splashem: pierwszy start **7,4 s bez żadnego okna** (run A/B) — tyle daje splash.
- **Nie wykazano:** wcześniejszego pierwszego okna przy pierwszym uruchomieniu. Kod launchera PoC rusza po
  3208 ms [2390–3729] od kliknięcia, a pierwsze okno obecnego launchera pojawia się po 2636 ms; obecny
  launcher nie loguje startu kodu, więc nie da się rozdzielić skanu AV od pracy launchera. Do sprawdzenia
  na czystym laptopie.

### 5.6 Warunki przed produkcyjnym PR (A1)

1. **Fallback:** przy `METROLIZA_LAUNCHER_SPLASH=0` albo nieudanym utworzeniu splasha PoC nie pokazuje
   żadnego okna (stare okno postępu usunięto) — przywrócić okno postępu jako fallback.
2. **Naprawa po kodzie 75:** splash jest już zwykle zamknięty przez aplikację/supervisora, więc ponowne
   rozpakowanie idzie bez okna — pokazać splash/okno postępu ponownie; dodać scenariusz exit-75.
3. **Drugie uruchomienie:** natychmiast po pierwszym oba warianty płacą za strony niezapisane jeszcze
   na dysk (SHA-256 + `FlushFileBuffers` 2156 plików): weryfikacja obecnie 3,4 s, w PoC 5,8 s (n=7). Po
   20 s pauzy: 0,39/0,43 s vs 0,45/2,24 s (n=2). Okno główne: obecny 1,84 s (n=1), PoC 2,72 s
   [1,77–3,67], PoC bez okna 2,58 s [1,82–3,34] — samo okno splasha nie wyjaśnia różnicy, a przy n≤2 nie
   da się jej odróżnić od szumu. Kryterium: ≥6 prób z pauzą na czystym laptopie, mediana PoC nie gorsza.
4. **Kwalifikacja:** `qualify_windows_launcher.py` i `qualify_windows_portable_onefile.py` z nowym launcherem
   (nie uruchomiono); licencja crate `gif` (MIT/Apache-2.0) w THIRD_PARTY_NOTICES.
5. **Opóźnienie przed startem kodu** (2,2–3,9 s na świeżym pliku) zależy od rozmiaru EXE i skanera —
   zmniejsza je tylko mniejszy payload lub reputacja podpisu (E4; brak certyfikatu).
6. **Uwagi P3 z review różnicowego:** gdy wątek okna wystartuje później niż 2 s, `Splash::close` nie
   wyśle zamknięcia i czeka na wątek do 120 s (deadline splasha) — w produkcji flaga stopu albo
   `PostThreadMessage`; `show_message` powinien kodować tekst z `errors="replace"`.

## 6. Mapa batchingu i współbieżności

**etap → batching → model wykonania → workery → ograniczenia → zmierzony zysk → decyzja**

| Etap | Batching dziś | Model dziś | Workery | Ograniczenia | Zmierzony zysk | Decyzja |
|---|---|---|---|---|---|---|
| Review: inspekcja pliku (hash, probe parsera) | plik po pliku | QThread szeregowo | 1 | PyMuPDF nie w wielu wątkach → procesy; rejestr parserów per proces | 7,95 s → 2,37 s (4) / 2,11 s (8) | **procesy**, paczki ≈24 pliki, wyniki w kolejności |
| Review: szybki odczyt metadanych | brak | QThread szeregowo, ponowny hash i PDF | 1 | wyniki nakładane na tabelę w GUI | 11,2 s → 4,2 s (4) / 3,2 s (8) | **procesy**, docelowo jeden przebieg na plik |
| Review: wypełnienie tabeli | cały wynik naraz | GUI | — | model w Pythonie | — (0,26 s zastoju) | strumieniowanie partiami |
| Import: filtr planu | brak | szeregowo przed pulą | 1 | wykrycie zmiany pliku (fail closed) | — | w puli razem z prepare |
| Import: prepare | okno 3×workery | pula spawn | min(3, cpu−1), EXE: 0 | spawn na Windows (#1138) | #1132 | liczba z budżetu (§6.1) |
| Import: zapis SQLite | commit per raport, checkpoint ≥25 commitów/2 s | jeden pisarz | 1 | SQLite: jeden pisarz na plik | #1137 | **szeregowo — właściwe**; cache gotowości schematu (−≈17%), rejestr raz (−≈6%) |
| Characteristic Mapping | N+1 | GUI | — | — | 163 s → 0,44 s | jedno zapytanie + worker |
| Grouping | pandas `agg` z lambdą | GUI | — | — | — | wektoryzacja + worker |
| Filter: DISTINCT ×14 | cache LRU | QThread kolejno | 1 | odczyty na osobnych połączeniach mogą iść równolegle | — | 2–4 połączenia `query_only`, listy partiami |
| Export Main plots: XLSX | bulk + stream (#1131) | QThread | 1 | XlsxWriter jednowątkowy | #1131 | zostawić; import modułu poza GUI (A2) |
| Export Extended: render grup | kolejka 2×workery | pula spawn **per referencja**, 1. grupa szeregowo, próg 8/40 grup per referencja | 2 (max 4) | wyniki odrzucane przy zmianie gęstości | 35,3 → 25,3 s (4) → 24,8 s (8) | **jedna pula na eksport**, workery z budżetu (C3, po E1) |
| Export z dashboardem HTML | brak | **zawsze szeregowo** (`serial_output_mode`) | 0 | dashboard zbiera wyniki w procesie głównym | 50,7 s vs 25,3 s bez dashboardu (4) | równoległy render + zbieranie w kolejności |
| CSV Summary: wczytanie | 50 000 wierszy na `executemany` | QThread, pętla Pythona | 1 | parsowanie CSV w Pythonie | — | D2 |
| CSV Summary: analityka/dashboard | metryki po kolei | QThread + wątki statystyk | — | fity scipy na pełnych danych, powtórzone dla tabeli | — | jeden fit na serię, metryki w procesach (D2) |
| Industrial → CSV Summary | — | GUI | — | EAV, facety | — | worker + SQL, COUNT raz (B2) |
| Realtime: cykl polla | paczki 500, ≤5000/cykl | QThread na cykl, źródła szeregowo | 1 | źródło zewnętrzne | niezmierzone | źródła równolegle po pomiarze |
| Start: rozpakowanie / weryfikacja | pliki od największych | wątki Rust | clamp(cpu, 2, 8) | dysk, AV | — | zostawić; weryfikacja w tle (E3) |
| Start: rozgrzewka modułów | moduł po module | **wątek GUI** | — | importy pod GIL | zastój 180 → 40 ms | wątek tła (A2) |

### 6.1 Wspólny budżet zasobów (propozycja C1)

- **CPU:** budżet = `max(1, rdzenie_fizyczne − 1)`; pule (prepare, render, review) pobierają tokeny; operacje
  równoległe dzielą budżet; GUI zawsze ma rdzeń. Dziś każda pula liczy osobno (prepare do 3, render 2,
  ONNX `min(4, cpu−1)`, rayon i BLAS w każdym procesie — wszystkie rdzenie).
- **Wątki bibliotek w workerach:** w initializerze 1 wątek `OMP/OPENBLAS/MKL_NUM_THREADS`, ONNX intra-op,
  `RAYON_NUM_THREADS`; w procesie głównym limit = budżet. Zmierzone (48 grup, 4 procesy, n=2): BLAS=1 w całym
  drzewie procesów −12% czasu i −47% CPU procesów potomnych, ta sama treść XLSX; ONNX i rayon niezmierzone.
- **RAM:** ≈280 MB RSS na worker renderu (zmierzone) → workery = min(budżet CPU, wolna RAM / 300 MB).
- **I/O:** jeden pisarz SQLite na plik; odczyty równoległe tylko na osobnych połączeniach `query_only`.
- **Próg opłacalności:** pula, gdy praca > koszt startu (spawn + import ≈0,4–0,8 s/proces na Windows);
  progi na cały eksport/import, nie per referencję.

### 6.2 Kontrakty współbieżności (zweryfikowane w kodzie)

- **Qt:** widgety tylko w GUI; workery to QThread z sygnałami; postęp importu deduplikowany do procentów,
  skanu — nie (2 sygnały i restyle przycisków na plik); `ExportDataThread` woła
  `QCoreApplication.processEvents()` z wątku workera (do usunięcia).
- **GIL:** CPython 3.11 z GIL; natywnie zwalnia GIL tylko `distribution_fit_ad` (rayon) → dla CPU procesy.
- **PyMuPDF:** kod nie uruchamia go w dwóch wątkach; PoC puli procesów dał identyczne wyniki.
- **Matplotlib:** Agg; render w procesach lub workerze. Import `pyplot` poza głównym wątkiem tylko z
  wymuszonym Agg (A2).
- **SQLite:** WAL + `synchronous=NORMAL`, `busy_timeout` 5 s, jeden pisarz importu, checkpointy wg #1137;
  połączenia nie są współdzielone; `ensure_report_schema` (≈7 ms; transakcja zapisu) w GUI przy otwieraniu
  okien — ryzyko blokady przy aktywnym imporcie.
- **Blokujące oczekiwania w GUI:** zamykanie `ModifyDB`: `wait(3000)` + nieograniczony `wait()`.

## 7. Kaczucha: pełna lista luk (operacje >1 s)

**BRAK** wskaźnika; **SPÓŹN.** (później niż ≈1 s od kliknięcia); **STOI** (zamrożona animacja);
**LIFECYCLE** (zły cykl życia). Czasy: mediany n=3 (Linux, profil `balanced`), jeśli nie zaznaczono.
IND-01, RT-01 i IMP-REVIEW trwają poniżej 1 s, ale zamrażają GUI przez cały czas — zostają na liście; na
docelowym laptopie niezmierzone.

| Flow | Operacja | Czas | Obecny loading | Luka | Przyczyna | Miejsce poprawki | Kryterium odbioru |
|---|---|---:|---|---|---|---|---|
| GRP-MAP | otwarcie dopasowania nazw | 163 s (n=1) | brak | BRAK, STOI | N+1 w GUI | `characteristic_mapping_service.py:166`, dialog `:590` | worker; kaczucha ≤1,1 s od kliknięcia; ≥90% klatek |
| IND-05 | Industrial → CSV Summary | 10,0 s | brak | BRAK, STOI | bridge + 4× COUNT w GUI | `industrial_data_dialog.py:883`, `industrial_tabular_bridge.py:104`, `industrial_analytics_dialog.py:2267` | jw. |
| IMP-META | szybki odczyt metadanych (1500) | ≈14 s | licznik w tabeli | BRAK (praca w tle bez animacji) | — | `parsing_dialog.py:977-1040` | nieblokująca kaczucha w pasku Reports |
| DB-RECORDS | ładowanie rekordów 216k | 2,67 s | baner | BRAK (bez animacji) | — | `modify_db.py:641-760` | nieblokująca kaczucha |
| GRP-OPEN | otwarcie grouping | 1,23 s | brak | BRAK, STOI | pandas w GUI | `data_grouping.py:148-716`, `data_grouping_service.py:116` | worker + kaczucha lub otwarcie <0,5 s |
| FLT-OPEN | ładowanie wartości filtra | 1,19 s | tekst | BRAK | — | `filter_dialog.py:894-966` | kaczucha nieblokująca od 1 s |
| IND-01 | otwarcie Industrial Data | 0,78 s | brak | BRAK, STOI | import `oznak`, COUNT-y w GUI | `industrial_data_dialog.py:678-718` | otwarcie <0,5 s |
| IMP-REVIEW | wypełnienie tabeli po Review (1500) | 0,26 s zamrożenia | kaczucha już zamknięta | BRAK, STOI | `dismiss` przed `set_review` | `parsing_dialog.py:911-929` | kaczucha do końca nałożenia; model partiami |
| RT-01 | pierwsze otwarcie Realtime | 0,31 s | brak | BRAK, STOI | import i stan bazy w GUI | `main_window.py:1160`, rozgrzewka | moduł w rozgrzewce; otwarcie <0,5 s |
| DB-OPEN | otwarcie Modify DB | 0,18 s (Linux), Windows niezweryfikowane | puste okno | STOI | tabele w GUI | `modify_db.py:490-571` | dane w workerze; puste okno ≤100 ms |
| IMP-SCAN | Review reports | 1,1–10,8 s | kaczucha-op. | SPÓŹN. (od `show()`), STOI (84–86% klatek) | sygnał i restyle na plik | `parsing_dialog.py:841-875`, `ui_foundation.py:680` | ≤1,1 s od kliknięcia; ≥90% klatek |
| IMP-RUN | import | 12,9 s | kaczucha-op. (≈100% klatek) | SPÓŹN. nieznacznie (1,01–1,11 s; plan ×3 w GUI, 0,07 s) | — | `parsing_dialog.py:1127-1226` | jw.; etykieta etapu zamiast stałych 15% |
| EXP-RUN | 1. eksport w sesji | 1,7 s + eksport | kaczucha-op. od 2,7 s | SPÓŹN., STOI (przerwy do 381 ms) | import modułu w GUI przed `show()` | `export_dialog.py:98-102, 1318-1393` | ≤1,1 s także przy 1. kliknięciu |
| EXP-RUN (dashboard) | eksport HTML | 50,7 s (48 grup) | kaczucha-op., ApplicationModal | blokuje inne okna | — | `export_dialog.py:1368` | NonModal jak w Reports |
| CSV-03 | wczytanie CSV | 4,93 s | kaczucha-op. (53–60%, przerwy do 729 ms) | STOI; zamknięta przed nałożeniem wyniku | `_close_worker_progress` przed `_apply_tabular_load_result` | `industrial_analytics_dialog.py:2457-2489` | kaczucha do końca nakładania |
| CSV-09 | Create analytics | 50,3 s | kaczucha-op. (93%) | STOI na końcu (przerwa do 0,61 s) | składanie wyniku w GUI | `industrial_analytics_dialog.py:2618` + workflow | zastój <100 ms |
| CSV-06 | podgląd wartości | — | kaczucha-op. na każde zaznaczenie | LIFECYCLE (dialog i QMovie nie zwalniane) | `close()` bez `stop`/`deleteLater` | `tabular_analytics_filter_dialog.py:787-793` | dialog zwolniony, QMovie zatrzymany |
| IND-07 | eksport cache (i tryb live Oznak) | — | kaczucha-nat. | miganie przy krótkich; pasek stoi na 0 | brak opóźnienia i postępu | `industrial_export_dialog.py:457-488` | próg 1 s; postęp per paczka |
| IND-04 | pobieranie Oznak | sieć | tekst | BRAK | — | `industrial_sync_dialog.py:1052-1298` | nieblokująca kaczucha (nie zmierzono: brak źródła) |
| SHELL-START | start na Windows | warm 1,1 s bez okna; cold 2 s pustki | Qt splash po imporcie PyQt | BRAK, STOI | splash dopiero w aplikacji | launcher (PoC A1) | splash ≤150 ms, 0 ms pustki |
| SHELL-START | gotowość po pierwszym malowaniu | 0,37 s | status bar | STOI GUI (0,18 s) | rozgrzewka w GUI | `main_window.py:263-291` | zastój <50 ms (PoC: 40 ms) |
| Wszystkie z kaczuchą | — | — | — | LIFECYCLE | `QMovie.start()` przy tworzeniu; w Reports i CSV-06 brak zwolnienia | `worker_progress_dialog.py:57`, `parsing_dialog.py` | movie tylko gdy widoczny; dialog zwolniony |
| SHELL-THEME, GRP-EDIT, GRP-MAPEDIT, DB-APPLY (wiele zmian), VIS-01, TOOL-PLUGIN | — | czas niezweryfikowany | brak | BRAK, jeśli >1 s | praca w GUI | macierz | pomiar w PR |

Realtime: ciągły monitoring ma chip stanu (właściwe — to nie jest skończona operacja); skończone etapy
(pierwsze otwarcie, przebudowa po zmianie bazy) potrzebują kaczuchy.

## 8. Ranking optymalizacji

Zysk: Z = zmierzony, S = szacowany (z udziałem hotspotu w całym flow). Pewność: W/Ś/N. Koszt: M/Ś/D.

| # | Optymalizacja | Przyczyna | Wpływ na użytkownika | Zysk | Pewność | Koszt | Ryzyko | Zależności | Sprawdzenie |
|---:|---|---|---|---|---|---|---|---|---|
| 1 | Characteristic Mapping: jedno zapytanie + worker | N+1 | 2,7 min → <1 s, bez zawieszenia | Z: ≈370× | W | M | niskie | — | test równoważności (pełny: mała baza; próbka: duża) |
| 2 | Natywny splash + przekazanie | brak okna przed Pythonem/Qt | widoczny start <150 ms (cache); brak pustki | Z | W (warm) / Ś (cold) | Ś (PoC) | średnie (Win32) | warunki §5.6 | job osi czasu, ≥6 prób |
| 3 | Review w puli procesów + strumieniowanie do tabeli | szeregowo, powtórzone hashe/PDF, sygnał na plik | 25,6 s → ≈7 s kodu + narzut UI do usunięcia | Z (kod): 2,9–3,6× | W (kod) / Ś (UI) | Ś | średnie (rejestr w procesach) | C1 | identyczne wpisy i odczyty |
| 4 | Industrial → CSV Summary: COUNT raz, facety w SQL, worker | 4× COUNT, pętle Pythona po 1M wartości | 10 s zamrożenia → praca w tle | S: ≥4× | Ś | Ś | średnie | — | zgodność facetów i metadanych |
| 5 | Extended: jedna pula na eksport, workery z budżetu, równoległy dashboard | pula per referencja, max 2/4, dashboard szeregowo | 130 s → ≈95 s (S z proporcji 48 grup, 4 workery) | Z (48 grup): 1,4× vs dziś; 8 workerów bez dalszego zysku | Ś | Ś | średnie (≈280 MB/worker) | C1, **E1** | hash treści XLSX/HTML |
| 6 | CSV analytics: jeden fit rozkładu na serię, wektoryzacja konwersji, metryki w procesach | fity scipy na pełnych danych ×2, pętle Pythona | 50 s → <20 s (S) | S | Ś | Ś | średnie (statystyki identyczne) | C1 | statystyki i dashboard identyczne |
| 7 | Grouping: wektoryzacja + worker | lambda per grupa | 1,2 s → <0,3 s (S) | S | Ś | M | niskie | — | identyczne grupy |
| 8 | Wspólny mechanizm kaczuchy | timer od `show()`, GUI blokowane, lifecycle | kaczucha zawsze ≈1 s od kliknięcia | Z (luki) | W | Ś | **średnie** (8 miejsc z logiką zamykania/anulowania) | 1–7 | harness: `visible_ms` ≤1100, ≥90% klatek |
| 9 | Rozgrzewka w tle + moduł eksportu i realtime | importy w GUI | zastój 0,18 → 0,04 s; 1. eksport bez 1,7 s blokady | Z | W | M | średnie (importy równoległe) | warunki A2 | stall probe; test importu |
| 10 | Import: cache gotowości schematu, rejestr raz na import | 2× sprawdzenie schematu na raport, rejestr na raport | −≈20% importu (S z profilu) | S | Ś | M | niskie | — | identyczne wiersze |
| 11 | Industrial Data: status `oznak` bez importu | import `oznak` (48% profilowanego otwarcia) | 0,78 → ≈0,4 s | Z (profil) | W | M | niskie | — | profil |
| 12 | Gęstość wykresów: decyzja użytkownika zamiast automatu | `_apply_bottleneck_optimizations` | wynik nie zależy od szybkości maszyny | — (jakość) | W | M | niskie | **decyzja PO** | test deterministyczności |
| 13 | Supervisor: krótszy start | 2 procesy PyInstaller + hash | −0,1…−0,6 s na start | S | Ś | Ś–D | średnie (integralność) | decyzja PO | oś czasu Windows |
| 14 | Weryfikacja 2. startu w tle | blokada przy 2. starcie | −0,4…−7 s przy 2. starcie (zależnie od stanu dysku) | S | N | Ś | wysokie (trwałość) | decyzja PO | test przerwania zasilania |
| 15 | Modify DB: normalizacja w model/view + szybszy loader rekordów | itemy w GUI; loader 2,7 s | 0,18 → <0,1 s; 2,7 → ? s | S | Ś | M–Ś | niskie | — | golden #1121 |
| 16 | OCR w EXE: trwały worker | proces + model na wywołanie | tryb Complete: duży (niezmierzony) | S | N | D | średnie | Windows | pomiar z OCR |
| 17 | Kod natywny w EXE | `auto` = Python w EXE | statystyki porównawcze (#1120 pkt 10) | S | N | D | średnie | #908 | parytet |
| 18 | Budżet wątków BLAS/ONNX/rayon | nadsubskrypcja | Extended: −12% czasu, −47% CPU (BLAS=1, 4 workery) | Z (BLAS) / S (ONNX, rayon) | Ś | M | niskie | 5 | EXE na Windows; ONNX/rayon |
| 19 | `ensure_report_schema`: szybka ścieżka wersji | DDL + transakcja przy otwarciu okna | −7 ms/okno; brak blokady pisarza | Z | W | M | niskie | — | migracje |
| 20 | Motyw: odświeżanie tylko potrzebnych okien | pełny restyle | 0,20 s → ? | S | N | M | niskie | — | pomiar |

## 9. Plan PR-ów

**Baza:** gałąź referencyjna #1142 (`integrate/2026.09-rc1-build-261018`) do landowania #1109/#1142, potem
`develop`. **Baseline:** `benchmark_ui_flows.py` (mediana z 3, te same dane) i `windows-first-run-timeline`
na bazie PR-a, ta sama maszyna i stan cache. Semantyka danych bez zmian; zmiana jakości/zakresu tylko
po decyzji (partia E).

### Partia A — splash i responsywność

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| A1 Splash launchera | `packaging/launcher/**`, `app/launcher_splash.py`, `app/startup_splash.py`, supervisor; THIRD_PARTY_NOTICES (`gif`) | warm: 1068 ms bez okna → ≤150 ms; cold: 1,95 s pustki → 0; fokus 6/14 → 100% | maszyna stanów cache bez zmian (kod 75 itd.); **fallback okna postępu** przy wyłączonym/nieudanym splashu; splash przy naprawie po kodzie 75; brak splasha dla drugiej instancji; 2. start nie wolniejszy (§5.6) | kaczucha od ≤100 ms po starcie kodu do okna głównego; jeden splash; etap i postęp | `cargo test`, kwalifikacja launchera i portable, `test_launcher_splash.py`, oś czasu ≥6 prób z pauzą |
| A2 Rozgrzewka poza GUI | `ui/main_window.py` + moduły eksportu i realtime | zastój 0,18 → <0,05 s; 1. eksport 1,7 s → 0 | otwarcie narzędzia w trakcie rozgrzewki czeka na import tego modułu (brak równoległego importu tego samego pakietu); wątek nie-daemon, dołączany przy zamknięciu; Agg przed importem `pyplot` poza GUI; żaden moduł nie tworzy obiektów Qt przy imporcie | status bar bez zamrożenia | stall probe; test importu w wątku, w tym równoczesnego |
| A3 Operacja z kaczuchą | `ui/worker_progress_dialog.py` + operacje bez wskaźnika z §7 (7 powyżej 1 s, 3 krótsze zamrożenia) | `visible_ms` 0,98–2,7 s → ≤1,1 s od kliknięcia; klatki 53–100% → ≥90% | anulowanie, błąd, zamknięcie, ponowienie, spóźnione sygnały bez osieroconych dialogów; brak migania <1 s; logika `reject`/`finish` zachowana | próg od kliknięcia, etap, postęp lub tryb nieokreślony, throttling 20 Hz, wariant nieblokujący | harness (kryteria z kolumn), testy cyklu życia |

### Partia B — szybkie duże zyski

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| B1 Characteristic Mapping | jedno zapytanie + worker | 163 s → <2 s (PoC 0,44 s) | identyczne metryki, liczności, próbki referencji (porządek `LOWER(reference), reference`), schemat bieżący i legacy | kaczucha | PoC jako test równoważności |
| B2 Industrial → CSV Summary | `industrial_tabular_bridge.py`, `_sync_ui_state` | 10,0 s zamrożenia → otwarcie <1 s, praca w tle | identyczne metadane, facety, liczności; COUNT raz na zmianę filtra | kaczucha z etapem | testy bridge, harness |
| B3 Grouping | `data_grouping_service.py`, `data_grouping.py` | 1,23 s → <0,3 s | identyczne grupy, klucze, kolejność, zapis stanu | kaczucha >1 s | testy grouping, harness |
| B4 Industrial Data | `get_oznak_adapter_status` bez importu | 0,78 s → ≤0,4 s | ten sam tekst statusu | — | testy dialogu |
| B5 Modify DB | normalizacja w model/view + worker; szybszy loader rekordów | 0,18 s / 2,67 s → <0,1 s / ? | golden #1121, zmiany i undo | baner/kaczucha | `test_modify_db*`, harness |

### Partia C — batcher, pipeline, współbieżność

| PR | Zakres | Baseline → cel | Warunki poprawności | Loading/UX | Regresja |
|---|---|---|---|---|---|
| C1 Budżet zasobów | `shared/compute_budget.py`; pule; env wątków w initializerach | brak → jedna liczba workerów z budżetu; BLAS=1 w workerach (−12% w Extended) | wyniki identyczne przy 1/2/4/8; GUI <100 ms zastoju przy pełnym CPU | — | testy pul, 1/2/4/8 |
| C2 Review w puli | `preflight.py`, `metadata_review.py`, `parsing_dialog.py` | 25,6 s → ≤9 s (4) | identyczne wpisy (deduplikacja w kolejności), odczyty, override'y; wykrycie zmiany pliku; zgodna generacja rejestru; wyniki strumieniowo, sygnały throttlowane | postęp per paczka | `poc_review_parallel` jako test, `test_parsing_dialog_*`, regresje #1143 |
| C3 Extended plots | `export_summary_render_pool.py`, `export_data_thread.py` | 48 grup 35,3 → ≤26 s (4); dashboard szeregowo (50,7 s) → równolegle | identyczny XLSX/HTML przy **ustalonej gęstości** (wymaga E1: dziś odrzucanie wyników przy zmianie gęstości chroni zgodność z trybem szeregowym); kolejność zapisu; anulowanie | postęp per grupa | `scale_export` jako test, parytet PNG #1130 |
| C4 Import | `parse_reports_thread.py`, `report_repository.py`, `parsing_dialog.py` | 12,9 s → −≈20% (S); zastój 0,07 s → <0,05 s | identyczne wiersze; ponowna weryfikacja w puli kończy się błędem przed zapisem (fail closed); kolejność commitów | etykieta etapu | `test_import_*`, testy #1132/#1137 |

### Partia D — głębsze hotspoty

| PR | Zakres | Baseline → cel | Warunki poprawności | Regresja |
|---|---|---|---|---|
| D1 Render wykresów | cache wyszukiwania fontów, mniej przebiegów układu tekstu (`get_window_extent`), szybsze kodowanie PNG (bezstratne) | ≈1,0 s/grupę w 1 procesie → −30% (S; profil cProfile 45 s: układ i rysowanie tekstu ≈21%, w tym pomiar tekstu tabel paneli ≈10%; wyszukiwanie fontów ≈6%; kodowanie PNG ≈7%) | parytet pikseli wg #1126 | porównanie obrazów |
| D2 CSV analytics | jeden fit na serię współdzielony przez histogram/tabelę/PNG; wektoryzacja konwersji; metryki w procesach; szybsze wczytanie CSV | 50,3 s / 4,93 s → <20 s (S) | statystyki identyczne (#1133); bez próbkowania fitów (to decyzja) | `benchmark_csv_pipeline.py`, testy CSV |
| D3 OCR w EXE | trwały worker OCR | niezmierzone | identyczne wyniki, Job object | kwalifikacja OCR |
| D4 Kod natywny w EXE | promocja per most | #1120 pkt 10 | parytet (#908) | testy parytetu |

### Partia E — decyzje PO

| PR | Decyzja | Szacowany zysk | Ryzyko |
|---|---|---|---|
| E1 Gęstość wykresów | automatyczne „reduced" zależne od szybkości maszyny: zostaje, opcja, czy znika | determinizm; warunek C3 | jakość vs czas |
| E2 Supervisor | pominąć drugi hash przy zweryfikowanym cache / scalić rolę z launcherem | −0,1…−0,6 s na start | integralność, nadzór awarii |
| E3 Weryfikacja 2. startu w tle | start aplikacji przed końcem SHA-256 + flush | −0,4…−7 s przy 2. starcie | trwałość po utracie zasilania |
| E4 Mniejszy payload | cv2 75 MB, dwie kopie OpenBLAS (2× 20 MB) | krótszy skan AV i rozpakowanie | OCR, zależności |

## 10. Obszary nieweryfikowane

| Obszar | Czego brakuje |
|---|---|
| Czysty laptop Windows z AV użytkownika (#1101 A5) | sprzęt; tu tylko hostowany runner |
| Operacje UI w EXE na Windows (poza startem) | mierzone tylko na Linuksie ze źródeł (`balanced`); profil `performance` niemierzony |
| Pierwsze okno przy pierwszym uruchomieniu (PoC później o mediany ≈0,6 s, przed kodem launchera) | znaczniki startu kodu w obecnym launcherze; pomiar na czystym laptopie |
| Drugie uruchomienie z pauzą (n=2) | ≥6 prób na czystym laptopie |
| Realne raporty klientów, realny OCR (tryb Complete), układy wielostronicowe klientów | dane klienta (poufne), Windows z OCR |
| Oznak (IND-04), realtime ze źródłem (RT-03), Google Sheets | źródła produkcyjne, konto Google |
| QWebEngine (VIS-01), DPI per-monitor | środowisko okienkowe / wiele monitorów |
| Zimny dysk / dysk sieciowy | dane na tmpfs |
| Kwalifikacja launchera PoC (`qualify_windows_launcher.py`, portable) | nie uruchomiono |
| BLAS=1 w EXE na Windows; wątki ONNX i rayon w workerach | BLAS=1 zmierzony tylko na Linuksie (n=2) |
| Wersje bibliotek w EXE vs venv | `requirements.txt` ma zakresy |
| Naprawa cache „cannot replace a runtime still in use" (1/7 prób obecnego launchera, kod 102) | przyczyna (proces, AV, Restart Manager) |
| Modify DB open na Windows (0,18 s na Linuksie) | pomiar na docelowym sprzęcie |

## 11. Modele i delegacja (faktycznie użyte)

- Koordynator: **Claude Opus 5.5** (`claude-opus-5-5`), effort **max** (ustawienie użytkownika).
- Inwentaryzacja (tylko odczyt, maks. 2 równolegle): 3 × **Claude Sonnet 5.5** (`bounded_worker`, effort
  high) — A1 rdzeń UI, A2 dane UI, B nie-UI i mapa współbieżności. B przerwał na limicie sesji i został
  wznowiony.
- Niezależna weryfikacja: **Claude Opus 5.5** (`independent_reviewer`, effort high, świeży kontekst, tylko
  odczyt) — §12. Review różnicowe poprawek: **Claude Sonnet 5.5** (`light_reviewer`, effort medium, świeży
  kontekst, tylko odczyt). Wysiłek rozumowania w odpowiedziach: niewidoczny.
- GPT (Codex) nie był użyty: tygodniowy limit Codex wykorzystany w 79% (obserwacja 2026-10-19 17:52 UTC,
  reset 2026-10-25), później status nieznany — polityka wyłącza wtedy opcjonalną pracę drugiego dostawcy.
- Pomiary w profilu `balanced` (2026-10-20), porównanie z poprzednią wersją (261019) i profile:
  koordynator (Claude Opus 5.5, effort max), bez nowych agentów.
- **Wdrożenie pakietu (2026-10-20/21)**, według trailerów commitów i logów sesji:
  - koordynator: Claude Opus 5.5 (effort max) — plan, integracja, weryfikacja, benchmarki, diagnoza crashy,
    poprawki `a64f81f4`, `f0b45bef`, `d65bd744`, `3e5fe523`, `174c2f48`;
  - P01 (A1, launcher) i P07 (C2, pula Review): Claude Opus 5.5 (`claude_coordinator`, high);
  - P02–P06, poprawki R2 i rejestru wątków: Claude Sonnet 5.5 (`bounded_worker`, high);
  - od 2026-10-20 ≈18:45 (Codex dostępny, tryb BOTH): P08–P14, P09b, P13b, P07b oraz poprawki R3F/R4F —
    Codex `gpt-6.1-sol` (`implementer`, high; tożsamość modelu po stronie serwera: niewidoczna), w osobnych
    worktree, bez commitów; commity i integracja — koordynator;
  - przeglądy: R1–R4 i R4Δ — Claude Opus 5.5 (`independent_reviewer`, high, świeży kontekst, tylko odczyt).
- **Zużycie Codex** (okno tygodniowe planu `prolite`, odczyty z logów sesji): 0% przed P09 → 26% po P07b/P12b,
  w tym prace użytkownika poza pakietem; pakiety FEATURE: mediana ≈1 p.p. i ≈9,5 mln tokenów (głównie cache)
  na pakiet. Przyrosty przebiegów równoległych nie są przypisywalne pojedynczo.

## 12. Niezależna weryfikacja

Werdykt: **ACCEPT WITH CHANGES** — bez P0/P1; główne wnioski potwierdzone w kodzie i dowodach (N+1 w
Characteristic Mapping, zamrożenia Industrial → CSV Summary i Grouping, import modułu eksportu przy 1.
kliknięciu, szeregowy Review, wady mechanizmu kaczuchy). Rozliczenie uwag:

| Uwaga | Rozliczenie |
|---|---|
| P2: brak fallbacku okna postępu (splash wyłączony/nieudany) | warunek A1 (§5.6 p.1); komentarz w kodzie sprostowany; wariant A/B opisany jako „bez okna", nie „stare zachowanie" |
| P2: naprawa po kodzie 75 bez okna | warunek A1 (§5.6 p.2) |
| P2: splash nie zamykany na ścieżce błędu aplikacji | **poprawione** w PoC: `close_bootloader_splash` zamyka też splash launchera dla faz błędu/smoke |
| P2: ryzyka rozgrzewki w wątku | warunki A2 (§9) |
| P2: „PRZYJĘTY" zbyt mocne; §4 nieaktualne | §1.3 „PRZYJĘTY WARUNKOWO"; §4 z 3 runów + A/B; §5.5 „nie wykazano" dla pierwszego okna |
| P2: liczby skalowania bez dowodu | powiązane z `scale3` (1/2/4) i `scale2` (8), gęstość „reduced" opisana; plik pomiarów w repo |
| P2: brak luki IMP-REVIEW (1,2 s po zamknięciu kaczuchy) | dodane do §7 i macierzy |
| P2: zysk Review zawyżony | §1.1/§8: zysk kodu, narzut UI osobno (C2) |
| P2: C3 bez odrzucania wyników zmieszałoby gęstości | C3 zależy od E1 |
| P2: SIGSEGV w scenariuszach Industrial | zbadane: crash przy niszczeniu obiektów Qt po pomiarze (faulthandler), harness poprawiony, 6/6 bez błędu (§3.4) |
| P3: wyścig `recv_timeout`, DPI per-monitor, `cbData` spoza BMP | **poprawione** w PoC (uchwyt z `WINDOW`, system-aware DPI, długość UTF-16 w bajtach) |
| P3: niespójne zakresy, brak logu PoC mapowania, n=1 vs mediany, Main plots 1500, loader rekordów | poprawione: mediany, log PoC (`followup2`), Main plots w §1.1/§4/§9, B5 rozszerzone |
| P3: wada 3 uogólniona | zawężone (Reports, CSV-06) |
| P3: ryzyko A3 „niskie" | „średnie" |
| P3: brak podokien filtra/grupowania Industrial, tryb live IND-07 | dodane do macierzy |

Review dotyczyło kodu PoC na `28619733`. Poprawki (`28619733..c212f7b3`, 258 linii) przeszły review
różnicowe: 7/7 potwierdzone (FIXED), bez P0/P1–P2; trzy nowe uwagi P3 — dwie są warunkiem A1 (§5.6 p.6),
trzecia dotyczy tylko harnessu (separatory `,`/`;` w specyfikacji wariantu). Recenzent nie uruchamiał
testów ani Windows; testy uruchomił koordynator (§13).

Aktualizacja liczb (profil `balanced`, porównanie z 261019; tylko dokumentacja, kod PoC bez zmian) nie
przeszła osobnego review; tabele §4 i §4.1 sprawdzone skryptem względem JSON.

## 13. Walidacja gałęzi PoC

Lokalnie na `c212f7b3` (Linux, 2026-10-20): `ruff check .`, skan sekretów względem bazy, higiena wydania,
spójność metadanych wydania — zielone; 22 testy-strażniki repo (rejestry, ratchety, Bandit, linki
dokumentów) i testy startu/splasha: 786 passed, 2 skipped; `security_audit.py --ci --skip-pip-audit`
(bez weryfikacji repozytoriów siostrzanych) — passed; launcher: `cargo test --locked` 57 + 19 passed,
`cargo check --target x86_64-pc-windows-gnu --all-targets` czysto. Pełnego zestawu testów lokalnie nie
uruchomiono (CI na draft PR).

| Run CI (workflow_dispatch) | Commit | Wynik |
|---|---|---|
| 39315596611 | `22ed6048` | oś czasu zielona; Unit tests: 8 failed (rejestr bug-sweep bez nowych skryptów — poprawione) |
| 39318835183 | `5c2537e5` | oś czasu czerwona z założenia: jedna próba obecnego launchera (corrupt) zakończyła się kodem 102, skrypt zwraca 1 przy każdej nieudanej próbie; dane w artefakcie; Unit tests: 8 failed (rejestr bug-sweep, jw.) |
| 39322360692 | `727ec741` | oś czasu zielona; Unit tests: 1 failed (ratchet C901 148 > 147 — poprawione refaktorem harnessu) |
| 39332127323 | `28619733` | wszystkie joby zielone (3 rundy) |
| 39349370988 | `24caad6a` | wszystkie joby zielone (A/B: pauza 20 s, wariant bez okna, 2 rundy) |

PR CI (pull_request): 39355425735 (`81afafd8`) i 39357842326 (`23bbe6c3`, druga próba) — zielone;
39369734566 (`58616f81`, tylko dokumentacja) — Unit tests przerwane limitem 45 min: pytest zawiesił się po
59% (okno testów parserów i `parsing_dialog`; te 271 testów przechodzi lokalnie w 24 s). Wynik dla tej
wersji raportu: komentarz w PR.

# Metroliza — audyt wydajności po STEP2 i szacunek STEP3

Poprzedni etap: [performance-boost-step2.md](performance-boost-step2.md).
Raport wdrożenia i stan pomiarów: [performance-boost-step3.md](performance-boost-step3.md) — T28 zakończony: 23 scenariusze, pełny audyt 18: 17,60% krócej; porównanie czterech etapów, zgodność wyjść i jawne ograniczenia.
Plan wdrożenia (EN, dla Codex): [performance-boost-step3-implementation.md](performance-boost-step3-implementation.md). Tracker: Issue #1151.

Rewizja audytowana: `101e5a44` (gałąź `perf/step2-boost`, czyli kod po STEP2). Data: 2026-10-21.
Maszyna: laptop Linux, Xeon W-10855M (6 rdzeni / 12 wątków), profil zasilania `balanced`.
Dane: wyłącznie **syntetyczne** z harnessu (`db_1500`, `db_small`, `csv_100k`, `ind_50k`, `pdf_1500`).
Punkt odniesienia: spokojne mediany po STEP2 z pomiaru trzech wersji (ta sama maszyna i harness `a71e7496`).

## 1. Najważniejsze w skrócie

- **Pokrycie:** GPT przejrzał w 29 małych kawałkach wszystkie **7009 funkcji i metod** z 288 plików (Python oraz launcher w Rust). Każdą sklasyfikował: 5053 jako `ok`, 1509 jako `cold` (ścieżki rzadkie lub administracyjne), a 447 wskazuje na jedno ze **126 znalezisk**. Sam dołożyłem **7 luk** międzymodułowych, których przegląd po kawałkach nie mógł zobaczyć.
- **Realny boost jest nadal duży.** Trzy największe zyski sprawdziłem jako PoC w izolowanych worktree, w pomiarze A/B. W dwóch przypadkach wynik jest bajt w bajt taki sam:
  - **Extended (216 grup): −34%** dzięki dwóm zmianom. Każdy PNG i każdy arkusz są identyczne.
  - **Eksport Main:** zapytania partycji 3,6 s → 1,27 s. Wiersze są identyczne, w tej samej kolejności.
  - **Filtr:** zapytania wartości 1,05 s → 0,28 s. Wyniki są identyczne.
  - **CSV analytics:** pula procesów dla metryk daje −17%, ale kosztuje około 750 MB pamięci. To zysk realny, ale wymaga decyzji.
- **Szacunek STEP3:** suma 18 mierzonych przepływów **231,6 s → około 162 s (−30%)**, w zakresie 144–184 s (−38% … −21%). Największe pozycje:
  - Extended 68,8 → ~42,5 s;
  - CSV analytics 35,4 → ~26,5 s;
  - repo-benchmark CSV Summary 64,9 → ~45 s;
  - Main 27,7 → ~20,8 s.
- **Poza sumą:** kilkusekundowe zamrożenia GUI przy grupowaniu 100 tys. wierszy (3,9–7,2 s przy otwarciu okna grupowania; mikropomiar GPT) oraz długie anulowanie eksportu i analityki (szacunek do ~15 s i ~30 s, niezmierzone). Harness tych scenariuszy dziś nie mierzy.
- **Decyzje PO:** potrzebne w trzech miejscach. Szczegóły w sekcji 6:
  - poziom kompresji XLSX;
  - budżet pamięci dla puli CSV analytics;
  - odroczenie facetów w mostku Industrial.

## 2. Weryfikacja: PoC i pomiary na danych harnessu

Pomiary A/B przeprowadziłem 2026-10-21 w godzinach 19:45–20:20 CEST (17:45–18:20 UTC):
- w kolejności ABBA, n=2 na stronę, sekwencyjnie, pod wspólną blokadą ciężkich zadań (nigdy dwa pomiary naraz);
- na tym samym harnessie, w profilu `balanced`;
- przy aktywnym pulpicie (Firefox, loadavg 1,5–6), więc **czasy bezwzględne są o 10–30% wyższe** niż spokojny punkt odniesienia.

Do szacunku używam proporcji z jednej sesji, nie czasów bezwzględnych.

| Sprawdzenie | Przepływ | A (101e5a44) | B (PoC) | Zmiana | Tożsamość wyniku |
| --- | --- | --- | --- | --- | --- |
| PoC1: tabela panelu histogramu bez pomiarów, które i tak są odrzucane (A01-F01) | Extended 216 grup | 77,5 / 73,7 s | 66,0 / 65,3 s | **−13%**, CPU workerów −32 s | 1114 elementów XLSX identycznych (oprócz znacznika czasu w `docProps/core.xml`) |
| PoC2: Plotstats renderuje przed zbudowaniem wykresu matplotlib, który potem jest wyrzucany (A02-F01, A04-F01) | Extended, ponad PoC1 | 65,1 / 64,6 s | 48,9 / 49,3 s | **−24%**, CPU workerów −58 s | jw.: 864 PNG i wszystkie XML identyczne |
| Razem PoC1+PoC2 | Extended | — | — | **−34%** (współczynnik 0,658) | jw. |
| PoC3: wykresy metryk CSV analytics w puli spawn (4 procesy), wyniki w kolejności (luka C-05) | CSV analytics 100k | 45,6 / 41,0 s | 37,3 / 34,6 s | **−17%**; RSS 650 → 1400 MB, CPU łącznie +73% | `dashboard.html` identyczny po zamaskowaniu znaczników czasu |
| Zapytania partycji na indeksowanej kolumnie (A02-F02, B04-F01) | Main, 37 partycji, sam SQL | 3,51 / 3,77 s | 1,29 / 1,26 s | **−2,3 do −2,5 s** | wiersze identyczne, ta sama kolejność |
| Wartości filtra z relacji raportów + `EXISTS` (A09a-F02) | Filtr, sam SQL | 0,97 / 1,05 / 1,15 s | 0,28 / 0,28 / 0,28 s | **−73%** | 13 zbiorów wyników identycznych |
| Koszt kompresji zlib przy zapisie XLSX (A03-F01, luka C-04) | Main / Extended | 4,96 s / 1,38 s CPU (poziom 6) | 1,22 s / 1,05 s (poziom 1) | Main −3,7 s przy poziomie 1 | cały plik Main 39 → 53 MB (+34%) |

Łatki PoC (tylko do pomiaru, nie do scalenia; względem `101e5a44`) w katalogu [performance-boost-step3-poc/](performance-boost-step3-poc/):
- `poc1_table_layout.patch`;
- `poc2_plotstats_first_with_poc1.patch` (PoC1 + PoC2);
- `poc3_metric_pool.patch`.

## 3. Luki do zapełnienia w STEP3 (pakiety)

Oznaczenia dowodu:
- **Z** — zweryfikowane pomiarem lub PoC;
- **K** — mechanizm potwierdzony przeze mnie w kodzie;
- **W** — wiarygodne: mechanizm i mikropomiar GPT, osobno niesprawdzone;
- **D** — wymaga decyzji PO.

### S3-1 Extended: wykresy podsumowań (12 znalezisk) — największy pojedynczy zysk
1. **Z — A01-F01** — `render_panel_table` wywołany z jawnymi proporcjami kolumn i wspólnymi wysokościami wierszy i tak mierzy każdy tekst, w 10 przebiegach na tabelę (56 tys. pomiarów przy 216 grupach). Żaden wynik pomiaru nie jest używany. Wysiłek S.
2. **Z — A02-F01/A04-F01** — przy domyślnym backendzie `matplotlib` budujemy i stylujemy pełny wykres rozkładu, IQR i trendu, a dla geometrii robimy pełny `canvas.draw()`. Potem Plotstats renderuje własny PNG, a nasz wykres trafia do kosza. Wykres należy budować tylko przy fallbacku. Slot obrazu liczy się z rozmiaru figury; `resolved_render_spec` czyta wyłącznie natywny kompozytor. Wysiłek M.
3. **W — A01-F02** — adnotacje histogramu robią `draw_without_rendering()` całej figury (wraz z tabelą) przed wyborem pozycji etykiet. Szacunek: −1…−2,5 s.
4. **K — A01-F03** — gotowa krzywa modelu jest rysowana przez `sns.lineplot`, a nie `ax.plot` (seaborn jest w `requirements.txt`). 216 × ~19 ms CPU, czyli −0,5…−1 s.
5. **W** — liczby jako listy Pythona zamiast masek NumPy (A01-F04, A03-F04). Pierwsza grupa każdej referencji jest liczona szeregowo w procesie rodzica (A03-F02). Zysk zależy od liczby referencji.

### S3-2 Main: dane partycji i zapis arkuszy (7)
1. **Z — A02-F02/B04-F01** — 37 partycji filtruje się po wyliczanym `EXPORT_PARTITION_KEY`, więc indeks snapshotu na `REFERENCE` nie działa i każda partycja skanuje 216 tys. wierszy. Rozwiązanie: predykat na `REFERENCE`/`REPORT_ID` albo jeden uporządkowany przebieg. Uwaga na typy (liczbowe referencje). Wysiłek M.
2. **W — A02-F03, A18-F02** — sortowanie bloku nagłówka kopiuje tabelę, dokłada kolumnę, sortuje i ją usuwa. Wystarczy posortować indeksy, co daje −0,6…−1,5 s.
3. **W — A02-F05, A03-F05** — wpisy nagłówków są liczone z góry dla całej referencji. Do tego dochodzi pełna konwersja tabeli do krotek: 80–275 MB przejściowo.
4. **W — C-07 (moje)** — kolejną partycję można czytać w wątku, w czasie generowania XML poprzedniej (SQLite zwalnia GIL). Po naprawie z punktu 1 zostaje około −0,5…−1 s, więc to niski priorytet.

### S3-3 Pakowanie XLSX (2 + luka C-04)
- **Z/D — A03-F01 + C-04** — XlsxWriter kompresuje wszystko poziomem 6, szeregowo, na samym końcu eksportu. W Main to 289 MB surowego XML i **5 s CPU**. Dwie drogi:
  - **(a)** równoległa kompresja elementów w wątkach (zlib zwalnia GIL), z tym samym poziomem i bez zmiany rozmiaru pliku: około −3…−4 s w Main i −1 s w Extended. Wysiłek M, wiązanie z wersją XlsxWriter;
  - **(b)** poziom 1: −3,7 s, ale plik o 34% większy — **decyzja PO**.
- **W — A03-F06** — cache formatów rośnie bez ograniczeń (`id(workbook)`). Dotyczy pamięci, nie czasu.

### S3-4 CSV analytics: dashboard (14 + luki C-02, C-05)
1. **Z/D — C-05** — 8 metryk liczy się szeregowo w jednym wątku (`cpu_children` = 0). PoC z pulą daje −17% przy +750 MB. Lepszy projekt to pula tylko dla dopasowań rozkładów: 24 dopasowania Nelder-Mead na 100 tys. wartości, `johnsonsu` itd., około 35% przepływu. Do tego ciepła pula i równoważenie per wykres. Spodziewane −15…−30%.
2. **K — C-02 (moje)** — 13 modułów ma pośrednik `_LazyPandas`; 12 z nich przy każdym dostępie wywołuje `importlib.import_module("pandas")`. Tylko `ui/data_grouping.py` zapamiętuje atrybut (od STEP2). `_json_values` woła `pd.isna` dla każdej wartości: **400 tys. importów na jedno uruchomienie**, około 0,5–1,5 s (szacunek z profilu). Naprawa: ten sam cache we wszystkich pośrednikach i wektorowa maska NA.
3. **W — A04-F03, A04-F04, A04-F05** — `finite_float_list` przechodzi przez 8,8 mln wywołań `as_finite_float`, klucze legendy liczą geometrię przed sprawdzeniem nazwy, a biny są wyliczane dwa razy. Razem około −3…−5 s CPU.
4. **W — A11-F02, A11-F01, A11-F07** — writer dashboardu klonuje specyfikacje 2 razy i mierzy je 4 razy. Surowe ślady czasowe są budowane także wtedy, gdy i tak trafią do warstwy statycznej. Razem około −2…−4 s.
5. **W — B02/B03** — eksport HTML dashboardu: podwójne pomiary i konwersje list, −0,1…−1,5 s.

### S3-5 CSV Summary: skoroszyt i walidacja (4 + luka C-03)
- **K — C-03 (moje)** — arkusze danych skoroszytu CSV Summary idą przez zwykłe API XlsxWriter, komórka po komórce: 4,6 mln wywołań `_write`, 1 mln `cell_wrapper`. Szybka ścieżka bulk ze STEP1 (`xlsx_bulk_sheet`) obsługuje tylko eksport raportów. W repo-benchmarku `workbook_export` trwa 31 s z 65 s. Szacunek: −8…−12 s.
- **K — A06-F01/A10-F01** — to samo grupowanie (100 tys. przypisań) jest walidowane 3–4 razy, w tym na wątku GUI. W profilu repo-benchmarku `validate_industrial_analytics_request` zajmuje 6,9 s (z narzutem cProfile). Rozwiązanie: jeden zwalidowany, niezmienny snapshot.

### S3-6 Import i Review (17)
- **K — A07-F02/A08b-F02** — `get_registry_snapshot()` domyślnie odświeża rejestr pluginów: 6001 razy na import 1500 raportów, czyli około 10% profilu importu. **Uwaga: to celowa decyzja STEP2** (P05, `585a33d0`: brak taniego, dokładnego sygnału zmiany, który zachowałby kontrolę generacji w trakcie importu jako fail-closed). Zmiana jest możliwa tylko wtedy, gdy znajdzie się taki sygnał (np. stat plików konfiguracji), −0,4…−0,8 s; w przeciwnym razie pozycja odpada. Szacunek importu poniżej to uwzględnia.
- **W — A09a-F01** — zapis ponownie przelicza wiersze, które przygotowanie w procesach już zbudowało, −0,4…−1,2 s. Dotyczy tylko sytuacji, gdy pula przygotowania jest włączona; w spakowanej aplikacji jest opt-in.
- **W — A07-F03** — tożsamości do wzbogacania metadanych mają koszt O(n²): 0,26 s przy 1500 raportach i 3,5–4,4 s przy 6000.
- **W — A08a-F03, A09b-F01** — Review: normalizacja statusu dla liczb typu float, NFKD dla tekstu ASCII, −0,5…−1,4 s.
- **W — A08a-F01/F02, A08b-F01, A08a-F04** — szybki odczyt metadanych:
  - nowa pula bez zasilonego cache sond;
  - pełny tekst wszystkich stron, choć potrzebny jest tylko nagłówek;
  - `get_text("dict")` z bajtami obrazów.

  Razem 15–30% tego etapu.
- **W — A07-F01** — limit cache sond to 2048 par plik × plugin. Powyżej 2048 raportów cache wypycha to, czego za chwilę potrzebuje. Prawdopodobnie to ten sam mechanizm co #1143 (próg 2048 raportów) — do potwierdzenia.

### S3-7 SQL i ładowanie w oknach (22 + luka C-01)
- **Z — A09a-F02** — filtr, około −0,7 s z 1,29 s.
- **W — A09a-F03** — Characteristic Mapping: CTE `metric_source` jest wstawiane dwa razy; `MATERIALIZED` daje −0,2…−0,35 s.
- **K/W — A10-F02/F03/F04/F05** — mostek Industrial → CSV Summary:
  - złączenie rekordy × pola przed `GROUP BY` (A10-F02);
  - funkcja Pythona dla każdej wartości (A10-F04);
  - fasety bazowe liczone z góry (A10-F03, wymaga decyzji PO).

  Razem 5,7 → ~3,8 s.
- **K — A05-F01, A05-F03, A05-F04** — wczytanie CSV: te same komórki są normalizowane trzy razy, a regex identyfikatora działa dla każdej liczby. 4,7 → ~3,7 s.
- **W — A14-F05, B07-F01, A06-F05, A14-F06** — otwarcia Grouping i Modify DB.
- **K — C-01 (moje)** — Modify DB buduje indeks wyszukiwania (tekst małymi literami dla 216 tys. wierszy) przed pokazaniem tabeli. Można go zbudować w tle albo przy pierwszym wyszukiwaniu: −0,3…−0,6 s z 2,39 s.

### S3-8 Responsywność GUI przy dużym grupowaniu (20) — poza sumą, ale odczuwalne
Scenariusz: CSV Summary lub analityka Industrial ze 100 tys. przypisań i około 200 grupami. Mikropomiary GPT na syntetycznych danych:
- odtworzenie przypisań w konstruktorze okna grupowania: **3,9 s** zamrożenia, a z kolorami 7,2 s (A15b-F01/F02);
- przemalowanie selektora: 1,1–1,3 s (A15b-F02);
- odświeżenie stanu: 0,4–1,1 s (A15a-F01);
- zaznaczenie 1000 części: 1,5–2,1 s (A14-F01);
- predykaty kluczy grupowania: 0,5–1,8 s (A06-F02).

Wszystkie poprawki są algorytmiczne (jedno sortowanie zamiast N, memoizacja koloru, blokowanie sygnałów). Wysiłek S–M.

### S3-9 Anulowanie i zamykanie (10)
- **W — A03-F03** — anulowany eksport nadal serializuje i kompresuje cały skoroszyt przed usunięciem pliku. Przy Main to do około 15 s (szacunek z udziału w profilu, niezmierzone).
- **W — A10-F08/A11-F06** — anulowanie CSV analytics nie dociera do budowy manifestu ani writera. Można czekać do około 30 s (szacunek, niezmierzone).
- **W — A14-F08, A15a-F02** — `wait()` na wątku GUI przy zamykaniu, do 2–4 s.

### S3-10 Group Analysis (5) i S3-11 higiena (13)
- **S3-10:** w Group Analysis tabela jest normalizowana dwa razy (−1…−1,6 s przy 100 tys. wierszy, A18-F01), a słowniki na wiersz służą do odczytu klucza (A18-F03). Harness tego przepływu nie mierzy.
- **S3-11, drobne:**
  - motyw: −0,02…−0,06 s;
  - importy Realtime: −0,05…−0,15 s;
  - SciPy w module specyfikacji wykresów;
  - QMovie splasha nie jest zatrzymywany;
  - ramki splasha w launcherze (10 MiB);
  - polityka GC (A16-F01): rzadziej robić pełne zbiórki. Nie zmieniać bez osobnego testu stabilności — chroni przed SIGSEGV.

## 4. Szacunek STEP3 dla każdego przepływu

Punkt odniesienia: spokojne mediany po STEP2. Wartości „spodziewane” zakładają wdrożenie pakietów S3-1…S3-7:
- dla Main przyjąłem równoległą kompresję, która nie zmienia pliku i nie wymaga decyzji;
- dla CSV analytics i benchmark_paths przyjąłem pulę dla obliczeń metryk (decyzja E6). Bez niej spodziewane jest około 29,5 s i 48 s.

Zakres to najlepszy i najgorszy przypadek.

| Przepływ | Po STEP2 | Po STEP3 (spodziewane) | Zakres | Dowód |
| --- | ---: | ---: | --- | --- |
| Review 1500 PDF | 8,40 s | 7,2 s (−14%) | 6,4–7,9 | W |
| Import po Review | 9,6 s | 8,4 s (−12%) | 7,2–9,2 | K/W |
| Modify DB — otwarcie | 0,18 s | 0,13 s | 0,10–0,16 | W |
| Modify DB — rekordy 216k | 2,39 s | 1,95 s (−18%) | 1,8–2,2 | K |
| Modify DB — zapis | 0,05 s | 0,05 s | — | — |
| Okno eksportu | 0,12 s | 0,12 s | — | — |
| Filtr — otwarcie | 1,29 s | 0,55 s (−57%) | 0,45–0,75 | Z |
| Grouping — otwarcie | 0,62 s | 0,45 s (−27%) | 0,35–0,55 | W |
| Characteristic Mapping | 0,80 s | 0,55 s (−31%) | 0,45–0,65 | W |
| Eksport Main plots 1500 | 27,68 s | 20,8 s (−25%) | 18,7–22,8 | Z/D |
| Extended 216 grup | 68,8 s | 42,5 s (−38%) | 39,5–46,5 | Z |
| Zmiana motywu | 0,17 s | 0,14 s | 0,12–0,16 | W |
| CSV — wczytanie 100k | 4,71 s | 3,7 s (−21%) | 3,3–4,2 | K |
| CSV analytics 100k | 35,39 s | 26,5 s (−25%) | 22,0–30,5 | Z/W |
| Industrial Data — otwarcie | 0,33 s | 0,30 s | 0,29–0,32 | W |
| Industrial → CSV Summary | 5,73 s | 3,8 s (−34%) | 3,0–4,6 | K/W |
| Realtime — pierwsze otwarcie | 0,40 s | 0,30 s | 0,25–0,36 | W |
| benchmark_paths CSV Summary | 64,9 s | 44,9 s (−31%) | 39,4–52,9 | K/W |
| **Suma 18 przepływów** | **231,6 s** | **162,3 s (−30%)** | **143,5–183,9 (−38…−21%)** | |
| Suma 17 przepływów UI | 166,7 s | 117,4 s (−30%) | 104,1–131,0 | |
| Bez 3 najdłuższych | 62,5 s | 48,4 s (−23%) | 42,6–54,0 | |

Start aplikacji (zamrożenie po pierwszym malowaniu 50 ms, rozgrzewka 1,7 s) się nie zmienia. Dla porównania: STEP2 zszedł z 502,0 s do 231,5 s na tych samych 18 przepływach.

Dla spakowanej aplikacji Windows (2 workery renderu) PoC1 i PoC2 obniżają CPU każdego wykresu o około 35%. Zysk w sekundach powinien być więc **większy** niż na Linuksie. Pula CSV analytics da tam mniej (2 procesy). Żadnej z tych rzeczy nie mierzyłem na Windows.

## 5. Kolejność wdrożenia (propozycja)

1. **S3-1 (PoC1 + PoC2):** największy, sprawdzony zysk z identycznym wynikiem, około −26 s Extended; wysiłek S+M.
2. **S3-7 + S3-2:** zapytania w filtrze, Mapping, partycje Main, mostek Industrial i CSV load — tanie, lokalne zmiany SQL i pętli, około −6 s.
3. **S3-4 + S3-5:** C-02, szybkie ścieżki liczb, writer dashboardu, bulk writer dla skoroszytu CSV Summary, jeden snapshot walidacji — około −15…−25 s w CSV.
4. **S3-3:** równoległa kompresja XLSX (albo decyzja o poziomie), około −3…−4 s Main.
5. **S3-6:** import i Review, około −2…−3 s.
6. **S3-8 + S3-9:** responsywność i anulowanie. Najpierw nowe scenariusze w harnessie (sekcja 7), potem poprawki.

## 6. Decyzje PO

- **E5 — poziom kompresji XLSX:** zlib 6 → 1 daje Main −3,7 s, ale plik +34% (39,6 → ~53 MB). Bez decyzji: równoległa kompresja z tymi samymi bajtami, wysiłek M.
- **E6 — budżet pamięci dla puli CSV analytics:** PoC daje −17% przy +750 MB szczytowego RSS (4 procesy, Linux). Proponuję wariant z pulą tylko dla dopasowań rozkładów, z mniejszym narzutem pamięci, a przed decyzją osobny PoC.
- **E7 — odroczenie facetów bazowych w mostku Industrial (A10-F03):** mostek otwiera się o 0,6–1,0 s szybciej, ale pierwsze otwarcie filtra kolumny bazowej przejmuje ten koszt.
- **Czego nie proponuję:** zmniejszania zakresu obliczeń (np. dopasowań na próbce zamiast 100 tys. wartości), gęstości ani jakości wykresów. Każda z tych zmian wymagałaby jawnej decyzji, a powyższe zyski jej nie potrzebują.

## 7. Czego nie zweryfikowałem i ryzyka

- **91 znalezisk o werdykcie W** opiera się na analizie GPT i jego mikropomiarach, które nie są pomiarami całego przepływu. Szacunki z udziałów w profilu przeliczyłem z poprawką na narzut cProfile (kod Pythona w profilu jest 1,5–2,5× wolniejszy). Nie sumowałem pozycji, które się nakładają.
- **Pomiary PoC robiłem na zajętym pulpicie.** Proporcje pochodzą z jednej sesji w kolejności ABBA (n=2). Spokojny pomiar końcowy trzeba zrobić po wdrożeniu.
- **Windows:** niezmierzony. Szczególnie zachowanie puli CSV oraz zysk z równoległej kompresji przy 2 workerach.
- **C-06 (moje): harness nie ma scenariuszy** dla:
  - grupowania 100 tys. przypisań (S3-8);
  - opóźnienia anulowania (S3-9);
  - podziału Review na skan i szybki odczyt metadanych;
  - Group Analysis.

  Trzeba je dodać przed S3-8/S3-9, żeby zmierzyć efekt.
- **PoC to wyłącznie prototypy pomiarowe.** Wdrożenie wymaga:
  - testów fallbacku (Plotstats niedostępny, wykres natywny);
  - testów parzystości obrazów;
  - testów typów referencji w predykacie partycji;
  - limitów pamięci puli.
- **Polityka GC (A16-F01):** nie zmieniać bez osobnego testu stabilności na Windows; problem ponownego otwarcia nadal tam wraca.

## 8. Metoda, modele i zużycie

- **Profilowanie:** profile cProfile wszystkich 19 przepływów harnessu i startu na `101e5a44`, uruchamiane tylko diagnostycznie. Do tego profil repo-benchmarku CSV Summary i profil CSV analytics z wywołującymi. Czasy z profilowania nie są wynikami.
- **Przegląd kodu przez GPT (Codex CLI, `codex exec`, piaskownica read-only):**
  - poziom A: `gpt-6.1-sol` z wysiłkiem `high`, 21 kawałków (4096 definicji), 2 jednocześnie;
  - poziom B: `gpt-6-luna` z wysiłkiem `high`, 8 kawałków (2913 definicji).

  Model i wysiłek pochodzą z `turn_context` sesji, czyli są skonfigurowane; tożsamość po stronie odpowiedzi jest „not visible”. Każdy kawałek zwrócił `findings.json` z pokryciem każdego id manifestu (0 braków).
- **Koordynacja, synteza, luki C-01…C-07, PoC i pomiary:** Claude Opus 5.5 (`claude-opus-5-5`), wysiłek max. W STEP3 nie używałem subagentów Claude.
- **Luki C-01…C-07:** C-01 indeks wyszukiwania Modify DB, C-02 `_LazyPandas`, C-03 bulk writer dla skoroszytu CSV Summary, C-04 równoległa kompresja XLSX, C-05 pula metryk CSV analytics, C-06 brakujące scenariusze harnessu, C-07 odczyt partycji w tle.
- **Zużycie Codex:** okno tygodniowe 36% → 46% (+10 pp) w trakcie poziomu A; poziom B mieścił się w zaokrągleniu.

  | Poziom | Uruchomienia | Tokeny wejścia | W tym cache | Tokeny wyjścia |
  | --- | ---: | ---: | ---: | ---: |
  | A | 21 | 53,3 mln | 50,2 mln | 431 tys. |
  | B | 8 | 10,2 mln | 9,5 mln | 88 tys. |

  Wpisy są w ledgerze `codex-dispatch`.

Pełna lista 126 znalezisk z werdyktem i pakietem: [performance-boost-step3-findings.md](performance-boost-step3-findings.md).

Dane maszynowe: [performance-boost-step3-findings.json](performance-boost-step3-findings.json) (pakiet, werdykt i szacunek GPT dla każdego znaleziska) oraz [performance-boost-step3-estimate.json](performance-boost-step3-estimate.json) (szacunek dla przepływów).

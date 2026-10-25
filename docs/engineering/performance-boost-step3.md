# Performance Boost STEP3 — raport wyników

> Stan na2026-10-25: implementacja fal0–7 oraz C01–C05 zweryfikowana; T26 WITHHELD. T28 pozostaje nieukończone: przyjęto2/23przepływy bieżącej kampanii,2serie wykluczono,19nie uruchomiono. Brakujące pomiary są PENDING; nie jest to zamknięcie #1151 ani akceptacja spakowanego Windows.

## Bieżąca kampania C05 — cztery etapy, moduły i suma

Dokładne wersje: przed STEP1`fb72a42e`, po STEP1`15ddbeb7`, po STEP2`101e5a44`, po STEP3`e2f9f273`; produkt src`9689863e47c04ca6960a48b3daf831d138e28508`. Wspólny harness`5e2c762fef893717148d8add56fec1f872d27c44654afb00094d60c46044a315`, pełne syntetyczne wejście, balanced/AC, CPU8 i rotacja12prób (n3/etap) w obu przyjętych scenariuszach. Wyniki są z nowych sesji; wcześniejszych pomiarów nie przeniesiono.

Suma modułu to suma median jego scenariuszy, z wagą1 każdy. Procent wynika z sum sekund, nie ze średniej procentów. Nie jest to czas pojedynczej sekwencji użytkownika. Moduł otrzymuje sumę dopiero po przyjęciu wszystkich swoich scenariuszy; pełny indeks ma14wspólnych przepływów. Brakujące komórki nie oznaczają zera. Ujemny procent oznacza wydłużenie czasu i pozostaje widoczny.

| Scenariusz / moduł | Przed STEP1 [s] | Po STEP1 [s] | Redukcja1/0 [%] | Po STEP2 [s] | Redukcja2/1 [%] | Redukcja2/0 [%] | Po STEP3 [s] | Redukcja3/2 [%] | Redukcja3/0 [%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| CSV Summary | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Eksport raportów | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Filtry i grupowanie | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Industrial Data | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Edycja bazy | 29.4071 | 0.2422 | 99.18 | 0.2499 | -3.18 | 99.15 | 0.1773 | 29.05 | 99.40 |
| Realtime | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Mapping | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| SUMA wspólnych14 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

### Szczegóły bieżących scenariuszy wspólnych

| Scenariusz / moduł | Przed STEP1 [s] | Po STEP1 [s] | Redukcja1/0 [%] | Po STEP2 [s] | Redukcja2/1 [%] | Redukcja2/0 [%] | Po STEP3 [s] | Redukcja3/2 [%] | Redukcja3/0 [%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ModifyOpen | 20.0644 | 0.2006 | 99.00 | 0.2100 | -4.69 | 98.95 | 0.1529 | 27.19 | 99.24 |
| ModifyApply | 9.3427 | 0.0416 | 99.55 | 0.0399 | 4.09 | 99.57 | 0.0244 | 38.85 | 99.74 |
| ExportOpen | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| FilterOpen | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| GroupingOpen | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| CharacteristicMapping | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| MainPlots1500 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| Extended216 | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| CsvLoad100k | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| CsvAnalytics100k | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| IndustrialOpen | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| IndustrialBridge | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| RealtimeOpen | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |
| PathsCsvSummary100k | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING | PENDING |

Po dziewięć ścisłych porównań katalogu SQLite i typowanych uporządkowanych wierszy na przyjęty scenariusz zakończyło się kodem0. Każdy z24wyników ma1500raportów/216000pomiarów; porównania nie zmieniły plików. Nie użyto wyjątków timestampów. Niezależne audyty potwierdziły dokładne przywrócenie masek/widżetu, zakończone korzenie sesji, brak pozostałej pracy i awaryjnego przywracania. To pojedyncze lokalne sesje; brak deklaracji istotności statystycznej, Windows i łącznego przyspieszenia aplikacji.

### Zachowane surowe próby przyjętych pomiarów

| Scenariusz | Wersja | Próby [s], w kolejności danej wersji | Mediana [s] |
| --- | --- | --- | ---: |
| ModifyOpen | przed STEP1 | 19.4578, 20.5704, 20.0644 | 20.0644 |
| ModifyOpen | po STEP1 | 0.2006, 0.1921, 0.2026 | 0.2006 |
| ModifyOpen | po STEP2 | 0.2022, 0.2100, 0.2450 | 0.2100 |
| ModifyOpen | po STEP3 | 0.1358, 0.1529, 0.1668 | 0.1529 |
| ModifyApply | przed STEP1 | 9.3427, 9.3476, 8.9966 | 9.3427 |
| ModifyApply | po STEP1 | 0.0411, 0.0416, 0.0693 | 0.0416 |
| ModifyApply | po STEP2 | 0.0399, 0.0393, 0.0412 | 0.0399 |
| ModifyApply | po STEP3 | 0.0244, 0.0192, 0.0264 | 0.0244 |

### Wykluczenia i warunek kontynuacji

Review1500 wykluczono po trzech kompletnych próbach: niezmienione zabezpieczenie sklasyfikowało cztery procesy Python po około99%rdzenia jako konkurujące i nieprzypisane do sesji. Ich historyczny właściciel pozostaje UNKNOWN; późniejszy brak PID nie dowodzi pochodzenia. ExportOpen wykluczono po trzech próbach przez kswapd0 na31,18%rdzenia, przed rozpoczęciem B. Żadnego czasu tych serii nie przyjęto ani nie wznowiono. Niezależne audyty obu wykluczeń potwierdziły dokładne przywrócenie ustawień, zakończone korzenie sesji i brak pozostającej rozpoznanej pracy. Nie wykazano regresji produktu.

Zgodnie z [wiążącą poprawką §3](performance-boost-step3-implementation.md) dalsze pomiary oczekują na odpowiednie, stabilne warunki. Po kolejnych niestabilnych oknach nie powtarzano długich serii, nie osłabiano zabezpieczeń i nie rozbudowywano kontrolerów. Przypisanie8CPU nie izoluje współdzielonej pamięci, cache, I/O ani termiki. Zachowano wszystkie niekorzystne wyniki. Źródła/testy/review/CI są zweryfikowane oddzielnie od brakujących końcowych czasów i porównań pełnych wyjść.

## Archiwalne trzy etapy — oddzielny punkt odniesienia

Poniższe czasy pochodzą z pomiarów STEP2 z 2026-10-21. Przed STEP1: `fb72a42e21651c516d912005eec18802504301e2`; po STEP1: `15ddbeb7e34ff7d6b77a349c0167fd6d8e902af0`; historyczne po STEP2: `a176139d740ec25aeac0f9fd3b39f9a3620db40c`. Wymagana baza końcowego porównania STEP3 to `101e5a44`, a nie historyczna wersja po STEP2. Nie zastępujemy jednej drugą.

Redukcja czasu = 100 × (czas wcześniejszy − czas późniejszy) / czas wcześniejszy. Dodatnia wartość oznacza przyspieszenie; ujemna oznacza regresję. Brak wyniku pozostaje PENDING lub N/A, nigdy zero.

| Moduł | Przed STEP1 [s] | Po STEP1 [s] | Redukcja 1/0 [%] | Historyczne po STEP2 [s] | Redukcja 2/1 [%] | Redukcja 2/0 [%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| CSV Summary | 149.7992 | 122.5542 | 18.19 | 104.9535 | 14.36 | 29.94 |
| Eksport raportów | 467.6158 | 163.5545 | 65.02 | 96.5505 | 40.97 | 79.35 |
| Filtry i grupowanie | 2.8265 | 2.6940 | 4.69 | 1.9190 | 28.77 | 32.11 |
| Industrial Data | 11.8406 | 11.3608 | 4.05 | 6.0615 | 46.65 | 48.81 |
| Edycja bazy | 28.2036 | 0.2388 | 99.15 | 0.2231 | 6.57 | 99.21 |
| Realtime | 1.1871 | 0.3812 | 67.89 | 0.4009 | -5.17 | 66.23 |
| Mapping | 169.9696 | 163.2817 | 3.93 | 0.7825 | 99.52 | 99.54 |
| SUMA wspólnych 14 scenariuszy | 831.4424 | 464.0652 | 44.19 | 210.8910 | 54.56 | 74.64 |

Suma obejmuje 14 wspólnych scenariuszy z wagą 1 na scenariusz i sumuje ich mediany. Jest indeksem porównawczym, nie czasem jednej ścieżki użytkownika. Procent sumy wynika z sum sekund, nie ze średniej procentów. Dane o liczności prób: długie Extended i Mapping po 1, CSV Summary paths po 2, pozostałe po 3 dla każdej wersji. Nie łączymy tego zestawu z 18 scenariuszami audytu ani z nowymi scenariuszami T00.

### Szczegóły scenariuszy

| Scenariusz | Przed STEP1 [s] | Po STEP1 [s] | Redukcja 1/0 [%] | Historyczne po STEP2 [s] | Redukcja 2/1 [%] | Redukcja 2/0 [%] | n 0/1/2 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `csv_analytics_100k` | 51.4387 | 52.0166 | -1.12 | 35.3942 | 31.96 | 31.19 | 3/3/3 |
| `csv_load_100k` | 4.9605 | 4.9376 | 0.46 | 4.7093 | 4.62 | 5.06 | 3/3/3 |
| `export_main_plots_1500` | 58.4681 | 28.8264 | 50.70 | 27.6799 | 3.98 | 52.66 | 3/3/3 |
| `export_open` | 0.1232 | 0.1256 | -1.95 | 0.1172 | 6.69 | 4.87 | 3/3/3 |
| `filter_open` | 1.5636 | 1.1935 | 23.67 | 1.2943 | -8.45 | 17.22 | 3/3/3 |
| `grouping_open` | 1.2629 | 1.5005 | -18.81 | 0.6247 | 58.37 | 50.53 | 3/3/3 |
| `industrial_bridge` | 10.2655 | 10.5073 | -2.36 | 5.7345 | 45.42 | 44.14 | 3/3/3 |
| `industrial_open` | 1.5751 | 0.8535 | 45.81 | 0.3270 | 61.69 | 79.24 | 3/3/3 |
| `modify_db_apply` | 8.9525 | 0.0457 | 99.49 | 0.0460 | -0.66 | 99.49 | 3/3/3 |
| `modify_db_open` | 19.2511 | 0.1931 | 99.00 | 0.1771 | 8.29 | 99.08 | 3/3/3 |
| `realtime_open` | 1.1871 | 0.3812 | 67.89 | 0.4009 | -5.17 | 66.23 | 3/3/3 |
| `export_extended_small` | 409.0245 | 134.6025 | 67.09 | 68.7534 | 48.92 | 83.19 | 1/1/1 |
| `char_mapping_open` | 169.9696 | 163.2817 | 3.93 | 0.7825 | 99.52 | 99.54 | 1/1/1 |
| `benchmark_paths_csv_summary_100k_8` | 93.4000 | 65.6000 | 29.76 | 64.8500 | 1.14 | 30.57 | 2/2/2 |

Bez porównywalnego wyniku przed STEP1: `modify_db_records`, `reports_import_1500`, `reports_scan_1500`, `theme_switch_1500`. Te scenariusze pozostają poza sumą 14.

Źródło historyczne: [pomiary STEP2](performance-boost-step2-measurements.json), SHA256 `dd8890ac93312098770059ccd300c9d9c5ad40e6099ee0521a026289a8019a7c`. Zapisana historyczna metoda: te same dane syntetyczne i plik harnessu, oddzielne drzewa, skompilowany bytecode, balanced i rotacja wersji. Sam wyciąg tabeli nie potwierdza ponownie dawnych plików wejściowych, zależności, cache ani pełnych dowodów identyczności. Ta granica musi pozostać widoczna w końcowym raporcie.


## Kampania końcowa 101e5a44 → STEP3

**PENDING.** Wymagane: 18 przepływów audytu oraz scenariusze T00, ten sam harness i dane syntetyczne, balanced, rotacja wersji, n=3 (n=2 ponad 60 s), identyczność każdego wyjścia. Warunki stanowiska i liczność prób należy podać przy wyniku. Nie przenosimy skumulowanych wyników poszczególnych pakietów do końcowych komórek.

### Wcześniejszy przyjęty wynik — inny harness, bez przeniesienia akceptacji

Warianty `fb72a42e` / `15ddbeb7` / `101e5a44` / `1acd37c9`, ten sam harness903afc, dane syntetyczne1500raportów/216000pomiarów, balanced/AC, CPU8 i rotacja12prób (n3/etap). To osobna sesja względem historycznej tabeli powyżej.

| Scenariusz | Przed STEP1 [s] | Po STEP1 [s] | Po STEP2 [s] | Po STEP3 [s] | Redukcja STEP3/STEP2 [%] | Redukcja STEP3/początek [%] |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Modify DB open | 20.6606 | 0.2030 | 0.2137 | 0.1627 | 23.87 | 99.21 |

Dziewięć dosłownych porównań SQLite (katalog i typowane uporządkowane wiersze), wszystkie z kodem0; pełne liczności w każdej z12prób. Niezależny audyt hosta: brak różnic masek, dokładne przywrócenie widżetu, oba procesy nadzoru zakończone, bez awaryjnego przywracania i bez pozostałej pracy. Pierwszy zapis akceptacji błędnie oczekiwał etykiety RETIRED zamiast rzeczywistego EXITED; zachowano ten błąd operatora i potwierdzono znaczenie API w źródle, bez powtórzenia benchmarku. Nie jest to jeszcze suma modułu ani całej aplikacji i nie stanowi deklaracji istotności statystycznej.

Scenariusz Modify DB apply zakończył pierwszą próbę pre1 kodem1: po wykonaniu działania `_retain_outputs` odczytuje opcjonalne `tabular_load_result` z usuniętego natywnego okna ModifyDB. Nie powstał JSON wyniku, więc żadnego czasu nie przyjęto ani nie odtworzono z innych logów. Przywrócenie ustawień potwierdzono niezależnie; źródła nie zmieniły się. PO zatwierdził wąski C04, opisany niżej. Wcześniejszy wynik f03 pozostaje dowodem dla harnessu903afc; akceptacja nie przechodzi na poprawiony harness5e2. Wynik końcowy i suma czterech etapów pozostają PENDING.

### Scenariusze poza wspólną sumą14

Te dziewięć scenariuszy dopełnia kampanię18przepływów audytu+5T00. Brak wcześniejszego porównywalnego pomiaru wyłącza je z sumy14; nie oznacza zerowego czasu. Nie mają przyjętego końcowego wyniku dla aktualnych źródeł C05.

| Scenariusz | Pełne wejście / wymagany wynik | Końcowy pomiar STEP3 |
| --- | --- | --- |
| Review reports | 1500syntetycznych raportów;1500wierszy przeglądu | PENDING; stary f01 dotyczy wcześniejszych źródeł |
| Import reports | 1500raportów/216000pomiarów, pełny SQLite | PENDING; ścisła funkcjonalna zgodność sprawdzona osobno, czasy f02 wykluczone |
| Modify DB records | 216000załadowanych wierszy; niepusty wynik filtrowania | PENDING |
| Theme switch | Pełny zestaw1500raportów, zakończony scenariusz GUI | PENDING; brak trwałego wyjścia oznacza N/A tylko dla porównania plików |
| CSV grouping open | 100000przypisań/216zapisanych grup, niepuste populacje | PENDING |
| CSV grouped analytics | Pełne100000przypisań/216grup, kompletny dashboard | PENDING |
| Export cancel | Praca faktycznie rozpoczęta przed cancel, worker zakończony, brak reszt wyjścia | PENDING; czas request→idle |
| CSV analytics cancel | Praca faktycznie rozpoczęta przed cancel, worker zakończony, brak reszt wyjścia | PENDING; czas request→idle |
| Group Analysis legacy export | Pełny standardowy eksport z dodatnią liczbą metryk, XLSX/HTML/zasoby | PENDING; wcześniejszy timeout bazy bez kompletnego wyniku zachowany, przyczyna UNKNOWN |

## Pakiety i tożsamość wyników

Rejestr źródłowy T00–T24 jest zachowany w handbackach. Poniższe obserwacje pakietów pochodzą z różnych sesji i często porównują skumulowany kandydat z bazą101. Nie są niezależnym wkładem pakietu, nie wolno ich sumować ani przenosić do końcowej kolumny STEP3. T25/fala6 zweryfikowane na `d89886d3`: pełna lokalna suita 8788 PASS +418 subtestów, DELTA1 APPROVE, oba CI SUCCESS z Windows core i Linux packaging; performance PENDING. [Zamknięcie fali6](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6396507244). Fala7 jest zamknięta na `2320013103f61e3adc661d65b398e68c3078438f`: T27 zintegrowany, T26 WITHHELD. Lokalna pełna suita: 8796 PASS, 140 SKIP i 418 subtestów; niezależny pełny review APPROVE; oba wymagane przebiegi CI SUCCESS. [Zamknięcie fali7](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6398179826). Końcowy pomiar i raport T28 pozostają nieukończone.

## Ograniczenia

Wyniki lokalnego Linux, przegląd źródeł, CI Windows core, pakowanie i akceptacja spakowanej aplikacji Windows są odrębnymi dowodami. Testowego EXE i akceptacji kandydata Windows nie uruchomiono. E5/E6/E7 nie przyjęto; obliczenia, wykresy, integralność i trwałość pozostają wymaganiami. Wycofane i NOT_APPLICABLE podzadania należy zachować w ostatecznym rejestrze.

## Rejestr pakietów — przygotowanie końcowego handbacku

| Pakiet | Wynik wydajności | Dowód zgodności i decyzje zakresowe |
| --- | --- | --- |
| T00 | Bez deklaracji przyspieszenia | Harness i komparator XLSX/HTML/zasoby/SQLite, kontrole A/A i negatywne; przypięcie istniejących zależności i poprawka własności formatów skoroszytu. [Handback](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6344792507), [korekta](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6346295299). |
| T01 | Extended81,9629→70,0489s;14,54% redukcji | Literalna zgodność wyjść. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6348992512). |
| T02 | Extended33,61%, HTML32,87% redukcji; wynik skumulowany | Plotstats-first, pełny i delta review, literalne wyjścia. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6351520064). |
| T03 | Extended65,25965→42,64585s;34,65% redukcji skumulowanej | Literalne wyjścia; A01-F02 DROPPED po zmianie PNG, kod wycofany. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6352555339). |
| T04 | Main26,27115→23,097s;12,08% redukcji skumulowanej | Identyczne uporządkowane wyniki SQL i eksporty. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6353837309). |
| T05 | Main26,3015→22,85245s;13,1135% redukcji skumulowanej | Literalne wyjścia po sortowaniu grup. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6354716661). |
| T06 | Anulowanie52,26% redukcji; Main bez wykazanego zysku | Poziom6 zachowany,11 kontroli tożsamości, pełny/delta review. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6350574781). |
| T07 | CSV33,4957→32,4726s;3,0544% redukcji skumulowanej | Trzy ścisłe porównania wyjść. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6358224323). |
| T08 | CSV5,5482%, Paths12,7769% redukcji skumulowanej | Sześć porównań, kontrola natywnych struktur i fallbacków; uwaga review zamknięta. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6369295227). |
| T09 | CSV3,372%, Paths4,451% redukcji skumulowanej | Sześć ścisłych porównań dashboardu i skoroszytu. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6366302389). |
| T10 | Paths60,4443→53,9785s;10,6972% redukcji skumulowanej, bezT09 | Oracle XLSX i pełne wejście zgodne; indywidualny pełny/delta review. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6366490799). |
| T11 | PENDING | Pełny snapshot100k/216grup, wyjścia/testy/review/CI zweryfikowane; nieukończone serie nie są wynikami. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6381260308). |
| T12a | Pula2/4: czas Paths wzrósł6,75%/0,51%, CSV16,59%/11,65% | 16 poleceń i16 ścisłych porównań; wyłącznie pomiar, E6 NOT ADOPTED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6372570215). |
| T13 | CSV4,4397→3,5062s;21,0262% redukcji na własnej rewizji | 20 porównań SQLite/uporządkowanych podsumowań i40 negatywnych kontroli. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6363527163). |
| T14 | PENDING | 14 typowanych uporządkowanych wyników na1500raportów zgodnych; ogólny fallback zachowany, filtr ID odroczony. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383026791). |
| T15 | PENDING | 2664 wyników/4limity próbek zgodne; MATERIALIZED i stary SQL fallback. Stary natywny parser NOT_RUN. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383075102). |
| T16 | PENDING | 50kwierszy/1Mwartości/20pól/128582facety zgodne. Przepisanie trwałych widoków pominięte dla zachowania katalogu; E7 niewdrożone. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383153520). |
| T17 | PENDING | 29wyjść Grouping i pełny stan ModifyDB zgodne; kolizja_label naprawiona; ochrona szkicuSTEP2 zachowana. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383642242). |
| T18 | Bez zysku; DROPPED/NOT_APPLICABLE | Cache parsera wycofany do dokładnej bazy101; odświeżanie rejestru NOT_APPLICABLE bez taniego dokładnego sygnału, fail-closed zachowane. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T19 | PENDING | Cache gotowych wierszy wycofany wC02; indeks wzbogacania i ogólny writer zachowane. Pełne1500raportów/216000wartości: katalog, typowane wiersze i dump zgodne. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T20 | PENDING | Ponowne użycie nagłówków przyjęte; skrót float DROPPED, block_parser identyczny101. Pełne wyjścia zgodne. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T21 | PENDING | Pełne1500raportów/58500nagłówków/216000pomiarów zgodne; pełny/delta review i CI. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T22 | PENDING | Dwa osobne pełne stany100k/216grup literalne, pełny/delta review/CI. F06 niewdrożone, F07 DROPPED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6390458270). |
| T23 | PENDING | Zliczenia i wybór części zgodne; oba pełny/delta review/CI. Mapping impact background DROPPED/DEFERRED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6391685452). |
| T24 | PENDING | 24paryCSV+5profili+pełny1500Mapping zgodne, czteryP2 zamknięte. ModifyDB-background/ensure-skip DROPPED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6393090524). |
| T25 | PENDING | 14pełnych porównań literalnych, kontrola rzeczywistej pracy/anulowania/normalnegoQuit, pełna suita/review/obaCI. StarySIGSEGV pozostajeUNKNOWN. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6396507244). |
| T26 | WITHHELD; bez deklaracji zysku | Kandydat poza integracją. Niezmienione CLI bazy101 przekroczyło limit1020s bez kompletnego wyniku; przyczyna UNKNOWN. Brak pełnej tożsamości A/A i A/B. Wszystkie cztery optymalizacje wstrzymane; źródła i testy w zintegrowanej wersji zachowują dokładną rewizję sprzed T26. [Decyzja i dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6398047834). |
| T27 | PENDING; kod zintegrowany | Pełny stan50kwierszy/39kolumn/20metryk: A/A i A/B literalne. Testy callerów716PASS/5SKIP/+1subtest; pełna suita, pełny review i oba CI zakończone sukcesem. Theme/profile-cache DROPPED, A03-F06 rozliczony tylkoT00. [Handback](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6398048291). |
| T28 | PENDING | Przygotowano23 scenariusze na istniejącej zamrożonej infrastrukturze. FULL1 wykrył P2 w granicy czasu anulowania; poprawka używa request→idle i DELTA1 zakończył się APPROVE. Pierwsza próba f01 nie została dopuszczona z powodu limitu przestrzeni tymczasowej; obliczenia nie wystartowały, a przywrócenie ustawień potwierdzono niezależnie. Po zachowaniu identycznej kopii starych syntetycznych wyników T06 na dysku uruchomiono świeżą próbę. Przyjęto f01:12,5803→9,8615s, redukcja21,6116%, n3/stronę; brak trwałych wyjść oznaczono N/A, przywrócenie ustawień potwierdzono niezależnie. To wynik wcześniejszego drzewa produktu `c649b4ea`; nie przenosi się na nowe źródła C02. Powtórka f01 i pozostałe scenariusze dla końcowej wersji pozostają PENDING. [Review](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6399085105). |

## Wcześniejsza walidacja fali7 — zachowany checkpoint

Produkt w checkpointcie fali7: `2320013103f61e3adc661d65b398e68c3078438f`, drzewo `1500e54fed343d493dc5eb10d5ef5d1db5cf3614`. [CI pull requesta40194557292](https://github.com/hexafe/metroliza/actions/runs/40194557292) oraz [CI uruchomione ręcznie40194573983](https://github.com/hexafe/metroliza/actions/runs/40194573983) zakończyły się SUCCESS. Drzewo scaleniowej rewizji CI PR jest identyczne ze zweryfikowanym drzewem produktu. Oba przebiegi Unit: 8796 PASS, 140 SKIP, 412 subtestów i dziewięć dodatkowych partii UI; pokrycie82,86%, kanoniczne86,56%. Różnica sześciu subtestów względem lokalnego uruchomienia pozostaje niewyjaśniona; wyniki podano oddzielnie.

Windows core smoke potwierdza źródła i testy podstawowe, a Linux packaging smoke potwierdza pakowanie. To nie jest akceptacja spakowanego kandydata Windows. W pakowaniu Linux zależność przechodnia wybrała pandas3.1.0, podczas gdy lokalna i jednostkowa walidacja używała3.0.6; obecne bezpośrednie piny nie są pełnym lockfile zależności. Nie porównano wydajności ani wyjść spakowanego wariantu.

## Korekta C01 — zamknięta

PO zatwierdził [wąski wyjątek](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6399420191) dla siedmiu pól czasu importu. Domyślne porównanie pozostaje ścisłe. Jawny tryb waliduje rozpoznany schemat i właściwy format UTC każdej kolumny; inne dane i sqlite_master są porównywane dosłownie. Pełne zachowane wyjścia: A/A i obie pary A/B zgodne z tym wyjątkiem; dziesięć negatywnych kontroli odrzuconych, oryginalne pliki bez zmian. To nie przyjmuje wykluczonych czasów importu.

Lokalny commit `a14e1720afcdcfc6e86a3b98921e91a442ff4081` zmienia komparator, jego testy i plan; kod produktu ma nadal drzewo src `c649b4ea0cf5b3026e8f1cfa3ae493fc924fae14`. [Niezależny pełny review C01](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6399864772): APPROVE, skonfigurowany gpt-6.1-sol/xhigh, backend NOT_VISIBLE. Pełna lokalna suita: 8956 PASS, 140 SKIP i 418 subtestów. Commit wypchnięty; [CI PR40211001479](https://github.com/hexafe/metroliza/actions/runs/40211001479) i [CI ręczne40211103888](https://github.com/hexafe/metroliza/actions/runs/40211103888) zakończyły się SUCCESS, z potwierdzonymi źródłami. Oba Unit: 8956 PASS, 140 SKIP i 412 subtestów, dziewięć dodatkowych partii UI; pokrycie82,87%, kanoniczne86,56%. Windows core i Linux packaging zakończone sukcesem; nowe testy komparatora nie wchodzą do wyboru Windows core. C01 zamknięto w [handbacku](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6400590285). T28 i cały STEP3 pozostają nieukończone.


## Korekty C02 i C03 — zamknięte na 1acd37c9

[C02](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6400732869) wycofał wyłącznie cache gotowych wierszy zapisu T19 A09a-F01 po wykazaniu kosztu rekurencyjnego klucza. Indeks wzbogacania T19, T21 i celowe fail-closed STEP2 pozostają zachowane. Pełny import1500raportów/216000pomiarów zgodny z bazą101 i C01 przy zatwierdzonych siedmiu polach czasu; zmiana pomiaru daje FAIL. Pierwotne niepowodzenie launchera po przejściowej obserwacji resource_tracker zachowano; historyczna tożsamość PID i przyczyna pozostają UNKNOWN.

Pierwsza pełna suita C02 miała dwie porażki testu geometrii OCR; seed58 odtworzył je również na oryginalnym101. C03 poprawia wyłącznie test: wymaga dokładnego śladu oryginalnego lookupu zamiast stałej liczby callbacków równości oraz zachowuje dosłowną geometrię. Dla seedów0/1/2/58/losowego baza i kandydat przechodzą, mutant dodatkowego lookupu zawodzi. Nie wykazano regresji produktu. Pierwotny seed suity nie został zarejestrowany.

Commity `dd399a926ab82905d59b4aa0c97fde17e09622ee` i `1acd37c93c13f029746e2ccce488affd7ea7ceb1`, drzewo `42949fbd8d8aaccb8ec3c1d22eb157c61dd5c88f`, produkt src `84619c209e248a6e389425e0cb4c1396503ee2ef`. Oba niezależne FULL1 APPROVE, MUST-7 i pełny audyt bezpieczeństwa0. Poprawiona lokalna pełna suita:8960PASS/140SKIP/25ostrzeżeń/418subtestów, rzeczywisty kod0.

[CI PR40222113351](https://github.com/hexafe/metroliza/actions/runs/40222113351) i [CI ręczne40222228479](https://github.com/hexafe/metroliza/actions/runs/40222228479): TERMINAL/SUCCESS, źródła potwierdzone; oba Unit8960PASS/140SKIP/25ostrzeżeń/412subtestów oraz dziewięć dodatkowych partiiUI. Windows core i Linux packaging przeszły; akceptacji spakowanego Windows nie wykonywano. [Handback zamknięcia](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6402091396). Implementer gpt-6.1-sol/high, reviewer gpt-6.1-sol/xhigh; ograniczona porada diagnostyczna C03 gpt-6-astra/high; backendy NOT_VISIBLE. Czasy wykluczonego f02 nie zostały przyjęte.

## C04 — wcześniejsze CI wykryło błąd, korekta zamknięta wraz z C05

PO zatwierdził [wąski wyjątek C04](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6402031022). Wypchnięty commit `ed4420a5781da931eb8207309cefccc4407a1038`, drzewo `8371d897d93faafe8bec4faf203944403dbe0d2d`, poprawia wyłącznie retencję po zakończonym Modify DB apply i testy/plan; produkt src84619c2 nie zmienił się. Wszystkie cztery wersje mają identyczny harness5e2 i świeży bytecode. Kontrole oryginału i mutanta odtwarzają błąd; kandydat przechodzi10kontroli. Po git add126PASS z pełnym smoke, MUST-7 i pełny audyt bezpieczeństwa0. [FULL1 C04](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6402298470): APPROVE, reviewer gpt-6.1-sol/xhigh, backend NOT_VISIBLE; FULL1wykorzystany1/1, DELTA0/1. Lokalna pełna suita8969PASS/140SKIP/25ostrzeżeń/418subtestów, rzeczywisty kod0.

[CI PR40228098820](https://github.com/hexafe/metroliza/actions/runs/40228098820) zakończyło się FAILURE:8968PASS/1FAIL/140SKIP/412subtestów; natywny test odrzuconego zamknięcia wykrył ostrzeżenie QWaitCondition. Oba Windows core smoke przeszły, lecz na tym etapie C04 nie zamknięto wobec niepowodzenia wymaganego CI. [Ręczny przebieg40228188938](https://github.com/hexafe/metroliza/actions/runs/40228188938) zakończył się TERMINAL/SUCCESS: Unit8969PASS, Windows core i Linux packaging przeszły, rzeczywiste źródła potwierdzone. Ten sukces nie usuwa porażki wcześniejszego PR CI. Pełną kwalifikację zamknęła dopiero korekta C05 i jej nowe CI, opisane poniżej; nie powtarzano niezmienionego CI do uzyskania zielonego wyniku.

Świeży f05-c04 zakończył pierwszą próbę pre1 kodem0: błąd retencji nie wrócił. Seria została jednak przerwana po10próbach przez niezmienione zabezpieczenie obciążenia; próbnik wykrył kswapd0 na28,74%rdzenia. W chwili przerwania brakowało kompletnego podsumowania i porównań; żaden czas nie został przyjęty. Później siedem ścisłych porównań zachowanych wyjść SQLite przeszło kodem0; każdy z10wyników ma1500raportów/216000pomiarów, pliki pozostały niezmienione. To wyłącznie dowód funkcjonalny starego C04/src84619c2, bez wznowienia serii i bez akceptacji czasu. Niezależny audyt potwierdził dokładne przywrócenie widżetu/masek i zakończenie procesów, bez pozostałej pracy. Nie ustalono przyczyny presji pamięci ani regresji produktu. f03-c04 nie uruchomiono; zastąpiły go świeże f03-c05 i f05-c05 z aktualnych źródeł, opisane na początku raportu. Wcześniejszego f03 nie przeniesiono na harness5e2.

## C05 — natywne sprawdzanie zakończenia wątku

[Przyjęty zakres diagnostyki](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6402612813) obejmuje wyłącznie ui/detached_threads.py i istniejący test. W kontrolowanym Qt6.6.1 isFinished może już zwracać prawdę podczas natywnego kończenia, gdy wait nadal musi sprawdzić ukończenie. Trzymana sygnalizacja finished deterministycznie odtworzyła ostrzeżenie dla wait(0); próba z już wygasłym precyzyjnym QDeadlineTimer zwracaFalse bez ostrzeżenia, a po faktycznym ukończeniuTrue. To rozróżnienie mechanizmu, nie dowód każdego szczegółu wcześniejszej porażki CI.

Wąska korekta jest zintegrowana i wypchnięta jako `e2f9f273027828d35bc0e70b150f3fc1e4460859`, drzewo `6cc02b7f2ab776f9d8f32641c4e6348d947e4233`, produkt src `9689863e47c04ca6960a48b3daf831d138e28508`. Kontrole po git add772PASS/5SKIP/48subtestów, MUST-7 156PASS/5subtestów i pełny audyt bezpieczeństwa przeszły kodem0; [Świeży FULL1 C05](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6402869254) zakończył się APPROVE bez ustaleń P0–P2/MUST; skonfigurowany reviewer gpt-6.1-sol/xhigh, backend NOT_VISIBLE, źródła związane przed/po. Pełna lokalna suita zakończona rzeczywistym kodem0:8970PASS/140SKIP/25ostrzeżeń/418subtestów,1314,69s, źródła przed/po identyczne i czyste. Asercje braku ostrzeżeń, brak blokowania GUI, natywne domknięcie, pending delivery, odrzucenie zamknięcia i wyścig ponowionego Quit pozostają obowiązkowe. Brak zmian zależności, GC, Rust, komparatora i kontrolerów pomiarów. Implementer gpt-6.1-sol/high; backend NOT_VISIBLE. Nie przypisujemy Opusowi udziału w tej korekcie; nie został wywołany. Review źródeł APPROVE; pełna suita i wymagane CI poprawionej wersji zakończone sukcesem. [CI PR40232527375](https://github.com/hexafe/metroliza/actions/runs/40232527375) i [CI ręczne40232531359](https://github.com/hexafe/metroliza/actions/runs/40232531359): wszystkie7/8wymaganych zadań i wykonane kroki zweryfikowane, rzeczywiste źródła potwierdzone. Oba Unit8970PASS/140SKIP/25ostrzeżeń/412subtestów plus9partiiUI; Windows core24grupy podsumowań każdy i Linux packaging PASS. Bezpośredni nowy test natywny C05 nie jest wybrany w Windows core; spakowany Windows nadal NOT_QUALIFIED. [Zamknięcie C04/C05](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6403417324). C04 i C05 mają każdy FULL1wykorzystany1/1, DELTA0/1; wcześniejsze budżety i porażki zachowane. STEP3 pozostaje nieukończone.

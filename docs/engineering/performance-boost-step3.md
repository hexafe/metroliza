# Performance Boost STEP3 — wyniki pomiarów

Zakończono 23 scenariusze na pełnych syntetycznych wejściach oraz ich kontrole wyjść: **103 ścisłe porównania z kodem 0 i 10 kontroli bez trwałego pliku**. Pełny audyt 18 przepływów: **17.60% krócej**; wszystkie 23 akcje: **12.59% krócej**; wspólne 14: **19.40% krócej** względem bieżącej bazy STEP2. Każda suma ma osobno podany zakres i wagę.

**Jawne odstępstwo wykonawcze dla ostatniej pary:** oba pełne Group Analysis zakończyły się kodem 0, lecz pierwotny operator zakończył się kodem 1 przez późniejszy timeout komparatora. Niezmienione ścisłe porównanie dokończono osobno z kodem 0; manifesty i źródła pozostały równe. Raport przyjmuje opisowe czasy obu kompletnych akcji według [bieżącego kierunku PO i ujawnionej decyzji koordynatora](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6414934954). Nie nazywa błędu operatora PASS i nie wykorzystuje starszych nieukończonych lub wykluczonych akcji. Szczegóły poniżej.

## Cztery etapy według modułów

Czasy dotyczą zadeklarowanej akcji harnessu; setup oraz późniejsze kontrole wyjść pozostają osobnymi etapami. Indeks 14 wspólnych scenariuszy sumuje mediany z wagą 1 na scenariusz. Redukcja sumy wynika z sum sekund, nie ze średniej procentów. To indeks porównawczy, a nie czas pojedynczej operacji użytkownika. Zestawów 14, 18 i 23 scenariuszy nie mieszamy. Ujemny procent oznacza wydłużenie czasu.

¹ Kolumny przed i po STEP1 pochodzą z historycznej sesji 2026-10-21: plik `performance-boost-step2-measurements.json`, SHA-256 `dd8890ac93312098770059ccd300c9d9c5ad40e6099ee0521a026289a8019a7c`. Procenty między tamtą a bieżącą sesją pokazują orientacyjną skalę, bez kontrolowanego dowodu przyczynowego. Bieżące pary 101/STEP3 mają te same pełne wejścia, interpreter i harness danej pary.

| Scenariusz/moduł | Przed STEP1 s¹ | Po STEP1 s¹ | Redukcja 1/0 %¹ | STEP2/101 s | Redukcja 2/1 %¹ | Redukcja 2/0 %¹ | STEP3 s | Redukcja 3/2 % | Redukcja 3/0 %¹ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CSV Summary | 149.7992 | 122.5542 | 18.1877 | 118.5714 | 3.2498 | 20.8464 | 105.5994 | 10.9402 | 29.5060 |
| Eksport raportów | 467.6158 | 163.5545 | 65.0237 | 103.8089 | 36.5295 | 77.8004 | 73.0805 | 29.6009 | 84.3717 |
| Filtry i grupowanie | 2.8265 | 2.6940 | 4.6878 | 2.1980 | 18.4113 | 22.2360 | 1.2687 | 42.2793 | 55.1141 |
| Industrial Data | 11.8406 | 11.3608 | 4.0522 | 9.2830 | 18.2892 | 21.6003 | 8.7070 | 6.2049 | 26.4649 |
| Edycja bazy | 28.2036 | 0.2388 | 99.1533 | 0.2278 | 4.6064 | 99.1923 | 0.1585 | 30.4214 | 99.4380 |
| Realtime | 1.1871 | 0.3812 | 67.8881 | 0.3327 | 12.7230 | 71.9737 | 0.2304 | 30.7484 | 80.5914 |
| Mapping | 169.9696 | 163.2817 | 3.9348 | 0.9462 | 99.4205 | 99.4433 | 0.6608 | 30.1628 | 99.6112 |
| **SUMA 14** | 831.4424 | 464.0652 | 44.1855 | 235.3680 | 49.2813 | 71.6916 | 189.7053 | 19.4006 | 77.1836 |

## Wspólne 14 — szczegóły

| Scenariusz/moduł | Przed STEP1 s¹ | Po STEP1 s¹ | Redukcja 1/0 %¹ | STEP2/101 s | Redukcja 2/1 %¹ | Redukcja 2/0 %¹ | STEP3 s | Redukcja 3/2 % | Redukcja 3/0 %¹ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| csv_analytics_100k | 51.4387 | 52.0166 | -1.1235 | 39.7863 | 23.5123 | 22.6530 | 38.0110 | 4.4621 | 26.1043 |
| csv_load_100k | 4.9605 | 4.9376 | 0.4616 | 6.0439 | -22.4056 | -21.8405 | 4.6501 | 23.0613 | 6.2574 |
| export_main_plots_1500 | 58.4681 | 28.8264 | 50.6972 | 26.7929 | 7.0543 | 54.1752 | 22.8109 | 14.8621 | 60.9857 |
| export_open | 0.1232 | 0.1256 | -1.9481 | 0.0920 | 26.7516 | 25.3247 | 0.0901 | 2.0652 | 26.8669 |
| filter_open | 1.5636 | 1.1935 | 23.6697 | 1.4679 | -22.9912 | 6.1205 | 0.6526 | 55.5419 | 58.2630 |
| grouping_open | 1.2629 | 1.5005 | -18.8138 | 0.7301 | 51.3429 | 42.1886 | 0.6161 | 15.6143 | 51.2155 |
| industrial_bridge | 10.2655 | 10.5073 | -2.3555 | 8.9606 | 14.7202 | 12.7115 | 8.3712 | 6.5777 | 18.4531 |
| industrial_open | 1.5751 | 0.8535 | 45.8130 | 0.3224 | 62.2261 | 79.5315 | 0.3358 | -4.1563 | 78.6807 |
| modify_db_apply | 8.9525 | 0.0457 | 99.4895 | 0.0318 | 30.4158 | 99.6448 | 0.0192 | 39.6226 | 99.7855 |
| modify_db_open | 19.2511 | 0.1931 | 98.9969 | 0.1960 | -1.5018 | 98.9819 | 0.1393 | 28.9286 | 99.2764 |
| realtime_open | 1.1871 | 0.3812 | 67.8881 | 0.3327 | 12.7230 | 71.9737 | 0.2304 | 30.7484 | 80.5914 |
| export_extended_small | 409.0245 | 134.6025 | 67.0918 | 76.9240 | 42.8510 | 81.1933 | 50.1795 | 34.7674 | 87.7319 |
| char_mapping_open | 169.9696 | 163.2817 | 3.9348 | 0.9462 | 99.4205 | 99.4433 | 0.6608 | 30.1628 | 99.6112 |
| benchmark_paths_csv_summary_100k_8 | 93.4000 | 65.6000 | 29.7645 | 72.7412 | -10.8860 | 22.1186 | 62.9383 | 13.4764 | 32.6142 |

## Pełne 18 przepływów audytu — odrębny indeks STEP2/STEP3

Wszystkie 18 pierwotnych przepływów audytu (f01–f18), z ponownym pomiarem poprawionego Records C13, dają **267.6977 → 220.5810 s**, czyli **17.60% redukcji czasu**. To suma median z wagą 1 na scenariusz. Indeks obejmuje dodatkowo Review, Import, Records i Theme, których nie ma w historycznej sumie 14; nie dopisujemy im fikcyjnych wyników przed/po STEP1. Nie porównujemy tej sumy wprost z audytową prognozą 231.6 s z innej sesji. Pięć scenariuszy T00 (f19–f23) przedstawiamy osobno. Pierwotna prognoza audytu wynosiła około 30%; bieżący pełny indeks pokazuje 17.60%. Wynik nie osiąga tej prognozy. Różne warunki i sesje nie pozwalają traktować różnicy względem prognozy jako izolowanego wpływu jednego pakietu.

## Wszystkie 23 akcje — osobna suma bieżącej kampanii

Suma z wagą 1 na każdy z 23 scenariuszy daje **7378.2352 → 6449.3273 s**, czyli opisowo **12.59% krócej**. To suma median zwykłych serii i pojedynczych obserwacji dwóch długich eksportów, a nie czas jednej ścieżki użytkownika. Długie zadania dominują w tej sumie i nie mają zmierzonego rozrzutu. Nie ma dla niej dopasowanego odpowiednika przed/po STEP1; czteroetapowy indeks nadal obejmuje tylko wspólne 14. Tożsamość wszystkich wyjść jest zamknięta; wyjątek wykonawczy ostatniej pary opisano na początku raportu.

## Liczność, źródła i warunki

Przed STEP1: `fb72a42e21651c516d912005eec18802504301e2`; po STEP1: `15ddbeb7e34ff7d6b77a349c0167fd6d8e902af0`. Wymagana bieżąca baza STEP2 to `101e5a445bc76223b88067de3a3bb37deb7dbb4e`. Historyczne `a176139d` nie zastępuje 101 i nie wchodzi do bieżącej kolumny STEP2.

Historyczne Mapping i Extended mają n=1 na wersję, Paths n=2, pozostałe n=3. W świeżych parach Paths ma n=2, pozostałe wspólne scenariusze n=3. Main i Extended mają dodatkową świeżą serię czterech wersji po trzy obserwacje: Main 60.1476 → 27.7576 → 26.7929 → 22.8109 s; Extended 368.9168 → 153.0201 → 76.9240 → 50.1795 s. To osobne sprawdzenie; jego kolumn historycznych nie mieszamy z sumą starszej kohorty.

Trzynaście wspólnych przepływów wykonano na rzeczywistym headzie `93641f82` z harnessem `5e2c762f`. Industrial Bridge powtórzono na `75ea71c5` z `136323eb` po korekcie trwałego cache C11. Review, Import, Theme, CSV Grouping i oba anulowania zmierzono na `75ea71c5`; poprawiony Records i oba duże eksporty na `18d67f59`. C10 zmienia wyłącznie retencję po zakończeniu mierzonej akcji. W całym zakresie 936→18 zmieniły się tylko dwa pliki produktu: Industrial Bridge i Modify DB. Wyniki zachowują rzeczywiste źródła i nie są deklaracją ponownego uruchomienia wszystkich przepływów na jednym końcowym headzie.

[Metoda laptopowa według kierunku PO](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6414934954) zachowuje pełne obliczenia, jakość wykresów i rotację zwykłych serii. Jednocześnie wykonuje się jedno ciężkie zadanie Metrolizy pod blokadą; profil zasilania i dostępne obciążenie są zapisywane. Zwykłe korzystanie z laptopa oraz krótkie skoki obciążenia nie odrzucają kompletnej serii. Nie zmieniamy profilu, przydziału rdzeni, widżetu ani przeglądarki. Dwa wyjątkowo duże zadania mają po jednej pełnej obserwacji na wersję (n=1), bez zmierzonego rozrzutu. Starsze wykluczenia pozostają wykluczeniami; nie przepisujemy ich czasów do nowej kampanii.

Środowisko pomiarowe: Linux, Python 3.11.16, PyQt6 6.6.1, Qt 6.6.1, NumPy 2.4.6, SciPy 1.17.1, pandas 3.0.6. Syntetyczny manifest wejść obejmuje 1555 plików / 536069121 bajtów, SHA-256 `7bdd11563d11393beeb4bd4cd4a8a9c434a52729ff620c64e64cacd1b4fa696a`. Dla każdej pary użyto identycznego pliku harnessu po obu stronach i niezmienionych ustawień bibliotek numerycznych. Bieżący harness UI ma SHA-256 `136323ebe9afb6fa0be574b4a73d4876ca3bc9bb6aacc8d351eefe369428d40d`, komparator `04bf289897e09d422deb641245579379a91ef1f2a15e41267c36d14218824d19`. Starsza kohorta zachowuje własny harness `5e2c762f` i rzeczywisty head.

W 46 zapisanych sondach przed/po wybranych scenariuszach oba odczyty profilu (`power_profile` i `platform_profile`) wynosiły `balanced`, wszystkie sondy zakończyły się kodem 0. To obserwacje punktowe, nie dowód ciągłej ciszy lub izolacji. Sonda po Group Analysis pochodzi z końca osobno dokończonej kontroli wyjść.

## Rozrzut świeżych par i rzeczywiste źródła

| Scenariusz | n / wersję 101 i STEP3 | Zakres 101 s | Zakres STEP3 s | Head STEP3 / harness | Ścisłe porównania (kod 0) |
|---|---:|---|---|---|---:|
| csv_analytics_100k | 3/3 | 38.6801–41.8141 | 36.6646–41.5959 | `93641f82` / `5e2c762f` | 5 |
| csv_load_100k | 3/3 | 5.9781–6.3304 | 4.6084–4.7186 | `93641f82` / `5e2c762f` | 5 |
| export_main_plots_1500 | 3/3 | 25.9295–26.8468 | 22.6156–23.2154 | `93641f82` / `5e2c762f` | 9 |
| export_open | 3/3 | 0.0913–0.0966 | 0.0890–0.0939 | `93641f82` / `5e2c762f` | 5 |
| filter_open | 3/3 | 1.4457–1.4688 | 0.6396–0.7266 | `93641f82` / `5e2c762f` | 5 |
| grouping_open | 3/3 | 0.6614–0.7615 | 0.5645–0.6488 | `93641f82` / `5e2c762f` | 5 |
| industrial_bridge | 3/3 | 8.8465–9.0676 | 8.0431–8.5867 | `75ea71c5` / `136323eb` | 5 |
| industrial_open | 3/3 | 0.2910–0.3362 | 0.3245–0.3829 | `93641f82` / `5e2c762f` | 5 |
| modify_db_apply | 3/3 | 0.0288–0.0363 | 0.0180–0.0222 | `93641f82` / `5e2c762f` | 5 |
| modify_db_open | 3/3 | 0.1918–0.2050 | 0.1343–0.1498 | `93641f82` / `5e2c762f` | 5 |
| realtime_open | 3/3 | 0.3134–0.3638 | 0.2240–0.2322 | `93641f82` / `5e2c762f` | 5 |
| export_extended_small | 3/3 | 73.0232–77.3836 | 44.8960–62.1988 | `93641f82` / `5e2c762f` | 9 |
| char_mapping_open | 3/3 | 0.9451–0.9873 | 0.6476–0.6989 | `93641f82` / `5e2c762f` | 5 |
| benchmark_paths_csv_summary_100k_8 | 2/2 | 70.5087–74.9738 | 62.7690–63.1077 | `93641f82` / `5e2c762f` | 3 |

## Scenariusze dodatkowe poza sumą 14

| Scenariusz | STEP2/101 s | STEP3 s | Redukcja 3/2 % | Zakres czasu STEP3 s | n/wersję |
|---|---:|---:|---:|---|---:|
| Review 1500 | 12.5489 | 10.4173 | 16.99 | 9.5357–10.6921 | 3 |
| Import 1500 | 17.3952 | 18.0493 | -3.76 | 17.7045–18.4533 | 3 |
| Records 216k | 2.2117 | 2.2243 | -0.57 | 2.1975–2.3848 | 3 |
| Theme 1500 | 0.1739 | 0.1848 | -6.27 | 0.1559–0.2253 | 3 |
| CSV Grouping 100k | 17.6255 | 1.0702 | 93.93 | 0.9593–1.0878 | 3 |
| CSV grouped 100k / 216 | 3278.7503 | 2777.4975 | 15.29 | 2777.4975 (jedna obserwacja) | 1 |
| Anulowanie eksportu | 0.5104 | 0.0885 | 82.66 | 0.0820–0.1489 | 3 |
| Anulowanie CSV | 0.0462 | 0.0480 | -3.90 | 0.0334–0.0502 | 3 |
| Group Analysis 1500 / standard | 3813.6051 | 3450.0421 | 9.53² | 3450.0421 (jedna obserwacja) | 1 |

Records przed C13: wszystkie 216000 wierszy i 54000 wyników były poprawne, ale pierwszy filtr blokował GUI przez 2263–2676 ms wobec 81–97 ms bazy. Dwie opcje T17 przeniosły budowę tekstu wyszukiwania na pierwszy filtr GUI. C13 je wycofał i powtórzył pełną serię na `18d67f59`: 2.2117 → 2.2243 s, czyli czas porównywalny, bez deklaracji zysku. Najdłuższe pauzy bazy to 61.1–69.5 ms, STEP3 69.4–82.0 ms; w sześciu próbach nie było pauzy ≥100 ms. Pięć ścisłych porównań plików przeszło. Wcześniejsza regresja pozostaje w dowodach. CSV cancel ma w bazie również próbę 44.536 s obok 0.0435 i 0.0462 s; zachowujemy ją, ponieważ mediana nie opisuje najgorszego przypadku.

Duży CSV: pełne 100000 przypisań i 216 grup, oba statusy OK, dashboard HTML o rozmiarze 32103683 bajtów. Ścisłe porównanie A/B zakończyło się kodem 0, manifesty przed/po są równe. Jedna pełna para daje oszczędność 501.2528 s (8 min 21 s). Pierwsza informacja: 4.8862 → 2.9330 s; najdłuższa pauza GUI: 5.8155 → 5.6372 s. Ten przepływ nadal ma wielosekundowe pauzy. Nie przypisujemy całego zysku samemu T11 ani nie ogłaszamy rozwiązania wszystkich zamrożeń GUI.

² Group Analysis: oba pełne przebiegi mają status OK i po 2664 metryki. Zachowano po 15989 plików / około 1.23 GB, w tym 15984 PNG, HTML, XLSX i SQLite. Opisowy zysk czasu to 363.5630 s (6 min 4 s), n=1 bez rozrzutu. Pierwsza informacja: 1.5592 → 2.1321 s; najdłuższa pauza GUI: 1.7628 → 2.1371 s. Wielosekundowe pauzy pozostają. Kandydat T26 nie jest wdrożony. **Tożsamość wyjść zgodna, kod 0:** pierwotny operator 1 / timeout samego komparatora 3720 s / proces −15 pozostaje zachowany. Niezmieniona kontrola z limitem 14520 s zakończyła się kodem 0 po 5128.4434 s; manifesty przed/po są równe i końcowe źródła zweryfikowane. Nie przedstawiamy błędu operatora jako PASS ani nie odzyskujemy starszej nieukończonej akcji bazy.

## Zgodność wyjść

Wspólne 14: 76 ścisłych porównań z kodem 0. Wszystkie 23 scenariusze: 103 ścisłe porównania z kodem 0 oraz 10 kontroli bez trwałego wyjścia; manifesty przed/po są równe. Liczby obejmują kontrole A/A i porównania 101/STEP3. Pięć wcześniejszych porównań Records przed C13 pozostaje dodatkowym historycznym dowodem regresji. XLSX: te same elementy, kolejność, CRC i bajty, poza nazwanymi datami w `docProps/core.xml`. HTML: wyłącznie dopuszczone daty i dokładny token losowego katalogu generacji; zawartość zasobów pozostaje bajtowa. SQLite: katalog `sqlite_master`, typowane wartości i wszystkie wiersze. C01 dopuszcza siedem nazwanych pól czasu importu. C12 dopuszcza tylko dwa pola runtime `updated_at` cache Industrial przy wymaganym schemacie i zakresie, z kontrolami negatywnymi. `max_updated_at` pozostaje literalny i jest poprawiony w C11. Brak pliku w Review/Theme oznacza N/A dla plików, nie zwolnienie z kontroli wyniku GUI.

## Rejestr pakietów

Historyczne pomiary pakietów pochodzą z różnych sesji i często ze skumulowanych wersji. Nie są niezależnymi wkładami i nie wolno ich sumować. Gdy brak pomiaru izolowanego, poniższy zysk końcowego przepływu oznaczamy jako skumulowany, z rzeczywistym headem podanym w tabelach powyżej.


| Pakiet | Wynik wydajności | Dowód zgodności i decyzje zakresowe |
| --- | --- | --- |
| T00 | Bez deklaracji przyspieszenia | Harness i komparator XLSX/HTML/zasoby/SQLite, kontrole A/A i negatywne; przypięcie istniejących zależności i poprawka własności formatów skoroszytu. [Handback](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6344792507), [korekta](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6346295299). |
| T01 | Extended 81,9629→70,0489 s; 14,54% redukcji | Literalna zgodność wyjść. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6348992512). |
| T02 | Extended 33,61%, HTML 32,87% redukcji; wynik skumulowany | Plotstats-first, pełny i delta review, literalne wyjścia. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6351520064). |
| T03 | Extended 65,25965→42,64585 s; 34,65% redukcji skumulowanej | Literalne wyjścia; A01-F02 DROPPED po zmianie PNG, kod wycofany. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6352555339). |
| T04 | Main 26,27115→23,097 s; 12,08% redukcji skumulowanej | Identyczne uporządkowane wyniki SQL i eksporty. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6353837309). |
| T05 | Main 26,3015→22,85245 s; 13,1135% redukcji skumulowanej | Literalne wyjścia po sortowaniu grup. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6354716661). |
| T06 | Anulowanie 52,26% redukcji; Main bez wykazanego zysku | Poziom 6 zachowany, 11 kontroli tożsamości, pełny/delta review. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6350574781). |
| T07 | CSV 33,4957→32,4726 s; 3,0544% redukcji skumulowanej | Trzy ścisłe porównania wyjść. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6358224323). |
| T08 | CSV 5,5482%, Paths 12,7769% redukcji skumulowanej | Sześć porównań, kontrola natywnych struktur i fallbacków; uwaga review zamknięta. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6369295227). |
| T09 | CSV 3,372%, Paths 4,451% redukcji skumulowanej | Sześć ścisłych porównań dashboardu i skoroszytu. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6366302389). |
| T10 | Paths 60,4443→53,9785 s; 10,6972% redukcji skumulowanej, bez T09 | Oracle XLSX i pełne wejście zgodne; indywidualny pełny/delta review. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6366490799). |
| T11 | Brak oddzielnego pomiaru wkładu; końcowy pełny T28 f20: 3278.7503→2777.4975 s,15.29% skumulowane/n=1; osobny wkład T11 niemierzony | Pełny snapshot 100000 wierszy/216 grup, wyjścia/testy/review/CI zweryfikowane; nieukończone serie nie są wynikami. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6381260308). |
| T12a | Pula 2/4: czas Paths wzrósł 6,75%/0,51%, CSV 16,59%/11,65% | 16 poleceń i 16 ścisłych porównań; wyłącznie pomiar, E6 NOT ADOPTED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6372570215). |
| T13 | CSV 4,4397→3,5062 s; 21,0262% redukcji na własnej rewizji | 20 porównań SQLite/uporządkowanych podsumowań i 40 negatywnych kontroli. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6363527163). |
| T14 | Brak oddzielnego pomiaru wkładu; końcowy Filter Open 1.4679→0.6526 s,55.54% skumulowane | 14 typowanych uporządkowanych wyników na 1500 raportów zgodnych; ogólny fallback zachowany, filtr ID odroczony. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383026791). |
| T15 | Brak oddzielnego pomiaru wkładu; końcowy Characteristic Mapping 0.9462→0.6608 s,30.16% skumulowane | 2664 wyników/4 limity próbek zgodne; MATERIALIZED i stary SQL fallback. Stary natywny parser NOT_RUN. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383075102). |
| T16 | Końcowy Bridge 8.9606→8.3712 s,6.58% skumulowane; C11 zachowuje literalne cache | 50000 wierszy/1000000 wartości/20 pól/128582 wartości facetów zgodnych. Przepisanie trwałych widoków pominięte dla zachowania katalogu; E7 niewdrożone. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383153520). |
| T17 | Końcowy Grouping 0.7301→0.6161 s,15.61%; Records po C13: 2.2117→2.2243 s (−0.57%); dodatkowe blokowanie GUI usunięte | 29 wyjść Grouping i pełny stan ModifyDB zgodne; kolizja_label naprawiona; ochrona szkicu STEP2 zachowana. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6383642242). |
| T18 | Bez zysku; DROPPED/NOT_APPLICABLE | Cache parsera wycofany do dokładnej bazy 101; odświeżanie rejestru NOT_APPLICABLE bez taniego dokładnego sygnału, fail-closed zachowane. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T19 | Końcowy Import 17.3952→18.0493 s,−3.76%; bez potwierdzonego zysku | Cache gotowych wierszy wycofany w C02; indeks wzbogacania i ogólny writer zachowane. Pełne 1500 raportów/216000 wartości: katalog, typowane wiersze i dump zgodne. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T20 | Końcowy Review 12.5489→10.4173 s,16.99% skumulowane; import −3.76% | Ponowne użycie nagłówków przyjęte; skrót float DROPPED, block_parser identyczny 101. Pełne wyjścia zgodne. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T21 | Końcowy Review 16.99% skumulowane; bez oddzielnego przypisania wkładu T21 | Pełne 1500 raportów/58500 nagłówków/216000 pomiarów zgodne; pełny/delta review i CI. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6389503390). |
| T22 | Końcowy CSV Grouping 17.6255→1.0702 s,93.93% skumulowane; pełna analiza f20: 15.29% skumulowane/n=1 | Dwa osobne pełne stany 100000 wierszy/216 grup literalne, pełny/delta review/CI. F06 niewdrożone, F07 DROPPED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6390458270). |
| T23 | Końcowy Mapping 0.9462→0.6608 s,30.16% skumulowane; bez osobnego wkładu T23 | Zliczenia i wybór części zgodne; oba pełny/delta review/CI. Mapping impact background DROPPED/DEFERRED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6391685452). |
| T24 | Końcowy CSV Load 6.0439→4.6501 s,23.06% skumulowane; bez osobnego wkładu T24 | 24 pary CSV+5 profili+pełny 1500 Mapping zgodne, cztery P2 zamknięte. ModifyDB-background/ensure-skip DROPPED. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6393090524). |
| T25 | Końcowe anulowanie eksportu 0.5104→0.0885 s,82.66%; CSV 0.0462→0.0480 s,−3.90%, oba wyniki skumulowane | 14 pełnych porównań literalnych, kontrola rzeczywistej pracy/anulowania/normalnego Quit, pełna suita/review/oba CI. Stary SIGSEGV pozostaje UNKNOWN. [Dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6396507244). |
| T26 | WITHHELD; bez deklaracji zysku | Kandydat poza integracją. Historyczna próba bazy przy limicie 1020 s nie dała kompletnego wyniku; tamten przebieg pozostaje niezakwalifikowany. T28 bada zintegrowany standardowy Group Analysis bez czterech optymalizacji T26. Pełna tożsamość kandydata T26 nie jest potwierdzona. [Decyzja i dowody](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6398047834). |
| T27 | Brak oddzielnego pomiaru wkładu; Realtime 0.3327→0.2304 s,30.75% skumulowane; Industrial Open −4.16%/Theme −6.27% bez potwierdzonego zysku | Pełny stan 50000 wierszy/39 kolumn/20 metryk: A/A i A/B literalne. Testy callerów 716 PASS/5 SKIP/+1 subtest; pełna suita, pełny review i oba CI zakończone sukcesem. Theme/profile-cache DROPPED, A03-F06 rozliczony tylko T00. [Handback](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6398048291). |
| T28 | Wspólne 14: 235.3680→189.7053 s,19.40%; cała kampania 23/23; duży CSV 15.29%/501.25 s krócej, Group Analysis 9.53% / 363.56 s krócej, n=1, tożsamość zgodna po osobnej kontroli | Aktualne wspólne 14 i wszystkie 18 audytu mają pełne dane i literalne wyjścia; duży CSV 100000 wierszy/216 grup A/B 15.29% krócej, zgodność 0; Group Analysis ma pełne wyjścia zgodne, kod 0; pierwotny timeout operatora pozostaje zachowany. Starsze wykluczenia i błędy zachowane w dowodach, nie przenoszone do nowych czasów. C09 został źródłowo/natywnie zakwalifikowany; bieżąca metoda laptopowa nie używa kontrolerów/partycji/widżetu. |


## Walidacja, modele i ograniczenia

Źródła produktu: tree `6c3317fb0a6ee15ff8b01ef3d68ccf01269d2763`; scripts tree `b375df625883c93a011da1a18f2ddba1ae11e74d`. Commit raportu `7a21bb51` zmienił wyłącznie trzy istniejące pliki Markdown. Późniejszy C14 dodaje jedynie obserwację w teście i jej dokumentację, bez zmian aplikacji lub harnessu. Produkt `18d67f59` ma pełną lokalną suitę: **9140 PASS, 140 SKIP, 25 ostrzeżeń i 418 subtestów**, kod 0, 1650.24 s; head i źródła pozostały niezmienione. [PR CI 40351575717](https://github.com/hexafe/metroliza/actions/runs/40351575717) i [ręczne CI 40351594372](https://github.com/hexafe/metroliza/actions/runs/40351594372) zakończyły się SUCCESS: wszystkie nieskipowane zadania/kroki przeszły, w tym Windows core i Linux packaging. PR checkout `752096b3` ma dokładne tree `a73652db`; ręczne Unit/Windows/packaging użyły `18d67f59`. Oba główne Unit: 9140 PASS / 140 SKIP / 412 subtestów oraz dziewięć dodatkowych partii UI. Pokrycie: 82.87%, kanoniczne 86.55%. Historyczna różnica sześciu subtestów local/CI pozostaje niewyjaśniona. Linux packaging: artifact `12667535061`, SHA-256 ZIP `350d1c7223b3d0e6141c9eab2dd56c7d50315525cd8229a24d0595a16ecf9682`. W pakowaniu rozwiązano tranzytywne pandas 3.1.0 wobec lokalnego/Unit 3.0.6: piny bezpośrednich zależności nie są pełnym lockiem i nie dowodzą pełnej zgodności wyjść pakietu. Windows core CI nie zastępuje kwalifikacji spakowanego EXE; wydajności Windows ani Windows EXE nie uruchamiano.

[C14 — wąska diagnostyka CI](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6429960792): CI raportu `7a21bb51` zakończyło się FAILURE przez jedną istniejącą asercję Windows core (PUBLISH_INCOMPLETE zamiast SAVED, pozostałe 817 przypadków i wariant headless przeszły). Odpowiedni kod i testy są identyczne z bazą STEP2. Przyczyna pozostaje UNKNOWN; sam wynik nie dowodzi regresji STEP3 ani problemu konkretnego środowiska. Pozostałe sześć zadań tego CI przeszło, w tym pełne Unit: 9140 PASS / 140 SKIP / 25 ostrzeżeń / 412 subtestów, dodatkowe partie UI, statyczne/security i native-wheel smoke. Checkout `49c32395927e516f5354f6cf86f12de5fa3210a1` ma tree `60c545f0ac3d1baa6f8eab7d25f27c85d358b2ff`, rodziców 101/7a.

C14 podłącza istniejący obserwator do niezmienionej asercji: maksymalnie 16 stałych faktów operacji/statusu/czasu, zamrożonych po close i widocznych także przy PASS. Zachowuje 750 ms, zegar, wynik API, całą ścieżkę preview/export i trwałość. Baseline 8 PASS / 0, focused/callers 88 PASS / 0; kontrolowany zastój nadal daje oczekiwany FAIL / 1 przy tej samej asercji i rzeczywistych 750 ms. [FULL1 SOURCE_APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6429931911), bez P0–P2; implementer `gpt-6.1-sol/high`, reviewer `gpt-6.1-sol/xhigh`, niezależny backend/effort not visible; FULL1=1, DELTA1=1 (budżet wyczerpany). [DELTA1 SOURCE_APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6430187754) obejmuje jedyną korektę importu do istniejącej przestrzeni `tests.*`: pierwotny import bez prefiksu został odrzucony przez niezmieniony strażnik deklaracji zależności. Nie dodano zależności, wyjątków ani zmian audytora. Nieudane pierwsze kontrole integracji są zachowane. Opus5.5/high udzielił porady na ogólnym opisie bez kodu; odpowiedź oznaczyła model `claude-opus-5-5`, niezależny backend/effort niewidoczne. To nie review źródeł. Jedna próba diagnostyczna z obserwatorem i jej fakty są rozliczane w podlinkowanym handbacku; nawet PASS nie wyjaśnia starego błędu. Niczego nie przedstawiamy jako naprawy produktu.

Nieblokująca telemetria tego samego CI zgłosiła również CSV Summary 6.505619 s wobec zapisanej historycznej bazy 4.298208 s (+51.36%). Alert jest zachowany, progi niezmienione. To inny scenariusz i zapisana baza, nie dopasowane A/B 101/STEP3; nie zastępuje wyników T28 ani nie dowodzi ich przyczyny. Pozostałe indeksy/ostrzeżenia CI pozostają w jego artefaktach.

Przypadek T28 miał niezależne [FULL1 REQUEST_CHANGES](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6398911897) oraz [DELTA1 APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6399085105), oba ze skonfigurowanym `gpt-6.1-sol/xhigh`; backend i effort niezależnie not visible. Delta naprawiła granicę pomiaru anulowania: od żądania cancel do bezczynności, z osobnym czasem całej akcji. Budżet T28 FULL1/DELTA1 jest wykorzystany. To review kodu przypadku; nie zastępuje bieżących dowodów wykonania ani nie jest nowym review końcowego raportu. Osobne zatwierdzone korekty zachowują własne raporty i budżety.

C10–C12: skonfigurowany implementer `gpt-6.1-sol/high`, świeży reviewer `gpt-6.1-sol/xhigh`; niezależna tożsamość backendu i effort nie są widoczne. Każdy zużył FULL1 i DELTA1. C11 korzystał z porady `gpt-6-astra/high`. C13: ten sam implementer/reviewer, [FULL1 APPROVE_SOURCE_ONLY](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6419594872), bez P0–P2, DELTA1 niewykorzystane. Porada `gpt-6-astra/high` miała nazwany trigger `MEASURED_GUI_STALL_REGRESSION_MODIFY_RECORDS_216K`; nie była konsultacją Opus ani formalnym review. C13 ma staged MUST-7/full security PASS, 84 testy modelu i 279 callerów +13 subtestów, pełną suitę, świeży pełny 216k A/B i oba CI. Modele i bramki wcześniejszych pakietów pozostają w podlinkowanych handbackach; nie odtwarzamy ich z aktualnych domyślnych ustawień.

T18: odświeżanie rejestru NOT_APPLICABLE bez taniego, dokładnego sygnału zmian; zachowano fail-closed STEP2. T26 WITHHELD, kandydat poza integracją. E5/E6/E7 niewdrożone. Historyczny C07 shutdown SIGSEGV i pierwotny błąd publikatora z C14 pozostają UNKNOWN/UNRESOLVED; przechodzące testy nie dowodzą jego naprawy. Nie zmieniono `app/gc_policy.py` ani launchera Rust. Wyniki nie są deklaracją braku wszystkich możliwych błędów ani kwalifikacji spakowanego Windows.

Pierwszą próbę Group Analysis na 101 przerwał dawny limit 3720 s (TimeoutExpired, proces −15, brak ukończonego JSON/czasu/tożsamości), mimo powstałego skoroszytu i zasobów. PO jawnie dopuścił czas ponad godzinę i polecił dokończenie. [Aktualna metoda](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6414934954) daje obu wersjom 14400 s runtime i 14520 s limitu zewnętrznego. Nowa baza i STEP3 ukończyły pełny standardowy eksport po 2664 metryki w 3813.6051 i 3450.0421 s. Odrębny komparator został następnie zakończony po 3720 s (TimeoutExpired, −15), więc oryginalny operator pozostał FAILED/1. Niezmienione ścisłe porównanie z limitem 14520 s zakończyło się kodem 0 po 5128.4434 s; oba pełne zakończone wyniki i niezmienione manifesty/źródła są zweryfikowane. Koordynator przyjął tę kompletną parę jako opisowy pomiar n=1 z jawnym odstępstwem wykonawczym: osobno zakończona kontrola po błędzie pierwotnego operatora. Nie deklarujemy osobnego dosłownego zatwierdzenia nowego wyjątku przez PO; decyzja wykonawcza stosuje jego aktualne polecenie dokończenia pomiarów skali także ponad godzinę, z zachowaniem ścisłej tożsamości. Ten przebieg nie jest przedstawiany jako bezbłędne zakończenie pierwotnego operatora. Nie zmieniono produktu, harnessu, porównań ani zakresu obliczeń. Poprzednia niedokończona próba pozostaje porażką, nie udanym pomiarem.

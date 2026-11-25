# Ocena rozmiaru bazy raportów · #1203

**Decyzja.** Zachować obecny format surowych pomiarów i indeks `idx_report_measurements_report`. Usunięcie indeksu odzyskało logicznie 651 stron, a w próbie podniosło medianę typowego odczytu uporządkowanych pomiarów o około 29%. Zapisy były podobne w obu wariantach. Zmianę formatu warto rozpatrzyć dopiero po osobnym pomiarze na zróżnicowanych profilach parsera i określeniu zgodności wstecznej.

## Pomiar

Schemat raportów i indeksy z `hexafe/metroliza dev@1b5b23a2f77702764a3c1eb46d7d48133d4774b7`. Linux, Python 3.11.16, SQLite 3.53.1, temp na dysku P15. 1200 syntetycznych raportów PDF w strukturze SQLite, po 180 wierszy pomiarów, łącznie 216 000. Surowe JSON-y naśladują strukturę tokenów, nagłówka i statusu CMM, celowo z dużą liczbą powtórzeń. Włączone klucze obce, `ANALYZE`, 4096 B na stronę, domyślny dziennik DELETE. Wariant B jest kopią bazy z usuniętym jednym indeksem. Próby były wykonywane naprzemiennie A/B i B/A, po sześć powtórzeń. Odczyt obejmuje po 240 zapytań na próbę. Zapis dodaje 3600 wierszy na transakcję. Wszystkie wyniki zapytań zgadzały się między wariantami. `quick_check` zwrócił `ok`, a `foreign_key_check` zwrócił pustą listę.

| Pozycja | Wynik |
|---|---:|
| Wielkość wyjściowej bazy | 80 003 072 B |
| Strony tabeli `report_measurements` | 59 056 128 B |
| Suma długości JSON-ów | 36 778 800 B |
| Strony badanego indeksu | 2 666 496 B |
| Wolne strony przed / po usunięciu indeksu | 0 / 651 |

Suma długości JSON-u to około 46% rozmiaru tej konkretnej bazy. Odsetek zależy od danych i nie oznacza, że usunięcie pola automatycznie zwolni tyle miejsca na dysku. SQLite pozostawił strony po indeksie na liście wolnych stron do ponownego użycia.

| Próba | Z indeksem, mediana i zakres | Bez indeksu, mediana i zakres |
|---|---:|---:|
| Liczba pomiarów raportu | 4,139 ms (4,068–5,336) | 5,074 ms (4,426–6,515) |
| Pomiary raportu w kolejności ID | 40,424 ms (38,751–42,841) | 52,111 ms (46,819–58,946) |
| Pomiar według raportu, nagłówka i osi | 3,562 ms (3,298–4,578) | 3,403 ms (3,216–3,600) |
| Zapis 3600 pomiarów | 64,256 ms (62,643–67,635) | 66,574 ms (63,192–76,526) |

Przy uporządkowanym odczycie po usunięciu prostego indeksu SQLite wybiera indeks złożony i dodaje `USE TEMP B-TREE FOR ORDER BY`. Przy wyszukiwaniu po nagłówku i osi plan korzysta z indeksu złożonego w obu wariantach.

## Znaczenie danych

- Parser CMM zapisuje w JSON oryginalne tokeny, nagłówek i źródło interpretacji statusu. Druga ścieżka zapisu profili zachowuje surowe metadane. [Parser CMM](https://github.com/hexafe/metroliza/blob/1b5b23a2f77702764a3c1eb46d7d48133d4774b7/src/metroliza/parsing/cmm_report_parser.py#L1274) · [Zapis wyników parsera](https://github.com/hexafe/metroliza/blob/1b5b23a2f77702764a3c1eb46d7d48133d4774b7/src/metroliza/parsing/parse_result_v2_persistence.py#L385)
- Repozytorium odczytuje JSON przy edycji pomiaru i aktualizuje go wraz z innymi polami. Kompresja lub normalizacja wymagałaby zgodnego odczytu i zapisu przez starsze wydania, atomowej migracji, weryfikacji kopii i odtwarzania. Deduplikacja ma dodatkowy koszt połączeń i może słabiej pomagać na różnych formatach parsera. [Repozytorium pomiarów](https://github.com/hexafe/metroliza/blob/1b5b23a2f77702764a3c1eb46d7d48133d4774b7/src/metroliza/reports/report_repository.py#L1632)

Pomiar jest syntetyczny i lokalny. Pakowane Windows, WAL i dane zakładowe pozostają poza wynikiem tej próby. Żadna baza użytkownika nie była otwierana ani modyfikowana.

## Próby przepływów · #952

Pięć odrębnych scenariuszy syntetycznych, po trzy wykonania na Linux/PyQt offscreen.
Rewizja kodu `fe1f65e4f467a41381c8386b72cdfb279b661e99`, Python 3.11.16.
RSS obejmuje proces i dzieci. „Przerwa UI” to najdłuższe opóźnienie znacznika
pętli zdarzeń w próbie. Wynik to mediana trzech największych opóźnień
z poszczególnych prób. Wszystkie 15 prób zwróciło oczekiwany wynik.

| Przepływ | Do wyniku, ms | Przerwa UI, ms | Szczyt RSS, MB |
|---|---:|---:|---:|
| Reports, 36 PDF i 5184 pomiary | 837,3 | 45,3 | 138,6 |
| Main report, 48 raportów × 144 wiersze | 7778,1 | 2284,5 | 349,7 |
| CSV Summary, 5000 wierszy | 10609,5 | 86,9 | 340,6 |
| Industrial cache do CSV, 1000 wierszy | 644,9 | 132,9 | 173,5 |
| Otwarcie Realtime na syntetycznej bazie Industrial | 552,3 | 552,3 | 103,4 |

Najdłuższe przerwy Main Reports w trzech próbach wyniosły 2,13–2,32 s.
Ta próba określa punkt startowy dla dalszej optymalizacji i nie przypisuje
przerwy do konkretnego etapu. Współbieżne obciążenie, Windows, progi
akceptacji i rzeczywiste źródła pozostają do zbadania w #952.

# GPT-6 — research modeli i routing Metrolizy

Sprawdzono: **23 września 2026**. Zakres: modele wykonawców, koordynatorów i reviewerów oraz
sposób pracy. Nie konfiguracja AI w aplikacji, nie nowy audyt kodu produktu. Refs #1061.

**Bieżący Codex pozostaje na swoim packetcie.** Ten research nie uruchamia agenta, nie zmienia
modelu konta, nie odświeża limitów i nie kwalifikuje Windows EXE. Nowe zasady dotyczą przyszłych
zadań albo jawnie uzgodnionego przekazania. Dokument polityki i jego wejścia są osobnym Draft PR.

## 1. Ustalenia w skrócie

Potwierdzone modele rodziny6 to Astra, Sol i Luna. Terra jest nadal opisana jako GPT-5.6.
Brak potwierdzenia GPT-6 Terra nie jest prognozą, że taki model nigdy nie powstanie.
Oficjalne materiały umieszczają premierę Astry 3 września, Sol/Luna 22 września 2026.
Sprawdzanie faktycznego selektora klienta pozostaje konieczne. [1][2][3][4][5]

Nasza decyzja: nowy podstawowy wykonawca to **Sol6/medium**, nie zawsze Sol/high albo Ultra.
**Luna6/high** dostaje rzeczywisty, ograniczony kod. **Astra6/high** rozwiązuje nieustalone
krytyczne kontrakty i prowadzi formalną ocenę wydania. Terra5.6 jest wariantem zgodności, nie
obowiązkowym pośrednim szczeblem. To wybór projektowy do kalibracji, nie wynik benchmarku Metrolizy.

TupTup PR175 na `d0db1cc476942cb77e26adb8e759c4edbb8e5e67` ma podobny kierunek. Zgadzam się
z większością propozycji; dodaję ścisły warunek dla wyjątku „settled critical”, kontrolę rzeczywistych
uprawnień reviewera oraz ograniczenia nowych mechanizmów kontekstu. Nie importuję reguł Supabase,
Next.js czy Vercel do aplikacji Python/PyQt/SQLite. [R1][R2]

## 2. Parametry, dostępność i koszty

Poniższa tabela to **standardowe API USD za milion tokenów**, dla wejścia do 272 tys. tokenów.
Nie obejmuje narzędzi, Fast, dopłat regionalnych ani przelicznika limitu abonamentowego.

| Model / potwierdzony ID | Wejście | Odczyt cache | Zapis cache | Wyjście |
| --- | ---: | ---: | ---: | ---: |
| Astra / `gpt-6-astra` | 10,00 | 1,00 | 12,50 | 50,00 |
| Sol / `gpt-6-sol` | 2,00 | 0,20 | 2,50 | 10,00 |
| Luna / `gpt-6-luna` | 0,10 | 0,01 | 0,125 | 0,50 |
| Terra / `gpt-5.6-terra` | 2,00 | 0,20 | 2,50 | 12,00 |

Karty i cennik: [2][3][4][5][6]. Zapis cache Terra wynika z opisanej stawki 1,25× input.
Przy ponad 272 tys. tokenów wejścia stawki całego żądania rosną: input/cache 2×, output 1,5×.
Wszystkie cztery karty podają kontekst 1 050 000 i limit odpowiedzi 128 000 tokenów; klient może
udostępniać inny praktyczny limit. Nie jest to zalecenie wkładania całej historii projektu w prompt.

Rachunkowo, przy identycznym wolumenie rozliczanych tokenów, Sol ma 1/5 stawki Astry, Luna 1/20
stawki Sola. Terra kosztuje tyle co Sol na wejściu i więcej na wyjściu. **Nie oznacza to 5×/20×
niższego kosztu zadania:** modele inaczej wykorzystują reasoning, narzędzia i korekty. Cena całej
pracy obejmuje również review oraz kontekst pomocników. Metroliza nie ma tu pomiaru oszczędności.

Oficjalna tabela poprzednich Sol/Luna zestawia input/output 5.6 Sol 4/20 USD i 5.6 Luna 0,20/1,20
z nowymi 2/10 oraz 0,10/0,50. Nie przenosimy promocyjnych/czasowych cen do trwałej konfiguracji. [7]

Work/Codex i API mają odrębne sposoby rozliczenia. Dokumentacja użycia opisuje współdzielone limity
Work/Codex oraz zależność od kontekstu, wysiłku i trybu. Jej starsze tabele 5.6 nie są tabelą
przeliczeniową dla6. Nie odczytywano konta PO, resetu ani dostępności w jego Herdr; przełączenie
modelu nie jest resetem wspólnego limitu. [8]

## 3. Co rzeczywiście mówią benchmarki

| Test producenta i warunki | Wynik | Ograniczony wniosek |
| --- | --- | --- |
| DeepSWE 1.1, oba nowe modele przy max | Sol 68,8%; Luna 66,6% | Luna zasługuje na ograniczone zadania programistyczne; brak dowodu, że high daje wynik max |
| AutomationBench, różne modele i effort | Sol xhigh 33,2% przy 0,27 USD/zadanie; Astra low 30,3% przy 3,9× koszcie | Największy model nie musi być najlepszym wyborem każdej konfiguracji |
| SEC-Bench Pro | Astra 85,4%; Sol6 66,3%; Luna6 34,2% | Podobieństwo jednego wyniku kodowania nie dowodzi równoważności w trudnym bezpieczeństwie |

Pierwsze dwa wyniki pochodzą z ogłoszenia [7], trzeci z system card [9]. SEC-Bench dotyczy silników
JavaScript, nie bezpieczeństwa naszej SQLite. System card wskazuje również, że Sol6 i Sol5.6 są
porównywalne przy podobnej liczbie tokenów, ale Sol5.6 osiąga wyższe maksimum przy większym
budżecie. Nie ma jednej uczciwej etykiety „zawsze lepszy w każdym zadaniu”.

Są to wyniki OpenAI w konkretnych środowiskach, nie niezależny test Metrolizy, ranking wszystkich
ustawień ani certyfikat poprawności wyników pomiarowych. Nie uruchamiano porównania czterech modeli
na tym repo. Praktyczny routing należy korygować na kolejnych prawdziwych, małych dostawach, a nie
budować osobny wielomodelowy projekt pomiarowy zamiast produktu.

## 4. Model, reasoning, tryb i miniony to osobne wybory

Karty API Astry: `low`, `medium`, `high`, `xhigh`, `max`. Sol/Luna dodają `none`.
To nie znaczy, że każde API, konto i klient oferują identyczny selektor. Karty Sol/Luna kierują
użycie narzędzi do Responses; ograniczenia Chat Completions nie powinny być podstawą nowej
integracji. Ta zmiana polityki nie implementuje takiej integracji. [2][3][4]

Przewodnik klienta zaleca start Sol/medium, Luna/high i Astra/Light (`low`), mimo że karta API Luny
podaje własny domyślny medium. To różne powierzchnie i **zalecenie dla pracy nie jest wartością
odziedziczoną przez dowolny klient**. Astra/high w naszej tabeli wynika z ryzyka krytycznej pracy,
nie z twierdzenia, że producent każe zawsze używać high. [10]

Max przeznacza więcej wysiłku na pojedynczy problem; Ultra w Work łączy głębokie reasoning z
delegacją. Luna w aktualnym przewodniku nie wspiera Ultra. Nie zapisujemy więc `Ultra = xhigh` ani
uniwersalnego API `reasoning.effort=ultra`. Codex potrafi delegować na żądanie także bez Ultra. [10][11]

Model, effort i faktyczne uprawnienia sprawdzamy oddzielnie dla pomocnika. Dokumentacja opisuje
ponowne zastosowanie bieżących override'ów rodzica przy spawnie oraz różne reguły dziedziczenia
model/effort. **Nazwa „read-only reviewer” w promptcie nie dowodzi blokady zapisu.** Stosujemy
sprawdzony no-write kontekst albo kontrolowany snapshot, nie deklarację. [11]

Nasza polityka: standard speed; Max/Ultra/Fast wyłącznie z konkretnym uzasadnieniem. Jeden zadaniowy
reviewer zamiast dodatkowego Astra-audytu po Sol-audycie. Pomocnicy mają zmniejszać niezależną pracę
lub kontekst autora; nie mnożymy tego samego QA. Nie deklarujemy oszczędności, jeżeli wszystkie
sesje faktycznie dziedziczą drogi model i ustawienia rodzica.

## 5. Nowe funkcje przydatne dla naszej pracy

### Zmiana reasoning bez odrzucania prefiksu cache

Responses pozwala rodzinie GPT-6 w standardowym trybie single-agent wstawić `configuration_update`
między odpowiedziami i zachować pierwotne request-level effort. To zmienia wysiłek, nie model.
**Ograniczenia są istotne:** bez sąsiadujących update'ów, bez automatycznej kompakcji/truncation i bez
standalone `/responses/compact`. Po jawnej kompakcji przez `compaction_trigger` potrzebny jest nowy
update. Pole effort w zwróconej odpowiedzi nadal odzwierciedla żądanie, nie efektywny update. [12]

Wniosek projektowy: przyszły klient może oszczędzać kontekst, przełączając wysiłek między rutynowym
krokiem a trudnym rozumowaniem. Musi jednak dowodzić obsługi i rejestrować stan; nie zakładamy, że
sam prompt w Herdr/Codex wykona tę operację. Nie zmieniamy działającej sesji.

### Dłuższa praca bez ciągłego kopiowania historii

Eksperymentalny tryb kontekstu Astry zachowuje notatki i wyszukuje wcześniejsze wiadomości/wyniki
narzędzi tego samego zadania. Jest domyślnie wyłączony i zależny od klienta/logowania; przewodnik
opisuje opt-in przy nowym tasku. Models i config reference nie są całkowicie zgodne co do listy
planów, dlatego dostępności nie obiecujemy. To nie odzyskuje utraconych plików lokalnych. [10][13]

Wniosek: opcjonalnie rozważyć w kolejnym długim tasku po sprawdzeniu klienta i zasad danych.
GitHub nadal przechowuje decyzje, source binding i odtwarzalny handoff. Pojemniejszy kontekst nie
usprawiedliwia dodawania wszystkich starych logów do każdego miniona.

### Narzędzia asynchroniczne i sterowanie trwającą pracą

Przewodnik GPT-6 opisuje async tool calling, mid-turn steering przez WebSocket oraz monitoring
niezgodnych działań. To możliwości API/toolchain, nie automatyczne uprawnienia naszych agentów. [14]
Zastosowanie wymaga własności operacji i narzędzi; równoległe odczyty nie uprawniają do równoległego
nadpisywania bazy czy tej samej gałęzi. Nie wdrażamy teraz nowego frameworka agentowego.

### Mniej instrukcji, lepsza definicja ukończenia

Poradnik Astry ostrzega, że rozbudowane reguły procesu mogą wywołać nadmiar testów, przerwań lub
innych działań. Zaleca ograniczony router i dociąganie specjalistycznego guidance wtedy, gdy
rzeczywiście dotyczy zadania. [15]

Wniosek: skracamy AGENTS i formularze; obowiązkowe invariants zostają w jednym playbooku i
właściwych dokumentach. Określamy wynik, testy i prawdziwe granice eskalacji, zamiast nakazywać
„pełny audyt bezpieczeństwa repo” po każdej zmianie. Nie usuwamy realnych odmów narzędzi ani
wymaganych testów.

## 6. Porównanie z naszymi dotychczasowymi regułami

Punkt odniesienia: Metroliza develop `784e44b25c6e0572eeda38d5daba433f1746d678`, AGENTS oraz trzy
dokumenty routingu/template; decyzja delivery-first #1061. Dotychczasowy formularz kończył się
instrukcją, że nowy head rozpoczyna nowy cykl readiness; bez rozróżnienia mogło to zachęcać do
powtarzania całości zamiast aktualizacji werdyktu. Nie twierdzimy, że zmierzono jego udział w kosztach.

| Dotychczas | Nowa propozycja |
| --- | --- |
| MICRO Luna5.6/Medium | Luna6/high do kodu; low/medium do trywialnego tekstu |
| Obowiązkowy szczebel Terra/High | Sol6/medium; Terra5.6 tylko uzasadniony wariant zgodności |
| Feature zawsze Sol/High | Sol6/medium, high dla złożonych stanów i kontraktów |
| Każdy CRITICAL/MILESTONE Sol/Ultra | Astra6/high dla nierozstrzygniętej krytycznej granicy/formalnej oceny; ścisły wyjątek Sol6/high + Astrareview |
| Jedna nazwa modelu/mode | Osobne klient, ID, effort, delegation, speed, effective permissions |
| Potencjalnie świeży review po każdym SHA | Nowy werdykt exact-head, ale ponowne użycie nadal ważnych dowodów i review delty |
| Ciężkie szablony dla każdej pracy | Krótki packet z właściwą szczegółowością i stałymi invariants w podlinkowanej polityce |
| Pomocnicy według stałego składu | 0/1/2 tylko dla niezależnej pracy; review wliczone do limitu współbieżności |

Pełna tabela i warunki są w [playbooku](codex-model-routing.md). Dokument nie zmienia obecnego
WIN-DLV-1, źródeł produktu, CI, runtime lub konfiguracji modelu. Dowody i wyczerpane stare budżety
nie są resetowane przez nowe nazwy.

## 7. Ocena TupTup d0db1cc

Przeczytane: AGENTS, cały playbook oraz research i stan PR175. Stan przy odczycie: Draft,
unmerged; nie przedstawiam propozycji jako scalonego main. [R1][R2]

**Zgoda:** nowe ID i legacy Terra, punkt startowy Sol/medium i Luna/high, osobny effort/delegacja,
jedna runda scope review + delta, triage major versus minor, brak automatycznego Ultra, brak
utożsamienia API cen z kredytami użytkownika, ochrona istniejących packetów.

**Doprecyzowanie 1 — wyjątek critical.** „Zaakceptowany kontrakt” musi obejmować dane, uprawnienia,
negatywne przypadki, współbieżność i rollback/safe recovery, nie sam opis feature'a. Bez spełnienia
jawnych warunków wybór Astry następuje przed implementacją. Jedno Astrareview zostaje, nie trzecia
kampania kontrolna. Dla Metrolizy szczególnie dotyczy to błędnych wyników, SQLite i własności Qt.

**Doprecyzowanie 2 — uprawnienia reviewera.** Sprawdzić rzeczywisty sandbox i narzędzia po
zastosowaniu dziedziczenia. Deklaracja autora/custom pliku nie jest dowodem read-only. [11]

**Doprecyzowanie 3 — funkcje kontekstu.** Dodać opcjonalne `configuration_update` z ograniczeniami
kompakcji i telemetryki; experimental context tylko po potwierdzeniu klienta przy nowym tasku.
Nie obiecywać automatycznej obsługi w działającym agencie. [12][13]

**Doprecyzowanie 4 — reviewer milestone.** „Risk-matched” warto zamienić w jednoznaczny wybór
przed taskiem: krytyczny werdykt nie może przypadkowo spaść do domyślnego reviewera zwykłej
integracji. Już zaakceptowane niezależne dowody pozostają do ponownego użycia.

Komentarz dla autora TupTup jest jednym zbiorczym review zasad, nie żądaniem audytu produktu ani
READY FOR MERGE wszystkich dziesięciu plików. Nie modyfikujemy jego gałęzi/ustawień/operacji.

## 8. Ograniczenia i wdrożenie

Nie wykonano porównawczego benchmarku Metrolizy, nie odczytano rzeczywistych limitów/model pickerów,
nie zmieniono ustawień klienta i nie uruchomiono workerów. Research oficjalny nie zastępuje
niezależnego przeglądu polityki. Nowy Draft PR zawiera tekst, a nie uruchomioną konfigurację.

Kalibracja następuje na następnych zaakceptowanych zadaniach: użyteczny rezultat, liczba istotnych
korekt, review/full-QA/agent starts oraz widoczny koszt i czas. Nie porównujemy samych liczb testów.
Poważny błąd pozostaje poważny po wyczerpaniu budżetu; kolejne podejście wymaga pytania
rozstrzygającego, nie losowego powtarzania. Przed release stabilizujemy wybrane drobne Issues,
a nie odwlekamy całe testowanie do ostatniego dnia.

## 9. Źródła

Poniższe oficjalne źródła sprawdzono 23.09.2026. Są snapshotem: następny dispatch weryfikuje tylko
fakty mające znaczenie dla jego dostępności/konfiguracji, nie powtarza całego researchu.

[1]: https://developers.openai.com/api/docs/changelog
[2]: https://developers.openai.com/api/docs/models/gpt-6-astra
[3]: https://developers.openai.com/api/docs/models/gpt-6-sol
[4]: https://developers.openai.com/api/docs/models/gpt-6-luna
[5]: https://developers.openai.com/api/docs/models/gpt-5.6-terra
[6]: https://developers.openai.com/api/docs/pricing
[7]: https://openai.com/index/introducing-gpt-6-sol-and-luna/
[8]: https://help.openai.com/en/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex
[9]: https://deploymentsafety.openai.com/gpt-6-astra
[10]: https://learn.chatgpt.com/docs/models
[11]: https://learn.chatgpt.com/docs/agent-configuration/subagents
[12]: https://developers.openai.com/api/docs/guides/reasoning#change-reasoning-mid-conversation
[13]: https://learn.chatgpt.com/docs/config-file/config-reference
[14]: https://developers.openai.com/api/docs/guides/latest-model
[15]: https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra
[R1]: https://github.com/hexafe/TupTup/pull/175
[R2]: https://github.com/hexafe/TupTup/blob/d0db1cc476942cb77e26adb8e759c4edbb8e5e67/docs/engineering/codex-model-routing.md

- [Changelog][1] i karty [Astra][2], [Sol][3], [Luna][4], [Terra5.6][5]: ID i parametry.
- [Cennik][6] i [ogłoszenie Sol/Luna][7]: stawki oraz konfiguracje benchmarków producenta.
- [Użycie Work/Codex][8]: rozliczenie abonamentowe, nie tabela kosztu konkretnego tasku.
- [System card][9]: porównanie bezpieczeństwa i ograniczenia ewaluacji.
- [Models][10], [Subagents][11], [Reasoning][12], [Config reference][13], [GPT-6 guide][14]:
  model/effort/permissions, kontekst i możliwości klienta/API.
- [Poradnik instrukcji Astry][15]: kontekst i nadmierna proceduralizacja.
- [TupTup PR175][R1], [dokładny playbook d0db1cc][R2]: porównana propozycja, nie wdrożony produkt.

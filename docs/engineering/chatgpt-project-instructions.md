# Krótkie instrukcje projektu Metroliza

Wersja 2026-09-23; propozycja lustrzana do ustawień projektu. Zapisanie tego pliku nie zmienia
ustawień ChatGPT/Codexa. Pełna polityka: [playbook](codex-model-routing.md); źródła:
[research GPT-6](model-routing-research-2026-09-23.md). Bieżące sesje nie są przełączane.

Użytkownik jest Product Ownerem, asystent zewnętrznym orkiestratorem. GitHub `hexafe/metroliza`
jest trwałym źródłem prawdy. Zawsze sprawdzaj aktualny Issue, branch, kod i istotne CI. Normalna
baza/target to `develop`; kanoniczny pakiet `src/metroliza`, `modules` tylko kompatybilność.
Zachowuj local-first, poufność pomiarów, atomowość SQLite, offline dashboards, deterministyczny
Python fallback i rzeczywiste działanie pakietu Windows. Bez udawanych testów, merge i telemetryki.

Branche zdalne są tymczasowym WIP, nie archiwum. Docelowo repo ma `master`, `develop`, aktywny
`release/*` tylko gdy potrzebny oraz heady rzeczywiście otwartych prac. Nie twórz brancha dla agenta,
review, testu ani checkpointu. Po merge oznacz source branch jako `DELETE_CANDIDATE`, chyba że nazwany
aktywny PR/integration/release nadal wymaga dokładnie tej referencji. Fizyczne usunięcie wykonuj
wyłącznie z zatwierdzonego przez PO skończonego manifestu exact-ref/full-SHA z recovery checkiem.

Dowieź główny rezultat. Jeden spójny Issue/PR; packet ma MUST, SHOULD i DEFERRED. Critical/major
lub naruszenie MUST poprawiaj od razu w odpowiednim zakresie. Wszystkie błędy deduplikuj w Issues;
mniejsze planuj z właścicielem i terminem przeglądu w paczkach stabilizacji. Nie zamieniaj czerwonego
testu w zielony przez etykietę. Testy celowane i bezpieczeństwo są ciągłe; większa stabilizacja,
przegląd zintegrowanych zmian i odbiór EXE następują przed każdym wydaniem minor/major.

Modele dla NOWYCH zadań: kod MICRO = GPT-6 Luna/high; ograniczona integracja i zwykły feature =
GPT-6 Sol/medium; złożone stany/kontrakty = Sol/high. Nierozstrzygnięta krytyczna granica danych,
współbieżności lub formalne domknięcie wydania = Astra/high. Sol/high dla CRITICAL dopuszczaj
wyłącznie według czterech warunków playbooka, z jednym niezależnym review Astra/high. Terra jest
potwierdzona jako GPT-5.6, nie zakładaj GPT-6 Terra. Ultra, Max i Fast nie są domyślne.

Dobieraj liczbę pomocników do rozłącznej pracy: zacznij bez nich, dodaj jednego lub dwóch tylko
z konkretnym uzasadnieniem; domyślnie najwyżej dwa dodatkowe konteksty równocześnie, wliczając
reviewera. Ustalaj osobno model, reasoning, zakres i faktyczne uprawnienia. Autor nie jest swoim
niezależnym reviewerem. Nie mnoż drogich agentów przez niejawne dziedziczenie.

Jeden przegląd całego zmienianego zakresu, zbiorcza korekta istotnych uwag, potem review delty.
Kolejna runda wymaga konkretnego nowego blokera. Nie powtarzaj audytu repo po każdej poprawce;
nie zlecaj pełnego QA każdemu workerowi. Zachowuj nadal ważne dowody. Pytaj PO tylko o rzeczywisty
zakres/ryzyko/uprawnienia/koszt, nie zwykłe poprawki. Merge wykonuje zewnętrzny orkiestrator po
weryfikacji exact-head i wszystkich właściwych bramek; release i operacje na danych są odrębne.

Aktualizacja modeli nie przerywa bieżącego Codexa, nie resetuje limitów i nie odtwarza zaginionych
plików. Następny nowy task lub jawne przekazanie określa nowy routing. Raportuj działający rezultat,
pozostały blocker i źródło dowodu, nie rozmiar archiwum ani obietnice pracy w tle.

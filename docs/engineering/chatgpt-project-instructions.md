# Krótkie instrukcje projektu Metroliza

Wersja 2026-10-18; wspólna polityka `development-routing` v1.1, mapa ról v1.0.
[Przyjęty kierunek użytkownika](https://github.com/hexafe/metroliza/issues/1061#issuecomment-6251973769)
obowiązuje nowe zadania od razu; trwające i wstrzymane przyjmują go na następnej bezpiecznej granicy
packetu po zapisaniu ciągłości źródła, właścicieli i zużytego/pozostałego budżetu. Sama zmiana polityki
nie przerywa pracy, nie resetuje prób, nie uruchamia wydatków ani nie zmienia obsady. Nazwane bramki
review i odbioru pozostają do jawnego uzgodnienia. Przed merge #1063 autorytetem jest przyjęty
Issue/packet, po merge aktywnym źródłem repo jest [playbook](codex-model-routing.md). Zapisanie tego
pliku nie zmienia ustawień ChatGPT/Codexa/Claude.

Użytkownik jest Product Ownerem. Zewnętrzny orkiestrator odpowiada za packet i niezależną decyzję
merge; koordynować wykonanie może Codex albo Claude. Autor nie scala własnego PR. GitHub
`hexafe/metroliza` jest trwałym źródłem prawdy. Sprawdź aktualny Issue, własny worktree, base/head/tree,
kod i istotne CI. Normalna baza/target to `develop`; kanoniczny pakiet `src/metroliza`, `modules`
tylko kompatybilność. Zachowuj local-first, poufność pomiarów, atomowość SQLite, offline dashboards,
deterministyczny Python fallback i rzeczywiste działanie pakietu Windows.

Role semantyczne, dokładne ID i effort rozstrzyga wersjonowana wspólna mapa, nie historyczny research.
Klient bez lokalnych skills musi otrzymać od koordynatora autorytatywną politykę, mapę i zaakceptowany
packet z wersją, pochodzeniem i hashem; nie zgaduje domyślnych modeli i nie wymaga ścieżek konkretnego
komputera. Tryb BOTH / OPENAI_ONLY / CLAUDE_ONLY / NEITHER / UNKNOWN wynika z właściwych obserwacji
limitu ze źródłem i czasem; dane starsze niż 60 minut lub niewiarygodne to UNKNOWN. Bez płatnych prób
limitu, nowych kont czy API billing. Zapisuj osobno żądany, skonfigurowany i zaobserwowany w odpowiedzi
model/effort; brak dowodu to `not visible`. Zmiana dostawcy nie znosi nazwanej bramki ani budżetu.

Dowieź główny rezultat. Jeden spójny Issue/PR; packet ma MUST, SHOULD i DEFERRED. Critical/major lub
naruszenie MUST poprawiaj lub bezpiecznie powstrzymuj w zakresie uprawnień. Błędy deduplikuj w Issues;
mniejsze planuj z właścicielem i terminem przeglądu w paczkach stabilizacji. Nie zamieniaj FAIL w PASS
przez etykietę. Testy celowane i bezpieczeństwo są ciągłe; stabilizacja, przegląd zintegrowanych zmian
i właściwe rzeczywiste podróże Windows są wymagane przed każdym wydaniem minor/major.

Deleguj użyteczne rozłączne fragmenty z jawną własnością; domyślnie najwyżej dwa dodatkowe konteksty,
wliczając reviewera, bez rekurencyjnego mnożenia agentów. Jeden writer na plik, jeden koordynator,
jeden właściciel Docker/CI, jeden ciężki przebieg walidacji, najwyżej jedno aktywne wywołanie Claude.
Przejęcie wymaga sprawdzenia bezczynności poprzednich writerów/procesów, źródła i przekazania zasobów.

Jeden niezależny przegląd zmienianego zakresu, zbiorcza korekta istotnych uwag, najwyżej jedna delta
na nowym exact-head. Scope review i delta używają świeżych kontekstów bez forkowania; delta dostaje
poprzednie ustalenia i zależności. Sprawdź faktyczne uprawnienia no-write albo użyj kontrolowanego
snapshotu i ujawnij ograniczenia. Kolejna runda wymaga nazwanego blokera i jawnego skończonego
rozszerzenia budżetu w limicie użytkownika. Zachowuj ważne dowody i niekorzystne wyniki. GitHub Codex
Review, niezależny exact-head review, rozwiązane wątki, faktyczne CI oraz właściwe bramki SQLite,
native, Windows i release nadal obowiązują. CRITICAL/milestone wymaga właściwego cross-provider
review albo jawnego wyjątku użytkownika dla kandydata przed integracją. Review źródła, CI, integracja
i odbiór użytkownika to osobne stany. Merge tylko przez uprawnioną zewnętrzną orkiestrację; release,
tag/deploy i operacje na danych mają osobny autorytet.

Branche zdalne są tymczasowym WIP. Nie twórz brancha dla agenta, review, testu ani checkpointu.
Po merge oznacz source jako `DELETE_CANDIDATE`, chyba że nazwany żywy konsument wymaga tej referencji.
Każde usunięcie, także po merge/squash, wymaga pełnej kontroli konsumentów z
[bramki cleanup](../release_checks/branching_strategy.md#cleanup-gate), fetch exact commit/tree
z zachowanego recovery ref w czystym repo oraz zatwierdzonego przez PO skończonego manifestu
exact-ref/full-SHA i expected-old-value lease. Bez udawanych testów, merge, recovery i telemetryki.

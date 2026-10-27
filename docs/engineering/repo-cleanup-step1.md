# Metroliza — porządki repo, krok 1

Historical preparation snapshot. The execution delegation and current state are recorded in [#1153](https://github.com/hexafe/metroliza/issues/1153). Earlier read-only authority and orchestrator handoff stop conditions below are superseded for this one execution. Original report SHA256: a4526f5bb61a4ef5b62da68ceb3b1380d350dbf96915325f10e24ebeb2e9c3f6.

Pakiet lokalny dla zewnętrznego orchestratora, 27.10.2026. **STEP3 odebrany jako zakończona dostawa źródeł, testów i pomiarów z ujawnionymi ograniczeniami.** Nie oznacza to integracji do develop ani kwalifikacji wydania. Następna operacja: **weryfikacja bramek i merge #1109 przez uprawnionego orchestratora**, metodą merge commit.

## Snapshot i granice

Pełny spis jest w [manifeście](repo-cleanup-manifest.json). Lokalny katalog dowodów `repo-cleanup-step1-evidence` obok checkoutu zawiera surowe odpowiedzi API, recenzje, logi, symulację, recovery i sumy kontrolne. To lokalny handoff; nie opublikowano go na GitHub. Dokumenty powstały w osobnym checkoutcie na końcowym STEP3. Symulacja używa osobnego repo i worktree; oryginalne checkouty, ich zmiany i wspólne gałęzie pozostawiono bez ingerencji.

MUST: zachować piny, historię, istniejące review i ich budżety; oddzielić odbiór STEP3, merge, cleanup i release. SHOULD: wykorzystać już istniejące dowody i ograniczyć przyszłą kontrolę do zmiany bazy/konfliktu. DEFERRED: kwalifikacja finalnego EXE, publikacja, wszystkie operacje GitHub oraz fizyczny cleanup. Bieżąca praca to przygotowanie materiału, bez nowego audytu produktu, provider admission lub model review; nowych budżetów review nie zużyto.

Arkusz wejściowy `Metroliza_plan_porzadkow_2026-10-26.xlsx` (SHA256 `ddfbde692eb2904bcdbb1c7bef3987a8d9f71f752f9a10372bf1d85c8303de9f`) odczytano bez modyfikacji: Plan, Gałęzie i PR. Wszystkie47 SHA z jego spisu są zgodne z odświeżonym stanem. Stara macierz do75ea71c5 jest kontekstem; bieżące ancestry policzono bezpośrednio dof69. Kwalifikacja tego nowego lokalnego pakietu nie jest nowym CI produktu. JSON manifestu oznaczałby pełną ścieżkę CI przy późniejszym zgłoszeniu PR; nie deklarujemy dla niego Tier0-only.

Odczytano AGENTS.md, źródła hierarchii, development workflow, branching strategy, codex-model-routing, ci-policy i release_status z końcowego STEP3; #1063 jest nadal nieprzyjętą propozycją aktualizacji instrukcji repo. Obowiązuje obecne polecenie PO zachowania historii, nadrzędne wobec domyślnego squash w starszych instrukcjach.

API: **47 gałęzi, 36 otwartych PR-ów, 142 otwarte issues**. Refy przed i po pobieraniu były identyczne. Wszystkie siedem pinów z promptu zgodne; brak nowej `release/2026.09-rc1`. Migawka czasowa i SHA256 spisu refów są w `snapshot` manifestu. Spis issues służył licznikowi i identyfikacji konsumentów, bez nowego audytu całego backlogu.

| Referencja | Commit | Tree |
|---|---|---|
| develop | `784e44b25c6e0572eeda38d5daba433f1746d678` | `c705f63f8fc51886e229718b264bc67e3f0fb746` |
| 1109 | `82f8f57653964dd344fac7c01a84d9ab303cdaac` | `a590d34d32b2c762f245a2d41dc7c12a20065b23` |
| 1142 | `78d5d775756e4b64530ce8fb04f175a2e3f461f1` | `71d2ce0a8225538ee1725150915f952af99a8b3e` |
| 1149 | `013aafacad42334dbd86b07d7dc2e88822011bdc` | `9e0a7e1b0d4ea0ecfe406f42ef9c8b200f9cf8b6` |
| 1150 | `101e5a445bc76223b88067de3a3bb37deb7dbb4e` | `4c567d8ff9ec0e40684538844920a35688f8a5e1` |
| 1152 | `f69ca5da31be5ef7efd5547457f14744dcb93baa` | `6287643be2e4e797357b01d6cbec855d6b1ca122` |
| 1063 | `508d5b865bd5d9c3c51d2ce121e5e5b3505630d9` | `0149bd8562fb3666ea629a1ec15a65cafdd68ccc` |

## Odbiór STEP3 i mapa dowodów

[Końcowy raport](https://github.com/hexafe/metroliza/blob/f69ca5da31be5ef7efd5547457f14744dcb93baa/docs/engineering/performance-boost-step3.md), [PR #1152](https://github.com/hexafe/metroliza/pull/1152) i [handback C15/#1151](https://github.com/hexafe/metroliza/issues/1151#issuecomment-6430889159) są zgodne co do zakresu, końcowego źródła i ograniczeń. Raport jest historycznym snapshotem sprzed zakończenia ostatniego CI; jego sformułowania o kolejnym CI jako przyszłym kroku uzupełnia późniejszy handback i żywy run, bez przepisywania raportu. T28 zamknięte; #1151 pozostaje otwarte. #1152 pozostaje draft **DO NOT MERGE** na bazie STEP2. Nie usunięto blokady.

| Zakres zmiany | Istniejące review | Commit/tree/blob | Test / CI | Ograniczenie |
|---|---|---|---|---|
| Eksporty, wykresy, SQL, grouping, import i UI: T00–T27, późniejsze C01–C12 | Pełne raporty i delty w komentarzach #1152 oraz handbacki z tabeli raportu. M.in. [SQL batchA delta](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6382979639), [T17 delta](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6383485176), [T22 delta](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6390447508), [C12 delta](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6418592277) | Bazą jest `101e5a44`; komplet `101..f69`: 138 plików, +25848/−712. Końcowe src tree `6c3317fb0a6ee15ff8b01ef3d68ccf01269d2763`, scripts tree `b375df625883c93a011da1a18f2ddba1ae11e74d` | Końcowe CI 40434484770; 103 ścisłe porównania i 10 kontroli bez pliku. Retained root proof SHA256 `130cf153a520976f1a23493c734b416b09994906f447e1ba627426fae9650f05` zweryfikowany | Review pakietów nie jest zgodą na nowy PR integracyjny; wcześniejsze REQUEST_CHANGES i ich rozstrzygnięcia zachowane |
| T28 harness i granica anulowania | [FULL1 REQUEST_CHANGES](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6398911897), [DELTA1 APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6399085105) | Osobne rzeczywiste kohorty poniżej; harness i źródła w każdym wierszu `benchmark_cohorts` manifestu | 23/23 pełne akcje; arytmetyka i liczniki root proof odczytane i sprawdzone, bez ponownego benchmarku | FULL1+DELTA1 wykorzystane; n=1 i historia Group Analysis zachowane |
| C13: wycofanie odroczenia budowy cache wyszukiwania Records | [FULL1 APPROVE_SOURCE_ONLY](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6419594872) | Commit `18d67f596bf4ff832199e026b0d9de3318ff579d`, tree `a73652dba31d0da9be5a0cf4ef51d3459c9be31c`; końcowe hash dwóch plików źródło/test zgodne z review | 84 model +279 callerów/+13 subtestów, pełna suita; oba CI40351575717/40351594372; nowa pełna para216k n3: 2.2117→2.2243 s, 5 porównań, pauzy69–82 ms | Brak ogólnego zysku Records; naprawiona wykazana regresja z pauzami2.6s. FULL1=1, DELTA1=0 |
| C14: wyłącznie obserwacja istniejącej asercji Windows SAVED | [FULL1](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6429931911), [DELTA1 SOURCE_APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6430187754) | Commit `c4c9c9577151fb7b0234fe526e5f01696b48d1a5`; końcowy test SHA256 `bcbc47a10daebbfe49a3165383f18d90d976e95766274b6c19e8bb123cb8edda` zgodny | Focused88 PASS, negatywne sterowane PUBLISH_INCOMPLETE nadal FAIL przy750ms. Windows core40423677624 PASS, końcowy40434484770 PASS | Nie jest naprawą starego Windows PUBLISH_INCOMPLETE. FULL1+DELTA1 wykorzystane |
| C15: diagnostyka GDB i jej pełne wycofanie | [FULL1](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6431071002), [DELTA1 SOURCE_APPROVE](https://github.com/hexafe/metroliza/pull/1152#issuecomment-6431675789) | `cd1c36d2`→`f69ca5da`; cztery końcowe blob SHA256 zgodne z DELTA1; helper nie istnieje. Workflow i ledger bajtowo jak C4, produkt/scripts/packaging jak18 | Staged156+5, workflow/caller198+47, full security/Ruff/mypy PASS w retained receipts; bieżące CI40434484770 SUCCESS | Próba40429936975: FAIL127, brak GDB, Industrial nie ruszył, brak śladu. FULL1+DELTA1 wykorzystane |

Pełne Git blob ID, tree i SHA256 siedmiu końcowych plików są w `final_blob_bindings`; treść review z komentarzy utrwalono lokalnie. Brak formalnych GitHub reviews na #1152 nie oznacza braku niezależnego review. Finalne review C13/C14/C15 mają źródłowe ograniczenia, a późniejsze wykonanie testów jest odrębnym dowodem. Ogólne porady Opus/Astra nie zostały policzone jako review źródeł. Tożsamość backendu/effort niewidoczna w dawnych receipts pozostaje `not visible`.

Ostatnia delta `75ea71c5..f69ca5da` ma sześć plików: `modify_db.py`, jego test, `test_diagnostic_qualification.py` oraz trzy Markdown. C13 obejmuje jedyną zmianę produktu; C14 test; C15 obejmuje wycofanie narzędzia i późniejsze dwa dokumenty. Trzeci dokument audytu i końcowy raport zaktualizował docs-only commit `7a21bb51` z odrębnymi guardami/arytmetyką; nie przedstawiamy go jako nowego niezależnego review raportu. W porównaniu `18..f69` nie zmieniły się src, scripts, packaging, zależności ani workflow. Nie wykryto niepokrytej nowej delty produktu uzasadniającej nową rundę audytu.

### Kohorty pomiarów i ograniczenia

| Indeks | STEP2/101 → STEP3 | Znaczenie |
|---|---|---|
| Wspólne14 | 235.3680→189.7053 s, −19.40% | Suma median, waga1/scenariusz; historyczne cztery etapy831.4424→464.0652→235.3680→189.7053 są kontekstem między sesjami |
| Oryginalny audyt18 | 267.6977→220.5810 s, −17.60% | Odrębny indeks; nie osiąga dawnej prognozyokoło30% |
| Wszystkie23 | 7378.2352→6449.3273 s, −12.59% | Zwykłe n3, Paths n2, dwa duże eksporty n1; brak rozrzutu dla dużych zadań; nie jedna ścieżka użytkownika |

- `93641f82e58c7608ad1e1710e1db352aee1cbae2`: 13 wspólnych scenariuszy, harness `5e2c762f…`.
- `75ea71c5ea6a85ee4a12514f434fdeb98a98c02e`: Bridge po C11, Review, Import, Theme, CSV Grouping i anulowania, harness `136323eb…`.
- `18d67f596bf4ff832199e026b0d9de3318ff579d`: poprawiony Records i oba pełne duże eksporty.

Nie przypisano tych pomiarów do finalnego f69. Odczytano 23 wiersze root proof i sprawdzono sumy103/10 oraz jego digest. Nie wykonano ponownie komparatora wielogigabajtowych wyników ani całej kampanii. Duży CSV3278.7503→2777.4975s (−15.29%) oraz Group Analysis3813.6051→3450.0421s (−9.53%) mają n=1. Oba pełne Group Analysis zakończyły0, po15989 plików, w tym15984PNG. Pierwotny operator zakończył1 po timeout komparatora3720s/−15. Identyczne porównanie dokończono osobno0 w5128.4434s, przy równych manifestach. To ujawniona decyzja wykonawcza koordynatora pod kierunkiem PO, nie bezbłędny pierwotny operator ani odrębna nowa literalna zgoda PO na wyjątek. Starsze nieukończone pary pozostają wykluczone.

T26 WITHHELD poza wdrożeniem. T18 cache wycofany, registry refresh NOT_APPLICABLE; T19 ready-row cache wycofany C02, float shortcut T20 wycofany; E5/E6/E7 niewdrożone. Inne DROPPED/DEFERRED zachowują dyspozycje tabeli raportu. Wielosekundowe pauzy dużych eksportów pozostają. C07, pierwotny C14 PUBLISH_INCOMPLETE oraz osobny C4 Industrial122PASS→139 pozostają **UNKNOWN/UNRESOLVED**. Bieżący PASS nie wyjaśnia i nie naprawia tych incydentów. Różnica418 lokalnych/412CI subtestów pozostaje ujawniona.

### Końcowe CI

[40434484770](https://github.com/hexafe/metroliza/actions/runs/40434484770): **TERMINAL SUCCESS**, 7 wykonanych zadań SUCCESS, 8 opt-in SKIPPED. PR checkout `b05bf87abb3eb7304800a09bba60cccf81415393`, rodzice101/f69, tree dokładnie6287643b. Linux9140PASS/140SKIP/412subtestów, dziewięć dodatkowych partii UI, Industrial122PASS, coverage82.87%/kanoniczne86.55%, próg80% zachowany. Windows core24 grupy PASS. Native wheel/static-security/CMM PASS; trend telemetryczny osobny od T28. Retained logi i completed-job bindings pozostają w pakiecie dowodów.

Linux packaging PASS pochodzi z kwalifikacji18/CI40351594372, a nie bieżącego PR. Bieżący packaging SKIPPED. Piny bezpośrednie nie blokują całego rozwiązania tranzytywnego; historyczny packaging rozwiązał pandas3.1.0 przy Unit/local3.0.6. **Windows EXE/candidate acceptance NOT_RUN**.

## Próba integracji z zachowaniem historii

Każdy poniższy commit jest lokalną symulacją, z dwoma rodzicami; nie jest merge na GitHub. Nie squashowano, nie rebase'owano i nie merge'owano 28 źródłowych PR-ów osobno.

| Etap | Lokalny commit wyniku | Tree wyniku | Ocena |
|---|---|---|---|
| #1109 | `0a192005f4c842448c7d45544173628b02f493e1` | `a590d34d32b2c762f245a2d41dc7c12a20065b23` | Zgodne z oczekiwaną referencją, bez konfliktu |
| #1142 | `cf59172ab9451e1523729bd12fce931c39a099f0` | `71d2ce0a8225538ee1725150915f952af99a8b3e` | Zgodne z oczekiwaną referencją, bez konfliktu |
| #1152 | `3168ec34b5a784df1ce7ca9582f815e16139fc1d` | `6287643be2e4e797357b01d6cbec855d6b1ca122` | Zgodne z oczekiwaną referencją, bez konfliktu |
| #1063 | `279772fb8a88af82fc632e43cf451b01cb77efbc` | `a46b560619007b814177a06b07653f51dcda6997` | Proponowane rozwiązanie jednego konfliktu dokumentacji; wymaga review |

1. #1109→develop: baza784e44b2, head82f8f576. Tree a590d34d zgodne także z rzeczywistym PR checkoutem `520fd207cd1495822b04194079bd7747e0002a61` (log Static checks run39064650589 wiąże rodziców). Brak konfliktu i dodatkowej zmiany.
2. #1142→wynik1: head78d5d775. Tree71d2ce0a zgodne z referencją. Obecny GitHub synthetic merge #1142 ma to samo tree, lecz starą bazę784; to nie kwalifikuje nowej bazy po rzeczywistym #1109.
3. Finalny STEP2+STEP3→wynik2 przez **jeden nowy PR integracyjny**. Tree6287643b identyczne z finalnym STEP3. Ancestry zawiera1109,1142,1149,1150,1152; brak dodatkowej zmiany produktu. #1149 nie jest osobnym merge produkcyjnym.
4. #1063→wynik3: konflikt wyłącznie `docs/project/development_workflow.md`, nagłówek Last reviewed:22.10 (dependency policy) kontra26.09. Lokalna propozycja zachowuje22.10 i obie czysto połączone sekcje. Polityka dokładnych pinów i wszystkie requirements zachowane bajtowo. Git automatycznie zachował sekcję pinów; nie stosowano całoplikowego ours/theirs. Zmiana wynikowa dotyczy13 plików instrukcji, template i dokumentacji, jawnie poza referencją STEP3. Pełna propozycja `resolved1063-index.diff` i oryginalny konflikt są zachowane osobno. Nie są jeszcze zaakceptowane ani przetestowane na GitHub.
5. Nowa `release/2026.09-rc1` dopiero z przyjętego końcowego develop. Przy obecnych niezmienionych źródłach/propozycji #1063 jej lokalny punkt symulacyjny ma treea46b5606. Istnieje wyłącznie lokalny ref `refs/cleanup-step1/proposed-release/2026.09-rc1`; rzeczywista gałąź release i finalny kandydat **NOT_CREATED**. Przyszła aktualizacja metadanych buildu lub ról/linków będzie osobną jawną deltą z nowym tree i bramkami.

### #1149 — dyspozycje odziedziczonych elementów

Samo ancestry nie zatwierdza PoC. Zestawienie wszystkich28 plików z audytowego diffu78→013 jest w `poc1149_dispositions` z blobem audytu i końcowym blobem. „Przyjęty” oznacza element przyjęty w dostawie P01/STEP2, nadal przed zewnętrznym odbiorem całej integracji.

| Element | Dyspozycja w końcowym kodzie | Dowód / pozostałe ograniczenie |
|---|---|---|
| Native splash, GIF/dekoder, logika cache/progress i Python bridge | Przyjęty jako część P01; pierwotna implementacja PoC zastąpiona produkcyjną | `4cfa4d27`, `0cac7fa4`, `f4a99b02`; STEP2 P01/R1+delta. Obecny fallback ProgressWindow, reopen przy75, hold/deadline i stop przy późnym wątku, bounded UTF-16/errors=replace, testy Rust/Python. Końcowy EXE nadal NOT_RUN |
| Zachowanie PoC „splash off/failed=brak okna postępu”, brak ponownego okna po75, nieograniczona obsługa późnego startu | Wycofane / zastąpione | Obecna implementacja P01 posiada jawny fallback i reopen; nie akceptujemy pierwotnych wad jako feature |
| Threaded warmup PoC | Zastąpiony P11/A2 `25f79ef5` | Domyślny worker, bezdaemonowy thread, stop/join, polling GUI; opt-out=0. R4/R4delta i poprawki zachowane, bez resetu budżetów |
| Bootstrap, splash lifecycle | Zastąpiony P01/P14 oraz późniejszym STEP3 | GC policy/bootstrap to dostawa STEP2; nie przypisujemy jej historycznemu PoC ani naprawie wszystkich awarii |
| Startup log marks, stall/exit-after-warmup probe, supervisor timing | Wyłącznie narzędzie audytu (opt-in) | Nie deklarujemy osobnego zysku runtime ani produkcyjnej akceptacji pomiaru |
| `benchmark_ui_flows.py`, timeline script/job, dokumenty/macierze/measurement JSON, registry/index | Wyłącznie narzędzie audytu | Zmienione harnessy zachowują rzeczywiste wersje; historyczne docs nadal mogą opisywać PoC jako niegotowe |

Pełna macierz plikowa:5 przyjętych,12 zastąpionych,11 audytowych. Semantyczne wycofania powyżej są częściami zastąpionych plików, więc nie udajemy usunięcia całego pliku. STEP2 #1150 ma R1–R4/R4delta i rozliczenie poprawek w opisie/reportach; końcowe drobne R4delta fixes nie były ponownie niezależnie reviewowane przy wyczerpanym budżecie. To ujawniony stan do admission, nie zgoda na nowy pełny audyt.

## Bramki i werdykty

Rulesety GitHub aktywnie wymagają dla develop pięciu checków: Static checks, Unit tests, Native wheel build and smoke checks, Windows core smoke, CMM parser perf guardrail (strict/current base). Wymagają PR i rozwiązania wątków; zerowa liczba formalnych approvals jest konfiguracją platformy, a nie uchyleniem wymogu Codex Review i niezależnego review z instrukcji repo. Klasyczny endpoint protection zwraca404 „disabled”, ale dwa aktywne rulesety i efektywne rules/branches/develop potwierdzono;404 nie oznacza braku ochrony.

Przed KAŻDYM rzeczywistym merge: świeży dokładny base/head, właściwy merge commit i wynik integracji, wymagane checki na aktualnej bazie, aktualny Codex Review, niezależne review we właściwym zakresie, zero nierozwiązanych wątków i brak późniejszego blokera. Zmiana bazy/head unieważnia odpowiednią gotowość; równość tree pomaga związać źródła, nie przenosi automatycznie PASS. READY_FOR_INTEGRATION dotyczyłoby jednego snapshotu do decyzji orchestratora, bez zgody na sekwencję.

| Operacja / snapshot | Werdykt | Konkretny brak |
|---|---|---|
| #1109: develop784 / head82f8 / treea590 | **BLOCKED** | Brak dołączonego końcowego niezależnego exact-head/current-base werdyktu orchestratora. PR przypisuje Opus koordynację, nie dowodzi niezależnego odbioru agregatu. Przy admission zatwierdzić poniższą dyspozycję manualnych redów, odświeżyć piny/checki. Nie ma wskazania do ponownego pełnego audytu produktu |
| #1142: head78d5 / tree71d2 | **BLOCKED** | Nie istnieje przyjęta nowa baza po #1109; potrzebne bramki nowej bazy i niezależny werdykt orchestratora. Obecne5 wątków rozwiązane i bieżący Codex summary na78 nie zastępują przyszłego admission |
| Nowy PR STEP2+STEP3: headf69 / tree6287 | **BLOCKED** | Poprzednie merge nie wykonane, PR integracyjny nie istnieje, Codex Review i current-base CI dla niego NOT_RUN, zewnętrzny odbiór integracji i dyspozycji PoC pending. Istniejące pakietowe review wykorzystać, bez powtórki |
| #1063: head508d / lokalna propozycja treea46b | **BLOCKED** | Rozstrzygnięcie konfliktu i nowa baza nieprzyjęte; potrzebne focused review rzeczywistej delty i nowe CI/Codex na odświeżonym headzie. Poprzednie full/delta i named extensions pozostają zużyte |
| Odcięcie release/2026.09-rc1 | **BLOCKED** | Brak przyjętego końcowego develop i pakietu finalnych metadanych/ról RC. Dystrybucja RC dodatkowo wymaga kwalifikacji exact EXE |

### #1109: historyczne czerwone manualne zadania

Wymagane5 checków na bieżącym headzie są SUCCESS w [PR run39064650589](https://github.com/hexafe/metroliza/actions/runs/39064650589), push39064576397 SUCCESS. Codex [6260147256](https://github.com/hexafe/metroliza/pull/1109#issuecomment-6260147256) ukończył review82f8 bez major findings; wcześniejsza odmowa quota jest zachowana i nie jest wynikiem review. Zero wątków unresolved.

[Manual39064576622](https://github.com/hexafe/metroliza/actions/runs/39064576622) pozostaje **FAILURE**. Supervised portable job117489412394 przeszedł. Windows startup benchmark job117493403937 padł podczas budowania starej ścieżki PyInstaller: subprocess importujący `onnxruntime.quantization`, exit3221225477. Linux packaging117493403972: `ModuleNotFoundError: scripts` z `prepare_build_provenance_manifest`. Nie mylić tych dwóch błędów ani ich zakresu z supervised portable PASS.

Dyspozycja na podstawie rzeczywistych rulesetów i ci-policy: te dwa manual/opt-in joby nie są wymaganymi checkami merge #1109. Zachowujemy je jako **niespełnione dowody legacy startup/packaging i ryzyka wydania**; nie zmieniamy whole-run FAIL na PASS. Nie znaleziono w odczytanym PR obowiązującej dodatkowej bramki merge wymagającej obu tych ścieżek. Orchestrator ma potwierdzić tę stosowalność przy admission. Jeśli odnajdzie konkretny zaakceptowany wymóg, pozostaje blokadą danego merge; sam brak nowego EXE nie tworzy takiej blokady. Późniejsze zielone runy #1142 dotyczą późniejszych źródeł i nie dowodzą naprawy starego incydentu. To rozstrzygnięcie nie wymaga ponawiania Linux campaign.

## Manifest cleanup i tabela PR

Manifest rozdziela `branch_action`, `pr_action`, `code_readiness`, rzeczywisty `pr_state` oraz `deletion_eligible_now=false`. Każdy z47 refów ma pełne SHA/tree, metodę ancestry lub unikalny zakres, head/dependent PRs, zarejestrowane worktree, aktywne CI, odwołania issues/PR/docs, warunki usunięcia i recovery. Skan konsumentów obejmuje snapshot lokalnych worktree, otwarte PR/issue bodies, tekstowe docs/.github/scripts oraz queued/in_progress CI; brak trafienia nie dowodzi braku zewnętrznego konsumenta. Końcowe potwierdzenie właścicieli pozostaje bramką.

**38 DELETE_AFTER_INTEGRATION +3 ARCHIVE_THEN_DELETE =41** warunkowych kandydatów. **6 KEEP**: master, develop, rc2, release/2026.06-rc2 i dwie gałęzie Dependabot #972/#973. Plus przyszła release/2026.09-rc1 daje7. Lokalnych bieżących gałęzi roboczych/symulacji nie doliczamy.40 gałęzi i33 heady PR-ów mają ancestry do STEP3; to nie jest dowód zawarcia w obecnym develop.

| PR-y | Dyspozycja | Warunek |
|---|---|---|
| #1109 | MERGE, pierwszy | Exact snapshot i admission opisane wyżej; merge commit |
| #1142 | MERGE, drugi | Aktualna baza po1109, bramki, merge commit |
| Nowy PR integracyjny STEP2+STEP3 | MERGE, trzeci (jeszcze nieutworzony) | Pełna historia, dyspozycje PoC, exact current-base CI/review |
| #1063 | MERGE po odświeżeniu, czwarty | Utrzymać piny22.10, review konfliktu, nowe bramki |
| #1149/#1150/#1152 | CLOSE_AFTER_INTEGRATION | Po przyjęciu jednego agregatu; readback faktycznego stanu GitHub. Nie usuwać obecnych blokad draft |
| 28 źródłowych PR-ów wymienionych poniżej | CLOSE_AFTER_INTEGRATION | Nie merge osobno; jeśli GitHub sam oznaczy merged, zachować ten stan i dowód; w pozostałych zamknięcie z odnośnikiem integracji |
| #972/#973 | DEFER | Osobna aktualizacja zależności po RC; odświeżenie/rozbicie, bez35 upgrade'ów do bieżącego RC |
| #1149 inherited PoC, #1109 admission, finalny RC i dwa historyczne RC | Wymaga decyzji orchestratora/release owner w odpowiednim kroku | Nie tworzy dodatkowego źródłowego merge; exact listy i ograniczenia wyżej |

Źródłowe28: #1050, #1051, #1052, #1056, #1059, #1060, #1062, #1087, #1102, #1103, #1104, #1105, #1107, #1113, #1114, #1116, #1117, #1121, #1122, #1129, #1130, #1131, #1132, #1133, #1135, #1137, #1138, #1139. Pełna tabela wszystkich36 PR-ów z head/base/tree jest w `pr_dispositions` manifestu.

### Trzy wyjątki i recovery

- `build/step2-rc1-261021`: `a0d37690272f6d0b05263076b20cc1b0cfe84780`, jeden commit ponad źródłem `a58b693f`, cztery pliki metadanych. Zachować identyfikację261021 i provenance oddzielnie; nie merge'ować starego numeru do finalnego RC. Run39545859603 posiada m.in. portable artifact12322750592, API digest `sha256:780b63e3848e7db0a67a5e3c6ece567233b8eae8c48e0e972fe63a12b7386435`; launcher12322835269, digest `sha256:8ae6d6c7de4d227d6f8b24878388c5922c7767d4c6e3db2f986045ea8d72d751`. To digest archiwum zgłoszony przez API, nie ponownie sprawdzony hash EXE. Binariów/BUILD_INFO jeszcze nie pobrano do trwałego archiwum — **NOT_RUN**, bramka usunięcia nadal zamknięta.
- `win-dlv-1/engineering`: `git cherry -v f69 <head>` potwierdził **7/7 nie-merge patch-equivalent**; w grafie pozostaje9 unikalnych commitów (7 patchy+2 merge). Nie są ancestors STEP3. Manifest wymienia pełne SHA wszystkich9, wynik patch-equivalence i2 merge. Archiwizować oryginalny head/tree; nie nazywać patch-equivalence ancestry ani pełną tożsamością historii.
- `fix/1106-onnxruntime-offline-namespaces`: dwa unikalne commity `6ad8a344` i `cffb024d`, odrzucona częściowa próba. Archiwizować, **nie merge'ować**. Recovery zachowuje exact oryginalny head/tree.

Utworzono samowystarczalny lokalny `all-remote-heads.bundle` obejmujący47 pełnych refów i ich historię. Zweryfikowano bundle, wykonano fetch do nowego pustego bare repo bez alternates, sprawdzono exact commit i tree dla47/47, oraz `git fsck --full --no-reflogs`: exit0. **PASS_LOCAL_BUNDLE_CLEAN_REPOSITORY** jest rzeczywistym wynikiem tej lokalnej próby.

Trwała kopia poza workspace, recovery ref/tag na zatwierdzonym nośniku/serwerze i recovery fetch z tego docelowego źródła: **NOT_RUN**. Lokalny bundle nie spełnia samodzielnie bramki trwałego recovery. SHA256 bundle, jego rozmiar i47 receipts są w manifeście oraz `recovery.json`. Nie usunięto żadnego refu.

Przyszła kolejność cleanup: przyjęty develop → readback i domknięcie zależnych PR-ów → poprawione aktywne linki/wycofani konsumenci → trwałe archiwum/provenance → próba exact commit/tree z czystego repo z docelowego źródła → świeży skończony manifest zatwierdzony przez PO → kontrola expected-old-SHA → deletion i readback braku refu. Historyczne rc2/release/2026.06-rc2 wymagają osobnego zamknięcia cyklu #901/#924; obecnie KEEP. Nie zamykać issues wyłącznie na podstawie merge.

Przygotowane operacje per ref są tablicami argv w `prepared_delete_operation`, wyłącznie do późniejszej autoryzowanej realizacji, z `--force-with-lease=refs/heads/<name>:<expected-full-sha>` i pustym źródłem `:refs/heads/<name>`. Operacje **NOT_RUN**, nie są wykonywalnym planem obejścia bramek. Przed nimi jeszcze raz odczytać stary ref i odmówić przy jakiejkolwiek rozbieżności; brak refu/drift/protection error to STOP, bez retry force.

## Stan kwalifikacji wydania

**RELEASE BLOCKED; Windows EXE / candidate acceptance NOT_RUN.** To nie unieważnia zakończonego STEP3. EXE kwalifikować na dokładnym finalnym kandydacie po integracji i ustaleniu aktualnego sześciocyfrowego buildu, przed przekazaniem RC do testów lub publikacją. Każda późniejsza zmiana źródeł, pinów, metadanych, packaging lub artefaktu wymaga jawnego ponownego związania odpowiednich dowodów.

Pakiet kwalifikacji ma związać accepted develop SHA/tree, build inputs/toolchain i wszystkie resolved dependencies, `BUILD_INFO`/provenance, SHA256 faktycznego archiwum i EXE, clean-machine/AV, launcher startup/fallback/repair/second instance, worker pools, parser/OCR, SQLite, dashboard i XLSX, pełne candidate acceptance oraz rollback. Linux Unit/Windows core/poprzedni Linux packaging nie zastępują tego dowodu. Nie ma potrzeby ponawiania całej kampanii Linux bez nowej delty lub wykazanego ryzyka.

Pozostałe otwarte kryteria: stosowalne Google/live-service, notices/hashes/legal i release-owner Go (#901/checklist); dyspozycja potencjalnie dotkniętych RC1 danych #1143; Windows timing #1110 i Linux hang #1147; odroczone review #1144 zgodnie z ich rzeczywistą stosowalnością, bez automatycznego uznania wszystkich za blocker merge; osobne incydenty UNKNOWN; aktualizacja release_status/README/branching i aktywnych linków z czerwcowego „current RC” na nową przyjętą rolę. Konkretne rozbieżności: opis #1109 nadal wskazuje referencję15ddbeb7/treebd812a3d, późniejszy komentarz #1142 wskazuje obecne78d5/tree71d2. #1063 jest obecnie GitHub MERGEABLE CLEAN względem starego develop, a lokalna próba na przyszłej bazie wykazuje konflikt nagłówka — te stany dotyczą różnych baz. Aktualne piny tego pakietu oraz późniejsze komentarze mają pierwszeństwo przy admission.

## Walidacja tego pakietu

Lokalnie wykonano:104 testy docs-link/ownership PASS (63.18s), release hygiene PASS, release metadata consistency PASS, staged diff whitespace PASS. Propozycja #1063:5 testów docs-link PASS. Kontrola semantyki manifestu potwierdziła pełne47 refów/SHA/tree, rozłączne dyspozycje, liczniki,23 kohorty/103 porównania/10 kontroli,47 rzeczywistych lokalnych recovery oraz wyłącznie dwa nowe dokumenty w checkoutcie. Szczegółowy receipt `validation.json` w katalogu dowodów. Te kontrole nie są CI integracji ani kwalifikacją EXE. Bieżących benchmarków, suite produktu, nowego CI i niezależnego audytu produktu nie uruchamiano.

Gotowe są materiał odbioru, symulacja oraz manifest. **Następna operacja pozostaje: weryfikacja bramek i merge #1109 przez uprawnionego orchestratora.** Żaden werdykt nie zezwala na automatyczne wykonanie całej sekwencji.

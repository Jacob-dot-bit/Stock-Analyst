import type { Catalogue } from './types'

/**
 * Polish catalogue.
 *
 * Polish has three plural categories: `one` (1), `few` (2–4, but not 12–14) and
 * `many` (0, 5+, and the teens). Entries with a count therefore define all three —
 * `Intl.PluralRules` picks the right one, which a `count === 1` ternary could not.
 */
export const pl: Catalogue = {
  // --- Shell ---------------------------------------------------------------
  'app.title': 'Stock Analyst',
  'nav.portfolio': 'Portfel',
  'nav.transactions': 'Transakcje',
  'nav.watchlist': 'Obserwowane',
  'nav.gems': 'Perełki',
  'nav.taxPrep': 'Przygotowanie podatkowe',
  'nav.risk': 'Ryzyko',
  'nav.journal': 'Dziennik',
  'alerts.tooltip': {
    one: '{count} pozycja z watchlisty osiągnęła cenę docelową',
    few: '{count} pozycje z watchlisty osiągnęły cenę docelową',
    many: '{count} pozycji z watchlisty osiągnęło cenę docelową',
  },
  'language.label': 'Język',
  'app.disclaimer':
    'To narzędzie generuje wskaźniki na podstawie danych publicznych; nie jest to doradztwo inwestycyjne. Decyzje pozostają po Twojej stronie.',

  // --- Common --------------------------------------------------------------
  'common.ok': 'OK',
  'common.cancel': 'Anuluj',
  'common.save': 'Zapisz',
  'common.saving': 'Zapisywanie…',
  'common.add': 'Dodaj',
  'common.delete': 'Usuń',
  'common.edit': 'Edytuj',
  'common.loading': 'Ładowanie…',
  'common.notComputable': 'nie do obliczenia',
  'common.notApplicable': 'nie dotyczy',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portfel',
  'portfolio.subtitle': 'Posiadane pozycje i wynik niezrealizowany.',
  'portfolio.lastImport': 'Ostatni import: {date}.',
  'portfolio.lastRefresh': 'Ceny zaktualizowane {date} o {time}',
  'portfolio.openPositions': 'Pozycje otwarte',
  'portfolio.manageData': 'Zarządzaj danymi',

  'totals.positions': 'Pozycje',
  'totals.marketValue': 'Wartość rynkowa ({currency})',
  'totals.unrealized': 'Wynik niezrealizowany ({currency})',
  'totals.unrealizedTooltip':
    'Różnica między wartością przy ostatniej dostępnej cenie a średnią ceną zakupu. Staje się wynikiem zrealizowanym dopiero po sprzedaży.',
  'totals.realized': 'Wynik zrealizowany ({currency})',
  'totals.performance': 'Stopa zwrotu',
  'totals.performanceTooltip':
    'Wynik niezrealizowany wyrażony jako procent zainwestowanej wartości — nie jest to roczna stopa zwrotu.',
  'totals.incomplete': {
    one: '{count} pozycja nie może być obecnie wyceniona — cena jeszcze nie pobrana, nieznana waluta lub brak kursu wymiany. Jest wyłączona z sum zamiast liczona jako zero, co dałoby błędną sumę wyglądającą na poprawną. Kliknięcie "Odśwież" może to naprawić.',
    few: '{count} pozycje nie mogą być obecnie wycenione — cena jeszcze nie pobrana, nieznana waluta lub brak kursu wymiany. Są wyłączone z sum zamiast liczone jako zero, co dałoby błędną sumę wyglądającą na poprawną. Kliknięcie "Odśwież" może to naprawić.',
    many: '{count} pozycji nie może być obecnie wycenionych — cena jeszcze nie pobrana, nieznana waluta lub brak kursu wymiany. Są wyłączone z sum zamiast liczone jako zero, co dałoby błędną sumę wyglądającą na poprawną. Kliknięcie "Odśwież" może to naprawić.',
  },
  'totals.staleDeclaredValuations':
    'Suma zawiera co najmniej jedną starą zadeklarowaną wycenę (Mintos, Amundi ESR…) — te pozycje są w pełni uwzględnione w sumie, ale ich wartość może już nie odzwierciedlać aktualnego portfela. Szczegóły w sekcji Stan danych.',

  'accounts.title': 'Według rachunku',
  'accounts.account': 'Rachunek',
  'accounts.positions': 'Pozycje',
  'accounts.invested': 'Zainwestowano',
  'accounts.investedTooltip': 'Koszt nabycia zgłoszony przez brokera — nie zmienia się wraz z rynkiem.',
  'accounts.value': 'Wartość',
  'accounts.unrealized': 'Niezrealizowany',
  'accounts.performance': 'Zwrot',

  // --- Performance approximation caveats (DEVLOG "Decision 3u.47") ---------
  'performance.mintosInterestIncome':
    'Zysk netto = odsetki i bonusy otrzymane minus opłaty/podatki, od {since} — rzeczywisty dochód, a nie wzrost ceny jak w przypadku akcji.',
  'performance.amundiApproximateGain':
    'Zysk przybliżony: proporcjonalny udział w zysku konta „{account}", oparty na znanych wpłatach/dopłatach pracodawcy/udziale w zyskach od {since} — lata, których nie zaimportowano, nie są uwzględnione, co może zawyżać ten wynik.',
  'performance.amundiRealGainSinceSnapshot':
    'Rzeczywisty zysk tego funduszu od {since}: obliczony na podstawie ostatniego wyciągu, który ujawnił jego zysk — liczba posiadanych jednostek nie zmieniła się od tego czasu.',

  // --- Aktualność zadeklarowanych wycen (DEVLOG "Decision 3u.50") ----------
  'valuation.declaredFresh':
    'Wartość zadeklarowana przez {provider} na dzień {date} — najnowszy zaimportowany wyciąg, w oczekiwanym oknie aktualności dla tego typu źródła.',
  'valuation.declaredStale':
    'Wartość zadeklarowana przez {provider} na dzień {date} — najnowszy zaimportowany wyciąg, ale starszy niż oczekiwane okno aktualności dla tego typu źródła. Nadal liczy się do sumy; może po prostu nie odzwierciedlać już aktualnego portfela. Zaimportuj nowszy wyciąg, aby ją odświeżyć.',

  // --- Import panel --------------------------------------------------------
  'import.xtb.title': 'Zaimportuj wyciąg XTB',
  'import.xtb.instructions':
    'W xStation: Account history → Export → okres „All”, format Excel. XTB wyłączyło swoje API 14 marca 2025 roku, więc eksport pliku to jedyny pewny sposób pobrania pozycji. Aplikacja nie prosi o żadne dane logowania ani ich nie przechowuje.',
  'import.xtb.multiAccount':
    'Jeden eksport obejmuje tylko jeden rachunek. Jeśli masz ich kilka (na przykład maklerski i PEA), wyeksportuj je osobno i zaimportuj oba pliki: współistnieją, nie nadpisując się wzajemnie.',
  'import.xtb.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.xlsx lub .csv)',
  'import.mintos.title': 'Zaimportuj wyciąg Mintos',
  'import.mintos.instructions':
    'Portfolio → Account Statement, jeden plik PDF na kwartał. Nie istnieje eksport zbiorczy: zaimportuj każdy kwartalny wyciąg osobno (kolejność nie ma znaczenia).',
  'import.mintos.multiAccount':
    'Wyciąg obejmuje dwa odrębne portfele: ETF-y „Core ETF 90” stają się zwykłymi pozycjami, a portfel pożyczek „Mintos Core” staje się jednym zbiorczym składnikiem wycenianym przez Mintos.',
  'import.mintos.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.pdf)',
  'import.mintos-investments.title': 'Zaktualizuj wartość Mintos (eksport Investments)',
  'import.mintos-investments.instructions':
    'Na Mintos: My investments → Export (.xlsx). W przeciwieństwie do kwartalnego wyciągu PDF, ten eksport pokazuje rzeczywistą wartość portfela pożyczek na dzień eksportu — przydatne do odświeżenia kwoty bez czekania na kolejny kwartał.',
  'import.mintos-investments.multiAccount':
    'Nowszy eksport zawsze wygrywa w wyświetlanej wartości, niezależnie czy pochodzi z tego pliku, czy z kwartalnego wyciągu PDF — zawsze pokazywany jest ten nowszy z obu.',
  'import.mintos-investments.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.xlsx)',
  'import.amundi.title': 'Zaimportuj wyciąg Amundi ESR',
  'import.amundi.instructions':
    'Twoje konto na amundi-ee.com → roczny wyciąg (PDF). Każdy wyciąg to zdjęcie stanu na koniec roku, a nie historia transakcji z datami — zaimportuj każdy rok osobno.',
  'import.amundi.multiAccount':
    'Starszy wyciąg zaimportowany po nowszym nigdy nie nadpisuje bieżących pozycji — pozostaje dostępny w historii importów poniżej.',
  'import.amundi.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.pdf)',
  'import.amundi-synthese.title': 'Zaktualizuj wartość Amundi (eksport Synthese)',
  'import.amundi-synthese.instructions':
    'Na koncie amundi-ee.com: eksport „Synthese" (.xlsb). W przeciwieństwie do rocznego wyciągu PDF, ten eksport pokazuje rzeczywistą wartość każdego funduszu na dzień eksportu — przydatne do odświeżenia kwoty bez czekania na kolejny roczny wyciąg.',
  'import.amundi-synthese.multiAccount':
    'Nowszy eksport zawsze wygrywa w wyświetlanej wartości, niezależnie czy pochodzi z tego pliku, czy z rocznego wyciągu PDF — zawsze pokazywany jest ten nowszy z obu.',
  'import.amundi-synthese.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.xlsb)',
  'import.chooseFile': 'Wybierz plik',
  'import.importing': 'Importowanie…',
  'import.failed': 'Import nie powiódł się: {error}',
  'import.summary':
    '{filename} — pozycje otwarte: {positions}, wykryte operacje: {transactions}, w tym nowych: {inserted}.',
  'import.sectionsTitle': 'Arkusze wykryte w pliku',
  'import.sectionLine': '{sheet} → {count} × {kind} (wiersze źródłowe: {rows})',
  'import.previewTitle': 'Podgląd — nic jeszcze nie zostało zapisane.',
  'import.confirm': 'Zatwierdź import',
  'import.cancel': 'Anuluj',
  'import.historyTitle': 'Historia importów',
  'import.historyLine': '{date} — {filename} ({positions} pozycji, {transactions} nowych operacji)',
  'import.undo': 'Cofnij ten import',

  'section.open_positions': 'pozycja otwarta',
  'section.closed_positions': 'pozycja zamknięta',
  'section.cash_operations': 'operacja gotówkowa',
  'section.unknown': 'nierozpoznany blok',

  // --- Backend message codes ----------------------------------------------
  'import.unsupportedFileType':
    'Nieobsługiwany typ pliku „{extension}”. Wyeksportuj z xStation w formacie Excel (.xlsx) lub CSV.',
  'import.fileUnreadable': 'Nie można odczytać pliku: {error}',
  'import.noTableRecognised':
    'Nie rozpoznano żadnej tabeli w tym pliku. Sprawdź, czy to raport wyeksportowany z Account history.',
  'import.nothingImportable': 'Nie znaleziono żadnej użytecznej pozycji ani operacji.',
  'import.unmappedColumns':
    'Nierozpoznane kolumny w „{sheet}”: {columns}. Ich wartości są zapisane, ale nieużywane.',
  'import.positionSkipped':
    'Pominięto pozycję „{symbol}”: nieczytelny wolumen lub cena otwarcia.',
  'import.closedPositionSkipped':
    'Pominięto zamkniętą pozycję „{symbol}”: nieczytelny wolumen lub cena otwarcia.',
  'import.unresolvedSymbols': {
    one: '{count} symbol bez przypisania do dostawcy danych: {symbols}. Popraw go poniżej, aby włączyć analizę.',
    few: '{count} symbole bez przypisania do dostawcy danych: {symbols}. Popraw je poniżej, aby włączyć analizę.',
    many: '{count} symboli bez przypisania do dostawcy danych: {symbols}. Popraw je poniżej, aby włączyć analizę.',
  },

  // --- Symbol mapping ------------------------------------------------------
  'unresolved.title': {
    one: 'Symbol bez przypisania ({count})',
    few: 'Symbole bez przypisania ({count})',
    many: 'Symboli bez przypisania ({count})',
  },
  'unresolved.description':
    'Te instrumenty nie mają automatycznego przypisania do dostawcy danych: dopóki nie zostaną poprawione, nie będą analizowane. CFD na indeksy, surowce i waluty nie mają danych fundamentalnych — to normalne, że pozostają bez przypisania.',
  'unresolved.brokerSymbol': 'Symbol XTB',
  'unresolved.providerSymbol': 'Symbol dostawcy (format Yahoo)',

  'mapping.confirmed': 'potwierdzone',
  'mapping.unverified': 'niezweryfikowane',
  'mapping.toFix': 'do poprawy',
  'mapping.fix': 'popraw',
  'mapping.unverifiedTooltip':
    'Automatyczna konwersja przyrostka giełdy. Rdzeń symbolu nie został sprawdzony u dostawcy danych.',
  'mapping.isinPlaceholder': 'ISIN (np. FR0000120271)',
  'mapping.isinHelp':
    'ISIN odblokowuje europejskie źródło notowań. Znajdziesz go na stronie instrumentu u brokera. Nigdy nie jest zgadywany: błędny ISIN zwróciłby notowania innej spółki.',
  'mapping.placeholder': 'np. ERIC-B.ST',

  'symbol.manualOverride': 'Przypisanie ustawione ręcznie.',
  'symbol.suffixConverted': 'Przyrostek .{suffix} zamieniony na „{providerSuffix}”.',
  'symbol.derivative':
    'Instrument pochodny ({category}): brak danych fundamentalnych, analiza nie ma zastosowania.',
  'symbol.unknownFormat':
    'Symbol poza oczekiwanym formatem „RDZEŃ.KRAJ” albo nieznana giełda. Wpisz symbol dostawcy ręcznie, jeśli instrument jest przez niego obsługiwany.',
  'symbol.notAnEquity':
    'Nierozpoznane jako akcja (indeks, surowiec, waluta lub kryptowaluta). Analiza fundamentalna nie ma zastosowania.',

  // --- Manual position -----------------------------------------------------
  'manual.title': 'Pozycja wpisana ręcznie',
  'manual.subtitle': 'Dla instrumentu spoza eksportu albo trzymanego u innego brokera.',
  'manual.newTitle': 'Nowa pozycja',
  'manual.symbol': 'Symbol XTB',
  'manual.quantity': 'Liczba',
  'manual.avgPrice': 'Cena nabycia',
  'manual.currency': 'Waluta',
  'manual.note':
    'Pozycja wpisana ręcznie nie ma wyceny od brokera: nie będzie liczona do sum, dopóki nie podłączymy cen rynkowych.',

  // --- Positions table -----------------------------------------------------
  'table.instrument': 'Instrument',
  'table.type': 'Typ',
  'table.mapping': 'Przypisanie',
  'table.quantity': 'Ilość',
  'table.avgPrice': 'Cena nabycia',
  'table.avgPriceTooltip': 'Średnia kwota zapłacona za akcję dla zarejestrowanych lotów.',
  'table.avgPriceNotApplicableTooltip':
    'Wartość zadeklarowana przez Mintos na dzień {date} — rzeczywisty zainwestowany koszt (wpłaty i automatycznie reinwestowany kapitał wymieszane razem) nie da się wyodrębnić z zaimportowanych wyciągów, więc dla tego agregatu nie liczymy ani kosztu nabycia, ani zysku/straty.',
  'table.price': 'Kurs',
  'table.value': 'Wartość ({currency})',
  'table.valueNotComputableTooltip':
    'Ta pozycja nie jest uwzględniona w sumach, dopóki nie jest dostępna użyteczna cena.',
  'table.deleteConfirm': 'Trwale usunąć pozycję {symbol}? Tej czynności nie można cofnąć.',
  'table.weight': 'Udział',
  'table.weightTooltip':
    'Udział tej pozycji w aktualnie obliczalnej wartości portfela — pozycje niewycenialne są wyłączone z obliczeń. Powyżej 15% wyróżniony jako ryzyko koncentracji.',

  // --- Znacznik statusu ceny ---
  'priceStatus.fresh': 'Dane cenowe są aktualne.',
  'priceStatus.stale':
    'Dane cenowe nie były sprawdzane od jakiegoś czasu — wyświetlona wartość może nie odzwierciedlać aktualnego rynku. Odśwież, aby zaktualizować.',
  'priceStatus.error': 'Żaden dostawca nigdy nie zwrócił danych dla tego symbolu.',
  'priceStatus.not_priceable': 'Ten instrument z natury nie ma ceny rynkowej — dokładny powód znajdziesz w szczegółach pozycji.',
  'priceStatus.unmapped': 'Brak mapowania dostawcy danych — popraw je poniżej, aby włączyć śledzenie cen.',
  'priceStatus.viaProvider': 'Zweryfikowano przez {provider} dnia {date}.',

  // --- Podział portfela ---
  'breakdown.title': 'Podział portfela',
  'breakdown.dimension.category': 'Klasa aktywów',
  'breakdown.dimension.currency': 'Waluta',
  'breakdown.dimension.country': 'Kraj',
  'breakdown.dimension.sector': 'Sektor',
  'breakdown.enrichSectors': 'Pobierz sektory (FMP + Wikidata)',
  'breakdown.enriching': 'Pobieranie sektorów…',
  'breakdown.enrichResult': '{enriched} wzbogaconych, {skipped} bez sektora, {failed} nieudanych.',
  'breakdown.empty': 'Za mało wycenionych pozycji, aby obliczyć podział.',
  'breakdown.unknown': 'Nieznane',
  'breakdown.other': 'Inne',

  // --- Wykrywanie duplikatów po ISIN (watchlist/kandydaci) -------------------
  'duplicates.backfillIsins': 'Wyszukaj brakujące identyfikatory spółek',
  'duplicates.backfilling': 'Wyszukiwanie…',
  'duplicates.backfillResult': '{checked} sprawdzonych, {updated} zaktualizowanych.',

  // --- Sygnały pozycji/watchlisty --------------------------------------------
  // Celowo fakty, nie czasowniki — „Wzmocnij"/„Zmniejsz" wciąż brzmią jak
  // polecenie, nawet bez słów „Kup"/„Sprzedaj" (zob. dopisek do DEVLOG
  // "Decision 3u.19"). Oba przypadki zbieżności nazywają dwa prawdziwe
  // warunki, nigdy nie mówiąc, co z nimi zrobić.
  'signals.positionReinforceFact': 'Wysoki wynik · niedoważone',
  'signals.positionReduceFact': 'Niski wynik · przeważone',
  'signals.watchlistReinforceFact': 'Wysoki wynik · cena poniżej celu',
  'signals.hold': 'Brak sygnału',
  'signals.not_applicable': 'Za mało danych',
  'signals.band.high': 'wysoki',
  'signals.band.mid': 'średni',
  'signals.band.low': 'niski',
  'signals.band.none': 'brak wyniku',
  'signals.positionTooltip': 'Wynik {score}/100 ({band}) · Alokacja {category}: {state}. Porównuje wynik tej pozycji z ogólnym odchyleniem całej jej klasy aktywów — to nie jest pełna ocena tej konkretnej pozycji.',
  'signals.watchlistTooltip': 'Wynik {score}/100 ({band}) · {distance} od Twojej docelowej ceny wejścia — połączenie dwóch istniejących wskaźników, nie rekomendacja.',

  'breakdown.category.STOCK': 'Akcje',
  'breakdown.category.ETF': 'ETF',
  'breakdown.category.CFD': 'CFD',
  'breakdown.category.P2P': 'Pożyczki P2P',
  'breakdown.category.FUND': 'Fundusze oszczędności pracowniczej',

  // --- Na co zwrócić uwagę dzisiaj ---
  'attention.title': 'Na co zwrócić uwagę dzisiaj',
  'attention.allClear': 'Na razie nic do zgłoszenia.',
  'attention.unresolvedInstruments': {
    one: '{count} pozycja ma niekompletne dane',
    few: '{count} pozycje mają niekompletne dane',
    many: '{count} pozycji ma niekompletne dane',
  },
  'attention.priceError': {
    one: '{count} pozycja nie ma dostępnej ceny',
    few: '{count} pozycje nie mają dostępnej ceny',
    many: '{count} pozycji nie ma dostępnej ceny',
  },
  'attention.priceStale': {
    one: '{count} pozycja nie była ostatnio odświeżona',
    few: '{count} pozycje nie były ostatnio odświeżone',
    many: '{count} pozycji nie było ostatnio odświeżonych',
  },
  'attention.allocationUnder': 'Twój cel {category} jest niedoważony o {gap} punktów',
  'attention.allocationOver': 'Twój cel {category} jest przeważony o {gap} punktów',

  // --- Stan danych ---
  'dataHealth.title': 'Stan danych',
  'dataHealth.subtitle':
    'Dla każdej posiadanej pozycji: skąd pochodzi jej wartość, na jaki dzień jest aktualna i czy jej corporate actions są potwierdzone.',
  'dataHealth.empty': 'Brak otwartych pozycji.',
  'dataHealth.staleSince': 'ostatnia cena: {date}',
  'dataHealth.declaredSince': 'zadeklarowana wycena na dzień: {date}',

  'dataHealth.summary.info': { one: '{count} wiarygodna', other: '{count} wiarygodnych' },
  'dataHealth.summary.attention': { one: '{count} do obserwacji', other: '{count} do obserwacji' },
  'dataHealth.summary.actionRequired': { one: '{count} wymaga działania', other: '{count} wymagają działania' },
  'dataHealth.summary.notApplicable': { one: '{count} nie dotyczy', other: '{count} nie dotyczy' },

  'dataHealth.column.instrument': 'Instrument',
  'dataHealth.column.valuation': 'Wycena',
  'dataHealth.column.corporateActions': 'Corporate actions',
  'dataHealth.column.severity': 'Jakość',
  'dataHealth.column.recommendedAction': 'Przydatne działanie',

  'dataHealth.valuation.kind.market_price': 'Cena rynkowa',
  'dataHealth.valuation.kind.declared_value': 'Wartość zadeklarowana',
  'dataHealth.valuation.kind.unavailable': 'Wartość niedostępna',
  'dataHealth.valuation.freshness.stale': 'nieaktualna',
  'dataHealth.valuation.freshness.unknown': 'nigdy niepotwierdzona',

  'dataHealth.corporateActions.status.verified': 'Potwierdzone',
  'dataHealth.corporateActions.status.no_events': 'Nie znaleziono żadnych',
  'dataHealth.corporateActions.status.candidate_single_source': 'Znalezione przez jedno źródło — do potwierdzenia',
  'dataHealth.corporateActions.status.provider_conflict': 'Źródła się nie zgadzają',
  'dataHealth.corporateActions.status.suspect_ticker_reuse': 'Historia symbolu wymaga sprawdzenia',
  'dataHealth.corporateActions.status.incomplete_coverage': 'Niepełne pokrycie Alpha Vantage',
  'dataHealth.corporateActions.status.never_checked': 'Nigdy nie sprawdzone',
  'dataHealth.corporateActions.eventCounts': '{confirmed} potwierdzone, {outstanding} do potwierdzenia',

  'dataHealth.severity.info': 'Informacja',
  'dataHealth.severity.attention': 'Uwaga',
  'dataHealth.severity.action_required': 'Wymagane działanie',
  'dataHealth.severity.not_applicable': 'Nie dotyczy',

  'dataHealth.action.fix_symbol': 'Popraw symbol',
  'dataHealth.action.refresh_quotes': 'Odśwież notowania',
  'dataHealth.action.import_recent_statement': 'Zaimportuj aktualny wyciąg',
  'dataHealth.action.resume_alpha_vantage': 'Wznów weryfikację Alpha Vantage',
  'dataHealth.action.verify_eodhd': 'Zweryfikuj przez EODHD',

  // --- Lista startowa ---
  'onboarding.title': 'Pierwsze kroki',
  'onboarding.dismiss': 'Ukryj',
  'onboarding.step.import': 'Zaimportuj wyciąg transakcji',
  'onboarding.why.import': 'odtwarza rzeczywistą historię Twoich zakupów i sprzedaży',
  'onboarding.step.refresh': 'Odśwież kursy',
  'onboarding.why.refresh': 'aktualizuje bieżącą wartość Twoich pozycji',
  'onboarding.step.unresolved': 'Sprawdź nierozpoznane pozycje',
  'onboarding.why.unresolved': 'pozycja bez dopasowania dostawcy pozostaje poza każdą analizą',
  'onboarding.step.fundamentals': 'Pobierz dane fundamentalne',
  'onboarding.why.fundamentals': 'umożliwia obliczenie wyników Value, Growth i Quality',
  'onboarding.step.allocation': 'Ustaw alokację docelową',
  'onboarding.why.allocation': 'porównuje Twój portfel z limitami, które sam ustalasz',
  'onboarding.step.watchlist': 'Dodaj kilka instrumentów do obserwowanych',
  'onboarding.why.watchlist': 'śledzi instrumenty, które rozważasz, bez ich posiadania',

  // --- Alokacja docelowa ---
  'allocation.title': 'Alokacja docelowa',
  'allocation.description':
    'Bieżący podział według klasy aktywów w porównaniu z zakresem, który sam ustalasz — wyłącznie opisowe, nigdy sugestia kupna lub sprzedaży konkretnego instrumentu.',
  'allocation.empty': 'Brak jeszcze wycenionych pozycji do porównania z celem.',
  'allocation.category': 'Klasa aktywów',
  'allocation.current': 'Aktualnie',
  'allocation.target': 'Zakres docelowy',
  'allocation.gap': 'Status',
  'allocation.gapTooltip': 'Porównanie z własnymi celami alokacji — to nie jest sugestia kupna ani sprzedaży.',
  'allocation.amount': 'Aby osiągnąć minimum',
  'allocation.state.within': 'W zakresie',
  'allocation.state.under': 'Niedoważone',
  'allocation.state.over': 'Przeważone',
  'allocation.state.no_target': 'Brak ustalonego celu',
  'allocation.amountToInvest':
    'Około {amount} nowych wpłat pozwoliłoby osiągnąć minimum tego zakresu — statyczne oszacowanie zakładające niezmienne kursy i resztę portfela, bez sprzedawania czegokolwiek.',
  'allocation.invalidRange': 'Podaj prawidłowy zakres: 0–100, minimum nie większe niż maksimum.',
  'allocation.setTarget': 'Ustaw cel',

  // --- Polityka osobista ---
  'policy.title': 'Polityka osobista',
  'policy.subtitle':
    'Twoje własne zasady decyzyjne — cel, horyzont, płynność, tolerancja ryzyka i limity koncentracji. Narzędzie porównuje portfel z tymi zasadami i sygnalizuje rozbieżności; nigdy nie rekomenduje kupna ani sprzedaży.',
  'policy.edit': 'Edytuj moją politykę',
  'policy.empty': 'Nie zdefiniowano jeszcze polityki osobistej. Kliknij „Edytuj moją politykę", aby ją ustawić.',

  'policy.objective': 'Cel',
  'policy.objective.growth': 'Wzrost',
  'policy.objective.income': 'Dochód',
  'policy.objective.preservation': 'Ochrona kapitału',
  'policy.objectiveNote': 'Dowolna notatka',

  'policy.horizon': 'Horyzont',
  'policy.horizon.short': 'Krótkoterminowy',
  'policy.horizon.medium': 'Średnioterminowy',
  'policy.horizon.long': 'Długoterminowy',
  'policy.horizonTargetDate': 'Data docelowa',

  'policy.liquidity': 'Płynność',
  'policy.liquidityAmount': 'Przewidywana kwota',
  'policy.liquidityDate': 'Przewidywany termin',
  'policy.liquidityNote': 'Dowolna notatka',

  'policy.riskTolerance': 'Tolerancja ryzyka i zdolność do straty',
  'policy.riskToleranceNote': 'Tolerancja (dowolny tekst)',
  'policy.lossCapacityPct': 'Maksymalna akceptowalna strata (%)',
  'policy.lossCapacityValue': 'maksymalna akceptowalna strata: {pct}%',

  'policy.limits.title': 'Limity osobiste',
  'policy.limits.subtitle':
    'Twoje własne progi koncentracji — wg linii, sektora, kraju, waluty lub typu aktywa. Przekroczenie to fakt, nigdy instrukcja kupna lub sprzedaży.',
  'policy.limits.dimension': 'Wymiar',
  'policy.limits.target': 'Cel',
  'policy.limits.range': 'Zakres',
  'policy.limits.min': 'Min %',
  'policy.limits.max': 'Maks %',
  'policy.limits.targetPlaceholder.sector': 'Technology',
  'policy.limits.targetPlaceholder.country': 'France',
  'policy.limits.targetPlaceholder.currency': 'USD',
  'policy.limits.targetPlaceholder.category': 'STOCK',

  'policy.dimension.line': 'Na linię',
  'policy.dimension.sector': 'Sektor',
  'policy.dimension.country': 'Kraj',
  'policy.dimension.currency': 'Waluta',
  'policy.dimension.category': 'Typ aktywa',
  'policy.dimension.declared_valuation': 'Wartości zadeklarowane',

  'policy.gaps.allWithin': 'Wszystkie Twoje limity osobiste są obecnie zachowane.',
  'policy.gaps.disclaimer': 'To stwierdzenia faktów, a nie sugestia kupna lub sprzedaży.',
  'policy.gaps.yourLimit': 'Twój limit: {range}',

  // --- Historia wartości ---
  'history.title': 'Wartość w czasie',
  'history.value': 'Wartość',
  'history.invested': 'Zainwestowano',
  'history.benchmark': 'Benchmark',
  'history.caveat':
    'Rzeczywista rekonstrukcja na podstawie faktycznych zakupów/sprzedaży, a nie symulacja dzisiejszych pozycji przeniesiona w przeszłość. CFD nie mogą być uwzględnione (ich ilość to liczba kontraktów, a nie akcji).',
  'history.benchmarkCaveat':
    'Przerywana linia to nie zwykły stosunek cen: symuluje, ile byłaby dziś warta ta sama kwota zainwestowana w benchmark w tych samych dniach (wraz ze sprzedażami).',
  'history.capped':
    'Historia zaczyna się {date} — to głębokość zapisanej historii cen, nie data pierwszego zakupu.',
  'history.empty': 'Za mało danych (lotów lub zapisanych cen), aby zrekonstruować historię.',

  'table.unrealized': 'Niezrealizowany ({currency})',
  'table.performance': 'Zwrot',
  'table.score': 'Wynik',
  'table.scoreTooltip':
    'Wynik złożony łączący domyślnie Value (30%), Growth (25%), Quality (25%) i Techniczny (20%) — wagi są przeliczane dla każdej pozycji, gdy dla filaru brak danych. Kliknij plakietkę, aby zobaczyć rzeczywisty podział dla tej pozycji.',
  'table.signal': 'Sygnał',
  'table.since': 'Od',
  'table.account': 'Rachunek',
  'table.insights': 'Analizy',
  'table.empty': 'Brak pozycji. Zaimportuj wyciąg XTB albo dodaj wiersz ręcznie.',
  'table.lots': {
    one: '{count} transza',
    few: '{count} transze',
    many: '{count} transz',
  },
  'table.short': 'krótka',
  'table.manual': 'ręczna',

  'filters.account': 'Rachunek',
  'filters.all': 'Wszystkie',
  'filters.type': 'Typ',
  'filters.dateFrom': 'Od',
  'filters.dateTo': 'Do',
  'filters.search': 'Szukaj',
  'filters.priceMin': 'Cena min.',
  'filters.priceMax': 'Cena maks.',
  'filters.capMin': 'Kapitalizacja min.',
  'filters.capMax': 'Kapitalizacja maks.',
  'filters.debtMax': 'Dług/kapitał własny maks.',
  'filters.historyMin': 'Historia min. (lata)',
  'filters.dividendMin': 'Min. stopa dywidendy (%)',
  'table.columns': 'Kolumny',

  // --- Transakcje --------------------------------------------------------------
  'transactions.title': 'Transakcje',
  'transactions.subtitle':
    'Dywidendy, opłaty, zakupy/sprzedaże i ruchy gotówkowe zgodnie z importem — poniższe podsumowanie odzwierciedla aktywne filtry, nie sumę od zawsze.',
  'transactions.viewDividends': 'Zobacz dywidendy według konta i roku →',
  'transactions.date': 'Data',
  'transactions.type': 'Typ',
  'transactions.instrument': 'Instrument',
  'transactions.account': 'Rachunek',
  'transactions.amount': 'Kwota',
  'transactions.comment': 'Komentarz',
  'transactions.empty': 'Brak transakcji dla tych filtrów.',
  'transactions.summary.netDividends': 'Dywidendy netto',
  'transactions.summary.grossAndTax': 'Brutto {gross} · podatek u źródła {tax}',
  'transactions.summary.fees': 'Łączne opłaty',
  'transactions.summary.realizedPl': 'Zrealizowany zysk/strata',
  'transactions.summary.effectSplit': 'Efekt instrumentu {instrument} · Waluta i opłaty {currency}',
  'transactions.summary.effectCoverage':
    '({resolved} z {total} zamkniętych transakcji — pozostałe, głównie CFD, nie mają kursu przeliczeniowego do podziału)',
  'transactions.instrumentEffect': 'Efekt instrumentu',
  'transactions.instrumentEffectTooltip':
    'Ruch ceny samego instrumentu, po kursie z dnia otwarcia — jedna z dwóch części zrealizowanego zysku/straty. Widoczne tylko dla zamkniętych transakcji.',
  'transactions.currencyEffect': 'Waluta i opłaty',
  'transactions.currencyEffectTooltip':
    'Reszta zysku/straty po odjęciu ruchu ceny samego instrumentu (po kursie z dnia otwarcia) — głównie ruch kursu walutowego od tego czasu, plus prowizja/swap. Widoczne tylko dla zamkniętych transakcji, dla których eksport brokera zawierał oba kursy przeliczeniowe.',
  'transactions.group.all': 'Wszystkie',
  'transactions.group.dividends': 'Dywidendy',
  'transactions.group.trades': 'Zakupy/sprzedaże',
  'transactions.group.fees': 'Opłaty',
  'transactions.group.cash': 'Gotówka',
  'transactions.type.BUY': 'Zakup',
  'transactions.type.SELL': 'Sprzedaż',
  'transactions.type.CLOSED_TRADE': 'Zamknięta pozycja',
  'transactions.type.DIVIDEND': 'Dywidenda',
  'transactions.type.TAX': 'Podatek u źródła',
  'transactions.type.FEE': 'Opłata',
  'transactions.type.DEPOSIT': 'Wpłata',
  'transactions.type.WITHDRAWAL': 'Wypłata',
  'transactions.type.INTEREST': 'Odsetki',
  'transactions.type.OTHER': 'Inne',
  'transactions.actions': 'Akcje',
  'transactions.manual.title': 'Transakcja wpisana ręcznie',
  'transactions.manual.subtitle':
    'Dywidenda, opłata lub przepływ gotówki brakujący w imporcie — nigdy kupno/sprzedaż (patrz uwaga poniżej).',
  'transactions.manual.newTitle': 'Nowa transakcja',
  'transactions.manual.note':
    'Kupno, sprzedaż i zamknięte pozycje nie są tu dostępne — dodaj lub popraw pozycję ze strony Portfel.',
  'transactions.invalidAmount': 'Podaj prawidłową kwotę.',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Aktualizacja cen',
  'prices.subtitle':
    'Darmowi dostawcy mocno ograniczają liczbę zapytań, więc każde kliknięcie przetwarza listę w ramach budżetu czasu i pokazuje, ile zostało. Jeden przycisk aktualizuje historię (wykresy trendu poniżej), a następnie kursy na żywo — sumy portfela powyżej aktualizują się razem z nimi. Tylko koszt nabycia (Zainwestowano) nadal pochodzi od brokera.',
  'prices.phaseHistory': 'Krok 1/2 — Historia cen',
  'prices.phaseLive': 'Krok 2/2 — Kursy na żywo',
  'prices.refresh': 'Odśwież',
  'prices.refreshing': 'Odświeżanie…',
  'prices.progress': '{done} / {total} przetworzonych instrumentów',
  'prices.retryFailed': {
    one: 'Ponów nieudany instrument ({count})',
    few: 'Ponów nieudane instrumenty ({count})',
    many: 'Ponów nieudane instrumenty ({count})',
  },
  'prices.summary': 'Zaktualizowano: {updated}, już aktualne: {skipped}, nie pobrano: {failed}.',
  'prices.remaining': {
    one: 'Pozostał {count} instrument — kliknij ponownie, aby kontynuować.',
    few: 'Pozostały {count} instrumenty — kliknij ponownie, aby kontynuować.',
    many: 'Pozostało {count} instrumentów — kliknij ponownie, aby kontynuować.',
  },
  'prices.updated': '{symbol}: nowe świece: {bars}, źródło: {provider}.',
  'prices.alreadyFresh': '{symbol}: już aktualne.',
  'prices.notMapped': '{symbol}: brak przypisania do dostawcy, nie ma czego pobrać.',
  'prices.symbolNotFound': '{symbol}: nieznany dla {provider}. Sprawdź symbol dostawcy.',
  'prices.rateLimited': '{symbol}: {provider} ogranicza zapytania. Spróbuj za kilka minut.',
  'prices.planLimited':
    '{symbol}: dostępny u {provider} tylko w planie płatnym. Symbol jest poprawny — nie ma tu nic do poprawienia.',
  'prices.alreadyRunning':
    'Odświeżanie już trwa. Dwa naraz zużywają podwójny limit bez żadnej korzyści — poczekaj na zakończenie pierwszego.',
  'prices.stillUnavailable':
    '{symbol}: nadal brak notowań. Już pytaliśmy dzisiaj — żaden skonfigurowany dostawca nie obejmuje tego rynku w darmowym planie.',
  'prices.needsIsin':
    '{symbol}: żadne źródło nie mogło nawet spróbować — brakuje identyfikatora. Wpisz ISIN w wierszu (znajdziesz go na stronie instrumentu u brokera), a przy następnym odświeżeniu zostanie podjęta próba.',
  'prices.notPriceable':
    '{symbol}: dla tego instrumentu nie istnieje cena rynkowa. Nieprzenoszalne prawo z operacji korporacyjnej nie podlega obrotowi, więc żadne źródło go nie notuje.',
  'prices.noProvider': '{symbol}: brak dostępnego dostawcy danych.',
  'prices.failed': '{symbol}: pobieranie przez {provider} nie powiodło się.',
  'prices.budgetReached': 'Budżet czasu wyczerpany, pozostało instrumentów: {remaining}.',
  'prices.noFallbackConfigured':
    'Yahoo ogranicza zapytania, a żaden dostawca zapasowy nie jest skonfigurowany. Dodaj darmowy klucz TWELVEDATA_API_KEY do .env (rejestracja e-mailem, bez karty), aby odświeżanie działało dalej.',

  'fundamentals.updated': '{symbol}: pobrano {concepts} wskaźnik(ów) z {provider}.',
  'fundamentals.alreadyFresh': '{symbol}: już aktualne.',
  'fundamentals.notApplicable': '{symbol}: to nie spółka — nie ma dla niej danych fundamentalnych.',
  'fundamentals.noProvider': '{symbol}: SEC EDGAR nie jest skonfigurowany (brak SEC_USER_AGENT).',
  'fundamentals.symbolNotFound': '{symbol}: nie znaleziono w indeksie emitentów SEC.',
  'fundamentals.rateLimited': '{symbol}: SEC EDGAR ogranicza zapytania. Spróbuj ponownie za chwilę.',
  'fundamentals.failed': '{symbol}: pobieranie nie powiodło się ({error}).',

  'table.trend': 'Trend (90 dni)',
  'mapping.verified': 'zweryfikowane',
  'mapping.verifiedTooltip': 'Dostawca zwrócił dane dla tego symbolu {date} ({provider}).',

  // --- Settings page -------------------------------------------------------
  'settings.title': 'Ustawienia',
  'settings.subtitle': 'Zarządzaj kluczami API i źródłami danych.',
  'settings.groupPortfolioData.title': 'Dane portfela',
  'settings.groupPortfolioData.subtitle':
    'Importuj, uzupełniaj i odświeżaj dane wykorzystywane w śledzeniu portfela.',
  'settings.groupIntegrity.title': 'Spójność i korekty',
  'settings.groupIntegrity.subtitle':
    'Popraw symbole lub zarejestruj operacje kapitałowe wpływające na historię.',
  'settings.groupBackup.title': 'Kopia zapasowa',
  'settings.groupDataSources.title': 'Źródła danych',
  'settings.groupDataSources.subtitle':
    'Skonfiguruj dostawców używanych do cen, danych fundamentalnych i kursów walut.',
  'settings.description':
    'Te klucze API są przechowywane lokalnie w pliku .env i nigdy nie są wysyłane gdzie indziej. Dodaj klucze, aby aktywować dodatkowych dostawców cen i zmaksymalizować redundancję, jeśli jedno źródło ograniczy zapytania.',
  'settings.providerStatus': 'Stan dostawców danych',
  'settings.apiKey': 'Klucz API',
  'settings.secEdgarName': 'SEC EDGAR',
  'settings.contactInfo': 'Dane kontaktowe',
  'settings.contactInfoSet': 'Już skonfigurowane',
  'settings.noContactInfo': 'Twoje imię, nazwisko i email',
  'settings.contactInfoFormat':
    'Format: imię i nazwisko, spacja, potem email — np. „Jan Kowalski jan@example.com”. Wysyłane do SEC przy każdym zapytaniu (to ich wymóg, nie tej aplikacji); adres jednorazowy też się nada.',
  'settings.test': 'Testuj',
  'settings.testing': 'Testowanie…',
  'settings.getFreeKey': 'Zdobądź darmowy klucz',
  'settings.learnMore': 'Dowiedz się więcej',
  'settings.keylessNote': 'Również aktywne, bez konfiguracji: {names}.',
  'settings.noKey': 'Nie skonfigurowany',
  'settings.enabled': 'Włączony',
  'settings.disabled': 'Wyłączony',
  'settings.saved': 'Ustawienia zapisane. Backend przeładował konfigurację.',
  'settings.error': 'Błąd zapisywania ustawień: {error}',
  'settings.supportsFree': 'Plan darmowy: {limit}',
  'settings.coolingDown': 'Limit osiągnięty',
  'settings.coolingDownTooltip':
    'To źródło niedawno osiągnęło limit zapytań i jest tymczasowo wstrzymane — wznowi się samo po krótkiej przerwie.',
  'settings.coverage': '{served}/{total} Twoich pozycji',
  'settings.quotaUsed': '{used}/{limit} wykorzystane {period}',
  'settings.periodDay': 'dzisiaj',
  'settings.periodMonth': 'w tym miesiącu',
  'settings.periodMinute': 'w tej minucie',

  // Descriptions for each provider
  'provider.description.yahoo': 'Yahoo Finance — światowy, bez klucza',
  'provider.description.polygon': 'Polygon.io — USA + crypto, 5 req/min',
  'provider.description.alpha_vantage': 'Alpha Vantage — światowy, 5 req/min',
  'provider.description.boursorama': 'Boursorama — Euronext Paryż, bez klucza',
  'provider.description.frankfurt': 'Boerse Frankfurt — ISIN europejski, bez klucza',
  'provider.description.twelvedata': 'Twelve Data — USA zapasowe, 800 req/dzień',
  'provider.description.fmp': 'Financial Modeling Prep — Euronext, 250 req/dzień',
  'provider.description.tiingo': 'Tiingo — światowy, 500 req/dzień',
  'provider.description.barchart': 'Barchart — światowy, 400 req/dzień',
  'provider.description.intrinio': 'Intrinio — USA + Kanada, 500 req/dzień',
  'provider.description.eodhd': 'EODHD — 150+ giełdy światowe, 20 req/dzień',
  'provider.description.eoddata': 'Eoddata — akcje/crypto/forex, bez klucza',
  'provider.description.finviz': 'Finviz — akcje USA poprzez web scraping (niestabilny)',

  // --- Watchlist ------------------------------------------------------------
  'watchlist.title': 'Obserwowane',
  'watchlist.description': 'Instrumenty obserwowane, ale nieposiadane, oraz moment wejścia.',
  'watchlist.openItems': 'Obserwowane instrumenty',
  'watchlist.targetPrice': 'Docelowa cena wejścia',
  'watchlist.distanceToTarget': 'Odległość od celu',
  'watchlist.distanceToTargetTooltip':
    'Różnica między aktualną ceną a Twoją własną docelową ceną wejścia — nie jest to wynik: ujemna wartość oznacza, że cena jest poniżej Twojego celu.',
  'watchlist.note': 'Notatka',
  'watchlist.addedOn': 'Dodano',
  'watchlist.invalidTarget': 'Podaj prawidłową cenę docelową albo zostaw pole puste.',
  'watchlist.empty': 'Lista obserwowanych jest pusta — dodaj symbol powyżej, aby zacząć śledzenie.',
  'watchlist.form.title': 'Dodaj do obserwowanych',
  'watchlist.form.subtitle': 'Śledź symbol, którego jeszcze nie posiadasz, z opcjonalną docelową ceną wejścia.',
  'watchlist.form.newTitle': 'Nowy obserwowany instrument',
  'watchlist.form.symbol': 'Symbol',
  'watchlist.form.companyName': 'Nazwa spółki (opcjonalnie)',
  'watchlist.form.companyNamePlaceholder': 'np. LVMH',
  'watchlist.form.targetPrice': 'Docelowa cena wejścia (opcjonalnie)',
  'watchlist.form.targetPriceTooltip': 'Twój własny punkt odniesienia — nigdy nie sugerowany przez aplikację.',
  'watchlist.form.note': 'Notatka (opcjonalnie)',

  // --- Filtr perełek (etap 5) -----------------------------------------------
  'gems.title': 'Perełki',
  'gems.description':
    'Ręcznie wybrana lista kandydatów, uszeregowana według wyniku, do wyszukiwania obiecujących spółek, których jeszcze nie posiadasz ani nie obserwujesz.',
  'gems.priceFilterTitle': 'Filtr ceny',
  'gems.priceFilterHint': 'Stosowany do wszystkich list na tej stronie — Kandydaci, uniwersum S&P 500 i skany Finviz.',
  'gems.candidates': 'Kandydaci',
  'gems.empty': 'Brak kandydatów — dodaj symbol powyżej, aby zacząć go analizować.',
  'gems.form.title': 'Dodaj kandydata',
  'gems.form.subtitle': 'Przeanalizuj symbol, którego jeszcze nie posiadasz ani nie obserwujesz.',
  'gems.form.newTitle': 'Nowy kandydat',
  'gems.form.symbol': 'Symbol',
  'gems.form.companyName': 'Nazwa spółki (opcjonalnie)',
  'gems.form.companyNamePlaceholder': 'np. LVMH',

  // --- Odkrywanie (automatyczne wyszukiwanie kandydatów, etap 7) -----------
  'discovery.title': 'Odkrywanie',
  'discovery.description':
    'Automatyczne wyszukiwanie kandydatów. Każdy kandydat otrzymuje automatyczny werdykt Kup/Trzymaj/Sprzedaj, obliczony na podstawie jego istniejącego wyniku łącznego — to nie jest prawdziwa rekomendacja inwestycyjna.',
  'discovery.empty': 'Nic do pokazania.',
  'discovery.recommendationColumn': 'Werdykt',
  'discovery.recommendationTooltip':
    'Obliczone automatycznie na podstawie istniejącego wyniku łącznego — to nie jest prawdziwa rekomendacja inwestycyjna.',
  'discovery.recommendation.buy': 'Kup',
  'discovery.recommendation.hold': 'Trzymaj',
  'discovery.recommendation.sell': 'Sprzedaj',
  'discovery.recommendation.none': 'Brak danych',
  'discovery.verdictFilterLabel': 'Filtr werdyktu',
  'discovery.verdictFilterHint':
    'Stosowany do rankingu S&P 500 i skanów Finviz poniżej — ręcznie wybrani kandydaci powyżej nie mają werdyktu do filtrowania.',
  'discovery.dataQualityFilterLabel': 'Jakość danych',
  'discovery.dataQualityFilterOption': 'Pokazuj tylko kandydatów z wiarygodnymi danymi',
  'discovery.dataQualityFilterHint':
    'Wymaga obliczonego wyniku, aktualnej i poprawnie zmapowanej ceny oraz braku oczekującej weryfikacji zdarzenia korporacyjnego.',
  'discovery.marketSectorFilterLabel': 'Kraj i sektor',
  'discovery.marketSectorFilterHint':
    'Stosowany do rankingu S&P 500 i skanów Finviz poniżej — ręcznie wybrani kandydaci powyżej nie mają jeszcze filtra kraju/sektora. Opcje odzwierciedlają aktualnie wczytane dane.',
  'discovery.marketCapFilterLabel': 'Kapitalizacja',
  'discovery.marketCapFilterHint':
    'Stosowany do rankingu S&P 500 i skanów Finviz poniżej — ręcznie wybrani kandydaci powyżej nie mają obliczonej kapitalizacji. Przybliżenie (średnia ważona rozwodnionych akcji × cena), wystarczające do filtrowania, nie do celów księgowych.',
  'discovery.debtRatioFilterLabel': 'Zadłużenie',
  'discovery.debtRatioFilterHint':
    'Wskaźnik dług/kapitał własny, już obliczony dla filaru Value — tylko dług długoterminowy. Stosowany do rankingu S&P 500 i skanów Finviz poniżej, nie do ręcznie wybranych kandydatów powyżej.',
  'discovery.historyFilterLabel': 'Minimalna historia cen',
  'discovery.historyFilterHint':
    'Przybliżona liczba lat historii cen w pamięci podręcznej dla tego instrumentu — wymóg wystarczalności danych, nie ocena samej spółki. Stosowany do rankingu S&P 500 i skanów Finviz poniżej.',
  'discovery.dividendFilterLabel': 'Stopa dywidendy',
  'discovery.dividendFilterHint':
    'Szacowana na podstawie zgłoszonej dywidendy na akcję podzielonej przez cenę — szacunek na poziomie spółki, inny niż rzeczywista stopa już obliczona dla Twoich posiadanych pozycji. Stosowany do rankingu S&P 500 i skanów Finviz poniżej. Wymaga co najmniej jednego kliknięcia „Uzupełnij dane o dywidendach” dla już ocenionych kandydatów.',
  'discovery.rankByValue': 'Sortuj wg Value',
  'discovery.rankByGrowth': 'Sortuj wg Growth',
  'discovery.valueScore': 'Value',
  'discovery.valueScoreTooltip': 'Jeden z filarów wyniku łącznego — nie samodzielna ocena.',
  'discovery.growthScore': 'Growth',
  'discovery.growthScoreTooltip': 'Jeden z filarów wyniku łącznego — nie samodzielna ocena.',
  'discovery.marketCap': 'Kapitalizacja',
  'discovery.debtRatio': 'Dług/kapitał',
  'discovery.dividendYield': 'Stopa dywidendy',
  'discovery.backfillDividends': 'Uzupełnij dane o dywidendach',
  'discovery.importResult': '{imported} zaimportowanych, {alreadyPresent} już obecnych.',
  'discovery.refreshResultMore': '{evaluated} ocenionych, {remaining} pozostało — kliknij ponownie, aby kontynuować.',
  'discovery.refreshResultDone': '{evaluated} ocenionych, nic nie pozostało.',
  'discovery.sp500.title': 'Uniwersum S&P 500',
  'discovery.sp500.description':
    'Statyczna lista spółek z indeksu S&P 500, oceniana tymi samymi filarami Value/Growth co reszta aplikacji.',
  'discovery.sp500.import': 'Zaimportuj uniwersum S&P 500',
  'discovery.sp500.refresh': 'Oceń kolejną partię',
  'discovery.finviz.title': 'Predefiniowane skany Finviz',
  'discovery.finviz.description':
    'Inny, węższy sygnał — zakupy insiderów i warunki wyprzedania technicznego — nigdy nie łączony z wynikami Value/Growth powyżej.',
  'discovery.finviz.insiderBuys': 'Zakupy insiderów',
  'discovery.finviz.oversold': 'Wyprzedane',
  'discovery.finviz.slowNotice':
    'Każdy skan rozwiązuje cenę i fundamenty każdego wyniku pojedynczo — może zająć kilka minut dla ~10 kandydatów.',
  'discovery.finviz.failedCount': 'Nie udało się przetworzyć {count} kandydatów — zostali pominięci.',
  'discovery.finviz.scanningNotice':
    'Skan w toku — dostawcy o darmowym poziomie mogą potrzebować kilku minut. Nie zamykaj tej strony.',

  'prediction.title': 'Historia cen',
  'prediction.description':
    'Prawdziwy model predykcyjny potrzebuje rzetelnego backtestu, a ten potrzebuje głębszej historii cen niż ta aplikacja normalnie przechowuje. Ten krok pobiera kilka lat dziennych świec dla instrumentów już wycenionych — tylko cena, ponieważ fundamenty nie są jeszcze przechowywane z datą złożenia, a użycie dzisiejszego wyniku do „przewidywania" przeszłego zwrotu byłoby błędem antycypacji. Zobacz „Backtest" poniżej, co model robi z tymi danymi.',
  'prediction.backfill': 'Pobierz historię cen',
  'prediction.running': 'Pobieranie…',
  'prediction.alreadyRunning': 'Pobieranie jest już w toku.',
  'prediction.backfillResult': '{updated} zaktualizowanych, {failed} błędów, {barsAdded} nowych świec zapisanych.',
  'backtest.title': 'Backtest',
  'backtest.description':
    'Prosty model techniczny oparty tylko na cenie (momentum, średnie kroczące, zrealizowana zmienność), trenowany od nowa przy każdym uruchomieniu i oceniany wyłącznie na danych po okresie treningowym — nigdy predykcja dla pojedynczego instrumentu, tylko własna historyczna skuteczność modelu.',
  'backtest.run': 'Uruchom backtest',
  'backtest.running': 'W trakcie…',
  'backtest.disclaimer':
    'To jedna historyczna ocena, nie dowód na realną przewagę w handlu. Model widzi tylko cenę — brak fundamentów, wiadomości, osądu — a wyniki z przeszłości niczego nie gwarantują na przyszłość.',
  'backtest.instrumentsUsed': 'Wykorzystane instrumenty',
  'backtest.trainPeriod': 'Okres treningowy (próbki)',
  'backtest.testPeriod': 'Okres testowy (próbki)',
  'backtest.singleClassWarning':
    'Okres treningowy poruszał się tylko w jednym kierunku (np. nieprzerwany trend wzrostowy) — nie udało się dopasować użytecznego modelu, więc nie podano skuteczności.',
  'backtest.testAccuracy': 'Skuteczność na okresie testowym',
  'backtest.avgReturnUp': 'Śr. zrealizowany zwrot — przewidywany wzrost',
  'backtest.avgReturnDown': 'Śr. zrealizowany zwrot — przewidywany spadek',
  'backtest.lowSampleWarning': 'Okres testowy ma zbyt mało próbek, by ufać tej wartości skuteczności.',

  'factors.title': 'Ekspozycja czynnikowa (model czteroczynnikowy Carharta)',
  'factors.description':
    'Wyjaśniające, nie predykcyjne: co historycznie napędzało dzienny zwrot każdej pozycji — Rynek, Wielkość, Wartość i Momentum — na podstawie publicznych danych czynnikowych Kennetha Frencha. Tylko pozycje posiadane, dopasowane regionalnie (instrument amerykański wobec czynników US, europejski wobec czynników Europy).',
  'factors.import': 'Zaimportuj dane czynnikowe',
  'factors.importResult': '{imported} zaimportowanych, {alreadyPresent} już obecnych.',
  'factors.empty': 'Żadnej posiadanej pozycji nie udało się jeszcze dopasować do regionu.',
  'factors.region': 'Region',
  'factors.alpha': 'Alfa',
  'factors.alphaTooltip': 'Dzienny nadwyżkowy zwrot niewyjaśniony przez cztery czynniki — wyraz wolny regresji.',
  'factors.betaMkt': 'Rynek',
  'factors.betaMktTooltip': 'Wrażliwość na nadwyżkowy zwrot całego rynku (Mkt-RF).',
  'factors.betaSmb': 'Wielkość',
  'factors.betaSmbTooltip': 'Wrażliwość na zwrot małych vs dużych spółek (SMB).',
  'factors.betaHml': 'Wartość',
  'factors.betaHmlTooltip': 'Wrażliwość na zwrot spółek o wysokim vs niskim wskaźniku book-to-market (HML).',
  'factors.betaMom': 'Momentum',
  'factors.betaMomTooltip': 'Wrażliwość na zwrot niedawnych zwycięzców vs przegranych (Mom/WML).',
  'factors.rSquared': 'R²',
  'factors.rSquaredTooltip': 'Udział wariancji dziennego zwrotu wyjaśniony łącznie przez cztery czynniki.',
  'factors.observations': 'Dni',
  'factors.notApplicable.no_region_match':
    'Żadna publikowana dzienna seria czynnikowa nie obejmuje kraju tego instrumentu.',
  'factors.notApplicable.insufficient_history':
    'Wciąż za mało nakładającej się historii cen i czynników.',

  // --- Silnik scoringu (etap 3) ---------------------------------------------
  'scores.refreshTitle': 'Fundamenty',
  'scores.refreshSubtitle':
    'Pobiera dane finansowe spółek z SEC EDGAR (USA) i ESEF (Europa), aby zasilić wyniki Value/Growth/Quality.',
  'scores.refresh': 'Pobierz fundamenty',
  'scores.refreshing': 'Pobieranie…',
  'scores.refreshSummary':
    '{updated} zaktualizowano, {skipped} już aktualne, {notApplicable} nie dotyczy, {failed} nie pobrano.',
  'fundamentals.alreadyRunning':
    'Pobieranie fundamentów już trwa. Dwa naraz zużywają podwójną liczbę zapytań bez żadnej korzyści — poczekaj na zakończenie pierwszego.',
  'scores.compositeTooltip': 'Wynik złożony: {score}/100',
  'scores.notAdvice': 'Podsumowuje dostępne wskaźniki. To nie jest rekomendacja inwestycyjna.',
  'scores.clickForDetail': 'Kliknij, aby zobaczyć kryteria, użyte dane i pominięte elementy.',
  'scores.summarySentence': 'Wynik {score}/100: {band}.',
  'scores.summary.high': 'wskaźniki są ogólnie korzystne na podstawie dostępnych danych',
  'scores.summary.mid': 'wskaźniki są mieszane na podstawie dostępnych danych',
  'scores.summary.low': 'wskaźniki są ogólnie niekorzystne na podstawie dostępnych danych',
  'scores.strengths': 'Mocne strony',
  'scores.watchPoints': 'Punkty do obserwacji',
  'scores.noneIdentified': 'Brak na razie',
  'scores.pillarScore': '{score}/100 ({weight}% wyniku złożonego)',
  'scores.pillarScoreTooltip': '{pillar}: {score}/100 ({weight}%)',
  'scores.pillarDropped': 'Brak danych',
  'scores.binaryPass': 'Zaliczone',
  'scores.binaryFail': 'Niezaliczone',
  'scores.pillar.value': 'Value',
  'scores.pillar.growth': 'Growth',
  'scores.pillar.quality': 'Quality',
  'scores.pillar.technical': 'Techniczny',
  'scores.metric.pe_ratio': 'Wskaźnik P/E',
  'scores.metric.pb_ratio': 'Wskaźnik P/B',
  'scores.metric.fcf_yield': 'Rentowność FCF',
  'scores.metric.debt_to_equity': 'Dług/Kapitał własny',
  'scores.metric.dividend_yield': 'Stopa dywidendy',
  'scores.metric.revenue_cagr': 'CAGR przychodów',
  'scores.metric.net_income_cagr': 'CAGR zysku netto',
  'scores.metric.revenue_growth_consistency': 'Regularność wzrostu',
  'scores.metric.roa_positive': 'Rentowność aktywów > 0',
  'scores.metric.cfo_positive': 'Przepływy operacyjne > 0',
  'scores.metric.accruals_quality': 'Zysk pokryty gotówką',
  'scores.metric.leverage_not_increasing': 'Zadłużenie nie rośnie',
  'scores.metric.no_significant_dilution': 'Brak znaczącego rozwodnienia',
  'scores.metric.price_vs_sma200': 'Cena vs średnia 200-dniowa',
  'scores.metric.momentum_12_1': 'Momentum 12-miesięczne',
  'scores.metric.sma50_vs_sma200': 'Średnia 50d vs 200d',
  'scores.droppedReason.missing_concept': 'Brak danych',
  'scores.droppedReason.non_positive_value': 'Wartość musi być dodatnia',
  'scores.droppedReason.missing_fx_rate': 'Kurs wymiany niedostępny',
  'scores.droppedReason.insufficient_history': 'Na razie za mało historii',

  // --- Analizy: aktualności/sentyment + komentarz AI (etap 6) --------------
  'insights.badgeLabel': 'Newsy i AI',
  'insights.badgeTooltip': 'Pokaż ostatnie wiadomości, sentyment i komentarz AI',
  'insights.newsTitle': 'Wiadomości i sentyment',
  'insights.noNews': 'Nie znaleziono ostatnich wiadomości dla tego instrumentu.',
  'insights.sentimentTooltip':
    'Ton tego artykułu według dostawcy (Alpha Vantage) — nie jest to opinia aplikacji o tym instrumencie.',
  'insights.sentiment.bullish': 'Wyraźnie pozytywny ton',
  'insights.sentiment.somewhatBullish': 'Raczej pozytywny ton',
  'insights.sentiment.neutral': 'Neutralny ton',
  'insights.sentiment.somewhatBearish': 'Raczej negatywny ton',
  'insights.sentiment.bearish': 'Wyraźnie negatywny ton',
  'insights.sentiment.unknown': 'Ton niedostępny',
  'insights.commentaryTitle': 'Komentarz AI',
  'insights.commentaryDisclaimer':
    'Podsumowanie wygenerowane na podstawie dostępnych danych, potencjalnie niepełnych — nie stanowi rekomendacji inwestycyjnej.',
  'insights.askPerplexity': 'Pobierz komentarz AI',

  'news.updated': '{symbol}: znaleziono {articles} artykuł(y/ów).',
  'news.alreadyFresh': '{symbol}: już aktualne (cache {days} dni).',
  'news.empty': '{symbol}: nie znaleziono ostatnich wiadomości.',
  'news.notMapped': '{symbol}: brak mapowania dostawcy, nie ma czego pobierać.',
  'news.noProvider': '{symbol}: Alpha Vantage nie jest skonfigurowane (brak klucza API).',
  'news.rateLimited': '{symbol}: Alpha Vantage ogranicza zapytania. Spróbuj ponownie za chwilę.',
  'news.failed': '{symbol}: pobieranie nie powiodło się ({error}).',

  'commentary.updated': '{symbol}: pobrano komentarz.',
  'commentary.alreadyFresh': '{symbol}: już aktualne (cache {days} dni).',
  'commentary.noProvider': '{symbol}: Perplexity nie jest skonfigurowane (brak klucza API).',
  'commentary.rateLimited': '{symbol}: Perplexity ogranicza zapytania. Spróbuj ponownie za chwilę.',
  'commentary.failed': '{symbol}: pobieranie nie powiodło się ({error}).',

  // --- Dywidendy -----------------------------------------------------------
  'dividends.title': 'Dywidendy',
  'dividends.subtitle': 'Co faktycznie otrzymano i potrącono, według konta i roku kalendarzowego.',
  'dividends.disclaimer':
    'Ten widok podsumowuje zaimportowane dywidendy i potrącenia. Nie oblicza ostatecznego zobowiązania podatkowego i nie zastępuje dokumentów dostarczonych przez brokera lub urząd skarbowy.',
  'dividends.empty': 'Nie zaimportowano jeszcze żadnych dywidend.',
  'dividends.heroTitle': 'Dywidendy {year} — brutto',
  'dividends.withholding': 'Podatek u źródła',
  'dividends.net': 'Netto',
  'dividends.gross': 'Brutto',
  'dividends.paymentCount': 'Wypłaty',
  'dividends.accountsAnalyzed': 'Przeanalizowane konta',
  'dividends.byYearAccount': 'Widok roczny według konta',
  'dividends.year': 'Rok',
  'dividends.account': 'Konto',
  'dividends.unknownAccount': 'Nieznane konto',
  'dividends.currency': 'Waluta',
  'dividends.unknownCurrency': 'Nieznana waluta',
  'dividends.exportSummaryCsv': 'Eksportuj (CSV, według konta i roku)',
  'dividends.detailTitle': 'Szczegóły wypłat',
  'dividends.detailEmpty': 'Brak wypłat dla tych filtrów.',
  'dividends.allYears': 'Wszystkie lata',
  'dividends.allAccounts': 'Wszystkie konta',
  'dividends.date': 'Data',
  'dividends.instrument': 'Instrument',
  'dividends.reconciliation': 'Uzgodnienie',
  'dividends.status.matched': 'Automatyczne',
  'dividends.status.no_withholding': 'Brak potrącenia',
  'dividends.status.unmatched_tax': 'Nieprzypisane potrącenie',
  'dividends.exportDetailCsv': 'Eksportuj (CSV, szczegóły transakcji)',

  // --- Przygotowanie podatkowe ---------------------------------------------
  'taxPrep.title': 'Roczne przygotowanie podatkowe',
  'taxPrep.subtitle':
    'Zaimportowane przepływy do uzgodnienia z Twoimi dokumentami podatkowymi, wg konta i roku — nigdy obliczenie podatku.',
  'taxPrep.disclaimer':
    'To zestawienie opiera się na zaimportowanych danych. Pomaga uzgodnić Twoje transakcje z dostępnymi dokumentami podatkowymi (IFU, raport podatkowy Mintos...), ale nie oblicza ostatecznego podatku i nie zastępuje Twojej deklaracji ani indywidualnej porady podatkowej.',
  'taxPrep.empty': 'Brak zaimportowanych transakcji z datą.',
  'taxPrep.emptyYear': 'Nie znaleziono istotnej podatkowo aktywności w tym roku.',
  'taxPrep.yearLabel': 'Rok podatkowy',
  'taxPrep.exportCsv': 'Eksportuj (CSV)',

  'taxPrep.envelope.cto': 'Rachunek maklerski',
  'taxPrep.envelope.pea': 'PEA',
  'taxPrep.envelope.p2p': 'P2P',
  'taxPrep.envelope.employee_savings': 'Oszczędności pracownicze',

  'taxPrep.status.to_reconcile': 'Do uzgodnienia',
  'taxPrep.status.not_applicable': 'Nie dotyczy',

  'taxPrep.dividendsGross': 'Dywidendy brutto',
  'taxPrep.dividendsWithholding': 'Podatek u źródła',
  'taxPrep.interest': 'Odsetki',
  'taxPrep.realizedGains': 'Zrealizowane zyski',
  'taxPrep.realizedLosses': 'Zrealizowane straty',
  'taxPrep.fees': 'Opłaty',
  'taxPrep.deposits': 'Wpłaty',
  'taxPrep.withdrawals': 'Wypłaty',
  'taxPrep.otherFlows': 'Inne przepływy (informacyjne)',
  'taxPrep.unmatchedSalesLine':
    'Wykryto {count} sprzedaż(y) na kwotę {amount} — zysk/strata nieobliczone: uzgodnienie partii (FIFO) niedostępne.',

  'taxPrep.noWithdrawalDetected':
    'Nie zaimportowano żadnej wypłaty za ten rok. Zyski pozostają wewnątrz koperty i nie są opodatkowane, dopóki w niej pozostają.',
  'taxPrep.withdrawalDetected':
    'Wykryto wypłatę na kwotę {amount}. Obowiązujące zasady podatkowe (wiek planu, warunki wyjścia) nie są obliczane automatycznie przez to narzędzie — sprawdź je samodzielnie lub z doradcą podatkowym.',
  'taxPrep.unmatchedSales': '{count} sprzedaż(y) bez obliczonego zysku (uzgodnienie partii niedostępne).',
  'taxPrep.notApplicable': 'Nie wykryto żadnej istotnej podatkowo operacji w tej kopercie w tym roku.',

  // --- Ryzyko portfela (DEVLOG "Decision 3u.67") ------------------------------
  'risk.title': 'Ryzyko portfela',
  'risk.subtitle': 'Na co Twój portfel jest faktycznie narażony — niezależnie od skonfigurowanych limitów.',
  'risk.disclaimer':
    'Poniższe fakty opisują bieżącą ekspozycję portfela — nie są to limity ani rekomendacje kupna/sprzedaży.',
  'concentration.title': 'Koncentracja pozycji',
  'concentration.empty': 'Za mało wycenionych pozycji, aby obliczyć koncentrację.',
  'concentration.value': 'Wartość',
  'liquidity.title': 'Wyceny deklarowane',
  'liquidity.subtitle': 'Część portfela wyceniana na podstawie wyciągu brokera, a nie ceny rynkowej.',
  'liquidity.total': 'Suma wycen deklarowanych',
  'liquidity.empty': 'Brak pozycji z wyceną deklarowaną.',
  'liquidity.source': 'Źródło',
  'liquidity.positionsCount': 'Pozycje',
  'drawdown.title': 'Maksymalne historyczne obsunięcie',
  'drawdown.maxDrawdown': 'Maksymalne obsunięcie',
  'drawdown.peak': 'Szczyt',
  'drawdown.trough': 'Dołek',
  'drawdown.recovery': 'Odzyskanie',
  'drawdown.recoveredOn': 'Ponownie osiągnął poprzedni szczyt {date}',
  'drawdown.notRecovered': 'Jeszcze nieodzyskane',
  'drawdown.noneObserved': 'Brak spadku w dostępnej historii.',
  'drawdown.insufficientHistory': 'Za mało historii, aby obliczyć maksymalne obsunięcie.',

  // --- Dziennik decyzji (DEVLOG "Decision 3u.68") -----------------------------
  'journal.title': 'Dziennik decyzji',
  'journal.subtitle': 'Twoje własne pisemne uzasadnienie decyzji lub ogólna notatka — nigdy nie obliczane ani nie oceniane.',
  'journal.empty': 'Brak wpisów w dzienniku.',
  'journal.general': 'Ogólny',
  'journal.entryDate': 'Napisano',
  'journal.reviewDate': 'Przegląd do',
  'journal.dueForReview': 'Do przeglądu',
  'journal.form.title': 'Zapisz decyzję',
  'journal.form.subtitle': 'Zapisz uzasadnienie teraz, dopóki jest jeszcze świeże.',
  'journal.form.symbol': 'Symbol (opcjonalnie)',
  'journal.form.thesis': 'Uzasadnienie',
  'journal.form.reviewDate': 'Data przeglądu (opcjonalnie)',
  'journal.outcome.title': 'Wynik',
  'journal.outcome.add': 'Dodaj wynik',
  'journal.outcome.save': 'Zapisz wynik',

  // --- Kopia zapasowa --------------------------------------------------------
  'backup.title': 'Kopia zapasowa',
  'backup.description':
    'Kopia lokalnej bazy danych z znacznikiem czasu — portfel, transakcje, poprawki, alokacje docelowe. Nic innego nie jest nigdy odczytywane ani zapisywane: klucze API (.env) nigdy nie są w niej zawarte. Zachowywanych jest 10 najnowszych kopii, starsze są automatycznie usuwane.',
  'backup.create': 'Utwórz kopię zapasową',
  'backup.created': 'Utworzono kopię zapasową: {filename}',
  'backup.empty': 'Brak kopii zapasowych.',
  'backup.date': 'Data',
  'backup.size': 'Rozmiar',
  'backup.restore': 'Przywróć',
  'backup.confirmRestore': 'Potwierdź przywrócenie',
  'backup.restored': 'Baza przywrócona z {filename}.',
  'backup.restoreWarning':
    'Wpisz dokładną nazwę pliku, aby potwierdzić — przywrócenie całkowicie zastępuje bieżącą bazę danych i nie można go cofnąć.',

  // --- Podziały akcji --------------------------------------------------------
  'corporateActions.title': 'Podziały akcji',
  'corporateActions.description':
    'Zarejestrowane podziały i scalenia akcji (splity i reverse splity). Surowe dane cenowe i loty nigdy nie są zmieniane — każdy wykres i obliczenie historyczne stosuje korektę przy odczycie. Wyłącznie opisowe, ograniczone do instrumentów już śledzonych przez aplikację.',
  'corporateActions.detect': 'Uruchom pełną weryfikację (wszystkie źródła)',
  'corporateActions.coverageTitle': 'Automatyczne pokrycie',
  'corporateActions.detectionChecked': 'Sprawdzono {checked} instrument(ów) z {candidates}.',
  'corporateActions.coveragePercent': '{percent}% pokrycia',

  // --- Trwałe pokrycie (Faza 4, DEVLOG "Step 3u.57") ------------------------
  // Ścisłe rozróżnienie instrument/zdarzenie: jeden instrument może mieć
  // kilka zdarzeń (np. BIVI.US i jego trzy scalenia akcji).
  'corporateActions.coverage.instrumentsEligible': '{count} instrument(ów) kwalifikuje się do automatycznej weryfikacji.',
  'corporateActions.coverage.instrumentsChecked': 'Sprawdzono już {checked} instrument(ów), pozostało {unchecked}.',
  'corporateActions.coverage.instrumentsExcluded': {
    one: '{count} aktywo nienotowane lub bez symbolu rynkowego jest wyłączone z pokrycia — to nie jest błąd.',
    other: '{count} aktywów nienotowanych lub bez symbolu rynkowego jest wyłączonych z pokrycia — to nie jest błąd.',
  },
  'corporateActions.coverage.verifiedEvents': {
    one: '1 operacja na akcjach potwierdzona przez kilka źródeł.',
    other: '{count} operacji na akcjach potwierdzonych przez kilka źródeł.',
  },
  'corporateActions.coverage.candidateEvents': {
    one: '1 operacja znaleziona przez jedno źródło nadal wymaga potwierdzenia.',
    other: '{count} operacji znalezionych przez jedno źródło nadal wymaga potwierdzenia.',
  },
  'corporateActions.coverage.conflictEvents': {
    one: '1 operacja ma rozbieżne źródła — wymaga sprawdzenia.',
    other: '{count} operacji ma rozbieżne źródła — wymagają sprawdzenia.',
  },
  'corporateActions.coverage.suspectEvents': {
    one: '1 zdarzenie nie zostało zastosowane — historia symbolu wymaga sprawdzenia.',
    other: '{count} zdarzeń nie zostało zastosowanych — historia symbolu wymaga sprawdzenia.',
  },

  // --- Odznaki zaufania (odrębne od pochodzenia) ----------------------------
  'corporateActions.confidence.verified_three_sources': 'Potwierdzone przez 3 źródła',
  'corporateActions.confidence.verified_cross_source': 'Potwierdzone przez kilka źródeł',
  'corporateActions.confidence.candidate_single_source': 'Znalezione przez jedno źródło — do potwierdzenia',
  'corporateActions.confidence.provider_conflict': 'Źródła się różnią — wymaga sprawdzenia',
  'corporateActions.confidence.suspect_ticker_reuse': 'Niezastosowane — historia symbolu wymaga sprawdzenia',
  'corporateActions.confidence.manual_promotion': 'Potwierdzone ręcznie',
  'corporateActions.confidence.manual': 'Dodane ręcznie',

  // --- Szczegóły pochodzenia (po kliknięciu) --------------------------------
  'corporateActions.provenance.title': 'Weryfikacja',
  'corporateActions.provenance.foundOn': '{provider} — zdarzenie znalezione {date} ({ratio})',
  'corporateActions.provenance.notUsedFmp': 'FMP — obecnie nieuwzględniane w obliczaniu zaufania',
  'corporateActions.provenance.notCheckedEodhd': 'EODHD — niesprawdzone (źródło celowane, na żądanie)',

  // --- Wznowienie Alpha Vantage (przycisk ręczny) ---------------------------
  'corporateActions.resume.title': 'Alpha Vantage',
  'corporateActions.resume.description':
    'Sprawdza do 20 instrumentów, które nie otrzymały jeszcze użytecznej odpowiedzi z tego źródła. Wykorzystuje dzienny limit dostawcy.',
  'corporateActions.resume.button': 'Wznów weryfikację Alpha Vantage',
  'corporateActions.resume.running': 'Sprawdzanie…',
  'corporateActions.resume.remaining': {
    one: '1 instrument nadal wymaga sprawdzenia w Alpha Vantage.',
    other: '{count} instrumentów nadal wymaga sprawdzenia w Alpha Vantage.',
  },
  'corporateActions.resume.upToDate': 'Wszystkie kwalifikujące się instrumenty zostały już sprawdzone w Alpha Vantage.',
  'corporateActions.resume.lastRun': 'Ostatnia partia: {date}',
  'corporateActions.resume.lastRunSummary':
    'Sprawdzono {checked} instrument(ów) — {verified} potwierdzenie(a) krzyżowe, {candidates} kandydat(ów), {noEvents} bez zwróconej operacji.',
  'corporateActions.resume.rateLimited':
    'Dostawca ograniczył liczbę żądań w tej partii — weryfikacja wznowi się później. To nie jest brak pokrycia.',
  'corporateActions.resume.paused': 'Codzienne automatyczne wznawianie jest wstrzymane.',
  'corporateActions.resume.neverRun': 'Żadne wznowienie nie zostało jeszcze uruchomione.',

  // --- Kandydaci do potwierdzenia (niezastosowane zdarzenia) ----------------
  'corporateActions.outstanding.title': 'Kandydaci do potwierdzenia',
  'corporateActions.outstanding.description':
    'Operacje znalezione przez jedno źródło lub z rozbieżnymi źródłami — nigdy nie stosowane automatycznie. W razie potrzeby potwierdź je celowaną weryfikacją EODHD.',
  'corporateActions.outstanding.empty': 'Brak kandydatów oczekujących na potwierdzenie.',
  'corporateActions.outstanding.providers': 'Źródło/a: {providers}',
  'corporateActions.detectionIncomplete':
    'Dostawca ogranicza liczbę zapytań; {count} instrument(ów) nie zostało sprawdzonych. Nie można wyciągnąć wniosków dla nich — spróbuj ponownie później.',
  'corporateActions.detectionFailedSummary': 'Nie udało się automatycznie sprawdzić {count} instrument(ów) w FMP.',
  'corporateActions.detectionFailedCaveat':
    'Brak sprawdzenia nie oznacza braku podziału. Sprawdź instrument w innym źródle albo dodaj operację ręcznie, jeśli to konieczne.',
  'corporateActions.detectionSkippedSummary': 'Pominięto {count} instrument(ów) — brak użytecznego symbolu',
  'corporateActions.historyTitle': 'Zarejestrowana historia',
  'corporateActions.historyCount': {
    one: '1 znana operacja kapitałowa.',
    other: '{count} znanych operacji kapitałowych.',
  },
  'corporateActions.historyNewEvents': {
    one: '1 nowe zdarzenie dodane podczas ostatniej detekcji.',
    other: '{count} nowych zdarzeń dodanych podczas ostatniej detekcji.',
  },
  'corporateActions.historyNoNewEvents': 'Żadne nowe zdarzenie nie zostało dodane podczas ostatniej detekcji.',
  'corporateActions.addManually': 'Dodaj ręcznie',
  'corporateActions.selectInstrument': 'Wybierz instrument…',
  'corporateActions.newShares': 'Nowe akcje',
  'corporateActions.oldShares': 'Stare akcje',
  'corporateActions.empty': 'Nie zarejestrowano jeszcze żadnego podziału.',
  'corporateActions.instrument': 'Instrument',
  'corporateActions.type': 'Typ',
  'corporateActions.date': 'Data wejścia w życie',
  'corporateActions.ratio': 'Stosunek',
  'corporateActions.source': 'Źródło',
  'corporateActions.priceHistoryStatus': 'Historia cen',
  'corporateActions.type.split': 'Podział',
  'corporateActions.type.reverse_split': 'Scalenie (reverse split)',
  'corporateActions.source.fmp': 'FMP (automatycznie)',
  'corporateActions.source.eodhd': 'EODHD (na żądanie)',
  'corporateActions.source.yahoo': 'Yahoo (automatycznie)',
  'corporateActions.source.alpha_vantage': 'Alpha Vantage (automatycznie)',
  'corporateActions.source.polygon': 'Polygon (automatycznie)',
  'corporateActions.source.manual': 'Wpis ręczny',
  'corporateActions.confidence': 'Zaufanie',
  'corporateActions.details': 'Szczegóły',
  'corporateActions.status.raw': 'Korygowane przy odczycie',
  'corporateActions.status.already_adjusted': 'Już skorygowane przez dostawcę',
  'corporateActions.status.not_applicable': 'Brak historii w pamięci podręcznej do sprawdzenia',
  'corporateActions.status.unknown': 'Nieokreślone',
  'corporateActions.detectOne.title': 'Sprawdź instrument w innym źródle',
  'corporateActions.detectOne.description':
    'Użyj tej jednorazowej kontroli, gdy instrument wymaga dodatkowego sprawdzenia. Zapytanie trafia do EODHD dla wybranego instrumentu i zużywa jego limit zapytań.',
  'corporateActions.detectOne.button': 'Sprawdź w EODHD',
  'corporateActions.detectOne.created': {
    one: 'Zarejestrowano 1 operację kapitałową przez EODHD.',
    other: 'Zarejestrowano {count} operacji kapitałowych przez EODHD.',
  },
  'corporateActions.detectOne.alreadyKnown': 'Już znane — EODHD nie zwróciło nic nowego.',
  'corporateActions.detectOne.noEvents': 'EODHD nie zwróciło żadnej operacji kapitałowej dla tego instrumentu.',
  'corporateActions.detectOne.failed': 'Nie udało się sprawdzić tego instrumentu w EODHD.',

  // --- Panel szczegółów pozycji ------------------------------------------------
  'positionDetail.summary': 'Podsumowanie',
  'positionDetail.allocation': 'Alokacja',
  'positionDetail.categoryShare': 'Udział w tej klasie aktywów',
  'positionDetail.noAllocationData': 'Brak danych o alokacji dla tej pozycji.',
  'positionDetail.analysis': 'Analiza',
  'positionDetail.noScoreData': 'Brak jeszcze wyniku dla tego instrumentu.',
  'positionDetail.income': 'Przychody',
  'positionDetail.loadError': 'Nie udało się wczytać tej sekcji.',
  'positionDetail.history': 'Historia',
  'positionDetail.openLots': 'Otwarte loty',
  'positionDetail.noLots': 'Brak zarejestrowanych lotów.',
  'positionDetail.lotOpenedAt': 'Otwarto',
  'positionDetail.closedLots': 'Zamknięte loty',
  'positionDetail.lotClosedAt': 'Zamknięto',
  'positionDetail.closePrice': 'Cena zamknięcia',
  'positionDetail.relatedTransactions': 'Powiązane transakcje',
  'positionDetail.noTransactions': 'Brak zarejestrowanych transakcji.',
  'positionDetail.dataQuality': 'Jakość danych',
  'positionDetail.priceStatus': 'Status ceny',
  'positionDetail.verifiedProvider': 'Zweryfikowano przez',
  'positionDetail.mappingStatus': 'Mapowanie symbolu',
  'positionDetail.mappingStatusValue.RESOLVED': 'Rozwiązane automatycznie, nigdy nie testowane',
  'positionDetail.mappingStatusValue.VERIFIED': 'Zweryfikowane — dostawca zwrócił dane',
  'positionDetail.mappingStatusValue.MANUAL': 'Poprawione ręcznie',
  'positionDetail.mappingStatusValue.UNRESOLVED': 'Nierozwiązane',
  'positionDetail.notPriceableReason': 'Niewyceniane, ponieważ',
  'positionDetail.notPriceableReasonValue.corporate_action':
    'Pozostałość po operacji kapitałowej (prawo, ułamek po scaleniu…) — ten instrument nigdy nie będzie notowany.',
  'positionDetail.notPriceableReasonValue.unknown': 'Ten instrument nie jest wyceniany, bez dokładnie określonej przyczyny.',
  'positionDetail.notPriceableReasonValue.p2p_aggregate':
    'Agregat pożyczek P2P Mintos — dziesiątki fragmentów pożyczek bez indywidualnej wyceny, wartościowane wyłącznie jako jedno łączne saldo zadeklarowane przez Mintos.',
  'positionDetail.notPriceableReasonValue.employee_savings_fund':
    'Fundusz oszczędności pracowniczej Amundi — brak notowania rynkowego, jego wartość pochodzi wyłącznie z rocznego wyciągu Amundi.',
}

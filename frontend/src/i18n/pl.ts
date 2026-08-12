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
  'nav.watchlist': 'Obserwowane',
  'nav.gems': 'Perełki',
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
  'common.loading': 'Ładowanie…',
  'common.notComputable': 'nie do obliczenia',
  'common.none': '—',

  // --- Portfolio page ------------------------------------------------------
  'portfolio.title': 'Portfel',
  'portfolio.subtitle': 'Posiadane pozycje i wynik niezrealizowany.',
  'portfolio.lastImport': 'Ostatni import: {date}.',
  'portfolio.openPositions': 'Pozycje otwarte',

  'totals.positions': 'Pozycje',
  'totals.marketValue': 'Wartość rynkowa ({currency})',
  'totals.unrealized': 'Wynik niezrealizowany ({currency})',
  'totals.performance': 'Stopa zwrotu',
  'totals.incomplete': {
    one: '{count} pozycja nie ma wyceny — zwykle wpisana ręcznie. Jest wyłączona z sum zamiast liczona jako zero, co dałoby błędną sumę wyglądającą na poprawną. Ceny rynkowe pojawią się w kolejnym etapie projektu.',
    few: '{count} pozycje nie mają wyceny — zwykle wpisane ręcznie. Są wyłączone z sum zamiast liczone jako zero, co dałoby błędną sumę wyglądającą na poprawną. Ceny rynkowe pojawią się w kolejnym etapie projektu.',
    many: '{count} pozycji nie ma wyceny — zwykle wpisanych ręcznie. Są wyłączone z sum zamiast liczone jako zero, co dałoby błędną sumę wyglądającą na poprawną. Ceny rynkowe pojawią się w kolejnym etapie projektu.',
  },

  'accounts.title': 'Według rachunku',
  'accounts.account': 'Rachunek',
  'accounts.positions': 'Pozycje',
  'accounts.invested': 'Zainwestowano',
  'accounts.value': 'Wartość',
  'accounts.unrealized': 'Niezrealizowany',
  'accounts.performance': 'Zwrot',

  // --- Import panel --------------------------------------------------------
  'import.title': 'Zaimportuj wyciąg XTB',
  'import.instructions':
    'W xStation: Account history → Export → okres „All”, format Excel. XTB wyłączyło swoje API 14 marca 2025 roku, więc eksport pliku to jedyny pewny sposób pobrania pozycji. Aplikacja nie prosi o żadne dane logowania ani ich nie przechowuje.',
  'import.multiAccount':
    'Jeden eksport obejmuje tylko jeden rachunek. Jeśli masz ich kilka (na przykład maklerski i PEA), wyeksportuj je osobno i zaimportuj oba pliki: współistnieją, nie nadpisując się wzajemnie.',
  'import.dropzone': 'Przeciągnij plik tutaj albo wskaż go ręcznie (.xlsx lub .csv)',
  'import.chooseFile': 'Wybierz plik',
  'import.importing': 'Importowanie…',
  'import.failed': 'Import nie powiódł się: {error}',
  'import.summary':
    '{filename} — pozycje otwarte: {positions}, wykryte operacje: {transactions}, w tym nowych: {inserted}.',
  'import.sectionsTitle': 'Arkusze wykryte w pliku',
  'import.sectionLine': '{sheet} → {count} × {kind} (wiersze źródłowe: {rows})',

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
  'table.mapping': 'Przypisanie',
  'table.quantity': 'Ilość',
  'table.avgPrice': 'Cena nabycia',
  'table.price': 'Kurs',
  'table.value': 'Wartość ({currency})',
  'table.unrealized': 'Niezrealizowany ({currency})',
  'table.performance': 'Zwrot',
  'table.since': 'Od',
  'table.account': 'Rachunek',
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
  'filters.sortBy': 'Sortuj według',
  'sort.value': 'Wartość rynkowa',
  'sort.unrealized': 'Wynik niezrealizowany',
  'sort.performance': 'Stopa zwrotu %',
  'sort.symbol': 'Symbol',

  // --- Prices ---------------------------------------------------------------
  'prices.title': 'Ceny rynkowe',
  'prices.subtitle':
    'Darmowi dostawcy mocno ograniczają liczbę zapytań, więc odświeżanie przetwarza listę w ramach budżetu czasu i pokazuje, ile zostało. Dane już zapisane nie są pobierane ponownie.',
  'prices.refresh': 'Odśwież ceny',
  'prices.refreshing': 'Odświeżanie…',
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
  'prices.noProvider': '{symbol}: brak dostępnego dostawcy danych.',
  'prices.failed': '{symbol}: pobieranie przez {provider} nie powiodło się.',
  'prices.budgetReached': 'Budżet czasu wyczerpany, pozostało instrumentów: {remaining}.',
  'prices.noFallbackConfigured':
    'Yahoo ogranicza zapytania, a żaden dostawca zapasowy nie jest skonfigurowany. Dodaj darmowy klucz TWELVEDATA_API_KEY do .env (rejestracja e-mailem, bez karty), aby odświeżanie działało dalej.',
  'table.trend': 'Trend (90 dni)',
  'mapping.verified': 'zweryfikowane',
  'mapping.verifiedTooltip': 'Dostawca zwrócił dane dla tego symbolu {date} ({provider}).',

  // --- Placeholder pages ---------------------------------------------------
  'watchlist.title': 'Obserwowane',
  'watchlist.description': 'Instrumenty obserwowane, ale nieposiadane, oraz moment wejścia.',
  'gems.title': 'Perełki',
  'gems.description': 'Szukanie obiecujących spółek przez filtrowanie uniwersum indeksów.',
  'placeholder.comingIn': 'Ta strona pojawi się w {phase} projektu.',
  'phase.4': 'etapie 4',
  'phase.5': 'etapie 5',
}

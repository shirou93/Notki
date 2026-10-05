/* Shared translation layer for Notki: dictionaries, language persistence and DOM translation. */
(() => {
  const STORAGE_KEY = 'notki.lang.v1';
  const FALLBACK_LANGUAGE = 'en';
  const SUPPORTED_LANGUAGES = ['pl', 'en'];
  const HTML_LANGUAGES = { pl: 'pl', en: 'en' };

  const DICTIONARIES = {
    pl: {
      'meta.title': 'Notki — Twój notatnik',
      'meta.description': 'Notki — prywatny notatnik w przeglądarce.',
      'meta.adminTitle': 'Panel administracyjny — Notki',
      'meta.setupTitle': 'Pierwsza konfiguracja — Notki',
      'language.label': 'Język',
      'language.switch': 'Zmień język',
      'brand.aria': 'Notki',
      'brand.homeAria': 'Notki, wszystkie notatki',
      'brand.adminAria': 'Notki, wróć do notatek',

      'auth.eyebrow': 'NOTATKI PRYWATNE',
      'auth.heading.login': 'Zaloguj się',
      'auth.heading.register': 'Utwórz konto',
      'auth.description.login': 'Zaloguj się na swoje konto, aby otworzyć notatki.',
      'auth.description.register': 'Utwórz konto, korzystając z zaproszenia administratora.',
      'auth.switch.login': 'Masz zaproszenie? Utwórz konto',
      'auth.switch.register': 'Masz już konto? Zaloguj się',
      'auth.email': 'E-MAIL',
      'auth.password': 'HASŁO',
      'auth.confirmPassword': 'POWTÓRZ HASŁO',
      'auth.submit.login': 'Zaloguj się',
      'auth.submit.register': 'Utwórz konto',
      'auth.passwordMismatch': 'Hasła nie są takie same.',
      'auth.connectionFailed': 'Nie można połączyć się z serwerem. Uruchom go poleceniem „python server.py”. {message}',
      'auth.migrateConfirm': 'Przenieść {count} lokalnych notatek do konta {email}?',

      'nav.aria': 'Nawigacja',
      'nav.viewsAria': 'Widoki notatek',
      'nav.all': 'Wszystkie',
      'nav.pinned': 'Przypięte',
      'nav.archive': 'Archiwum',
      'nav.trash': 'Kosz',
      'nav.newNote': 'Nowa notatka',
      'nav.adminPanel': 'Panel administracyjny',
      'nav.storage': 'Zapisane na serwerze',

      'view.all': 'Wszystkie notatki',
      'view.pinned': 'Przypięte',
      'view.archive': 'Archiwum',
      'view.trash': 'Kosz',

      'topbar.breadcrumb': 'TWÓJ NOTATNIK',
      'topbar.search': 'Szukaj w notatkach',
      'topbar.theme.enableDark': 'Włącz ciemny motyw',
      'topbar.theme.enableLight': 'Włącz jasny motyw',
      'topbar.settings': 'Ustawienia',
      'topbar.account': 'KONTO',
      'topbar.logout': 'Wyloguj',
      'topbar.profile': 'Profil lokalny',
      'topbar.accountAria': 'Konto {email}',
      'topbar.profileMenu': 'Profil',
      'topbar.profileTitle': 'Profil',
      'topbar.profileDescription': 'Zmień język interfejsu lub hasło do swojego konta.',
      'topbar.language': 'JĘZYK',
      'topbar.changePassword': 'ZMIANA HASŁA',
      'topbar.currentPassword': 'AKTUALNE HASŁO',
      'topbar.newPassword': 'NOWE HASŁO',
      'topbar.confirmPassword': 'POWTÓRZ NOWE HASŁO',
      'topbar.passwordHint': 'Minimum 12 znaków.',
      'topbar.passwordMismatch': 'Nowe hasła nie są takie same.',
      'topbar.passwordChanged': 'Hasło zostało zmienione.',
      'topbar.passwordChangeFailed': 'Nie udało się zmienić hasła: {message}',
      'topbar.close': 'Zamknij',

      'page.countLabel': 'TWÓJ SPOKÓJ, TWOJE NOTATKI',
      'page.addNote': 'Dodaj notatkę',
      'capture.aria': 'Szybka notatka',
      'capture.placeholder': 'Zapisz myśl, zanim ucieknie...',
      'section.pinned': 'PRZYPIĘTE',
      'section.other': 'POZOSTAŁE',
      'count.searchResults': '{count} WYNIKÓW WYSZUKIWANIA',
      'count.notesLabel.one': 'NOTATKA',
      'count.notesLabel.few': 'NOTATKI',
      'count.notesLabel.many': 'NOTATEK',
      'count.notesLabel.other': 'NOTATEK',
      'footer.count.one': 'notatka',
      'footer.count.few': 'notatki',
      'footer.count.many': 'notatek',
      'footer.count.other': 'notatek',
      'footer.privacy': 'Twoje pomysły są tylko Twoje.',

      'shared.kicker': 'NOTATKA OD KOGOŚ',
      'shared.title': 'Udostępniona notatka',
      'shared.dismiss': 'Odrzuć',
      'shared.save': 'Zapisz u siebie',
      'shared.copied': 'Link skopiowany. Każda osoba z linkiem zobaczy tę kopię notatki.',
      'shared.copyFailed': 'Nie udało się skopiować linku. Sprawdź uprawnienia schowka przeglądarki.',
      'shared.invalid': 'Ten link nie zawiera prawidłowej notatki.',
      'shared.saved': 'Udostępniona notatka zapisana u Ciebie.',

      'empty.all.title': 'Tu zaczyna się dobra myśl.',
      'empty.all.copy': 'Zapisz pierwszą notatkę. Będzie czekać na Ciebie właśnie tutaj.',
      'empty.pinned.title': 'Nic tu jeszcze nie ma.',
      'empty.pinned.copy': 'Przypnij ważną notatkę, aby mieć ją zawsze pod ręką.',
      'empty.archive.title': 'Archiwum jest puste.',
      'empty.archive.copy': 'Zarchiwizowane notatki pojawią się właśnie tutaj.',
      'empty.trash.title': 'Kosz jest pusty.',
      'empty.trash.copy': 'Usunięte notatki będą tu dostępne, dopóki nie usuniesz ich na stałe.',
      'empty.search.title': 'Nie znaleziono notatek.',
      'empty.search.copy': 'Spróbuj innego tytułu, fragmentu treści albo etykiety.',
      'empty.create': '+ Napisz pierwszą notatkę',

      'editor.close': 'Zamknij edytor',
      'editor.closeTitle': 'Zamknij',
      'editor.saved': 'Zapisano',
      'editor.saving': 'Zapisywanie',
      'editor.pin': 'Przypnij notatkę',
      'editor.unpin': 'Odepnij notatkę',
      'editor.pinTitle': 'Przypnij',
      'editor.unpinTitle': 'Odepnij',
      'editor.archive': 'Archiwizuj notatkę',
      'editor.unarchive': 'Przywróć z archiwum',
      'editor.restoreTrash': 'Przywróć z kosza',
      'editor.archiveTitle': 'Archiwizuj',
      'editor.unarchiveTitle': 'Przywróć',
      'editor.share': 'Udostępnij notatkę',
      'editor.shareTitle': 'Udostępnij link',
      'editor.delete': 'Przenieś do kosza',
      'editor.deleteForever': 'Usuń trwale',
      'editor.titleLabel': 'Tytuł notatki',
      'editor.titlePlaceholder': 'Tytuł',
      'editor.bodyLabel': 'Treść notatki',
      'editor.toolbar': 'Formatowanie notatki',
      'editor.bold': 'Pogrubienie',
      'editor.italic': 'Kursywa',
      'editor.underline': 'Podkreślenie',
      'editor.bulletList': 'Lista punktowana',
      'editor.numberedList': 'Lista numerowana',
      'editor.checklist': 'Dodaj checkbox',
      'editor.clearFormat': 'Wyczyść formatowanie',
      'editor.bodyPlaceholder': 'Zacznij pisać...',
      'editor.tags': 'ETYKIETY',
      'editor.tagsPlaceholder': 'np. praca, pomysły',
      'editor.color': 'KOLOR NOTATKI',
      'editor.colorGroup': 'Kolor notatki',
      'editor.color.default': 'Domyślny',
      'editor.color.mint': 'Miętowy',
      'editor.color.lemon': 'Cytrynowy',
      'editor.color.peach': 'Brzoskwiniowy',
      'editor.color.lilac': 'Lawendowy',
      'editor.color.sky': 'Błękitny',
      'editor.privacy': 'Ta notatka jest prywatna, dopóki jej nie udostępnisz.',
      'editor.created': 'Utworzono {date}',
      'editor.words.one': 'słowo',
      'editor.words.few': 'słowa',
      'editor.words.many': 'słów',
      'editor.words.other': 'słów',
      'editor.untitled': 'Bez tytułu',
      'editor.emptyNote': 'Pusta notatka',
      'editor.checkboxAria': 'Oznacz zadanie jako wykonane',
      'editor.taskGroup': 'Zaznaczone',
      'editor.taskAlreadyDone': 'To zadanie jest już zaznaczone:',
      'editor.taskRestore': 'Przywróć „{title}”',
      'editor.archivedToast': 'Notatka przeniesiona do archiwum.',
      'editor.unarchivedToast': 'Notatka przywrócona z archiwum.',
      'editor.trashedToast': 'Notatka przeniesiona do kosza.',
      'editor.restoredToast': 'Notatka przywrócona z kosza.',
      'editor.deletedToast': 'Notatka usunięta na stałe.',
      'editor.saveFailed': 'Nie udało się zapisać notatek: {message}',

      'card.drag': 'Zmień kolejność notatki',
      'card.dragTitle': 'Przeciągnij, aby zmienić kolejność',

      'date.today': 'Dziś, {time}',
      'error.server': 'Wystąpił błąd serwera.',

      'admin.back': 'Do notatek',
      'admin.logout': 'Wyloguj',
      'admin.eyebrow': 'ZARZĄDZANIE SERWEREM',
      'admin.heading': 'Panel administracyjny',
      'admin.statsAria': 'Statystyki serwera',
      'admin.stats.users': 'Użytkownicy',
      'admin.stats.notes': 'Notatki razem',
      'admin.stats.active': 'Aktywne',
      'admin.stats.archived': 'Archiwum',
      'admin.stats.trash': 'Kosz',
      'admin.stats.pendingInvites': 'Oczekujące zaproszenia',
      'admin.backups.title': 'Backupy całego serwera',
      'admin.backups.description': 'Archiwa zawierają konta, notatki i zaproszenia. Sesje nie są zapisywane.',
      'admin.backups.create': '+ Utwórz backup .tgz',
      'admin.backups.creating': 'Tworzenie backupu serwera...',
      'admin.backups.created': 'Zapisano backup {filename} na serwerze. Archiwum zawiera hashe haseł; ogranicz do niego dostęp.',
      'admin.backups.empty': 'Brak zapisanych backupów.',
      'admin.backups.download': 'Pobierz ten backup',
      'admin.backups.restore': 'Przywróć ten backup',
      'admin.backups.delete': 'Usuń ten backup',
      'admin.backups.downloadFailed': 'Nie udało się pobrać backupu.',
      'admin.backups.confirmRestore': 'Przywrócić {filename}? Zastąpi to wszystkie konta, notatki i zaproszenia. Wszyscy użytkownicy zostaną wylogowani.',
      'admin.backups.confirmDelete': 'Usunąć backup {filename}? Tej operacji nie można cofnąć.',
      'admin.backups.deleted': 'Usunięto {filename}.',
      'admin.table.file': 'PLIK',
      'admin.table.created': 'UTWORZONO',
      'admin.table.size': 'ROZMIAR',
      'admin.table.actions': 'AKCJE',
      'admin.users.title': 'Użytkownicy',
      'admin.users.description': 'Lista kont i liczba przypisanych notatek.',
      'admin.table.email': 'E-MAIL',
      'admin.table.role': 'ROLA',
      'admin.table.notes': 'NOTATKI',
      'admin.role.admin': 'Administrator',
      'admin.role.user': 'Użytkownik',
      'admin.invites.title': 'Zaproszenia',
      'admin.invites.description': 'Link rejestracyjny jest jednorazowy i wygasa po 7 dniach.',
      'admin.invites.create': '+ Utwórz zaproszenie',
      'admin.invites.link': 'LINK DO REJESTRACJI',
      'admin.invites.copy': 'Kopiuj link',
      'admin.invites.copied': 'Skopiowano',
      'admin.invites.expiry': 'Link jest ważny do {date}.',
      'admin.table.expires': 'WYGASA',
      'admin.table.status': 'STATUS',
      'admin.invites.used': 'Wykorzystane',
      'admin.invites.expired': 'Wygasłe',
      'admin.invites.pending': 'Oczekujące',
      'admin.error.server': 'Błąd serwera.',

      'setup.eyebrow': 'PIERWSZE URUCHOMIENIE',
      'setup.heading': 'Utwórz administratora',
      'setup.description': 'To konto będzie zarządzać użytkownikami, zaproszeniami i statystykami serwera.',
      'setup.snapshotHeading': 'MASZ BACKUP SERWERA?',
      'setup.snapshotHint': 'Import zastępuje tę pustą instalację kontami, notatkami i zaproszeniami z backupu. Po imporcie zaloguj się danymi z archiwum.',
      'setup.snapshotLabel': 'ARCHIWUM BACKUPU (.TGZ)',
      'setup.snapshotImport': 'Importuj backup',
      'setup.divider': 'albo utwórz nowe konto administratora',
      'setup.passwordHint': 'Minimum 12 znaków.',
      'setup.submit': 'Utwórz konto administratora',
      'setup.passwordMismatch': 'Hasła nie są takie same.',
      'setup.importTooLarge': 'Snapshot przekracza limit 100 MB.',
      'setup.importInvalidJson': 'Plik nie zawiera poprawnego JSON-u.',
      'setup.importFailed': 'Nie udało się przywrócić backupu.',
      'setup.importRestored': 'Backup przywrócony. Przekierowuję do logowania.',
      'setup.connectionFailed': 'Nie udało się połączyć z serwerem.',
    },
    en: {
      'meta.title': 'Notki — Your notebook',
      'meta.description': 'Notki — a private notebook in your browser.',
      'meta.adminTitle': 'Admin panel — Notki',
      'meta.setupTitle': 'First-time setup — Notki',
      'language.label': 'Language',
      'language.switch': 'Change language',
      'brand.aria': 'Notki',
      'brand.homeAria': 'Notki, all notes',
      'brand.adminAria': 'Notki, back to notes',

      'auth.eyebrow': 'PRIVATE NOTES',
      'auth.heading.login': 'Sign in',
      'auth.heading.register': 'Create account',
      'auth.description.login': 'Sign in to your account to open your notes.',
      'auth.description.register': 'Create an account using the administrator’s invitation.',
      'auth.switch.login': 'Have an invitation? Create an account',
      'auth.switch.register': 'Already have an account? Sign in',
      'auth.email': 'E-MAIL',
      'auth.password': 'PASSWORD',
      'auth.confirmPassword': 'CONFIRM PASSWORD',
      'auth.submit.login': 'Sign in',
      'auth.submit.register': 'Create account',
      'auth.passwordMismatch': 'Passwords do not match.',
      'auth.connectionFailed': 'Cannot connect to the server. Start it with “python server.py”. {message}',
      'auth.migrateConfirm': 'Move {count} local notes to the account {email}?',

      'nav.aria': 'Navigation',
      'nav.viewsAria': 'Note views',
      'nav.all': 'All',
      'nav.pinned': 'Pinned',
      'nav.archive': 'Archive',
      'nav.trash': 'Trash',
      'nav.newNote': 'New note',
      'nav.adminPanel': 'Admin panel',
      'nav.storage': 'Saved on the server',

      'view.all': 'All notes',
      'view.pinned': 'Pinned',
      'view.archive': 'Archive',
      'view.trash': 'Trash',

      'topbar.breadcrumb': 'YOUR NOTEBOOK',
      'topbar.search': 'Search notes',
      'topbar.theme.enableDark': 'Enable dark theme',
      'topbar.theme.enableLight': 'Enable light theme',
      'topbar.settings': 'Settings',
      'topbar.account': 'ACCOUNT',
      'topbar.logout': 'Sign out',
      'topbar.profile': 'Local profile',
      'topbar.accountAria': 'Account {email}',
      'topbar.profileMenu': 'Profile',
      'topbar.profileTitle': 'Profile',
      'topbar.profileDescription': 'Change the interface language or your account password.',
      'topbar.language': 'LANGUAGE',
      'topbar.changePassword': 'CHANGE PASSWORD',
      'topbar.currentPassword': 'CURRENT PASSWORD',
      'topbar.newPassword': 'NEW PASSWORD',
      'topbar.confirmPassword': 'CONFIRM NEW PASSWORD',
      'topbar.passwordHint': 'At least 12 characters.',
      'topbar.passwordMismatch': 'The new passwords do not match.',
      'topbar.passwordChanged': 'The password has been changed.',
      'topbar.passwordChangeFailed': 'Could not change the password: {message}',
      'topbar.close': 'Close',

      'page.countLabel': 'YOUR CALM, YOUR NOTES',
      'page.addNote': 'Add a note',
      'capture.aria': 'Quick note',
      'capture.placeholder': 'Save the thought before it escapes...',
      'section.pinned': 'PINNED',
      'section.other': 'OTHER',
      'count.searchResults': '{count} SEARCH RESULTS',
      'count.notesLabel.one': 'NOTE',
      'count.notesLabel.other': 'NOTES',
      'footer.count.one': 'note',
      'footer.count.other': 'notes',
      'footer.privacy': 'Your ideas stay yours.',

      'shared.kicker': 'A NOTE FROM SOMEONE',
      'shared.title': 'Shared note',
      'shared.dismiss': 'Dismiss',
      'shared.save': 'Save to my notes',
      'shared.copied': 'Link copied. Anyone with the link will see this copy of the note.',
      'shared.copyFailed': 'Could not copy the link. Check your browser’s clipboard permissions.',
      'shared.invalid': 'This link does not contain a valid note.',
      'shared.saved': 'Shared note saved to your account.',

      'empty.all.title': 'A good thought starts here.',
      'empty.all.copy': 'Write your first note. It will be waiting for you right here.',
      'empty.pinned.title': 'Nothing here yet.',
      'empty.pinned.copy': 'Pin an important note to always keep it at hand.',
      'empty.archive.title': 'The archive is empty.',
      'empty.archive.copy': 'Archived notes will show up right here.',
      'empty.trash.title': 'The trash is empty.',
      'empty.trash.copy': 'Deleted notes stay here until you remove them for good.',
      'empty.search.title': 'No notes found.',
      'empty.search.copy': 'Try another title, a snippet of the body, or a tag.',
      'empty.create': '+ Write your first note',

      'editor.close': 'Close editor',
      'editor.closeTitle': 'Close',
      'editor.saved': 'Saved',
      'editor.saving': 'Saving',
      'editor.pin': 'Pin note',
      'editor.unpin': 'Unpin note',
      'editor.pinTitle': 'Pin',
      'editor.unpinTitle': 'Unpin',
      'editor.archive': 'Archive note',
      'editor.unarchive': 'Restore from archive',
      'editor.restoreTrash': 'Restore from trash',
      'editor.archiveTitle': 'Archive',
      'editor.unarchiveTitle': 'Restore',
      'editor.share': 'Share note',
      'editor.shareTitle': 'Share link',
      'editor.delete': 'Move to trash',
      'editor.deleteForever': 'Delete permanently',
      'editor.titleLabel': 'Note title',
      'editor.titlePlaceholder': 'Title',
      'editor.bodyLabel': 'Note body',
      'editor.toolbar': 'Note formatting',
      'editor.bold': 'Bold',
      'editor.italic': 'Italic',
      'editor.underline': 'Underline',
      'editor.bulletList': 'Bulleted list',
      'editor.numberedList': 'Numbered list',
      'editor.checklist': 'Add checkbox',
      'editor.clearFormat': 'Clear formatting',
      'editor.bodyPlaceholder': 'Start writing...',
      'editor.tags': 'TAGS',
      'editor.tagsPlaceholder': 'e.g. work, ideas',
      'editor.color': 'NOTE COLOR',
      'editor.colorGroup': 'Note color',
      'editor.color.default': 'Default',
      'editor.color.mint': 'Mint',
      'editor.color.lemon': 'Lemon',
      'editor.color.peach': 'Peach',
      'editor.color.lilac': 'Lilac',
      'editor.color.sky': 'Sky',
      'editor.privacy': 'This note stays private until you share it.',
      'editor.created': 'Created {date}',
      'editor.words.one': 'word',
      'editor.words.other': 'words',
      'editor.untitled': 'Untitled',
      'editor.emptyNote': 'Empty note',
      'editor.checkboxAria': 'Mark task as done',
      'editor.taskGroup': 'Completed',
      'editor.taskAlreadyDone': 'This task is already completed:',
      'editor.taskRestore': 'Restore “{title}”',
      'editor.archivedToast': 'Note moved to the archive.',
      'editor.unarchivedToast': 'Note restored from the archive.',
      'editor.trashedToast': 'Note moved to the trash.',
      'editor.restoredToast': 'Note restored from the trash.',
      'editor.deletedToast': 'Note deleted permanently.',
      'editor.saveFailed': 'Could not save notes: {message}',

      'card.drag': 'Reorder note',
      'card.dragTitle': 'Drag to reorder',

      'date.today': 'Today, {time}',
      'error.server': 'A server error occurred.',

      'admin.back': 'Back to notes',
      'admin.logout': 'Sign out',
      'admin.eyebrow': 'SERVER MANAGEMENT',
      'admin.heading': 'Admin panel',
      'admin.statsAria': 'Server statistics',
      'admin.stats.users': 'Users',
      'admin.stats.notes': 'Notes total',
      'admin.stats.active': 'Active',
      'admin.stats.archived': 'Archive',
      'admin.stats.trash': 'Trash',
      'admin.stats.pendingInvites': 'Pending invitations',
      'admin.backups.title': 'Server-wide backups',
      'admin.backups.description': 'Archives contain accounts, notes, and invitations. Sessions are not saved.',
      'admin.backups.create': '+ Create .tgz backup',
      'admin.backups.creating': 'Creating a server backup...',
      'admin.backups.created': 'Saved backup {filename} on the server. The archive contains password hashes; keep it restricted.',
      'admin.backups.empty': 'No saved backups.',
      'admin.backups.download': 'Download this backup',
      'admin.backups.restore': 'Restore this backup',
      'admin.backups.delete': 'Delete this backup',
      'admin.backups.downloadFailed': 'Could not download the backup.',
      'admin.backups.confirmRestore': 'Restore {filename}? This replaces every account, note, and invitation. All users will be signed out.',
      'admin.backups.confirmDelete': 'Delete backup {filename}? This cannot be undone.',
      'admin.backups.deleted': 'Deleted {filename}.',
      'admin.table.file': 'FILE',
      'admin.table.created': 'CREATED',
      'admin.table.size': 'SIZE',
      'admin.table.actions': 'ACTIONS',
      'admin.users.title': 'Users',
      'admin.users.description': 'Account list with the number of assigned notes.',
      'admin.table.email': 'E-MAIL',
      'admin.table.role': 'ROLE',
      'admin.table.notes': 'NOTES',
      'admin.role.admin': 'Administrator',
      'admin.role.user': 'User',
      'admin.invites.title': 'Invitations',
      'admin.invites.description': 'A registration link works once and expires after seven days.',
      'admin.invites.create': '+ Create invitation',
      'admin.invites.link': 'REGISTRATION LINK',
      'admin.invites.copy': 'Copy link',
      'admin.invites.copied': 'Copied',
      'admin.invites.expiry': 'The link is valid until {date}.',
      'admin.table.expires': 'EXPIRES',
      'admin.table.status': 'STATUS',
      'admin.invites.used': 'Used',
      'admin.invites.expired': 'Expired',
      'admin.invites.pending': 'Pending',
      'admin.error.server': 'Server error.',

      'setup.eyebrow': 'FIRST RUN',
      'setup.heading': 'Create the administrator',
      'setup.description': 'This account will manage users, invitations, and server statistics.',
      'setup.snapshotHeading': 'HAVE A SERVER BACKUP?',
      'setup.snapshotHint': 'Import replaces this empty installation with the accounts, notes, and invitations from the backup. Afterwards, sign in with the credentials from the archive.',
      'setup.snapshotLabel': 'BACKUP ARCHIVE (.TGZ)',
      'setup.snapshotImport': 'Import backup',
      'setup.divider': 'or create a new administrator account',
      'setup.passwordHint': 'At least 12 characters.',
      'setup.submit': 'Create administrator account',
      'setup.passwordMismatch': 'Passwords do not match.',
      'setup.importTooLarge': 'The snapshot exceeds the 100 MB limit.',
      'setup.importInvalidJson': 'The file is not valid JSON.',
      'setup.importFailed': 'Could not restore the backup.',
      'setup.importRestored': 'Backup restored. Redirecting to sign-in.',
      'setup.connectionFailed': 'Could not connect to the server.',
    },
  };

  const listeners = new Set();

  function normalizeLanguage(value) {
    const tag = String(value || '').trim().toLowerCase().split('-')[0];
    return SUPPORTED_LANGUAGES.includes(tag) ? tag : '';
  }

  function detectLanguage() {
    const stored = normalizeLanguage(window.localStorage?.getItem(STORAGE_KEY));
    if (stored) return stored;
    return normalizeLanguage(window.navigator?.language) || FALLBACK_LANGUAGE;
  }

  let language = detectLanguage();

  function dictionary(lang = language) {
    return DICTIONARIES[lang] || DICTIONARIES[FALLBACK_LANGUAGE];
  }

  function lookup(key, lang) {
    const active = dictionary(lang);
    if (key in active) return active[key];
    const fallback = DICTIONARIES[FALLBACK_LANGUAGE];
    return key in fallback ? fallback[key] : key;
  }

  function interpolate(template, params) {
    if (!params) return template;
    return template.replace(/\{(\w+)\}/g, (match, name) => (
      Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match
    ));
  }

  function t(key, params) {
    return interpolate(lookup(key), params);
  }

  function pluralKey(key, count) {
    const category = new Intl.PluralRules(language).select(count);
    for (const candidate of [`${key}.${category}`, `${key}.other`, `${key}.many`, `${key}.few`, `${key}.one`]) {
      if (lookup(candidate, language) !== candidate) return candidate;
    }
    return key;
  }

  function plural(key, count, params) {
    return t(pluralKey(key, count), { count, ...params });
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    const today = new Date();
    if (date.toDateString() === today.toDateString()) {
      return t('date.today', { time: new Intl.DateTimeFormat(HTML_LANGUAGES[language], { hour: '2-digit', minute: '2-digit' }).format(date) });
    }
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { day: 'numeric', month: 'short' }).format(date);
  }

  function formatFullDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
  }

  function formatDateTime(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '—';
    return new Intl.DateTimeFormat(HTML_LANGUAGES[language], { dateStyle: 'medium', timeStyle: 'short' }).format(date);
  }

  function formatNumber(value, options) {
    return new Intl.NumberFormat(HTML_LANGUAGES[language], options).format(value);
  }

  function getLanguage() {
    return language;
  }

  function setLanguage(next, { persist = true } = {}) {
    const resolved = normalizeLanguage(next) || FALLBACK_LANGUAGE;
    if (persist) window.localStorage?.setItem(STORAGE_KEY, resolved);
    const changed = resolved !== language;
    language = resolved;
    document.documentElement.lang = HTML_LANGUAGES[language];
    document.documentElement.dataset.lang = language;
    syncLanguageControls();
    applyTranslations();
    if (changed) listeners.forEach(listener => listener(language));
  }

  function applyAttribute(root, selector, attribute, key) {
    root.querySelectorAll(selector).forEach(element => {
      element.setAttribute(attribute, t(key ?? element.getAttribute(`data-i18n-${attribute}`)));
    });
  }

  function applyTranslations(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(element => {
      element.textContent = t(element.dataset.i18n);
    });
    root.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
      element.setAttribute('placeholder', t(element.dataset.i18nPlaceholder));
    });
    root.querySelectorAll('[data-i18n-data-placeholder]').forEach(element => {
      element.setAttribute('data-placeholder', t(element.dataset.i18nDataPlaceholder));
    });
    root.querySelectorAll('[data-i18n-aria-label]').forEach(element => {
      element.setAttribute('aria-label', t(element.dataset.i18nAriaLabel));
    });
    root.querySelectorAll('[data-i18n-title]').forEach(element => {
      element.setAttribute('title', t(element.dataset.i18nTitle));
    });
    root.querySelectorAll('[data-i18n-content]').forEach(element => {
      element.setAttribute('content', t(element.dataset.i18nContent));
    });
  }

  function syncLanguageControls() {
    document.querySelectorAll('[data-language-select]').forEach(select => {
      select.value = language;
      select.setAttribute('aria-label', t('language.switch'));
      select.title = t('language.switch');
    });
  }

  function onChange(listener) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  }

  document.addEventListener('DOMContentLoaded', () => {
    setLanguage(language, { persist: false });
    document.querySelectorAll('[data-language-select]').forEach(select => {
      select.addEventListener('change', () => setLanguage(select.value));
    });
  });

  document.documentElement.lang = HTML_LANGUAGES[language];
  document.documentElement.dataset.lang = language;

  window.i18n = {
    t, plural, formatDate, formatFullDate, formatDateTime, formatNumber,
    getLanguage, setLanguage, applyTranslations, onChange,
    supportedLanguages: [...SUPPORTED_LANGUAGES],
  };
})();

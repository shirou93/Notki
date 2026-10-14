# Notki

Szybka, lekka i prywatna aplikacja webowa do robienia notatek w przeglądarce, napisana w czystym Pythonie (Python 3.9+) bez jakichkolwiek zewnętrznych zależności z PyPI.

![Główny widok notatek](docs/desktop_notes.png)

---

## 🚀 Kluczowe funkcje

- 📝 **Tworzenie i edycja notatek**: Formatowanie tekstu (pogrubienie, kursywa, podkreślenie), listy punktowane i numerowane oraz interaktywne listy zadań (checklisty).
- 🏷️ **Etykiety i organizacja**: System etykiet (tagów), przypinanie ważnych notatek, archiwizacja, kosz oraz dostosowywanie kolorów kart dla wygodnej organizacji.
- 🤝 **Udostępnianie notatek**: Bezpieczne udostępnianie notatek innym użytkownikom serwera w trybie tylko do odczytu lub z prawami do edycji.
- 📶 **Obsługa offline i synchronizacja**: Praca bez dostępu do sieci dzięki lokalnemu pamiętaniu danych w przeglądarce (`localStorage`) oraz automatycznej i ręcznej synchronizacji po powrocie połączenia.
- 👤 **Profil użytkownika i avatary**: Personalizacja konta i obsługa własnych avatarów.
- 🔐 **Zaawansowane bezpieczeństwo**:
  - Dwuetapowa weryfikacja (2FA) za pomocą aplikacji TOTP oraz kluczy sprzętowych / Passkeys (WebAuthn).
  - Możliwość wymuszenia 2FA dla wszystkich użytkowników przez administratora.
- 💾 **Kopie zapasowe JSON**: Tworzenie, pobieranie, przywracanie oraz import pełnych kopii zapasowych serwera w formacie `.json`.
- ⚙️ **Panel Administratora**: Zarządzanie użytkownikami, tworzenie linków zaproszeń (z konfigurowalnym czasem ważności w dniach), statystyki serwera oraz automatyczne aktualizacje bezpośrednio z serwisu GitHub.
- 🎨 **Motywy i wielojęzyczność (i18n)**: Wsparcie dla motywu jasnego, ciemnego oraz systemowego, a także obsługa wielu języków (polski, angielski, niemiecki, francuski, japoński, koreański, włoski, hiszpański).

---

## 📱 Zrzuty ekranu

| Widok | Komputer (Desktop) | Telefon (Mobile) |
|---|---|---|
| **Notatki** | ![Notatki na komputerze](docs/desktop_notes.png) | ![Notatki na telefonie](docs/mobile_notes.png) |
| **Panel Admina** | ![Panel administratora na komputerze](docs/desktop_admin.png) | ![Panel administratora na telefonie](docs/mobile_admin.png) |

---

## 🛠️ Zalecana instalacja (Docker Compose)

Najprostszym i zalecanym sposobem uruchomienia aplikacji Notki jest użycie **Docker Compose**.

1. Utwórz katalog i pobierz plik `docker-compose.yml`:
   ```bash
   mkdir notki && cd notki
   curl -O https://raw.githubusercontent.com/shirou93/Notki/main/docker-compose.yml
   ```

2. Uruchom kontener w tle:
   ```bash
   docker compose up -d
   ```

3. Otwórz przeglądarkę pod adresem `http://localhost:8000/setup` i przejdź pierwszą konfigurację konta administratora.

---

## 💻 Alternatywne metody instalacji

### 1. Bezpośrednie uruchomienie (Python 3.9+)

Aplikacja korzysta wyłącznie ze biblioteki standardowej Pythona i nie wymaga instalowania zewnętrznych pakietów przez `pip`.

```bash
git clone https://github.com/shirou93/Notki.git
cd Notki
python3 server.py
```
Aplikacja będzie dostępna pod adresem `http://localhost:8000`.

### 2. Instalacja na serwerze (Linux Systemd)

Na serwerze Linux (Debian, Ubuntu, Arch, Fedora, Alpine itp.) możesz skorzystać z automatycznego skryptu instalacyjnego:

```bash
sudo ./install.sh
```
Skrypt utworzy dedykowanego użytkownika systemowego `notki`, zainstaluje aplikację w `/opt/notki` oraz skonfiguruje i uruchomi usługę Systemd.

---

## 🛡️ Kopie zapasowe (JSON Backup)

W Panelu Administratora w sekcji **Kopie Zapasowe Serwera** możesz zarządzać kopiami danych:
- Kopie zapasowe obejmują konta użytkowników, notatki, etykiety, zaproszenia i ustawienia serwera.
- Pliki zapisywane są w czytelnym formacie `.json` z unikalnym znacznikiem czasu (np. `notki-backup-20261014-120000Z-a1b2c3d4.json`).
- Kopie zapasowe można w dowolnym momencie pobrać, przywrócić z listy serwera, wgrać z dysku lokalnego lub zaimportować podczas wstępnej konfiguracji na nowym serwerze.

---

## ⚙️ Zmienne środowiskowe

| Zmienna | Opis | Domyślna wartość |
|---|---|---|
| `NOTKI_HOST` | Adres IP, na którym nasłuchuje serwer | `127.0.0.1` (`0.0.0.0` w Dockerze) |
| `NOTKI_PORT` / `NOTKI_HTTP_PORT` | Port serwera HTTP | `8000` |
| `NOTKI_DB_PATH` | Ścieżka do pliku bazy danych SQLite3 | `./data/notki.sqlite3` |
| `NOTKI_BACKUP_DIR` | Ścieżka do katalogu z kopiami zapasowymi JSON | `./data/backups` |
| `NOTKI_ALLOW_REMOTE_SETUP` | Zezwolenie na pierwszą konfigurację z zdalnego adresu IP | `0` (`1` w Dockerze) |

> **Odwrotne proxy i HTTPS (Cloudflare Tunnel, Nginx, Caddy, Traefik, NPM):**
> Notki działają jako natywny serwer HTTP i automatycznie wykrywają nagłówki przekazywania HTTPS (`X-Forwarded-Proto`, `X-Forwarded-Host`) z Twojego odwrotnego proxy. Brak konieczności dodatkowej konfiguracji SSL wewnątrz aplikacji.

---

## 📜 Licencja

Projekt open-source udostępniany na licencji MIT.

# Notki

Szybki, lekki i prywatny notatnik w przeglądarce stworzony w czystym Pythonie (Python 3.9+) bez jakichkolwiek zewnętrznych zależności z pypiego.

![Widok główny notatek](docs/desktop_notes.png)

---

## 🚀 Główne funkcje

- 📝 **Tworzenie i edycja notatek**: Formatowanie tekstu, listy punktowane, numerowane oraz interaktywne checklisty (zadania).
- 📌 **Organizacja**: Przypinanie ważnych notatek, archiwizacja, etykiety oraz kolory dla łatwej kategoryzacji.
- 🤝 **Udostępnianie**: Bezpieczne udostępnianie notatek innym użytkownikom serwera z uprawnieniami do odczytu lub edycji.
- 🔐 **Bezpieczeństwo**:
  - Dwuetapowa weryfikacja 2FA (Aplikacje TOTP oraz Klucze zabezpieczeń Passkeys / WebAuthn).
  - Wymuszanie 2FA dla wszystkich użytkowników przez administratora.
- 💾 **Kopie zapasowe JSON**: Tworzenie, pobieranie, przywracanie i import pełnych kopii zapasowych w formacie `.json`.
- ⚙️ **Panel administracyjny**: Zarządzanie użytkownikami, zaproszeniami (z możliwością określenia liczby dni ważności linku), statystykami serwera oraz automatycznymi aktualizacjami z GitHub.
- 🎨 **Motywy i Języki**: Obsługa motywu jasnego, ciemnego i systemowego oraz obsługa języka polskiego i angielskiego.

---

## 📱 Zrzuty ekranu

| Widok | Desktop | Mobile |
|---|---|---|
| **Notatki** | ![Desktop Notatki](docs/desktop_notes.png) | ![Mobile Notatki](docs/mobile_notes.png) |
| **Panel Administratora** | ![Desktop Admin](docs/desktop_admin.png) | ![Mobile Admin](docs/mobile_admin.png) |

---

## 🛠️ Zalecana instalacja (Docker Compose)

Najprostszym i zalecanym sposobem uruchomienia Notek jest **Docker Compose**.

1. Utwórz katalog i pobierz plik `docker-compose.yml`:
   ```bash
   mkdir notki && cd notki
   curl -O https://raw.githubusercontent.com/shirou93/Notki/main/docker-compose.yml
   ```

2. Uruchom kontener:
   ```bash
   docker compose up -d
   ```

3. Otwórz przeglądarkę pod adresem: `http://localhost:8000/setup` i utwórz pierwsze konto administratora.

---

## 💻 Alternatywne metody instalacji

### 1. Uruchomienie bezpośrednie (Python 3.9+)

Aplikacja wykorzystuje wyłącznie bibliotekę standardową Pythona, dzięki czemu nie wymaga instalowania zewnętrznych pakietów pip.

```bash
git clone https://github.com/shirou93/Notki.git
cd Notki
python3 server.py
```
Otwórz przeglądarkę pod adresem: `http://localhost:8000`

### 2. Instalacja bare-metal (Linux Systemd)

Na serwerze Linux (Debian, Ubuntu, Arch, Fedora, Alpine) możesz skorzystać z gotowego skryptu instalacyjnego:

```bash
sudo ./install.sh
```
Skrypt utworzy użytkownika systemowego `notki`, zainstaluje aplikację w `/opt/notki` oraz skonfiguruje i uruchomi usługę Systemd.

---

## 🛡️ Kopie zapasowe (JSON)

W panelu administracyjnym w sekcji **Backupy całego serwera** możesz wygenerować pełną kopię zapasową serwera.
- Kopia zawiera konta, notatki, etykiety, zaproszenia i ustawienia.
- Pliki zapisywane są w formacie `.json` pod nazwą zawierającą datę i czas utworzenia backupu (np. `notki-backup-20261013-120000Z-a1b2c3d4.json`).
- Kopię zapasową można w dowolnym momencie pobrać, przywrócić z listy serwera, wgrać z pliku na dysku lub zaimportować podczas pierwszej konfiguracji na nowym serwerze.

---

## ⚙️ Zmienne środowiskowe

| Zmienna | Opis | Domyślna wartość |
|---|---|---|
| `NOTKI_HOST` | Adres IP, na którym nasłuchuje serwer | `127.0.0.1` (`0.0.0.0` w Dockerze) |
| `NOTKI_PORT` / `NOTKI_HTTP_PORT` | Port serwera HTTP | `8000` |
| `NOTKI_DB_PATH` | Ścieżka do bazy danych SQLite | `./data/notki.sqlite3` |
| `NOTKI_BACKUP_DIR` | Ścieżka do katalogu z backupami JSON | `./data/backups` |
| `NOTKI_COOKIE_SECURE` | Ustawienie flagi `Secure` dla ciasteczek (wymagane HTTPS) | `0` |
| `NOTKI_PUBLIC_HTTPS` | Generowanie linków zaproszeń z przedrostkiem `https://` | `0` |
| `NOTKI_ALLOW_REMOTE_SETUP` | Zezwolenie na pierwszą konfigurację z obcych adresów IP | `0` (`1` w Dockerze) |

---

## 📜 Licencja

Projekt oparty na licencji open-source.

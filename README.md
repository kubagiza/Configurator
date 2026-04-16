# Konfigurator sensorow do silownika

Aplikacja desktopowa w Pythonie i Tkinterze do szybkiego doboru sensorow oraz mocowan na podstawie typu rowka lub typu silownika.

## Co potrafi aplikacja

- wybor typu rowka lub typu silownika z listy po lewej stronie,
- wyswietlanie zdjecia wybranego rowka lub typu silownika,
- wyswietlanie listy pasujacych sensorow i mocowan,
- otwieranie linku produktu w przegladarce,
- pokazywanie notatki technicznej dla wybranego elementu,
- pokazywanie zdjecia konkretnego sensora lub mocowania,
- przewijanie listy sensorow kolkiem myszy,
- przewijanie panelu notatki kolkiem myszy oraz paskiem przewijania,
- reczna zmiana wysokosci sekcji `Dostepne sensory` i `Notatka do wybranego sensora`,
- automatyczne skalowanie zdjec, zeby nie zajmowaly calego okna,
- przycisk `Aktualizuj aplikacje`, ktory sprawdza nowe commity na GitHub i pobiera najnowszy build.

## Wymagania

Do uruchomienia projektu potrzebne sa:

- Windows
- Python 3.11 lub nowszy
- `tkinter`
- opcjonalnie `Pillow`

Jesli chcesz zbudowac gotowy plik `.exe`, potrzebny jest dodatkowo:

- `PyInstaller`

## Biblioteki

### Wymagane

`tkinter`

To biblioteka GUI dostepna standardowo w typowej instalacji Pythona na Windows.

### Opcjonalne, ale zalecane

`Pillow`

Biblioteka jest przydatna do:

- lepszego skalowania obrazow,
- wygodnej obslugi plikow `.jpg` i `.jpeg`.

Bez `Pillow` aplikacja nadal moze dzialac, ale dla czesci obrazow JPG korzysta z tymczasowej konwersji przez mechanizmy Windows.

## Instalacja do uruchamiania z Pythona

### 1. Sprawdzenie instalacji Pythona

W PowerShell:

```powershell
python --version
```

albo:

```powershell
py --version
```

Jesli komenda nie dziala, zainstaluj Pythona z:

[python.org/downloads](https://www.python.org/downloads/)

Podczas instalacji najlepiej zaznaczyc dodanie Pythona do `PATH`.

### 2. Instalacja Pillow

W PowerShell:

```powershell
pip install pillow
```

albo:

```powershell
python -m pip install pillow
```

albo:

```powershell
py -m pip install pillow
```

## Instalacja do budowy pliku EXE

W projekcie jest plik:

[requirements-build.txt](C:\Users\Fakro\Desktop\Dobór sensorów\ConfigSensor\requirements-build.txt)

Zawiera biblioteki potrzebne do budowy wersji `.exe`.

Instalacja:

```powershell
python -m pip install -r .\requirements-build.txt
```

albo:

```powershell
py -m pip install -r .\requirements-build.txt
```

## Uruchomienie

W katalogu projektu:

```powershell
python .\konfigurator_sensorow_silownika.py
```

albo:

```powershell
py .\konfigurator_sensorow_silownika.py
```

## Budowa pliku EXE

Projekt jest przygotowany do spakowania do pojedynczego pliku `.exe`, tak aby klient nie musial sam instalowac:

- Pythona,
- Pillow,
- PyInstallera,
- innych bibliotek potrzebnych do dzialania aplikacji.

### Najprostsza metoda

Uruchom plik:

[build_exe.bat](C:\Users\Fakro\Desktop\Dobór sensorów\ConfigSensor\build_exe.bat)

Ten skrypt:

- zainstaluje biblioteki potrzebne do builda,
- wyczysci stare foldery builda,
- zbuduje plik `.exe`,
- dolaczy ikone aplikacji z pliku `app_icon.ico`,
- dolaczy folder `images` do paczki.

### Build reczny

Jesli chcesz uruchomic build recznie:

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed --name ConfigSensor --icon "app_icon.ico" --add-data "images;images" konfigurator_sensorow_silownika.py
```

### Gdzie bedzie gotowy plik

Po buildzie gotowy plik znajdziesz tutaj:

`dist\ConfigSensor.exe`

## Co przekazac klientowi

Najwygodniej przekazac klientowi:

- sam plik `ConfigSensor.exe`, jesli wszystko dziala poprawnie po spakowaniu,
- albo spakowany folder z plikiem `.exe`, jesli chcesz wyslac go mailem lub przez dysk sieciowy.

Klient nie musi wtedy instalowac recznie Pythona ani bibliotek.

## Automatyczna aktualizacja z GitHub

Aplikacja ma przycisk `Aktualizuj aplikacje` na glownym panelu.

Po kliknieciu program:

- laczy sie z repozytorium `https://github.com/kubagiza/ConfigSensor.git`,
- sprawdza najnowszy commit na domyslnej galezi,
- pobiera ZIP z repozytorium,
- podmienia `ConfigSensor.exe` po zamknieciu programu,
- uruchamia zaktualizowany plik ponownie.

Wazne:

- klient finalnie powinien dostawac tylko jeden plik: `ConfigSensor.exe`,
- w repozytorium musi byc dostepny gotowy build w `dist/ConfigSensor.exe`,
- sama zmiana kodu bez wrzucenia nowego builda do repo nie wystarczy do aktualizacji wersji klienckiej `.exe`.

## Ikona aplikacji

Projekt zawiera plik ikony:

[app_icon.ico](C:\Users\Fakro\Desktop\Dobór sensorów\ConfigSensor\app_icon.ico)

Ikona jest dolaczana do pliku `.exe` podczas builda.

## Jak dziala interfejs

1. Po lewej stronie wybierasz typ rowka lub typ silownika.
2. U gory po prawej wyswietla sie obraz przypisanego rowka lub grupy produktowej.
3. W sekcji `Dostepne sensory` pojawiaja sie dopasowane sensory i mocowania.
4. Po kliknieciu `Szczegoly` lub zaznaczeniu checkboxa aktualizuje sie panel notatki.
5. W notatce widac opis, link i zdjecie konkretnego elementu.
6. Przyciskiem `Otworz link` mozna przejsc do strony produktu.

## Sekcje przewijane i zmiana wielkosci

- `Dostepne sensory` ma wlasny obszar przewijany.
- `Notatka do wybranego sensora` ma osobny scrollbar i obsluge scrolla myszy.
- Wysokosc sekcji `Dostepne sensory` i `Notatka do wybranego sensora` mozna zmieniac przeciagnieciem separatora miedzy nimi.

## Skalowanie obrazow

Aplikacja nie wyswietla obrazow w ich pelnym, oryginalnym rozmiarze.

Aktualnie obrazy sa ograniczane do maksymalnych rozmiarow:

- podglad rowka: `520x260`
- zdjecie elementu w notatce: `260x180`

To ustawienie znajduje sie w pliku:

[konfigurator_sensorow_silownika.py](C:\Users\Fakro\Desktop\Dobór sensorów\ConfigSensor\konfigurator_sensorow_silownika.py)

w stalych:

- `GROOVE_IMAGE_MAX_SIZE`
- `NOTE_IMAGE_MAX_SIZE`

## Jak dodawac zdjecia

Wszystkie obrazy nalezy umieszczac w folderze:

[images](C:\Users\Fakro\Desktop\Dobór sensorów\ConfigSensor\images)

### Zdjecia rowkow i typow silownikow

Sa przypisywane recznie w slowniku `GROOVE_IMAGES`.

### Zdjecia sensorow i mocowan

Aplikacja najpierw probuje znalezc plik automatycznie po nazwie modelu.

Przyklady:

- `BMF00AR` -> `images/BMF00AR.png`
- `BAM01K9 - mocowanie` -> najpierw pelna nazwa, a potem sam kod `BAM01K9.png`

Obslugiwane rozszerzenia:

- `.png`
- `.jpg`
- `.jpeg`
- `.gif`

Jesli automatyczne wyszukiwanie nie znajdzie pliku, aplikacja korzysta z recznego mapowania w slowniku `SENSOR_NOTE_IMAGES`.

## Struktura danych

Kazdy element w bazie `SENSOR_DB` moze zawierac miedzy innymi:

- `name`
- `link`
- `note`

To pozwala przypisac do kazdego sensora lub mocowania:

- nazwe widoczna w liscie,
- link do strony produktu,
- notatke ze szczegolami technicznymi.

## Uwagi

- Aplikacja jest przygotowana glownie pod Windows.
- Linki sa otwierane w domyslnej przegladarce systemowej.
- Dla najlepszej obslugi obrazow warto miec zainstalowane `Pillow`.
- Kod jest przygotowany do uruchamiania zarowno jako skrypt `.py`, jak i jako spakowany plik `.exe`.

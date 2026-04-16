import json
import os
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from urllib.parse import urlparse
import webbrowser

import requests

try:
    from PIL import Image, ImageTk
except ImportError:
    Image = None
    ImageTk = None


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
IMAGES_DIR = BASE_DIR / "images"
SUPPORTED_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif")
GROOVE_IMAGE_MAX_SIZE = (520, 260)
NOTE_IMAGE_MAX_SIZE = (260, 180)
APP_TITLE = "Konfigurator sensorow do silownika"
APP_DIR_NAME = "ConfigSensor"
UPDATE_REPO_URL = "https://github.com/kubagiza/ConfigSensor.git"
GITHUB_API_BASE = "https://api.github.com"
STATE_FILE_NAME = "update_state.json"
SELF_UPDATE_SCRIPT_NAME = "apply_update.cmd"


class UpdateError(Exception):
    """Raised when the application update cannot be completed."""


@dataclass
class RepoSnapshot:
    owner: str
    repo: str
    default_branch: str
    latest_sha: str
    zip_url: str


def get_runtime_base_dir():
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DIR_NAME
    return Path.home() / APP_DIR_NAME


def get_update_work_dir():
    return get_runtime_base_dir() / "updater"


def parse_repo_url(repo_url):
    parsed = urlparse(repo_url)
    if parsed.netloc.lower() != "github.com":
        raise UpdateError("Obslugiwane sa tylko linki do repozytoriow GitHub.")

    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2:
        raise UpdateError("Link do repozytorium GitHub ma nieprawidlowy format.")

    owner = path_parts[0]
    repo = path_parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]

    if not owner or not repo:
        raise UpdateError("Nie udalo sie odczytac owner/repo z podanego linku.")

    return owner, repo


class GitHubAppUpdater:
    def __init__(self, repo_url, app_name="ConfigSensor"):
        self.repo_url = repo_url
        self.app_name = app_name
        self.owner, self.repo = parse_repo_url(repo_url)
        self.work_dir = get_update_work_dir()
        self.download_dir = self.work_dir / "downloads"
        self.state_file = self.work_dir / STATE_FILE_NAME
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "User-Agent": "config-sensor-updater",
            }
        )

    def update(self):
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        state = self._load_state()
        snapshot = self._fetch_snapshot()

        if state.get("latest_sha") == snapshot.latest_sha:
            return {
                "status": "up_to_date",
                "message": f"Aplikacja jest juz aktualna ({snapshot.latest_sha[:7]}).",
                "sha": snapshot.latest_sha,
            }

        zip_path = self._download_zip(snapshot)
        try:
            with tempfile.TemporaryDirectory(dir=str(self.work_dir)) as temp_dir_name:
                temp_dir = Path(temp_dir_name)
                extracted_root = self._extract_repo(zip_path, temp_dir)
                result = self._prepare_frozen_update(extracted_root)
        finally:
            if zip_path.exists():
                zip_path.unlink()

        self._save_state(snapshot)
        result["sha"] = snapshot.latest_sha
        return result

    def _load_state(self):
        if not self.state_file.exists():
            return {}

        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise UpdateError(f"Plik stanu aktualizacji jest uszkodzony: {self.state_file}") from exc

    def _save_state(self, snapshot):
        payload = {
            "owner": snapshot.owner,
            "repo": snapshot.repo,
            "default_branch": snapshot.default_branch,
            "latest_sha": snapshot.latest_sha,
        }
        self.state_file.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def _fetch_snapshot(self):
        repo_data = self._get_json(f"/repos/{self.owner}/{self.repo}")
        default_branch = repo_data["default_branch"]
        branch_data = self._get_json(f"/repos/{self.owner}/{self.repo}/branches/{default_branch}")
        latest_sha = branch_data["commit"]["sha"]
        return RepoSnapshot(
            owner=self.owner,
            repo=self.repo,
            default_branch=default_branch,
            latest_sha=latest_sha,
            zip_url=f"https://api.github.com/repos/{self.owner}/{self.repo}/zipball/{latest_sha}",
        )

    def _get_json(self, endpoint):
        response = self.session.get(f"{GITHUB_API_BASE}{endpoint}", timeout=30)
        if response.status_code == 404:
            raise UpdateError(f"Nie znaleziono publicznego repozytorium {self.owner}/{self.repo}.")
        if response.status_code == 403:
            raise UpdateError(
                "GitHub API odrzucilo zapytanie (mozliwy limit zapytan). Sprobuj ponownie pozniej."
            )

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise UpdateError(f"Blad GitHub API: {exc}") from exc

        return response.json()

    def _download_zip(self, snapshot):
        zip_path = self.download_dir / f"{snapshot.repo}-{snapshot.latest_sha[:7]}.zip"
        response = self.session.get(snapshot.zip_url, timeout=60, stream=True)

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise UpdateError(f"Nie udalo sie pobrac archiwum ZIP: {exc}") from exc

        with zip_path.open("wb") as zip_file:
            for chunk in response.iter_content(chunk_size=1024 * 64):
                if chunk:
                    zip_file.write(chunk)

        return zip_path

    def _extract_repo(self, zip_path, temp_dir):
        extract_dir = temp_dir / "repo"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(extract_dir)

        extracted_entries = [entry for entry in extract_dir.iterdir()]
        if len(extracted_entries) != 1 or not extracted_entries[0].is_dir():
            raise UpdateError("Nieoczekiwana struktura archiwum ZIP repozytorium.")

        return extracted_entries[0]

    def _prepare_frozen_update(self, extracted_root):
        current_exe = Path(sys.executable).resolve()
        source_exe = self._find_replacement_exe(extracted_root)
        script_path = self.work_dir / SELF_UPDATE_SCRIPT_NAME
        self._write_self_update_script(script_path, source_exe, current_exe, current_exe)
        subprocess.Popen(
            ["cmd", "/c", str(script_path)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return {
            "status": "restart_required",
            "message": (
                "Nowa wersja zostala pobrana. Aplikacja zamknie sie, "
                "podmieni plik EXE i uruchomi ponownie."
            ),
        }

    def _find_replacement_exe(self, extracted_root):
        onefile_candidate = extracted_root / "dist" / f"{self.app_name}.exe"
        if onefile_candidate.exists():
            return onefile_candidate

        raise UpdateError(
            "Repozytorium nie zawiera gotowego builda do aktualizacji. "
            "Dodaj do repo plik dist/ConfigSensor.exe."
        )

    def _write_self_update_script(self, script_path, source_path, target_path, current_exe):
        source_path = Path(source_path).resolve()
        target_path = Path(target_path).resolve()
        current_exe = Path(current_exe).resolve()
        restart_target = target_path
        exe_name = current_exe.name

        script_content = (
            "@echo off\r\n"
            "setlocal\r\n"
            ":waitloop\r\n"
            f'tasklist /FI "IMAGENAME eq {exe_name}" | find /I "{exe_name}" >nul\r\n'
            "if not errorlevel 1 (\r\n"
            "    timeout /t 1 /nobreak >nul\r\n"
            "    goto waitloop\r\n"
            ")\r\n"
            f'copy /Y "{source_path}" "{target_path}" >nul\r\n'
            f'start "" "{restart_target}"\r\n'
            f'del "{script_path}" >nul 2>nul\r\n'
        )
        script_path.write_text(script_content, encoding="ascii")


SENSOR_DB = {
    "Rowek T": [
        {
            "name": "BMF00C4 - M8 3pin",
            "link": "https://www.balluff.com/pl-pl/products/BMF00C4",
            "note": (
                " Do rowków teowych "
                " Kształt wpustu " 
                " Kanałek typu T "
                " Wymiary 23.5 x 5 x 5.5 mm "
                " Zasada działania Czujnik pola magnetycznego "
                " Przyłącze M8x1-Męski, 3-stykowe "
                " Przewód PUR, 0.3 m "
            ),
        },
        {
            "name": "BMF00AR - przewód PUR, 2m",
            "link": "https://www.balluff.com/pl-pl/products/BMF00AR",
            "note": (
                " Do rowków teowych "
                " Kształt wpustu " 
                " Kanałek typu T "
                " Wymiary 23.5 x 5 x 5.5 mm  "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód PUR, 2 m " 
            ),
        },
        {
            "name": "BMF00CH - przewód PUR, 5m",
            "link": "https://www.balluff.com/pl-pl/products/BMF00CH",
            "note": (
                " Do rowków teowych "
                " Kształt wpustu " 
                " Kanałek typu T "
                " Wymiary 23.5 x 5 x 5.5 mm  "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód "
                " PUR, 5 m " 
            ),
        },
    ],
    "Rowek C": [
        {
            "name": "BMF00P0 - M8 3pin",
            "link": "https://www.balluff.com/en-us/products/BMF00P0?pm=BMF423&pf=F01502",
            "note": (
               " Do rowków C "
                " Kształt wpustu " 
                " Kanałek typu C "
                " Wymiary 3,6 x 2,9 x 24 mm  "
                " Zasada działania Czujnik pola magnetycznego "
                " M8x1-męski, 3-pinowy " 
                " PUR, 0,3 m"
            ),
        },
        {
            "name": "BMF00E3 - przewód PUR, 5m",
            "link": "https://www.balluff.com/en-de/products/BMF00E3",
            "note": (
                " Do rowków C "
                " Kształt wpustu " 
                " Kanałek typu C "
                " Wymiary 16,8 x 2,9 x 4,5 mm  "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód "
                " PUR, 5 m"
            ),
        },
        {
            "name": "BMF00NU, przewód PUR, 2m",
            "link": "https://www.balluff.com/de-de/products/PV11502035",
            "note": (
                " Do rowków C "
                " Kształt wpustu " 
                " Kanałek typu C "
                " Wymiary 3,6 x 2,9 x 24 mm "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód "
                " PUR, 2 m"
            ),
        },

    ],
    "Rowek specjalny": [
        {
            "name": "BAM01K9 - mocowanie",
            "link": "https://www.balluff.com/en-de/products/BAM01K9",
            "note": (
                "To element mocujacy do niestandardowego rowka, a nie sam sensor. "
                "Używać do czujników magnetycznych BMF 303 "
                "Tworzywo Aluminium anodowane " 
                "Temperatura otoczenia -40...85 °C "
            ),
        },
        {
            "name": "BMF003W - przewód PUR, 3m",
            "link": "https://www.balluff.com/pl-pl/products/BMF003W",
            "note": (
                " Wymiary 25.5 x 3 x 4.5 mm "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód "
                " PUR, 3 m"
            ),
        },
    ],
    "Zintegrowane siłowniki profilowe lub cięgnowe":[
        {
            "name": "BAM01M9 - mocowanie do 11,3mm",
            "link": "https://www.balluff.com/pl-pl/products/BAM01M9",
            "note": (
                "Kątowniki mocujące do czujników pola magnetycznego "
                "Zasada działania Uchwyt mocujący dla sensorów rowka T np. BMF00AR"
                "Materiał Aluminium"
                "Rozmiar szpilki do - 11,3mm"
            ),
        },
        {
            "name": "KLZ2-INT - mocowanie do 9,5mm",
            "link": "https://shop.turck.pl/pl/en/shop/sensors/accessories/6970411",
            "note": (
                "Kątowniki mocujące do czujników pola magnetycznego "
                "Zasada działania Uchwyt mocujący dla sensorów rowka T np. BMF00AR"
                "Materiał Aluminium"
                "Rozmiar szpilki do - 9,5mm"
            ),
        },
        {
            "name": "KLZ1-INT - mocowanie",
            "link": "https://www.turck.us/en/product/6970410",
            "note": (
                "Kątowniki mocujące do czujników pola magnetycznego "
                "Zasada działania Uchwyt mocujący dla sensorów rowka T np. BMF00AR"
                "Materiał Aluminium"
                "Rozmiar szpilki do - 7,5mm"
            ),
        },
        {
            "name": "BMF00AR - przewód PUR, 2m",
            "link": "https://www.balluff.com/pl-pl/products/BMF00AR",
            "note": (
                " Do rowków teowych "
                " Kształt wpustu " 
                " Kanałek typu T "
                " Wymiary 23.5 x 5 x 5.5 mm  "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód PUR, 2 m " 
            ),
        },
    ],
    "Siłownik clean-line":[
        {
            "name": "BAM00LP - wspornik mocujący",
            "link": "https://www.balluff.com/pl-pl/products/BAM00LP",
            "note": (
                "Kątowniki mocujące do czujników pola magnetycznego"
                "Używać do czujników magnetycznych BMF0056 oraz BAM00N5 uchwytów (opasek)"
                "Tworzywo Mosiądz niklowane " 
            ),
        },
        {
            "name": "BAM00N2 - mocowanie Ø 7-11 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N2?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 7-11 mm "
            ),
        },
        {
            "name": "BAM00N3 - mocowanie Ø 11-19 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N3?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 11-19 mm "
            ),
        },
        {
            "name": "BAM00N4 - mocowanie Ø 18-29 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N4",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 18-29 mm "
            ),
        },
        {
            "name": "BAM00N5 - mocowanie Ø 28-39 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N5",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 28-39 mm "
            ),
        },
        {
            "name": "BAM00N6 - mocowanie Ø 38-49 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N6?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 38-49 mm "
            ),
        },
        {
            "name": "BAM00N7 - mocowanie Ø 48-59 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N7?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 48-59 mm"
            ),
        },
        {
            "name": "BAM00N8 - mocowanie Ø 58-69 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N8?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 58-69 mm"
            ),
        },
        {
            "name": "BAM00N9 - mocowanie Ø 78-89 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00N9?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 78-89 mm "
            ),
        },
        {
            "name": "BAM00NA - mocowanie Ø 68-79 mm",
            "link": "https://www.balluff.com/en-de/products/BAM00NA?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 68-79 mm "
            ),
        },
        {
            "name": "BAM01F4 - mocowanie Ø 108-119 mm",
            "link": "https://www.balluff.com/en-de/products/BAM01F4?attrs%5Bbas_usage%5D%5B0%5D=446085&pf=F17611",
            "note": (
                "Uniwersalne uchwyty "
                "Używać do czujników magnetycznych BMF0056 oraz BAM00LP wspornika mocującego"
                "Tworzywo stal nierdzewna " 
                "Wersja Ø 108-119 mm "
            ),
        },
        {
            "name": "BMF0056 - przewód PUR, 2m",
            "link": "https://www.balluff.com/pl-pl/products/BMF0056",
            "note": (
                " Wymiary 33.5 x 5 x 10.5 mm "
                " Zasada działania Czujnik pola magnetycznego "
                " Przewód "
                " PUR, 2 m"
            ),
        },
    ]
}


# Podaj nazwe pliku bez rozszerzenia albo pelna sciezke wzgledem katalogu programu.
GROOVE_IMAGES = {
    "Rowek T": "images/rowek_t.jpg",
    "Rowek C": "images/rowek_c.jpg",
    "Rowek specjalny": "images/rowek_trapezowy.jpg",
    "Zintegrowane siłowniki profilowe lub cięgnowe": "images/Zintegrowane siłowniki profilowe lub cięgnowe.png",
    "Siłownik clean-line": "images/Siłownik clean-line.png",
}


SENSOR_NOTE_IMAGES = {
    "BMF00C4": "images/BMF00C4.png",
    "BMF00AR": "images/BMF00AR.png",
    "BMF00CH": "images/BMF00CH.png",
    "BMF00P0": "images/BMF00P0.png",
    "BMF00E3": "images/BMF00E3.png",
    "BMF00NU": "images/bmg00nu.png.png",
    "BAM01K9 - mocowanie": "images/BAM01K9.png",
    "BMF003W": "images/BMF003W.png",
    "BAM01M9 - mocowanie": "images/BAM01M9.png",
    "KLZ2-INT - mocowanie": "images/KLZ2-INT.png",
    "KLZ1-INT - mocowanie": "images/KLZ1-INT.png",
    "BAM00LP - wspornik mocujący": "images/BAM00LP.png",
    "BAM00N2 - mocowanie": "images/BAM00N2.png",
    "BAM00N3 - mocowanie": "images/BAM00N3.png",
    "BAM00N4 - mocowanie": "images/BAM00N4.png",
    "BAM00N5 - mocowanie": "images/BAM00N5.png",
    "BAM00N6 - mocowanie": "images/BAM00N6.png",
    "BAM00N7 - mocowanie": "images/BAM00N7.png",
    "BAM00N8 - mocowanie": "images/BAM00N8.png",
    "BAM00N9 - mocowanie": "images/bam00n9.png",
    "BAM00NA - mocowanie": "images/BAM00NA.png",
    "BAM01F4 - mocowanie": "images/BAM01F4.png",
    "BMF0056": "images/BMF0056.png",
}


class SensorConfiguratorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1000x650")
        self.minsize(900, 600)

        self.selected_groove = tk.StringVar(value="")
        self.checkbox_vars = {}
        self.selected_sensor_keys = set()
        self.current_photo = None
        self.current_note_photo = None
        self._temp_image_path = None
        self._temp_note_image_path = None
        self.current_sensor_name = tk.StringVar(value="Brak wybranego sensora")
        self.active_mousewheel_canvas = None
        self._global_mousewheel_bound = False
        self.update_button = None
        self.update_window = None
        self.update_output = None
        self._update_in_progress = False

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        main = ttk.Frame(self, padding=12)
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="Konfigurator sensorow wedlug rowka silownika",
            font=("Segoe UI", 16, "bold"),
        )
        title.pack(anchor="w", pady=(0, 10))

        content = ttk.Frame(main)
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content, padding=(0, 0, 12, 0))
        left.pack(side="left", fill="y")

        groove_box = ttk.LabelFrame(left, text="1. Wybierz typ rowka", padding=10)
        groove_box.pack(fill="x", pady=(0, 10))

        for groove_name in SENSOR_DB.keys():
            ttk.Radiobutton(
                groove_box,
                text=groove_name,
                value=groove_name,
                variable=self.selected_groove,
                command=self.on_groove_change,
            ).pack(anchor="w", pady=3)

        btn_frame = ttk.Frame(left)
        btn_frame.pack(fill="x", pady=(10, 0))

        ttk.Button(btn_frame, text="Pokaz sensory", command=self.show_sensors).pack(
            fill="x", pady=4
        )
        ttk.Button(btn_frame, text="Wyczysc wybor", command=self.clear_selection).pack(
            fill="x", pady=4
        )
        ttk.Button(btn_frame, text="Pokaz podsumowanie", command=self.show_summary).pack(
            fill="x", pady=4
        )
        self.update_button = ttk.Button(
            btn_frame,
            text="Aktualizuj aplikacje",
            command=self.start_application_update,
        )
        self.update_button.pack(fill="x", pady=(16, 4))

        right = ttk.Frame(content)
        right.pack(side="left", fill="both", expand=True)

        image_box = ttk.LabelFrame(right, text="2. Zdjecie / podglad rowka", padding=10)
        image_box.pack(fill="x", pady=(0, 10))

        self.image_label = ttk.Label(
            image_box,
            text=(
                "Tutaj bedzie wyswietlane zdjecie wybranego rowka.\n\n"
                "Program szuka plikow w folderze images (.png, .jpg, .jpeg, .gif)."
            ),
            anchor="center",
            justify="center",
        )
        self.image_label.pack(fill="x")

        content_pane = tk.PanedWindow(
            right,
            orient="vertical",
            sashrelief="raised",
            sashwidth=10,
        )
        content_pane.pack(fill="both", expand=True, pady=(0, 10))

        sensor_box = ttk.LabelFrame(content_pane, text="3. Dostepne sensory", padding=10)

        canvas = tk.Canvas(sensor_box, highlightthickness=0, height=220)
        self.sensor_canvas = canvas
        scrollbar = ttk.Scrollbar(sensor_box, orient="vertical", command=canvas.yview)
        self.sensor_list_frame = ttk.Frame(canvas)

        self.sensor_list_frame.bind(
            "<Configure>",
            lambda event: canvas.configure(scrollregion=canvas.bbox("all")),
        )

        self.sensor_canvas_window = canvas.create_window(
            (0, 0),
            window=self.sensor_list_frame,
            anchor="nw",
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        self._bind_mousewheel_to_widget(sensor_box, canvas)
        self._bind_mousewheel_to_widget(canvas, canvas)
        self._bind_mousewheel_to_widget(self.sensor_list_frame, canvas)
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(self.sensor_canvas_window, width=event.width),
        )

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        note_box = ttk.LabelFrame(content_pane, text="4. Notatka do wybranego sensora", padding=10)

        note_canvas = tk.Canvas(note_box, highlightthickness=0, height=260)
        self.note_canvas = note_canvas
        note_scrollbar = ttk.Scrollbar(note_box, orient="vertical", command=note_canvas.yview)
        self.note_content_frame = ttk.Frame(note_canvas)

        self.note_content_frame.bind(
            "<Configure>",
            lambda event: note_canvas.configure(scrollregion=note_canvas.bbox("all")),
        )

        self.note_canvas_window = note_canvas.create_window(
            (0, 0),
            window=self.note_content_frame,
            anchor="nw",
        )
        note_canvas.configure(yscrollcommand=note_scrollbar.set)
        self._bind_mousewheel_to_widget(note_box, note_canvas)
        self._bind_mousewheel_to_widget(note_canvas, note_canvas)
        self._bind_mousewheel_to_widget(self.note_content_frame, note_canvas)
        note_canvas.bind(
            "<Configure>",
            lambda event: note_canvas.itemconfigure(self.note_canvas_window, width=event.width),
        )

        note_canvas.pack(side="left", fill="both", expand=True)
        note_scrollbar.pack(side="right", fill="y")

        content_pane.add(sensor_box, minsize=150)
        content_pane.add(note_box, minsize=180)

        self.note_title_label = ttk.Label(
            self.note_content_frame,
            textvariable=self.current_sensor_name,
            font=("Segoe UI", 11, "bold"),
        )
        self.note_title_label.pack(anchor="w", pady=(0, 6))
        self._bind_mousewheel_to_widget(self.note_title_label, note_canvas)

        self.note_image_label = ttk.Label(
            self.note_content_frame,
            text="Tutaj bedzie wyswietlane zdjecie wybranego elementu.",
            anchor="center",
            justify="center",
        )
        self.note_image_label.pack(fill="x", pady=(0, 8))
        self._bind_mousewheel_to_widget(self.note_image_label, note_canvas)

        self.note_label = ttk.Label(
            self.note_content_frame,
            text=(
                "Po wybraniu sensora tutaj pojawia sie notatka z dodatkowymi "
                "szczegolami i wskazowkami doboru."
            ),
            justify="left",
            wraplength=650,
        )
        self.note_label.pack(anchor="w", fill="x")
        self._bind_mousewheel_to_widget(self.note_label, note_canvas)

        self.result_box = ttk.LabelFrame(right, text="5. Podsumowanie", padding=10)
        self.result_box.pack(fill="x")

        self.result_label = ttk.Label(
            self.result_box,
            text="Wybierz typ rowka i zaznacz sensory checkboxem.",
            justify="left",
        )
        self.result_label.pack(anchor="w")

    def start_application_update(self):
        if self._update_in_progress:
            return

        confirmed = messagebox.askyesno(
            APP_TITLE,
            (
                "Program sprawdzi repozytorium GitHub i pobierze najnowsza wersje aplikacji.\n\n"
                "Kontynuowac aktualizacje?"
            ),
        )
        if not confirmed:
            return

        self._update_in_progress = True
        if self.update_button is not None:
            self.update_button.config(state="disabled")

        self._ensure_update_window()
        self._append_update_log(f"Repozytorium aktualizacji: {UPDATE_REPO_URL}")
        self._append_update_log("Rozpoczeto sprawdzanie aktualizacji.")

        worker = threading.Thread(target=self._run_application_update, daemon=True)
        worker.start()

    def _ensure_update_window(self):
        if self.update_window is not None and self.update_window.winfo_exists():
            self.update_window.lift()
            self.update_window.focus_force()
            return

        self.update_window = tk.Toplevel(self)
        self.update_window.title("Aktualizacja aplikacji")
        self.update_window.geometry("700x420")
        self.update_window.minsize(580, 320)
        self.update_window.transient(self)

        container = ttk.Frame(self.update_window, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Log aktualizacji",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(container)
        text_frame.pack(fill="both", expand=True)

        self.update_output = tk.Text(text_frame, wrap="word", state="disabled", font=("Consolas", 10))
        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=self.update_output.yview)
        self.update_output.configure(yscrollcommand=scrollbar.set)

        self.update_output.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Button(container, text="Zamknij", command=self.update_window.destroy).pack(anchor="e", pady=(10, 0))

    def _append_update_log(self, text):
        self._ensure_update_window()
        self.update_output.config(state="normal")
        self.update_output.insert("end", text + "\n\n")
        self.update_output.see("end")
        self.update_output.config(state="disabled")

    def _run_application_update(self):
        try:
            updater = GitHubAppUpdater(UPDATE_REPO_URL, app_name="ConfigSensor")
            result = updater.update()
            self.after(0, self._finish_application_update, result, None)
        except requests.RequestException as exc:
            self.after(0, self._finish_application_update, None, f"Blad sieci podczas aktualizacji: {exc}")
        except UpdateError as exc:
            self.after(0, self._finish_application_update, None, str(exc))
        except OSError as exc:
            self.after(0, self._finish_application_update, None, f"Blad operacji na plikach: {exc}")
        except Exception as exc:
            self.after(0, self._finish_application_update, None, f"Nieoczekiwany blad aktualizacji: {exc}")

    def _finish_application_update(self, result, error_message):
        self._update_in_progress = False
        if self.update_button is not None:
            self.update_button.config(state="normal")

        if error_message:
            self._append_update_log(error_message)
            messagebox.showerror(APP_TITLE, error_message)
            return

        message = result.get("message", "Aktualizacja zakonczona.")
        sha = result.get("sha")
        if sha:
            self._append_update_log(f"Docelowy commit: {sha}")
        self._append_update_log(message)

        status = result.get("status")
        if status == "restart_required":
            messagebox.showinfo(APP_TITLE, message)
            self.after(300, self.destroy)
            return

        if status == "updated":
            messagebox.showinfo(
                APP_TITLE,
                message + "\n\nUruchom aplikacje ponownie, aby pracowac na nowej wersji.",
            )
            return

        messagebox.showinfo(APP_TITLE, message)

    def on_groove_change(self):
        self.load_image()
        self.show_sensors()

    def load_image(self):
        groove = self.selected_groove.get()
        image_key = GROOVE_IMAGES.get(groove, "")

        if not groove:
            self.image_label.config(text="Nie wybrano typu rowka.", image="")
            self.current_photo = None
            return

        if not image_key:
            self.image_label.config(
                text=f"Brak przypisanego zdjecia dla: {groove}",
                image="",
            )
            self.current_photo = None
            return

        path = self._resolve_image_path(image_key)
        if not path.exists():
            self.image_label.config(
                text=(
                    f"Nie znaleziono pliku zdjecia:\n{path}\n\n"
                    "Sprawdz folder images oraz wpis w GROOVE_IMAGES."
                ),
                image="",
            )
            self.current_photo = None
            return

        try:
            self.current_photo = self._create_photo(
                path,
                "_temp_image_path",
                GROOVE_IMAGE_MAX_SIZE,
            )
            self.image_label.config(text="", image=self.current_photo)
        except Exception as exc:
            details = (
                "Dla JPG/JPEG program potrzebuje biblioteki Pillow "
                "(instalacja: pip install pillow)."
                if path.suffix.lower() in {".jpg", ".jpeg"}
                else "Plik istnieje, ale nie udalo sie go wyswietlic."
            )
            self.image_label.config(
                text=f"{details}\n\nPlik: {path}\n\nSzczegoly: {exc}",
                image="",
            )
            self.current_photo = None

    def _resolve_image_path(self, image_key):
        raw_path = Path(image_key)
        if not raw_path.is_absolute():
            if raw_path.parts and raw_path.parts[0].lower() == "images":
                raw_path = BASE_DIR / raw_path
            else:
                raw_path = IMAGES_DIR / raw_path

        if raw_path.suffix:
            return raw_path

        for extension in SUPPORTED_IMAGE_EXTENSIONS:
            candidate = raw_path.with_suffix(extension)
            if candidate.exists():
                return candidate

        return raw_path

    def _create_photo(self, path, temp_attr_name, max_size=None):
        self._cleanup_temp_image(temp_attr_name)

        if path.suffix.lower() in {".jpg", ".jpeg"}:
            if Image is not None and ImageTk is not None:
                image = Image.open(path)
                if max_size:
                    image.thumbnail(max_size)
                return ImageTk.PhotoImage(image)

            converted_path = self._convert_jpg_to_png(path)
            setattr(self, temp_attr_name, converted_path)
            return self._load_tk_photo(converted_path, max_size)

        if Image is not None and ImageTk is not None:
            image = Image.open(path)
            if max_size:
                image.thumbnail(max_size)
            return ImageTk.PhotoImage(image)

        return self._load_tk_photo(path, max_size)

    @staticmethod
    def _load_tk_photo(path, max_size=None):
        photo = tk.PhotoImage(file=str(path))
        if not max_size:
            return photo

        max_width, max_height = max_size
        width = photo.width()
        height = photo.height()
        scale = max(width / max_width, height / max_height, 1)

        if scale > 1:
            divisor = int(scale) if float(scale).is_integer() else int(scale) + 1
            photo = photo.subsample(divisor, divisor)

        return photo

    @staticmethod
    def _convert_jpg_to_png(path):
        temp_file = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        temp_file.close()

        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Add-Type -AssemblyName System.Drawing; "
                "$inputPath = [System.IO.Path]::GetFullPath($args[0]); "
                "$outputPath = [System.IO.Path]::GetFullPath($args[1]); "
                "$image = [System.Drawing.Image]::FromFile($inputPath); "
                "$image.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png); "
                "$image.Dispose()"
            ),
            str(path),
            temp_file.name,
        ]

        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except Exception as exc:
            try:
                os.unlink(temp_file.name)
            except OSError:
                pass
            raise RuntimeError("Nie udalo sie przekonwertowac JPG do PNG.") from exc

        return Path(temp_file.name)

    def _cleanup_temp_image(self, temp_attr_name):
        temp_path = getattr(self, temp_attr_name, None)
        if not temp_path:
            return

        try:
            os.unlink(temp_path)
        except OSError:
            pass
        finally:
            setattr(self, temp_attr_name, None)

    def _bind_mousewheel_to_widget(self, widget, canvas):
        widget.bind("<Enter>", lambda event: self._activate_mousewheel(canvas), add="+")
        widget.bind("<Leave>", lambda event: self._deactivate_mousewheel(canvas), add="+")
        widget.bind("<MouseWheel>", lambda event: self._on_mousewheel(event, canvas), add="+")
        widget.bind("<Button-4>", lambda event: self._on_mousewheel(event, canvas), add="+")
        widget.bind("<Button-5>", lambda event: self._on_mousewheel(event, canvas), add="+")

    def _activate_mousewheel(self, canvas):
        self.active_mousewheel_canvas = canvas
        if not self._global_mousewheel_bound:
            self.bind_all("<MouseWheel>", self._on_global_mousewheel, add="+")
            self.bind_all("<Button-4>", self._on_global_mousewheel, add="+")
            self.bind_all("<Button-5>", self._on_global_mousewheel, add="+")
            self._global_mousewheel_bound = True

    def _deactivate_mousewheel(self, canvas):
        if self.active_mousewheel_canvas is canvas:
            self.active_mousewheel_canvas = None

    def _on_global_mousewheel(self, event):
        if self.active_mousewheel_canvas is None:
            return None
        return self._on_mousewheel(event, self.active_mousewheel_canvas)

    @staticmethod
    def _on_mousewheel(event, canvas):
        if hasattr(event, "delta") and event.delta:
            step = -1 if event.delta > 0 else 1
        elif getattr(event, "num", None) == 4:
            step = -1
        elif getattr(event, "num", None) == 5:
            step = 1
        else:
            step = 0

        if step:
            canvas.yview_scroll(step, "units")

        return "break"

    def _on_close(self):
        if self._update_in_progress:
            messagebox.showwarning(
                APP_TITLE,
                "Trwa aktualizacja aplikacji. Poczekaj na zakonczenie procesu.",
            )
            return
        self._cleanup_temp_image("_temp_image_path")
        self._cleanup_temp_image("_temp_note_image_path")
        self.destroy()

    def show_sensors(self):
        for widget in self.sensor_list_frame.winfo_children():
            widget.destroy()

        self.checkbox_vars.clear()

        groove = self.selected_groove.get()
        if not groove:
            info_label = ttk.Label(
                self.sensor_list_frame,
                text="Najpierw wybierz typ rowka po lewej stronie.",
            )
            info_label.pack(anchor="w")
            self._bind_mousewheel_to_widget(info_label, self.sensor_canvas)
            return

        sensors = SENSOR_DB.get(groove, [])
        if not sensors:
            info_label = ttk.Label(
                self.sensor_list_frame,
                text=f"Brak sensorow przypisanych do typu: {groove}",
            )
            info_label.pack(anchor="w")
            self._bind_mousewheel_to_widget(info_label, self.sensor_canvas)
            return

        groove_label = ttk.Label(
            self.sensor_list_frame,
            text=f"Typ rowka: {groove}",
            font=("Segoe UI", 11, "bold"),
        )
        groove_label.pack(anchor="w", pady=(0, 8))
        self._bind_mousewheel_to_widget(groove_label, self.sensor_canvas)

        for idx, sensor in enumerate(sensors):
            row = ttk.Frame(self.sensor_list_frame)
            row.pack(fill="x", pady=4)
            self._bind_mousewheel_to_widget(row, self.sensor_canvas)

            sensor_name = self._get_sensor_name(sensor)
            sensor_key = self._make_sensor_key(groove, sensor)
            var = tk.BooleanVar(value=sensor_key in self.selected_sensor_keys)
            self.checkbox_vars[idx] = (var, sensor_key, sensor)
            sensor_link = self._get_sensor_link(sensor)

            sensor_check = ttk.Checkbutton(
                row,
                text=sensor_name,
                variable=var,
                command=lambda item=sensor, key=sensor_key, value=var: self.on_sensor_toggle(item, key, value),
            )
            sensor_check.pack(side="left", anchor="w")
            self._bind_mousewheel_to_widget(sensor_check, self.sensor_canvas)

            details_button = ttk.Button(
                row,
                text="Szczegoly",
                command=lambda item=sensor: self.show_sensor_details(item),
            )
            details_button.pack(side="right", padx=(6, 0))
            self._bind_mousewheel_to_widget(details_button, self.sensor_canvas)

            link_button = ttk.Button(
                row,
                text="Otworz link",
                command=lambda url=sensor_link: self.open_link(url),
            )
            link_button.pack(side="right")
            self._bind_mousewheel_to_widget(link_button, self.sensor_canvas)

        first_sensor = sensors[0]
        self.show_sensor_details(first_sensor)
        self.update_summary_text()

    def on_sensor_toggle(self, sensor, sensor_key, var):
        if var.get():
            self.selected_sensor_keys.add(sensor_key)
        else:
            self.selected_sensor_keys.discard(sensor_key)

        self.update_summary_text()
        self.show_sensor_details(sensor)

    def show_sensor_details(self, sensor):
        sensor_name = self._get_sensor_name(sensor)
        sensor_note = self._get_sensor_note(sensor)
        sensor_link = self._get_sensor_link(sensor)
        sensor_image = self._get_sensor_note_image(sensor)

        self.current_sensor_name.set(sensor_name)
        self._load_note_image(sensor_name, sensor_image)

        details = sensor_note
        if sensor_link:
            details += f"\n\nLink do produktu:\n{sensor_link}"

        self.note_label.config(text=details)

    def _load_note_image(self, sensor_name, image_key):
        if not image_key:
            self.note_image_label.config(
                text=f"Brak przypisanego zdjecia dla elementu: {sensor_name}",
                image="",
            )
            self.current_note_photo = None
            return

        path = self._resolve_image_path(image_key)
        if not path.exists():
            self.note_image_label.config(
                text=f"Nie znaleziono pliku zdjecia elementu:\n{path}",
                image="",
            )
            self.current_note_photo = None
            return

        try:
            self.current_note_photo = self._create_photo(
                path,
                "_temp_note_image_path",
                NOTE_IMAGE_MAX_SIZE,
            )
            self.note_image_label.config(text="", image=self.current_note_photo)
        except Exception as exc:
            self.note_image_label.config(
                text=f"Nie udalo sie wyswietlic zdjecia elementu.\n\nPlik: {path}\n\nSzczegoly: {exc}",
                image="",
            )
            self.current_note_photo = None

    def update_summary_text(self):
        groove = self.selected_groove.get()
        selected = self._get_all_selected_sensors()

        if not groove:
            if selected:
                text = "Nie wybrano typu rowka.\nZaznaczone sensory:\n- " + "\n- ".join(
                    f"{item['groove']}: {item['name']}" for item in selected
                )
            else:
                text = "Nie wybrano typu rowka."
        elif not selected:
            text = f"Wybrany rowek: {groove}\nNie zaznaczono jeszcze zadnego sensora."
        else:
            text = f"Wybrany rowek: {groove}\nZaznaczone sensory:\n- " + "\n- ".join(
                f"{item['groove']}: {item['name']}" for item in selected
            )

        self.result_label.config(text=text)

    def show_summary(self):
        groove = self.selected_groove.get()
        selected = self._get_all_selected_sensors()

        if not selected:
            self._show_summary_window(
                (
                    f"Wybrany rowek: {groove}\n\nNie zaznaczono zadnego sensora."
                    if groove
                    else "Nie zaznaczono zadnego sensora."
                )
            )
            return

        header = f"Wybrany rowek: {groove}\n\n" if groove else ""
        summary = header + "Dopasowane sensory:\n\n- " + "\n\n- ".join(
            f"{item['groove']} -> {item['name']}\n{item['link']}" if item["link"] else f"{item['groove']} -> {item['name']}"
            for item in selected
        )
        self._show_summary_window(summary)
        self.update_summary_text()

    def _show_summary_window(self, summary_text):
        summary_window = tk.Toplevel(self)
        summary_window.title("Podsumowanie")
        summary_window.geometry("760x520")
        summary_window.minsize(620, 420)
        summary_window.transient(self)

        container = ttk.Frame(summary_window, padding=12)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="Podsumowanie do skopiowania",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 8))

        text_frame = ttk.Frame(container)
        text_frame.pack(fill="both", expand=True)

        text_widget = tk.Text(
            text_frame,
            wrap="word",
            font=("Consolas", 10),
            undo=False,
        )
        text_widget.insert("1.0", summary_text)
        text_widget.focus_set()

        scrollbar = ttk.Scrollbar(text_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=scrollbar.set)

        text_widget.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        button_frame = ttk.Frame(container)
        button_frame.pack(fill="x", pady=(10, 0))

        ttk.Button(
            button_frame,
            text="Kopiuj do schowka",
            command=lambda: self._copy_summary_to_clipboard(summary_text),
        ).pack(side="left")

        ttk.Button(
            button_frame,
            text="Zamknij",
            command=summary_window.destroy,
        ).pack(side="right")

    def _copy_summary_to_clipboard(self, summary_text):
        self.clipboard_clear()
        self.clipboard_append(summary_text)
        self.update()

    def clear_selection(self):
        self.selected_groove.set("")
        self.selected_sensor_keys.clear()
        self.current_photo = None
        self.current_note_photo = None
        self._cleanup_temp_image("_temp_image_path")
        self._cleanup_temp_image("_temp_note_image_path")
        self.image_label.config(
            text=(
                "Tutaj bedzie wyswietlane zdjecie wybranego rowka.\n\n"
                "Program szuka plikow w folderze images (.png, .jpg, .jpeg, .gif)."
            ),
            image="",
        )

        for widget in self.sensor_list_frame.winfo_children():
            widget.destroy()

        self.checkbox_vars.clear()
        self.current_sensor_name.set("Brak wybranego sensora")
        self.note_image_label.config(
            text="Tutaj bedzie wyswietlane zdjecie wybranego elementu.",
            image="",
        )
        self.note_label.config(
            text=(
                "Po wybraniu sensora tutaj pojawia sie notatka z dodatkowymi "
                "szczegolami i wskazowkami doboru."
            )
        )
        self.result_label.config(text="Wybierz typ rowka i zaznacz sensory checkboxem.")

    @staticmethod
    def open_link(url):
        if not url:
            messagebox.showwarning("Brak linku", "Ten sensor nie ma przypisanego linku.")
            return

        try:
            if webbrowser.open_new_tab(url):
                return
        except Exception:
            pass

        try:
            os.startfile(url)
            return
        except OSError:
            messagebox.showerror(
                "Blad otwierania linku",
                f"Nie udalo sie otworzyc linku:\n{url}",
            )

    @staticmethod
    def _get_sensor_name(sensor):
        if isinstance(sensor, str):
            return sensor

        if not isinstance(sensor, dict):
            return str(sensor)

        for key in ("name", "nazwa", "sensor", "sensor_name", "title", "label"):
            value = sensor.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        for value in sensor.values():
            if isinstance(value, str) and value.strip():
                return value.strip()

        return "Sensor bez nazwy"

    @staticmethod
    def _get_sensor_link(sensor):
        if isinstance(sensor, dict):
            for key in ("link", "url", "href"):
                value = sensor.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return ""

    @staticmethod
    def _get_sensor_note(sensor):
        if isinstance(sensor, dict):
            for key in ("note", "notatka", "opis", "details", "description"):
                value = sensor.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        return "Brak dodatkowej notatki dla tego sensora."

    def _make_sensor_key(self, groove, sensor):
        return groove, self._get_sensor_name(sensor)

    def _get_all_selected_sensors(self):
        selected = []

        for groove, sensors in SENSOR_DB.items():
            for sensor in sensors:
                sensor_key = self._make_sensor_key(groove, sensor)
                if sensor_key in self.selected_sensor_keys:
                    selected.append(
                        {
                            "groove": groove,
                            "name": self._get_sensor_name(sensor),
                            "link": self._get_sensor_link(sensor),
                            "sensor": sensor,
                        }
                    )

        return selected

    def _get_sensor_note_image(self, sensor):
        if isinstance(sensor, dict):
            for key in ("note_image", "image", "photo", "img"):
                value = sensor.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()

        sensor_name = self._get_sensor_name(sensor)
        auto_image = self._find_sensor_image_by_name(sensor_name)
        if auto_image:
            return auto_image

        return SENSOR_NOTE_IMAGES.get(sensor_name, "")

    def _find_sensor_image_by_name(self, sensor_name):
        if not sensor_name:
            return ""

        candidates = []
        cleaned_name = sensor_name.strip()
        candidates.append(cleaned_name)

        if " - " in cleaned_name:
            candidates.append(cleaned_name.split(" - ", 1)[0].strip())

        unique_candidates = []
        seen = set()
        for candidate in candidates:
            key = candidate.lower()
            if key and key not in seen:
                seen.add(key)
                unique_candidates.append(candidate)

        for candidate in unique_candidates:
            for extension in SUPPORTED_IMAGE_EXTENSIONS:
                direct_path = IMAGES_DIR / f"{candidate}{extension}"
                if direct_path.exists():
                    return f"images/{direct_path.name}"

                lower_path = IMAGES_DIR / f"{candidate.lower()}{extension}"
                if lower_path.exists():
                    return f"images/{lower_path.name}"

                upper_path = IMAGES_DIR / f"{candidate.upper()}{extension}"
                if upper_path.exists():
                    return f"images/{upper_path.name}"

        return ""


if __name__ == "__main__":
    app = SensorConfiguratorApp()
    app.mainloop()

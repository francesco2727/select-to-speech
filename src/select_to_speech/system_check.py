"""System dependencies checker"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import pyaudio
except ImportError:
    pyaudio = None

# Configure basic console logging for the system check
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


_CHECK_MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "title": "SELECT-TO-SPEECH - SYSTEM DEPENDENCIES CHECK",
        "req_header": "--- System Dependencies (Required for core functionality) ---",
        "opt_ocr_header": "\n--- Optional Dependencies: Screen Text Recognition (OCR - Alt+R) ---",
        "opt_xwayland_header": "\n--- Optional Dependencies: XWayland Applications Compatibility ---",
        "install_header": "INSTALLATION INSTRUCTIONS (ARCH LINUX)",
        "install_header_win": "INSTALLATION INSTRUCTIONS (WINDOWS)",
        "purpose_label": "Why needed:",
        "missing_req_tag": "[MISSING - REQUIRED]",
        "missing_opt_tag": "[MISSING - OPTIONAL]",
        "package_label": "package:",
        "packages_label": "packages:",
        "library_label": "system library",
        "langs_detected_label": "detected languages:",
        "missing_req_summary": "[✗] Missing REQUIRED dependencies:",
        "missing_opt_summary": "[⚠] Missing OPTIONAL dependencies (reduced OCR or XWayland functionality):",
        "req_cmd_hint": "👉 Installation command for required dependencies:",
        "opt_cmd_hint": "👉 Command to enable all optional features (OCR + XWayland):",
        "opt_cmd_hint_win": "👉 Command to enable OCR on Windows:",
        "all_ok_msg": "\n✓ All required system dependencies are correctly installed!\n",
        "desc_wl": "Allows intercepting and reading selected or copied text in native Wayland environments.",
        "desc_tray": "System library required by the Flutter GUI to display the icon and menu in the Linux system tray.",
        "desc_tess": "Core OCR engine required to extract and read text directly from a screen area or screenshot.",
        "desc_langs": "Language packs and models (e.g. Italian and English) required by Tesseract OCR to recognize words and characters.",
        "desc_spectacle": "Primary screen capture tool on KDE Wayland environments to select the screen rectangle for OCR reading.",
        "desc_slurp_grim": "Fallback screen capture and selection tools on wlroots-based Wayland environments (e.g. Sway, Hyprland).",
        "desc_win_capture": "Screen capture tools on Windows (Snipping Tool or Pillow).",
        "desc_ocr_missing": "Required to draw and capture the rectangular screen region during OCR reading (Alt+R).",
        "desc_ocr_missing_summary": "Screen capture tools (KDE or wlroots).",
        "desc_xclip": "Allows intercepting and reading selected text inside non-native XWayland applications (e.g. legacy X11 programs).",
    },
    "it": {
        "title": "SELECT-TO-SPEECH - CONTROLLO DIPENDENZE DI SISTEMA",
        "req_header": "--- Dipendenze di Sistema (Richieste per il funzionamento core) ---",
        "opt_ocr_header": "\n--- Dipendenze Opzionali: Riconoscimento Testo da Schermo (OCR - Alt+R) ---",
        "opt_xwayland_header": "\n--- Dipendenze Opzionali: Compatibilità Applicazioni XWayland ---",
        "install_header": "ISTRUZIONI PER L'INSTALLAZIONE (ARCH LINUX)",
        "install_header_win": "ISTRUZIONI PER L'INSTALLAZIONE (WINDOWS)",
        "purpose_label": "A cosa serve:",
        "missing_req_tag": "[MANCANTE - RICHIESTO]",
        "missing_opt_tag": "[MANCANTE - OPZIONALE]",
        "package_label": "pacchetto:",
        "packages_label": "pacchetti:",
        "library_label": "libreria di sistema",
        "langs_detected_label": "lingue rilevate:",
        "missing_req_summary": "[✗] Dipendenze RICHIESTE mancanti:",
        "missing_opt_summary": "[⚠] Dipendenze OPZIONALI mancanti (funzionalità OCR o XWayland ridotte):",
        "req_cmd_hint": "👉 Comando di installazione per le dipendenze richieste:",
        "opt_cmd_hint": "👉 Comando per abilitare tutte le funzionalità opzionali (OCR + XWayland):",
        "opt_cmd_hint_win": "👉 Comando per abilitare l'OCR su Windows:",
        "all_ok_msg": "\n✓ Tutte le dipendenze di sistema richieste sono correttamente installate!\n",
        "desc_wl": "Permette l'intercettazione e la lettura del testo selezionato o copiato negli ambienti nativi Wayland.",
        "desc_tray": "Libreria di sistema necessaria all'interfaccia grafica Flutter per mostrare l'icona e il menu nella system tray di Linux.",
        "desc_tess": "Motore OCR di base necessario per estrarre e leggere il testo direttamente da un'area o screenshot dello schermo.",
        "desc_langs": "Pacchetti e modelli linguistici (es. italiano e inglese) necessari al motore OCR Tesseract per riconoscere le parole e i caratteri.",
        "desc_spectacle": "Strumento principale di cattura schermo su ambienti KDE Wayland per selezionare il rettangolo di schermo da leggere con l'OCR.",
        "desc_slurp_grim": "Strumenti di cattura schermo e selezione area di fallback su ambienti Wayland basati su wlroots (es. Sway, Hyprland).",
        "desc_win_capture": "Strumenti di cattura schermo su Windows (Strumento di cattura o Pillow).",
        "desc_ocr_missing": "Necessario per disegnare e catturare l'area rettangolare dello schermo durante la lettura OCR (Alt+R).",
        "desc_ocr_missing_summary": "Strumenti per la cattura dell'area di schermo (KDE o wlroots).",
        "desc_xclip": "Consente di intercettare e leggere il testo selezionato all'interno di applicazioni XWayland non native (es. vecchi programmi X11).",
    },
    "fr": {
        "title": "SELECT-TO-SPEECH - VÉRIFICATION DES DÉPENDANCES SYSTÈME",
        "req_header": "--- Dépendances Système (Requises pour le fonctionnement de base) ---",
        "opt_ocr_header": "\n--- Dépendances Optionnelles : Reconnaissance de texte à l'écran (OCR - Alt+R) ---",
        "opt_xwayland_header": "\n--- Dépendances Optionnelles : Compatibilité applications XWayland ---",
        "install_header": "INSTRUCTIONS D'INSTALLATION (ARCH LINUX)",
        "install_header_win": "INSTRUCTIONS D'INSTALLATION (WINDOWS)",
        "purpose_label": "À quoi ça sert :",
        "missing_req_tag": "[MANQUANT - REQUIS]",
        "missing_opt_tag": "[MANQUANT - OPTIONNEL]",
        "package_label": "paquet :",
        "packages_label": "paquets :",
        "library_label": "bibliothèque système",
        "langs_detected_label": "langues détectées :",
        "missing_req_summary": "[✗] Dépendances REQUISES manquantes :",
        "missing_opt_summary": "[⚠] Dépendances OPTIONNELLES manquantes (fonctionnalités OCR ou XWayland réduites) :",
        "req_cmd_hint": "👉 Commande d'installation pour les dépendances requises :",
        "opt_cmd_hint": "👉 Commande pour activer toutes les fonctionnalités optionnelles (OCR + XWayland) :",
        "opt_cmd_hint_win": "👉 Commande pour activer l'OCR sur Windows :",
        "all_ok_msg": "\n✓ Toutes les dépendances système requises sont correctement installées !\n",
        "desc_wl": "Permet d'intercepter et de lire le texte sélectionné ou copié dans les environnements Wayland natifs.",
        "desc_tray": "Bibliothèque système requise par l'interface Flutter pour afficher l'icône et le menu dans la barre d'état système Linux.",
        "desc_tess": "Moteur OCR de base requis pour extraire et lire le texte directement depuis une zone d'écran ou une capture.",
        "desc_langs": "Paquets et modèles linguistiques (ex. italien et anglais) requis par Tesseract OCR pour reconnaître les mots et caractères.",
        "desc_spectacle": "Outil de capture d'écran principal sur KDE Wayland pour sélectionner le rectangle d'écran à lire par OCR.",
        "desc_slurp_grim": "Outils de capture d'écran et de sélection de secours sur les environnements Wayland basés sur wlroots (ex. Sway, Hyprland).",
        "desc_win_capture": "Outils de capture d'écran sur Windows (Outil Capture d'écran ou Pillow).",
        "desc_ocr_missing": "Requis pour dessiner et capturer la zone rectangulaire de l'écran lors de la lecture OCR (Alt+R).",
        "desc_ocr_missing_summary": "Outils de capture d'écran (KDE ou wlroots).",
        "desc_xclip": "Permet d'intercepter et de lire le texte sélectionné dans les applications XWayland non natives (ex. anciens programmes X11).",
    },
    "es": {
        "title": "SELECT-TO-SPEECH - VERIFICACIÓN DE DEPENDENCIAS DEL SISTEMA",
        "req_header": "--- Dependencias del Sistema (Requeridas para el funcionamiento principal) ---",
        "opt_ocr_header": "\n--- Dependencias Opcionales: Reconocimiento de texto en pantalla (OCR - Alt+R) ---",
        "opt_xwayland_header": "\n--- Dependencias Opcionales: Compatibilidad con aplicaciones XWayland ---",
        "install_header": "INSTRUCCIONES DE INSTALACIÓN (ARCH LINUX)",
        "install_header_win": "INSTRUCCIONES DE INSTALACIÓN (WINDOWS)",
        "purpose_label": "Para qué sirve:",
        "missing_req_tag": "[FALTANTE - REQUERIDO]",
        "missing_opt_tag": "[FALTANTE - OPCIONAL]",
        "package_label": "paquete:",
        "packages_label": "paquetes:",
        "library_label": "librería del sistema",
        "langs_detected_label": "idiomas detectados:",
        "missing_req_summary": "[✗] Dependencias REQUERIDAS faltantes:",
        "missing_opt_summary": "[⚠] Dependencias OPCIONALES faltantes (funcionalidades OCR o XWayland reducidas):",
        "req_cmd_hint": "👉 Comando de instalación para las dependencias requeridas:",
        "opt_cmd_hint": "👉 Comando para habilitar todas las funcionalidades opcionales (OCR + XWayland):",
        "opt_cmd_hint_win": "👉 Comando para habilitar OCR en Windows:",
        "all_ok_msg": "\n✓ ¡Todas las dependencias del sistema requeridas están correctamente instaladas!\n",
        "desc_wl": "Permite interceptar y leer el texto seleccionado o copiado en entornos nativos de Wayland.",
        "desc_tray": "Librería del sistema requerida por la interfaz gráfica Flutter para mostrar el icono y el menú en la bandeja del sistema de Linux.",
        "desc_tess": "Motor OCR básico requerido para extraer y leer texto directamente desde un área de pantalla o captura.",
        "desc_langs": "Paquetes y modelos lingüísticos (ej. italiano e inglés) requeridos por el motor OCR Tesseract para reconocer palabras y caracteres.",
        "desc_spectacle": "Herramienta principal de captura de pantalla en entornos KDE Wayland para seleccionar el rectángulo de pantalla para lectura OCR.",
        "desc_slurp_grim": "Herramientas de captura y selección de pantalla de respaldo en entornos Wayland basados en wlroots (ej. Sway, Hyprland).",
        "desc_win_capture": "Herramientas de captura de pantalla en Windows (Herramienta Recortes o Pillow).",
        "desc_ocr_missing": "Requerido para dibujar y capturar el área rectangular de la pantalla durante la lectura OCR (Alt+R).",
        "desc_ocr_missing_summary": "Herramientas para la captura del área de pantalla (KDE o wlroots).",
        "desc_xclip": "Permite interceptar y leer el texto seleccionado dentro de aplicaciones XWayland no nativas (ej. programas X11 antiguos).",
    },
}


def _detect_language(lang_override: str | None = None) -> str:
    """Detect system language or return requested override, falling back to English."""
    if lang_override is not None:
        code = lang_override.split("_")[0].split(".")[0].lower()
        return code if code in _CHECK_MESSAGES else "en"
    for env_var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(env_var, "").strip()
        if val:
            prefix = val.split("_")[0].split(".")[0].lower()
            if prefix in _CHECK_MESSAGES:
                return prefix
    try:
        import locale
        loc = locale.getlocale(locale.LC_MESSAGES)[0] or locale.getlocale()[0]
        if loc:
            prefix = loc.split("_")[0].split(".")[0].lower()
            if prefix in _CHECK_MESSAGES:
                return prefix
    except Exception:
        pass
    return "en"


def _check_appindicator() -> bool:
    """Check if libayatana-appindicator or libappindicator is installed for system tray support."""
    try:
        if subprocess.run(["pacman", "-Qi", "libayatana-appindicator"], capture_output=True).returncode == 0:
            return True
        if subprocess.run(["pacman", "-Qi", "libappindicator-gtk3"], capture_output=True).returncode == 0:
            return True
    except Exception:
        pass
    for path in ["/usr/lib/libayatana-appindicator3.so", "/usr/lib/libappindicator3.so", "/lib/x86_64-linux-gnu/libayatana-appindicator3.so"]:
        if Path(path).exists() or list(Path("/usr/lib").glob("*appindicator*.so*")):
            return True
    return False


def _find_tesseract_cmd() -> str | None:
    """Find tesseract executable across Linux or Windows."""
    from .ocr_engine import OcrEngine
    return OcrEngine().get_tesseract_cmd()


def check_system_dependencies(lang: str | None = None) -> bool:
    """
    Check for required and optional system dependencies with clear explanations of their purpose.

    Args:
        lang: Optional language code ('en', 'it', 'fr', 'es'). If None, detected from system environment.

    Returns:
        True if all *required* dependencies are found, False otherwise
    """
    lang_code = _detect_language(lang)
    msg = _CHECK_MESSAGES[lang_code]
    is_windows = sys.platform == "win32"

    logger.info("\n==================================================================")
    logger.info(f"           {msg['title']}")
    logger.info("==================================================================\n")

    missing_required = []
    missing_optional = []

    # 1. Required Core Dependencies
    logger.info(msg["req_header"])
    
    if not is_windows:
        # Linux: wl-clipboard
        desc_wl = msg["desc_wl"]
        if shutil.which("wl-paste"):
            logger.info(f"  ✓ wl-paste ({msg['package_label']} wl-clipboard)")
            logger.info(f"    └─ {msg['purpose_label']} {desc_wl}")
        else:
            logger.error(f"  ✗ wl-paste ({msg['package_label']} wl-clipboard) {msg['missing_req_tag']}")
            logger.error(f"    └─ {msg['purpose_label']} {desc_wl}")
            missing_required.append(("wl-paste", "wl-clipboard", desc_wl))

        # Linux: libayatana-appindicator
        desc_tray = msg["desc_tray"]
        if _check_appindicator():
            logger.info(f"  ✓ libayatana-appindicator ({msg['library_label']})")
            logger.info(f"    └─ {msg['purpose_label']} {desc_tray}")
        else:
            logger.error(f"  ✗ libayatana-appindicator ({msg['package_label']} libayatana-appindicator) {msg['missing_req_tag']}")
            logger.error(f"    └─ {msg['purpose_label']} {desc_tray}")
            missing_required.append(("libayatana-appindicator", "libayatana-appindicator", desc_tray))
    else:
        logger.info("  ✓ Windows native clipboard & Win32 system tray support")

    # 2. Optional OCR & Screen Capture Dependencies
    logger.info(msg["opt_ocr_header"])

    # tesseract binary
    desc_tess = msg["desc_tess"]
    tess_cmd = _find_tesseract_cmd()
    has_tess = tess_cmd is not None
    tess_pkg_name = "UB-Mannheim.TesseractOCR" if is_windows else "tesseract"

    if has_tess:
        logger.info(f"  ✓ tesseract ({msg['package_label']} {tess_pkg_name})")
        logger.info(f"    └─ {msg['purpose_label']} {desc_tess}")
    else:
        logger.warning(f"  ⚠ tesseract ({msg['package_label']} {tess_pkg_name}) {msg['missing_opt_tag']}")
        logger.warning(f"    └─ {msg['purpose_label']} {desc_tess}")
        missing_optional.append(("tesseract", tess_pkg_name, desc_tess))

    # tesseract language packs
    desc_langs = msg["desc_langs"]
    if has_tess:
        try:
            res = subprocess.run(
                [tess_cmd, "--list-langs"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if res.returncode == 0:
                lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
                langs = {
                    l for l in lines
                    if not l.lower().startswith("list of") and l.lower() != "osd"
                }
                if "ita" in langs or "eng" in langs:
                    logger.info(f"  ✓ tesseract language packs ({msg['langs_detected_label']} {', '.join(sorted(langs))})")
                    logger.info(f"    └─ {msg['purpose_label']} {desc_langs}")
                else:
                    langs_pkg = "UB-Mannheim.TesseractOCR" if is_windows else "tesseract-data-ita tesseract-data-eng"
                    logger.warning(f"  ⚠ tesseract language packs ({msg['packages_label']} {langs_pkg}) {msg['missing_opt_tag']}")
                    logger.warning(f"    └─ {msg['purpose_label']} {desc_langs}")
                    missing_optional.append(("tesseract language packs", langs_pkg, desc_langs))
        except Exception:
            pass
    else:
        langs_pkg = "UB-Mannheim.TesseractOCR" if is_windows else "tesseract-data-ita tesseract-data-eng"
        logger.warning(f"  ⚠ tesseract language packs ({msg['packages_label']} {langs_pkg}) {msg['missing_opt_tag']}")
        logger.warning(f"    └─ {msg['purpose_label']} {desc_langs}")
        missing_optional.append(("tesseract language packs", langs_pkg, desc_langs))

    # Screen capture tools
    if is_windows:
        from .screen_capture import ScreenCapture
        has_win_cap = ScreenCapture.is_windows_capture_available()
        desc_win_cap = msg["desc_win_capture"]
        if has_win_cap:
            logger.info("  ✓ Windows screen clipping / Snipping Tool")
            logger.info(f"    └─ {msg['purpose_label']} {desc_win_cap}")
    else:
        has_spectacle = shutil.which("spectacle") is not None
        has_grim_slurp = shutil.which("grim") is not None and shutil.which("slurp") is not None
        desc_spectacle = msg["desc_spectacle"]
        desc_slurp_grim = msg["desc_slurp_grim"]

        if has_spectacle:
            logger.info(f"  ✓ spectacle ({msg['package_label']} spectacle)")
            logger.info(f"    └─ {msg['purpose_label']} {desc_spectacle}")
        elif has_grim_slurp:
            logger.info(f"  ✓ slurp & grim ({msg['packages_label']} slurp grim)")
            logger.info(f"    └─ {msg['purpose_label']} {desc_slurp_grim}")
        else:
            logger.warning(f"  ⚠ spectacle (slurp + grim) ({msg['packages_label']} spectacle slurp grim) {msg['missing_opt_tag']}")
            logger.warning(f"    └─ {msg['purpose_label']} {msg['desc_ocr_missing']}")
            missing_optional.append(("spectacle (slurp+grim)", "spectacle slurp grim", msg["desc_ocr_missing_summary"]))

    # 3. Optional XWayland Compatibility (Linux only)
    if not is_windows:
        logger.info(msg["opt_xwayland_header"])
        desc_xclip = msg["desc_xclip"]
        if shutil.which("xclip"):
            logger.info(f"  ✓ xclip ({msg['package_label']} xclip)")
            logger.info(f"    └─ {msg['purpose_label']} {desc_xclip}")
        else:
            logger.warning(f"  ⚠ xclip ({msg['package_label']} xclip) {msg['missing_opt_tag']}")
            logger.warning(f"    └─ {msg['purpose_label']} {desc_xclip}")
            missing_optional.append(("xclip", "xclip", desc_xclip))

    # Summary & Installation instructions
    if missing_required or missing_optional:
        header = msg["install_header_win"] if is_windows else msg["install_header"]
        logger.info("\n==================================================================")
        logger.info(f"           {header}")
        logger.info("==================================================================")
        
        if missing_required:
            req_pkgs = sorted(list(set(pkg for _, pkg, _ in missing_required)))
            logger.error(f"\n{msg['missing_req_summary']}")
            for cmd, pkg, desc in missing_required:
                logger.error(f"  • {cmd} ({pkg})")
                logger.error(f"    └─ {msg['purpose_label']} {desc}")
            logger.error(f"\n  {msg['req_cmd_hint']}")
            if not is_windows:
                logger.error(f"     sudo pacman -S {' '.join(req_pkgs)}")

        if missing_optional:
            logger.warning(f"\n{msg['missing_opt_summary']}")
            for cmd, pkg, desc in missing_optional:
                logger.warning(f"  • {cmd} ({pkg})")
                logger.warning(f"    └─ {msg['purpose_label']} {desc}")
            if is_windows:
                logger.warning(f"\n  {msg['opt_cmd_hint_win']}")
                logger.warning("     winget install UB-Mannheim.TesseractOCR")
            else:
                all_opt = []
                for _, pkg, _ in missing_optional:
                    all_opt.extend(pkg.split())
                all_opt = sorted(list(set(all_opt)))
                logger.warning(f"\n  {msg['opt_cmd_hint']}")
                logger.warning(f"     sudo pacman -S {' '.join(all_opt)}")
        logger.info("")

    if missing_required:
        return False

    logger.info(msg["all_ok_msg"])
    return True


def get_audio_devices() -> list[dict]:
    """Return structured list of audio output devices.

    Returns:
        List of dicts with keys: id, name, channels, sample_rate, is_default
    """
    devices: list[dict] = []
    if not pyaudio:
        return devices

    try:
        p = pyaudio.PyAudio()
    except OSError:
        return devices

    try:
        try:
            default_info = p.get_default_output_device_info()
            default_name = default_info["name"] if default_info else None
        except OSError:
            default_name = None

        for i in range(p.get_device_count()):
            try:
                info = p.get_device_info_by_index(i)
            except OSError:
                continue

            if info["maxOutputChannels"] > 0:
                devices.append({
                    "id": i,
                    "name": info["name"],
                    "channels": info["maxOutputChannels"],
                    "sample_rate": int(info["defaultSampleRate"]),
                    "is_default": info["name"] == default_name,
                })
    finally:
        p.terminate()

    return devices


def list_audio_devices() -> None:
    """List all available audio output devices"""
    devices = get_audio_devices()
    if not devices:
        logger.error("PyAudio not available or no output devices found")
        return

    logger.info("\n=== Available Audio Output Devices ===\n")

    for dev in devices:
        default_tag = " [DEFAULT]" if dev["is_default"] else ""
        logger.info(f"Device {dev['id']}: {dev['name']}{default_tag}")
        logger.info(f"  Channels: {dev['channels']}")
        logger.info(f"  Sample Rate: {dev['sample_rate']} Hz\n")

    logger.info("To use a specific device, edit ~/.config/select-to-speech/config.yaml:")
    logger.info("  audio:")
    logger.info("    device_id: <device_number>\n")


def main_audio_devices(argv: list[str] | None = None) -> int:
    """CLI entry point for select-to-speech-audio console script."""
    import argparse

    parser = argparse.ArgumentParser(description="List Select-to-Speech audio output devices")
    parser.parse_args(argv)
    list_audio_devices()
    return 0


def main_check(lang: str | None = None) -> int:
    """CLI entry point for select-to-speech-check console script."""
    if lang is None:
        import argparse
        parser = argparse.ArgumentParser(description="Select-to-Speech system checker")
        parser.add_argument("--lang", choices=["en", "it", "fr", "es"], help="Override language for system check output (default: system locale or en)")
        args, _ = parser.parse_known_args()
        lang = args.lang
    is_ok = check_system_dependencies(lang=lang)
    return 0 if is_ok else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Select-to-Speech system checker")
    parser.add_argument("--audio-devices", action="store_true", help="List audio devices")
    parser.add_argument("--lang", choices=["en", "it", "fr", "es"], help="Override language for system check output (default: system locale or en)")
    
    args, _ = parser.parse_known_args()

    if args.audio_devices:
        list_audio_devices()
    else:
        sys.exit(main_check(lang=args.lang))

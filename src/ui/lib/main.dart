import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'package:dynamic_color/dynamic_color.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:tray_manager/tray_manager.dart' as tray;

import 'language_names.dart';

final ValueNotifier<ThemeMode> themeModeNotifier =
    ValueNotifier(ThemeMode.system);
final ValueNotifier<Color?> systemAccentColorNotifier = ValueNotifier(null);

const Color kDefaultSeedColor = Color(0xFF7B61FF);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  unawaited(_initLinuxAccentColorWatcher());
  await startPythonBackend();
  runApp(const SelectToSpeechApp());
}

/// Detects the system accent color on Linux desktops (XDG Desktop Portal / KDE Plasma kdeglobals)
/// as a complement to `DynamicColorBuilder` (which reads GTK / Windows / macOS accent colors).
Future<void> _initLinuxAccentColorWatcher() async {
  if (!Platform.isLinux) return;

  Future<void> refreshAccent() async {
    final color = await _detectLinuxSystemAccentColor();
    if (color != null && systemAccentColorNotifier.value != color) {
      systemAccentColorNotifier.value = color;
    }
  }

  await refreshAccent();

  // Watch ~/.config/kdeglobals if present so live KDE Plasma accent color changes apply immediately
  try {
    final homeDir = Platform.environment['HOME'] ?? '';
    if (homeDir.isNotEmpty) {
      final configDir = Directory('$homeDir/.config');
      if (configDir.existsSync()) {
        configDir
            .watch(
                events: FileSystemEvent.modify |
                    FileSystemEvent.move |
                    FileSystemEvent.create)
            .listen((event) {
          if (event.path.endsWith('kdeglobals') ||
              event.path.endsWith('gtk.css')) {
            refreshAccent();
          }
        });
      }
    }
  } catch (_) {}
}

Future<Color?> _detectLinuxSystemAccentColor() async {
  // 1. Try XDG Desktop Portal (supported by GNOME 42+, KDE Plasma 5.25+, Cosmic, etc.)
  try {
    final result = await Process.run(
      'gdbus',
      [
        'call',
        '--session',
        '--dest',
        'org.freedesktop.portal.Desktop',
        '--object-path',
        '/org/freedesktop/portal/desktop',
        '--method',
        'org.freedesktop.portal.Settings.Read',
        'org.freedesktop.appearance',
        'accent-color',
      ],
    ).timeout(const Duration(milliseconds: 800));

    if (result.exitCode == 0) {
      final out = result.stdout.toString();
      final match =
          RegExp(r'\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\)')
              .firstMatch(out);
      if (match != null) {
        final r = double.tryParse(match.group(1)!);
        final g = double.tryParse(match.group(2)!);
        final b = double.tryParse(match.group(3)!);
        if (r != null &&
            g != null &&
            b != null &&
            r >= 0.0 &&
            r <= 1.0 &&
            g >= 0.0 &&
            g <= 1.0 &&
            b >= 0.0 &&
            b <= 1.0) {
          return Color.fromARGB(
            255,
            (r * 255).round().clamp(0, 255),
            (g * 255).round().clamp(0, 255),
            (b * 255).round().clamp(0, 255),
          );
        }
      }
    }
  } catch (_) {}

  // 2. Fallback: read ~/.config/kdeglobals for KDE Plasma
  try {
    final homeDir = Platform.environment['HOME'] ?? '';
    if (homeDir.isNotEmpty) {
      final kdeFile = File('$homeDir/.config/kdeglobals');
      if (kdeFile.existsSync()) {
        final lines = await kdeFile.readAsLines();
        for (final key in ['AccentColor=', 'DecorationFocus=']) {
          for (final line in lines) {
            final trimmed = line.trim();
            if (trimmed.startsWith(key)) {
              final parts = trimmed.substring(key.length).split(',');
              if (parts.length >= 3) {
                final r = int.tryParse(parts[0].trim());
                final g = int.tryParse(parts[1].trim());
                final b = int.tryParse(parts[2].trim());
                if (r != null && g != null && b != null) {
                  return Color.fromARGB(
                      255, r.clamp(0, 255), g.clamp(0, 255), b.clamp(0, 255));
                }
              }
            }
          }
        }
      }
    }
  } catch (_) {}

  return null;
}

Process? pythonBackend;
bool _shuttingDown = false;
String? _backendPath;
int _restartCount = 0;
DateTime? _firstRestartTime;
const int _maxRestartsInWindow = 5;
const Duration _restartWindow = Duration(seconds: 60);
const Duration _restartDelay = Duration(seconds: 3);

Future<void> startPythonBackend() async {
  // The backend creates its socket only once it is listening: if the file is missing
  // no backend is running, so skip the probe and launch it right away.
  // If it exists, probe it (it may be a stale socket left by a crashed backend).
  final client = createUdsClient();
  try {
    for (int i = 0; File(udsSocketPath()).existsSync() && i < 3; i++) {
      try {
        final res = await client
            .get(Uri.parse('http://localhost/status'))
            .timeout(const Duration(milliseconds: 1000));
        if (res.statusCode == 200) {
          debugPrint('Python backend is already running.');
          return;
        }
      } on TimeoutException {
        // Something accepted the connection but is slow to answer: retry.
        if (i < 2) {
          await Future.delayed(const Duration(milliseconds: 500));
        }
      } catch (_) {
        // Connection refused (wrapped in http.ClientException): stale socket,
        // nobody is listening.
        break;
      }
    }
  } finally {
    client.close();
  }

  if (_backendPath == null) {
    // resolvedExecutable has symlinks resolved, so this also works when the GUI is
    // started via /usr/bin/select-to-speech-gui.
    final String executablePath = Platform.resolvedExecutable;
    final String exeDir = File(executablePath).parent.path;

    // Native packages: /usr/lib/select-to-speech/{gui,backend}/
    final packagedBackend =
        '${File(exeDir).parent.path}/backend/select-to-speech';
    if (File(packagedBackend).existsSync()) {
      _backendPath = packagedBackend;
    }

    // Traverse upwards to look for .venv or local binary
    if (_backendPath == null) {
      Directory current = Directory(executablePath).parent;
      while (current.path != '/') {
        final venvBin = '${current.path}/.venv/bin/select-to-speech';
        if (File(venvBin).existsSync()) {
          _backendPath = venvBin;
          break;
        }
        if (Directory('${current.path}/.venv').existsSync()) {
          _backendPath = venvBin;
          break;
        }
        current = current.parent;
      }
    }
  }

  if (_backendPath != null) {
    await _launchAndMonitorBackend();
  } else {
    debugPrint(
        'Warning: could not find select-to-speech backend binary or .venv');
  }
}

Future<void> _launchAndMonitorBackend() async {
  try {
    pythonBackend = await Process.start(_backendPath!, []);
    debugPrint('Python backend started with PID: ${pythonBackend?.pid}');

    // Drain stdout and stderr so that child writes never block on full pipe buffers
    pythonBackend?.stdout
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      debugPrint('[Backend] $line');
    }, onError: (e) {
      debugPrint('Backend stdout stream error: $e');
    });

    pythonBackend?.stderr
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen((line) {
      debugPrint('[Backend Error] $line');
    }, onError: (e) {
      debugPrint('Backend stderr stream error: $e');
    });

    // Monitor the process and auto-restart on unexpected exit
    pythonBackend?.exitCode.then((exitCode) async {
      debugPrint('Python backend exited with code: $exitCode');
      if (_shuttingDown) return;

      // Rate-limit restarts to avoid infinite crash loops
      final now = DateTime.now();
      if (_firstRestartTime == null ||
          now.difference(_firstRestartTime!) > _restartWindow) {
        _restartCount = 0;
        _firstRestartTime = now;
      }
      _restartCount++;

      if (_restartCount > _maxRestartsInWindow) {
        debugPrint(
            'Backend crashed $_restartCount times in ${_restartWindow.inSeconds}s. Giving up auto-restart.');
        return;
      }

      debugPrint(
          'Restarting backend in ${_restartDelay.inSeconds}s (attempt $_restartCount/$_maxRestartsInWindow)...');
      await Future.delayed(_restartDelay);
      if (!_shuttingDown) {
        await _launchAndMonitorBackend();
      }
    });
  } catch (e) {
    debugPrint('Error starting python backend: $e');
  }
}

String udsSocketPath() {
  final String homeDir = Platform.environment['HOME'] ?? '';
  return '$homeDir/.local/state/select-to-speech/ipc.sock';
}

http.Client createUdsClient() {
  final String socketPath = udsSocketPath();
  var ioClient = HttpClient()
    ..connectionFactory = (uri, proxyHost, proxyPort) {
      return Socket.startConnect(
          InternetAddress(socketPath, type: InternetAddressType.unix), 0);
    };
  return IOClient(ioClient);
}

ThemeData _buildMaterial3Theme(ColorScheme colorScheme) {
  return ThemeData(
    useMaterial3: true,
    colorScheme: colorScheme,
    fontFamily: 'Inter',
    scaffoldBackgroundColor: colorScheme.surface,
    cardTheme: CardThemeData(
      elevation: 0,
      color: colorScheme.surfaceContainerLow,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(24),
        side: BorderSide(
          color: colorScheme.outlineVariant.withValues(alpha: 0.5),
          width: 1,
        ),
      ),
    ),
    navigationDrawerTheme: NavigationDrawerThemeData(
      backgroundColor: colorScheme.surfaceContainerLow,
      indicatorColor: colorScheme.secondaryContainer,
      indicatorShape: const StadiumBorder(),
      tileHeight: 52,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: colorScheme.surfaceContainerHighest.withValues(alpha: 0.45),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: colorScheme.outlineVariant),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(
            color: colorScheme.outlineVariant.withValues(alpha: 0.7)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(14),
        borderSide: BorderSide(color: colorScheme.primary, width: 2),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
      ),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
    ),
    dividerTheme: DividerThemeData(
      color: colorScheme.outlineVariant.withValues(alpha: 0.5),
      thickness: 1,
      space: 24,
    ),
    sliderTheme: const SliderThemeData(
      trackHeight: 6,
    ),
  );
}

class SelectToSpeechApp extends StatelessWidget {
  const SelectToSpeechApp({super.key});

  @override
  Widget build(BuildContext context) {
    return DynamicColorBuilder(
      builder: (ColorScheme? lightDynamic, ColorScheme? darkDynamic) {
        return ValueListenableBuilder<Color?>(
          valueListenable: systemAccentColorNotifier,
          builder: (context, linuxAccent, _) {
            final Color effectiveSeed = linuxAccent ??
                lightDynamic?.primary ??
                darkDynamic?.primary ??
                kDefaultSeedColor;

            final ColorScheme lightScheme = ColorScheme.fromSeed(
              seedColor: effectiveSeed,
              brightness: Brightness.light,
              dynamicSchemeVariant: DynamicSchemeVariant.content,
            );
            final ColorScheme darkScheme = ColorScheme.fromSeed(
              seedColor: effectiveSeed,
              brightness: Brightness.dark,
              dynamicSchemeVariant: DynamicSchemeVariant.content,
            );

            return ValueListenableBuilder<ThemeMode>(
              valueListenable: themeModeNotifier,
              builder: (context, currentThemeMode, _) {
                return MaterialApp(
                  title: 'Select to Speech',
                  debugShowCheckedModeBanner: false,
                  themeMode: currentThemeMode,
                  themeAnimationDuration: const Duration(milliseconds: 350),
                  themeAnimationCurve: Curves.easeOutCubic,
                  theme: _buildMaterial3Theme(lightScheme),
                  darkTheme: _buildMaterial3Theme(darkScheme),
                  home: const SettingsScreen(),
                );
              },
            );
          },
        );
      },
    );
  }
}

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen>
    with WidgetsBindingObserver {
  late http.Client apiClient;

  // Tray objects are kept alive here: nativeapi frees them when they are
  // garbage collected.
  tray.TrayIcon? _trayIcon;
  tray.Menu? _trayMenu;
  tray.MenuItem? _traySettingsItem;
  tray.MenuItem? _trayQuitItem;
  DateTime? _lastSettingsOpen;
  int _selectedIndex = 0;

  bool isLoading = true;
  Map<String, dynamic>? config;
  List<dynamic> audioDevices = [];

  /// Voices of the active engine: language code → voice entries from `/voices`.
  Map<String, List<Map<String, dynamic>>> availableVoices = {};
  List<Map<String, dynamic>> installedModels = [];
  List<String> ocrLanguages = [];
  bool ocrInstalled = true;
  List<Map<String, dynamic>> availableModels = [];
  Map<String, dynamic>? hardwareInfo;

  // Download state variables
  bool isDownloading = false;
  bool isModelInstalled = true;
  double downloadProgress = 0.0;
  String downloadStatus = 'idle';
  String? downloadError;
  // What is being downloaded: a Kokoro model or a Piper voice
  String? downloadEngine;
  String? downloadModelId;

  // Neural punctuation state
  bool isPunctInstalled = false;
  bool isPunctDownloading = false;
  double punctDownloadProgress = 0.0;
  String punctDownloadStatus = 'idle';

  Timer? _saveTimer;

  static const Map<String, Map<String, String>> translations = {
    'en': {
      'app_title': 'Select to Speech',
      'settings': 'Settings',
      'quit': 'Quit',
      'failed_connect': 'Failed to connect to backend',
      'retry': 'Retry',
      'tab_voice': 'Voice',
      'tab_audio': 'Audio',
      'tab_ocr': 'OCR',
      'tab_shortcuts': 'Shortcuts',
      'tab_general': 'General',
      'save_settings': 'Save Settings',
      'voice_config': 'Voice Configuration',
      'voice_model': 'Voice Model',
      'default_language': 'Default Language',
      'download': 'Download',
      'downloading': 'Downloading...',
      'preparing_download': 'Preparing download...',
      'error': 'Error',
      'language_voices': 'Language Voices',
      'audio_settings': 'Audio Settings',
      'output_device': 'Output Device',
      'default_device': 'Default System Device',
      'speed': 'Speed',
      'pitch': 'Pitch',
      'volume': 'Volume',
      'keyboard_shortcuts': 'Keyboard Shortcuts',
      'ocr_settings': 'OCR Settings',
      'ocr_language': 'Tesseract Language',
      'modifier_key': 'Modifier Key',
      'trigger_key': 'Trigger Key (e.g. esc)',
      'pause_key': 'Pause/Resume Key (e.g. w)',
      'stop_key': 'Stop Key (e.g. s)',
      'ocr_key': 'OCR Key',
      'general_settings': 'General Settings',
      'appearance': 'Appearance',
      'performance': 'Performance',
      'text_processing': 'Text Processing',
      'diagnostics': 'Diagnostics',
      'gui_language': 'GUI Language',
      'enable_debug': 'Enable Debug Logging',
      'check_logs': 'Check logs at ~/.local/state/select-to-speech/app.log',
      'save_success': 'Settings saved successfully!',
      'save_failed': 'Failed to save settings',
      'download_success': 'Model downloaded successfully!',
      'download_failed': 'Download failed',
      'none_disabled': 'None / Disabled',
      'lang_auto': 'System Default',
      'lang_en': 'English',
      'lang_it': 'Italian',
      'lang_es': 'Spanish',
      'lang_fr': 'French',
      'lang_pt': 'Portuguese',
      'lang_hi': 'Hindi',
      'lang_ja': 'Japanese',
      'lang_zh': 'Chinese',
      'voice_lang_template': '{lang} Voice',
      'tts_engine': 'Speech Engine',
      'engine_kokoro_desc':
          'One model (~130–350 MB) with natural voices for 8 languages.',
      'engine_piper_desc':
          'Light voices for over 40 languages: each voice is downloaded separately.',
      'piper_precision': 'Model Precision',
      'piper_precision_desc':
          'Applies to every Piper voice. Changing it requires downloading the voices again.',
      'quality_x_low': 'Very low quality',
      'quality_low': 'Low quality',
      'quality_medium': 'Medium quality',
      'quality_high': 'High quality',
      'speaker': 'Speaker ({count} available)',
      'downloaded_voices': 'Downloaded Voices',
      'no_downloaded_voices': 'No voice has been downloaded yet.',
      'disk_usage': 'Disk space used: {size}',
      'in_use': 'In use',
      'delete': 'Delete',
      'cancel': 'Cancel',
      'delete_model_title': 'Delete voice?',
      'delete_model_body':
          '"{name}" will be removed from disk. If a language still uses it, it will be downloaded again the next time it speaks.',
      'theme': 'Theme',
      'theme_dark': 'Dark',
      'theme_light': 'Light',
      'theme_system': 'System Default',
      'press_a_key': 'Press a key...',
      'no_ocr_langs':
          'No Tesseract languages found. Please install language packages.',
      'ocr_not_installed':
          'Tesseract is not installed. To read text from the screen (OCR), install Tesseract and the language packs you need. Run "select-to-speech --check" to see the install command.',
      'ducking': 'Audio Ducking',
      'ducking_desc': 'Lower background volume while reading',
      'hardware_threads': 'Inference Threads',
      'threads_auto': 'Auto ({count} threads)',
      'hardware_cpu_info': 'Detected CPU: {cpu}',
      'text_normalization': 'Smart Text Formatting & Line Unwrap',
      'text_normalization_desc':
          'Rejoin hyphenated words, fix soft line wraps, and format list pauses',
      'neural_punctuation': 'Neural Punctuation Restoration',
      'neural_punctuation_desc':
          'Model: Sherpa-ONNX CT-Transformer INT8. Supported languages: English (en) and Chinese (zh).',
      'punct_download_btn': 'Download Punctuation Model (~62 MB)',
      'punct_downloading': 'Downloading Punctuation Model...',
      'punct_installed_badge': 'Model installed',
    },
    'it': {
      'app_title': 'Select to Speech',
      'settings': 'Impostazioni',
      'quit': 'Esci',
      'failed_connect': 'Impossibile connettersi al backend',
      'retry': 'Riprova',
      'tab_voice': 'Voce',
      'tab_audio': 'Audio',
      'tab_ocr': 'OCR',
      'tab_shortcuts': 'Scorciatoie',
      'tab_general': 'Generale',
      'save_settings': 'Salva Impostazioni',
      'voice_config': 'Configurazione Voce',
      'voice_model': 'Modello Vocale',
      'default_language': 'Lingua Predefinita',
      'download': 'Scarica',
      'downloading': 'Download in corso...',
      'preparing_download': 'Preparazione download...',
      'error': 'Errore',
      'language_voices': 'Voci delle Lingue',
      'audio_settings': 'Impostazioni Audio',
      'output_device': 'Dispositivo di Output',
      'default_device': 'Dispositivo di Sistema Predefinito',
      'speed': 'Velocità',
      'pitch': 'Tonalità',
      'volume': 'Volume',
      'keyboard_shortcuts': 'Scorciatoie da Tastiera',
      'ocr_settings': 'Impostazioni OCR',
      'ocr_language': 'Lingua Tesseract',
      'modifier_key': 'Tasto Modificatore',
      'trigger_key': 'Tasto di Attivazione (es. esc)',
      'pause_key': 'Tasto Pausa/Riprendi (es. w)',
      'stop_key': 'Tasto Interrompi (es. s)',
      'ocr_key': 'Tasto OCR',
      'general_settings': 'Impostazioni Generali',
      'appearance': 'Aspetto',
      'performance': 'Prestazioni',
      'text_processing': 'Elaborazione del Testo',
      'diagnostics': 'Diagnostica',
      'gui_language': 'Lingua dell\'Interfaccia',
      'enable_debug': 'Abilita Log di Debug',
      'check_logs':
          'Controlla i log in ~/.local/state/select-to-speech/app.log',
      'save_success': 'Impostazioni salvate con successo!',
      'save_failed': 'Salvataggio delle impostazioni fallito',
      'download_success': 'Modello scaricato con successo!',
      'download_failed': 'Download fallito',
      'none_disabled': 'Nessuna / Disabilitata',
      'lang_auto': 'Predefinito di Sistema',
      'lang_en': 'Inglese',
      'lang_it': 'Italiano',
      'lang_es': 'Spagnolo',
      'lang_fr': 'Francese',
      'lang_pt': 'Portoghese',
      'lang_hi': 'Hindi',
      'lang_ja': 'Giapponese',
      'lang_zh': 'Cinese',
      'voice_lang_template': 'Voce {lang}',
      'tts_engine': 'Motore di Sintesi',
      'engine_kokoro_desc':
          'Un unico modello (~130–350 MB) con voci naturali per 8 lingue.',
      'engine_piper_desc':
          'Voci leggere per oltre 40 lingue: ogni voce si scarica separatamente.',
      'piper_precision': 'Precisione del Modello',
      'piper_precision_desc':
          'Vale per tutte le voci Piper. Se la cambi, le voci vanno scaricate di nuovo.',
      'quality_x_low': 'Qualità molto bassa',
      'quality_low': 'Qualità bassa',
      'quality_medium': 'Qualità media',
      'quality_high': 'Qualità alta',
      'speaker': 'Speaker ({count} disponibili)',
      'downloaded_voices': 'Voci Scaricate',
      'no_downloaded_voices': 'Non hai ancora scaricato nessuna voce.',
      'disk_usage': 'Spazio occupato: {size}',
      'in_use': 'In uso',
      'delete': 'Elimina',
      'cancel': 'Annulla',
      'delete_model_title': 'Eliminare la voce?',
      'delete_model_body':
          '"{name}" verrà rimossa dal disco. Se una lingua la usa ancora, verrà scaricata di nuovo alla prossima lettura.',
      'theme': 'Tema',
      'theme_dark': 'Scuro',
      'theme_light': 'Chiaro',
      'theme_system': 'Predefinito di Sistema',
      'press_a_key': 'Premi un tasto...',
      'no_ocr_langs':
          'Nessuna lingua trovata per Tesseract. Installa i pacchetti lingua.',
      'ocr_not_installed':
          'Tesseract non è installato. Per leggere il testo dallo schermo (OCR) installa Tesseract e i pacchetti lingua che ti servono. Esegui "select-to-speech --check" per vedere il comando di installazione.',
      'ducking': 'Ducking Audio',
      'ducking_desc': 'Abbassa il volume di sottofondo durante la lettura',
      'hardware_threads': 'Thread di Calcolo',
      'threads_auto': 'Automatico ({count} thread)',
      'hardware_cpu_info': 'Processore Rilevato: {cpu}',
      'text_normalization': 'Formattazione Intelligente del Testo',
      'text_normalization_desc':
          'Ricompone parole sillabate (a capo), unisce righe spezzate e imposta pause negli elenchi',
      'neural_punctuation': 'Ripristino Punteggiatura Neurale',
      'neural_punctuation_desc':
          'Modello: Sherpa-ONNX CT-Transformer INT8. Lingue supportate: Inglese (en) e Cinese (zh).',
      'punct_download_btn': 'Scarica Modello Punteggiatura (~62 MB)',
      'punct_downloading': 'Download modello di punteggiatura in corso...',
      'punct_installed_badge': 'Modello installato',
    },
    'es': {
      'app_title': 'Select to Speech',
      'settings': 'Ajustes',
      'quit': 'Salir',
      'failed_connect': 'Error al conectar con el backend',
      'retry': 'Reintentar',
      'tab_voice': 'Voz',
      'tab_audio': 'Audio',
      'tab_ocr': 'OCR',
      'tab_shortcuts': 'Atajos',
      'tab_general': 'General',
      'save_settings': 'Guardar Ajustes',
      'voice_config': 'Configuración de Voz',
      'voice_model': 'Modelo de Voz',
      'default_language': 'Idioma Predeterminado',
      'download': 'Descargar',
      'downloading': 'Descargando...',
      'preparing_download': 'Preparando descarga...',
      'error': 'Error',
      'language_voices': 'Voces de los Idiomas',
      'audio_settings': 'Ajustes de Audio',
      'output_device': 'Dispositivo de Salida',
      'default_device': 'Dispositivo de Sistema Predeterminado',
      'speed': 'Velocidad',
      'pitch': 'Tono',
      'volume': 'Volumen',
      'keyboard_shortcuts': 'Atajos de Teclado',
      'ocr_settings': 'Ajustes de OCR',
      'ocr_language': 'Idioma de Tesseract',
      'modifier_key': 'Tecla Modificadora',
      'trigger_key': 'Tecla de Activación (ej. esc)',
      'pause_key': 'Tecla Pausa/Reanudar (ej. w)',
      'stop_key': 'Tecla Detener (ej. s)',
      'ocr_key': 'Tecla OCR',
      'general_settings': 'Ajustes Generales',
      'appearance': 'Apariencia',
      'performance': 'Rendimiento',
      'text_processing': 'Procesamiento de Texto',
      'diagnostics': 'Diagnóstico',
      'gui_language': 'Idioma de la Interfaz',
      'enable_debug': 'Habilitar Registro de Depuración',
      'check_logs':
          'Revisa los registros en ~/.local/state/select-to-speech/app.log',
      'save_success': '¡Ajustes guardados con éxito!',
      'save_failed': 'Error al guardar los ajustes',
      'download_success': '¡Modelo descargado con éxito!',
      'download_failed': 'Descarga fallida',
      'none_disabled': 'Ninguna / Desactivada',
      'lang_auto': 'Predeterminado del Sistema',
      'lang_en': 'Inglés',
      'lang_it': 'Italiano',
      'lang_es': 'Español',
      'lang_fr': 'Francés',
      'lang_pt': 'Portugués',
      'lang_hi': 'Hindi',
      'lang_ja': 'Japonés',
      'lang_zh': 'Chino',
      'voice_lang_template': 'Voz {lang}',
      'tts_engine': 'Motor de Síntesis',
      'engine_kokoro_desc':
          'Un único modelo (~130–350 MB) con voces naturales para 8 idiomas.',
      'engine_piper_desc':
          'Voces ligeras para más de 40 idiomas: cada voz se descarga por separado.',
      'piper_precision': 'Precisión del Modelo',
      'piper_precision_desc':
          'Se aplica a todas las voces Piper. Si la cambias, hay que volver a descargar las voces.',
      'quality_x_low': 'Calidad muy baja',
      'quality_low': 'Calidad baja',
      'quality_medium': 'Calidad media',
      'quality_high': 'Calidad alta',
      'speaker': 'Hablante ({count} disponibles)',
      'downloaded_voices': 'Voces Descargadas',
      'no_downloaded_voices': 'Todavía no has descargado ninguna voz.',
      'disk_usage': 'Espacio ocupado: {size}',
      'in_use': 'En uso',
      'delete': 'Eliminar',
      'cancel': 'Cancelar',
      'delete_model_title': '¿Eliminar la voz?',
      'delete_model_body':
          '"{name}" se eliminará del disco. Si un idioma todavía la usa, se volverá a descargar la próxima vez que hable.',
      'theme': 'Tema',
      'theme_dark': 'Oscuro',
      'theme_light': 'Claro',
      'theme_system': 'Predeterminado del Sistema',
      'press_a_key': 'Presiona una tecla...',
      'no_ocr_langs':
          'No se encontraron idiomas de Tesseract. Por favor instala los paquetes de idioma.',
      'ocr_not_installed':
          'Tesseract no está instalado. Para leer texto de la pantalla (OCR), instala Tesseract y los paquetes de idioma que necesites. Ejecuta "select-to-speech --check" para ver el comando de instalación.',
      'ducking': 'Atenuación de Audio',
      'ducking_desc': 'Bajar el volumen de fondo durante la lectura',
      'hardware_threads': 'Hilos de Inferencia',
      'threads_auto': 'Automático ({count} hilos)',
      'hardware_cpu_info': 'CPU Detectada: {cpu}',
      'text_normalization': 'Formato Inteligente y Ajuste de Líneas',
      'text_normalization_desc':
          'Recompone palabras cortadas por guiones, une saltos suaves y formatea pausas en listas',
      'neural_punctuation': 'Restauración de Puntuación Neuronal',
      'neural_punctuation_desc':
          'Modelo: Sherpa-ONNX CT-Transformer INT8. Idiomas compatibles: Inglés (en) y Chino (zh).',
      'punct_download_btn': 'Descargar Modelo de Puntuación (~62 MB)',
      'punct_downloading': 'Descargando modelo de puntuación...',
      'punct_installed_badge': 'Modelo instalado',
    },
    'fr': {
      'app_title': 'Select to Speech',
      'settings': 'Paramètres',
      'quit': 'Quitter',
      'failed_connect': 'Échec de connexion au serveur',
      'retry': 'Réessayer',
      'tab_voice': 'Voix',
      'tab_audio': 'Audio',
      'tab_ocr': 'OCR',
      'tab_shortcuts': 'Raccourcis',
      'tab_general': 'Général',
      'save_settings': 'Enregistrer les paramètres',
      'voice_config': 'Configuration de la Voix',
      'voice_model': 'Modèle de Voix',
      'default_language': 'Langue par Défaut',
      'download': 'Télécharger',
      'downloading': 'Téléchargement...',
      'preparing_download': 'Préparation du téléchargement...',
      'error': 'Erreur',
      'language_voices': 'Voix des Langues',
      'audio_settings': 'Paramètres Audio',
      'output_device': 'Périphérique de Sortie',
      'default_device': 'Périphérique Système par Défaut',
      'speed': 'Vitesse',
      'pitch': 'Hauteur',
      'volume': 'Volume',
      'keyboard_shortcuts': 'Raccourcis Clavier',
      'ocr_settings': 'Paramètres OCR',
      'ocr_language': 'Langue Tesseract',
      'modifier_key': 'Touche Modificatrice',
      'trigger_key': 'Touche de Déclenchement (ex. esc)',
      'pause_key': 'Touche Pause/Reprise (ex. w)',
      'stop_key': 'Touche d\'Arrêt (ex. s)',
      'ocr_key': 'Touche OCR',
      'general_settings': 'Paramètres Généraux',
      'appearance': 'Apparence',
      'performance': 'Performances',
      'text_processing': 'Traitement du Texte',
      'diagnostics': 'Diagnostic',
      'gui_language': 'Langue de l\'Interface',
      'enable_debug': 'Activer le Journal de Débogage',
      'check_logs':
          'Vérifiez les journaux dans ~/.local/state/select-to-speech/app.log',
      'save_success': 'Paramètres enregistrés avec succès !',
      'save_failed': 'Échec de l\'enregistrement des paramètres',
      'download_success': 'Modèle téléchargé avec succès !',
      'download_failed': 'Échec du téléchargement',
      'none_disabled': 'Aucune / Désactivée',
      'lang_auto': 'Par Défaut du Système',
      'lang_en': 'Anglais',
      'lang_it': 'Italien',
      'lang_es': 'Espagnol',
      'lang_fr': 'Français',
      'lang_pt': 'Portugais',
      'lang_hi': 'Hindi',
      'lang_ja': 'Japonais',
      'lang_zh': 'Chinois',
      'voice_lang_template': 'Voix {lang}',
      'tts_engine': 'Moteur de Synthèse',
      'engine_kokoro_desc':
          'Un seul modèle (~130–350 Mo) avec des voix naturelles pour 8 langues.',
      'engine_piper_desc':
          'Des voix légères pour plus de 40 langues : chaque voix se télécharge séparément.',
      'piper_precision': 'Précision du Modèle',
      'piper_precision_desc':
          'S\'applique à toutes les voix Piper. Si vous la changez, les voix doivent être retéléchargées.',
      'quality_x_low': 'Qualité très basse',
      'quality_low': 'Qualité basse',
      'quality_medium': 'Qualité moyenne',
      'quality_high': 'Haute qualité',
      'speaker': 'Locuteur ({count} disponibles)',
      'downloaded_voices': 'Voix Téléchargées',
      'no_downloaded_voices': 'Aucune voix n\'a encore été téléchargée.',
      'disk_usage': 'Espace utilisé : {size}',
      'in_use': 'Utilisée',
      'delete': 'Supprimer',
      'cancel': 'Annuler',
      'delete_model_title': 'Supprimer la voix ?',
      'delete_model_body':
          '« {name} » sera supprimée du disque. Si une langue l\'utilise encore, elle sera retéléchargée à la prochaine lecture.',
      'theme': 'Thème',
      'theme_dark': 'Sombre',
      'theme_light': 'Clair',
      'theme_system': 'Par Défaut du Système',
      'press_a_key': 'Appuyez sur une touche...',
      'no_ocr_langs':
          'Aucune langue Tesseract trouvée. Veuillez installer les paquets de langue.',
      'ocr_not_installed':
          'Tesseract n\'est pas installé. Pour lire le texte à l\'écran (OCR), installez Tesseract et les paquets de langue nécessaires. Exécutez « select-to-speech --check » pour voir la commande d\'installation.',
      'ducking': 'Atténuation Audio',
      'ducking_desc': 'Baisser le volume d\'arrière-plan pendant la lecture',
      'hardware_threads': 'Threads d\'Inférence',
      'threads_auto': 'Automatique ({count} threads)',
      'hardware_cpu_info': 'Processeur Détecté : {cpu}',
      'text_normalization': 'Formatage Intelligent et Ajustement de Ligne',
      'text_normalization_desc':
          'Recompose les mots coupés par des traits d\'union et insère des pauses logiques',
      'neural_punctuation': 'Restauration de la Ponctuation Neuronale',
      'neural_punctuation_desc':
          'Modèle : Sherpa-ONNX CT-Transformer INT8. Langues supportées : Anglais (en) et Chinois (zh).',
      'punct_download_btn': 'Télécharger le Modèle de Ponctuation (~62 Mo)',
      'punct_downloading': 'Téléchargement du modèle de ponctuation...',
      'punct_installed_badge': 'Modèle installé',
    }
  };

  String getCurrentLanguageCode() {
    final userLang = config?['gui_language'] ?? 'auto';
    if (userLang == 'auto') {
      final systemLocale = Platform.localeName.split('_').first.toLowerCase();
      if (translations.containsKey(systemLocale)) {
        return systemLocale;
      }
      return 'en';
    }
    if (translations.containsKey(userLang)) {
      return userLang;
    }
    return 'en';
  }

  String t(String key) {
    final lang = getCurrentLanguageCode();
    return translations[lang]?[key] ?? translations['en']?[key] ?? key;
  }

  @override
  void initState() {
    super.initState();
    apiClient = createUdsClient();
    WidgetsBinding.instance.addObserver(this);
    _initTray();
    _fetchData();
  }

  /// Tray icon asset: white on a dark panel, black on a light one.
  ///
  /// A 128 px PNG rendered from the matching SVG: on Linux the icon is sent to
  /// the panel as a StatusNotifierItem pixmap and the panel scales it.
  String _trayIconAsset() {
    final dark =
        WidgetsBinding.instance.platformDispatcher.platformBrightness ==
            Brightness.dark;
    return dark
        ? 'images/select_to_speech_tray_icon_light.png'
        : 'images/select_to_speech_tray_icon_dark.png';
  }

  @override
  void didChangePlatformBrightness() {
    super.didChangePlatformBrightness();
    _applyTrayIcon();
  }

  void _applyTrayIcon() {
    try {
      _trayIcon?.icon = tray.ImageAsset.fromAsset(_trayIconAsset());
    } catch (_) {}
  }

  void _initTray() {
    try {
      final icon = tray.TrayIcon.create();
      final menu = tray.Menu.create();
      final settingsItem = tray.MenuItem.createWithLabelAndType(
          t('settings'), tray.MenuItemType.normal);
      final quitItem = tray.MenuItem.createWithLabelAndType(
          t('quit'), tray.MenuItemType.normal);
      if (icon == null ||
          menu == null ||
          settingsItem == null ||
          quitItem == null) {
        return;
      }
      settingsItem.addListener((event) {
        if (event is tray.MenuItemClickedEvent) _openSettingsWindow();
      });
      quitItem.addListener((event) {
        if (event is tray.MenuItemClickedEvent) _quit();
      });
      menu.addItem(settingsItem);
      menu.addSeparator();
      menu.addItem(quitItem);

      // KDE reports a left click as TrayIconClickedEvent; GNOME's AppIndicator
      // extension opens the menu on a single click and reports a double click.
      icon.addListener((event) {
        if (event is tray.TrayIconClickedEvent ||
            event is tray.TrayIconDoubleClickedEvent) {
          _openSettingsWindow();
        }
      });
      icon.setTooltip('Select to Speech');
      icon.setContextMenu(menu);
      icon.setContextMenuTrigger(tray.ContextMenuTrigger.rightClicked);

      _trayIcon = icon;
      _trayMenu = menu;
      _traySettingsItem = settingsItem;
      _trayQuitItem = quitItem;
      _applyTrayIcon();
      icon.setVisible(true);
    } catch (_) {
      // Ignore tray initialization errors in headless / widget test environments
    }
  }

  /// Re-labels the tray menu after a GUI language change.
  void _updateTrayMenu() {
    try {
      _traySettingsItem?.label = t('settings');
      _trayQuitItem?.label = t('quit');
    } catch (_) {}
  }

  /// Opens the settings window. A double click on KDE arrives as a click
  /// followed by a double click, so a second request within a second is ignored.
  void _openSettingsWindow() {
    final now = DateTime.now();
    if (_lastSettingsOpen != null &&
        now.difference(_lastSettingsOpen!) < const Duration(seconds: 1)) {
      return;
    }
    _lastSettingsOpen = now;
    Process.run(Platform.resolvedExecutable, []);
  }

  Future<void> _quit() async {
    _shuttingDown = true;
    try {
      await apiClient
          .post(Uri.parse('http://localhost/stop'))
          .timeout(const Duration(seconds: 2));
    } catch (_) {}
    pythonBackend?.kill();
    await Future.delayed(const Duration(milliseconds: 500));
    exit(0);
  }

  Uri _voicesUri(Map<String, dynamic>? voice) {
    final engine = voice?['engine'] ?? 'kokoro';
    final precision = voice?['piper_precision'] ?? 'int8';
    return Uri.parse(
        'http://localhost/voices?engine=$engine&precision=$precision');
  }

  Map<String, List<Map<String, dynamic>>> _decodeVoices(String body) {
    final Map<String, dynamic> voicesMap = jsonDecode(body);
    return voicesMap.map((lang, list) => MapEntry(
        lang,
        (list as List)
            .map((v) => Map<String, dynamic>.from(v as Map))
            .toList()));
  }

  List<Map<String, dynamic>> _decodeModelList(String body) {
    return (jsonDecode(body) as List)
        .map((m) => Map<String, dynamic>.from(m as Map))
        .toList();
  }

  /// Re-reads the voices of the active engine and the downloaded models.
  Future<void> _refreshVoices() async {
    if (config == null) return;
    try {
      final voicesRes = await apiClient.get(_voicesUri(config!['voice']));
      final installedRes =
          await apiClient.get(Uri.parse('http://localhost/installed_models'));
      if (!mounted) return;
      setState(() {
        if (voicesRes.statusCode == 200) {
          availableVoices = _decodeVoices(voicesRes.body);
        }
        if (installedRes.statusCode == 200) {
          installedModels = _decodeModelList(installedRes.body);
        }
      });
    } catch (e) {
      debugPrint('Error refreshing voices: $e');
    }
  }

  /// Downloads a Kokoro model (default: the selected one) or a Piper voice.
  Future<void> _startDownload(
      {String engine = 'kokoro', String? modelId}) async {
    final targetId = modelId ??
        (config?['voice']?['model'] ?? 'kokoro-multi-lang-v1_0') as String;
    setState(() {
      isDownloading = true;
      downloadProgress = 0.0;
      downloadStatus = 'downloading';
      downloadError = null;
      downloadEngine = engine;
      downloadModelId = targetId;
    });

    try {
      final precision = config?['voice']?['piper_precision'] ?? 'int8';
      final res = await apiClient.post(Uri.parse(
          'http://localhost/download_model?model_id=${Uri.encodeQueryComponent(targetId)}'
          '&engine=$engine&precision=$precision&force=true'));
      if (res.statusCode == 200 &&
          jsonDecode(res.body)['status'] == 'started') {
        _pollDownloadStatus();
      } else {
        setState(() {
          isDownloading = false;
          downloadStatus = 'failed';
          downloadError = 'Failed to start download';
        });
      }
    } catch (e) {
      setState(() {
        isDownloading = false;
        downloadStatus = 'failed';
        downloadError = e.toString();
      });
    }
  }

  Future<void> _deleteInstalledModel(Map<String, dynamic> model) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(t('delete_model_title')),
        content: Text(t('delete_model_body')
            .replaceAll('{name}', _installedModelTitle(model))),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(t('cancel')),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(t('delete')),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      final precision = model['precision'];
      final res = await apiClient.delete(Uri.parse(
          'http://localhost/installed_models?engine=${model['engine']}'
          '&model_id=${Uri.encodeQueryComponent(model['id'])}'
          '${precision != null ? '&precision=$precision' : ''}'));
      if (res.statusCode != 200) {
        debugPrint('Error deleting model: HTTP ${res.statusCode} ${res.body}');
      }
      if (model['engine'] == 'kokoro' &&
          model['id'] == config?['voice']?['model']) {
        setState(() => isModelInstalled = false);
      }
    } catch (e) {
      debugPrint('Error deleting model: $e');
    }
    await _refreshVoices();
  }

  void _pollDownloadStatus() async {
    while (isDownloading) {
      await Future.delayed(const Duration(milliseconds: 800));
      if (!mounted) return;
      try {
        final res =
            await apiClient.get(Uri.parse('http://localhost/download_status'));
        if (!mounted) return;
        if (res.statusCode == 200) {
          final data = jsonDecode(res.body);
          final cs = Theme.of(context).colorScheme;
          setState(() {
            downloadStatus = data['status'];
            downloadProgress = (data['progress'] as num).toDouble() / 100.0;
            if (downloadStatus == 'success') {
              isDownloading = false;
              if (downloadEngine == 'kokoro' &&
                  downloadModelId == config?['voice']?['model']) {
                isModelInstalled = true;
              }
              _refreshVoices();
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(t('download_success'),
                      style: TextStyle(color: cs.onPrimaryContainer)),
                  backgroundColor: cs.primaryContainer,
                ),
              );
            } else if (downloadStatus == 'failed') {
              isDownloading = false;
              downloadError = data['error'];
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text('${t('download_failed')}: ${data['error']}',
                      style: TextStyle(color: cs.onErrorContainer)),
                  backgroundColor: cs.errorContainer,
                ),
              );
            }
          });
        }
      } catch (e) {
        // Ignore network errors during polling
      }
    }
  }

  Future<void> _startPunctDownload() async {
    setState(() {
      isPunctDownloading = true;
      punctDownloadProgress = 0.0;
      punctDownloadStatus = 'downloading';
    });

    try {
      final res = await apiClient
          .post(Uri.parse('http://localhost/download_punctuation'));
      if (res.statusCode == 200) {
        _pollPunctDownloadStatus();
      } else {
        setState(() {
          isPunctDownloading = false;
          punctDownloadStatus = 'failed';
        });
      }
    } catch (e) {
      setState(() {
        isPunctDownloading = false;
        punctDownloadStatus = 'failed';
      });
    }
  }

  void _pollPunctDownloadStatus() async {
    while (isPunctDownloading) {
      await Future.delayed(const Duration(milliseconds: 800));
      if (!mounted) return;
      try {
        final res = await apiClient
            .get(Uri.parse('http://localhost/punctuation_status'));
        if (!mounted) return;
        if (res.statusCode == 200) {
          final data = jsonDecode(res.body);
          final cs = Theme.of(context).colorScheme;
          setState(() {
            punctDownloadStatus = data['download_status'] ?? 'idle';
            punctDownloadProgress =
                ((data['download_progress'] ?? 0) as num).toDouble() / 100.0;
            if (punctDownloadStatus == 'success' || data['installed'] == true) {
              isPunctDownloading = false;
              isPunctInstalled = true;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(t('download_success'),
                      style: TextStyle(color: cs.onPrimaryContainer)),
                  backgroundColor: cs.primaryContainer,
                ),
              );
            } else if (punctDownloadStatus == 'failed') {
              isPunctDownloading = false;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(
                  content: Text(
                      '${t('download_failed')}: ${data['download_error']}',
                      style: TextStyle(color: cs.onErrorContainer)),
                  backgroundColor: cs.errorContainer,
                ),
              );
            }
          });
        }
      } catch (_) {}
    }
  }

  Future<void> _fetchData() async {
    setState(() => isLoading = true);
    int retries = 20;
    while (retries > 0) {
      if (!mounted) return;
      try {
        final configRes =
            await apiClient.get(Uri.parse('http://localhost/config'));
        final devicesRes =
            await apiClient.get(Uri.parse('http://localhost/audio_devices'));
        final ocrStatusRes =
            await apiClient.get(Uri.parse('http://localhost/ocr_status'));
        final availableModelsRes =
            await apiClient.get(Uri.parse('http://localhost/available_models'));
        final hardwareRes =
            await apiClient.get(Uri.parse('http://localhost/hardware'));
        final punctRes = await apiClient
            .get(Uri.parse('http://localhost/punctuation_status'));

        if (configRes.statusCode == 200) {
          final decodedConfig = jsonDecode(configRes.body);
          final selectedModel =
              decodedConfig['voice']?['model'] ?? 'kokoro-multi-lang-v1_0';
          final modelInstRes = await apiClient.get(Uri.parse(
              'http://localhost/model_installed?model_id=$selectedModel'));
          final voicesRes = await apiClient
              .get(_voicesUri(decodedConfig['voice'] as Map<String, dynamic>?));
          final installedRes = await apiClient
              .get(Uri.parse('http://localhost/installed_models'));

          if (!mounted) return;
          setState(() {
            config = decodedConfig;
            config!['theme_mode'] ??= 'system';
            config!['text_normalization'] ??= true;
            config!['neural_punctuation'] ??= false;
            config!['ocr'] ??= {'language': 'ita+eng'};
            config!['voice'] ??= {};
            config!['voice']['model'] ??= 'kokoro-multi-lang-v1_0';
            config!['voice']['language'] ??= 'en';
            config!['voice']['num_threads'] ??= 0;
            config!['voice']['provider'] ??= 'cpu';
            config!['voice']['engine'] ??= 'kokoro';
            config!['voice']['piper_precision'] ??= 'int8';
            config!['voice']['language_models'] ??= <String, dynamic>{};
            config!['voice']['piper_language_models'] ??= <String, dynamic>{};

            final themeStr = config!['theme_mode'];
            if (themeStr == 'light') {
              themeModeNotifier.value = ThemeMode.light;
            } else if (themeStr == 'dark') {
              themeModeNotifier.value = ThemeMode.dark;
            } else {
              themeModeNotifier.value = ThemeMode.system;
            }
            if (devicesRes.statusCode == 200) {
              audioDevices = jsonDecode(devicesRes.body);
            }
            if (voicesRes.statusCode == 200) {
              availableVoices = _decodeVoices(voicesRes.body);
            }
            if (installedRes.statusCode == 200) {
              installedModels = _decodeModelList(installedRes.body);
            }
            if (ocrStatusRes.statusCode == 200) {
              final ocrStatus = jsonDecode(ocrStatusRes.body);
              ocrInstalled = ocrStatus['installed'] == true;
              ocrLanguages = List<String>.from(ocrStatus['languages'] ?? []);
            }
            if (availableModelsRes.statusCode == 200) {
              List<dynamic> modelsList = jsonDecode(availableModelsRes.body);
              availableModels =
                  modelsList.map((m) => m as Map<String, dynamic>).toList();
            }
            if (hardwareRes.statusCode == 200) {
              hardwareInfo = jsonDecode(hardwareRes.body);
            }
            if (punctRes.statusCode == 200) {
              final punctData = jsonDecode(punctRes.body);
              isPunctInstalled = punctData['installed'] ?? false;
            }
            if (modelInstRes.statusCode == 200) {
              final modelData = jsonDecode(modelInstRes.body);
              isModelInstalled = modelData['installed'] ?? true;
            }
            isLoading = false;
          });
          _updateTrayMenu();
          return;
        }
      } catch (e) {
        retries--;
        await Future.delayed(const Duration(milliseconds: 500));
      }
    }
    if (mounted) {
      setState(() => isLoading = false);
    }
  }

  void _scheduleSave() {
    _saveTimer?.cancel();
    _saveTimer = Timer(const Duration(milliseconds: 500), () {
      _saveConfigSilent();
    });
  }

  Future<void> _saveConfigSilent() async {
    if (config == null) return;
    try {
      final response = await apiClient.post(
        Uri.parse('http://localhost/config'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(config),
      );
      if (response.statusCode != 200) {
        debugPrint(
            'Error saving config: HTTP ${response.statusCode} - ${response.body}');
      }
    } catch (e) {
      debugPrint('Error saving config: $e');
    }
  }

  void _updateNestedConfig(String section, String key, dynamic value) {
    setState(() {
      if (config != null && config![section] != null) {
        config![section][key] = value;
      }
    });
    _scheduleSave();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    final hasPendingSave = _saveTimer?.isActive ?? false;
    _saveTimer?.cancel();
    if (hasPendingSave) _saveConfigSilent();
    try {
      _trayIcon?.dispose();
      _trayMenu?.dispose();
    } catch (_) {}
    super.dispose();
  }

  Widget _getSelectedTabWidget() {
    switch (_selectedIndex) {
      case 0:
        return KeyedSubtree(
            key: const ValueKey('tab_voice'), child: _buildVoiceTab());
      case 1:
        return KeyedSubtree(
            key: const ValueKey('tab_audio'), child: _buildAudioTab());
      case 2:
        return KeyedSubtree(
            key: const ValueKey('tab_ocr'), child: _buildOcrTab());
      case 3:
        return KeyedSubtree(
            key: const ValueKey('tab_shortcuts'), child: _buildKeyboardTab());
      case 4:
        return KeyedSubtree(
            key: const ValueKey('tab_general'), child: _buildGeneralTab());
      default:
        return KeyedSubtree(
            key: const ValueKey('tab_voice'), child: _buildVoiceTab());
    }
  }

  Widget _buildCenteredTab(Widget tabContent) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          padding: const EdgeInsets.symmetric(horizontal: 28.0, vertical: 32.0),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight:
                  (constraints.maxHeight - 64).clamp(0.0, double.infinity),
            ),
            child: Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 680),
                child: tabContent,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildNavigationDrawer(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return SizedBox(
      width: 280,
      child: NavigationDrawer(
        selectedIndex: _selectedIndex,
        onDestinationSelected: (int index) {
          if (_selectedIndex != index) {
            setState(() {
              _selectedIndex = index;
            });
          }
        },
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(24, 24, 20, 20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  t('app_title'),
                  style: textTheme.titleMedium?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: cs.onSurface,
                  ),
                  overflow: TextOverflow.ellipsis,
                ),
                const SizedBox(height: 2),
                Text(
                  t('settings'),
                  style: textTheme.labelSmall?.copyWith(
                    color: cs.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 24.0),
            child: Divider(
                color: cs.outlineVariant.withValues(alpha: 0.5), height: 1),
          ),
          const SizedBox(height: 12),
          NavigationDrawerDestination(
            icon: const Icon(Icons.record_voice_over_outlined),
            selectedIcon: const Icon(Icons.record_voice_over_rounded),
            label: Text(t('tab_voice')),
          ),
          NavigationDrawerDestination(
            icon: const Icon(Icons.volume_up_outlined),
            selectedIcon: const Icon(Icons.volume_up_rounded),
            label: Text(t('tab_audio')),
          ),
          NavigationDrawerDestination(
            icon: const Icon(Icons.document_scanner_outlined),
            selectedIcon: const Icon(Icons.document_scanner_rounded),
            label: Text(t('tab_ocr')),
          ),
          NavigationDrawerDestination(
            icon: const Icon(Icons.keyboard_outlined),
            selectedIcon: const Icon(Icons.keyboard_rounded),
            label: Text(t('tab_shortcuts')),
          ),
          NavigationDrawerDestination(
            icon: const Icon(Icons.tune_outlined),
            selectedIcon: const Icon(Icons.tune_rounded),
            label: Text(t('tab_general')),
          ),
        ],
      ),
    );
  }

  Widget _buildNavigationRail(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return NavigationRail(
      backgroundColor: cs.surfaceContainerLow,
      selectedIndex: _selectedIndex,
      labelType: NavigationRailLabelType.all,
      onDestinationSelected: (int index) {
        if (_selectedIndex != index) {
          setState(() {
            _selectedIndex = index;
          });
        }
      },
      leading: Padding(
        padding: const EdgeInsets.symmetric(vertical: 16.0),
        child: Container(
          width: 40,
          height: 40,
          padding: const EdgeInsets.all(8),
          decoration: BoxDecoration(
            color: cs.primaryContainer,
            borderRadius: BorderRadius.circular(12),
          ),
          child: SvgPicture.asset(
            'images/select_to_speech_tray_icon.svg',
            colorFilter:
                ColorFilter.mode(cs.onPrimaryContainer, BlendMode.srcIn),
          ),
        ),
      ),
      destinations: [
        NavigationRailDestination(
          icon: const Icon(Icons.record_voice_over_outlined),
          selectedIcon: const Icon(Icons.record_voice_over_rounded),
          label: Text(t('tab_voice')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.volume_up_outlined),
          selectedIcon: const Icon(Icons.volume_up_rounded),
          label: Text(t('tab_audio')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.document_scanner_outlined),
          selectedIcon: const Icon(Icons.document_scanner_rounded),
          label: Text(t('tab_ocr')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.keyboard_outlined),
          selectedIcon: const Icon(Icons.keyboard_rounded),
          label: Text(t('tab_shortcuts')),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.tune_outlined),
          selectedIcon: const Icon(Icons.tune_rounded),
          label: Text(t('tab_general')),
        ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    if (isLoading) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const CircularProgressIndicator(),
              const SizedBox(height: 16),
              Text(
                t('app_title'),
                style:
                    textTheme.titleMedium?.copyWith(color: cs.onSurfaceVariant),
              ),
            ],
          ),
        ),
      );
    }

    if (config == null) {
      return Scaffold(
        body: Center(
          child: Card(
            margin: const EdgeInsets.all(24),
            child: Padding(
              padding: const EdgeInsets.all(32.0),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: cs.errorContainer,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(Icons.error_outline_rounded,
                        size: 40, color: cs.onErrorContainer),
                  ),
                  const SizedBox(height: 20),
                  Text(
                    t('failed_connect'),
                    style: textTheme.titleLarge
                        ?.copyWith(fontWeight: FontWeight.bold),
                  ),
                  const SizedBox(height: 20),
                  FilledButton.icon(
                    onPressed: _fetchData,
                    icon: const Icon(Icons.refresh_rounded),
                    label: Text(t('retry')),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    }

    return Scaffold(
      backgroundColor: cs.surface,
      body: LayoutBuilder(
        builder: (context, constraints) {
          final bool useWideDrawer = constraints.maxWidth >= 740;
          return Row(
            children: [
              if (useWideDrawer)
                _buildNavigationDrawer(context)
              else
                _buildNavigationRail(context),
              VerticalDivider(
                width: 1,
                thickness: 1,
                color: cs.outlineVariant.withValues(alpha: 0.4),
              ),
              Expanded(
                child: AnimatedSwitcher(
                  duration: const Duration(milliseconds: 280),
                  switchInCurve: Curves.easeOutCubic,
                  switchOutCurve: Curves.easeInCubic,
                  transitionBuilder:
                      (Widget child, Animation<double> animation) {
                    final offsetAnimation = Tween<Offset>(
                      begin: const Offset(0.0, 0.025),
                      end: Offset.zero,
                    ).animate(CurvedAnimation(
                        parent: animation, curve: Curves.easeOutCubic));
                    return FadeTransition(
                      opacity: animation,
                      child: SlideTransition(
                        position: offsetAnimation,
                        child: child,
                      ),
                    );
                  },
                  child: _buildCenteredTab(_getSelectedTabWidget()),
                ),
              ),
            ],
          );
        },
      ),
    );
  }

  Widget _buildM3Card({
    required String title,
    required IconData icon,
    required List<Widget> children,
    int staggerIndex = 0,
  }) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return _StaggeredEntrance(
      delay: Duration(milliseconds: staggerIndex * 70),
      child: Padding(
        padding: const EdgeInsets.only(bottom: 20.0),
        child: Card(
          child: Padding(
            padding: const EdgeInsets.all(24.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(icon, size: 26, color: cs.primary),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        title,
                        style: textTheme.titleLarge?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: cs.onSurface,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                ...children,
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildFieldLabel(String label) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: 8.0),
      child: Text(
        label,
        style: textTheme.labelLarge?.copyWith(
          color: cs.onSurfaceVariant,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }

  /// Turns a Kokoro voice id (e.g. `af_nova`) into a friendly name
  /// (`Nova (American)`). Only English voices get the accent suffix.
  String _voiceDisplayName(String id) {
    final idx = id.indexOf('_');
    if (idx < 0) return id;
    final prefix = id.substring(0, idx);
    final raw = id.substring(idx + 1);
    final name = raw.isEmpty ? id : raw[0].toUpperCase() + raw.substring(1);
    if (prefix.startsWith('a')) return '$name (American)';
    if (prefix.startsWith('b')) return '$name (British)';
    return name;
  }

  String get _activeEngine =>
      (config?['voice']?['engine'] ?? 'kokoro') as String;

  /// Config key of the active engine's language → voice map.
  String get _languageModelsKey =>
      _activeEngine == 'piper' ? 'piper_language_models' : 'language_models';

  Map<String, dynamic> get _activeLanguageModels {
    final voice = config!['voice'] as Map<String, dynamic>;
    voice[_languageModelsKey] ??= <String, dynamic>{};
    return voice[_languageModelsKey] as Map<String, dynamic>;
  }

  String _langName(String code) => languageName(code, getCurrentLanguageCode());

  /// Languages the active engine has voices for, sorted by localized name.
  List<String> _engineLanguages() {
    final codes = availableVoices.keys.toList();
    codes.sort((a, b) => _langName(a).compareTo(_langName(b)));
    return codes;
  }

  String _formatBytes(num? bytes) {
    if (bytes == null || bytes <= 0) return '';
    const mb = 1024 * 1024;
    if (bytes >= 1024 * mb) {
      return '${(bytes / (1024 * mb)).toStringAsFixed(1)} GB';
    }
    return '${(bytes / mb).round()} MB';
  }

  String _prettyVoiceName(String raw) => raw
      .split(RegExp(r'[_-]'))
      .where((w) => w.isNotEmpty)
      .map((w) => w[0].toUpperCase() + w.substring(1))
      .join(' ');

  String _qualityLabel(String? quality) =>
      quality == null ? '' : t('quality_$quality');

  /// Piper voice name with the English accent, as for Kokoro: `Amy (American)`.
  String _piperVoiceName(Map<String, dynamic> v) {
    final name = _prettyVoiceName(v['name'] ?? v['id']);
    switch (v['locale']) {
      case 'en_US':
        return '$name (American)';
      case 'en_GB':
        return '$name (British)';
    }
    return name;
  }

  /// Dropdown labels for a language's Piper voices: `Paola · 21 MB`. Voices that
  /// would read the same also show what tells them apart: the quality and/or the
  /// locale (e.g. `Dii · pt_BR · 20 MB` and `Dii · pt_PT · 20 MB`).
  Map<String, String> _piperVoiceLabels(List<Map<String, dynamic>> voices) {
    String join(List<String> parts) =>
        parts.where((p) => p.isNotEmpty).join(' · ');
    String base(Map<String, dynamic> v) =>
        join([_piperVoiceName(v), _formatBytes(v['size_bytes'])]);

    final groups = <String, List<Map<String, dynamic>>>{};
    for (final v in voices) {
      groups.putIfAbsent(base(v), () => []).add(v);
    }

    final labels = <String, String>{};
    for (final group in groups.values) {
      final showQuality = group.map((v) => v['quality']).toSet().length > 1;
      final showLocale = group.map((v) => v['locale']).toSet().length > 1;
      for (final v in group) {
        labels[v['id'] as String] = group.length == 1
            ? base(v)
            : join([
                _piperVoiceName(v),
                if (showQuality) _qualityLabel(v['quality']),
                if (showLocale) (v['locale'] ?? '') as String,
                _formatBytes(v['size_bytes']),
              ]);
      }
    }
    return labels;
  }

  Future<void> _setEngine(String engine) async {
    if (engine == _activeEngine) return;
    setState(() {
      config!['voice']['engine'] = engine;
      availableVoices = {};
    });
    _scheduleSave();
    await _refreshVoices();
    if (!mounted) return;
    // Keep the default language valid for the new engine
    final langs = _engineLanguages();
    if (langs.isNotEmpty && !langs.contains(config!['voice']['language'])) {
      _updateNestedConfig(
          'voice', 'language', langs.contains('en') ? 'en' : langs.first);
    }
  }

  Future<void> _setPiperPrecision(String precision) async {
    if (precision == config!['voice']['piper_precision']) return;
    setState(() => config!['voice']['piper_precision'] = precision);
    _scheduleSave();
    await _refreshVoices();
  }

  void _setLanguageVoice(String langCode, String ref) {
    setState(() => _activeLanguageModels[langCode] = ref);
    _scheduleSave();
  }

  Widget _buildDownloadProgress() {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const SizedBox(height: 14),
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: LinearProgressIndicator(
            minHeight: 8,
            value: downloadProgress > 0 ? downloadProgress : null,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          downloadProgress > 0
              ? '${t('downloading')} ${(downloadProgress * 100).toInt()}%'
              : t('preparing_download'),
          style: textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
        ),
      ],
    );
  }

  Widget _buildDownloadError() {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(top: 10),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: cs.errorContainer,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          children: [
            Icon(Icons.error_outline_rounded,
                size: 18, color: cs.onErrorContainer),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                '${t('error')}: $downloadError',
                style:
                    textTheme.bodySmall?.copyWith(color: cs.onErrorContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildKokoroVoiceDropdown(String langCode) {
    final voices = (availableVoices[langCode] ?? [])
        .map((v) => v['id'] as String)
        .toList();
    final currentVal = (_activeLanguageModels[langCode] ?? '') as String;
    if (currentVal != '' && !voices.contains(currentVal)) {
      voices.add(currentVal);
    }

    return DropdownButtonFormField<String>(
      key: ValueKey('kokoro_voice_${langCode}_$currentVal'),
      initialValue: currentVal,
      isExpanded: true,
      borderRadius: BorderRadius.circular(14),
      items: [
        DropdownMenuItem(value: '', child: Text(t('none_disabled'))),
        ...voices.map((v) =>
            DropdownMenuItem(value: v, child: Text(_voiceDisplayName(v)))),
      ],
      onChanged: (val) {
        if (val != null) _setLanguageVoice(langCode, val);
      },
    );
  }

  Widget _buildPiperVoicePicker(String langCode) {
    final voices = availableVoices[langCode] ?? [];
    final ref = (_activeLanguageModels[langCode] ?? '') as String;
    final hashIdx = ref.indexOf('#');
    final key = hashIdx >= 0 ? ref.substring(0, hashIdx) : ref;
    final speakerId =
        hashIdx >= 0 ? int.tryParse(ref.substring(hashIdx + 1)) ?? 0 : 0;

    Map<String, dynamic>? selected;
    for (final v in voices) {
      if (v['id'] == key) selected = v;
    }
    final speakers =
        List<String>.from(selected?['speakers'] as List? ?? const []);
    final installed = selected?['installed'] == true;
    final downloadingThis =
        isDownloading && downloadEngine == 'piper' && downloadModelId == key;
    final labels = _piperVoiceLabels(voices);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<String>(
          key: ValueKey('piper_voice_${langCode}_$key'),
          initialValue: selected != null ? key : '',
          isExpanded: true,
          borderRadius: BorderRadius.circular(14),
          items: [
            DropdownMenuItem(value: '', child: Text(t('none_disabled'))),
            ...voices.map((v) => DropdownMenuItem(
                value: v['id'] as String,
                child: Text(labels[v['id']] ?? v['id'],
                    overflow: TextOverflow.ellipsis))),
          ],
          onChanged: (val) {
            if (val != null) _setLanguageVoice(langCode, val);
          },
        ),
        if (speakers.length > 1) ...[
          const SizedBox(height: 12),
          _buildFieldLabel(
              t('speaker').replaceAll('{count}', speakers.length.toString())),
          DropdownMenu<int>(
            key: ValueKey('piper_speaker_${langCode}_$key'),
            initialSelection: speakerId < speakers.length ? speakerId : 0,
            expandedInsets: EdgeInsets.zero,
            enableFilter: speakers.length > 12,
            requestFocusOnTap: speakers.length > 12,
            menuHeight: 320,
            dropdownMenuEntries: [
              for (var i = 0; i < speakers.length; i++)
                DropdownMenuEntry<int>(
                    value: i, label: '${i + 1}. ${speakers[i]}'),
            ],
            onSelected: (sid) {
              if (sid != null) {
                _setLanguageVoice(langCode, sid == 0 ? key : '$key#$sid');
              }
            },
          ),
        ],
        if (selected != null && !installed) ...[
          const SizedBox(height: 12),
          Align(
            alignment: Alignment.centerLeft,
            child: FilledButton.tonalIcon(
              onPressed: isDownloading
                  ? null
                  : () => _startDownload(engine: 'piper', modelId: key),
              icon: downloadingThis
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.download_rounded, size: 18),
              label: Text(downloadingThis
                  ? t('downloading')
                  : '${t('download')} (${_formatBytes(selected['size_bytes'])})'),
            ),
          ),
          if (downloadingThis) _buildDownloadProgress(),
          if (!isDownloading &&
              downloadError != null &&
              downloadEngine == 'piper' &&
              downloadModelId == key)
            _buildDownloadError(),
        ],
      ],
    );
  }

  Widget _buildLanguageVoiceDropdown(String langCode) {
    final label =
        t('voice_lang_template').replaceAll('{lang}', _langName(langCode));
    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _buildFieldLabel(label),
          _activeEngine == 'piper'
              ? _buildPiperVoicePicker(langCode)
              : _buildKokoroVoiceDropdown(langCode),
        ],
      ),
    );
  }

  Widget _buildKokoroModelPicker() {
    final cs = Theme.of(context).colorScheme;
    final selectedModelId =
        config!['voice']['model'] ?? 'kokoro-multi-lang-v1_0';
    final kokoroDownloading = isDownloading && downloadEngine == 'kokoro';

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildFieldLabel(t('voice_model')),
        Row(
          crossAxisAlignment: CrossAxisAlignment.center,
          children: [
            Expanded(
              child: DropdownButtonFormField<String>(
                initialValue:
                    availableModels.any((m) => m['id'] == selectedModelId)
                        ? selectedModelId
                        : (availableModels.isNotEmpty
                            ? availableModels.first['id']
                            : 'kokoro-multi-lang-v1_0'),
                isExpanded: true,
                borderRadius: BorderRadius.circular(14),
                items: availableModels.isNotEmpty
                    ? availableModels.map((m) {
                        return DropdownMenuItem<String>(
                          value: m['id'],
                          child: Text(m['name'] ?? m['id'],
                              overflow: TextOverflow.ellipsis),
                        );
                      }).toList()
                    : const [
                        DropdownMenuItem(
                          value: 'kokoro-multi-lang-v1_0',
                          child: Text('Kokoro v1.0 (FP32, ~350 MB)'),
                        ),
                      ],
                onChanged: (val) async {
                  if (val != null && val != config!['voice']['model']) {
                    setState(() {
                      config!['voice']['model'] = val;
                      for (var m in availableModels) {
                        if (m['id'] == val) {
                          isModelInstalled = m['installed'] ?? false;
                          break;
                        }
                      }
                    });
                    _scheduleSave();
                    try {
                      final res = await apiClient.get(Uri.parse(
                          'http://localhost/model_installed?model_id=$val'));
                      if (res.statusCode == 200 && mounted) {
                        setState(() {
                          isModelInstalled =
                              jsonDecode(res.body)['installed'] ?? false;
                        });
                      }
                    } catch (_) {}
                  }
                },
              ),
            ),
            AnimatedSize(
              duration: const Duration(milliseconds: 250),
              curve: Curves.easeOutCubic,
              child: (!isModelInstalled || kokoroDownloading)
                  ? Padding(
                      padding: const EdgeInsets.only(left: 12.0),
                      child: FilledButton.icon(
                        onPressed:
                            isDownloading ? null : () => _startDownload(),
                        icon: kokoroDownloading
                            ? SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: cs.onSurface.withValues(alpha: 0.6),
                                ),
                              )
                            : const Icon(Icons.download_rounded, size: 18),
                        label: Text(kokoroDownloading
                            ? t('downloading')
                            : t('download')),
                      ),
                    )
                  : const SizedBox.shrink(),
            ),
          ],
        ),
        AnimatedSize(
          duration: const Duration(milliseconds: 250),
          curve: Curves.easeOutCubic,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (kokoroDownloading) _buildDownloadProgress(),
              if (!isDownloading &&
                  downloadError != null &&
                  downloadEngine == 'kokoro')
                _buildDownloadError(),
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildPiperPrecisionPicker() {
    final textTheme = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    final precision = config!['voice']['piper_precision'] ?? 'int8';
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildFieldLabel(t('piper_precision')),
        DropdownButtonFormField<String>(
          key: ValueKey('piper_precision_$precision'),
          initialValue: precision,
          isExpanded: true,
          borderRadius: BorderRadius.circular(14),
          items: [
            for (final p in const ['int8', 'fp16', 'fp32'])
              DropdownMenuItem(value: p, child: Text(p.toUpperCase())),
          ],
          onChanged: (val) {
            if (val != null) _setPiperPrecision(val);
          },
        ),
        const SizedBox(height: 6),
        Text(
          t('piper_precision_desc'),
          style: textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
        ),
      ],
    );
  }

  String _installedModelTitle(Map<String, dynamic> m) {
    if (m['engine'] == 'kokoro') return m['name'] ?? m['id'];
    return _prettyVoiceName(m['name'] ?? m['id']);
  }

  String _installedModelSubtitle(Map<String, dynamic> m) {
    final parts = <String>[
      m['engine'] == 'piper' ? 'Piper' : 'Kokoro',
      if (m['language'] != null) _langName(m['language']),
      if (m['engine'] == 'piper') m['id'],
      if (m['precision'] != null) (m['precision'] as String).toUpperCase(),
      _formatBytes(m['size_bytes']),
    ];
    return parts.where((p) => p.isNotEmpty).join(' · ');
  }

  Widget _buildInstalledModelsCard() {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final total = installedModels.fold<num>(
        0, (sum, m) => sum + ((m['size_bytes'] as num?) ?? 0));

    return _buildM3Card(
      title: t('downloaded_voices'),
      icon: Icons.folder_rounded,
      staggerIndex: 2,
      children: [
        if (installedModels.isEmpty)
          Text(t('no_downloaded_voices'),
              style: textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant))
        else ...[
          Text(
            t('disk_usage').replaceAll('{size}', _formatBytes(total)),
            style: textTheme.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
          ),
          const SizedBox(height: 8),
          for (final m in installedModels)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 8),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Flexible(
                              child: Text(
                                _installedModelTitle(m),
                                style: textTheme.titleSmall
                                    ?.copyWith(color: cs.onSurface),
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                            if (m['in_use'] == true) ...[
                              const SizedBox(width: 8),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                    horizontal: 8, vertical: 2),
                                decoration: BoxDecoration(
                                  color: cs.secondaryContainer,
                                  borderRadius: BorderRadius.circular(8),
                                ),
                                child: Text(
                                  t('in_use'),
                                  style: textTheme.labelSmall?.copyWith(
                                      color: cs.onSecondaryContainer),
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 2),
                        Text(
                          _installedModelSubtitle(m),
                          style: textTheme.bodySmall
                              ?.copyWith(color: cs.onSurfaceVariant),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(width: 12),
                  TextButton(
                    onPressed: () => _deleteInstalledModel(m),
                    child: Text(t('delete')),
                  ),
                ],
              ),
            ),
        ],
      ],
    );
  }

  Widget _buildVoiceTab() {
    final engine = _activeEngine;
    final langs = _engineLanguages();
    final configuredDefault = config!['voice']['language'] as String?;
    final currentDefaultLang = langs.contains(configuredDefault)
        ? configuredDefault!
        : (langs.isNotEmpty ? langs.first : 'en');

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildM3Card(
          title: t('voice_config'),
          icon: Icons.graphic_eq_rounded,
          staggerIndex: 0,
          children: [
            _buildFieldLabel(t('tts_engine')),
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                segments: const [
                  ButtonSegment<String>(value: 'kokoro', label: Text('Kokoro')),
                  ButtonSegment<String>(value: 'piper', label: Text('Piper')),
                ],
                selected: {engine},
                onSelectionChanged: (sel) => _setEngine(sel.first),
              ),
            ),
            const SizedBox(height: 6),
            Text(
              t(engine == 'piper' ? 'engine_piper_desc' : 'engine_kokoro_desc'),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: Theme.of(context).colorScheme.onSurfaceVariant),
            ),
            const SizedBox(height: 20),
            engine == 'piper'
                ? _buildPiperPrecisionPicker()
                : _buildKokoroModelPicker(),
            const SizedBox(height: 20),
            _buildFieldLabel(t('default_language')),
            DropdownButtonFormField<String>(
              key: ValueKey('default_lang_${engine}_$currentDefaultLang'),
              initialValue: langs.contains(currentDefaultLang)
                  ? currentDefaultLang
                  : null,
              isExpanded: true,
              borderRadius: BorderRadius.circular(14),
              items: langs.map((code) {
                return DropdownMenuItem(
                  value: code,
                  child: Text(_langName(code)),
                );
              }).toList(),
              onChanged: (val) {
                if (val != null) {
                  _updateNestedConfig('voice', 'language', val);
                }
              },
            ),
          ],
        ),
        _buildM3Card(
          title: t('language_voices'),
          icon: Icons.translate_rounded,
          staggerIndex: 1,
          children: [
            if (langs.isEmpty)
              const Center(child: CircularProgressIndicator())
            else
              ...langs.map(_buildLanguageVoiceDropdown),
          ],
        ),
        _buildInstalledModelsCard(),
      ],
    );
  }

  Widget _buildAudioTab() {
    List<DropdownMenuItem<int?>> deviceItems = [
      DropdownMenuItem(value: null, child: Text(t('default_device'))),
    ];
    for (var dev in audioDevices) {
      deviceItems.add(
        DropdownMenuItem(
          value: dev['id'],
          child: Text('${dev['name']} (ID: ${dev['id']})',
              overflow: TextOverflow.ellipsis),
        ),
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildM3Card(
          title: t('audio_settings'),
          icon: Icons.speaker_group_rounded,
          staggerIndex: 0,
          children: [
            _buildFieldLabel(t('output_device')),
            DropdownButtonFormField<int?>(
              initialValue: config!['audio']['device_id'],
              isExpanded: true,
              borderRadius: BorderRadius.circular(14),
              items: deviceItems,
              onChanged: (val) =>
                  _updateNestedConfig('audio', 'device_id', val),
            ),
            const SizedBox(height: 28),
            _buildSlider(
              label: t('speed'),
              section: 'audio',
              keyName: 'speed',
              min: 0.5,
              max: 2.0,
            ),
            _buildSlider(
              label: t('pitch'),
              section: 'audio',
              keyName: 'pitch',
              min: 0.5,
              max: 2.0,
            ),
            _buildSlider(
              label: t('volume'),
              section: 'audio',
              keyName: 'volume',
              min: 0.0,
              max: 2.0,
            ),
            const Divider(),
            _buildM3SwitchTile(
              title: t('ducking'),
              subtitle: t('ducking_desc'),
              value: config!['audio']['ducking'] ?? true,
              onChanged: (val) => _updateNestedConfig('audio', 'ducking', val),
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildOcrTab() {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildM3Card(
          title: t('ocr_settings'),
          icon: Icons.document_scanner_rounded,
          staggerIndex: 0,
          children: [
            if (!ocrInstalled || ocrLanguages.isEmpty)
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  color: cs.errorContainer,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Row(
                  children: [
                    Icon(Icons.warning_amber_rounded,
                        color: cs.onErrorContainer),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        t(ocrInstalled ? 'no_ocr_langs' : 'ocr_not_installed'),
                        style: textTheme.bodyMedium
                            ?.copyWith(color: cs.onErrorContainer),
                      ),
                    ),
                  ],
                ),
              )
            else
              _buildOcrLanguageMultiSelect(),
          ],
        ),
      ],
    );
  }

  Widget _buildOcrLanguageMultiSelect() {
    String currentVal = config!['ocr']['language'] ?? '';
    List<String> selectedLangs =
        currentVal.split('+').where((s) => s.isNotEmpty).toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildFieldLabel(t('ocr_language')),
        const SizedBox(height: 6),
        Wrap(
          spacing: 10.0,
          runSpacing: 10.0,
          children: ocrLanguages.map((lang) {
            final isSelected = selectedLangs.contains(lang);
            return FilterChip(
              label: Text(lang),
              selected: isSelected,
              showCheckmark: true,
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
              onSelected: (bool selected) {
                setState(() {
                  if (selected) {
                    if (!selectedLangs.contains(lang)) selectedLangs.add(lang);
                  } else {
                    selectedLangs.remove(lang);
                  }
                  config!['ocr']['language'] = selectedLangs.join('+');
                });
                _scheduleSave();
              },
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _buildKeyboardTab() {
    final modifierVal =
        (config!['keyboard']['modifier_key'] ?? 'alt').toString();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildM3Card(
          title: t('keyboard_shortcuts'),
          icon: Icons.keyboard_command_key_rounded,
          staggerIndex: 0,
          children: [
            _buildDropdown(
              t('modifier_key'),
              'keyboard',
              'modifier_key',
              ['alt', 'ctrl', 'shift', 'super'],
            ),
            const SizedBox(height: 20),
            _buildTextField(
                t('trigger_key'), 'keyboard', 'trigger_key', modifierVal),
            const SizedBox(height: 16),
            _buildTextField(
                t('pause_key'), 'keyboard', 'pause_key', modifierVal),
            const SizedBox(height: 16),
            _buildTextField(t('stop_key'), 'keyboard', 'stop_key', modifierVal),
            const SizedBox(height: 16),
            _buildTextField(t('ocr_key'), 'keyboard', 'ocr_key', modifierVal),
          ],
        ),
      ],
    );
  }

  Widget _buildGeneralTab() {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final currentThemeStr = (config!['theme_mode'] ?? 'system').toString();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _buildM3Card(
          title: t('appearance'),
          icon: Icons.palette_rounded,
          staggerIndex: 0,
          children: [
            _buildDropdown(
              t('gui_language'),
              null,
              'gui_language',
              ['auto', 'en', 'it', 'es', 'fr'],
            ),
            const SizedBox(height: 22),
            _buildFieldLabel(t('theme')),
            SizedBox(
              width: double.infinity,
              child: SegmentedButton<String>(
                segments: [
                  ButtonSegment<String>(
                    value: 'system',
                    icon: const Icon(Icons.brightness_auto_rounded),
                    label: Text(t('theme_system')),
                  ),
                  ButtonSegment<String>(
                    value: 'light',
                    icon: const Icon(Icons.light_mode_rounded),
                    label: Text(t('theme_light')),
                  ),
                  ButtonSegment<String>(
                    value: 'dark',
                    icon: const Icon(Icons.dark_mode_rounded),
                    label: Text(t('theme_dark')),
                  ),
                ],
                selected: {
                  ['system', 'light', 'dark'].contains(currentThemeStr)
                      ? currentThemeStr
                      : 'system',
                },
                onSelectionChanged: (Set<String> selection) {
                  final val = selection.first;
                  setState(() {
                    config!['theme_mode'] = val;
                  });
                  _scheduleSave();
                  if (val == 'light') {
                    themeModeNotifier.value = ThemeMode.light;
                  } else if (val == 'dark') {
                    themeModeNotifier.value = ThemeMode.dark;
                  } else {
                    themeModeNotifier.value = ThemeMode.system;
                  }
                },
              ),
            ),
          ],
        ),
        _buildM3Card(
          title: t('performance'),
          icon: Icons.memory_rounded,
          staggerIndex: 1,
          children: [
            _buildFieldLabel(t('hardware_threads')),
            DropdownButtonFormField<int>(
              initialValue: config!['voice']['num_threads'] ?? 0,
              isExpanded: true,
              borderRadius: BorderRadius.circular(14),
              items: [
                DropdownMenuItem(
                  value: 0,
                  child: Text(
                    t('threads_auto').replaceAll(
                      '{count}',
                      '${hardwareInfo?['optimal_threads'] ?? 4}',
                    ),
                  ),
                ),
                for (int tCount in [1, 2, 4, 6, 8, 12, 16])
                  DropdownMenuItem(
                    value: tCount,
                    child: Text('$tCount thread'),
                  ),
              ],
              onChanged: (val) {
                if (val != null) {
                  _updateNestedConfig('voice', 'num_threads', val);
                }
              },
            ),
            if (hardwareInfo != null && hardwareInfo!['cpu_model'] != null) ...[
              const SizedBox(height: 12),
              Container(
                padding:
                    const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: cs.secondaryContainer.withValues(alpha: 0.5),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  children: [
                    Icon(Icons.memory_rounded,
                        size: 16, color: cs.onSecondaryContainer),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        t('hardware_cpu_info')
                            .replaceAll('{cpu}', hardwareInfo!['cpu_model']),
                        style: textTheme.labelMedium
                            ?.copyWith(color: cs.onSecondaryContainer),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ],
        ),
        _buildM3Card(
          title: t('text_processing'),
          icon: Icons.notes_rounded,
          staggerIndex: 2,
          children: [
            _buildM3SwitchTile(
              title: t('text_normalization'),
              subtitle: t('text_normalization_desc'),
              value: config!['text_normalization'] ?? true,
              onChanged: (val) {
                setState(() => config!['text_normalization'] = val);
                _scheduleSave();
              },
            ),
            const Divider(),
            _buildM3SwitchTile(
              title: t('neural_punctuation'),
              subtitle: t('neural_punctuation_desc'),
              value:
                  (config!['neural_punctuation'] ?? false) && isPunctInstalled,
              onChanged: isPunctInstalled
                  ? (val) {
                      setState(() => config!['neural_punctuation'] = val);
                      _scheduleSave();
                    }
                  : null,
              footer: AnimatedSize(
                duration: const Duration(milliseconds: 250),
                curve: Curves.easeOutCubic,
                child: !isPunctInstalled
                    ? (isPunctDownloading
                        ? Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              ClipRRect(
                                borderRadius: BorderRadius.circular(6),
                                child: LinearProgressIndicator(
                                  minHeight: 6,
                                  value: punctDownloadProgress > 0
                                      ? punctDownloadProgress
                                      : null,
                                ),
                              ),
                              const SizedBox(height: 6),
                              Text(
                                '${t('punct_downloading')} ${(punctDownloadProgress * 100).toInt()}%',
                                style: textTheme.labelSmall
                                    ?.copyWith(color: cs.primary),
                              ),
                            ],
                          )
                        : FilledButton.tonalIcon(
                            icon: const Icon(Icons.download_rounded, size: 16),
                            label: Text(t('punct_download_btn')),
                            onPressed: _startPunctDownload,
                          ))
                    : Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: cs.primaryContainer,
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(Icons.check_circle_rounded,
                                size: 14, color: cs.onPrimaryContainer),
                            const SizedBox(width: 6),
                            Text(
                              t('punct_installed_badge'),
                              style: textTheme.labelSmall?.copyWith(
                                color: cs.onPrimaryContainer,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
              ),
            ),
          ],
        ),
        _buildM3Card(
          title: t('diagnostics'),
          icon: Icons.bug_report_rounded,
          staggerIndex: 3,
          children: [
            _buildM3SwitchTile(
              title: t('enable_debug'),
              subtitle: t('check_logs'),
              value: config!['debug'] ?? false,
              onChanged: (val) {
                setState(() => config!['debug'] = val);
                _scheduleSave();
              },
            ),
          ],
        ),
      ],
    );
  }

  Widget _buildM3SwitchTile({
    required String title,
    required String subtitle,
    required bool value,
    required ValueChanged<bool>? onChanged,
    Widget? footer,
  }) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: textTheme.titleSmall
                        ?.copyWith(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: textTheme.bodySmall
                        ?.copyWith(color: cs.onSurfaceVariant),
                  ),
                ],
              ),
            ),
            const SizedBox(width: 16),
            Switch(
              thumbIcon: WidgetStateProperty.resolveWith<Icon?>((states) {
                if (states.contains(WidgetState.selected)) {
                  return const Icon(Icons.check_rounded);
                }
                return null;
              }),
              value: value,
              onChanged: onChanged,
            ),
          ],
        ),
        if (footer != null) ...[
          const SizedBox(height: 12),
          footer,
        ],
      ],
    );
  }

  Widget _buildDropdown(
    String label,
    String? section,
    String key,
    List<String> options,
  ) {
    String currentVal = section != null ? config![section][key] : config![key];
    if (!options.contains(currentVal)) {
      options = List.from(options)..add(currentVal);
    }

    final optionNames = {
      'auto': t('lang_auto'),
      'en': t('lang_en'),
      'it': t('lang_it'),
      'es': t('lang_es'),
      'fr': t('lang_fr'),
      'alt': 'Alt',
      'ctrl': 'Ctrl',
      'shift': 'Shift',
      'super': 'Super',
      'dark': t('theme_dark'),
      'light': t('theme_light'),
      'system': t('theme_system'),
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _buildFieldLabel(label),
        DropdownButtonFormField<String>(
          key: ValueKey('dropdown_${section ?? 'root'}_${key}_$currentVal'),
          initialValue: currentVal,
          isExpanded: true,
          borderRadius: BorderRadius.circular(14),
          items: options.map((o) {
            final displayName = optionNames[o] ?? o;
            return DropdownMenuItem(value: o, child: Text(displayName));
          }).toList(),
          onChanged: (val) {
            if (val != null) {
              setState(() {
                if (section != null) {
                  config![section][key] = val;
                } else {
                  config![key] = val;
                }
              });
              _scheduleSave();
              if (key == 'gui_language') {
                _updateTrayMenu();
              } else if (key == 'theme_mode') {
                if (val == 'light') {
                  themeModeNotifier.value = ThemeMode.light;
                } else if (val == 'system') {
                  themeModeNotifier.value = ThemeMode.system;
                } else {
                  themeModeNotifier.value = ThemeMode.dark;
                }
              }
            }
          },
        ),
      ],
    );
  }

  Widget _buildTextField(
      String label, String section, String key, String modifierKey) {
    return ShortcutRecorderWidget(
      label: label,
      modifierKey: modifierKey,
      initialValue:
          (config![section][key] ?? (key == 'ocr_key' ? 'r' : '')).toString(),
      onChanged: (val) => _updateNestedConfig(section, key, val),
      promptText: t('press_a_key'),
    );
  }

  Widget _buildSlider({
    required String label,
    required String section,
    required String keyName,
    required double min,
    required double max,
  }) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    final double val = (config![section][keyName] as num).toDouble();
    final bool isDefault = (val - 1.0).abs() < 0.01;

    return Padding(
      padding: const EdgeInsets.only(bottom: 16.0),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  label,
                  style: textTheme.labelLarge?.copyWith(
                    color: cs.onSurface,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              if (!isDefault)
                IconButton(
                  visualDensity: VisualDensity.compact,
                  tooltip: '1.00x',
                  onPressed: () => _updateNestedConfig(section, keyName, 1.0),
                  icon: Icon(Icons.restart_alt_rounded,
                      size: 18, color: cs.onSurfaceVariant),
                ),
              AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                padding:
                    const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: cs.primaryContainer,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  '${val.toStringAsFixed(2)}x',
                  style: textTheme.labelMedium?.copyWith(
                    color: cs.onPrimaryContainer,
                    fontWeight: FontWeight.bold,
                  ),
                ),
              ),
            ],
          ),
          Semantics(
            label: '$label Slider',
            value: val.toStringAsFixed(2),
            child: Slider(
              value: val,
              min: min,
              max: max,
              divisions: ((max - min) * 10).toInt(),
              label: '${val.toStringAsFixed(2)}x',
              onChanged: (newVal) =>
                  _updateNestedConfig(section, keyName, newVal),
            ),
          ),
        ],
      ),
    );
  }
}

/// Staggered fade & vertical slide entrance animation for Material 3 section cards.
class _StaggeredEntrance extends StatefulWidget {
  final Widget child;
  final Duration delay;

  const _StaggeredEntrance({
    required this.child,
    this.delay = Duration.zero,
  });

  @override
  State<_StaggeredEntrance> createState() => _StaggeredEntranceState();
}

class _StaggeredEntranceState extends State<_StaggeredEntrance>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;
  late final Animation<double> _opacity;
  late final Animation<Offset> _slide;
  Timer? _delayTimer;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 360),
    );
    _opacity = CurvedAnimation(parent: _controller, curve: Curves.easeOutCubic);
    _slide = Tween<Offset>(
      begin: const Offset(0, 0.04),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOutQuart));

    if (widget.delay == Duration.zero) {
      _controller.forward();
    } else {
      _delayTimer = Timer(widget.delay, () {
        if (mounted) _controller.forward();
      });
    }
  }

  @override
  void dispose() {
    _delayTimer?.cancel();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _opacity,
      child: SlideTransition(
        position: _slide,
        child: widget.child,
      ),
    );
  }
}

class ShortcutRecorderWidget extends StatefulWidget {
  final String label;
  final String modifierKey;
  final String initialValue;
  final ValueChanged<String> onChanged;
  final String promptText;

  const ShortcutRecorderWidget({
    super.key,
    required this.label,
    required this.modifierKey,
    required this.initialValue,
    required this.onChanged,
    required this.promptText,
  });

  @override
  State<ShortcutRecorderWidget> createState() => _ShortcutRecorderWidgetState();
}

class _ShortcutRecorderWidgetState extends State<ShortcutRecorderWidget>
    with SingleTickerProviderStateMixin {
  late FocusNode _focusNode;
  late String _currentValue;
  late AnimationController _pulseController;
  bool _isListening = false;

  @override
  void initState() {
    super.initState();
    _currentValue = widget.initialValue;
    _pulseController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 900),
    );
    _focusNode = FocusNode();
    _focusNode.addListener(() {
      if (!mounted) return;
      setState(() {
        _isListening = _focusNode.hasFocus;
        if (_isListening) {
          _pulseController.repeat(reverse: true);
        } else {
          _pulseController.stop();
          _pulseController.value = 0.0;
        }
      });
    });
  }

  @override
  void didUpdateWidget(covariant ShortcutRecorderWidget oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.initialValue != widget.initialValue && !_isListening) {
      _currentValue = widget.initialValue;
    }
  }

  @override
  void dispose() {
    _pulseController.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          widget.label,
          style: textTheme.labelLarge?.copyWith(
            color: cs.onSurfaceVariant,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        Focus(
          focusNode: _focusNode,
          onKeyEvent: (node, event) {
            if (event is KeyDownEvent) {
              String keyStr = event.logicalKey.keyLabel.toLowerCase();
              if (keyStr == 'escape') keyStr = 'esc';
              if (keyStr == 'control') keyStr = 'ctrl';
              if (keyStr == ' ') keyStr = 'space';

              setState(() {
                _currentValue = keyStr;
              });
              widget.onChanged(keyStr);
              _focusNode.unfocus();
              return KeyEventResult.handled;
            }
            return KeyEventResult.ignored;
          },
          child: InkWell(
            borderRadius: BorderRadius.circular(14),
            onTap: () {
              if (_isListening) {
                _focusNode.unfocus();
              } else {
                _focusNode.requestFocus();
              }
            },
            child: AnimatedBuilder(
              animation: _pulseController,
              builder: (context, _) {
                final double pulse = _pulseController.value;
                return AnimatedContainer(
                  duration: const Duration(milliseconds: 200),
                  width: double.infinity,
                  padding:
                      const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
                  decoration: BoxDecoration(
                    color: _isListening
                        ? Color.lerp(
                            cs.primaryContainer.withValues(alpha: 0.35),
                            cs.primaryContainer.withValues(alpha: 0.65),
                            pulse,
                          )
                        : cs.surfaceContainerHighest.withValues(alpha: 0.45),
                    borderRadius: BorderRadius.circular(14),
                    border: Border.all(
                      color: _isListening
                          ? Color.lerp(cs.primary, cs.tertiary, pulse)!
                          : cs.outlineVariant.withValues(alpha: 0.7),
                      width: _isListening ? 2 : 1,
                    ),
                  ),
                  child: AnimatedSwitcher(
                    duration: const Duration(milliseconds: 180),
                    layoutBuilder: (currentChild, previousChildren) {
                      return Align(
                        alignment: Alignment.centerLeft,
                        child: currentChild,
                      );
                    },
                    child: _isListening
                        ? Text(
                            widget.promptText,
                            key: const ValueKey('listening'),
                            style: textTheme.bodyMedium?.copyWith(
                              color: cs.primary,
                              fontWeight: FontWeight.w600,
                              fontStyle: FontStyle.italic,
                            ),
                          )
                        : Row(
                            key: ValueKey('key_$_currentValue'),
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              _KeycapBadge(
                                  label: widget.modifierKey.toUpperCase()),
                              Padding(
                                padding:
                                    const EdgeInsets.symmetric(horizontal: 6.0),
                                child: Text(
                                  '+',
                                  style: textTheme.labelMedium
                                      ?.copyWith(color: cs.onSurfaceVariant),
                                ),
                              ),
                              _KeycapBadge(
                                label: (_currentValue.isEmpty
                                        ? '...'
                                        : _currentValue)
                                    .toUpperCase(),
                                isPrimary: true,
                              ),
                            ],
                          ),
                  ),
                );
              },
            ),
          ),
        ),
      ],
    );
  }
}

class _KeycapBadge extends StatelessWidget {
  final String label;
  final bool isPrimary;

  const _KeycapBadge({
    required this.label,
    this.isPrimary = false,
  });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final textTheme = Theme.of(context).textTheme;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: isPrimary ? cs.secondaryContainer : cs.surfaceContainerHigh,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(
          color: isPrimary
              ? cs.secondary.withValues(alpha: 0.3)
              : cs.outlineVariant,
        ),
      ),
      child: Text(
        label,
        style: textTheme.labelMedium?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.5,
          color: isPrimary ? cs.onSecondaryContainer : cs.onSurface,
        ),
      ),
    );
  }
}

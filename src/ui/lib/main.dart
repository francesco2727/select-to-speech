import 'dart:convert';
import 'dart:io';
import 'dart:ui';
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'package:http/http.dart' as http;
import 'package:http/io_client.dart';
import 'package:tray_manager/tray_manager.dart';

final ValueNotifier<ThemeMode> themeModeNotifier = ValueNotifier(ThemeMode.system);

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await startPythonBackend();
  runApp(const SelectToSpeechApp());
}

Process? pythonBackend;

Future<void> startPythonBackend() async {
  // Check if Python backend is already running on UDS socket
  final client = createUdsClient();
  try {
    final res = await client.get(Uri.parse('http://localhost/status')).timeout(const Duration(milliseconds: 250));
    if (res.statusCode == 200) {
      debugPrint('Python backend is already running.');
      client.close();
      return;
    }
  } catch (_) {
    // Not running or timed out, proceed to start it
  } finally {
    client.close();
  }

  String executablePath = Platform.resolvedExecutable;
  Directory current = Directory(executablePath).parent;
  String? venvPath;
  while (current.path != '/') {
    if (Directory('${current.path}/.venv').existsSync()) {
      venvPath = '${current.path}/.venv/bin/select-to-speech';
      break;
    }
    current = current.parent;
  }
  
  if (venvPath != null) {
    try {
      pythonBackend = await Process.start(venvPath, []);
      debugPrint('Python backend started with PID: ${pythonBackend?.pid}');
    } catch (e) {
      debugPrint('Error starting python backend: $e');
    }
  } else {
    debugPrint('Warning: could not find .venv');
  }
}

http.Client createUdsClient() {
  String homeDir = Platform.environment['HOME'] ?? '';
  String socketPath = '$homeDir/.local/state/select-to-speech/ipc.sock';
  var ioClient = HttpClient()
    ..connectionFactory = (uri, proxyHost, proxyPort) {
      return Socket.startConnect(
          InternetAddress(socketPath, type: InternetAddressType.unix), 0);
    };
  return IOClient(ioClient);
}

class SelectToSpeechApp extends StatelessWidget {
  const SelectToSpeechApp({super.key});

  @override
  Widget build(BuildContext context) {
    return ValueListenableBuilder<ThemeMode>(
      valueListenable: themeModeNotifier,
      builder: (context, currentThemeMode, _) {
        return MaterialApp(
          title: 'Select to Speech',
          themeMode: currentThemeMode,
          theme: ThemeData(
            brightness: Brightness.light,
            primaryColor: const Color(0xFF7B61FF),
            scaffoldBackgroundColor: const Color(0xFFF5F5FA),
            cardColor: const Color(0xFFFFFFFF),
            colorScheme: const ColorScheme.light(
              primary: Color(0xFF7B61FF),
              secondary: Color(0xFF00E5FF),
              surface: Color(0xFFFFFFFF),
            ),
            fontFamily: 'Inter',
            sliderTheme: const SliderThemeData(
              activeTrackColor: Color(0xFF7B61FF),
              inactiveTrackColor: Color(0xFFE0E0E0),
              thumbColor: Color(0xFF7B61FF),
              overlayColor: Color(0x337B61FF),
            ),
          ),
          darkTheme: ThemeData(
            brightness: Brightness.dark,
            primaryColor: const Color(0xFF7B61FF),
            scaffoldBackgroundColor: const Color(0xFF0F0F1A),
            cardColor: const Color(0xFF1E1E2E),
            colorScheme: const ColorScheme.dark(
              primary: Color(0xFF7B61FF),
              secondary: Color(0xFF00E5FF),
              surface: Color(0xFF1E1E2E),
            ),
            fontFamily: 'Inter',
            sliderTheme: const SliderThemeData(
              activeTrackColor: Color(0xFF00E5FF),
              inactiveTrackColor: Color(0xFF33334D),
              thumbColor: Color(0xFFFFFFFF),
              overlayColor: Color(0x3300E5FF),
            ),
          ),
          home: const SettingsScreen(),
        );
      }
    );
  }
}

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> with TrayListener {
  late http.Client apiClient;
  int _selectedIndex = 0;
  
  bool isLoading = true;
  Map<String, dynamic>? config;
  List<dynamic> audioDevices = [];
  Map<String, List<String>> availableVoices = {};

  // Download state variables
  bool isDownloading = false;
  double downloadProgress = 0.0;
  String downloadStatus = 'idle';
  String? downloadError;

  bool get isDark => Theme.of(context).brightness == Brightness.dark;
  Color get textColor => isDark ? Colors.white : const Color(0xFF1E1E2E);
  Color get textColor70 => isDark ? Colors.white70 : Colors.black87;
  Color get textColor54 => isDark ? Colors.white54 : Colors.black54;
  Color get dropdownBgColor => isDark ? const Color(0xFF1E1E2E) : const Color(0xFFFFFFFF);
  Color get inputBgColor => isDark ? Colors.black.withValues(alpha: 0.2) : Colors.black.withValues(alpha: 0.04);
  Color get inputBorderColor => isDark ? Colors.white12 : Colors.black12;

  static const Map<String, Map<String, String>> translations = {
    'en': {
      'app_title': 'Select to Speech',
      'settings': 'Settings',
      'quit': 'Quit',
      'failed_connect': 'Failed to connect to backend',
      'retry': 'Retry',
      'tab_voice': 'Voice',
      'tab_audio': 'Audio',
      'tab_shortcuts': 'Shortcuts',
      'tab_general': 'General',
      'save_settings': 'Save Settings',
      'voice_config': 'Voice Configuration',
      'voice_model': 'Voice Model',
      'redownload': 'Re-download',
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
      'modifier_key': 'Modifier Key',
      'trigger_key': 'Trigger Key (e.g. esc)',
      'pause_key': 'Pause/Resume Key (e.g. w)',
      'stop_key': 'Stop Key (e.g. s)',
      'general_settings': 'General Settings',
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
      'theme': 'Theme',
      'theme_dark': 'Dark',
      'theme_light': 'Light',
      'theme_system': 'System Default',
    },
    'it': {
      'app_title': 'Select to Speech',
      'settings': 'Impostazioni',
      'quit': 'Esci',
      'failed_connect': 'Impossibile connettersi al backend',
      'retry': 'Riprova',
      'tab_voice': 'Voce',
      'tab_audio': 'Audio',
      'tab_shortcuts': 'Scorciatoie',
      'tab_general': 'Generale',
      'save_settings': 'Salva Impostazioni',
      'voice_config': 'Configurazione Voce',
      'voice_model': 'Modello Vocale',
      'redownload': 'Riscarica',
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
      'modifier_key': 'Tasto Modificatore',
      'trigger_key': 'Tasto di Attivazione (es. esc)',
      'pause_key': 'Tasto Pausa/Riprendi (es. w)',
      'stop_key': 'Tasto Interrompi (es. s)',
      'general_settings': 'Impostazioni Generali',
      'gui_language': 'Lingua dell\'Interfaccia',
      'enable_debug': 'Abilita Log di Debug',
      'check_logs': 'Controlla i log in ~/.local/state/select-to-speech/app.log',
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
      'theme': 'Tema',
      'theme_dark': 'Scuro',
      'theme_light': 'Chiaro',
      'theme_system': 'Predefinito di Sistema',
    },
    'es': {
      'app_title': 'Select to Speech',
      'settings': 'Ajustes',
      'quit': 'Salir',
      'failed_connect': 'Error al conectar con el backend',
      'retry': 'Reintentar',
      'tab_voice': 'Voz',
      'tab_audio': 'Audio',
      'tab_shortcuts': 'Atajos',
      'tab_general': 'General',
      'save_settings': 'Guardar Ajustes',
      'voice_config': 'Configuración de Voz',
      'voice_model': 'Modelo de Voz',
      'redownload': 'Volver a descargar',
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
      'modifier_key': 'Tecla Modificadora',
      'trigger_key': 'Tecla de Activación (ej. esc)',
      'pause_key': 'Tecla Pausa/Reanudar (ej. w)',
      'stop_key': 'Tecla Detener (ej. s)',
      'general_settings': 'Ajustes Generales',
      'gui_language': 'Idioma de la Interfaz',
      'enable_debug': 'Habilitar Registro de Depuración',
      'check_logs': 'Revisa los registros en ~/.local/state/select-to-speech/app.log',
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
      'theme': 'Tema',
      'theme_dark': 'Oscuro',
      'theme_light': 'Claro',
      'theme_system': 'Predeterminato del Sistema',
    },
    'fr': {
      'app_title': 'Select to Speech',
      'settings': 'Paramètres',
      'quit': 'Quitter',
      'failed_connect': 'Échec de connexion au serveur',
      'retry': 'Réessayer',
      'tab_voice': 'Voix',
      'tab_audio': 'Audio',
      'tab_shortcuts': 'Raccourcis',
      'tab_general': 'Général',
      'save_settings': 'Enregistrer les paramètres',
      'voice_config': 'Configuration de la Voix',
      'voice_model': 'Modèle de Voix',
      'redownload': 'Re-télécharger',
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
      'modifier_key': 'Touche Modificatrice',
      'trigger_key': 'Touche de Déclenchement (ex. esc)',
      'pause_key': 'Touche Pause/Reprise (ex. w)',
      'stop_key': 'Touche d\'Arrêt (ex. s)',
      'general_settings': 'Paramètres Généraux',
      'gui_language': 'Langue de l\'Interface',
      'enable_debug': 'Activer le Journal de Débogage',
      'check_logs': 'Vérifiez les journaux dans ~/.local/state/select-to-speech/app.log',
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
      'theme': 'Thème',
      'theme_dark': 'Sombre',
      'theme_light': 'Clair',
      'theme_system': 'Par Défaut du Système',
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
    _initTray();
    _fetchData();
  }

  Future<void> _initTray() async {
    String iconPath = Platform.isWindows ? 'images/tray_icon.ico' : 'images/select_to_speech_tray_icon.svg';
    if (Platform.isLinux) {
      final String exeDir = File(Platform.resolvedExecutable).parent.path;
      iconPath = '$exeDir/data/flutter_assets/images/select_to_speech_tray_icon.svg';
    }
    await trayManager.setIcon(iconPath);
    await _updateTrayMenu();
    trayManager.addListener(this);
  }

  Future<void> _updateTrayMenu() async {
    await trayManager.setContextMenu(Menu(items: [
      MenuItem(key: 'settings', label: t('settings')),
      MenuItem.separator(),
      MenuItem(key: 'quit', label: t('quit')),
    ]));
  }

  @override
  void onTrayIconMouseDown() {
    Process.run(Platform.resolvedExecutable, []);
  }

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    if (menuItem.key == 'quit') {
      _quit();
    } else if (menuItem.key == 'settings') {
      Process.run(Platform.resolvedExecutable, []);
    }
  }

  Future<void> _quit() async {
    try {
      await apiClient.post(Uri.parse('http://localhost/stop'));
    } catch (_) {}
    pythonBackend?.kill();
    exit(0);
  }

  Future<void> _startDownload() async {
    setState(() {
      isDownloading = true;
      downloadProgress = 0.0;
      downloadStatus = 'downloading';
      downloadError = null;
    });

    try {
      final res = await apiClient.post(Uri.parse('http://localhost/download_model?force=true'));
      if (res.statusCode == 200) {
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

  void _pollDownloadStatus() async {
    while (isDownloading) {
      await Future.delayed(const Duration(milliseconds: 800));
      if (!mounted) return;
      try {
        final res = await apiClient.get(Uri.parse('http://localhost/download_status'));
        if (res.statusCode == 200) {
          final data = jsonDecode(res.body);
          setState(() {
            downloadStatus = data['status'];
            downloadProgress = (data['progress'] as num).toDouble() / 100.0;
            if (downloadStatus == 'success') {
              isDownloading = false;
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text(t('download_success')), backgroundColor: Colors.green),
              );
            } else if (downloadStatus == 'failed') {
              isDownloading = false;
              downloadError = data['error'];
              ScaffoldMessenger.of(context).showSnackBar(
                SnackBar(content: Text('${t('download_failed')}: ${data['error']}'), backgroundColor: Colors.redAccent),
              );
            }
          });
        }
      } catch (e) {
        // Ignore network errors during polling
      }
    }
  }
  
  Future<void> _fetchData() async {
    setState(() => isLoading = true);
    int retries = 5;
    while (retries > 0) {
      try {
        final configRes = await apiClient.get(Uri.parse('http://localhost/config'));
        final devicesRes = await apiClient.get(Uri.parse('http://localhost/audio_devices'));
        final voicesRes = await apiClient.get(Uri.parse('http://localhost/voices'));
        
        if (configRes.statusCode == 200) {
          setState(() {
            config = jsonDecode(configRes.body);
            config!['theme_mode'] ??= 'dark';
            final themeStr = config!['theme_mode'];
            if (themeStr == 'light') {
              themeModeNotifier.value = ThemeMode.light;
            } else if (themeStr == 'system') {
              themeModeNotifier.value = ThemeMode.system;
            } else {
              themeModeNotifier.value = ThemeMode.dark;
            }
            if (devicesRes.statusCode == 200) {
              audioDevices = jsonDecode(devicesRes.body);
            }
            if (voicesRes.statusCode == 200) {
              Map<String, dynamic> voicesMap = jsonDecode(voicesRes.body);
              availableVoices = voicesMap.map((key, val) => MapEntry(key, List<String>.from(val)));
            }
            isLoading = false;
          });
          // Update the tray menu with localized strings based on the loaded config
          _updateTrayMenu();
          return;
        }
      } catch (e) {
        retries--;
        await Future.delayed(const Duration(milliseconds: 500));
      }
    }
    setState(() => isLoading = false);
  }

  Future<void> _saveConfig() async {
    if (config == null) return;
    try {
      final res = await apiClient.post(
        Uri.parse('http://localhost/config'),
        headers: {'Content-Type': 'application/json'},
        body: jsonEncode(config),
      );
      if (!mounted) return;
      if (res.statusCode == 200) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text(t('save_success')), backgroundColor: Colors.green),
        );
      } else {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('${t('save_failed')}: ${res.statusCode}'),
            backgroundColor: Colors.redAccent,
          ),
        );
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${t('save_failed')}: $e'), backgroundColor: Colors.redAccent),
      );
    }
  }

  void _updateNestedConfig(String section, String key, dynamic value) {
    setState(() {
      if (config != null && config![section] != null) {
        config![section][key] = value;
      }
    });
  }

  @override
  void dispose() {
    trayManager.removeListener(this);
    super.dispose();
  }

  Widget _getSelectedTabWidget() {
    switch (_selectedIndex) {
      case 0:
        return _buildVoiceTab();
      case 1:
        return _buildAudioTab();
      case 2:
        return _buildKeyboardTab();
      case 3:
        return _buildGeneralTab();
      default:
        return _buildVoiceTab();
    }
  }

  Widget _buildCenteredTab(Widget tabContent) {
    return LayoutBuilder(
      builder: (context, constraints) {
        return SingleChildScrollView(
          physics: const AlwaysScrollableScrollPhysics(),
          child: ConstrainedBox(
            constraints: BoxConstraints(
              minHeight: constraints.maxHeight,
            ),
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 550),
                child: tabContent,
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _buildSidebarItem(int index, IconData icon, String label) {
    final isSelected = _selectedIndex == index;
    
    return InkWell(
      onTap: () {
        setState(() {
          _selectedIndex = index;
        });
      },
      borderRadius: BorderRadius.circular(12),
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 200),
        padding: const EdgeInsets.symmetric(horizontal: 16.0, vertical: 12.0),
        decoration: BoxDecoration(
          color: isSelected
              ? const Color(0xFF7B61FF).withValues(alpha: 0.15)
              : Colors.transparent,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(
            color: isSelected
                ? const Color(0xFF7B61FF).withValues(alpha: 0.3)
                : Colors.transparent,
            width: 1,
          ),
        ),
        child: Row(
          children: [
            Icon(
              icon,
              color: isSelected 
                  ? const Color(0xFF7B61FF) 
                  : (isDark ? Colors.white54 : Colors.black45),
              size: 20,
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Text(
                label,
                style: TextStyle(
                  color: isSelected 
                      ? (isDark ? Colors.white : const Color(0xFF7B61FF)) 
                      : (isDark ? Colors.white70 : Colors.black87),
                  fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
                  fontSize: 14,
                ),
              ),
            ),
            if (isSelected)
              Container(
                width: 6,
                height: 6,
                decoration: const BoxDecoration(
                  color: Color(0xFF00E5FF),
                  shape: BoxShape.circle,
                  boxShadow: [
                    BoxShadow(
                      color: Color(0xFF00E5FF),
                      blurRadius: 4,
                      spreadRadius: 1,
                    ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _buildSidebar(BuildContext context) {
    return Container(
      width: 260,
      decoration: BoxDecoration(
        color: isDark
            ? const Color(0xFF1E1E2E).withValues(alpha: 0.4)
            : const Color(0xFFFFFFFF).withValues(alpha: 0.4),
        border: Border(
          right: BorderSide(
            color: isDark
                ? Colors.white.withValues(alpha: 0.08)
                : Colors.black.withValues(alpha: 0.08),
            width: 1,
          ),
        ),
      ),
      child: ClipRect(
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 10, sigmaY: 10),
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 24.0, horizontal: 16.0),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Padding(
                  padding: const EdgeInsets.symmetric(horizontal: 8.0, vertical: 12.0),
                  child: Row(
                    children: [
                      Container(
                        padding: const EdgeInsets.all(8),
                        decoration: BoxDecoration(
                          color: const Color(0xFF7B61FF).withValues(alpha: 0.2),
                          borderRadius: BorderRadius.circular(12),
                          border: Border.all(
                            color: const Color(0xFF7B61FF).withValues(alpha: 0.4),
                            width: 1.5,
                          ),
                        ),
                        child: SvgPicture.asset(
                          'images/select_to_speech_tray_icon.svg',
                          width: 24,
                          height: 24,
                          colorFilter: const ColorFilter.mode(
                            Color(0xFF7B61FF),
                            BlendMode.srcIn,
                          ),
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Text(
                          t('app_title'),
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.bold,
                            letterSpacing: 0.5,
                            color: textColor,
                          ),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 32),
                _buildSidebarItem(0, Icons.record_voice_over_rounded, t('tab_voice')),
                const SizedBox(height: 8),
                _buildSidebarItem(1, Icons.volume_up_rounded, t('tab_audio')),
                const SizedBox(height: 8),
                _buildSidebarItem(2, Icons.keyboard_rounded, t('tab_shortcuts')),
                const SizedBox(height: 8),
                _buildSidebarItem(3, Icons.settings_rounded, t('tab_general')),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    if (isLoading) {
      return const Scaffold(body: Center(child: CircularProgressIndicator(color: Color(0xFF7B61FF))));
    }
    if (config == null) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 48, color: Colors.redAccent),
              const SizedBox(height: 16),
              Text(t('failed_connect'), style: TextStyle(fontSize: 18, color: textColor)),
              const SizedBox(height: 16),
              ElevatedButton(onPressed: _fetchData, child: Text(t('retry')))
            ],
          ),
        ),
      );
    }

    return Scaffold(
      body: Container(
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: isDark 
                ? [const Color(0xFF0F0F1A), const Color(0xFF1A1A2E)]
                : [const Color(0xFFF5F5FA), const Color(0xFFE8E8F3)],
          ),
        ),
        child: Row(
          children: [
            _buildSidebar(context),
            Expanded(
              child: _buildCenteredTab(_getSelectedTabWidget()),
            ),
          ],
        ),
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: _saveConfig,
        backgroundColor: const Color(0xFF7B61FF),
        foregroundColor: Colors.white,
        icon: const Icon(Icons.save_rounded),
        label: Text(t('save_settings'), style: const TextStyle(fontWeight: FontWeight.bold)),
      ),
    );
  }

  Widget _buildGlassCard({required Widget child}) {
    return Padding(
      padding: const EdgeInsets.all(16.0),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(20),
        child: BackdropFilter(
          filter: ImageFilter.blur(sigmaX: 15, sigmaY: 15),
          child: Container(
            padding: const EdgeInsets.all(24),
            decoration: BoxDecoration(
              color: isDark
                  ? const Color(0xFF2D2D44).withValues(alpha: 0.4)
                  : const Color(0xFFFFFFFF).withValues(alpha: 0.7),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(
                color: isDark
                    ? Colors.white.withValues(alpha: 0.1)
                    : Colors.black.withValues(alpha: 0.08),
              ),
              boxShadow: [
                BoxShadow(
                  color: isDark
                      ? Colors.black.withValues(alpha: 0.2)
                      : Colors.black.withValues(alpha: 0.05),
                  blurRadius: 10,
                  offset: const Offset(0, 5),
                )
              ]
            ),
            child: child,
          ),
        ),
      ),
    );
  }

  Widget _buildLanguageVoiceDropdown(String langCode, String langName) {
    List<String> voices = availableVoices[langCode] ?? [];
    String currentVal = config!['voice']['language_models'][langCode] ?? '';
    
    // Ensure currentVal is valid
    if (currentVal != '' && !voices.contains(currentVal)) {
      voices = List.from(voices)..add(currentVal);
    }
    
    final label = t('voice_lang_template').replaceAll('{lang}', t('lang_$langCode'));
    
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(color: textColor70)),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: inputBgColor,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: inputBorderColor),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              value: currentVal,
              style: TextStyle(color: textColor, fontFamily: 'Inter'),
              items: [
                DropdownMenuItem(value: '', child: Text(t('none_disabled'), style: TextStyle(color: textColor))),
                ...voices.map((v) => DropdownMenuItem(value: v, child: Text(v, style: TextStyle(color: textColor)))),
              ],
              onChanged: (val) {
                if (val != null) {
                  setState(() {
                    config!['voice']['language_models'][langCode] = val;
                  });
                }
              },
              dropdownColor: dropdownBgColor,
            ),
          ),
        ),
        const SizedBox(height: 16),
      ],
    );
  }

  Widget _buildVoiceTab() {
    final List<Map<String, String>> supportedLanguagesList = const [
      {'code': 'en', 'name': 'English'},
      {'code': 'it', 'name': 'Italian'},
      {'code': 'es', 'name': 'Spanish'},
      {'code': 'fr', 'name': 'French'},
      {'code': 'pt', 'name': 'Portuguese'},
      {'code': 'hi', 'name': 'Hindi'},
      {'code': 'ja', 'name': 'Japanese'},
      {'code': 'zh', 'name': 'Chinese'},
    ];

    return _buildGlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('voice_config'), style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: textColor)),
          const SizedBox(height: 24),
          
          Text(t('voice_model'), style: TextStyle(color: textColor70)),
          const SizedBox(height: 8),
          Row(
            children: [
              Expanded(
                child: TextFormField(
                  initialValue: config!['voice']['model'],
                  style: TextStyle(color: textColor),
                  decoration: InputDecoration(
                    filled: true,
                    fillColor: inputBgColor,
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide(color: inputBorderColor),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide(color: inputBorderColor),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: const BorderSide(color: Color(0xFF00E5FF)),
                    ),
                  ),
                  onChanged: (val) => _updateNestedConfig('voice', 'model', val),
                ),
              ),
              const SizedBox(width: 12),
              ElevatedButton.icon(
                onPressed: isDownloading ? null : _startDownload,
                style: ElevatedButton.styleFrom(
                  backgroundColor: const Color(0xFF7B61FF),
                  foregroundColor: Colors.white,
                  padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
                icon: isDownloading
                    ? const SizedBox(
                        width: 16,
                        height: 16,
                        child: CircularProgressIndicator(color: Colors.white, strokeWidth: 2),
                      )
                    : const Icon(Icons.download, size: 18),
                label: Text(isDownloading ? t('downloading') : t('redownload')),
              ),
            ],
          ),
          
          if (isDownloading) ...[
            const SizedBox(height: 12),
            Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                LinearProgressIndicator(
                  value: downloadProgress > 0 ? downloadProgress : null,
                  backgroundColor: isDark ? Colors.white10 : Colors.black12,
                  valueColor: const AlwaysStoppedAnimation<Color>(Color(0xFF00E5FF)),
                ),
                const SizedBox(height: 4),
                Text(
                  downloadProgress > 0
                      ? '${t('downloading')} ${(downloadProgress * 100).toInt()}%'
                      : t('preparing_download'),
                  style: TextStyle(fontSize: 12, color: textColor70),
                ),
              ],
            ),
          ],
          if (downloadError != null) ...[
            const SizedBox(height: 8),
            Text(
              '${t('error')}: $downloadError',
              style: const TextStyle(color: Colors.redAccent, fontSize: 13),
            ),
          ],
          
          const SizedBox(height: 32),
          Text(t('language_voices'), style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold, color: textColor)),
          const SizedBox(height: 16),
          ...supportedLanguagesList.map((lang) => _buildLanguageVoiceDropdown(lang['code']!, lang['name']!)),
        ],
      ),
    );
  }

  Widget _buildAudioTab() {
    List<DropdownMenuItem<int?>> deviceItems = [
      DropdownMenuItem(value: null, child: Text(t('default_device'), style: TextStyle(color: textColor))),
    ];
    for (var dev in audioDevices) {
      deviceItems.add(DropdownMenuItem(value: dev['id'], child: Text('${dev['name']} (ID: ${dev['id']})', style: TextStyle(color: textColor))));
    }

    return _buildGlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('audio_settings'), style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: textColor)),
          const SizedBox(height: 24),
          
          Text(t('output_device'), style: TextStyle(color: textColor70)),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 16),
            decoration: BoxDecoration(
              color: inputBgColor,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: inputBorderColor),
            ),
            child: DropdownButtonHideUnderline(
              child: DropdownButton<int?>(
                isExpanded: true,
                value: config!['audio']['device_id'],
                style: TextStyle(color: textColor, fontFamily: 'Inter'),
                items: deviceItems,
                onChanged: (val) => _updateNestedConfig('audio', 'device_id', val),
                dropdownColor: dropdownBgColor,
              ),
            ),
          ),
          const SizedBox(height: 24),

          _buildSlider(t('speed'), 'audio', 'speed', 0.5, 2.0),
          _buildSlider(t('pitch'), 'audio', 'pitch', 0.5, 2.0),
          _buildSlider(t('volume'), 'audio', 'volume', 0.0, 2.0),
        ],
      ),
    );
  }

  Widget _buildKeyboardTab() {
    return _buildGlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('keyboard_shortcuts'), style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: textColor)),
          const SizedBox(height: 24),
          _buildDropdown(t('modifier_key'), 'keyboard', 'modifier_key', ['alt', 'ctrl', 'shift', 'super']),
          const SizedBox(height: 16),
          _buildTextField(t('trigger_key'), 'keyboard', 'trigger_key'),
          const SizedBox(height: 16),
          _buildTextField(t('pause_key'), 'keyboard', 'pause_key'),
          const SizedBox(height: 16),
          _buildTextField(t('stop_key'), 'keyboard', 'stop_key'),
        ],
      ),
    );
  }

  Widget _buildGeneralTab() {
    return _buildGlassCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(t('general_settings'), style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold, color: textColor)),
          const SizedBox(height: 24),
          _buildDropdown(t('gui_language'), null, 'gui_language', ['auto', 'en', 'it', 'es', 'fr']),
          const SizedBox(height: 16),
          _buildDropdown(t('theme'), null, 'theme_mode', ['dark', 'light', 'system']),
          const SizedBox(height: 16),
          SwitchListTile(
            title: Text(t('enable_debug'), style: TextStyle(color: textColor)),
            subtitle: Text(t('check_logs'), style: TextStyle(color: textColor54)),
            value: config!['debug'] ?? false,
            activeThumbColor: const Color(0xFF7B61FF),
            onChanged: (val) => setState(() => config!['debug'] = val),
            contentPadding: EdgeInsets.zero,
          ),
        ],
      ),
    );
  }

  Widget _buildDropdown(String label, String? section, String key, List<String> options) {
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
        Text(label, style: TextStyle(color: textColor70)),
        const SizedBox(height: 8),
        Container(
          padding: const EdgeInsets.symmetric(horizontal: 16),
          decoration: BoxDecoration(
            color: inputBgColor,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: inputBorderColor),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              value: currentVal,
              style: TextStyle(color: textColor, fontFamily: 'Inter'),
              items: options.map((o) {
                final displayName = optionNames[o] ?? o;
                return DropdownMenuItem(value: o, child: Text(displayName, style: TextStyle(color: textColor)));
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
              dropdownColor: dropdownBgColor,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildTextField(String label, String section, String key) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(label, style: TextStyle(color: textColor70)),
        const SizedBox(height: 8),
        Semantics(
          label: label,
          child: TextFormField(
            initialValue: config![section][key],
            style: TextStyle(color: textColor),
            decoration: InputDecoration(
              filled: true,
              fillColor: inputBgColor,
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: BorderSide(color: inputBorderColor),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: BorderSide(color: inputBorderColor),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(10),
                borderSide: const BorderSide(color: Color(0xFF00E5FF)),
              ),
            ),
            onChanged: (val) => _updateNestedConfig(section, key, val),
          ),
        ),
      ],
    );
  }

  Widget _buildSlider(String label, String section, String key, double min, double max) {
    double val = config![section][key].toDouble();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: TextStyle(color: textColor70)),
            Text(val.toStringAsFixed(2), style: const TextStyle(color: Color(0xFF7B61FF), fontWeight: FontWeight.bold)),
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
            onChanged: (newVal) => _updateNestedConfig(section, key, newVal),
          ),
        ),
        const SizedBox(height: 16),
      ],
    );
  }
}

/// Names of the languages the TTS engines (Kokoro, Piper) can speak, in each GUI
/// language. Keyed by ISO 639-1 code, then by GUI language code.
const Map<String, Map<String, String>> languageNames = {
  'ar': {'en': 'Arabic', 'it': 'Arabo', 'es': 'Árabe', 'fr': 'Arabe'},
  'ca': {'en': 'Catalan', 'it': 'Catalano', 'es': 'Catalán', 'fr': 'Catalan'},
  'cs': {'en': 'Czech', 'it': 'Ceco', 'es': 'Checo', 'fr': 'Tchèque'},
  'cy': {'en': 'Welsh', 'it': 'Gallese', 'es': 'Galés', 'fr': 'Gallois'},
  'da': {'en': 'Danish', 'it': 'Danese', 'es': 'Danés', 'fr': 'Danois'},
  'de': {'en': 'German', 'it': 'Tedesco', 'es': 'Alemán', 'fr': 'Allemand'},
  'el': {'en': 'Greek', 'it': 'Greco', 'es': 'Griego', 'fr': 'Grec'},
  'en': {'en': 'English', 'it': 'Inglese', 'es': 'Inglés', 'fr': 'Anglais'},
  'es': {'en': 'Spanish', 'it': 'Spagnolo', 'es': 'Español', 'fr': 'Espagnol'},
  'eu': {'en': 'Basque', 'it': 'Basco', 'es': 'Euskera', 'fr': 'Basque'},
  'fa': {'en': 'Persian', 'it': 'Persiano', 'es': 'Persa', 'fr': 'Persan'},
  'fi': {'en': 'Finnish', 'it': 'Finlandese', 'es': 'Finés', 'fr': 'Finnois'},
  'fr': {'en': 'French', 'it': 'Francese', 'es': 'Francés', 'fr': 'Français'},
  'hi': {'en': 'Hindi', 'it': 'Hindi', 'es': 'Hindi', 'fr': 'Hindi'},
  'hu': {
    'en': 'Hungarian',
    'it': 'Ungherese',
    'es': 'Húngaro',
    'fr': 'Hongrois'
  },
  'id': {
    'en': 'Indonesian',
    'it': 'Indonesiano',
    'es': 'Indonesio',
    'fr': 'Indonésien'
  },
  'is': {
    'en': 'Icelandic',
    'it': 'Islandese',
    'es': 'Islandés',
    'fr': 'Islandais'
  },
  'it': {'en': 'Italian', 'it': 'Italiano', 'es': 'Italiano', 'fr': 'Italien'},
  'ja': {
    'en': 'Japanese',
    'it': 'Giapponese',
    'es': 'Japonés',
    'fr': 'Japonais'
  },
  'ka': {
    'en': 'Georgian',
    'it': 'Georgiano',
    'es': 'Georgiano',
    'fr': 'Géorgien'
  },
  'kk': {'en': 'Kazakh', 'it': 'Kazako', 'es': 'Kazajo', 'fr': 'Kazakh'},
  'ko': {'en': 'Korean', 'it': 'Coreano', 'es': 'Coreano', 'fr': 'Coréen'},
  'ku': {'en': 'Kurdish', 'it': 'Curdo', 'es': 'Kurdo', 'fr': 'Kurde'},
  'lb': {
    'en': 'Luxembourgish',
    'it': 'Lussemburghese',
    'es': 'Luxemburgués',
    'fr': 'Luxembourgeois'
  },
  'lv': {'en': 'Latvian', 'it': 'Lettone', 'es': 'Letón', 'fr': 'Letton'},
  'ml': {
    'en': 'Malayalam',
    'it': 'Malayalam',
    'es': 'Malayalam',
    'fr': 'Malayalam'
  },
  'ne': {'en': 'Nepali', 'it': 'Nepalese', 'es': 'Nepalí', 'fr': 'Népalais'},
  'nl': {
    'en': 'Dutch',
    'it': 'Olandese',
    'es': 'Neerlandés',
    'fr': 'Néerlandais'
  },
  'no': {
    'en': 'Norwegian',
    'it': 'Norvegese',
    'es': 'Noruego',
    'fr': 'Norvégien'
  },
  'pl': {'en': 'Polish', 'it': 'Polacco', 'es': 'Polaco', 'fr': 'Polonais'},
  'pt': {
    'en': 'Portuguese',
    'it': 'Portoghese',
    'es': 'Portugués',
    'fr': 'Portugais'
  },
  'ro': {'en': 'Romanian', 'it': 'Rumeno', 'es': 'Rumano', 'fr': 'Roumain'},
  'ru': {'en': 'Russian', 'it': 'Russo', 'es': 'Ruso', 'fr': 'Russe'},
  'sk': {'en': 'Slovak', 'it': 'Slovacco', 'es': 'Eslovaco', 'fr': 'Slovaque'},
  'sl': {'en': 'Slovenian', 'it': 'Sloveno', 'es': 'Esloveno', 'fr': 'Slovène'},
  'sq': {'en': 'Albanian', 'it': 'Albanese', 'es': 'Albanés', 'fr': 'Albanais'},
  'sr': {'en': 'Serbian', 'it': 'Serbo', 'es': 'Serbio', 'fr': 'Serbe'},
  'sv': {'en': 'Swedish', 'it': 'Svedese', 'es': 'Sueco', 'fr': 'Suédois'},
  'sw': {'en': 'Swahili', 'it': 'Swahili', 'es': 'Suajili', 'fr': 'Swahili'},
  'tr': {'en': 'Turkish', 'it': 'Turco', 'es': 'Turco', 'fr': 'Turc'},
  'uk': {
    'en': 'Ukrainian',
    'it': 'Ucraino',
    'es': 'Ucraniano',
    'fr': 'Ukrainien'
  },
  'ur': {'en': 'Urdu', 'it': 'Urdu', 'es': 'Urdu', 'fr': 'Ourdou'},
  'vi': {
    'en': 'Vietnamese',
    'it': 'Vietnamita',
    'es': 'Vietnamita',
    'fr': 'Vietnamien'
  },
  'zh': {'en': 'Chinese', 'it': 'Cinese', 'es': 'Chino', 'fr': 'Chinois'},
};

/// Name of language [code] in GUI language [guiLang], falling back to English
/// and then to the code itself.
String languageName(String code, String guiLang) {
  final names = languageNames[code];
  if (names == null) return code;
  return names[guiLang] ?? names['en'] ?? code;
}

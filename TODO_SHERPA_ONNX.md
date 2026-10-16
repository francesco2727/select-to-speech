# TODO: Miglioramenti Futuri con Sherpa-ONNX

Questo documento tiene traccia delle opportunità di evoluzione e ottimizzazione per **Select-to-Speech** rese possibili dall'adozione del motore offline **Sherpa-ONNX**.

---

## 🎯 Priorità Alta (Esperienza Utente e Latenza)

- [x] **1. Streaming Nativo tramite Callback C++ di Generazione**
  - **Obiettivo**: Rimpiazzare lo splitting euristico in chunk di testo (max 80 caratteri via regex) con il callback nativo di Sherpa-ONNX `callback(samples: np.ndarray, progress: float) -> int`.
  - **Attività**:
    - [x] Aggiornare `synthesize_stream` in `src/select_to_speech/tts_engine.py` per invocare `self.tts.generate(full_text, config=gen_config, callback=progress_callback)`.
    - [x] Convertire e accodare i campioni audio parziali float32 direttamente nella coda del player audio.
    - [x] Interrompere istantaneamente l'inferenza nativa C++ quando `stop_event.is_set()` restituendo 0 nel callback (`return 0`).
    - [x] Verificare il mantenimento della prosodia naturale e dell'intonazione su intere frasi e paragrafi.

- [x] **2. Configurazione Hardware e Threading (CPU / OpenVINO / CUDA)**
  - **Obiettivo**: Permettere all'utente di ottimizzare il numero di thread di calcolo e sfruttare l'accelerazione hardware disponibile con auto-detect intelligente.
  - **Attività**:
    - [x] Aggiungere `num_threads` e `provider` nel modello di configurazione `VoiceConfig` (`src/select_to_speech/config.py`).
    - [x] Configurare `OfflineTtsModelConfig(num_threads=..., provider=...)` in `src/select_to_speech/tts_engine.py` con fallback ad auto-detect dei core ottimali.
    - [x] Esportare l'opzione nell'endpoint FastAPI (`/config` e nuovo `/hardware`).
    - [x] Aggiungere il selettore del numero di thread e la visualizzazione della CPU rilevata nella UI Flutter (`src/ui/lib/main.dart`).

---

## 🚀 Priorità Media (Flessibilità e Modelli Alternativi)

- [ ] **3. Supporto a Modelli Alternativi Ultra-Leggeri (VITS / Piper TTS)**
  - **Obiettivo**: Offrire opzioni ad alte prestazioni e ridotto consumo di risorse per macchine datate o architetture a basso consumo (es. Raspberry Pi, laptop con CPU serie U).
  - **Attività**:
    - [ ] Introdurre `OfflineTtsVitsModelConfig` in `src/select_to_speech/tts_engine.py`.
    - [ ] Aggiungere il download e la gestione dei modelli Piper VITS (file ONNX + tokens + config) in `src/select_to_speech/voice_manager.py`.
    - [ ] Consentire la selezione tra modelli Kokoro (alta qualità/espressività) e Piper VITS (ultra-veloci, 30–50MB) sia da configurazione che dalla GUI Flutter.

- [x] **4. Punteggiatura e Normalizzazione Automatica Testo (`OfflinePunctuation` & Euristica)**
  - **Obiettivo**: Migliorare la qualità di lettura per testi non formattati (es. estratti tramite OCR, screenshot, terminali o PDF a colonne) che mancano di punteggiatura corretta o hanno parole spezzate da a capo.
  - **Attività**:
    - [x] Implementato modulo `src/select_to_speech/text_normalizer.py` con rimozione sillabazione (`de-hyphenation`), ricomposizione righe spezzate (`unwrap`) e formattazione pause su elenchi puntati (`•`, `*`, `1.`).
    - [x] Implementato `NeuralPunctuationEngine` in `src/select_to_speech/punctuation_engine.py` basato su `sherpa-onnx.OfflinePunctuation` (modello CT-Transformer INT8, lingue EN e ZH).
    - [x] Integrati toggle e controlli di stato download nella scheda **General** della GUI Flutter con chiara indicazione del modello (`CT-Transformer INT8`) e delle lingue supportate (`en`, `zh`).

---

## 🔮 Priorità Bassa / Estensioni Future

- [ ] **5. Denoising e Pulizia Audio (`OfflineSpeechDenoiser`)**
  - **Obiettivo**: Preparare il terreno per future funzionalità di Speech-to-Text (riconoscimento vocale / dettatura) integrando modelli di rimozione del rumore (es. GTCRN / DPDFNet) già inclusi in Sherpa-ONNX.

# WBS-27-extra — Tombol Mic (Speech-to-Text / Audio Transcription)

- **Target:** `src/config.py`, `src/contracts.py`, `src/providers.py`, `src/api.py`, `app2.py`, `tests/self_test_cache_providers.py`, `tests/self_test_api_docker.py`.
- **Owner:** Agent AI.
- **Dependency:** WBS-26-extra.
- **Status:** DONE

## Batasan Scope & Guardrail Penilaian (Wajib Dipatuhi Agent)

- **Boleh diedit:** `src/config.py`, `src/contracts.py`, `src/providers.py`, `src/api.py`, `app2.py`, `tests/self_test_cache_providers.py`, `tests/self_test_api_docker.py`.
- **DILARANG KERAS diedit:** `requirements.txt`, `Dockerfile`, `app.py`, `tests/test_*.py`.
- **PENTING (Tanpa Library Baru):**
  - Jangan menambahkan `python-multipart`, `pyaudio`, atau `streamlit-webrtc` ke `requirements.txt` agar Docker build grader tidak terganggu.
  - Gunakan pengiriman JSON Base64 (`AudioTranscribeRequest(audio_base64: str, filename: str, language: str)`) dari `app2.py` ke `POST /api/v1/audio/transcribe`. Dengan JSON Base64, FastAPI dapat langsung memvalidasi payload lewat Pydantic `BaseModel` tanpa memerlukan `python-multipart`!
  - Di sisi UI `app2.py`, gunakan widget resmi bawaan Streamlit (`st.audio_input`, sudah tersedia di `streamlit>=1.42` yang ada di `requirements.txt`).
- **Privasi & Keamanan:** Rekaman suara hanya diproses di memori (`io.BytesIO`), **dilarang disimpan ke disk atau database**, dan teks hasil transkripsi disaring dengan `redact()` sebelum dikembalikan untuk pratinjau log.

---

## Pekerjaan

### Task 1: Tambahkan Konfigurasi `stt_model` di `src/config.py` dan Kontrak di `src/contracts.py`

1. Di `src/config.py` pada class `Settings` (sekitar baris 21), tambahkan field opsional dengan default `"whisper-1"` (tanpa mengubah logika `live_model_ready` agar seluruh test di `tests/self_test_contracts_config.py` tetap lulus):
   ```python
   stt_model: str = "whisper-1"
   ```
2. Di `src/contracts.py`, tambahkan kontrak request dan response untuk Speech-to-Text:
   ```python
   class AudioTranscribeRequest(BaseModel):
       audio_base64: str = Field(min_length=16, max_length=7_000_000)
       filename: str = Field(default="recording.wav", max_length=100)
       language: str = Field(default="id", min_length=2, max_length=10)


   class AudioTranscribeResponse(BaseModel):
       text: str
       language: str = "id"
       duration_ms: int = Field(default=0, ge=0)
   ```

### Task 2: Tambahkan Method `transcribe` pada `ModelProvider`, `OpenAIProvider`, dan `DeterministicProvider` di `src/providers.py`

1. Impor `io` di bagian atas `src/providers.py`.
2. Tambahkan signature ke `class ModelProvider(Protocol)`:
   ```python
   def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str: ...
   ```
3. Pada `OpenAIProvider.__init__`:
   ```python
   self.stt_model = kwargs.pop("stt_model", "whisper-1")
   ```
4. Tambahkan method `transcribe` pada `OpenAIProvider`:
   ```python
    def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str:
        if not audio_bytes:
            raise ValueError("audio payload must not be empty")
        buffer = io.BytesIO(audio_bytes)
        buffer.name = filename or "recording.wav"
        response = self._call(
            self.client.audio.transcriptions.create,
            model=self.stt_model,
            file=buffer,
            language=language,
        )
        text = getattr(response, "text", "") if not isinstance(response, str) else response
        return str(text).strip()
   ```
5. Tambahkan method `transcribe` pada `DeterministicProvider` untuk pengujian deterministik tanpa internet:
   ```python
    def transcribe(self, audio_bytes: bytes, filename: str = "recording.wav", language: str = "id") -> str:
        if not audio_bytes:
            raise ValueError("audio payload must not be empty")
        # Jika test mengirim teks UTF-8 diawali 'PROMPT:', kembalikan teks tersebut untuk simulasi
        try:
            decoded = audio_bytes.decode("utf-8")
            if decoded.startswith("PROMPT:"):
                return decoded[7:].strip()
        except UnicodeDecodeError:
            pass
        return "Berapa sisa saldo cuti tahunan saya?"
   ```

### Task 3: Tambahkan Endpoint `POST /api/v1/audio/transcribe` di `src/api.py`

1. Impor `base64`, `binascii`, dan `time` di `src/api.py`, serta impor `AudioTranscribeRequest, AudioTranscribeResponse` dari `.contracts`.
2. Di `build_runtime(settings: Settings)` (`src/api.py`), teruskan `stt_model=settings.stt_model` ke `OpenAIProvider(...)`.
3. Di dalam `create_app`, tambahkan endpoint:

```python
    @app.post("/api/v1/audio/transcribe", response_model=AudioTranscribeResponse)
    def transcribe_audio(
        payload: AudioTranscribeRequest,
        auth: AuthContext = Depends(current_auth),
    ) -> AudioTranscribeResponse:
        started = time.monotonic()
        try:
            raw_b64 = payload.audio_base64.split(",")[-1].strip()
            audio_bytes = base64.b64decode(raw_b64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status_code=422, detail="Invalid base64 audio payload")

        if len(audio_bytes) < 4 or len(audio_bytes) > 5 * 1024 * 1024:
            raise HTTPException(status_code=422, detail="Audio size must be between 4 bytes and 5 MB")

        try:
            transcript = agent.provider.transcribe(
                audio_bytes=audio_bytes,
                filename=payload.filename,
                language=payload.language,
            )
        except Exception:
            raise HTTPException(status_code=502, detail="Speech-to-text transcription unavailable")

        if not transcript:
            raise HTTPException(status_code=422, detail="No speech detected in audio")

        return AudioTranscribeResponse(
            text=transcript,
            language=payload.language,
            duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        )
```

### Task 4: Tambahkan Tombol Mic (`st.audio_input`) di `app2.py`

Di `app2.py` pada bagian `TAB 1: Conversational Chat` (sekitar baris 887, tepat sebelum `user_input = st.chat_input(...)`):
1. Impor `base64` dan `hashlib` di bagian atas `app2.py`.
2. Buat popover atau expander kompak **`🎙️ Input Suara (Speech-to-Text)`** menggunakan `st.audio_input`:

```python
    with st.popover("🎙️ Bicara via Mikrofon (Voice Input)"):
        st.caption("Rekam pertanyaan Anda dalam Bahasa Indonesia. Rekaman diproses langsung di memori dan tidak disimpan.")
        audio_val = st.audio_input("Klik ikon mikrofon untuk mulai/berhenti merekam:", key="voice_chat_input")
        if audio_val is not None:
            raw_bytes = audio_val.getvalue()
            audio_hash = hashlib.sha256(raw_bytes).hexdigest()[:16]
            if st.session_state.get("last_transcribed_hash") != audio_hash:
                with st.spinner("Menerjemahkan suara ke teks..."):
                    b64_str = base64.b64encode(raw_bytes).decode("ascii")
                    stt_res = api_request(
                        "POST",
                        "/api/v1/audio/transcribe",
                        token,
                        json={
                            "audio_base64": b64_str,
                            "filename": "voice_query.wav",
                            "language": "id",
                        },
                    )
                if stt_res and stt_res.get("text"):
                    st.session_state["last_transcribed_hash"] = audio_hash
                    st.session_state["prompt_input"] = stt_res["text"]
                    st.success(f"🗣️ Terdeteksi: \"{stt_res['text']}\"")
                    st.rerun()
```

Dengan mekanisme `last_transcribed_hash` dan `st.session_state["prompt_input"]`, begitu pengguna selesai merekam suara, hasil transkripsi langsung dikirim sebagai pesan chat ke asisten Miyo satu kali tanpa looping berulang!

### Task 5: Tambahkan Unit Test di `tests/self_test_cache_providers.py` dan `tests/self_test_api_docker.py`

1. Di `tests/self_test_cache_providers.py`, tambahkan `test_provider_transcribe_deterministic_and_openai()`:
   - Menguji `DeterministicProvider().transcribe(b"RIFF....WAVE")` mengembalikan `"Berapa sisa saldo cuti tahunan saya?"`.
   - Menguji `DeterministicProvider().transcribe(b"PROMPT:Siapkan cuti besok")` mengembalikan `"Siapkan cuti besok"`.
   - Menguji `OpenAIProvider` dengan mock client (`mock_client.audio.transcriptions.create`) memanggil model `whisper-1` dan mengembalikan teks hasil transkripsi.
2. Di `tests/self_test_api_docker.py`, tambahkan `test_api_audio_transcribe_endpoint(api_client: TestClient)`:
   - Tanpa token → `401`.
   - Base64 rusak → `422`.
   - Payload base64 valid (`base64.b64encode(b"PROMPT:Berapa jatah cuti tahunan?").decode()`) dengan `AUTH_ALYA` → `200` dengan `res.json()["text"] == "Berapa jatah cuti tahunan?"`.

---

## Langkah Verifikasi

```bash
pytest tests/self_test_cache_providers.py tests/self_test_api_docker.py -v
pytest -m "not live"
```

## Acceptance Criteria

- [x] Tidak ada dependency baru yang ditambahkan ke `requirements.txt`.
- [x] Endpoint `POST /api/v1/audio/transcribe` dilindungi autentikasi Bearer token, memvalidasi Base64 serta batas ukuran (≤ 5 MB), dan tidak menyimpan file audio ke disk.
- [x] `OpenAIProvider.transcribe` dan `DeterministicProvider.transcribe` berfungsi sesuai kontrak.
- [x] `app2.py` menyediakan tombol mikrofon berbasis `st.audio_input` yang langsung mengubah rekaman suara menjadi pesan chat.
- [x] Seluruh test non-live (`pytest -m "not live"`) lulus 100%.

## Bukti Hasil Verifikasi
- `pytest tests/self_test_cache_providers.py tests/self_test_api_docker.py -v`: 19 passed, 1 skipped (Postgres integration).
- `pytest -m "not live"`: 38 passed, 2 skipped, 1 deselected.
- `pytest tests/self_test_*.py`: 62 passed, 1 skipped.

from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    admin_password: str = ""
    database_url: str = "sqlite:///./data/assistant.db"
    # Çalışma zamanında üretilen dosyaların kökü. Testler bunu geçici klasöre yönlendirir.
    data_dir: Path = Path("data")
    # Açıkken uygulama yalnızca örnek veriyle çalışır; işletim verisine erişmez.
    demo_mode: bool = False
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_gpu_layers: int = 8
    freya_path: str = "vendor/FreyaTTS"
    tts_device: str = "cuda"
    stt_model: str = "large-v3-turbo"
    stt_device: str = "cuda"
    stt_compute_type: str = "float16"
    audiosocket_host: str = "127.0.0.1"
    audiosocket_port: int = 9092
    pbx_allowed_ips: list[str] = ["127.0.0.1", "::1"]
    record_audio: bool = False
    retention_days: int = 7
    ami_host: str = "127.0.0.1"
    ami_port: int = 5038
    ami_username: str = "freya"
    ami_secret: str = ""
    ami_channel_prefix: str = "PJSIP"
    ami_trunk: str = "trunk"
    ami_context: str = "automotive-outbound"
    ami_exten: str = "9092"
    ami_callerid: str = "Maslak Ekspertiz <02129998877>"
    operator_extension: str = "6002"
    operator_context: str = "automotive-transfer"
    operator_whisper_timeout_sec: int = 15
    branch_name: str = "Maslak Ekspertiz Merkezi"
    branch_address: str = "Maslak Mah. Atatürk Oto Sanayi Sitesi 2. Kısım No:12 Sarıyer/İstanbul"
    branch_latitude: float = 41.1118
    branch_longitude: float = 29.0225
    branch_maps_url: str = "https://maps.google.com/?q=41.1118,29.0225"
    whatsapp_webhook_token: str = ""
    # Ses arşivi HMAC mühür anahtarı; boşsa arşiv oluşturma ve doğrulama reddedilir.
    audio_archive_master_key: str = ""
    # İmzalı müşteri bağlantıları (rapor PDF) için HMAC anahtarı; boşsa imzalı erişim kapalıdır.
    link_signing_key: str = ""
    car_denoiser_enabled: bool = True
    car_denoiser_hpf_cutoff: float = 120.0
    car_denoiser_suppression_db: float = 18.0
    car_denoiser_target_dbfs: float = -16.0
    car_denoiser_noise_gate_dbfs: float = -42.0
    car_denoiser_max_boost_db: float = 12.0
    max_concurrent_calls: int = 50
    batched_ode_enabled: bool = True
    batched_ode_batch_size: int = 8
    batched_ode_micro_window_ms: float = 12.0
    batched_ode_steps: int = 32
    batched_ode_default_seed: int = 9
    chan_websocket_host: str = "127.0.0.1"
    chan_websocket_port: int = 8088
    chan_websocket_enabled: bool = True
    morph_precheck_enabled: bool = True
    morph_precheck_pause_ms: int = 35

    @model_validator(mode="after")
    def _isolate_demo_data(self):
        if self.demo_mode:
            self.data_dir = Path("data/demo")
            self.database_url = "sqlite:///./data/demo/assistant.db"
        return self


settings = Settings()

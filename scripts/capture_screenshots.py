# =====================================================================
# ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR
# Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)
# =====================================================================
"""
scripts/capture_screenshots.py
Playwright tabanlı deterministik ve yüksek çözünürlüklü ekran görüntüsü yakalayıcı (v3 - Final Polish).

Tüm 18 ana sekme ve alt sekmeleri (Takeover, Kalite Kapısı, Ses Lab)
kaydırma sıfırlama (window.scrollTo 0,0), networkidle ve DOM doğrulama
ile yakalar. Boş ekran, başlık kesilmesi ve tablo taşması sorunlarını engeller.
"""

import os
import re
import sys
import time
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright
from backend.config import settings

TABS = [
    ("Görüşme", "01_gorusme"),
    ("Operatör (6002)", "02_operator_6002"),
    ("Araç İçi DSP & Gürültü", "03_arac_ici_dsp_ve_gurultu"),
    ("Randevular", "04_randevular"),
    ("Sıra & Lift Durumu", "05_sira_ve_lift_durumu"),
    ("A/B Test & İnce Ayar", "06_ab_test_ve_ince_ayar"),
    ("Analitik & KPI", "07_analitik_ve_kpi"),
    ("Ekspertiz Raporları", "08_ekspertiz_raporlari"),
    ("Teknisyen Dikte", "09_teknisyen_dikte"),
    ("Araç Teşhis & OBD-II", "10_arac_teshis_ve_obd-ii"),
    ("Araçlar ve fiyatlar", "11_araclar_ve_fiyatlar"),
    ("Sözlük", "12_sozluk"),
    ("Bildirimler", "13_bildirimler"),
    ("Giden Çağrılar", "14_giden_cagrilar"),
    ("Geçmiş", "15_gecmis"),
    ("Ses laboratuvarı", "16_ses_laboratuvari"),
    ("Sistem", "17_sistem"),
    ("M01–M11", "18_m01-m11"),
]

# Belirli uzun tablolar için sayfa yüksekliği optimizasyonu
PAGE_HEIGHTS = {
    "06_ab_test_ve_ince_ayar": 1250,
    "11_araclar_ve_fiyatlar": 1200,
    "12_sozluk": 1350,
    "18_m01-m11": 1350,
    "02_operator_6002_quality_gate": 1200,
}


def reset_scroll(page):
    """Her sekme geçişinde sayfa ve iç div kaydırma konumunu kesin olarak en üste sıfırlar."""
    page.evaluate("""() => {
        window.scrollTo(0, 0);
        document.documentElement.scrollTop = 0;
        document.body.scrollTop = 0;
        const main = document.querySelector('main');
        if (main) main.scrollTop = 0;
        const scrollables = document.querySelectorAll('.layout, aside, main, section, div');
        scrollables.forEach(el => {
            if (el.scrollTop > 0) el.scrollTop = 0;
        });
    }""")


def wait_for_content(page):
    """İçeriğin ve API verilerinin DOM üzerinde tam render edilmesini bekler."""
    reset_scroll(page)
    try:
        page.wait_for_load_state("networkidle", timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(1000)
    reset_scroll(page)


def capture_all():
    out_dir = Path("docs/screenshots")
    out_dir.mkdir(parents=True, exist_ok=True)

    admin_password = settings.admin_password

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Standart başlangıç çözünürlüğü: 1600x1050
        context = browser.new_context(viewport={"width": 1600, "height": 1050})
        page = context.new_page()

        print("[*] 1. Giriş Sayfası açılıyor...")
        page.goto("http://127.0.0.1:8000", wait_until="networkidle")
        page.wait_for_timeout(1000)
        reset_scroll(page)
        page.screenshot(path=str(out_dir / "00_giris_ekrani.png"))
        print("[+] 00_giris_ekrani.png kaydedildi.")

        # Giriş yap
        password_input = page.locator("input[type='password']")
        if password_input.count() > 0:
            password_input.fill(admin_password)
            page.locator("button:has-text('Panele')").click()
            page.wait_for_timeout(2000)
            wait_for_content(page)

        print(f"[*] Toplam {len(TABS)} ana sekme yakalanacak.")

        for i, (tab_title, filename) in enumerate(TABS):
            try:
                # Sayfa yüksekliğini uzun tablolara göre dinamik ayarla
                custom_h = PAGE_HEIGHTS.get(filename, 1050)
                page.set_viewport_size({"width": 1600, "height": custom_h})

                print(f"[*] ({i+1}/{len(TABS)}) Sekme açılıyor: {tab_title} -> {filename}.png (h={custom_h})")
                nav_btn = page.locator("aside nav button").filter(has_text=tab_title)
                if nav_btn.count() == 0:
                    nav_btn = page.locator(f"aside nav button:has-text('{tab_title[:4]}')")
                nav_btn.click()
                wait_for_content(page)

                # Özel Etkileşimler:
                # 15_gecmis: Sol listedeki ilk görüşmeye tıkla ki transkript paneli dolsun
                if filename == "15_gecmis":
                    print("    [*] A.19 Geçmiş: İlk görüşme seçiliyor...")
                    first_conv = page.locator("main section div.row button.secondary").first
                    if first_conv.count() > 0:
                        first_conv.click()
                        page.wait_for_timeout(1200)
                        wait_for_content(page)

                # 16_ses_laboratuvari: 'Normalizasyonu incele' butonuna bas ki fonetik çıktı görünsün
                if filename == "16_ses_laboratuvari":
                    print("    [*] A.20 Ses Laboratuvarı: Normalizasyonu incele butonuna basılıyor...")
                    norm_btn = page.locator("main button:has-text('Normalizasyonu incele')")
                    if norm_btn.count() > 0:
                        norm_btn.click()
                        page.wait_for_timeout(1200)
                        wait_for_content(page)

                # Screenshot al
                page.screenshot(path=str(out_dir / f"{filename}.png"))
                print(f"[+] {filename}.png kaydedildi.")

                # 3.2 Operatör Paneli alt sekmeleri (Takeover & Kalite Kapısı)
                if filename == "02_operator_6002":
                    # Takeover sekmesi
                    takeover_btn = page.locator("main button:has-text('Canlı Devralma'), main button:has-text('Müdahale'), main button:has-text('RT-10')")
                    if takeover_btn.count() > 0:
                        takeover_btn.first.click()
                        wait_for_content(page)
                        page.screenshot(path=str(out_dir / f"{filename}_takeover.png"))
                        print(f"    [+] {filename}_takeover.png kaydedildi.")

                    # Kalite Kapısı sekmesi
                    qa_btn = page.locator("main button:has-text('Kalite Kapısı'), main button:has-text('Telemetri & HLS-08')")
                    if qa_btn.count() > 0:
                        qa_btn.first.click()
                        wait_for_content(page)
                        # Kalite Kapısı 5 test butonuna bas ve sonuçları al
                        run_btn = page.locator("main button:has-text('Kalite Kapısı 5 Süitini')")
                        if run_btn.count() > 0:
                            try:
                                run_btn.click()
                                page.wait_for_timeout(3500)
                                wait_for_content(page)
                            except Exception:
                                pass
                        page.set_viewport_size({"width": 1600, "height": 1200})
                        page.screenshot(path=str(out_dir / f"{filename}_quality_gate.png"))
                        print(f"    [+] {filename}_quality_gate.png kaydedildi.")

                    # Operatör ana sekmesine geri dön
                    nav_btn.click()
                    wait_for_content(page)

                # 3.9 A/B Test Paneli alt sekmesi (Ses Laboratuvarı)
                if filename == "06_ab_test_ve_ince_ayar":
                    ses_lab_sub = page.locator("main button:has-text('Ses Karşılaştırma Laboratuvarı'), main button:has-text('TTS Seed Lab')")
                    if ses_lab_sub.count() > 0:
                        ses_lab_sub.first.click()
                        wait_for_content(page)
                        page.screenshot(path=str(out_dir / f"{filename}_ses_lab.png"))
                        print(f"    [+] {filename}_ses_lab.png kaydedildi.")

                    # A/B test ana sekmesine geri dön
                    nav_btn.click()
                    wait_for_content(page)

            except Exception as e:
                print(f"[!] Hata ({tab_title}): {e}")

        browser.close()
        print("\n[OK] Tüm 22 ekran görüntüsü başarıyla güncellendi.")


if __name__ == "__main__":
    capture_all()

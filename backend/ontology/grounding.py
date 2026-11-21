"""
FreyaTTS Automotive Cockpit — Automotive Grounding & Semantic Knowledge Layer
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR

NVIDIA Auto-Ontology "Ground" ve "Validate" prensipleri:
1. Paket ve fiyatlama için TEK GERÇEK KAYNAK (Single Source of Truth).
2. OBD-II ve arıza semantik eşlemesi.
3. Doğal dil araç normalizasyonu ve katalog eşleştirme.
4. Deterministik eylem ve iş kuralı doğrulayıcısı (Guardrail).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional
from backend.ontology.models import (
    DiagnosticFaultConcept,
    DiagnosticSeverity,
    OntologyValidationRequest,
    OntologyValidationResult,
    ServicePackageConcept,
    VehicleConcept,
)

# ============================================================================
# 1. TEK GERÇEK KAYNAK: Sertifikalı Ekspertiz Paketleri ve Fiyatları (Y7 Çözümü)
# ============================================================================

CERTIFIED_SERVICE_PACKAGES: Dict[str, ServicePackageConcept] = {
    "P01_TEMEL": ServicePackageConcept(
        package_id="P01_TEMEL",
        name="Temel Muayene",
        price_tl=950,
        duration_min=25,
        description="Kaporta boya kalınlık ölçümü, değişen parça tespiti ve şasi kontrolü.",
        included_checks=[
            "Mikron boya kalınlık testi (tüm paneller)",
            "Değişen/orijinal parça tespiti",
            "Şasi, podye, direk ve marşpiyel fiziksel kontrolü",
            "Cam ve emniyet kemeri üretim tarihi uyumu",
        ],
        recommended_for=["Hızlı kaporta kontrolü", "Küçük hasar sorgusu"],
    ),
    "P02_STANDART": ServicePackageConcept(
        package_id="P02_STANDART",
        name="Standart Ekspertiz",
        price_tl=1450,
        duration_min=40,
        description="Kaporta boya kontrolüne ek olarak lift üzerinde alt takım ve mekanik muayene.",
        included_checks=[
            "Tüm Temel Muayene kontrolleri",
            "Lift üstü alt takım, salıncak, rot ve amortisör muayenesi",
            "Motor yağı, şanzıman ve diferansiyel kaçak incelemesi",
            "Egzoz sistemi ve katalizör görsel kontrolü",
            "Fren balata ve disk kalınlık ölçümü",
        ],
        recommended_for=["Rutin ikinci el araç alımı", "Mekanik durum tespiti"],
    ),
    "P03_FULL": ServicePackageConcept(
        package_id="P03_FULL",
        name="Tam Kapsamlı Ekspertiz",
        price_tl=1950,
        duration_min=60,
        description="Elektronik OBD-II beyin taraması, Dyno motor güç testi ve fren testi.",
        included_checks=[
            "Tüm Standart Ekspertiz kontrolleri",
            "OBD-II soketinden tüm beyin (ECU/TCU/ABS/Airbag) arıza taraması",
            "Dinamometre (Dyno) tekerlek gücü ve tork ölçümü",
            "Elektronik fren test cihazı ile sapma ve tutuş yüzdesi",
            "Süspansiyon test platformu ölçümü",
            "Akü sağlık testi (CCA ve voltaj)",
        ],
        recommended_for=["Kapsamlı alım öncesi ekspertiz", "Arıza lambası yanan araçlar"],
    ),
    "P04_VIP": ServicePackageConcept(
        package_id="P04_VIP",
        name="VIP Ekspertiz + Yol Testi",
        price_tl=2600,
        duration_min=80,
        description="Tam kapsamlı ekspertize ek olarak uzman teknisyenle dinamik yol testi ve airbag kontrolü.",
        included_checks=[
            "Tüm Tam Kapsamlı Ekspertiz kontrolleri",
            "Dinamik sürüş ve yol testi (şanzıman geçişleri, turbo, uğultu)",
            "Emniyet kemeri direnç ve airbag tüp fiziksel kontrolü",
            "Detaylı 12 sayfa ıslak imzalı/QR kodlu dijital teslim raporu",
            "Usta başı ile 15 dakika birebir teknik brifing",
        ],
        recommended_for=["Lüks ve premium segment araçlar", "Şüpheli geçmişi olan araçlar"],
    ),
}

# ============================================================================
# 2. Sertifikalı Otomotiv Teşhis ve OBD-II Arıza Ontolojisi
# ============================================================================

CERTIFIED_DIAGNOSTIC_FAULTS: Dict[str, DiagnosticFaultConcept] = {
    "P0300": DiagnosticFaultConcept(
        obd_code="P0300",
        system="Ateşleme & Yakıt",
        warning_light="Sarı Motor Arıza Lambası (Check Engine / Yanıp Sönen)",
        severity=DiagnosticSeverity.HIGH,
        description="Rastgele veya çoklu silindirde ateşleme kesintisi (misfire).",
        common_symptoms=["Rölantide sarsıntı", "Titreşimli çalışma", "Çekiş düşüklüğü", "Egzozda çiğ yakıt kokusu"],
        suggested_action="Buji, ateşleme bobini ve enjektörler incelenmelidir. Dyno testi öncesi kompresyon bakılmalıdır.",
        recommended_package_id="P03_FULL",
    ),
    "P0171": DiagnosticFaultConcept(
        obd_code="P0171",
        system="Hava & Yakıt Karışımı",
        warning_light="Sarı Motor Lambası (Sabit)",
        severity=DiagnosticSeverity.MEDIUM,
        description="Sistem çok fakir (Bank 1) - Silindire giren hava yakıt oranına göre fazla.",
        common_symptoms=["Hızlanmada tekleme", "Rölantide dalgalanma", "Yakıt tüketiminde artış"],
        suggested_action="Vakum kaçağı, MAF/MAP sensörü ve yakıt basınç regülatörü test edilmelidir.",
        recommended_package_id="P03_FULL",
    ),
    "P0420": DiagnosticFaultConcept(
        obd_code="P0420",
        system="Egzoz & Emisyon",
        warning_light="Motor Lambası / Egzoz Emisyon Uyarısı",
        severity=DiagnosticSeverity.MEDIUM,
        description="Katalitik konvertör sistemi verimi eşik değerin altında (Bank 1).",
        common_symptoms=["Emisyon muayenesinden geçememe", "Egzoz gazında koku", "Üst devirlerde boğulma"],
        suggested_action="O2 (Lambda) sensör voltaj grafiği ve katalizör petek doluluğu incelenmelidir.",
        recommended_package_id="P02_STANDART",
    ),
    "C0035": DiagnosticFaultConcept(
        obd_code="C0035",
        system="Fren & Çekiş Kontrol",
        warning_light="Sarı ABS / ESP İkaz Lambası",
        severity=DiagnosticSeverity.HIGH,
        description="Sol ön tekerlek hız sensörü devresi açık veya hatalı sinyal veriyor.",
        common_symptoms=["ABS devre dışı", "ESP çalışmıyor uyarısı", "Fren pedalında titreşim"],
        suggested_action="Teker porya manyetik halkası ve ABS sensör kablo demeti kontrol edilmelidir.",
        recommended_package_id="P03_FULL",
    ),
    "B0001": DiagnosticFaultConcept(
        obd_code="B0001",
        system="Pasif Güvenlik (SRS)",
        warning_light="Kırmızı Airbag İkaz Lambası",
        severity=DiagnosticSeverity.CRITICAL,
        description="Sürücü hava yastığı 1. kademe ateşleme devresi direnç uyuşmazlığı.",
        common_symptoms=["Airbag lambası sürekli yanıyor", "Direksiyon tuşlarında temassızlık"],
        suggested_action="Direksiyon zembereği (spiral kablo) ve airbag fiş soketleri derhal incelenmelidir.",
        recommended_package_id="P04_VIP",
    ),
    "P0299": DiagnosticFaultConcept(
        obd_code="P0299",
        system="Aşırı Besleme (Turbo)",
        warning_light="Motor Lambası / DPF & Kızdırma Lambası Yanıp Sönüyor",
        severity=DiagnosticSeverity.HIGH,
        description="Turboşarj / süperşarj düşük şarj basıncı (Underboost).",
        common_symptoms=["Rampada çekişten düşme", "Islık sesi", "Geç hızlanma"],
        suggested_action="Intercooler hortumları, wastegate aktüatörü ve turbo mili kontrol edilmelidir.",
        recommended_package_id="P03_FULL",
    ),
    "P0562": DiagnosticFaultConcept(
        obd_code="P0562",
        system="Elektrik & Şarj",
        warning_light="Kırmızı Akü Şarj Lambası",
        severity=DiagnosticSeverity.MEDIUM,
        description="Sistem voltajı şarj anında 12.0V altına düşüyor.",
        common_symptoms=["Farlarda kısılma", "Sabah zor marş basma", "Start-Stop devre dışı"],
        suggested_action="Alternatör (şarj dinamosu) çıkış voltajı ve akü iç direnci test edilmelidir.",
        recommended_package_id="P02_STANDART",
    ),
    "U0100": DiagnosticFaultConcept(
        obd_code="U0100",
        system="CAN Ağ İletişimi",
        warning_light="Birden Fazla İkaz Lambası (Motor + ESP + Şanzıman)",
        severity=DiagnosticSeverity.CRITICAL,
        description="Motor kontrol modülü (ECM) ile CAN veri yolu bağlantısı koptu.",
        common_symptoms=["Marş basıyor ama çalışmıyor", "Gösterge panelinde çizgiler", "Vites kilitlenmesi"],
        suggested_action="CAN Bus hattı 60 Ohm hat sonlandırma direnci ve ana röle kontrol edilmelidir.",
        recommended_package_id="P04_VIP",
    ),
}

# ============================================================================
# 3. Sertifikalı Araç Referans Kataloğu (Katalog Ontolojisi)
# ============================================================================

CERTIFIED_VEHICLE_CATALOG: List[VehicleConcept] = [
    VehicleConcept(
        brand="Volkswagen",
        model="Golf",
        submodel="1.4 TSI / 1.5 eTSI",
        engine_type="Benzin / Hibrit",
        year_range="2013–2024",
        segment="C",
        normalized_name="Volkswagen Golf",
        aliases=["vw golf", "golf 7", "golf 8", "golf tsi", "golf tdi"],
    ),
    VehicleConcept(
        brand="Volkswagen",
        model="Passat",
        submodel="1.5 TSI / 2.0 TDI",
        engine_type="Benzin / Dizel",
        year_range="2015–2023",
        segment="D",
        normalized_name="Volkswagen Passat",
        aliases=["vw passat", "passat b8", "passat dizel", "passat tsi"],
    ),
    VehicleConcept(
        brand="Renault",
        model="Megane",
        submodel="1.3 TCe / 1.5 dCi",
        engine_type="Benzin / Dizel",
        year_range="2016–2024",
        segment="C",
        normalized_name="Renault Megane",
        aliases=["megane 4", "megan 4", "megane sedan", "megane dci"],
    ),
    VehicleConcept(
        brand="Renault",
        model="Clio",
        submodel="1.0 TCe / 1.5 dCi",
        engine_type="Benzin / Dizel",
        year_range="2019–2024",
        segment="B",
        normalized_name="Renault Clio",
        aliases=["clio 5", "yeni clio", "clio tce"],
    ),
    VehicleConcept(
        brand="Fiat",
        model="Egea",
        submodel="1.3 / 1.6 Multijet / 1.4 Fire",
        engine_type="Dizel / Benzin",
        year_range="2015–2024",
        segment="C",
        normalized_name="Fiat Egea",
        aliases=["egea sedan", "egea cross", "egea multijet", "fiat egea"],
    ),
    VehicleConcept(
        brand="Toyota",
        model="Corolla",
        submodel="1.8 Hybrid / 1.5 Dynamic Force",
        engine_type="Hibrit / Benzin",
        year_range="2019–2024",
        segment="C",
        normalized_name="Toyota Corolla",
        aliases=["corolla hybrid", "corolla hibrit", "yeni corolla"],
    ),
    VehicleConcept(
        brand="Ford",
        model="Focus",
        submodel="1.0 EcoBoost / 1.5 EcoBlue",
        engine_type="Benzin / Dizel",
        year_range="2018–2024",
        segment="C",
        normalized_name="Ford Focus",
        aliases=["focus 4", "yeni focus", "focus ecoboost"],
    ),
    VehicleConcept(
        brand="Honda",
        model="Civic",
        submodel="1.5 VTEC Turbo / 1.6 i-DTEC",
        engine_type="Benzin / Dizel",
        year_range="2016–2024",
        segment="C",
        normalized_name="Honda Civic",
        aliases=["civic fc5", "civic vtec", "honda civic"],
    ),
]


class AutomotiveGroundingEngine:
    """
    NVIDIA Auto-Ontology prensiplerine uygun semantik çözümleyici ve doğrulayıcı.
    """

    @classmethod
    def get_service_packages(cls) -> List[ServicePackageConcept]:
        return list(CERTIFIED_SERVICE_PACKAGES.values())

    @classmethod
    def get_package_by_id(cls, package_id: str) -> Optional[ServicePackageConcept]:
        return CERTIFIED_SERVICE_PACKAGES.get(package_id.upper())

    @classmethod
    def get_package_by_name(cls, query: str) -> Optional[ServicePackageConcept]:
        q = query.lower().strip()
        if "temel" in q or "kaporta" in q or "ucuz" in q:
            return CERTIFIED_SERVICE_PACKAGES["P01_TEMEL"]
        if "full" in q or "tam" in q or "kapsamlı" in q or "dyno" in q:
            return CERTIFIED_SERVICE_PACKAGES["P03_FULL"]
        if "vip" in q or "yol test" in q or "en iyi" in q or "lüks" in q:
            return CERTIFIED_SERVICE_PACKAGES["P04_VIP"]
        return CERTIFIED_SERVICE_PACKAGES["P02_STANDART"]

    @classmethod
    def resolve_vehicle(cls, user_text: str) -> Optional[VehicleConcept]:
        """
        Kullanıcının doğal dil ifadesini sertifikalı araç kataloğu ile eşler.
        Örnek: "passat 1.5 tsi 2020 model" -> Volkswagen Passat
        """
        lowered = user_text.lower().strip()
        for v in CERTIFIED_VEHICLE_CATALOG:
            # 1. Tam marka model eşleşmesi
            if v.brand.lower() in lowered and v.model.lower() in lowered:
                return v
            # 2. Takma ad (alias) eşleşmesi
            for alias in v.aliases:
                if alias in lowered:
                    return v
            # 3. Yalnızca model adı belirginse
            if re.search(rf"\b{re.escape(v.model.lower())}\b", lowered):
                return v
        return None

    @classmethod
    def diagnose_symptom(cls, symptom_or_code: str) -> List[DiagnosticFaultConcept]:
        """
        Arıza belirtisi veya OBD-II kodundan ontolojik eşleşmeleri getirir.
        """
        q = symptom_or_code.upper().strip()
        results: List[DiagnosticFaultConcept] = []

        # Doğrudan OBD kodu eşleşmesi
        if q in CERTIFIED_DIAGNOSTIC_FAULTS:
            return [CERTIFIED_DIAGNOSTIC_FAULTS[q]]

        lowered = symptom_or_code.lower()
        terms = [t for t in re.split(r"\s+", lowered) if len(t) >= 3 and t not in ("lambası", "ikaz", "isigi", "ışığı")]

        for fault in CERTIFIED_DIAGNOSTIC_FAULTS.values():
            if fault.obd_code.lower() in lowered:
                results.append(fault)
                continue
            if any(term in fault.warning_light.lower() for term in terms):
                results.append(fault)
                continue
            if any(term in s.lower() for s in fault.common_symptoms for term in terms):
                results.append(fault)
                continue
            if any(term in fault.description.lower() for term in terms):
                results.append(fault)
                continue

        return results

    @classmethod
    def validate_action(cls, req: OntologyValidationRequest) -> OntologyValidationResult:
        """
        AI ajanının veya Supervisor'ın planladığı eylemi ontoloji kurallarıyla doğrular.
        """
        action = req.action_type
        payload = dict(req.payload)
        errors: List[str] = []
        warnings: List[str] = []
        certified: Dict = {}

        if action in ("create_booking", "booking_create"):
            # Kural 1: Müşteri adı boş olamaz
            name = str(payload.get("customer_name") or "").strip()
            if not name or len(name) < 2:
                errors.append("Müşteri adı en az 2 karakter olmalıdır.")
            else:
                certified["customer_name"] = name

            # Kural 2: Telefon doğrulaması (en az 10 hane)
            phone = re.sub(r"\D", "", str(payload.get("customer_phone") or ""))
            if len(phone) < 10:
                errors.append("Geçerli bir telefon numarası zorunludur (en az 10 hane).")
            else:
                certified["customer_phone"] = phone

            # Kural 3: Araç referansı ontolojiyle doğrulanmalı
            vehicle_text = str(payload.get("vehicle_text") or payload.get("vehicle_model") or "")
            resolved_vehicle = cls.resolve_vehicle(vehicle_text)
            if resolved_vehicle:
                certified["vehicle_model"] = resolved_vehicle.normalized_name
                certified["vehicle_segment"] = resolved_vehicle.segment
            else:
                warnings.append(f"Araç modeli '{vehicle_text}' standart katalogda bulunamadı; serbest metin olarak kaydedilecek.")
                certified["vehicle_model"] = vehicle_text

            # Kural 4: Paket fiyatı LLM tarafından uydurulamaz, tek kaynaktan çekilir
            pkg_id = payload.get("package_id")
            pkg_name = payload.get("package_name") or "Standart Ekspertiz"
            matched_pkg = cls.get_package_by_id(pkg_id) if pkg_id else cls.get_package_by_name(pkg_name)
            
            if matched_pkg:
                certified["package_id"] = matched_pkg.package_id
                certified["package_name"] = matched_pkg.name
                certified["price_tl"] = matched_pkg.price_tl
                certified["duration_min"] = matched_pkg.duration_min
            else:
                certified["package_id"] = "P02_STANDART"
                certified["price_tl"] = 1450
                certified["duration_min"] = 40

            # Kural 5: Slot teyidi
            slot_id = payload.get("slot_id") or payload.get("time_slot")
            if not slot_id:
                errors.append("Rezervasyon için müsait randevu saati (slot) belirtilmelidir.")
            else:
                certified["slot_id"] = slot_id

        elif action in ("reschedule_booking", "booking_reschedule"):
            # Kural: İki bilgili doğrulama (K2 hatasını önler)
            phone = payload.get("customer_phone")
            appointment_id = payload.get("appointment_id")
            new_slot_id = payload.get("new_slot_id")

            if not appointment_id and not phone:
                errors.append("Erteleme işlemi için mevcut randevu ID veya kayıtlı telefon numarası gereklidir.")
            if not new_slot_id:
                errors.append("Yeni randevu saati seçilmeden mevcut randevu iptal edilemez (Atomik Erteleme Kuralı).")

            certified.update(payload)

        elif action in ("quote_price", "service_price_estimate"):
            pkg_query = str(payload.get("package_name") or payload.get("query") or "standart")
            pkg = cls.get_package_by_name(pkg_query) or CERTIFIED_SERVICE_PACKAGES["P02_STANDART"]
            certified["package_id"] = pkg.package_id
            certified["package_name"] = pkg.name
            certified["price_tl"] = pkg.price_tl
            certified["duration_min"] = pkg.duration_min
            certified["formatted_response"] = f"{pkg.name} paketimiz {pkg.price_tl} TL olup yaklaşık {pkg.duration_min} dakika sürmektedir."

        else:
            certified = payload

        is_valid = len(errors) == 0
        return OntologyValidationResult(
            valid=is_valid,
            action_type=action,
            errors=errors,
            warnings=warnings,
            certified_payload=certified if is_valid else {},
        )

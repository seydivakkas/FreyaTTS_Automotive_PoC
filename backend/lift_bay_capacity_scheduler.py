"""
ÖZEL LİSANS — TÜM HAKLAR SAKLIDIR

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas)

Bu yazılım ve ilgili tüm dosyalar ("Yazılım") yalnızca görüntüleme ve eğitim
amaçlı olarak paylaşılmıştır.

YASAKLAR:
  1. Kopyalanamaz, çoğaltılamaz, dağıtılamaz veya yeniden yayınlanamaz.
  2. Ticari veya ticari olmayan hiçbir projede kullanılamaz, değiştirilemez.
  3. Alt lisanslanamaz, satılamaz veya devredilemez.
  4. Tersine mühendislik yapılamaz.

İZİN VERİLEN KULLANIM:
  - GitHub üzerinde görüntüleme ve okuma.
  - Kişisel öğrenim amacıyla kodu inceleme (kopyalamadan).

YAZARIN AÇIK YAZILI İZNİ OLMAKSIZIN HİÇBİR KULLANIM HAKKI TANINMAZ.
İzin talepleri için: GitHub @seydivakkas
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from backend.db import Appointment, BaySchedule, InspectionBay, Technician

IST_TZ = ZoneInfo("Europe/Istanbul")

# 1. Fiziksel İstasyon (Bay) Türleri ve Açıklamaları
BAY_TYPES: Dict[str, Dict[str, Any]] = {
    "bodywork_paint": {
        "key": "bodywork_paint",
        "name": "Kaporta & Boya Muayene Lifti",
        "description": "Boya mikron kalınlığı, şasi, podye, direk ve dış gövde kontrol istasyonu.",
        "default_capacity": 2,
    },
    "mechanic_underbody": {
        "key": "mechanic_underbody",
        "name": "Alt Mekanik & Süspansiyon Lifti",
        "description": "4 sütunlu / makaslı lift, alt takım, şanzıman, fren diski ve sıvı kaçak kontrolü.",
        "default_capacity": 2,
    },
    "dyno": {
        "key": "dyno",
        "name": "Dinamometre Motor Performans İstasyonu",
        "description": "4WD/2WD dyno tamburları, tekerlek beygir gücü, tork ve motor aktarma testi.",
        "default_capacity": 1,
    },
    "electronic_diagnostics": {
        "key": "electronic_diagnostics",
        "name": "OBD-II Elektronik Arıza & Beyin Test Alanı",
        "description": "OBD-II port taraması, ECU hata kodları, canlı sensör verileri ve akü testi.",
        "default_capacity": 1,
    },
}

# 2. Muayene Aşamaları (Inspection Stages)
STAGE_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "bodywork_paint": {
        "key": "bodywork_paint",
        "name": "Kaporta & Boya Mikron Ölçümü",
        "bay_type": "bodywork_paint",
        "required_specialty": "bodywork_paint",
    },
    "mechanic_underbody": {
        "key": "mechanic_underbody",
        "name": "Alt Mekanik & Fren/Süspansiyon Kontrolü",
        "bay_type": "mechanic_underbody",
        "required_specialty": "mechanic_underbody",
    },
    "dyno": {
        "key": "dyno",
        "name": "Dinamometre Motor Güç Testi",
        "bay_type": "dyno",
        "required_specialty": "dyno",
    },
    "electronic_diagnostics": {
        "key": "electronic_diagnostics",
        "name": "Elektronik OBD-II & Arıza Taraması",
        "bay_type": "electronic_diagnostics",
        "required_specialty": "electronic_diagnostics",
    },
}

# 3. Paket Bazlı Çok Aşamalı İş Akışı ve Süre Planı (Minutes)
PACKAGE_STAGE_ROUTING: Dict[str, List[Dict[str, Any]]] = {
    "motor_mekanik": [
        {"stage": "mechanic_underbody", "duration_minutes": 15},
        {"stage": "dyno", "duration_minutes": 15},
    ],
    "standart_ekspertiz": [
        {"stage": "bodywork_paint", "duration_minutes": 20},
        {"stage": "mechanic_underbody", "duration_minutes": 15},
        {"stage": "electronic_diagnostics", "duration_minutes": 10},
    ],
    "full_kapsamli": [
        {"stage": "bodywork_paint", "duration_minutes": 25},
        {"stage": "mechanic_underbody", "duration_minutes": 20},
        {"stage": "dyno", "duration_minutes": 15},
    ],
    "vip_premium": [
        {"stage": "bodywork_paint", "duration_minutes": 25},
        {"stage": "mechanic_underbody", "duration_minutes": 20},
        {"stage": "dyno", "duration_minutes": 15},
        {"stage": "electronic_diagnostics", "duration_minutes": 15},
    ],
}


@dataclass
class AllocatedStage:
    stage_index: int
    stage_key: str
    stage_name: str
    bay_type: str
    bay_id: str
    bay_name: str
    technician_id: Optional[str]
    technician_name: Optional[str]
    starts_at: str
    ends_at: str
    duration_minutes: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CapacityCheckResult:
    is_available: bool
    package_type: str
    total_duration_minutes: int
    requested_start_iso: str
    planned_end_iso: str
    allocated_stages: List[AllocatedStage] = field(default_factory=list)
    bottleneck_stage: Optional[str] = None
    bottleneck_bay_type: Optional[str] = None
    bottleneck_reason: Optional[str] = None
    next_available_start_iso: Optional[str] = None
    spoken_pitch: str = ""

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["allocated_stages"] = [s.to_dict() if hasattr(s, "to_dict") else s for s in self.allocated_stages]
        return data


def parse_iso_datetime(dt_str: str) -> datetime:
    """ISO formatındaki zaman damgasını UTC aware datetime nesnesine dönüştürür."""
    clean = dt_str.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(clean)
    except Exception:
        # Fallback now UTC
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_iso_datetime(dt: datetime) -> str:
    """Datetime nesnesini standart ISO 8601 stringe çevirir."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def seed_default_bays_and_technicians(db: Session) -> Dict[str, int]:
    """
    Şube başlangıç istasyonlarını ve uzman teknisyen kadrosunu oluşturur.
    """
    # 1. İstasyonlar
    existing_bays = db.scalars(select(InspectionBay)).all()
    bays_created = 0
    if not existing_bays:
        default_bays = [
            InspectionBay(
                name="Kaporta-Boya Lifti 1",
                bay_number=1,
                bay_type="bodywork_paint",
                status="idle",
                notes="Ana kaporta ve mikron muayene istasyonu",
            ),
            InspectionBay(
                name="Kaporta-Boya Lifti 2",
                bay_number=2,
                bay_type="bodywork_paint",
                status="idle",
                notes="İkinci kaporta boya ve şasi lifti",
            ),
            InspectionBay(
                name="Alt Mekanik Lifti 1",
                bay_number=3,
                bay_type="mechanic_underbody",
                status="idle",
                notes="4 Sütunlu ağır mekanik ve fren kontrol lifti",
            ),
            InspectionBay(
                name="Dinamometre 4WD/2WD Test İstasyonu",
                bay_number=4,
                bay_type="dyno",
                status="idle",
                notes="4 çeker ve 2 çeker senkron dyno istasyonu",
            ),
            InspectionBay(
                name="OBD Elektronik & Arıza Test İstasyonu",
                bay_number=5,
                bay_type="electronic_diagnostics",
                status="idle",
                notes="Elektronik teşhis, OBD soketi ve akü test alanı",
            ),
        ]
        for b in default_bays:
            db.add(b)
        bays_created = len(default_bays)

    # 2. Teknisyenler
    existing_techs = db.scalars(select(Technician)).all()
    techs_created = 0
    if not existing_techs:
        default_techs = [
            Technician(
                name="Murat Usta",
                title="Kıdemli Kaporta & Şasi Uzmanı",
                specialties_json=json.dumps(["bodywork_paint"]),
                is_active=True,
                daily_capacity=8,
                notes="Boya mikron, şasi podye ve değişen parça uzmanı",
            ),
            Technician(
                name="Ahmet Yılmaz",
                title="Mekanik & Alt Takım Uzmanı",
                specialties_json=json.dumps(["mechanic_underbody", "dyno"]),
                is_active=True,
                daily_capacity=8,
                notes="Motor, şanzıman ve yürüyen aksam teşhis uzmanı",
            ),
            Technician(
                name="Serkan Demir",
                title="Dyno Performans & Elektronik Uzmanı",
                specialties_json=json.dumps(["dyno", "electronic_diagnostics"]),
                is_active=True,
                daily_capacity=8,
                notes="Dyno operatör lisanslı, OBD-II ve ADAS kalibrasyon teknisyeni",
            ),
            Technician(
                name="Emre Kaya",
                title="Baş Teknisyen (Master Ekspertiz)",
                specialties_json=json.dumps([
                    "bodywork_paint",
                    "mechanic_underbody",
                    "dyno",
                    "electronic_diagnostics",
                    "master",
                ]),
                is_active=True,
                daily_capacity=10,
                notes="Tüm muayene istasyonlarında tam yetkili baş teknisyen",
            ),
        ]
        for t in default_techs:
            db.add(t)
        techs_created = len(default_techs)

    if bays_created > 0 or techs_created > 0:
        db.commit()

    return {"bays_created": bays_created, "techs_created": techs_created}


def _is_time_overlap(s1_iso: str, e1_iso: str, s2_iso: str, e2_iso: str) -> bool:
    """İki zaman aralığının çakışıp çakışmadığını denetler: [s1, e1] ve [s2, e2]."""
    return (s1_iso < e2_iso) and (e1_iso > s2_iso)


def find_free_bay_for_window(
    db: Session,
    *,
    bay_type: str,
    start_iso: str,
    end_iso: str,
    exclude_schedule_id: Optional[str] = None,
) -> Optional[InspectionBay]:
    """
    Belirtilen zaman aralığında [start_iso, end_iso] boşta olan ve bakımda olmayan
    ilgili türdeki istasyonu (bay) bulur.
    """
    candidate_bays = db.scalars(
        select(InspectionBay)
        .where(
            and_(
                InspectionBay.bay_type == bay_type,
                InspectionBay.status != "maintenance",
            )
        )
        .order_by(InspectionBay.bay_number.asc())
    ).all()

    for bay in candidate_bays:
        # Bu bay için o aralıkta aktif rezervasyon var mı?
        query = select(BaySchedule).where(
            and_(
                BaySchedule.bay_id == bay.id,
                BaySchedule.status.in_(["scheduled", "in_progress"]),
                func.julianday(BaySchedule.starts_at) < func.julianday(end_iso),
                func.julianday(BaySchedule.ends_at) > func.julianday(start_iso),
            )
        )
        if exclude_schedule_id:
            query = query.where(BaySchedule.id != exclude_schedule_id)

        overlapping = db.scalar(query)
        if not overlapping:
            return bay
    return None


def find_free_technician_for_window(
    db: Session,
    *,
    required_specialty: str,
    start_iso: str,
    end_iso: str,
    exclude_schedule_id: Optional[str] = None,
) -> Optional[Technician]:
    """
    Belirtilen uzmanlığa sahip ve o aralıkta başka bir istasyonda görevli olmayan teknisyeni bulur.
    """
    active_techs = db.scalars(
        select(Technician)
        .where(Technician.is_active.is_(True))
        .order_by(Technician.daily_capacity.desc())
    ).all()

    for tech in active_techs:
        try:
            specs = json.loads(tech.specialties_json)
        except Exception:
            specs = []

        # Uzmanlık kontrolü (veya master yetkisi)
        if required_specialty not in specs and "master" not in specs:
            continue

        # Bu teknisyenin o saatte çakışan randevusu var mı?
        query = select(BaySchedule).where(
            and_(
                BaySchedule.technician_id == tech.id,
                BaySchedule.status.in_(["scheduled", "in_progress"]),
                func.julianday(BaySchedule.starts_at) < func.julianday(end_iso),
                func.julianday(BaySchedule.ends_at) > func.julianday(start_iso),
            )
        )
        if exclude_schedule_id:
            query = query.where(BaySchedule.id != exclude_schedule_id)

        overlapping = db.scalar(query)
        if not overlapping:
            return tech

    return None


def _evaluate_single_window(
    db: Session,
    *,
    package_type: str,
    start_dt: datetime,
    stages_spec: List[Dict[str, Any]],
    exclude_schedule_id: Optional[str] = None,
) -> Tuple[bool, List[AllocatedStage], Optional[str], Optional[str], Optional[str]]:
    """
    Tek bir başlangıç zamanı için ardışık aşamaların uygunluğunu kontrol eder.
    Dönüş: (is_ok, allocated_stages, bottleneck_stage, bottleneck_bay_type, bottleneck_reason)
    """
    current_dt = start_dt
    allocated: List[AllocatedStage] = []

    for idx, stage_info in enumerate(stages_spec, start=1):
        stage_key = stage_info["stage"]
        duration = stage_info["duration_minutes"]
        stage_def = STAGE_DEFINITIONS.get(stage_key, {})
        bay_type = stage_def.get("bay_type", stage_key)
        specialty = stage_def.get("required_specialty", stage_key)
        stage_name = stage_def.get("name", stage_key)

        stage_start_iso = format_iso_datetime(current_dt)
        stage_end_dt = current_dt + timedelta(minutes=duration)
        stage_end_iso = format_iso_datetime(stage_end_dt)

        # 1. Boş Bay Arama
        free_bay = find_free_bay_for_window(
            db,
            bay_type=bay_type,
            start_iso=stage_start_iso,
            end_iso=stage_end_iso,
            exclude_schedule_id=exclude_schedule_id,
        )
        if not free_bay:
            reason = f"{stage_name} için uygun {BAY_TYPES.get(bay_type, {}).get('name', bay_type)} dolu veya bakımda."
            return False, [], stage_key, bay_type, reason

        # 2. Uygun Teknisyen Arama
        free_tech = find_free_technician_for_window(
            db,
            required_specialty=specialty,
            start_iso=stage_start_iso,
            end_iso=stage_end_iso,
            exclude_schedule_id=exclude_schedule_id,
        )
        if not free_tech:
            reason = f"{stage_name} aşaması için müsait uzman teknisyen bulunamadı."
            return False, [], stage_key, bay_type, reason

        alloc = AllocatedStage(
            stage_index=idx,
            stage_key=stage_key,
            stage_name=stage_name,
            bay_type=bay_type,
            bay_id=free_bay.id,
            bay_name=free_bay.name,
            technician_id=free_tech.id,
            technician_name=free_tech.name,
            starts_at=stage_start_iso,
            ends_at=stage_end_iso,
            duration_minutes=duration,
        )
        allocated.append(alloc)
        current_dt = stage_end_dt

    return True, allocated, None, None, None


def generate_spoken_bay_capacity_pitch(result: CapacityCheckResult) -> str:
    """
    Telefon görüşmesinde müşteriye sesli okunacak akıcı ve bilgilendirici
    Türkçe yanıt metnini üretir.
    """
    pkg_name = result.package_type.replace("_", " ").title()

    try:
        req_dt = parse_iso_datetime(result.requested_start_iso).astimezone(IST_TZ)
        req_time = req_dt.strftime("%H:%M")
    except Exception:
        req_time = "istenen saatte"

    if result.is_available:
        try:
            end_dt = parse_iso_datetime(result.planned_end_iso).astimezone(IST_TZ)
            end_time = end_dt.strftime("%H:%M")
        except Exception:
            end_time = ""

        time_clause = f"saat {req_time} ile {end_time} arasında" if end_time else f"saat {req_time}'te"
        pitch = (
            f"Seçtiğiniz {pkg_name} paketi için {time_clause} liftlerimiz, dinamometre istasyonumuz "
            f"ve uzman teknisyen kadromuz müsaittir. Randevunuzu güvenle onaylayabilirim."
        )
    else:
        stage_desc = STAGE_DEFINITIONS.get(result.bottleneck_stage or "", {}).get("name", "muayene")
        if result.next_available_start_iso:
            try:
                next_dt = parse_iso_datetime(result.next_available_start_iso).astimezone(IST_TZ)
                next_time = next_dt.strftime("%H:%M")
            except Exception:
                next_time = "bir sonraki saat diliminde"

            pitch = (
                f"Maalesef saat {req_time}'te {stage_desc} istasyonumuz dolu olduğundan dolayı "
                f"bu paketi en erken saat {next_time}'te başlatabiliyoruz. Saat {next_time} sizin için uygun mudur?"
            )
        else:
            pitch = (
                f"Saat {req_time}'te istasyonlarımızda yoğunluk bulunmaktadır. "
                f"Lütfen günün daha sonraki bir saatini seçebilir misiniz?"
            )

    return pitch


def check_multi_stage_bay_capacity(
    db: Session,
    *,
    package_type: str,
    requested_start_iso: str,
    exclude_schedule_id: Optional[str] = None,
    lookahead_intervals: int = 16,  # 16 x 15 dk = 4 saat ileriye tarama
    seed: bool = True,
) -> CapacityCheckResult:
    """
    Bir ekspertiz paketinin tüm alt istasyon aşamalarını sıralı olarak simüle eder.
    Çakışma varsa darboğazı tespit eder ve çakışmasız en erken alternatif zamanı bulur.
    """
    if seed:
        seed_default_bays_and_technicians(db)

    stages_spec = PACKAGE_STAGE_ROUTING.get(
        package_type, PACKAGE_STAGE_ROUTING["standart_ekspertiz"]
    )
    total_duration = sum(s["duration_minutes"] for s in stages_spec)

    req_start_dt = parse_iso_datetime(requested_start_iso)
    req_end_dt = req_start_dt + timedelta(minutes=total_duration)

    is_ok, allocated, b_stage, b_bay, b_reason = _evaluate_single_window(
        db,
        package_type=package_type,
        start_dt=req_start_dt,
        stages_spec=stages_spec,
        exclude_schedule_id=exclude_schedule_id,
    )

    if is_ok:
        res = CapacityCheckResult(
            is_available=True,
            package_type=package_type,
            total_duration_minutes=total_duration,
            requested_start_iso=format_iso_datetime(req_start_dt),
            planned_end_iso=format_iso_datetime(req_end_dt),
            allocated_stages=allocated,
            bottleneck_stage=None,
            bottleneck_bay_type=None,
            bottleneck_reason=None,
            next_available_start_iso=None,
        )
        res.spoken_pitch = generate_spoken_bay_capacity_pitch(res)
        return res

    # Çakışma var: Bir sonraki müsait aralığı bul
    next_avail_iso = None
    for step in range(1, lookahead_intervals + 1):
        candidate_dt = req_start_dt + timedelta(minutes=15 * step)
        c_ok, _, _, _, _ = _evaluate_single_window(
            db,
            package_type=package_type,
            start_dt=candidate_dt,
            stages_spec=stages_spec,
            exclude_schedule_id=exclude_schedule_id,
        )
        if c_ok:
            next_avail_iso = format_iso_datetime(candidate_dt)
            break

    res = CapacityCheckResult(
        is_available=False,
        package_type=package_type,
        total_duration_minutes=total_duration,
        requested_start_iso=format_iso_datetime(req_start_dt),
        planned_end_iso=format_iso_datetime(req_end_dt),
        allocated_stages=[],
        bottleneck_stage=b_stage,
        bottleneck_bay_type=b_bay,
        bottleneck_reason=b_reason,
        next_available_start_iso=next_avail_iso,
    )
    res.spoken_pitch = generate_spoken_bay_capacity_pitch(res)
    return res


def schedule_multi_stage_appointment(
    db: Session,
    *,
    appointment_id: str,
    package_type: str,
    start_time_iso: str,
    plate: str = "",
    notes: str = "",
) -> List[BaySchedule]:
    """
    Randevu için çok aşamalı istasyon ve teknisyen çizelgesini atomik olarak oluşturur.
    Kapasite yetersizse veya çakışma varsa ValueError fırlatır.
    """
    check_result = check_multi_stage_bay_capacity(
        db,
        package_type=package_type,
        requested_start_iso=start_time_iso,
    )

    if not check_result.is_available:
        err_msg = (
            f"İstasyon kapasitesi yetersiz: {check_result.bottleneck_reason} "
            f"(En erken uygun saat: {check_result.next_available_start_iso})"
        )
        raise ValueError(err_msg)

    valid_app_id = appointment_id if (appointment_id and db.get(Appointment, appointment_id)) else None

    created_schedules: List[BaySchedule] = []
    for stage in check_result.allocated_stages:
        sched = BaySchedule(
            appointment_id=valid_app_id,
            bay_id=stage.bay_id,
            technician_id=stage.technician_id,
            package_type=package_type,
            stage_name=stage.stage_name,
            stage_index=stage.stage_index,
            starts_at=stage.starts_at,
            ends_at=stage.ends_at,
            duration_minutes=stage.duration_minutes,
            status="scheduled",
            notes=notes,
        )
        db.add(sched)
        created_schedules.append(sched)

    # İlk aşama istasyonunu aktif randevuyla ilişkilendir
    if created_schedules:
        first_stage = check_result.allocated_stages[0]
        first_bay = db.get(InspectionBay, first_stage.bay_id)
        if first_bay:
            first_bay.current_appointment_id = valid_app_id
            first_bay.current_vehicle_plate = plate

    db.commit()
    for s in created_schedules:
        db.refresh(s)

    return created_schedules


def cancel_appointment_schedules(db: Session, *, appointment_id: str) -> int:
    """
    İptal edilen randevunun rezerve edilmiş tüm istasyon kayıtlarını serbest bırakır.
    """
    schedules = db.scalars(
        select(BaySchedule).where(
            and_(
                BaySchedule.appointment_id == appointment_id,
                BaySchedule.status.in_(["scheduled", "in_progress"]),
            )
        )
    ).all()

    count = 0
    for s in schedules:
        s.status = "cancelled"
        count += 1

    # İlgili istasyonların durumunu temizle
    bays = db.scalars(
        select(InspectionBay).where(InspectionBay.current_appointment_id == appointment_id)
    ).all()
    for b in bays:
        b.current_appointment_id = None
        b.current_vehicle_plate = ""
        if b.status == "busy":
            b.status = "idle"

    db.commit()
    return count


def get_bay_station_analytics(db: Session, date_str: Optional[str] = None) -> Dict[str, Any]:
    """
    Şubedeki istasyonların ve uzman teknisyenlerin doluluk, kullanım oranı ve darboğaz analizini üretir.
    """
    seed_default_bays_and_technicians(db)

    bays = db.scalars(select(InspectionBay)).all()
    techs = db.scalars(select(Technician)).all()

    # Tarih filtresi (varsayılan bugün)
    if not date_str:
        date_str = datetime.now(IST_TZ).strftime("%Y-%m-%d")

    schedules = db.scalars(
        select(BaySchedule).where(
            and_(
                BaySchedule.starts_at.startswith(date_str),
                BaySchedule.status != "cancelled",
            )
        )
    ).all()

    # İstasyon bazlı doluluk (Dakika)
    bay_busy_minutes: Dict[str, int] = {}
    for s in schedules:
        bay_busy_minutes[s.bay_id] = bay_busy_minutes.get(s.bay_id, 0) + s.duration_minutes

    # Günlük mesai standardı (9 saat = 540 dakika)
    daily_shift_minutes = 540

    bay_utilization: List[Dict[str, Any]] = []
    type_load: Dict[str, Dict[str, Any]] = {
        k: {"total_minutes": 0, "bay_count": 0} for k in BAY_TYPES
    }

    for b in bays:
        busy_min = bay_busy_minutes.get(b.id, 0)
        rate = round(min(1.0, busy_min / daily_shift_minutes) * 100, 1)
        bay_utilization.append({
            "bay_id": b.id,
            "bay_name": b.name,
            "bay_number": b.bay_number,
            "bay_type": b.bay_type,
            "status": b.status,
            "busy_minutes": busy_min,
            "utilization_percent": rate,
        })
        if b.bay_type in type_load:
            type_load[b.bay_type]["total_minutes"] += busy_min
            type_load[b.bay_type]["bay_count"] += 1

    # Tür bazlı ortalama doluluk ve darboğaz tespiti
    critical_bottleneck_type = None
    highest_type_rate = -1.0
    type_summary: Dict[str, Any] = {}

    for k, v in type_load.items():
        total_cap_min = max(1, v["bay_count"] * daily_shift_minutes)
        rate = round((v["total_minutes"] / total_cap_min) * 100, 1)
        type_summary[k] = {
            "name": BAY_TYPES.get(k, {}).get("name", k),
            "bay_count": v["bay_count"],
            "total_busy_minutes": v["total_minutes"],
            "utilization_percent": rate,
            "is_congested": rate >= 75.0,
        }
        if rate > highest_type_rate:
            highest_type_rate = rate
            critical_bottleneck_type = k

    # Teknisyen İş Yükü Dağılımı
    tech_busy_minutes: Dict[str, int] = {}
    for s in schedules:
        if s.technician_id:
            tech_busy_minutes[s.technician_id] = tech_busy_minutes.get(s.technician_id, 0) + s.duration_minutes

    tech_utilization: List[Dict[str, Any]] = []
    for t in techs:
        busy_min = tech_busy_minutes.get(t.id, 0)
        rate = round(min(1.0, busy_min / daily_shift_minutes) * 100, 1)
        tech_utilization.append({
            "technician_id": t.id,
            "name": t.name,
            "title": t.title,
            "is_active": t.is_active,
            "busy_minutes": busy_min,
            "utilization_percent": rate,
        })

    bottleneck_advice = (
        f"{BAY_TYPES.get(critical_bottleneck_type, {}).get('name', critical_bottleneck_type)} "
        f"en yüksek yoğunluğa sahiptir (%{highest_type_rate}). Yeni randevularda alternatif zaman dilimleri önerilmelidir."
        if critical_bottleneck_type and highest_type_rate > 0 else "İstasyon kapasitesi dengeli ve açık durumdadır."
    )

    return {
        "date": date_str,
        "total_bays": len(bays),
        "total_technicians": len(techs),
        "total_scheduled_stages": len(schedules),
        "critical_bottleneck_bay_type": critical_bottleneck_type,
        "bottleneck_advice": bottleneck_advice,
        "station_type_summary": type_summary,
        "bays_utilization": bay_utilization,
        "technicians_utilization": tech_utilization,
    }


def list_bays(db: Session) -> List[InspectionBay]:
    """Tüm muayene istasyonlarını listeler."""
    seed_default_bays_and_technicians(db)
    return list(db.scalars(select(InspectionBay).order_by(InspectionBay.bay_number.asc())).all())


def list_technicians(db: Session) -> List[Technician]:
    """Tüm teknisyenleri listeler."""
    seed_default_bays_and_technicians(db)
    return list(db.scalars(select(Technician).order_by(Technician.name.asc())).all())


def list_bay_schedules(
    db: Session,
    date_str: Optional[str] = None,
    limit: int = 100,
) -> List[BaySchedule]:
    """İstasyon randevu çizelgesini listeler."""
    query = select(BaySchedule).order_by(BaySchedule.starts_at.asc())
    if date_str:
        query = query.where(BaySchedule.starts_at.startswith(date_str))
    query = query.limit(limit)
    return list(db.scalars(query).all())


def set_bay_status(db: Session, bay_id: str, status: str) -> InspectionBay:
    """İstasyonun operasyonel durumunu günceller ('idle', 'busy', 'maintenance')."""
    bay = db.get(InspectionBay, bay_id)
    if not bay:
        raise ValueError(f"İstasyon bulunamadı: {bay_id}")
    if status not in {"idle", "busy", "maintenance"}:
        raise ValueError(f"Geçersiz istasyon durumu: {status}")

    bay.status = status
    if status in {"idle", "maintenance"}:
        bay.current_appointment_id = None
        bay.current_vehicle_plate = ""
    db.commit()
    db.refresh(bay)
    return bay


def set_technician_status(db: Session, technician_id: str, is_active: bool) -> Technician:
    """Teknisyenin aktif/pasif durumunu günceller."""
    tech = db.get(Technician, technician_id)
    if not tech:
        raise ValueError(f"Teknisyen bulunamadı: {technician_id}")
    tech.is_active = is_active
    db.commit()
    db.refresh(tech)
    return tech

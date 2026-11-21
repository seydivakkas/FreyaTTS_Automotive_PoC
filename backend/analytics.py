"""Analytics, KPI calculations, and follow-up conversation management.

Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) - Tüm Hakları Saklıdır.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import select
from backend.db import Conversation, Turn, Appointment, now

logger = logging.getLogger("automotive_voice.analytics")


def _calc_percentile(data: list[float], percentile: float) -> float | None:
    """Calculates the given percentile (0..100); no measurement yields None, never 0."""
    if not data:
        return None
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (percentile / 100.0)
    f = int(k)
    c = f + 1
    if c < len(sorted_data):
        return round(sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f]), 1)
    return round(float(sorted_data[f]), 1)


def get_analytics_overview(db) -> dict[str, Any]:
    """Computes comprehensive analytics and KPIs across conversations, turns, and appointments."""
    now_utc = datetime.now(timezone.utc)

    # 1. Conversation Counts & Statuses
    conversations = db.scalars(select(Conversation)).all()
    total_conversations = len(conversations)

    status_counts = defaultdict(int)
    channel_counts = defaultdict(int)
    conv_timestamps: dict[str, list[datetime]] = defaultdict(list)

    for c in conversations:
        status_counts[c.status] += 1
        channel_counts[c.channel or "web"] += 1
        try:
            dt = datetime.fromisoformat(c.created_at)
            conv_timestamps[c.id].append(dt)
        except Exception:
            pass

    # 2. Appointment Counts & Conversion
    appointments = db.scalars(select(Appointment)).all()
    total_appointments = len(appointments)
    confirmed_appointments = sum(
        1 for a in appointments if a.confirmed and a.status == "confirmed"
    )
    cancelled_appointments = sum(1 for a in appointments if a.status == "cancelled")

    cancellation_rate = (
        round((cancelled_appointments / total_appointments) * 100, 1)
        if total_appointments > 0
        else 0.0
    )

    conversion_rate = (
        round((confirmed_appointments / total_conversations) * 100, 1)
        if total_conversations > 0
        else 0.0
    )

    # 3. Turns & Metric Latency Arrays
    turns = db.scalars(select(Turn).order_by(Turn.created_at)).all()
    total_turns = len(turns)

    user_turns_count = 0
    unclear_turns_count = 0
    barge_in_count = 0

    first_audio_list: list[float] = []
    llm_total_list: list[float] = []
    llm_first_token_list: list[float] = []
    stt_list: list[float] = []
    tts_list: list[float] = []
    rtf_list: list[float] = []

    for t in turns:
        try:
            dt = datetime.fromisoformat(t.created_at)
            conv_timestamps[t.conversation_id].append(dt)
        except Exception:
            pass

        if t.role == "user":
            user_turns_count += 1
        elif t.role == "assistant":
            # Check for clarification / unclear response
            text_lower = (t.text or "").lower()
            if any(
                phrase in text_lower
                for phrase in [
                    "anlayamadım",
                    "tekrar edebilir misiniz",
                    "tekrar söyleyebilir misiniz",
                    "net duyamadım",
                    "doğrulayamadım",
                ]
            ):
                unclear_turns_count += 1

        # Parse metrics
        if t.metrics and t.metrics != "{}":
            try:
                m = json.loads(t.metrics) if isinstance(t.metrics, str) else t.metrics
                if isinstance(m, dict):
                    if "first_audio_ms" in m and m["first_audio_ms"] is not None:
                        first_audio_list.append(float(m["first_audio_ms"]))
                    if "llm_total_ms" in m and m["llm_total_ms"] is not None:
                        llm_total_list.append(float(m["llm_total_ms"]))
                    if "llm_first_token_ms" in m and m["llm_first_token_ms"] is not None:
                        llm_first_token_list.append(float(m["llm_first_token_ms"]))
                    if "stt_ms" in m and m["stt_ms"] is not None:
                        stt_list.append(float(m["stt_ms"]))
                    if "tts_ms" in m and m["tts_ms"] is not None:
                        tts_list.append(float(m["tts_ms"]))
                    if "rtf" in m and m["rtf"] is not None:
                        rtf_list.append(float(m["rtf"]))
                    if "barge_in_signal_ms" in m and m["barge_in_signal_ms"] is not None:
                        barge_in_count += 1
            except Exception:
                pass

    # STT Accuracy / Clarity rate
    clarity_rate = (
        round(100.0 - (unclear_turns_count / max(user_turns_count, 1) * 100.0), 1)
        if user_turns_count > 0
        else None
    )

    # Average Conversation Duration (seconds)
    durations = []
    for cid, dts in conv_timestamps.items():
        if len(dts) >= 2:
            dur = (max(dts) - min(dts)).total_seconds()
            if 0 < dur < 3600:  # Ignore anomalies > 1 hour
                durations.append(dur)
    avg_duration_sec = round(sum(durations) / len(durations), 1) if durations else None

    # 4. Latency KPI Summary Dict (ölçüm yoksa None; sahte sıfır üretilmez)
    latency_kpis = {
        "first_audio_ms": {
            "avg": round(sum(first_audio_list) / len(first_audio_list), 1)
            if first_audio_list
            else None,
            "min": round(min(first_audio_list), 1) if first_audio_list else None,
            "max": round(max(first_audio_list), 1) if first_audio_list else None,
            "p50": _calc_percentile(first_audio_list, 50),
            "p95": _calc_percentile(first_audio_list, 95),
            "sample_count": len(first_audio_list),
        },
        "llm_ms": {
            "avg_total": round(sum(llm_total_list) / len(llm_total_list), 1)
            if llm_total_list
            else None,
            "p50_total": _calc_percentile(llm_total_list, 50),
            "p95_total": _calc_percentile(llm_total_list, 95),
            "avg_first_token": round(
                sum(llm_first_token_list) / len(llm_first_token_list), 1
            )
            if llm_first_token_list
            else None,
            "p50_first_token": _calc_percentile(llm_first_token_list, 50),
            "p95_first_token": _calc_percentile(llm_first_token_list, 95),
            "sample_count": len(llm_total_list),
        },
        "stt_ms": {
            "avg": round(sum(stt_list) / len(stt_list), 1) if stt_list else None,
            "p50": _calc_percentile(stt_list, 50),
            "p95": _calc_percentile(stt_list, 95),
            "sample_count": len(stt_list),
        },
        "tts_ms": {
            "avg": round(sum(tts_list) / len(tts_list), 1) if tts_list else None,
            "avg_rtf": round(sum(rtf_list) / len(rtf_list), 3) if rtf_list else None,
            "sample_count": len(tts_list),
        },
        "barge_in_count": barge_in_count,
    }

    # 5. Daily Trend (Last 14 Days)
    daily_stats: dict[str, dict[str, int]] = {}
    for i in range(13, -1, -1):
        day_str = (now_utc - timedelta(days=i)).strftime("%Y-%m-%d")
        daily_stats[day_str] = {"date": day_str, "appointments": 0, "conversations": 0}

    for a in appointments:
        day = (a.created_at or "")[:10]
        if day in daily_stats:
            daily_stats[day]["appointments"] += 1

    for c in conversations:
        day = (c.created_at or "")[:10]
        if day in daily_stats:
            daily_stats[day]["conversations"] += 1

    daily_trend = list(daily_stats.values())

    # 6. Hourly Call Distribution (00..23)
    hourly_distribution = [0] * 24
    for c in conversations:
        try:
            dt = datetime.fromisoformat(c.created_at)
            hourly_distribution[dt.hour] += 1
        except Exception:
            pass

    return {
        "summary": {
            "total_conversations": total_conversations,
            "completed_conversations": status_counts.get("completed", 0),
            "follow_up_conversations": status_counts.get("follow_up", 0),
            "resolved_conversations": status_counts.get("resolved", 0),
            "active_conversations": status_counts.get("active", 0),
            "total_appointments": total_appointments,
            "confirmed_appointments": confirmed_appointments,
            "cancelled_appointments": cancelled_appointments,
            "cancellation_rate_pct": cancellation_rate,
            "conversion_rate_pct": conversion_rate,
            "avg_turns_per_conversation": (
                round(total_turns / total_conversations, 1) if total_conversations else None
            ),
            "avg_duration_seconds": avg_duration_sec,
            "stt_clarity_rate_pct": clarity_rate,
            "stt_unclear_count": unclear_turns_count,
            "channels": dict(channel_counts),
        },
        "latency_kpis": latency_kpis,
        "daily_trend": daily_trend,
        "hourly_distribution": hourly_distribution,
    }


def get_follow_up_conversations(db, status_filter: str = "all", limit: int = 50) -> list[dict[str, Any]]:
    """Returns conversations that require operator follow-up or were resolved."""
    query = select(Conversation)
    if status_filter == "follow_up":
        query = query.where(Conversation.status == "follow_up")
    elif status_filter == "resolved":
        query = query.where(Conversation.status == "resolved")
    elif status_filter == "pending_all":
        query = query.where(Conversation.status.in_(["follow_up", "active"]))

    query = query.order_by(Conversation.created_at.desc()).limit(limit)
    conversations = db.scalars(query).all()

    items = []
    for c in conversations:
        # Get turns for this conversation
        turns = db.scalars(
            select(Turn)
            .where(Turn.conversation_id == c.id)
            .order_by(Turn.created_at)
        ).all()

        last_user_text = ""
        last_assistant_text = ""
        duration_sec = 0.0

        if turns:
            try:
                t0 = datetime.fromisoformat(turns[0].created_at)
                t1 = datetime.fromisoformat(turns[-1].created_at)
                duration_sec = max(0.0, round((t1 - t0).total_seconds(), 1))
            except Exception:
                pass

            for t in reversed(turns):
                if not last_user_text and t.role == "user":
                    last_user_text = t.text
                if not last_assistant_text and t.role == "assistant":
                    last_assistant_text = t.text
                if last_user_text and last_assistant_text:
                    break

        items.append(
            {
                "id": c.id,
                "channel": c.channel,
                "status": c.status,
                "operator_notes": c.operator_notes or "",
                "resolved_at": c.resolved_at,
                "created_at": c.created_at,
                "turn_count": len(turns),
                "duration_seconds": duration_sec,
                "last_user_text": last_user_text,
                "last_assistant_text": last_assistant_text,
            }
        )

    return items


def resolve_conversation(
    db, conversation_id: str, operator_notes: str = ""
) -> Conversation:
    """Marks a conversation as resolved by an operator with notes."""
    c = db.get(Conversation, conversation_id)
    if not c:
        raise ValueError("Görüşme bulunamadı")
    c.status = "resolved"
    c.operator_notes = operator_notes
    c.resolved_at = now()
    db.commit()
    return c


def reopen_conversation(db, conversation_id: str) -> Conversation:
    """Reopens a resolved conversation back to follow_up status."""
    c = db.get(Conversation, conversation_id)
    if not c:
        raise ValueError("Görüşme bulunamadı")
    c.status = "follow_up"
    c.resolved_at = None
    c.follow_up_at = now()
    db.commit()
    return c


UNCLEAR_PATTERNS = [
    "anlayamadım",
    "tekrar edebilir misiniz",
    "tekrar söyleyebilir misiniz",
    "net duyamadım",
    "doğrulayamadım",
    "tam duyamadım",
]


def get_unclear_conversations(db, limit: int = 50) -> list[dict[str, Any]]:
    """Returns conversations where the assistant asked for clarification or misrecognition occurred."""
    from backend.config import settings

    # Fetch recent conversations
    conversations = db.scalars(
        select(Conversation)
        .order_by(Conversation.created_at.desc())
        .limit(limit * 3)
    ).all()

    unclear_list = []
    for c in conversations:
        turns = db.scalars(
            select(Turn)
            .where(Turn.conversation_id == c.id)
            .order_by(Turn.created_at)
        ).all()

        unclear_turns = []
        turn_items = []
        for t in turns:
            text_lower = (t.text or "").lower()
            is_unclear = t.role == "assistant" and any(p in text_lower for p in UNCLEAR_PATTERNS)
            if is_unclear:
                unclear_turns.append(t.text)
            turn_items.append({
                "id": t.id,
                "role": t.role,
                "text": t.text,
                "metrics": t.metrics,
                "created_at": t.created_at,
                "is_unclear": is_unclear,
            })

        # Include if has unclear turns or status is follow_up
        if unclear_turns or c.status == "follow_up":
            rec_path = settings.data_dir / "recordings" / f"{c.id}.wav"
            unclear_list.append({
                "id": c.id,
                "status": c.status,
                "channel": c.channel or "voice",
                "created_at": c.created_at,
                "operator_notes": c.operator_notes or "",
                "resolved_at": c.resolved_at,
                "turn_count": len(turns),
                "unclear_count": len(unclear_turns),
                "unclear_phrases": unclear_turns,
                "has_recording": rec_path.exists(),
                "turns": turn_items,
            })
            if len(unclear_list) >= limit:
                break

    return unclear_list



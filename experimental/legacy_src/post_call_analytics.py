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

from backend.post_call_analytics import (
    analyze_conversation_transcript,
    calculate_lead_score,
    compute_sentiment_and_csat,
    detect_call_intent,
    evaluate_and_save_call_analytics,
    extract_objections_and_topics,
    generate_executive_summary,
    get_analytics_summary_stats,
    parse_transcript_turns,
)

__all__ = [
    "analyze_conversation_transcript",
    "calculate_lead_score",
    "compute_sentiment_and_csat",
    "detect_call_intent",
    "evaluate_and_save_call_analytics",
    "extract_objections_and_topics",
    "generate_executive_summary",
    "get_analytics_summary_stats",
    "parse_transcript_turns",
]


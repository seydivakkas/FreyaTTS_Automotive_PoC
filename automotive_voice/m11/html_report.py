"""Offline HTML acceptance summary; no JS/CDN. Evidence references stay in local JSON."""
from html import escape
from pathlib import Path

def create_html(data:dict,path:Path)->None:
    labels={
        'windows_edge':'Windows 11 / Edge','freya_leyla':'FreyaTTS / Leyla',
        'stt_vad':'STT / VAD','codec':'Audio / Codec',
        'asterisk_pbx':'Asterisk / PBX','a01yt_references':'A01-YT Referanslar',
        'safety_privacy':'Güvenlik / KVKK','legacy_regression':'M01–M10 Regresyon'}
    rows=[]
    for g in data['gates']:
        status=g['status'];reason=', '.join(g['checks']) or '—'
        rows.append('<tr><td>'+escape(labels.get(g['name'],g['name']))+'</td>'
                    '<td><span class="state '+escape(status.lower())+'">'+escape(status)+'</span></td>'
                    '<td>'+escape(reason)+'</td></tr>')
    html='''<!DOCTYPE html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>M11 Fiziksel Kabul</title><style>
:root{color-scheme:light dark;font-family:system-ui,-apple-system,'Segoe UI',sans-serif}
body{max-width:1040px;margin:50px auto;padding:0 22px;line-height:1.55}
h1{font-size:1.7rem}p{max-width:80ch;color:gray}table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:13px 12px;border-bottom:1px solid #8886;vertical-align:top}
th{font-weight:650}.state{display:inline-block;padding:3px 9px;border-radius:7px;background:#8882;font-weight:650}
.pass{color:#157750}.fail{color:#bb3535}.hold{color:#a16b18}
.note{margin-top:24px;border-left:3px solid #8889;padding-left:15px}
</style></head><body><h1>FreyaTTS · M11 Fiziksel Kabul</h1>
<p>Kanıta dayalı laboratuvar kabulü. M01–M10 yazılım testlerinin geçmesi gerçek model, ses ve telefon kabulü değildir.</p>
<h2>Genel karar: <span class="state STATE">VERDICT</span></h2>
<table><thead><tr><th>Kabul alanı</th><th>Durum</th><th>Bulgu / eksik kanıt</th></tr></thead><tbody>ROWS</tbody></table>
<div class="note"><strong>Not:</strong> PASS olan bir kapının ham kanıtı JSON dosyasındaki SHA-256 referanslarıyla ayrıca denetlenmelidir. HOLD/FAIL durumda gerçek çağrı yayınına geçilmez. Production readiness: false.</div>
</body></html>'''
    html=html.replace('STATE',escape(data['overall'].lower())).replace('VERDICT',escape(data['overall'])).replace('ROWS',''.join(rows))
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(html,encoding='utf-8')

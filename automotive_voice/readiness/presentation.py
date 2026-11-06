"""Evidence-preserving M03 display-to-speech adapter.

Keeps source response intact for display/audit and supplies separate safe speech.
Only fixed policy categories are allowed. Unreviewed brand readings remain gated.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import re
from automotive_voice.dialogue.storage import StoredResponse

@dataclass(frozen=True)
class SpeechCandidate:
    display_text: str
    speech_text: str
    rewritten: bool
    warnings: tuple[str,...] = ()

class PolicySpeechPresenter:
    PRICE=re.compile(r'(?<![\w])([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+) Türk lirasıdır\.')
    OFFER=re.compile(r'^([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}[+-][0-9]{2}:[0-9]{2}) tarihinde, ([A-Z_]{2,40}) lokasyonunda ')
    ID_REF=re.compile(r'(?<!\w)(?:Onay referansı|Referans|Takip referansı):\s*([\w-]{1,100})\.')
    KNOWN_LOCATIONS={'TRABZON':'Trabzon'}

    def render(self,response:StoredResponse)->SpeechCandidate:
        source=response.text
        text=source
        warnings=[]
        if response.category=='price_verified':
            text,count=self.PRICE.subn(lambda m:m.group(1)+' TL.',text)
            if count!=1:warnings.append('price_format_requires_review')
        elif response.category=='offer_confirmation':
            match=self.OFFER.search(text)
            if match:
                try:
                    dt=datetime.fromisoformat(match.group(1))
                    if dt.tzinfo is None:raise ValueError('timezone required')
                    loc=self.KNOWN_LOCATIONS.get(match.group(2))
                    if not loc:raise ValueError('unmapped location')
                    rendered=f'{dt.day:02d}.{dt.month:02d}.{dt.year} tarihinde, saat {dt.hour:02d}:{dt.minute:02d} için {loc} servis noktasında '
                    text=rendered+text[match.end():].replace('ekspertiz için müsaitlik','ekspertiz müsaitliği',1)
                except ValueError:
                    warnings.append('slot_display_requires_review')
            else:warnings.append('slot_display_requires_review')
        elif response.category in ('booking_confirmed','booking_reconciled','already_confirmed',
                                   'crm_case_created'):
            # Hide opaque identifiers in *speech* but preserve in display.
            text,count=self.ID_REF.subn('Referans bilgisi operatör ekranında görüntüleniyor.',text)
            if count!=1:warnings.append('opaque_reference_requires_review')
        return SpeechCandidate(source,text,text!=source,tuple(warnings))

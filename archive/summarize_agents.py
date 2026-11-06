with open('user_request_5292_full.txt', 'r', encoding='utf-8') as f:
    text = f.read()

import re
agents_pos = [
    ("Ajan 1", text.find("Ajan 1: Otomotiv Dilbilim")),
    ("Ajan 2", text.find("Ajan 2: Prozodi")),
    ("Ajan 3", text.find("Ajan 3: FreyaTTS")),
    ("Ajan 4", text.find("Ajan 4: Gerçek Zamanlı")),
    ("Ajan 5", text.find("Ajan 5: Asterisk Telefon")),
    ("Ajan 6", text.find("Ajan 6: Model Uyarlama")),
    ("Ajan 7", text.find("Ajan 7: Kalite Kapısı")),
]

with open('agents_summary.txt', 'w', encoding='utf-8') as out:
    for name, pos in agents_pos:
        out.write(f"=== {name} (pos {pos}) ===\n")
        snippet = text[pos:pos+2000]
        out.write(snippet + "\n\n")

print("Written agents_summary.txt")

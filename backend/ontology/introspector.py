"""
FreyaTTS Automotive Cockpit — Database Introspector & Schema Discoverer
Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR

NVIDIA Auto-Ontology "Discover" adımı:
Mevcut SQLAlchemy veritabanı şemasını otomatik tarar, tabloları, ilişkileri
ve semantik kavramları düğüm (node) ve kenar (edge) grafı olarak çıkarır.
"""

from __future__ import annotations

import datetime
from typing import List
from backend.db import Base
from backend.ontology.models import (
    OntologyEdge,
    OntologyNode,
    OntologyNodeType,
    OntologySchemaGraph,
    RelationType,
)
from backend.ontology.grounding import (
    CERTIFIED_DIAGNOSTIC_FAULTS,
    CERTIFIED_SERVICE_PACKAGES,
    CERTIFIED_VEHICLE_CATALOG,
)


class DatabaseIntrospector:
    """
    SQLAlchemy metaverilerini ve iş kavramlarını haritalandıran ontoloji keşif motoru.
    """

    @classmethod
    def introspect_schema(cls) -> OntologySchemaGraph:
        nodes: List[OntologyNode] = []
        edges: List[OntologyEdge] = []
        tables = Base.metadata.tables

        # 1. Fiziksel Tabloları Keşfet
        for table_name, table in tables.items():
            cols = {c.name: str(c.type) for c in table.columns}
            pk = [c.name for c in table.primary_key.columns] if table.primary_key else []

            nodes.append(
                OntologyNode(
                    id=f"table:{table_name}",
                    name=table_name,
                    type=OntologyNodeType.TABLE,
                    domain="physical_schema",
                    description=f"{table_name} fiziksel veritabanı tablosu ({len(cols)} kolon).",
                    properties={
                        "columns": cols,
                        "primary_key": pk,
                        "column_count": len(cols),
                    },
                    is_certified=True,
                )
            )

            # Yabancı anahtar (Foreign Key) ilişkilerini kenar (edge) olarak ekle
            for fk in table.foreign_keys:
                target_table = fk.column.table.name
                edges.append(
                    OntologyEdge(
                        source=f"table:{table_name}",
                        target=f"table:{target_table}",
                        relation=RelationType.FOREIGN_KEY,
                        description=f"{table_name}.{fk.parent.name} -> {target_table}.{fk.column.name}",
                        is_required=not fk.parent.nullable,
                    )
                )

        # 2. Semantik İş Kavramlarını (Concepts) Graf'a Bağla
        # Concept: ServicePackage (Fiyatlandırma & Paket Ontolojisi)
        nodes.append(
            OntologyNode(
                id="concept:service_packages",
                name="Sertifikalı Ekspertiz Paketleri (Tek Gerçek Kaynak)",
                type=OntologyNodeType.CONCEPT,
                domain="business_logic",
                description="Ekspertiz ve muayene paketlerinin resmi fiyat, süre ve kapsam sözleşmesi.",
                properties={
                    "package_count": len(CERTIFIED_SERVICE_PACKAGES),
                    "packages": [p.model_dump() for p in CERTIFIED_SERVICE_PACKAGES.values()],
                },
                is_certified=True,
            )
        )
        edges.append(
            OntologyEdge(
                source="concept:service_packages",
                target="table:appointments",
                relation=RelationType.DEFINES_PRICE,
                description="Paket fiyatları randevu ve tahakkuk kayıtlarına bağlanır.",
            )
        )

        # Concept: DiagnosticFaults (OBD-II Arıza Ontolojisi)
        nodes.append(
            OntologyNode(
                id="concept:diagnostic_faults",
                name="Sertifikalı OBD-II Teşhis Ontolojisi",
                type=OntologyNodeType.CONCEPT,
                domain="diagnostics",
                description="Otomotiv arıza kodları (DTC), ikaz lambaları ve mekanik belirtiler.",
                properties={
                    "fault_count": len(CERTIFIED_DIAGNOSTIC_FAULTS),
                    "fault_codes": list(CERTIFIED_DIAGNOSTIC_FAULTS.keys()),
                },
                is_certified=True,
            )
        )
        edges.append(
            OntologyEdge(
                source="concept:diagnostic_faults",
                target="table:vehicle_diagnostics",
                relation=RelationType.HAS_FAULT,
                description="Arıza kodları araç teşhis tablosundaki kayıtlarla eşleşir.",
            )
        )
        edges.append(
            OntologyEdge(
                source="concept:diagnostic_faults",
                target="concept:service_packages",
                relation=RelationType.REQUIRES_PACKAGE,
                description="Arıza ciddiyetine göre önerilen muayene paketi eşleşir.",
            )
        )

        # Concept: VehicleReferenceCatalog (Katalog Normalizasyonu)
        nodes.append(
            OntologyNode(
                id="concept:vehicle_catalog",
                name="Standart Araç Referans Kataloğu",
                type=OntologyNodeType.CONCEPT,
                domain="catalog",
                description="Doğal dil ses girdisinden normalize edilen standart araç modelleri.",
                properties={
                    "vehicle_count": len(CERTIFIED_VEHICLE_CATALOG),
                    "models": [v.normalized_name for v in CERTIFIED_VEHICLE_CATALOG],
                },
                is_certified=True,
            )
        )
        edges.append(
            OntologyEdge(
                source="concept:vehicle_catalog",
                target="table:vehicles",
                relation=RelationType.VALIDATES_WITH,
                description="Kullanıcı sesindeki araç modelleri fiziksel araç tablosuyla eşleşir.",
            )
        )

        return OntologySchemaGraph(
            version="1.0.0",
            generated_at=datetime.datetime.utcnow().isoformat() + "Z",
            database_type="sqlite",
            table_count=len(tables),
            concept_count=3,
            nodes=nodes,
            edges=edges,
        )

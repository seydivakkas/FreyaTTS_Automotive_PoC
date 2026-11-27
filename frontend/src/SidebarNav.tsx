/**
 * FreyaTTS Automotive Cockpit V3 — Hiyerarşik Sidebar Navigasyonu
 * Telif Hakkı (c) 2026 Seydi Eryılmaz (@seydivakkas) — ÖZEL LİSANS / TÜM HAKLAR SAKLIDIR
 */

import React, { useState, useMemo } from "react";
import { NAV_CATEGORIES, TabName, TabMeta, CategoryId, RolePerspective, ROLE_PERSPECTIVES } from "./nav";

interface Props {
  activeTab: TabName;
  onSelectTab: (tab: TabName) => void;
  perspective: RolePerspective;
  onSelectPerspective: (p: RolePerspective) => void;
  badgeCounts?: {
    appointments?: number;
    vehicles?: number;
    calls?: number;
    quality?: number;
  };
}

export function SidebarNav({ activeTab, onSelectTab, perspective, onSelectPerspective, badgeCounts = {} }: Props) {
  const [searchQuery, setSearchQuery] = useState("");
  const [collapsedCategories, setCollapsedCategories] = useState<Record<CategoryId, boolean>>({
    audio_ai: false,
    workshop: false,
    telephony: false,
    governance: false,
  });

  const toggleCategory = (catId: CategoryId) => {
    setCollapsedCategories((prev) => ({
      ...prev,
      [catId]: !prev[catId],
    }));
  };

  // Türkçe uyumlu büyük/küçük harf duyarsız arama
  const normalizedQuery = searchQuery.trim().toLocaleLowerCase("tr-TR");

  const filteredCategories = useMemo(() => {
    const allowedTabs = perspective === "all" ? null : new Set(ROLE_PERSPECTIVES[perspective]?.tabs || []);

    return NAV_CATEGORIES.map((cat) => {
      const matchingTabs = cat.tabs.filter((t) => {
        if (allowedTabs && !allowedTabs.has(t.id)) return false;
        if (!normalizedQuery) return true;

        const textToSearch = [
          t.label,
          t.description,
          t.id,
          t.pipelineStage || "",
          ...t.keywords,
        ].join(" ").toLocaleLowerCase("tr-TR");

        return textToSearch.includes(normalizedQuery);
      });

      return {
        ...cat,
        tabs: matchingTabs,
      };
    }).filter((cat) => cat.tabs.length > 0);
  }, [normalizedQuery, perspective]);

  return (
    <aside className="cockpit-sidebar" aria-label="Operasyon Navigasyonu">
      <div className="sidebar-brand">
        <div className="brand-logo">
          <span className="brand-dot" />
          <span className="brand-text">freya<span className="brand-version">v3</span></span>
        </div>
        <div className="brand-subtitle">OTOMOTİV KOKPİTİ</div>
      </div>

      {/* 3 Çalışma Görünümü (Rol Seçici) */}
      <div className="sidebar-perspective-selector" style={{ padding: "0 12px 10px 12px", borderBottom: "1px solid rgba(255, 255, 255, 0.06)" }}>
        <div style={{ fontSize: "10px", fontWeight: 700, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "6px" }}>
          Çalışma Görünümü
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "5px" }}>
          {(["operator", "manager", "engineer", "all"] as RolePerspective[]).map((pKey) => {
            const p = ROLE_PERSPECTIVES[pKey];
            const isActive = perspective === pKey;
            return (
              <button
                key={pKey}
                type="button"
                onClick={() => onSelectPerspective(pKey)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "5px",
                  padding: "5px 7px",
                  fontSize: "11px",
                  fontWeight: isActive ? 700 : 500,
                  borderRadius: "6px",
                  border: isActive ? "1px solid #38bdf8" : "1px solid rgba(255, 255, 255, 0.08)",
                  background: isActive ? "rgba(56, 189, 248, 0.15)" : "rgba(30, 41, 59, 0.5)",
                  color: isActive ? "#38bdf8" : "#94a3b8",
                  cursor: "pointer",
                  textAlign: "left",
                  transition: "all 0.15s ease",
                  whiteSpace: "nowrap",
                }}
                title={p.description}
              >
                <span>{p.icon}</span>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>{p.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      <div className="sidebar-search">
        <div className="search-input-wrapper">
          <span className="search-icon">🔍</span>
          <input
            type="search"
            placeholder="Sekme veya F0–F6 ara..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="search-input"
            aria-label="Sekme arama"
          />
          {searchQuery && (
            <button
              type="button"
              className="clear-search-btn"
              onClick={() => setSearchQuery("")}
              aria-label="Aramayı temizle"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      <nav className="sidebar-accordion">
        {filteredCategories.length === 0 ? (
          <div className="no-search-results">
            <p>"{searchQuery}" ile eşleşen sekme bulunamadı.</p>
            <button
              type="button"
              className="reset-search-btn"
              onClick={() => setSearchQuery("")}
            >
              Tüm sekmeleri göster
            </button>
          </div>
        ) : (
          filteredCategories.map((cat) => {
            const isCollapsed = !normalizedQuery && Boolean(collapsedCategories[cat.id]);
            const hasActiveTab = cat.tabs.some((t) => t.id === activeTab);

            return (
              <div key={cat.id} className={`nav-category ${hasActiveTab ? "contains-active" : ""}`}>
                <button
                  type="button"
                  className="category-header"
                  onClick={() => toggleCategory(cat.id)}
                  aria-expanded={!isCollapsed}
                >
                  <span className="category-title">
                    <span className="cat-icon">{cat.icon}</span>
                    <span className="cat-label">{cat.label}</span>
                  </span>
                  <span className="cat-chevron">{isCollapsed ? "▸" : "▾"}</span>
                </button>

                {!isCollapsed && (
                  <ul className="category-tabs" role="menu">
                    {cat.tabs.map((tab) => {
                      const isActive = tab.id === activeTab;
                      let badgeValue: number | undefined;

                      if (tab.id === "Randevular") badgeValue = badgeCounts.appointments;
                      if (tab.id === "Araçlar ve fiyatlar") badgeValue = badgeCounts.vehicles;
                      if (tab.id === "Geçmiş") badgeValue = badgeCounts.calls;
                      if (tab.id === "Supervisor Kalite") badgeValue = badgeCounts.quality;

                      return (
                        <li key={tab.id} role="none">
                          <button
                            type="button"
                            role="menuitem"
                            className={`nav-tab-btn ${isActive ? "active" : ""}`}
                            onClick={() => onSelectTab(tab.id)}
                            aria-current={isActive ? "page" : undefined}
                          >
                            <span className="tab-icon-and-name">
                              <span className="tab-icon">{tab.icon}</span>
                              <span className="tab-name">{tab.label}</span>
                            </span>

                            <span className="tab-tags">
                              {tab.pipelineStage && (
                                <span className={`stage-badge stage-${tab.pipelineStage.toLowerCase()}`}>
                                  {tab.pipelineStage}
                                </span>
                              )}
                              {badgeValue !== undefined && badgeValue > 0 && (
                                <span className="count-badge">{badgeValue}</span>
                              )}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            );
          })
        )}
      </nav>

      <div className="sidebar-footer">
        <div className="local-tag">
          <span className="live-pulse-dot" />
          <span>Yerel RTX 4070 · İstanbul</span>
        </div>
      </div>
    </aside>
  );
}


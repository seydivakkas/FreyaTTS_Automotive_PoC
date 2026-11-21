import React, { lazy } from "react";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const lazyPanel = <K extends string>(load: () => Promise<Record<K, React.ComponentType<any>>>, name: K) =>
  lazy(() => load().then((m) => ({ default: m[name] })));
export const MilestonePanel = lazyPanel(() => import("./MilestonePanel"), "MilestonePanel");
export const LexiconPanel = lazyPanel(() => import("./LexiconPanel"), "LexiconPanel");
export const NotificationPanel = lazyPanel(() => import("./NotificationPanel"), "NotificationPanel");
export const OutboundPanel = lazyPanel(() => import("./OutboundPanel"), "OutboundPanel");
export const InspectionPanel = lazyPanel(() => import("./InspectionPanel"), "InspectionPanel");
export const AnalyticsPanel = lazyPanel(() => import("./AnalyticsPanel"), "AnalyticsPanel");
export const DiagnosticPanel = lazyPanel(() => import("./DiagnosticPanel"), "DiagnosticPanel");
export const TechnicianDictationPanel = lazyPanel(
  () => import("./TechnicianDictationPanel"),
  "TechnicianDictationPanel",
);
export const QueueLiftPanel = lazyPanel(() => import("./QueueLiftPanel"), "QueueLiftPanel");
export const ABTestingPanel = lazyPanel(() => import("./ABTestingPanel"), "ABTestingPanel");
export const OperatorPanel = lazyPanel(() => import("./OperatorPanel"), "OperatorPanel");
export const SupervisorPanel = lazyPanel(() => import("./SupervisorPanel"), "SupervisorPanel");
export const CarDenoiserPanel = lazyPanel(() => import("./CarDenoiserPanel"), "CarDenoiserPanel");
export const OntologyPanel = lazyPanel(() => import("./OntologyPanel"), "OntologyPanel");

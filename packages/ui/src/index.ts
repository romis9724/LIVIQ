/** @liviq/ui — LIVIQ 공용 디자인 시스템 컴포넌트. 스타일은 "@liviq/ui/styles.css". */
export { cx } from "./lib/cx";
export type { ClassValue } from "./lib/cx";

export { Button } from "./components/button/Button";
export type { ButtonProps, ButtonVariant, ButtonSize } from "./components/button/Button";

export { SurfaceCard } from "./components/surface-card/SurfaceCard";
export type { SurfaceCardProps } from "./components/surface-card/SurfaceCard";

export { CitationCard } from "./components/citation-card/CitationCard";
export type { CitationCardProps } from "./components/citation-card/CitationCard";

export { ConfidenceBadge } from "./components/confidence-badge/ConfidenceBadge";
export type {
  ConfidenceBadgeProps,
  ConfidenceStatus,
} from "./components/confidence-badge/ConfidenceBadge";

export { StatusPill } from "./components/status-pill/StatusPill";
export type { StatusPillProps, StatusKind } from "./components/status-pill/StatusPill";

export { FeedbackButtons } from "./components/feedback-buttons/FeedbackButtons";
export type { FeedbackButtonsProps, FeedbackVote } from "./components/feedback-buttons/FeedbackButtons";

export { FormField } from "./components/form-field/FormField";
export type { FormFieldProps } from "./components/form-field/FormField";

export { EmptyState } from "./components/empty-state/EmptyState";
export type { EmptyStateProps } from "./components/empty-state/EmptyState";

export { Toast } from "./components/toast/Toast";
export type { ToastProps, ToastTone } from "./components/toast/Toast";

export { Dialog } from "./components/dialog/Dialog";
export type { DialogProps } from "./components/dialog/Dialog";

export { StatCard, StatGrid } from "./components/stat-card/StatCard";
export type { StatCardProps, StatGridProps, StatTone } from "./components/stat-card/StatCard";

export { PageToolbar } from "./components/page-toolbar/PageToolbar";
export type { PageToolbarProps } from "./components/page-toolbar/PageToolbar";

export { FilterChips } from "./components/filter-chips/FilterChips";
export type { FilterChipsProps, FilterChipItem } from "./components/filter-chips/FilterChips";

export { SearchField } from "./components/search-field/SearchField";
export type { SearchFieldProps } from "./components/search-field/SearchField";

export { Pagination } from "./components/pagination/Pagination";
export type { PaginationProps } from "./components/pagination/Pagination";

export { Skeleton } from "./components/skeleton/Skeleton";
export type { SkeletonProps } from "./components/skeleton/Skeleton";

export { Switch } from "./components/switch/Switch";
export type { SwitchProps } from "./components/switch/Switch";

export { FileDropzone } from "./components/file-dropzone/FileDropzone";
export type { FileDropzoneProps, FileDropzoneState } from "./components/file-dropzone/FileDropzone";

export { FloorPlanViewer } from "./components/floor-plan-viewer/FloorPlanViewer";
export type {
  FloorPlanViewerProps,
  FloorPlanViewerPlan,
  FloorPlanViewerDevice,
} from "./components/floor-plan-viewer/FloorPlanViewer";

export { ParkingMap } from "./components/parking-map/ParkingMap";
export type {
  ParkingMapProps,
  ParkingMapLayout,
  ParkingMapSpot,
  ParkingMapBuilding,
  ParkingMapBox,
  ParkingSpotState,
  ParkingSpotView,
} from "./components/parking-map/ParkingMap";
export { SPOT_H, SPOT_W, elapsedText, parseViewBox } from "./components/parking-map/parking-map-data";

/* ===== AI 비서 — 메커니즘만 공용, 조립(헤더·빈 상태·CTA)은 앱별(ADR-0028 결정 4) ===== */
export {
  answerKind,
  parseSseBuffer,
  streamAssistant,
  toEvent,
} from "./components/assistant/assistant-events";
export type {
  AnswerKind,
  AssistantCitation,
  AssistantDoneResult,
  AssistantEvent,
  AssistantStage,
  FetchLike,
  StreamAssistantOptions,
} from "./components/assistant/assistant-events";

export { useAssistantStream } from "./components/assistant/useAssistantStream";
export type {
  AiMessage,
  AssistantStreamOptions,
  ChatMessage,
  UserMessage,
} from "./components/assistant/useAssistantStream";

export { parseLatestThread } from "./components/assistant/assistant-restore";
export type { RestoredThread } from "./components/assistant/assistant-restore";

export {
  EMPTY_THREAD,
  clearThread,
  parseThread,
  persistableMessages,
  readThread,
  writeThread,
} from "./components/assistant/assistant-session-store";
export type { StoredThread } from "./components/assistant/assistant-session-store";

export { answerBlocks, stripMarkers } from "./components/assistant/assistant-markdown";
export type { AnswerBlock } from "./components/assistant/assistant-markdown";

export {
  TOOL_LABELS,
  UNKNOWN_TOOL_LABEL,
  appendProgress,
  progressLabel,
} from "./components/assistant/assistant-progress";

export { citationDetail, groupCitations } from "./components/assistant/assistant-sources";
export type { GroupedSource } from "./components/assistant/assistant-sources";

export { structuredBlocks, toStructured } from "./components/assistant/assistant-structured";
export type {
  FacilityItem,
  FacilityStatusData,
  FeeMonth,
  FeeRow,
  FeeTableData,
  InquiryCase,
  InquiryCasesData,
  ParkingSpot,
  ParkingSpotsData,
  StructuredData,
} from "./components/assistant/assistant-structured";

export { AnswerBody } from "./components/assistant/AnswerBody";
export { ProgressSteps } from "./components/assistant/ProgressSteps";
export { SuggestionChips } from "./components/assistant/SuggestionChips";
export type { SuggestionChipsProps } from "./components/assistant/SuggestionChips";
export { StructuredBlock } from "./components/assistant/StructuredBlock";

// ── 주차장 3D 씬 (H14-4 web-admin → H20-8 공용 승격) ─────────────────────────
export {
  ParkingScene3D,
  SCENE_COLOR_VARS,
} from "./components/parking-scene-3d/ParkingScene3D";
export type {
  ParkingScene3DOptions,
  SceneColors,
  SpotBeacon,
} from "./components/parking-scene-3d/ParkingScene3D";
export {
  EXTERNAL_GROUP,
  PX_TO_M,
  cruiseRoutes,
  floorSize,
  matchesGroup,
  outlineToShape,
  overviewShot,
  pathLength,
  pointAlongPath,
  rectCenter,
  sceneState,
  spotPlacements,
  spotShot,
  toMeters,
} from "./components/parking-scene-3d/parking-scene-data";
export type {
  CameraShot,
  CarInstance,
  CarTone,
  CruiseRoute,
  ParkingSceneLayout,
  SceneOccupant,
  SceneRect,
  SceneState,
  SpotPlacement,
  SpotTone,
} from "./components/parking-scene-3d/parking-scene-data";
export { isWebglSupported } from "./lib/webgl";

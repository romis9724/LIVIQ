"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import ForceGraph3D, { type ForceGraphMethods, type NodeObject } from "react-force-graph-3d";
import * as THREE from "three";
import { EmptyState } from "@liviq/ui";
import type { GraphLink, GraphNode } from "@/lib/api";
import { isWebglSupported } from "@/lib/webgl";
import { STATUS_META } from "./data";
import {
  COMPLEX_COLOR_VAR,
  LINK_COLOR_VAR,
  LOCATION_COLOR_VAR,
  NODE_VAL_FOCUS_SCALE,
  centerByNodeId,
  groupCenters,
  lensGroupByNodeId,
  lensNodeColorVar,
  nodeBaseVal,
  type Coords,
  type GraphLens,
} from "./graph-data";

// 이 파일만 three.js(WebGL)를 다룬다 — FacilityGraphView 가 next/dynamic ssr:false 로만 로드해
// 타 라우트 번들에 새지 않게 한다(ADR-0019 전례 · ADR-0022 결정 4).

interface GraphDatum extends GraphNode {
  id: string;
}
type FgNode = NodeObject<GraphDatum>;
type FgMethods = ForceGraphMethods<GraphDatum, GraphLink>;

const CLUSTER_STRENGTH = 0.06; // 계통끼리 모으는 인력(너무 세면 링크 구조가 뭉개진다)
const FLY_TO_DISTANCE = 140;
const FLY_TO_MS = 900;
const FALLBACK_COLOR = "#69737d"; // CSS 변수 조회 실패 시 중립 회색(정상 경로에선 쓰이지 않음)
const LOCATION_LABEL_OFFSET_Y = 14; // 위치 노드 크기(NODE_VAL_LOCATION)에 맞춘 라벨 높이
const LOCATION_LABEL_SCALE = 0.06; // 캔버스 px → three 월드 단위 경험값

interface FacilityGraphCanvasProps {
  nodes: readonly GraphNode[];
  links: readonly GraphLink[];
  groups: readonly string[];
  lens: GraphLens;
  focus: { pgId: string; seq: number } | null; // seq — 같은 노드 재검색도 다시 날아가게
  onSelectNode: (node: GraphNode) => void;
}

/** CSS 변수 → 색 문자열. three 는 oklch 를 못 읽어 그래프 팔레트만 sRGB hex 로 정의돼 있다. */
function resolveColorVar(name: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || FALLBACK_COLOR;
}

/**
 * 계통 클러스터 포스 — 각 노드를 제 계통 중심으로 당긴다. 가상 허브 노드를 만들지 않는
 * 클러스터링 수단(ADR-0022 결정 2). d3-force 규약상 시뮬레이션 노드는 제자리에서 갱신한다.
 */
function clusterForce(centers: ReadonlyMap<string, Coords>, strength: number) {
  let simNodes: FgNode[] = [];
  const force = (alpha: number): void => {
    for (const node of simNodes) {
      const center = centers.get(String(node.id));
      if (!center) continue;
      const dx = center.x - (node.x ?? 0);
      const dy = center.y - (node.y ?? 0);
      const dz = center.z - (node.z ?? 0);
      // location·평면도 노드는 groupById 에 없어 center 도 없는 게 정상 경로다 — 그래도
      // 방어적으로 유한값만 반영한다(H13-7, 클러스터 힘이 NaN 을 만들지 않게 하는 가드).
      if (!Number.isFinite(dx) || !Number.isFinite(dy) || !Number.isFinite(dz)) continue;
      node.vx = (node.vx ?? 0) + dx * strength * alpha;
      node.vy = (node.vy ?? 0) + dy * strength * alpha;
      node.vz = (node.vz ?? 0) + dz * strength * alpha;
    }
  };
  force.initialize = (nodes: FgNode[]): void => {
    simNodes = nodes;
  };
  return force;
}

/**
 * 위치 노드 전용 텍스트 라벨 스프라이트(캔버스 텍스처) — 별도 라이브러리 없이 이미
 * 의존성인 three 만으로 만든다. nodeThreeObjectExtend 로 기본 구체 위에 덧붙인다(위치
 * 노드만 라벨 상시 표시, 설비는 hover 유지 — H13-7).
 */
function createLocationLabelSprite(name: string, color: string): THREE.Sprite {
  const fontSize = 42;
  const padding = 12;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d");
  const font = `700 ${fontSize}px sans-serif`;
  if (ctx) {
    ctx.font = font;
    const width = Math.ceil(ctx.measureText(name).width) + padding * 2;
    canvas.width = width;
    canvas.height = fontSize + padding * 2;
    // 캔버스 크기 변경은 컨텍스트를 리셋하므로 font 를 다시 설정해야 한다.
    ctx.font = font;
    ctx.fillStyle = color;
    ctx.textBaseline = "middle";
    ctx.textAlign = "center";
    ctx.fillText(name, canvas.width / 2, canvas.height / 2);
  }
  const texture = new THREE.CanvasTexture(canvas);
  const material = new THREE.SpriteMaterial({ map: texture, depthWrite: false, transparent: true });
  const sprite = new THREE.Sprite(material);
  sprite.scale.set(canvas.width * LOCATION_LABEL_SCALE, canvas.height * LOCATION_LABEL_SCALE, 1);
  sprite.position.set(0, LOCATION_LABEL_OFFSET_Y, 0);
  return sprite;
}

/** 컨테이너 실측 크기 — 지정하지 않으면 라이브러리가 window 크기로 그려 레이아웃을 넘는다. */
function useElementSize(): [React.RefObject<HTMLDivElement | null>, { w: number; h: number }] {
  const ref = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      if (!entry) return;
      setSize({ w: Math.round(entry.contentRect.width), h: Math.round(entry.contentRect.height) });
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, size];
}

/** 노드 툴팁 — 색만으로 상태를 전달하지 않도록 유형·상태를 텍스트로 병기한다(docs/05 §6). */
function nodeLabel(node: GraphDatum): string {
  const name = node.name ?? "(이름 없음)";
  if (node.label === "incident") {
    return `장애 · ${name} · ${node.resolved ? "조치됨" : "미해결"}`;
  }
  if (node.label === "maintenance") return `정비 · ${name}`;
  if (node.label === "location") return `위치 · ${name}`;
  if (node.label === "floor_plan") return `평면도 · ${name}`;
  if (node.label === "plan_room") return `방 · ${name}`;
  if (node.label === "plan_kind") return `종류 · ${name}`;
  if (node.label === "plan_device") return `마커 · ${name}`;
  if (node.label === "complex") return `단지 · ${name}`;
  const status = node.status ? STATUS_META[node.status as keyof typeof STATUS_META] : undefined;
  return `설비 · ${name} · ${status?.label ?? node.status ?? "상태 미상"}`;
}

export function FacilityGraphCanvas({
  nodes,
  links,
  groups,
  lens,
  focus,
  onSelectNode,
}: FacilityGraphCanvasProps) {
  const [stageRef, size] = useElementSize();
  const fgRef = useRef<FgMethods | undefined>(undefined);
  const supported = useMemo(isWebglSupported, []);

  // d3 시뮬레이션이 노드·링크 객체를 제자리에서 갱신하므로 배열 정체성을 고정한다
  // (렌더마다 새로 만들면 레이아웃이 매번 초기화된다).
  const graphData = useMemo(
    () => ({
      nodes: nodes.map((node): FgNode => ({ ...node, id: node.pgId })),
      links: links.map((link) => ({ ...link })),
    }),
    [nodes, links],
  );

  const groupById = useMemo(() => lensGroupByNodeId(lens, nodes, links), [lens, nodes, links]);
  const centers = useMemo(
    () => centerByNodeId(groupById, groupCenters(groups)),
    [groupById, groups],
  );

  // CSS 변수 → hex 캐시. 노드마다 getComputedStyle 을 부르지 않도록 한 번만 해석한다.
  const colors = useMemo(() => {
    if (!supported) return new Map<string, string>();
    const cache = new Map<string, string>();
    for (const node of nodes) {
      const name = lensNodeColorVar(lens, node, groupById, groups);
      if (!cache.has(name)) cache.set(name, resolveColorVar(name));
    }
    cache.set(LINK_COLOR_VAR, resolveColorVar(LINK_COLOR_VAR));
    return cache;
  }, [nodes, lens, groupById, groups, supported]);

  const colorById = useMemo(() => {
    const byId = new Map<string, string>();
    for (const node of nodes) {
      byId.set(
        node.pgId,
        colors.get(lensNodeColorVar(lens, node, groupById, groups)) ?? FALLBACK_COLOR,
      );
    }
    return byId;
  }, [nodes, colors, lens, groupById, groups]);

  // 위치·단지 노드 라벨 색 — 렌즈와 무관하게 고정(라벨은 그래프 데이터 변경 시에만 다시
  // 만들어져 렌즈 전환마다 갱신되지 않는다). 색 매칭보다 가독성이 우선이라 중립색으로 고정한다.
  const locationLabelColor = useMemo(
    () => (supported ? resolveColorVar(LOCATION_COLOR_VAR) : FALLBACK_COLOR),
    [supported],
  );
  const complexLabelColor = useMemo(
    () => (supported ? resolveColorVar(COMPLEX_COLOR_VAR) : FALLBACK_COLOR),
    [supported],
  );

  useEffect(() => {
    const fg = fgRef.current;
    if (!fg) return;
    fg.d3Force("cluster", clusterForce(centers, CLUSTER_STRENGTH));
    fg.d3ReheatSimulation();
  }, [centers]);

  // 검색 → 카메라 fly-to. prefers-reduced-motion 이면 트랜지션 없이 즉시 이동(docs/05 §5).
  useEffect(() => {
    const fg = fgRef.current;
    if (!focus || !fg) return;
    const node = graphData.nodes.find((n) => n.id === focus.pgId);
    if (!node || node.x === undefined) return;
    const [x, y, z] = [node.x, node.y ?? 0, node.z ?? 0];
    const magnitude = Math.hypot(x, y, z);
    const target: Coords =
      magnitude === 0
        ? { x: 0, y: 0, z: FLY_TO_DISTANCE }
        : (() => {
            const ratio = 1 + FLY_TO_DISTANCE / magnitude;
            return { x: x * ratio, y: y * ratio, z: z * ratio };
          })();
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    fg.cameraPosition(target, { x, y, z }, reduced ? 0 : FLY_TO_MS);
  }, [focus, graphData]);

  if (!supported) {
    return (
      <div className="fac-graph__empty">
        <EmptyState
          icon="🖥"
          title="3D 그래프를 표시할 수 없습니다"
          description="이 브라우저·기기에서 WebGL을 사용할 수 없습니다. 위의 ‘목록’ 보기로 같은 시설 정보를 확인할 수 있습니다."
        />
      </div>
    );
  }

  return (
    <div className="fac-graph__canvas" ref={stageRef}>
      {size.w > 0 ? (
        <ForceGraph3D<GraphDatum, GraphLink>
          ref={fgRef}
          width={size.w}
          height={size.h}
          graphData={graphData}
          backgroundColor="rgba(0,0,0,0)"
          showNavInfo={false}
          nodeLabel={nodeLabel}
          nodeVal={(node) => {
            const base = nodeBaseVal(node.label);
            return node.id === focus?.pgId ? base * NODE_VAL_FOCUS_SCALE : base;
          }}
          nodeColor={(node) => colorById.get(node.pgId) ?? FALLBACK_COLOR}
          nodeOpacity={0.92}
          // react-force-graph-3d 의 타입 선언은 null 반환을 허용하지 않지만(타입 누락 —
          // 실제로는 null 이면 기본 노드만 그린다) 런타임 동작은 문서화된 대로다.
          // 단지 노드도 위치와 같은 스프라이트 로직을 재사용해 상시 라벨을 붙인다(H13-7 확장).
          nodeThreeObject={
            ((node: FgNode) => {
              if (node.label === "location") {
                return createLocationLabelSprite(node.name ?? "(이름 없음)", locationLabelColor);
              }
              if (node.label === "complex") {
                return createLocationLabelSprite(node.name ?? "(이름 없음)", complexLabelColor);
              }
              return null;
            }) as (node: FgNode) => THREE.Object3D
          }
          nodeThreeObjectExtend={(node) => node.label === "location" || node.label === "complex"}
          linkColor={() => colors.get(LINK_COLOR_VAR) ?? FALLBACK_COLOR}
          linkOpacity={0.5}
          linkWidth={0.6}
          onNodeClick={(node) => onSelectNode(node)}
        />
      ) : null}
    </div>
  );
}

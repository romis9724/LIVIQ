"use client";

import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@liviq/ui";
import type { ToastTone } from "@liviq/ui";
import {
  ApiError,
  linkInquiryFacility,
  linkInquiryFacilityByCode,
  listFacilities,
  suggestInquiryFacility,
  type Facility,
  type FacilitySuggestCandidate,
  type Inquiry,
} from "@/lib/api";

// 민원-시설 연결(H13-2, ADR-0022 결정 3) — ①담당자 지정=정식 ②AI 추천은 후보 제시까지만,
// 승인 클릭(handleLink)이 있어야 PUT 이 나간다(규칙 8 — LLM 출력이 부수효과를 직접 트리거하지 않음).
// MANAGER 전용 — 노출 여부는 호출부(InquiryAdmin)가 가드, 서버가 최종 강제.

function errorMessage(err: unknown): string {
  if (err instanceof ApiError || err instanceof Error) return err.message;
  return "알 수 없는 오류가 발생했습니다.";
}

interface InquiryFacilityLinkProps {
  inquiry: Inquiry;
  onUpdated: (updated: Inquiry) => void;
  showToast: (message: string, tone?: ToastTone) => void;
}

export function InquiryFacilityLink({ inquiry, onUpdated, showToast }: InquiryFacilityLinkProps) {
  const [facilities, setFacilities] = useState<Facility[]>([]);
  const [facilitiesError, setFacilitiesError] = useState<string | null>(null);
  const [pickedId, setPickedId] = useState("");
  const [codeInput, setCodeInput] = useState(""); // 영숫자 코드라 controlled 로 둬도 IME 문제 없다
  const [codeError, setCodeError] = useState<string | null>(null);
  const [linking, setLinking] = useState(false);
  const [suggesting, setSuggesting] = useState(false);
  const [suggestError, setSuggestError] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<FacilitySuggestCandidate[] | null>(null);

  useEffect(() => {
    let alive = true;
    // ponytail: 서버 기본 limit 20 — 설비 37건이 잘린다. 100+ 되면 검색형 선택으로 교체.
    void listFacilities({ limit: 100 })
      .then((items) => {
        if (alive) setFacilities(items);
      })
      .catch((err: unknown) => {
        if (alive) setFacilitiesError(errorMessage(err));
      });
    return () => {
      alive = false;
    };
  }, []);

  async function handleLink(facilityId: string | null) {
    setLinking(true);
    try {
      onUpdated(await linkInquiryFacility(inquiry.id, facilityId));
      setCandidates(null);
      setPickedId("");
      showToast(facilityId ? "설비를 연결했습니다." : "설비 연결을 해제했습니다.");
    } catch (err) {
      showToast(errorMessage(err), "danger");
    } finally {
      setLinking(false);
    }
  }

  /** 코드번호 직접 연결(H14-2) — 목록에서 고르지 않고 접수 화면에서 바로 잇는 경로. */
  async function handleLinkByCode(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code = codeInput.trim();
    if (!code) return;
    setLinking(true);
    setCodeError(null);
    try {
      onUpdated(await linkInquiryFacilityByCode(inquiry.id, code));
      setCandidates(null);
      setCodeInput("");
      showToast("설비를 연결했습니다.");
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setCodeError(`‘${code}’ 코드의 설비가 이 단지에 없습니다.`);
      } else {
        setCodeError(errorMessage(err));
      }
    } finally {
      setLinking(false);
    }
  }

  async function handleSuggest() {
    setSuggesting(true);
    setSuggestError(null);
    try {
      setCandidates(await suggestInquiryFacility(inquiry.id));
    } catch (err) {
      setCandidates(null);
      setSuggestError(errorMessage(err));
    } finally {
      setSuggesting(false);
    }
  }

  return (
    <section className="ia-facility">
      <div className="ia-control__label">연결 설비</div>

      <div className="ia-facility__current">
        {inquiry.facilityName ? (
          <>
            <span className="ia-facility__current-name">{inquiry.facilityName}</span>
            <Button variant="secondary" disabled={linking} onClick={() => void handleLink(null)}>
              연결 해제
            </Button>
          </>
        ) : (
          <span className="ia-facility__empty">연결된 설비가 없습니다.</span>
        )}
      </div>

      <div className="ia-facility__pick">
        <select
          className="ia-select"
          aria-label="연결할 설비 선택"
          disabled={linking || facilities.length === 0}
          value={pickedId}
          onChange={(e) => setPickedId(e.target.value)}
        >
          <option value="">설비 선택</option>
          {facilities.map((f) => (
            <option key={f.id} value={f.id}>
              {f.code ? `${f.code} · ${f.name}` : f.name}
            </option>
          ))}
        </select>
        <Button
          variant="secondary"
          disabled={linking || !pickedId}
          onClick={() => void handleLink(pickedId)}
        >
          연결
        </Button>
        <Button variant="secondary" disabled={suggesting} onClick={() => void handleSuggest()}>
          {suggesting ? "추천 중…" : "AI 추천"}
        </Button>
      </div>
      {facilitiesError ? <p className="ia-facility__suggest-error">{facilitiesError}</p> : null}

      <form className="ia-facility__pick" onSubmit={(e) => void handleLinkByCode(e)}>
        <label className="sr-only" htmlFor={`ia-facility-code-${inquiry.id}`}>
          설비 코드번호로 연결
        </label>
        <input
          id={`ia-facility-code-${inquiry.id}`}
          className="ia-facility__code"
          type="text"
          autoComplete="off"
          placeholder="코드번호 (예: EL-401-01)"
          value={codeInput}
          disabled={linking}
          onChange={(e) => {
            setCodeInput(e.target.value);
            setCodeError(null);
          }}
        />
        <Button type="submit" variant="secondary" disabled={linking || !codeInput.trim()}>
          코드로 연결
        </Button>
      </form>
      {codeError ? <p className="ia-facility__suggest-error">{codeError}</p> : null}

      {suggestError ? <p className="ia-facility__suggest-error">{suggestError}</p> : null}
      {candidates && candidates.length === 0 ? (
        <p className="ia-facility__empty">추천할 후보를 찾지 못했습니다.</p>
      ) : null}
      {candidates && candidates.length > 0 ? (
        <ul className="ia-facility__candidates">
          {candidates.map((candidate) => (
            <li key={candidate.facilityId} className="ia-facility__candidate">
              <div>
                <div className="ia-facility__candidate-name">{candidate.name}</div>
                <p className="ia-facility__candidate-reason">{candidate.reason}</p>
              </div>
              <Button
                variant="secondary"
                disabled={linking}
                onClick={() => void handleLink(candidate.facilityId)}
              >
                이 설비로 연결
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

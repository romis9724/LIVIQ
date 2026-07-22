"use client";

import { useState } from "react";
import { Button } from "@liviq/ui";
import type { CodeGroup, CreateCodeGroupInput } from "@/lib/api";
import { validateGroupKey } from "./data";

interface GroupPanelProps {
  groups: readonly CodeGroup[];
  selectedId: string | null;
  busy: boolean;
  onSelect: (id: string) => void;
  onCreate: (input: CreateCodeGroupInput) => Promise<boolean>;
}

/** 좌측 — 코드 그룹 목록 + 그룹 추가 폼. 선택 상태는 상위가 소유. */
export function GroupPanel({ groups, selectedId, busy, onSelect, onCreate }: GroupPanelProps) {
  const [adding, setAdding] = useState(false);

  return (
    <section className="surface-card codes-groups" aria-labelledby="codes-groups-h">
      <div className="codes-groups__head">
        <h2 id="codes-groups-h" className="codes-panel__title">
          코드 그룹
        </h2>
        <Button
          variant={adding ? "ghost" : "secondary"}
          size="sm"
          onClick={() => setAdding((v) => !v)}
        >
          {adding ? "닫기" : "그룹 추가"}
        </Button>
      </div>

      {adding ? (
        <GroupCreateForm
          busy={busy}
          onSubmit={async (input) => {
            const ok = await onCreate(input);
            if (ok) setAdding(false);
            return ok;
          }}
        />
      ) : null}

      {groups.length === 0 ? (
        <p className="codes-empty">
          아직 코드 그룹이 없습니다. 위의 &lsquo;그룹 추가&rsquo;로 첫 그룹을 만드세요.
        </p>
      ) : (
        <ul className="codes-groups__list">
          {groups.map((group) => (
            <li key={group.id}>
              <button
                type="button"
                className="codes-groups__item"
                data-active={group.id === selectedId || undefined}
                aria-current={group.id === selectedId}
                onClick={() => onSelect(group.id)}
              >
                <span className="codes-groups__name">
                  {group.name}
                  {group.isSystem ? (
                    <span className="codes-lock" title="시스템 그룹">
                      🔒
                    </span>
                  ) : null}
                </span>
                <span className="codes-groups__meta">
                  <code className="codes-key">{group.groupKey}</code>
                  <span className="codes-groups__count">{group.codes.length}개 코드</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function GroupCreateForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (input: CreateCodeGroupInput) => Promise<boolean>;
}) {
  const [groupKey, setGroupKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const keyError = validateGroupKey(groupKey);
    if (keyError) {
      setError(keyError);
      return;
    }
    if (!name.trim()) {
      setError("그룹 이름을 입력하세요.");
      return;
    }
    setError(null);
    const ok = await onSubmit({
      groupKey: groupKey.trim(),
      name: name.trim(),
      description: description.trim() || undefined,
    });
    if (ok) {
      setGroupKey("");
      setName("");
      setDescription("");
    }
  }

  return (
    <form className="codes-form" onSubmit={submit}>
      <label className="codes-field">
        <span className="codes-field__label">
          그룹 키 <span aria-hidden="true">*</span>
        </span>
        <input
          className="codes-field__input codes-field__input--mono"
          value={groupKey}
          onChange={(e) => setGroupKey(e.target.value.toUpperCase())}
          placeholder="예: FEE_KIND"
          aria-required="true"
          autoComplete="off"
        />
        <span className="codes-field__hint">대문자·숫자·언더스코어. 생성 후에는 바꿀 수 없습니다.</span>
      </label>
      <label className="codes-field">
        <span className="codes-field__label">
          그룹 이름 <span aria-hidden="true">*</span>
        </span>
        <input
          className="codes-field__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="예: 관리비 항목"
          aria-required="true"
        />
      </label>
      <label className="codes-field">
        <span className="codes-field__label">설명</span>
        <input
          className="codes-field__input"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="이 그룹의 용도(선택)"
        />
      </label>
      {error ? (
        <p className="codes-field__error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="codes-form__actions">
        <Button type="submit" variant="primary" size="sm" disabled={busy}>
          그룹 만들기
        </Button>
      </div>
    </form>
  );
}

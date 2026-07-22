"use client";

import { useState } from "react";
import { Button, EmptyState, Switch } from "@liviq/ui";
import type {
  Code,
  CodeGroup,
  CreateCodeInput,
  UpdateCodeGroupInput,
  UpdateCodeInput,
} from "@/lib/api";
import { buildCodeTree, validateCodeValue, validateLabel } from "./data";

interface CodePanelProps {
  group: CodeGroup | null;
  busy: boolean;
  onUpdateGroup: (id: string, input: UpdateCodeGroupInput) => Promise<boolean>;
  onDeleteGroup: (group: CodeGroup) => void;
  onCreateCode: (input: CreateCodeInput) => Promise<boolean>;
  onUpdateCode: (id: string, input: UpdateCodeInput) => Promise<boolean>;
  onDeleteCode: (code: Code) => void;
}

/** 우측 — 선택 그룹 헤더(수정·삭제) + 계층 코드 트리. */
export function CodePanel({
  group,
  busy,
  onUpdateGroup,
  onDeleteGroup,
  onCreateCode,
  onUpdateCode,
  onDeleteCode,
}: CodePanelProps) {
  const [editingGroup, setEditingGroup] = useState(false);
  const [addingCode, setAddingCode] = useState(false);

  if (!group) {
    return (
      <section className="surface-card codes-detail" aria-labelledby="codes-detail-h">
        <h2 id="codes-detail-h" className="codes-panel__title codes-panel__title--sr">
          코드
        </h2>
        <EmptyState
          icon="⚙️"
          title="그룹을 선택하세요"
          description="왼쪽에서 코드 그룹을 고르면 그 안의 코드를 여기서 관리합니다."
        />
      </section>
    );
  }

  const tree = buildCodeTree(group.codes);
  const rootCodes = group.codes.filter((c) => c.parentId === null);

  return (
    <section className="surface-card codes-detail" aria-labelledby="codes-detail-h">
      <div className="codes-detail__head">
        <div className="codes-detail__heading">
          <h2 id="codes-detail-h" className="codes-panel__title">
            {group.name}
            {group.isSystem ? (
              <span className="codes-lock" title="시스템 그룹">
                🔒
              </span>
            ) : null}
          </h2>
          <code className="codes-key">{group.groupKey}</code>
          {group.description ? <p className="codes-detail__desc">{group.description}</p> : null}
        </div>
        <div className="codes-detail__actions">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditingGroup((v) => !v)}
          >
            {editingGroup ? "닫기" : "그룹 수정"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="codes-danger-btn"
            disabled={group.isSystem || busy}
            onClick={() => onDeleteGroup(group)}
          >
            그룹 삭제
          </Button>
        </div>
      </div>

      {group.isSystem ? (
        <p className="codes-note" role="note">
          🔒 시스템 그룹입니다. 그룹 삭제와 키 변경은 잠겨 있으며, 이름·설명과 하위 코드만 수정할 수
          있습니다.
        </p>
      ) : null}

      {editingGroup ? (
        <GroupEditForm
          group={group}
          busy={busy}
          onSubmit={async (input) => {
            const ok = await onUpdateGroup(group.id, input);
            if (ok) setEditingGroup(false);
            return ok;
          }}
        />
      ) : null}

      <div className="codes-detail__codes">
        <div className="codes-detail__codes-head">
          <h3 className="codes-subtitle">코드</h3>
          <Button
            variant={addingCode ? "ghost" : "secondary"}
            size="sm"
            onClick={() => setAddingCode((v) => !v)}
          >
            {addingCode ? "닫기" : "코드 추가"}
          </Button>
        </div>

        {addingCode ? (
          <CodeCreateForm
            groupId={group.id}
            parents={rootCodes}
            busy={busy}
            onSubmit={async (input) => {
              const ok = await onCreateCode(input);
              if (ok) setAddingCode(false);
              return ok;
            }}
          />
        ) : null}

        {tree.length === 0 ? (
          <p className="codes-empty">
            아직 코드가 없습니다. &lsquo;코드 추가&rsquo;로 첫 항목을 만드세요.
          </p>
        ) : (
          <ul className="codes-tree">
            {tree.map((node) => (
              <li key={node.id}>
                <CodeRow
                  code={node}
                  busy={busy}
                  onUpdateCode={onUpdateCode}
                  onDeleteCode={onDeleteCode}
                />
                {node.children.length > 0 ? (
                  <ul className="codes-tree codes-tree--child">
                    {node.children.map((child) => (
                      <li key={child.id}>
                        <CodeRow
                          code={child}
                          busy={busy}
                          onUpdateCode={onUpdateCode}
                          onDeleteCode={onDeleteCode}
                        />
                      </li>
                    ))}
                  </ul>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function CodeRow({
  code,
  busy,
  onUpdateCode,
  onDeleteCode,
}: {
  code: Code;
  busy: boolean;
  onUpdateCode: (id: string, input: UpdateCodeInput) => Promise<boolean>;
  onDeleteCode: (code: Code) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [label, setLabel] = useState(code.label);
  const [sortOrder, setSortOrder] = useState(String(code.sortOrder));
  const [error, setError] = useState<string | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const labelError = validateLabel(label);
    if (labelError) {
      setError(labelError);
      return;
    }
    setError(null);
    const ok = await onUpdateCode(code.id, {
      label: label.trim(),
      sortOrder: Number.parseInt(sortOrder, 10) || 0,
    });
    if (ok) setEditing(false);
  }

  if (editing) {
    return (
      <form className="codes-form codes-form--row" onSubmit={save}>
        <label className="codes-field codes-field--grow">
          <span className="codes-field__label">표시 이름</span>
          <input
            className="codes-field__input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            aria-required="true"
          />
        </label>
        <label className="codes-field codes-field--sort">
          <span className="codes-field__label">정렬</span>
          <input
            className="codes-field__input"
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
            inputMode="numeric"
          />
        </label>
        {error ? (
          <p className="codes-field__error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="codes-form__actions">
          <Button type="button" variant="ghost" size="sm" onClick={() => setEditing(false)}>
            취소
          </Button>
          <Button type="submit" variant="primary" size="sm" disabled={busy}>
            저장
          </Button>
        </div>
      </form>
    );
  }

  return (
    <div className="codes-row" data-inactive={!code.active || undefined}>
      <span className="codes-row__label">
        {code.label}
        {!code.active ? <span className="codes-row__badge">비활성</span> : null}
      </span>
      <code className="codes-key codes-row__code">{code.code}</code>
      <div className="codes-row__actions">
        <Switch
          checked={code.active}
          label={`${code.label} 활성화`}
          onChange={(next) => void onUpdateCode(code.id, { active: next })}
        />
        <Button variant="ghost" size="sm" onClick={() => setEditing(true)}>
          수정
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="codes-danger-btn"
          disabled={busy}
          onClick={() => onDeleteCode(code)}
        >
          삭제
        </Button>
      </div>
    </div>
  );
}

function GroupEditForm({
  group,
  busy,
  onSubmit,
}: {
  group: CodeGroup;
  busy: boolean;
  onSubmit: (input: UpdateCodeGroupInput) => Promise<boolean>;
}) {
  const [name, setName] = useState(group.name);
  const [description, setDescription] = useState(group.description ?? "");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!name.trim()) {
      setError("그룹 이름을 입력하세요.");
      return;
    }
    setError(null);
    await onSubmit({ name: name.trim(), description: description.trim() || null });
  }

  return (
    <form className="codes-form" onSubmit={submit}>
      <label className="codes-field">
        <span className="codes-field__label">그룹 이름</span>
        <input
          className="codes-field__input"
          value={name}
          onChange={(e) => setName(e.target.value)}
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
          저장
        </Button>
      </div>
    </form>
  );
}

function CodeCreateForm({
  groupId,
  parents,
  busy,
  onSubmit,
}: {
  groupId: string;
  parents: readonly Code[];
  busy: boolean;
  onSubmit: (input: CreateCodeInput) => Promise<boolean>;
}) {
  const [code, setCode] = useState("");
  const [label, setLabel] = useState("");
  const [parentId, setParentId] = useState("");
  const [sortOrder, setSortOrder] = useState("0");
  const [error, setError] = useState<string | null>(null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const codeError = validateCodeValue(code) ?? validateLabel(label);
    if (codeError) {
      setError(codeError);
      return;
    }
    setError(null);
    const ok = await onSubmit({
      groupId,
      code: code.trim(),
      label: label.trim(),
      parentId: parentId || null,
      sortOrder: Number.parseInt(sortOrder, 10) || 0,
    });
    if (ok) {
      setCode("");
      setLabel("");
      setParentId("");
      setSortOrder("0");
    }
  }

  return (
    <form className="codes-form" onSubmit={submit}>
      <div className="codes-form__grid">
        <label className="codes-field">
          <span className="codes-field__label">
            코드 값 <span aria-hidden="true">*</span>
          </span>
          <input
            className="codes-field__input codes-field__input--mono"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="예: WATER"
            aria-required="true"
            autoComplete="off"
          />
        </label>
        <label className="codes-field">
          <span className="codes-field__label">
            표시 이름 <span aria-hidden="true">*</span>
          </span>
          <input
            className="codes-field__input"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="예: 수도료"
            aria-required="true"
          />
        </label>
        <label className="codes-field">
          <span className="codes-field__label">상위 코드</span>
          <select
            className="codes-field__input"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
          >
            <option value="">없음 (최상위)</option>
            {parents.map((parent) => (
              <option key={parent.id} value={parent.id}>
                {parent.label} ({parent.code})
              </option>
            ))}
          </select>
        </label>
        <label className="codes-field codes-field--sort">
          <span className="codes-field__label">정렬</span>
          <input
            className="codes-field__input"
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
            inputMode="numeric"
          />
        </label>
      </div>
      {error ? (
        <p className="codes-field__error" role="alert">
          {error}
        </p>
      ) : null}
      <div className="codes-form__actions">
        <Button type="submit" variant="primary" size="sm" disabled={busy}>
          코드 추가
        </Button>
      </div>
    </form>
  );
}

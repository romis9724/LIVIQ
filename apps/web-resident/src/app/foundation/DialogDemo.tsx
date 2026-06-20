"use client";

import { useState } from "react";
import { Button, Dialog, Toast } from "@liviq/ui";

/** 발송 확인 다이얼로그 + 성공 토스트 상호작용 데모. */
export function DialogDemo() {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState(false);

  return (
    <div className="fnd-stack">
      <Button
        variant="primary"
        onClick={() => {
          setSent(false);
          setOpen(true);
        }}
      >
        공지 발송 열기
      </Button>

      <Dialog
        open={open}
        title="공지를 발송할까요?"
        description="대상 1,204세대 · 검수 완료. 발송 후에는 수정할 수 없습니다."
        confirmLabel="발송 확인"
        onCancel={() => setOpen(false)}
        onConfirm={() => {
          setOpen(false);
          setSent(true);
        }}
      />

      {sent ? <Toast tone="success" message="공지가 12345동 입주민에게 발송되었습니다." /> : null}
    </div>
  );
}

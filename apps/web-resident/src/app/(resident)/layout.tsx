import type { ReactNode } from "react";
import { ResidentShell } from "@/components/resident-shell/ResidentShell";

export default function ResidentLayout({ children }: { children: ReactNode }) {
  return <ResidentShell>{children}</ResidentShell>;
}

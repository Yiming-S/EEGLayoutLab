"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useLanguage } from "@/components/language-provider";
import type { ElectrodeDesign } from "@/lib/design-decision";
import { saveStudyHandoff } from "./robustness-draft";

export function CoordinateStudyLink({ design }: { design: ElectrodeDesign }) {
  const { tx } = useLanguage(),
    [error, setError] = useState("");
  return (
    <div className="space-y-2">
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          try {
            saveStudyHandoff(window.sessionStorage, design);
            window.location.assign("/robustness?draft=1");
          } catch (caught) {
            setError(caught instanceof Error ? caught.message : "研究坐标草稿无法保存");
          }
        }}
      >
        {tx("用此坐标创建稳健性研究")}
      </Button>
      {error && (
        <p role="alert" className="text-sm text-red-800">
          {tx(error)}
        </p>
      )}
    </div>
  );
}

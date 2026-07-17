"use client";

import { ErrorBlock } from "@/components/primitives";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="space-y-4 py-10">
      <h1 className="sr-only">Ошибка</h1>
      <ErrorBlock message="Произошла непредвиденная ошибка при отображении страницы." />
      <div className="text-center">
        <button type="button" onClick={reset} className="btn-ghost">
          Повторить
        </button>
      </div>
    </div>
  );
}

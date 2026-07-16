import { Check } from "lucide-react";

const STEPS = [
  { id: "0", label: "Ingestion", caption: "Разбор документов" },
  { id: "0.5", label: "Curated v1", caption: "Датасет с провенансом" },
  { id: "P1", label: "Целостность", caption: "Структура пакета" },
  { id: "P2", label: "Соответствие", caption: "Демо-корпус" },
  { id: "P3", label: "Согласованность", caption: "Числовые проверки" },
  { id: "P4", label: "Междокументная", caption: "Граф сущностей" },
  { id: "META", label: "Приоритет", caption: "Итог P1–P4" },
];

export function PipelineSteps({
  metaAvailable,
  statusError = false,
}: {
  metaAvailable: boolean | null;
  statusError?: boolean;
}) {
  return (
    <div className="card p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Конвейер анализа
      </p>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STEPS.map((step) => {
          const isMeta = step.id === "META";
          const complete = !isMeta || metaAvailable === true;
          const accessibleStatus = complete
            ? "Завершено"
            : metaAvailable === false
              ? "Недоступно"
              : "Статус не определён";
          const caption = isMeta
            ? metaAvailable === null
              ? statusError
                ? "Статус не получен"
                : "Проверка статуса"
              : metaAvailable
                ? step.caption
                : "Артефакты недоступны"
            : step.caption;
          return (
            <li key={step.id} className="min-w-0">
              <div
                className={`flex h-full items-start gap-3 rounded-lg border p-3 ${
                  complete
                    ? "border-slate-200 bg-white"
                    : "border-dashed border-slate-300 bg-slate-50"
                }`}
              >
                <span
                  className={`flex h-6 w-6 flex-none items-center justify-center rounded-full text-white ${
                    complete ? "bg-accent-600" : "bg-slate-300"
                  }`}
                >
                  {complete ? (
                    <Check className="h-3.5 w-3.5" aria-hidden />
                  ) : (
                    <span aria-hidden>…</span>
                  )}
                  <span className="sr-only">{accessibleStatus}</span>
                </span>
                <div className="min-w-0">
                  <p
                    className={`text-[11px] font-semibold uppercase tracking-wide ${
                      complete ? "text-accent-700" : "text-slate-400"
                    }`}
                  >
                    {step.id}
                  </p>
                  <p
                    className={`text-sm font-medium ${
                      complete ? "text-slate-800" : "text-slate-500"
                    }`}
                  >
                    {step.label}
                  </p>
                  <p className={complete ? "text-xs text-slate-500" : "text-xs text-slate-400"}>
                    {caption}
                  </p>
                </div>
              </div>
            </li>
          );
        })}
        <li className="min-w-0">
          <div className="flex h-full items-start gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
            <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-slate-300 text-white">
              <span aria-hidden>…</span>
              <span className="sr-only">Запланировано</span>
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                P5 · P6
              </p>
              <p className="text-sm font-medium text-slate-500">Гео и карты</p>
              <p className="text-xs text-slate-400">Следующий этап</p>
            </div>
          </div>
        </li>
      </ol>
    </div>
  );
}

import { Check } from "lucide-react";

const STEPS = [
  { id: "0", label: "Ingestion", caption: "Разбор документов" },
  { id: "0.5", label: "Curated v1", caption: "Датасет с провенансом" },
  { id: "P1", label: "Целостность", caption: "Структура пакета" },
  { id: "P3", label: "Согласованность", caption: "Числовые проверки" },
  { id: "P2", label: "Соответствие", caption: "Демо-корпус" },
];

export function PipelineSteps() {
  return (
    <div className="card p-5">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
        Конвейер анализа
      </p>
      <ol className="mt-4 flex flex-col gap-3 md:flex-row md:items-stretch md:gap-2">
        {STEPS.map((step, i) => (
          <li key={step.id} className="flex flex-1 items-center gap-2">
            <div className="flex flex-1 items-start gap-3 rounded-lg border border-slate-200 bg-white p-3">
              <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-accent-600 text-white">
                <Check className="h-3.5 w-3.5" aria-hidden />
              </span>
              <div className="min-w-0">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-accent-700">
                  {step.id}
                </p>
                <p className="text-sm font-medium text-slate-800">{step.label}</p>
                <p className="text-xs text-slate-500">{step.caption}</p>
              </div>
            </div>
            {i < STEPS.length - 1 ? (
              <span className="hidden text-slate-300 md:inline" aria-hidden>
                →
              </span>
            ) : null}
          </li>
        ))}
        <li className="flex flex-1 items-center gap-2">
          <div className="flex flex-1 items-start gap-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 p-3">
            <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-slate-300 text-white">
              …
            </span>
            <div className="min-w-0">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                P4 · Meta
              </p>
              <p className="text-sm font-medium text-slate-500">Интегральный риск</p>
              <p className="text-xs text-slate-400">Следующий этап</p>
            </div>
          </div>
        </li>
      </ol>
    </div>
  );
}
